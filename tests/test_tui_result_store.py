from __future__ import annotations

import errno
import json
import multiprocessing
import os
import stat
import threading
from dataclasses import fields, replace
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from pathlib import Path
from types import MethodType

import pytest

from csvql import tui_result_store
from csvql.bounded_result import BoundedQueryResult, PreviewPolicy
from csvql.result_codec import encode_row_payload
from csvql.tui_result_store import (
    TUI_RESULT_LEASE_NAME,
    TUI_RESULT_MARKER_NAME,
    TUI_RESULT_SESSION_PREFIX,
    TUIResultCleanupSummary,
    TUIResultHandle,
    TUIResultStorageError,
    TUIResultStore,
    _PlatformLease,
)


def _commit(
    store: TUIResultStore,
    *,
    sequence: int = 1,
    columns: tuple[str, ...] = ("value",),
    rows: tuple[tuple[object, ...], ...] = (("alpha",),),
    elapsed_ms: float = 1.0,
):
    writer = store.begin_complete(sequence=sequence, columns=columns)
    for row in rows:
        writer.append_payload(encode_row_payload(row))
    return writer.commit(elapsed_ms=elapsed_ms)


def _preview(
    rows: tuple[tuple[object, ...], ...] = (("alpha",),),
) -> BoundedQueryResult:
    payloads = tuple(encode_row_payload(row) for row in rows)
    return BoundedQueryResult(
        columns=("value",),
        rows=rows,
        elapsed_ms=1.0,
        preview_payload_bytes=sum(len(payload) for payload in payloads),
        has_more_rows=True,
        truncation_reason="row_limit",
    )


def _probe_platform_lease(path: Path, connection: Connection) -> None:
    lease = _PlatformLease.open(path)
    try:
        connection.send(lease.acquire_nonblocking())
    finally:
        lease.close()
        connection.close()


def _acquire_lease_in_spawned_process(path: Path) -> bool:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_probe_platform_lease, args=(path, sender))
    process.start()
    sender.close()
    try:
        if not receiver.poll(5.0):
            raise AssertionError("lease probe did not respond within five seconds")
        acquired = receiver.recv()
    finally:
        receiver.close()
        process.join(timeout=5.0)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5.0)
    if process.exitcode != 0:
        raise AssertionError(f"lease probe exited with code {process.exitcode}")
    if not isinstance(acquired, bool):
        raise AssertionError("lease probe returned a non-boolean result")
    return acquired


def test_handle_exposes_only_opaque_registry_identity() -> None:
    assert tuple(field.name for field in fields(TUIResultHandle)) == (
        "sequence",
        "store_id",
        "nonce",
    )


@pytest.mark.parametrize(
    "artifact_name",
    [
        "query-1.result",
        "preview-2.result",
        f".query-3-{'b' * 16}.result.tmp",
        f".preview-4-{'c' * 16}.result.tmp",
    ],
)
def test_private_result_artifact_recognition_requires_exact_workspace_and_filename(
    tmp_path: Path,
    artifact_name: str,
) -> None:
    workspace = tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{'a' * 32}"

    assert tui_result_store._is_private_tui_result_artifact(workspace / artifact_name)
    assert not tui_result_store._is_private_tui_result_artifact(tmp_path / artifact_name)
    assert not tui_result_store._is_private_tui_result_artifact(workspace / "query-01.result")
    assert not tui_result_store._is_private_tui_result_artifact(
        tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{'A' * 32}" / artifact_name
    )


def test_private_result_artifact_recognition_follows_resolvable_symlink_alias(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{'a' * 32}"
    workspace.mkdir()
    artifact = workspace / "query-1.result"
    artifact.write_bytes(b"result")
    alias = tmp_path / "result-alias"
    alias.symlink_to(artifact)

    assert tui_result_store._is_private_tui_result_artifact(alias)


def test_private_result_artifact_recognition_ignores_unresolvable_symlink_alias(
    tmp_path: Path,
) -> None:
    alias = tmp_path / "result-alias"
    alias.symlink_to(alias)

    assert not tui_result_store._is_private_tui_result_artifact(alias)


def test_private_result_artifact_recognition_ignores_malformed_path_syntax(
    tmp_path: Path,
) -> None:
    malformed_path = tmp_path / "result\x00alias"

    assert not tui_result_store._is_private_tui_result_artifact(malformed_path)


def test_complete_result_round_trips_from_framed_storage(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path)

    stored = _commit(store, rows=(("alpha",), ("beta",)), elapsed_ms=2.5)
    source = store.open_rows(stored.handle)

    assert source.columns == ("value",)
    assert source.elapsed_ms == 2.5
    assert tuple(source.iter_rows()) == (("alpha",), ("beta",))
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        source.iter_rows()


def test_complete_result_exposes_recorded_duckdb_column_types(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    writer = store.begin_complete(
        sequence=1,
        columns=("id", "amount"),
        column_types=("INTEGER", "DECIMAL(10,2)"),
    )
    writer.append_payload(encode_row_payload((1, "12.34")))
    stored = writer.commit(elapsed_ms=2.5)

    source = store.open_rows(stored.handle)

    assert stored.column_types == ("INTEGER", "DECIMAL(10,2)")
    assert store.describe(stored.handle) is stored
    assert source.column_types == stored.column_types


def test_store_uses_exact_workspace_grammar_and_registry_only_path(
    tmp_path: Path,
) -> None:
    created_at = datetime(2026, 7, 12, 12, 34, 56, tzinfo=UTC)
    store = TUIResultStore(
        temp_root=tmp_path,
        session_id="a" * 32,
        now=created_at,
    )

    stored = _commit(store)

    workspace = tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{'a' * 32}"
    assert store.workspace_path == workspace
    assert sorted(path.name for path in workspace.iterdir()) == [
        TUI_RESULT_LEASE_NAME,
        TUI_RESULT_MARKER_NAME,
        "query-1.result",
    ]
    assert json.loads((workspace / TUI_RESULT_MARKER_NAME).read_text(encoding="utf-8")) == {
        "created_at_utc": "2026-07-12T12:34:56Z",
        "format_version": 1,
        "session_id": "a" * 32,
    }
    assert (workspace / "query-1.result").read_bytes().startswith(b"LQLRS")
    assert not hasattr(stored.handle, "temp_path")


def test_preview_only_uses_distinct_exact_artifact_name(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="b" * 32)

    stored = store.persist_preview(
        sequence=2,
        preview=_preview(),
        reason="user_cancelled",
        elapsed_ms=3.0,
    )

    assert stored is not None
    assert store.workspace_path is not None
    assert sorted(path.name for path in store.workspace_path.iterdir()) == [
        TUI_RESULT_LEASE_NAME,
        TUI_RESULT_MARKER_NAME,
        "preview-2.result",
    ]
    assert store.load_preview(stored.handle, PreviewPolicy()).rows == (("alpha",),)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits only")
def test_workspace_metadata_and_result_permissions_are_owner_only(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="c" * 32)

    _commit(store)

    assert store.workspace_path is not None
    assert stat.S_IMODE(store.workspace_path.stat().st_mode) == 0o700
    assert stat.S_IMODE((store.workspace_path / TUI_RESULT_MARKER_NAME).stat().st_mode) == 0o600
    assert stat.S_IMODE((store.workspace_path / TUI_RESULT_LEASE_NAME).stat().st_mode) == 0o600
    assert stat.S_IMODE((store.workspace_path / "query-1.result").stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits only")
def test_workspace_permission_mode_is_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_chmod = os.chmod

    def leave_workspace_insecure(path: os.PathLike[str] | str, mode: int) -> None:
        requested_path = Path(path)
        real_chmod(
            path, 0o755 if requested_path.name.startswith(TUI_RESULT_SESSION_PREFIX) else mode
        )

    monkeypatch.setattr("csvql.tui_result_store.os.chmod", leave_workspace_insecure)
    store = TUIResultStore(temp_root=tmp_path, session_id="d" * 32)

    with pytest.raises(TUIResultStorageError) as error:
        store.begin_complete(sequence=1, columns=("value",))

    assert error.value.kind == "permission"
    assert str(tmp_path) not in error.value.user_message
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits only")
def test_staging_file_permission_mode_is_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_chmod = os.chmod

    def leave_staging_insecure(path: os.PathLike[str] | str, mode: int) -> None:
        requested_path = Path(path)
        real_chmod(path, 0o644 if requested_path.name.endswith(".result.tmp") else mode)

    monkeypatch.setattr("csvql.tui_result_store.os.chmod", leave_staging_insecure)
    store = TUIResultStore(temp_root=tmp_path, session_id="e" * 32)

    with pytest.raises(TUIResultStorageError) as error:
        store.begin_complete(sequence=1, columns=("value",))

    assert error.value.kind == "permission"
    assert str(tmp_path) not in error.value.user_message
    store.cleanup()


@pytest.mark.parametrize("session_id", ["a" * 31, "A" * 32, "g" * 32, "../" + "a" * 29])
def test_injected_session_id_must_match_exact_grammar(
    tmp_path: Path,
    session_id: str,
) -> None:
    with pytest.raises(ValueError, match="session_id"):
        TUIResultStore(temp_root=tmp_path, session_id=session_id)


def test_default_temp_failure_is_deferred_until_first_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def fail_temp_discovery() -> str:
        nonlocal attempts
        attempts += 1
        raise FileNotFoundError(errno.ENOENT, "private temp detail")

    monkeypatch.setattr("csvql.tui_result_store.tempfile.gettempdir", fail_temp_discovery)
    store = TUIResultStore()

    assert attempts == 0
    with pytest.raises(TUIResultStorageError) as error:
        store.begin_complete(sequence=1, columns=("value",))

    assert attempts == 1
    assert error.value.kind == "workspace_unavailable"
    assert "private temp detail" not in error.value.user_message


def test_append_failure_leaves_no_registered_handle_or_final_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="f" * 32)
    writer = store.begin_complete(sequence=1, columns=("value",))

    def fail_append(_writer: object, _payload: bytes) -> None:
        raise TypeError("private codec detail")

    monkeypatch.setattr(
        "csvql.tui_result_store.ResultSpoolWriter.append_payload",
        fail_append,
    )

    with pytest.raises(TUIResultStorageError) as error:
        writer.append_payload(encode_row_payload(("alpha",)))

    assert error.value.kind == "serialization"
    assert "private codec detail" not in error.value.user_message
    writer.rollback()
    assert store.workspace_path is not None
    assert sorted(path.name for path in store.workspace_path.iterdir()) == [
        TUI_RESULT_LEASE_NAME,
        TUI_RESULT_MARKER_NAME,
    ]


def test_atomic_publication_failure_removes_staging_and_registers_no_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="1" * 32)
    writer = store.begin_complete(sequence=1, columns=("value",))
    writer.append_payload(encode_row_payload(("alpha",)))

    def fail_link(
        _source: object,
        _destination: object,
        *,
        follow_symlinks: bool = True,
    ) -> None:
        del follow_symlinks
        raise OSError(errno.EIO, f"private path: {tmp_path}")

    monkeypatch.setattr("csvql.result_spool.os.link", fail_link)

    with pytest.raises(TUIResultStorageError) as error:
        writer.commit(elapsed_ms=1.0)

    assert error.value.kind == "io"
    assert str(tmp_path) not in error.value.user_message
    assert store.workspace_path is not None
    assert sorted(path.name for path in store.workspace_path.iterdir()) == [
        TUI_RESULT_LEASE_NAME,
        TUI_RESULT_MARKER_NAME,
    ]


def test_foreign_final_injected_before_commit_is_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="2" * 32)
    writer = store.begin_complete(sequence=1, columns=("value",))
    writer.append_payload(encode_row_payload(("alpha",)))
    foreign_bytes = b"foreign-final"
    real_link = os.link

    def inject_foreign_final(
        source: os.PathLike[str] | str,
        destination: os.PathLike[str] | str,
        *,
        follow_symlinks: bool = True,
    ) -> None:
        destination_path = Path(destination)
        destination_path.write_bytes(foreign_bytes)
        real_link(source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr("csvql.result_spool.os.link", inject_foreign_final)

    with pytest.raises(TUIResultStorageError):
        writer.commit(elapsed_ms=1.0)

    assert store.workspace_path is not None
    final_path = store.workspace_path / "query-1.result"
    assert final_path.read_bytes() == foreign_bytes
    summary = store.cleanup()
    assert final_path.read_bytes() == foreign_bytes
    assert summary.workspaces_failed == 1


def test_copied_handle_is_rejected_before_file_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    stored = _commit(store)
    copied = replace(stored.handle)
    accesses = 0

    def reject_access(_path: Path) -> None:
        nonlocal accesses
        accesses += 1
        raise AssertionError("copied handle reached the filesystem")

    monkeypatch.setattr(Path, "lstat", reject_access)

    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.open_rows(copied)

    assert accesses == 0


def test_same_path_replacement_is_rejected_and_foreign_file_is_preserved(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="3" * 32)
    stored = _commit(store)
    assert store.workspace_path is not None
    final_path = store.workspace_path / "query-1.result"
    final_path.unlink()
    final_path.write_bytes(b"foreign")

    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.open_rows(stored.handle)

    assert final_path.read_bytes() == b"foreign"
    summary = store.cleanup()
    assert final_path.read_bytes() == b"foreign"
    assert summary.workspaces_failed == 1


def test_unexpected_workspace_entry_invalidates_handles_without_deleting_entry(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="4" * 32)
    stored = _commit(store)
    assert store.workspace_path is not None
    unexpected = store.workspace_path / "unexpected.txt"
    unexpected.write_text("retain", encoding="utf-8")

    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.load_preview(stored.handle, PreviewPolicy())

    assert unexpected.read_text(encoding="utf-8") == "retain"
    assert store.workspace_path is None


def test_lost_workspace_invalidates_all_registered_handles(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="5" * 32)
    first = _commit(store, sequence=1, rows=((1,),))
    second = _commit(store, sequence=2, rows=((2,),))
    assert store.workspace_path is not None
    (store.workspace_path / TUI_RESULT_MARKER_NAME).unlink()

    with pytest.raises(TUIResultStorageError) as error:
        store.open_rows(first.handle)

    assert error.value.invalidated_sequences == (1, 2)
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.open_rows(second.handle)


def test_store_holds_exclusive_lease_until_cleanup(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="6" * 32)
    _commit(store)
    assert store.workspace_path is not None
    lease_path = store.workspace_path / TUI_RESULT_LEASE_NAME

    assert _acquire_lease_in_spawned_process(lease_path) is False
    store.cleanup()
    assert not lease_path.exists()


def test_cleanup_removes_marker_before_releasing_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="7" * 32)
    _commit(store)
    real_unlink = Path.unlink

    def observe_order(path: Path, missing_ok: bool = False) -> None:
        if path.name == TUI_RESULT_MARKER_NAME:
            assert store._lease is not None
            assert store._lease.is_locked is True
        elif path.name == TUI_RESULT_LEASE_NAME:
            assert store._lease is None
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", observe_order)

    assert store.cleanup().warning_count == 0


def test_cleanup_retries_after_one_shot_late_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="8" * 32)
    committed_writer = store.begin_complete(sequence=1, columns=("value",))
    committed_writer.append_payload(encode_row_payload(("alpha",)))
    stored = committed_writer.commit(elapsed_ms=1.0)
    assert committed_writer.commit(elapsed_ms=2.0) is stored
    active_writer = store.begin_complete(sequence=2, columns=("value",))
    active_writer.append_payload(encode_row_payload(("pending",)))
    workspace = store.workspace_path
    assert workspace is not None
    result_path = workspace / "query-1.result"
    marker_path = workspace / TUI_RESULT_MARKER_NAME
    lease_path = workspace / TUI_RESULT_LEASE_NAME
    foreign_path = tmp_path / "foreign.txt"
    foreign_path.write_text("retain", encoding="utf-8")
    real_close_active_lease = store._close_active_lease
    close_calls = 0

    def fail_once_at_lease_close(candidate: TUIResultStore) -> bool:
        nonlocal close_calls
        assert candidate is store
        close_calls += 1
        if close_calls == 1:
            assert not result_path.exists()
            assert not marker_path.exists()
            assert lease_path.is_file()
            raise RuntimeError("one-shot late cleanup failure")
        return real_close_active_lease()

    monkeypatch.setattr(
        store,
        "_close_active_lease",
        MethodType(fail_once_at_lease_close, store),
    )

    with pytest.raises(RuntimeError, match="one-shot late cleanup failure"):
        store.cleanup()

    assert store._cleanup_started is True
    assert store._cleanup_attempted is False
    assert store.workspace_path == workspace
    assert store._allocated_bytes == stored.logical_bytes
    assert workspace.is_dir()
    assert lease_path.is_file()
    assert foreign_path.read_text(encoding="utf-8") == "retain"

    def assert_result_unavailable(operation: object) -> None:
        assert callable(operation)
        with pytest.raises(TUIResultStorageError) as error:
            operation()
        assert error.value.kind == "result_unavailable"

    assert_result_unavailable(lambda: store.begin_complete(sequence=3, columns=("value",)))
    assert_result_unavailable(
        lambda: store.persist_preview(
            sequence=3,
            preview=_preview(),
            reason="preservation_failed",
            elapsed_ms=1.0,
        )
    )
    assert_result_unavailable(lambda: store.open_rows(stored.handle))
    assert_result_unavailable(lambda: store.load_preview(stored.handle, PreviewPolicy()))
    assert_result_unavailable(lambda: store.remove(stored.handle))
    assert_result_unavailable(lambda: committed_writer.commit(elapsed_ms=2.0))
    assert_result_unavailable(lambda: active_writer.append_payload(encode_row_payload(("late",))))
    assert_result_unavailable(lambda: active_writer.progress)
    assert_result_unavailable(lambda: active_writer.commit(elapsed_ms=2.0))
    assert store.workspace_path == workspace

    summary = store.cleanup()

    assert summary == TUIResultCleanupSummary(files_removed=1, workspaces_removed=1)
    assert close_calls == 2
    assert store._cleanup_started is True
    assert store._cleanup_attempted is True
    assert store.workspace_path is None
    assert store._workspace_identity is None
    assert store._session_id is None
    assert store._lease is None
    assert store._allocated_bytes == 0
    assert store._records_by_nonce == {}
    assert store._record_nonce_by_sequence == {}
    assert store._issued_handles == {}
    assert store._pending_cleanup_paths == set()
    assert store._pending_cleanup_identities == {}
    assert store._pending_cleanup_bytes == {}
    assert store._pending_cleanup_workspaces == {}
    assert not workspace.exists()
    assert foreign_path.read_text(encoding="utf-8") == "retain"

    assert store.cleanup() == TUIResultCleanupSummary()
    assert close_calls == 2
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.open_rows(stored.handle)
    assert_result_unavailable(lambda: committed_writer.commit(elapsed_ms=3.0))


def test_writer_queued_behind_late_cleanup_failure_cannot_replace_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    stored = _commit(store)
    workspace = store.workspace_path
    workspace_identity = store._workspace_identity
    assert workspace is not None
    assert workspace_identity is not None
    result_path = workspace / "query-1.result"
    marker_path = workspace / TUI_RESULT_MARKER_NAME
    lease_path = workspace / TUI_RESULT_LEASE_NAME
    real_close_active_lease = store._close_active_lease
    cleanup_reached_late_failure = threading.Event()
    release_cleanup_failure = threading.Event()
    writer_call_started = threading.Event()
    writer_finished = threading.Event()
    cleanup_errors: list[BaseException] = []
    writer_outcomes: list[object] = []
    close_calls = 0

    def fail_once_at_lease_close(candidate: TUIResultStore) -> bool:
        nonlocal close_calls
        assert candidate is store
        close_calls += 1
        if close_calls == 1:
            assert not result_path.exists()
            assert not marker_path.exists()
            assert lease_path.is_file()
            cleanup_reached_late_failure.set()
            if not release_cleanup_failure.wait(timeout=5.0):
                raise AssertionError("cleanup failure was not released within five seconds")
            raise RuntimeError("one-shot late cleanup failure")
        return real_close_active_lease()

    monkeypatch.setattr(
        store,
        "_close_active_lease",
        MethodType(fail_once_at_lease_close, store),
    )

    def run_cleanup() -> None:
        try:
            store.cleanup()
        except BaseException as exc:
            cleanup_errors.append(exc)

    def run_writer() -> None:
        writer_call_started.set()
        try:
            writer_outcomes.append(store.begin_complete(sequence=2, columns=("value",)))
        except BaseException as exc:
            writer_outcomes.append(exc)
        finally:
            writer_finished.set()

    cleanup_thread = threading.Thread(target=run_cleanup, name="cleanup")
    writer_thread = threading.Thread(target=run_writer, name="queued-writer")
    cleanup_thread.start()
    try:
        assert cleanup_reached_late_failure.wait(timeout=5.0)
        writer_thread.start()
        assert writer_call_started.wait(timeout=5.0)
        assert not writer_finished.wait(timeout=0.1)
    finally:
        release_cleanup_failure.set()
        cleanup_thread.join(timeout=5.0)
        if writer_thread.ident is not None:
            writer_thread.join(timeout=5.0)

    assert not cleanup_thread.is_alive()
    assert not writer_thread.is_alive()
    assert len(cleanup_errors) == 1
    assert isinstance(cleanup_errors[0], RuntimeError)
    assert str(cleanup_errors[0]) == "one-shot late cleanup failure"
    assert len(writer_outcomes) == 1
    assert isinstance(writer_outcomes[0], TUIResultStorageError)
    assert writer_outcomes[0].kind == "result_unavailable"
    assert store._cleanup_started is True
    assert store._cleanup_attempted is False
    assert store.workspace_path == workspace
    assert store._workspace_identity == workspace_identity
    assert store._allocated_bytes == stored.logical_bytes
    assert {path for path in tmp_path.iterdir() if path.is_dir()} == {workspace}

    summary = store.cleanup()

    assert summary == TUIResultCleanupSummary(files_removed=1, workspaces_removed=1)
    assert close_calls == 2
    assert store._cleanup_started is True
    assert store._cleanup_attempted is True
    assert store.workspace_path is None
    assert not workspace.exists()
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink regression")
def test_cleanup_preserves_registered_result_replaced_by_symlink(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="8" * 32)
    _commit(store)
    assert store.workspace_path is not None
    final_path = store.workspace_path / "query-1.result"
    foreign = tmp_path / "foreign.txt"
    foreign.write_text("foreign", encoding="utf-8")
    final_path.unlink()
    final_path.symlink_to(foreign)

    summary = store.cleanup()

    assert final_path.is_symlink()
    assert foreign.read_text(encoding="utf-8") == "foreign"
    assert summary.files_failed == 1
    assert summary.workspaces_failed == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX parent symlink regression")
def test_cleanup_rejects_active_workspace_replaced_by_symlink(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="9" * 32)
    _commit(store)
    workspace = store.workspace_path
    assert workspace is not None
    owned_workspace = tmp_path / "moved-owned"
    workspace.rename(owned_workspace)
    foreign_workspace = tmp_path / "foreign"
    foreign_workspace.mkdir()
    foreign_result = foreign_workspace / "query-1.result"
    foreign_result.write_bytes(b"foreign")
    workspace.symlink_to(foreign_workspace, target_is_directory=True)

    first = store.cleanup()
    second = store.cleanup()

    assert foreign_result.read_bytes() == b"foreign"
    assert (owned_workspace / "query-1.result").is_file()
    assert first.workspaces_failed == 1
    assert second == TUIResultCleanupSummary()


def test_cleanup_release_failure_is_bounded_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    _commit(store)
    lease = store._lease
    assert lease is not None

    def fail_release(candidate: _PlatformLease) -> None:
        assert candidate is lease
        raise OSError(errno.EIO, "private release detail")

    monkeypatch.setattr(_PlatformLease, "release", fail_release)

    first = store.cleanup()
    second = store.cleanup()

    assert first.files_failed == 1
    assert first.workspaces_failed == 1
    assert second == TUIResultCleanupSummary()
    assert lease.file.closed is True
    assert lease.is_locked is False


def test_staging_name_collision_is_preserved_and_never_registered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="b" * 32)
    first = _commit(store, sequence=1)
    assert store.workspace_path is not None
    staging_path = store.workspace_path / f".query-2-{'f' * 16}.result.tmp"
    real_open = os.open

    def staging_token(nbytes: int) -> str:
        assert nbytes == 8
        return "f" * 16

    monkeypatch.setattr("csvql.tui_result_store.secrets.token_hex", staging_token)

    def collide(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
    ) -> int:
        if Path(path) == staging_path and not staging_path.exists():
            staging_path.write_text("foreign", encoding="utf-8")
        return real_open(path, flags, mode)

    monkeypatch.setattr("csvql.result_spool.os.open", collide)

    with pytest.raises(TUIResultStorageError):
        store.begin_complete(sequence=2, columns=("value",))

    assert staging_path.read_text(encoding="utf-8") == "foreign"
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.open_rows(first.handle)
    assert staging_path.read_text(encoding="utf-8") == "foreign"


def test_remove_unlinks_only_selected_artifact(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="c" * 32)
    first = _commit(store, sequence=1, rows=((1,),))
    second = _commit(store, sequence=2, rows=((2,),))

    store.remove(first.handle)

    assert store.workspace_path is not None
    assert not (store.workspace_path / "query-1.result").exists()
    assert (store.workspace_path / "query-2.result").is_file()
    assert tuple(store.open_rows(second.handle).iter_rows()) == ((2,),)


def test_cleanup_removes_normal_workspace_and_is_safe_to_repeat(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="d" * 32)
    stored = _commit(store)
    workspace = store.workspace_path
    assert workspace is not None

    first = store.cleanup()
    second = store.cleanup()

    assert not workspace.exists()
    assert first == TUIResultCleanupSummary(files_removed=3, workspaces_removed=1)
    assert second == TUIResultCleanupSummary()
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.open_rows(stored.handle)


def test_cleanup_is_terminal_and_rejects_future_writers(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    store.cleanup()

    with pytest.raises(TUIResultStorageError) as error:
        store.begin_complete(sequence=1, columns=("value",))

    assert error.value.kind == "result_unavailable"
    assert store.workspace_path is None
    assert tuple(tmp_path.iterdir()) == ()


def test_cleanup_summary_merge_adds_each_bounded_count() -> None:
    first = TUIResultCleanupSummary(
        temp_entries_inspected=1,
        candidates_validated=2,
        files_removed=3,
        files_failed=4,
        workspaces_removed=5,
        workspaces_failed=6,
    )
    second = TUIResultCleanupSummary(
        temp_entries_inspected=10,
        candidates_validated=20,
        files_removed=30,
        files_failed=40,
        workspaces_removed=50,
        workspaces_failed=60,
    )

    assert first.merge(second) == TUIResultCleanupSummary(
        temp_entries_inspected=11,
        candidates_validated=22,
        files_removed=33,
        files_failed=44,
        workspaces_removed=55,
        workspaces_failed=66,
    )
    assert first.warning_count == 10
