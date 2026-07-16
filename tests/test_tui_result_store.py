import errno
import json
import multiprocessing
import os
import pickle
import shutil
import stat
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from pathlib import Path

import pytest

from csvql.models import QueryResult
from csvql.tui_result_store import (
    TUI_RESULT_LEASE_NAME,
    TUI_RESULT_MARKER_NAME,
    TUI_RESULT_SESSION_PREFIX,
    TUI_RESULT_SPILL_CELL_THRESHOLD,
    TUI_RESULT_SPILL_ROW_THRESHOLD,
    TUIResultCleanupSummary,
    TUIResultHandle,
    TUIResultStorageError,
    TUIResultStore,
    _PlatformLease,
)


def _result(row_count: int, column_count: int = 1) -> QueryResult:
    columns = tuple(f"c{index}" for index in range(column_count))
    rows = tuple(
        tuple(f"{row}-{column}" for column in range(column_count)) for row in range(row_count)
    )
    return QueryResult(columns=columns, rows=rows, elapsed_ms=1.0)


def _deterministic_token_hex() -> Callable[[int], str]:
    session_ids = iter(("c" * 32, "d" * 32))
    staging_tokens = iter(("1" * 16, "2" * 16))

    def token_hex(nbytes: int) -> str:
        if nbytes == 16:
            return next(session_ids)
        if nbytes == 8:
            return next(staging_tokens)
        raise AssertionError(f"unexpected token size: {nbytes}")

    return token_hex


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


def test_small_result_does_not_create_spill_workspace(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path)

    outcome = store.put(_result(2), sequence=1)

    assert outcome.handle.is_spilled is False
    assert store.workspace_path is None
    assert tuple(tmp_path.iterdir()) == ()
    assert store.get(outcome.handle).row_count == 2


def test_default_temp_failure_is_deferred_until_first_spill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_discovery_attempts = 0

    def fail_temp_discovery() -> str:
        nonlocal temp_discovery_attempts
        temp_discovery_attempts += 1
        raise FileNotFoundError(errno.ENOENT, "sensitive temporary-directory detail")

    monkeypatch.setattr("csvql.tui_result_store.tempfile.gettempdir", fail_temp_discovery)

    store = TUIResultStore()
    small = store.put(_result(2), sequence=1)

    assert temp_discovery_attempts == 0
    assert store.get(small.handle).row_count == 2
    assert store.workspace_path is None

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=2)

    assert temp_discovery_attempts == 1
    assert error.value.kind == "workspace_unavailable"
    assert "sensitive temporary-directory detail" not in error.value.user_message


def test_result_store_spills_large_cell_count(tmp_path: Path) -> None:
    row_count = 101
    column_count = (TUI_RESULT_SPILL_CELL_THRESHOLD // row_count) + 1
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)

    outcome = store.put(_result(row_count, column_count), sequence=2)

    assert outcome.handle.is_spilled is True
    assert store.get(outcome.handle).row_count == row_count


def test_spill_uses_exact_workspace_grammar_and_atomic_final_name(tmp_path: Path) -> None:
    created_at = datetime(2026, 7, 12, 12, 34, 56, tzinfo=UTC)
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32, now=created_at)

    outcome = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    workspace = tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{'a' * 32}"
    assert store.workspace_path == workspace
    assert outcome.handle.temp_path == workspace / "query-1.pickle"
    assert sorted(path.name for path in workspace.iterdir()) == [
        TUI_RESULT_LEASE_NAME,
        TUI_RESULT_MARKER_NAME,
        "query-1.pickle",
    ]
    assert json.loads((workspace / TUI_RESULT_MARKER_NAME).read_text(encoding="utf-8")) == {
        "created_at_utc": "2026-07-12T12:34:56Z",
        "format_version": 1,
        "session_id": "a" * 32,
    }
    lease_path = workspace / TUI_RESULT_LEASE_NAME
    assert lease_path.stat().st_size == 1
    if os.name != "nt":
        assert lease_path.read_bytes() == b"0"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits only")
def test_workspace_and_spill_permissions_are_owner_only(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="d" * 32)

    outcome = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert store.workspace_path is not None
    assert stat.S_IMODE(store.workspace_path.stat().st_mode) == 0o700
    assert stat.S_IMODE((store.workspace_path / TUI_RESULT_MARKER_NAME).stat().st_mode) == 0o600
    assert stat.S_IMODE((store.workspace_path / TUI_RESULT_LEASE_NAME).stat().st_mode) == 0o600
    assert outcome.handle.temp_path is not None
    assert stat.S_IMODE(outcome.handle.temp_path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits only")
def test_workspace_permission_mode_is_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_chmod = os.chmod

    def leave_workspace_insecure(path: os.PathLike[str] | str, mode: int) -> None:
        requested_path = Path(path)
        insecure_mode = 0o755 if requested_path.name.startswith(TUI_RESULT_SESSION_PREFIX) else mode
        real_chmod(path, insecure_mode)

    monkeypatch.setattr("csvql.tui_result_store.os.chmod", leave_workspace_insecure)
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

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
        insecure_mode = 0o644 if requested_path.name.endswith(".tmp") else mode
        real_chmod(path, insecure_mode)

    monkeypatch.setattr("csvql.tui_result_store.os.chmod", leave_staging_insecure)
    store = TUIResultStore(temp_root=tmp_path, session_id="b" * 32)

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert error.value.kind == "permission"
    assert str(tmp_path) not in error.value.user_message
    store.cleanup()


@pytest.mark.parametrize("session_id", ["a" * 31, "A" * 32, "g" * 32, "../" + "a" * 29])
def test_injected_session_id_must_match_exact_grammar(tmp_path: Path, session_id: str) -> None:
    with pytest.raises(ValueError, match="session_id"):
        TUIResultStore(temp_root=tmp_path, session_id=session_id)


@pytest.mark.parametrize("sequence", [0, -1, True])
def test_spill_sequence_must_be_a_positive_integer(tmp_path: Path, sequence: object) -> None:
    store = TUIResultStore(temp_root=tmp_path)

    with pytest.raises(ValueError, match="positive integer"):
        store.put(_result(1), sequence=sequence)  # type: ignore[arg-type]

    assert store.workspace_path is None


def test_duplicate_sequence_is_rejected_without_replacing_existing_result(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    first_result = _result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1)
    first = store.put(first_result, sequence=1)

    with pytest.raises(ValueError, match="already stored"):
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 2), sequence=1)

    assert store.get(first.handle) == first_result


def test_serialization_failure_registers_no_handle_or_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="b" * 32)

    def fail_dump(result: object, file: object, *, protocol: int) -> None:
        del result, file, protocol
        raise TypeError("sensitive serializer detail")

    monkeypatch.setattr("csvql.tui_result_store.pickle.dump", fail_dump)

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert error.value.kind == "serialization"
    assert "sensitive serializer detail" not in error.value.user_message
    assert str(tmp_path) not in error.value.user_message
    assert list((store.workspace_path or tmp_path).glob("query-1.pickle")) == []
    assert list((store.workspace_path or tmp_path).glob(".query-1-*.tmp")) == []


def test_atomic_replace_failure_removes_staging_and_registers_no_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="b" * 32)

    def fail_replace(source: object, destination: object) -> None:
        del source, destination
        raise OSError(errno.EIO, f"sensitive path: {tmp_path}")

    monkeypatch.setattr("csvql.tui_result_store.os.replace", fail_replace)

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert error.value.kind == "io"
    assert str(tmp_path) not in error.value.user_message
    assert store.workspace_path is not None
    assert sorted(path.name for path in store.workspace_path.iterdir()) == [
        TUI_RESULT_LEASE_NAME,
        TUI_RESULT_MARKER_NAME,
    ]


@pytest.mark.skipif(
    os.name == "nt",
    reason="renaming a workspace containing an open lease is a POSIX-only test setup",
)
def test_serialization_failure_does_not_unlink_foreign_staging_through_parent_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "3" * 16
    session_id = "c" * 32
    workspace = tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{session_id}"
    moved_workspace = tmp_path / "moved-owned-staging-workspace"
    foreign_workspace = tmp_path / "foreign-staging-workspace"
    staging_name = f".query-1-{token}.tmp"
    foreign_staging = foreign_workspace / staging_name
    store = TUIResultStore(temp_root=tmp_path, session_id=session_id)

    def staging_token_hex(nbytes: int) -> str:
        assert nbytes == 8
        return token

    def replace_parent_with_symlink(
        result: object,
        file: object,
        *,
        protocol: int,
    ) -> None:
        del result, file, protocol
        workspace.rename(moved_workspace)
        foreign_workspace.mkdir()
        foreign_staging.write_bytes(b"foreign staging content")
        workspace.symlink_to(foreign_workspace, target_is_directory=True)
        raise TypeError("sensitive serializer detail")

    monkeypatch.setattr("csvql.tui_result_store.secrets.token_hex", staging_token_hex)
    monkeypatch.setattr(
        "csvql.tui_result_store.pickle.dump",
        replace_parent_with_symlink,
    )

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert error.value.kind == "serialization"
    assert "sensitive serializer detail" not in error.value.user_message
    assert str(tmp_path) not in error.value.user_message
    assert foreign_staging.read_bytes() == b"foreign staging content"
    assert (moved_workspace / staging_name).is_file()
    assert workspace / staging_name in store._pending_cleanup_paths

    summary = store.cleanup()

    assert summary == TUIResultCleanupSummary(workspaces_failed=1)
    assert foreign_staging.read_bytes() == b"foreign staging content"


@pytest.mark.skipif(
    os.name == "nt",
    reason="renaming a workspace containing an open lease is a POSIX-only test setup",
)
def test_serialization_failure_does_not_unlink_foreign_staging_in_replaced_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "4" * 16
    session_id = "d" * 32
    workspace = tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{session_id}"
    moved_workspace = tmp_path / "moved-owned-staging-workspace"
    staging_name = f".query-1-{token}.tmp"
    foreign_staging = workspace / staging_name
    store = TUIResultStore(temp_root=tmp_path, session_id=session_id)

    def staging_token_hex(nbytes: int) -> str:
        assert nbytes == 8
        return token

    def replace_parent_with_directory(
        result: object,
        file: object,
        *,
        protocol: int,
    ) -> None:
        del result, file, protocol
        workspace.rename(moved_workspace)
        workspace.mkdir()
        foreign_staging.write_bytes(b"foreign staging content")
        raise TypeError("sensitive serializer detail")

    monkeypatch.setattr("csvql.tui_result_store.secrets.token_hex", staging_token_hex)
    monkeypatch.setattr(
        "csvql.tui_result_store.pickle.dump",
        replace_parent_with_directory,
    )

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert error.value.kind == "serialization"
    assert "sensitive serializer detail" not in error.value.user_message
    assert str(tmp_path) not in error.value.user_message
    assert foreign_staging.read_bytes() == b"foreign staging content"
    assert (moved_workspace / staging_name).is_file()
    assert foreign_staging in store._pending_cleanup_paths

    summary = store.cleanup()

    assert summary == TUIResultCleanupSummary(workspaces_failed=1)
    assert foreign_staging.read_bytes() == b"foreign staging content"


@pytest.mark.skipif(os.name == "nt", reason="os.fchmod is not used on Windows")
def test_spill_permission_setup_failure_closes_raw_file_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="b" * 32)
    real_open = os.open
    staging_descriptors: list[int] = []

    def record_open(path: os.PathLike[str] | str, flags: int, mode: int = 0o777) -> int:
        descriptor = real_open(path, flags, mode)
        if Path(path).name.startswith(".query-"):
            staging_descriptors.append(descriptor)
        return descriptor

    def fail_fchmod(file_descriptor: int, mode: int) -> None:
        del file_descriptor, mode
        raise OSError(errno.EIO, "sensitive descriptor detail")

    monkeypatch.setattr("csvql.tui_result_store.os.open", record_open)
    monkeypatch.setattr("csvql.tui_result_store.os.fchmod", fail_fchmod)

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert error.value.kind == "io"
    assert len(staging_descriptors) == 1
    with pytest.raises(OSError) as closed_error:
        os.fstat(staging_descriptors[0])
    assert closed_error.value.errno == errno.EBADF


def test_partial_marker_creation_failure_removes_attempt_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = os.open

    def fail_lease_open(path: os.PathLike[str] | str, flags: int, mode: int = 0o777) -> int:
        if Path(path).name == TUI_RESULT_LEASE_NAME:
            raise PermissionError(errno.EACCES, f"sensitive path: {path}")
        return real_open(path, flags, mode)

    monkeypatch.setattr("csvql.tui_result_store.os.open", fail_lease_open)
    store = TUIResultStore(temp_root=tmp_path, session_id="b" * 32)

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert error.value.kind == "permission"
    assert str(tmp_path) not in error.value.user_message
    assert store.workspace_path is None
    assert tuple(tmp_path.iterdir()) == ()


def test_initial_workspace_unavailable_is_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    create_attempts = 0

    def fail_creation() -> Path:
        nonlocal create_attempts
        create_attempts += 1
        raise TUIResultStorageError(
            "Unable to create secure temporary result storage.",
            kind="workspace_unavailable",
        )

    monkeypatch.setattr(store, "_create_workspace", fail_creation)

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert create_attempts == 1
    assert error.value.kind == "workspace_unavailable"


def test_invalid_workspace_retries_once_and_invalidates_old_spills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "csvql.tui_result_store.secrets.token_hex",
        _deterministic_token_hex(),
    )
    store = TUIResultStore(temp_root=tmp_path)
    first = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    assert store.workspace_path is not None
    (store.workspace_path / TUI_RESULT_MARKER_NAME).unlink()
    ensure_attempts = 0
    real_ensure_workspace = store._ensure_workspace

    def record_ensure_workspace() -> Path:
        nonlocal ensure_attempts
        ensure_attempts += 1
        return real_ensure_workspace()

    monkeypatch.setattr(store, "_ensure_workspace", record_ensure_workspace)

    second = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=2)

    assert ensure_attempts == 2
    assert second.handle.is_spilled is True
    assert second.invalidated_sequences == (1,)
    assert store.workspace_path == tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{'d' * 32}"
    with pytest.raises(TUIResultStorageError, match="no longer available") as error:
        store.get(first.handle)
    assert error.value.kind == "result_unavailable"
    assert error.value.invalidated_sequences == (1,)


def test_workspace_replacement_failure_reports_invalidated_sequences_and_stops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    first = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    assert first.handle.temp_path is not None
    assert store.workspace_path is not None
    (store.workspace_path / TUI_RESULT_MARKER_NAME).unlink()
    create_attempts = 0

    def fail_replacement() -> Path:
        nonlocal create_attempts
        create_attempts += 1
        raise TUIResultStorageError(
            "Unable to create secure temporary result storage.",
            kind="permission",
        )

    monkeypatch.setattr(store, "_create_workspace", fail_replacement)

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=2)

    assert create_attempts == 1
    assert error.value.kind == "permission"
    assert error.value.invalidated_sequences == (1,)


def test_put_normalizes_raw_replacement_os_error_and_preserves_invalidations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    first = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    assert store.workspace_path is not None
    (store.workspace_path / TUI_RESULT_MARKER_NAME).unlink()

    def fail_replacement() -> Path:
        raise PermissionError("private path")

    monkeypatch.setattr(store, "_create_workspace", fail_replacement)

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=2)

    assert error.value.kind == "permission"
    assert error.value.invalidated_sequences == (1,)
    assert error.value.user_message == "Unable to use secure temporary result storage."
    assert "private path" not in error.value.user_message
    assert str(tmp_path) not in error.value.user_message
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.get(first.handle)


def test_non_workspace_storage_failure_is_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    dump_attempts = 0

    def fail_dump(result: object, file: object, *, protocol: int) -> None:
        nonlocal dump_attempts
        del result, file, protocol
        dump_attempts += 1
        raise TypeError("private value")

    monkeypatch.setattr("csvql.tui_result_store.pickle.dump", fail_dump)

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert dump_attempts == 1
    assert error.value.kind == "serialization"


def test_workspace_exact_name_check_rejects_unexpected_entry_without_deleting_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "csvql.tui_result_store.secrets.token_hex",
        _deterministic_token_hex(),
    )
    store = TUIResultStore(temp_root=tmp_path)
    first = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    assert store.workspace_path is not None
    old_workspace = store.workspace_path
    unexpected = old_workspace / "do-not-delete.txt"
    unexpected.write_text("foreign", encoding="utf-8")

    second = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=2)

    assert second.invalidated_sequences == (1,)
    assert unexpected.read_text(encoding="utf-8") == "foreign"
    with pytest.raises(TUIResultStorageError):
        store.get(first.handle)


def test_result_store_rejects_foreign_spilled_paths_without_unpickling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    foreign_path = tmp_path / "foreign-result.pickle"
    foreign_path.write_bytes(pickle.dumps(_result(1)))
    handle = TUIResultHandle(sequence=99, is_spilled=True, temp_path=foreign_path)

    def fail_on_load(*args: object, **kwargs: object) -> object:
        raise AssertionError("foreign spilled paths must not be unpickled")

    monkeypatch.setattr("csvql.tui_result_store.pickle.load", fail_on_load)

    with pytest.raises(TUIResultStorageError) as error:
        store.get(handle)

    assert error.value.kind == "result_unavailable"
    assert error.value.invalidated_sequences == (99,)


def test_result_store_rejects_handle_with_registered_sequence_but_foreign_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    stored = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    forged = TUIResultHandle(sequence=1, is_spilled=True, temp_path=tmp_path / "foreign.pickle")

    def fail_on_load(*args: object, **kwargs: object) -> object:
        raise AssertionError("a mismatched registered path must not be unpickled")

    monkeypatch.setattr("csvql.tui_result_store.pickle.load", fail_on_load)

    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.get(forged)

    monkeypatch.undo()
    assert store.get(stored.handle).row_count == TUI_RESULT_SPILL_ROW_THRESHOLD + 1


def test_result_store_rejects_foreign_and_copied_in_memory_handles(tmp_path: Path) -> None:
    first_store = TUIResultStore(temp_root=tmp_path / "first")
    second_store = TUIResultStore(temp_root=tmp_path / "second")
    first = first_store.put(
        QueryResult(columns=("owner",), rows=(("first",),), elapsed_ms=1.0),
        sequence=1,
    )
    second = second_store.put(
        QueryResult(columns=("owner",), rows=(("second",),), elapsed_ms=1.0),
        sequence=1,
    )

    with pytest.raises(TUIResultStorageError, match="no longer available"):
        first_store.get(second.handle)
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        first_store.get(replace(first.handle))

    assert first_store.get(first.handle).rows == (("first",),)


def test_result_store_rejects_copied_spill_handle_before_unpickling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    stored = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    def fail_on_load(*args: object, **kwargs: object) -> object:
        raise AssertionError("a copied handle must be rejected before unpickling")

    monkeypatch.setattr("csvql.tui_result_store.pickle.load", fail_on_load)

    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.get(replace(stored.handle))


def test_lost_workspace_invalidates_all_registered_spills(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    first = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    second = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=2)
    workspace = store.workspace_path
    assert workspace is not None
    if os.name == "nt":
        assert store._close_active_lease()
    shutil.rmtree(workspace)

    with pytest.raises(TUIResultStorageError, match="no longer available") as error:
        store.get(first.handle)

    assert error.value.kind == "result_unavailable"
    assert error.value.invalidated_sequences == (1, 2)
    with pytest.raises(TUIResultStorageError):
        store.get(second.handle)


def test_spill_open_missing_race_invalidates_all_registered_spills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    first = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=2)
    assert first.handle.temp_path is not None
    real_open = Path.open

    def disappear_before_open(
        path: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ):
        if path == first.handle.temp_path:
            path.unlink()
            raise FileNotFoundError(errno.ENOENT, "private vanished path")
        return real_open(
            path,
            mode,
            buffering,
            encoding,
            errors,
            newline,
        )

    monkeypatch.setattr(Path, "open", disappear_before_open)

    with pytest.raises(TUIResultStorageError, match="no longer available") as error:
        store.get(first.handle)

    assert error.value.invalidated_sequences == (1, 2)
    assert "private vanished path" not in error.value.user_message
    assert str(tmp_path) not in error.value.user_message


def test_missing_module_pickle_is_sanitized_as_result_unavailable(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    stored = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    assert stored.handle.temp_path is not None
    stored.handle.temp_path.write_bytes(b"cno_such_localql_module\nMissing\n.")

    with pytest.raises(TUIResultStorageError) as error:
        store.get(stored.handle)

    assert error.value.kind == "result_unavailable"
    assert error.value.invalidated_sequences == (1,)
    assert "no_such_localql_module" not in error.value.user_message
    assert str(tmp_path) not in error.value.user_message


def test_unpickle_base_exception_is_not_normalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    stored = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    def interrupt_load(file: object) -> object:
        del file
        raise KeyboardInterrupt

    monkeypatch.setattr("csvql.tui_result_store.pickle.load", interrupt_load)

    with pytest.raises(KeyboardInterrupt):
        store.get(stored.handle)


def test_missing_memory_handle_raises_sanitized_unavailable_error(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path)

    with pytest.raises(TUIResultStorageError) as error:
        store.get(TUIResultHandle(sequence=42, is_spilled=False))

    assert error.value.kind == "result_unavailable"
    assert error.value.invalidated_sequences == (42,)
    assert error.value.user_message == "The full result is no longer available."


def test_invalid_registered_payload_is_rejected_with_sanitized_error(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    outcome = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    assert outcome.handle.temp_path is not None
    outcome.handle.temp_path.write_bytes(pickle.dumps({"private": "row value"}))

    with pytest.raises(TUIResultStorageError) as error:
        store.get(outcome.handle)

    assert error.value.kind == "result_unavailable"
    assert "private" not in error.value.user_message
    assert str(tmp_path) not in error.value.user_message


def test_cleanup_is_non_recursive_bounded_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    outcome = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    assert store.workspace_path is not None
    workspace = store.workspace_path
    unexpected_directory = workspace / "foreign-directory"
    unexpected_directory.mkdir()
    (unexpected_directory / "keep.txt").write_text("keep", encoding="utf-8")

    def fail_recursive_delete(*args: object, **kwargs: object) -> None:
        raise AssertionError("cleanup must never recursively delete")

    monkeypatch.setattr(shutil, "rmtree", fail_recursive_delete)

    first = store.cleanup()
    second = store.cleanup()

    assert outcome.handle.temp_path is not None
    assert not outcome.handle.temp_path.exists()
    assert unexpected_directory.is_dir()
    assert first == TUIResultCleanupSummary(
        files_removed=3,
        workspaces_failed=1,
    )
    assert first.warning_count == 1
    assert second == TUIResultCleanupSummary()


def test_cleanup_is_idempotent_and_never_removes_unexpected_entry(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="e" * 32)
    store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    assert store.workspace_path is not None
    unexpected = store.workspace_path / "keep-me.txt"
    unexpected.write_text("foreign", encoding="utf-8")

    first = store.cleanup()
    second = store.cleanup()

    assert unexpected.read_text(encoding="utf-8") == "foreign"
    assert first.workspaces_failed == 1
    assert second.warning_count == 0


def test_store_holds_lease_until_cleanup(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="f" * 32)
    store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert store._lease is not None
    assert store._lease.is_locked is True

    store.cleanup()

    assert store._lease is None


def test_platform_lease_excludes_competing_process(tmp_path: Path) -> None:
    lease_path = tmp_path / TUI_RESULT_LEASE_NAME
    lease_path.write_bytes(b"0")
    lease = _PlatformLease.open(lease_path)
    assert lease.acquire_nonblocking() is True

    try:
        assert _acquire_lease_in_spawned_process(lease_path) is False
    finally:
        lease.close()

    assert _acquire_lease_in_spawned_process(lease_path) is True


def test_unexpected_platform_lock_error_is_sanitized_at_store_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_lock(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError(errno.EIO, "sensitive platform lock detail")

    if os.name == "nt":
        import msvcrt

        monkeypatch.setattr(msvcrt, "locking", fail_lock)
    else:
        import fcntl

        monkeypatch.setattr(fcntl, "lockf", fail_lock)
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert error.value.kind == "io"
    assert "sensitive platform lock detail" not in error.value.user_message
    assert str(tmp_path) not in error.value.user_message
    assert store._lease is None
    assert tuple(tmp_path.iterdir()) == ()


def test_workspace_creation_rejects_unavailable_lease_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "csvql.tui_result_store._PlatformLease.acquire_nonblocking",
        lambda _lease: False,
    )
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert error.value.kind == "workspace_unavailable"
    assert str(tmp_path) not in error.value.user_message
    assert store._lease is None
    assert tuple(tmp_path.iterdir()) == ()


def test_cleanup_removes_marker_before_releasing_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="b" * 32)
    store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    real_unlink = Path.unlink

    def observe_lease_order(path: Path, missing_ok: bool = False) -> None:
        if path.name == TUI_RESULT_MARKER_NAME:
            assert store._lease is not None
            assert store._lease.is_locked is True
        elif path.name == TUI_RESULT_LEASE_NAME:
            assert store._lease is None
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", observe_lease_order)

    summary = store.cleanup()

    assert summary.warning_count == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink creation is portable")
def test_cleanup_retains_registered_spill_replaced_by_symlink(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="c" * 32)
    outcome = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    assert outcome.handle.temp_path is not None
    spill_path = outcome.handle.temp_path
    foreign_target = tmp_path / "foreign-target.txt"
    foreign_target.write_text("foreign", encoding="utf-8")
    spill_path.unlink()
    spill_path.symlink_to(foreign_target)

    summary = store.cleanup()

    assert spill_path.is_symlink()
    assert foreign_target.read_text(encoding="utf-8") == "foreign"
    assert summary == TUIResultCleanupSummary(
        files_removed=2,
        files_failed=1,
        workspaces_failed=1,
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX parent symlink regression")
def test_cleanup_rejects_active_workspace_replaced_by_symlink(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="d" * 32)
    outcome = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    workspace = store.workspace_path
    assert workspace is not None
    assert outcome.handle.temp_path is not None
    owned_workspace = tmp_path / "moved-owned-workspace"
    workspace.rename(owned_workspace)
    foreign_workspace = tmp_path / "foreign-workspace"
    foreign_workspace.mkdir()
    foreign_paths = tuple(
        foreign_workspace / name
        for name in (TUI_RESULT_MARKER_NAME, TUI_RESULT_LEASE_NAME, "query-1.pickle")
    )
    for foreign_path in foreign_paths:
        foreign_path.write_bytes(b"foreign")
    workspace.symlink_to(foreign_workspace, target_is_directory=True)

    first = store.cleanup()
    second = store.cleanup()

    assert all(path.read_bytes() == b"foreign" for path in foreign_paths)
    assert (owned_workspace / TUI_RESULT_MARKER_NAME).is_file()
    assert (owned_workspace / TUI_RESULT_LEASE_NAME).is_file()
    assert (owned_workspace / "query-1.pickle").is_file()
    assert workspace.is_symlink()
    assert first == TUIResultCleanupSummary(workspaces_failed=1)
    assert second == TUIResultCleanupSummary()


def test_lost_workspace_release_failure_detaches_and_retries_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    first = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    workspace = store.workspace_path
    abandoned_lease = store._lease
    assert workspace is not None
    assert abandoned_lease is not None
    (workspace / TUI_RESULT_MARKER_NAME).unlink()
    real_release = _PlatformLease.release

    def fail_abandoned_release(lease: _PlatformLease) -> None:
        if lease is abandoned_lease:
            raise OSError(errno.EIO, "sensitive abandoned lease detail")
        real_release(lease)

    monkeypatch.setattr(_PlatformLease, "release", fail_abandoned_release)

    replacement = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=2)

    assert replacement.invalidated_sequences == (1,)
    assert store._lease is not None
    assert store._lease is not abandoned_lease
    assert store._lease.is_locked is True
    assert abandoned_lease.file.closed is True
    assert abandoned_lease.is_locked is False
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.get(first.handle)

    cleanup = store.cleanup()
    repeated = store.cleanup()

    assert cleanup == TUIResultCleanupSummary(
        files_removed=3,
        files_failed=1,
        workspaces_removed=1,
    )
    assert repeated == TUIResultCleanupSummary()


def test_lost_workspace_release_failure_from_get_is_sanitized_and_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="e" * 32)
    stored = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    workspace = store.workspace_path
    abandoned_lease = store._lease
    assert workspace is not None
    assert abandoned_lease is not None
    (workspace / TUI_RESULT_MARKER_NAME).unlink()

    def fail_release(lease: _PlatformLease) -> None:
        assert lease is abandoned_lease
        raise OSError(errno.EIO, "sensitive abandoned lease detail")

    monkeypatch.setattr(_PlatformLease, "release", fail_release)

    with pytest.raises(TUIResultStorageError) as error:
        store.get(stored.handle)

    assert error.value.kind == "result_unavailable"
    assert error.value.invalidated_sequences == (1,)
    assert "sensitive abandoned lease detail" not in error.value.user_message
    assert store._lease is None
    assert store.workspace_path is None
    assert abandoned_lease.file.closed is True
    assert abandoned_lease.is_locked is False
    assert store.cleanup() == TUIResultCleanupSummary(files_failed=1)
    assert store.cleanup() == TUIResultCleanupSummary()


def test_cleanup_release_failure_is_bounded_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="f" * 32)
    store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    workspace = store.workspace_path
    lease = store._lease
    assert workspace is not None
    assert lease is not None

    def fail_release(candidate: _PlatformLease) -> None:
        assert candidate is lease
        raise OSError(errno.EIO, "sensitive release detail")

    monkeypatch.setattr(_PlatformLease, "release", fail_release)

    first = store.cleanup()
    second = store.cleanup()

    assert first == TUIResultCleanupSummary(
        files_removed=2,
        files_failed=1,
        workspaces_failed=1,
    )
    assert second == TUIResultCleanupSummary()
    assert store._lease is None
    assert lease.file.closed is True
    assert lease.is_locked is False
    assert (workspace / TUI_RESULT_LEASE_NAME).is_file()


def test_cleanup_rejects_replaced_workspace_identity(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="1" * 32)
    store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    workspace = store.workspace_path
    assert workspace is not None
    owned_workspace = tmp_path / "moved-owned-workspace"
    if os.name == "nt":
        assert store._close_active_lease()
    workspace.rename(owned_workspace)
    workspace.mkdir()
    replacement_paths = tuple(
        workspace / name
        for name in (TUI_RESULT_MARKER_NAME, TUI_RESULT_LEASE_NAME, "query-1.pickle")
    )
    for replacement_path in replacement_paths:
        replacement_path.write_bytes(b"replacement")

    summary = store.cleanup()

    assert all(path.read_bytes() == b"replacement" for path in replacement_paths)
    assert (owned_workspace / TUI_RESULT_MARKER_NAME).is_file()
    assert (owned_workspace / TUI_RESULT_LEASE_NAME).is_file()
    assert (owned_workspace / "query-1.pickle").is_file()
    assert summary == TUIResultCleanupSummary(workspaces_failed=1)


@pytest.mark.skipif(os.name != "nt", reason="Windows active-lease contract")
def test_windows_active_lease_prevents_lease_removal(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    workspace = store.workspace_path
    assert workspace is not None

    with pytest.raises(PermissionError):
        (workspace / TUI_RESULT_LEASE_NAME).unlink()

    assert store.cleanup().warning_count == 0
    assert not workspace.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX parent symlink regression")
def test_cleanup_rejects_pending_workspace_replaced_by_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed_workspace = tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{'2' * 32}"
    failed_marker = failed_workspace / TUI_RESULT_MARKER_NAME
    real_open = os.open

    def fail_lease_open(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
    ) -> int:
        if Path(path).name == TUI_RESULT_LEASE_NAME:
            raise PermissionError(errno.EACCES, "sensitive lease detail")
        return real_open(path, flags, mode)

    real_unlink = Path.unlink
    marker_unlink_attempts = 0

    def retain_marker_once(path: Path, missing_ok: bool = False) -> None:
        nonlocal marker_unlink_attempts
        if path == failed_marker:
            marker_unlink_attempts += 1
            if marker_unlink_attempts == 1:
                raise PermissionError(errno.EACCES, "sensitive marker detail")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr("csvql.tui_result_store.os.open", fail_lease_open)
    monkeypatch.setattr(Path, "unlink", retain_marker_once)
    store = TUIResultStore(temp_root=tmp_path, session_id="2" * 32)
    with pytest.raises(TUIResultStorageError):
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    owned_workspace = tmp_path / "moved-pending-workspace"
    failed_workspace.rename(owned_workspace)
    foreign_workspace = tmp_path / "foreign-pending-workspace"
    foreign_workspace.mkdir()
    foreign_marker = foreign_workspace / TUI_RESULT_MARKER_NAME
    foreign_marker.write_bytes(b"foreign")
    failed_workspace.symlink_to(foreign_workspace, target_is_directory=True)

    summary = store.cleanup()

    assert foreign_marker.read_bytes() == b"foreign"
    assert (owned_workspace / TUI_RESULT_MARKER_NAME).is_file()
    assert failed_workspace.is_symlink()
    assert summary == TUIResultCleanupSummary(workspaces_failed=1)


def test_cleanup_removes_normal_workspace_and_is_safe_to_repeat(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    outcome = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    workspace = store.workspace_path
    assert workspace is not None

    first = store.cleanup()
    second = store.cleanup()

    assert outcome.handle.temp_path is not None
    assert not outcome.handle.temp_path.exists()
    assert not workspace.exists()
    assert first == TUIResultCleanupSummary(files_removed=3, workspaces_removed=1)
    assert second == TUIResultCleanupSummary()


def test_failed_metadata_rollback_remains_owned_beside_future_active_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "csvql.tui_result_store.secrets.token_hex",
        _deterministic_token_hex(),
    )
    real_open = os.open
    lease_creation_attempts = 0

    def fail_first_lease_open(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
    ) -> int:
        nonlocal lease_creation_attempts
        if Path(path).name == TUI_RESULT_LEASE_NAME:
            lease_creation_attempts += 1
            if lease_creation_attempts == 1:
                raise PermissionError(errno.EACCES, f"sensitive path: {path}")
        return real_open(path, flags, mode)

    failed_workspace = tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{'c' * 32}"
    failed_marker = failed_workspace / TUI_RESULT_MARKER_NAME
    real_unlink = Path.unlink

    def fail_partial_marker_unlink(path: Path, missing_ok: bool = False) -> None:
        if path == failed_marker:
            raise PermissionError(errno.EACCES, f"sensitive path: {path}")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr("csvql.tui_result_store.os.open", fail_first_lease_open)
    monkeypatch.setattr(Path, "unlink", fail_partial_marker_unlink)
    store = TUIResultStore(temp_root=tmp_path)

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert error.value.kind == "permission"
    assert store.workspace_path is None
    assert failed_marker.is_file()

    stored = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=2)
    active_workspace = store.workspace_path

    assert stored.handle.is_spilled is True
    assert active_workspace == tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{'d' * 32}"

    summary = store.cleanup()

    assert summary == TUIResultCleanupSummary(
        files_removed=3,
        files_failed=1,
        workspaces_removed=1,
        workspaces_failed=1,
    )
    assert failed_workspace.is_dir()
    assert active_workspace is not None
    assert not active_workspace.exists()


def test_failed_metadata_rollback_can_be_removed_by_later_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = os.open

    def fail_lease_open(path: os.PathLike[str] | str, flags: int, mode: int = 0o777) -> int:
        if Path(path).name == TUI_RESULT_LEASE_NAME:
            raise PermissionError(errno.EACCES, f"sensitive path: {path}")
        return real_open(path, flags, mode)

    failed_workspace = tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{'b' * 32}"
    failed_marker = failed_workspace / TUI_RESULT_MARKER_NAME
    real_unlink = Path.unlink
    marker_unlink_attempts = 0

    def fail_first_marker_unlink(path: Path, missing_ok: bool = False) -> None:
        nonlocal marker_unlink_attempts
        if path == failed_marker:
            marker_unlink_attempts += 1
            if marker_unlink_attempts == 1:
                raise PermissionError(errno.EACCES, f"sensitive path: {path}")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr("csvql.tui_result_store.os.open", fail_lease_open)
    monkeypatch.setattr(Path, "unlink", fail_first_marker_unlink)
    store = TUIResultStore(temp_root=tmp_path, session_id="b" * 32)

    with pytest.raises(TUIResultStorageError):
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    summary = store.cleanup()

    assert summary == TUIResultCleanupSummary(files_removed=1, workspaces_removed=1)
    assert not failed_workspace.exists()


def test_cleanup_never_deletes_lease_path_that_store_did_not_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = os.open
    failed_workspace = tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{'b' * 32}"
    marker_path = failed_workspace / TUI_RESULT_MARKER_NAME
    lease_path = failed_workspace / TUI_RESULT_LEASE_NAME

    def fail_lease_open(path: os.PathLike[str] | str, flags: int, mode: int = 0o777) -> int:
        if Path(path) == lease_path:
            raise PermissionError(errno.EACCES, "private lease detail")
        return real_open(path, flags, mode)

    real_unlink = Path.unlink
    marker_unlink_attempts = 0

    def keep_marker_on_immediate_rollback(path: Path, missing_ok: bool = False) -> None:
        nonlocal marker_unlink_attempts
        if path == marker_path:
            marker_unlink_attempts += 1
            if marker_unlink_attempts == 1:
                raise PermissionError(errno.EACCES, "private marker detail")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr("csvql.tui_result_store.os.open", fail_lease_open)
    monkeypatch.setattr(Path, "unlink", keep_marker_on_immediate_rollback)
    store = TUIResultStore(temp_root=tmp_path, session_id="b" * 32)

    with pytest.raises(TUIResultStorageError):
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    lease_path.write_text("foreign", encoding="utf-8")
    summary = store.cleanup()

    assert lease_path.read_text(encoding="utf-8") == "foreign"
    assert summary.workspaces_failed == 1


def test_staging_open_collision_is_never_registered_or_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    workspace = store.workspace_path
    assert workspace is not None
    staging_path = workspace / f".query-2-{'f' * 16}.tmp"
    real_open = os.open

    def staging_token(nbytes: int) -> str:
        assert nbytes == 8
        return "f" * 16

    monkeypatch.setattr("csvql.tui_result_store.secrets.token_hex", staging_token)

    def collide_during_staging_open(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
    ) -> int:
        if Path(path) == staging_path and not staging_path.exists():
            staging_path.write_text("foreign", encoding="utf-8")
        return real_open(path, flags, mode)

    monkeypatch.setattr("csvql.tui_result_store.os.open", collide_during_staging_open)

    with pytest.raises(TUIResultStorageError):
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=2)

    assert staging_path.read_text(encoding="utf-8") == "foreign"
    summary = store.cleanup()
    assert staging_path.read_text(encoding="utf-8") == "foreign"
    assert summary.workspaces_failed == 1


def test_cleanup_counts_only_entries_it_actually_unlinks(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    stored = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    workspace = store.workspace_path
    assert stored.handle.temp_path is not None
    assert workspace is not None
    stored.handle.temp_path.unlink()
    (workspace / TUI_RESULT_MARKER_NAME).unlink()

    summary = store.cleanup()

    assert summary == TUIResultCleanupSummary(files_removed=1, workspaces_removed=1)


def test_cleanup_is_terminal_and_rejects_future_puts(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    store.cleanup()

    with pytest.raises(TUIResultStorageError) as error:
        store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert error.value.kind == "result_unavailable"
    assert str(tmp_path) not in error.value.user_message
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
