from __future__ import annotations

import errno
import os
import re
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from csvql.bounded_result import BoundedQueryResult, PreviewPolicy
from csvql.result_codec import encode_row_payload
from csvql.tui_result_store import (
    DEFAULT_TUI_RESULT_CAPACITY_BYTES,
    TUIResultHandle,
    TUIResultReason,
    TUIResultStorageError,
    TUIResultStore,
)

_HEADER_PREFIX_BYTES = 14
_LENGTH_BYTES = 8
_FRAME_PREFIX_BYTES = 9
_FOOTER_BYTES = 9


def _header_bytes(columns: tuple[str, ...]) -> int:
    return (
        _HEADER_PREFIX_BYTES
        + _LENGTH_BYTES
        + sum(_LENGTH_BYTES + len(column.encode("utf-8")) for column in columns)
    )


def _artifact_bytes(columns: tuple[str, ...], payloads: tuple[bytes, ...]) -> int:
    return (
        _header_bytes(columns)
        + sum(_FRAME_PREFIX_BYTES + len(payload) for payload in payloads)
        + _FOOTER_BYTES
    )


def _preview(
    rows: tuple[tuple[object, ...], ...],
    *,
    columns: tuple[str, ...] = ("value",),
    has_more_rows: bool = True,
    truncation_reason: str | None = "row_limit",
) -> BoundedQueryResult:
    payloads = tuple(encode_row_payload(row) for row in rows)
    return BoundedQueryResult(
        columns=columns,
        rows=rows,
        elapsed_ms=4.0,
        preview_payload_bytes=sum(len(payload) for payload in payloads),
        has_more_rows=has_more_rows,
        truncation_reason=cast("object", truncation_reason),
    )


def _commit_rows(
    store: TUIResultStore,
    *,
    sequence: int,
    rows: tuple[tuple[object, ...], ...],
    columns: tuple[str, ...] = ("value",),
    elapsed_ms: float = 3.0,
):
    writer = store.begin_complete(sequence=sequence, columns=columns)
    for row in rows:
        writer.append_payload(encode_row_payload(row))
    return writer.commit(elapsed_ms=elapsed_ms)


def test_default_capacity_is_exactly_one_gibibyte() -> None:
    assert DEFAULT_TUI_RESULT_CAPACITY_BYTES == 1_073_741_824


@pytest.mark.parametrize("capacity_bytes", [0, -1, True])
def test_store_rejects_nonpositive_or_boolean_capacity(
    tmp_path: Path,
    capacity_bytes: object,
) -> None:
    with pytest.raises(ValueError, match="capacity"):
        TUIResultStore(
            temp_root=tmp_path,
            capacity_bytes=capacity_bytes,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("sequence", [0, -1, True])
def test_store_rejects_nonpositive_or_boolean_sequence(
    tmp_path: Path,
    sequence: object,
) -> None:
    store = TUIResultStore(temp_root=tmp_path)

    with pytest.raises(ValueError, match="positive integer"):
        store.begin_complete(
            sequence=sequence,  # type: ignore[arg-type]
            columns=("value",),
        )

    assert store.workspace_path is None


def test_zero_row_artifact_exact_fit_and_one_byte_under(
    tmp_path: Path,
) -> None:
    columns = ("left", "right")
    exact_bytes = _artifact_bytes(columns, ())
    exact_root = tmp_path / "exact"
    exact_root.mkdir()
    exact_store = TUIResultStore(
        temp_root=exact_root,
        capacity_bytes=exact_bytes,
    )

    writer = exact_store.begin_complete(sequence=1, columns=columns)

    assert writer.progress.rows_written == 0
    assert writer.progress.logical_bytes_written == _header_bytes(columns)
    assert writer.progress.remaining_capacity_bytes == 0
    stored = writer.commit(elapsed_ms=1.0)
    assert stored.logical_bytes == exact_bytes
    assert stored.stored_row_count == 0

    under_root = tmp_path / "under"
    under_root.mkdir()
    under_store = TUIResultStore(temp_root=under_root, capacity_bytes=exact_bytes - 1)
    with pytest.raises(TUIResultStorageError) as error:
        under_store.begin_complete(sequence=1, columns=columns)

    assert error.value.kind == "capacity"
    assert under_store.workspace_path is not None
    assert sorted(path.name for path in under_store.workspace_path.iterdir()) == [
        ".lease",
        ".localql-session.json",
    ]


def test_progress_counts_written_header_and_rows_but_reserves_footer(
    tmp_path: Path,
) -> None:
    columns = ("value",)
    payload = encode_row_payload(("alpha",))
    exact_bytes = _artifact_bytes(columns, (payload,))
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes + 17)

    writer = store.begin_complete(sequence=1, columns=columns)

    assert writer.progress.logical_bytes_written == _header_bytes(columns)
    assert writer.progress.remaining_capacity_bytes == (
        exact_bytes + 17 - _header_bytes(columns) - _FOOTER_BYTES
    )

    writer.append_payload(payload)

    assert writer.progress.rows_written == 1
    assert writer.progress.logical_bytes_written == exact_bytes - _FOOTER_BYTES
    assert writer.progress.remaining_capacity_bytes == 17

    stored = writer.commit(elapsed_ms=2.5)

    assert stored.logical_bytes == exact_bytes
    assert stored.stored_row_count == 1


def test_one_byte_over_row_is_rejected_before_write_and_rollback_releases_capacity(
    tmp_path: Path,
) -> None:
    columns = ("value",)
    payload = encode_row_payload(("alpha",))
    exact_bytes = _artifact_bytes(columns, (payload,))
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes - 1)
    writer = store.begin_complete(sequence=1, columns=columns)
    before = writer.progress

    with pytest.raises(TUIResultStorageError) as error:
        writer.append_payload(payload)

    assert error.value.kind == "capacity"
    assert writer.progress == before

    writer.rollback()
    zero_row = store.begin_complete(sequence=2, columns=columns)
    assert zero_row.commit(elapsed_ms=1.0).stored_row_count == 0


def test_second_writer_is_rejected_until_first_rolls_back(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    first = store.begin_complete(sequence=1, columns=("value",))

    with pytest.raises(RuntimeError, match="writer"):
        store.begin_complete(sequence=2, columns=("value",))

    first.rollback()
    second = store.begin_complete(sequence=2, columns=("value",))
    second.rollback()


def test_multiple_complete_results_share_one_capacity_without_eviction(
    tmp_path: Path,
) -> None:
    columns = ("value",)
    first_payload = encode_row_payload(("first",))
    second_payload = encode_row_payload(("second",))
    first_bytes = _artifact_bytes(columns, (first_payload,))
    second_bytes = _artifact_bytes(columns, (second_payload,))
    store = TUIResultStore(
        temp_root=tmp_path,
        capacity_bytes=first_bytes + second_bytes,
    )

    first = _commit_rows(store, sequence=1, rows=(("first",),))
    second = _commit_rows(store, sequence=2, rows=(("second",),))

    with pytest.raises(TUIResultStorageError) as error:
        store.begin_complete(sequence=3, columns=columns)

    assert error.value.kind == "capacity"
    assert tuple(store.open_rows(first.handle).iter_rows()) == (("first",),)
    assert tuple(store.open_rows(second.handle).iter_rows()) == (("second",),)


def test_explicit_removal_releases_only_selected_result_capacity(
    tmp_path: Path,
) -> None:
    columns = ("value",)
    first_payload = encode_row_payload(("first",))
    second_payload = encode_row_payload(("second",))
    first_bytes = _artifact_bytes(columns, (first_payload,))
    second_bytes = _artifact_bytes(columns, (second_payload,))
    store = TUIResultStore(
        temp_root=tmp_path,
        capacity_bytes=first_bytes + second_bytes,
    )
    first = _commit_rows(store, sequence=1, rows=(("first",),))
    second = _commit_rows(store, sequence=2, rows=(("second",),))

    store.remove(first.handle)
    replacement = _commit_rows(store, sequence=3, rows=(("first",),))

    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.load_preview(first.handle, PreviewPolicy())
    assert tuple(store.open_rows(second.handle).iter_rows()) == (("second",),)
    assert tuple(store.open_rows(replacement.handle).iter_rows()) == (("first",),)


def test_complete_handle_is_opaque_and_survives_later_commits(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path)

    first = _commit_rows(store, sequence=1, rows=((1,),))
    _commit_rows(store, sequence=2, rows=((2,),))

    assert first.handle.sequence == 1
    assert re.fullmatch(r"[0-9a-f]{32}", first.handle.store_id)
    assert re.fullmatch(r"[0-9a-f]{32}", first.handle.nonce)
    assert not hasattr(first.handle, "temp_path")
    assert not hasattr(first.handle, "is_spilled")
    assert tuple(store.open_rows(first.handle).iter_rows()) == ((1,),)


def test_copied_reconstructed_and_foreign_handles_fail_before_file_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_root = tmp_path / "one"
    second_root = tmp_path / "two"
    first_root.mkdir()
    second_root.mkdir()
    store = TUIResultStore(temp_root=first_root)
    foreign_store = TUIResultStore(temp_root=second_root)
    stored = _commit_rows(store, sequence=1, rows=((1,),))
    foreign = _commit_rows(foreign_store, sequence=1, rows=((2,),))
    copied = replace(stored.handle)
    reconstructed = TUIResultHandle(
        sequence=stored.handle.sequence,
        store_id=stored.handle.store_id,
        nonce=stored.handle.nonce,
    )
    file_accesses = 0

    def reject_file_access(_path: Path) -> None:
        nonlocal file_accesses
        file_accesses += 1
        raise AssertionError("invalid handle reached filesystem access")

    monkeypatch.setattr(Path, "lstat", reject_file_access)

    for invalid in (copied, reconstructed, foreign.handle):
        with pytest.raises(TUIResultStorageError, match="no longer available"):
            store.load_preview(invalid, PreviewPolicy())

    assert file_accesses == 0


def test_preview_only_snapshot_uses_capacity_and_preserves_truncation_metadata(
    tmp_path: Path,
) -> None:
    rows = (("one",), ("two",))
    preview = _preview(rows)
    payloads = tuple(encode_row_payload(row) for row in rows)
    exact_bytes = _artifact_bytes(preview.columns, payloads)
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)

    stored = store.persist_preview(
        sequence=1,
        preview=preview,
        reason="user_cancelled",
        elapsed_ms=7.5,
    )

    assert stored is not None
    assert stored.kind == "preview_only"
    assert stored.reason == "user_cancelled"
    assert stored.stored_row_count == 2
    assert stored.logical_bytes == exact_bytes
    loaded = store.load_preview(stored.handle, PreviewPolicy(row_limit=10))
    assert loaded.rows == rows
    assert loaded.elapsed_ms == 7.5
    assert loaded.has_more_rows is True
    assert loaded.truncation_reason == "row_limit"
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.open_rows(stored.handle)


def test_preview_returns_none_when_it_cannot_fit_and_releases_staging(
    tmp_path: Path,
) -> None:
    preview = _preview((("one",),))
    payload = encode_row_payload(("one",))
    exact_bytes = _artifact_bytes(preview.columns, (payload,))
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes - 1)

    stored = store.persist_preview(
        sequence=1,
        preview=preview,
        reason="session_spool_limit",
        elapsed_ms=2.0,
    )

    assert stored is None
    assert store.workspace_path is not None
    assert sorted(path.name for path in store.workspace_path.iterdir()) == [
        ".lease",
        ".localql-session.json",
    ]
    zero_row = store.begin_complete(sequence=2, columns=preview.columns)
    zero_row.rollback()


def test_full_rollback_releases_capacity_before_preview_persist(
    tmp_path: Path,
) -> None:
    rows = (("preview",),)
    payload = encode_row_payload(rows[0])
    exact_bytes = _artifact_bytes(("value",), (payload,))
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    full = store.begin_complete(sequence=1, columns=("value",))
    full.append_payload(payload)

    with pytest.raises(RuntimeError, match="writer"):
        store.persist_preview(
            sequence=1,
            preview=_preview(rows),
            reason="session_spool_limit",
            elapsed_ms=4.0,
        )

    full.rollback()
    stored = store.persist_preview(
        sequence=1,
        preview=_preview(rows),
        reason="session_spool_limit",
        elapsed_ms=4.0,
    )

    assert stored is not None
    assert stored.logical_bytes == exact_bytes


def test_complete_and_preview_only_artifacts_share_capacity(
    tmp_path: Path,
) -> None:
    complete_payload = encode_row_payload(("complete",))
    preview_payload = encode_row_payload(("preview",))
    complete_bytes = _artifact_bytes(("value",), (complete_payload,))
    preview_bytes = _artifact_bytes(("value",), (preview_payload,))
    store = TUIResultStore(
        temp_root=tmp_path,
        capacity_bytes=complete_bytes + preview_bytes,
    )

    complete = _commit_rows(store, sequence=1, rows=(("complete",),))
    preview = store.persist_preview(
        sequence=2,
        preview=_preview((("preview",),)),
        reason="preservation_failed",
        elapsed_ms=5.0,
    )

    assert preview is not None
    with pytest.raises(TUIResultStorageError) as error:
        store.begin_complete(sequence=3, columns=("value",))
    assert error.value.kind == "capacity"
    assert tuple(store.open_rows(complete.handle).iter_rows()) == (("complete",),)


def test_load_preview_streams_complete_result_to_row_and_payload_limits(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    stored = _commit_rows(
        store,
        sequence=1,
        rows=(("one",), ("two",), ("three",)),
    )

    row_limited = store.load_preview(stored.handle, PreviewPolicy(row_limit=2))

    assert row_limited.rows == (("one",), ("two",))
    assert row_limited.has_more_rows is True
    assert row_limited.truncation_reason == "row_limit"

    first_payload_size = len(encode_row_payload(("one",)))
    byte_limited = store.load_preview(
        stored.handle,
        PreviewPolicy(row_limit=10, payload_limit_bytes=first_payload_size - 1),
    )

    assert byte_limited.rows == ()
    assert byte_limited.has_more_rows is True
    assert byte_limited.truncation_reason == "byte_limit"


def test_preview_loaded_with_tighter_policy_keeps_truthful_more_rows(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    stored = store.persist_preview(
        sequence=1,
        preview=_preview((("one",), ("two",))),
        reason="user_cancelled",
        elapsed_ms=2.0,
    )
    assert stored is not None

    loaded = store.load_preview(stored.handle, PreviewPolicy(row_limit=1))

    assert loaded.rows == (("one",),)
    assert loaded.has_more_rows is True
    assert loaded.truncation_reason == "row_limit"


def test_invalid_preview_reason_is_rejected_before_workspace_creation(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path)

    with pytest.raises(ValueError, match="reason"):
        store.persist_preview(
            sequence=1,
            preview=_preview((("one",),)),
            reason=cast(TUIResultReason, "unknown"),
            elapsed_ms=1.0,
        )

    assert store.workspace_path is None


def test_append_io_failure_keeps_accounting_until_rollback_then_releases_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    payload = encode_row_payload(("one",))
    exact_bytes = _artifact_bytes(columns, (payload,))
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    writer = store.begin_complete(sequence=1, columns=columns)

    def fail_append(_writer: object, _payload: bytes) -> None:
        raise OSError(errno.EIO, "private path")

    monkeypatch.setattr(
        "csvql.tui_result_store.ResultSpoolWriter.append_payload",
        fail_append,
    )

    with pytest.raises(TUIResultStorageError) as error:
        writer.append_payload(payload)

    assert error.value.kind == "io"
    writer.rollback()

    replacement = store.begin_complete(sequence=2, columns=columns)
    replacement.rollback()


def test_cleanup_invalidates_every_handle_and_is_idempotent(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    complete = _commit_rows(store, sequence=1, rows=((1,),))
    preview = store.persist_preview(
        sequence=2,
        preview=_preview(((2,),)),
        reason="user_cancelled",
        elapsed_ms=1.0,
    )
    assert preview is not None

    first = store.cleanup()
    second = store.cleanup()

    assert first.warning_count == 0
    assert second.warning_count == 0
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.load_preview(complete.handle, PreviewPolicy())
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.load_preview(preview.handle, PreviewPolicy())


def test_lost_workspace_is_invalidated_before_capacity_is_reserved_for_replacement(
    tmp_path: Path,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    first = _commit_rows(store, sequence=1, rows=())
    assert store.workspace_path is not None
    (store.workspace_path / ".localql-session.json").unlink()

    replacement = store.begin_complete(sequence=2, columns=columns)

    assert replacement.progress.remaining_capacity_bytes == 0
    assert replacement.commit(elapsed_ms=1.0).logical_bytes == exact_bytes
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.open_rows(first.handle)


def test_remove_cleans_retained_staging_alias_before_releasing_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    real_unlink = Path.unlink
    retained_once = False

    def retain_staging_once(path: Path, missing_ok: bool = False) -> None:
        nonlocal retained_once
        if path.name.endswith(".result.tmp") and not retained_once:
            retained_once = True
            raise OSError(errno.EBUSY, "staging busy")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", retain_staging_once)
    stored = _commit_rows(store, sequence=1, rows=())
    assert store.workspace_path is not None
    retained = tuple(store.workspace_path.glob(".query-1-*.result.tmp"))
    assert len(retained) == 1
    monkeypatch.setattr(Path, "unlink", real_unlink)

    store.remove(stored.handle)

    assert not retained[0].exists()
    replacement = store.begin_complete(sequence=2, columns=columns)
    replacement.rollback()


def test_remove_missing_final_cleans_retained_staging_alias_before_releasing_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    real_unlink = Path.unlink
    retained_once = False

    def retain_staging_once(path: Path, missing_ok: bool = False) -> None:
        nonlocal retained_once
        if path.name.endswith(".result.tmp") and not retained_once:
            retained_once = True
            raise OSError(errno.EBUSY, "staging busy")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", retain_staging_once)
    stored = _commit_rows(store, sequence=1, rows=())
    assert store.workspace_path is not None
    retained = tuple(store.workspace_path.glob(".query-1-*.result.tmp"))
    assert len(retained) == 1
    final_path = store.workspace_path / "query-1.result"
    monkeypatch.setattr(Path, "unlink", real_unlink)
    final_path.unlink()

    with pytest.raises(TUIResultStorageError) as error:
        store.remove(stored.handle)

    assert error.value.kind == "result_unavailable"
    assert not retained[0].exists()
    replacement = store.begin_complete(sequence=2, columns=columns)
    replacement.rollback()


def test_remove_final_disappears_after_matching_observation_cleans_owned_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    real_unlink = Path.unlink
    retained_once = False

    def retain_staging_once(path: Path, missing_ok: bool = False) -> None:
        nonlocal retained_once
        if path.name.endswith(".result.tmp") and not retained_once:
            retained_once = True
            raise OSError(errno.EBUSY, "staging busy")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", retain_staging_once)
    stored = _commit_rows(store, sequence=1, rows=())
    assert store.workspace_path is not None
    retained = tuple(store.workspace_path.glob(".query-1-*.result.tmp"))
    assert len(retained) == 1
    final_path = store.workspace_path / "query-1.result"
    monkeypatch.setattr(Path, "unlink", real_unlink)
    real_lstat = Path.lstat
    disappear_once = True

    def disappear_after_matching_lstat(path: Path) -> os.stat_result:
        nonlocal disappear_once
        result = real_lstat(path)
        if path == final_path and disappear_once:
            disappear_once = False
            real_unlink(path)
        return result

    monkeypatch.setattr(Path, "lstat", disappear_after_matching_lstat)
    with pytest.raises(TUIResultStorageError) as error:
        store.remove(stored.handle)

    assert error.value.kind == "result_unavailable"
    assert not retained[0].exists()
    replacement = store.begin_complete(sequence=2, columns=columns)
    replacement.rollback()


def test_remove_foreign_final_cleans_owned_alias_and_preserves_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    real_unlink = Path.unlink
    retained_once = False

    def retain_staging_once(path: Path, missing_ok: bool = False) -> None:
        nonlocal retained_once
        if path.name.endswith(".result.tmp") and not retained_once:
            retained_once = True
            raise OSError(errno.EBUSY, "staging busy")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", retain_staging_once)
    stored = _commit_rows(store, sequence=1, rows=())
    assert store.workspace_path is not None
    retained = tuple(store.workspace_path.glob(".query-1-*.result.tmp"))
    assert len(retained) == 1
    final_path = store.workspace_path / "query-1.result"
    monkeypatch.setattr(Path, "unlink", real_unlink)
    final_path.unlink()
    foreign_content = b"foreign replacement"
    final_path.write_bytes(foreign_content)

    with pytest.raises(TUIResultStorageError) as error:
        store.remove(stored.handle)

    assert error.value.kind == "result_unavailable"
    assert not retained[0].exists()
    assert final_path.read_bytes() == foreign_content
    replacement = store.begin_complete(sequence=2, columns=columns)
    replacement.rollback()


def test_remove_foreign_result_preserves_unrelated_handle_and_workspace(
    tmp_path: Path,
) -> None:
    columns = ("value",)
    payload = encode_row_payload((1,))
    exact_bytes = _artifact_bytes(columns, (payload,))
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes * 2)
    first = _commit_rows(store, sequence=1, rows=((1,),))
    second = _commit_rows(store, sequence=2, rows=((2,),))
    assert store.workspace_path is not None
    workspace = store.workspace_path
    foreign_path = workspace / "query-1.result"
    foreign_path.unlink()
    foreign_content = b"foreign replacement"
    foreign_path.write_bytes(foreign_content)

    with pytest.raises(TUIResultStorageError) as error:
        store.remove(first.handle)

    assert error.value.kind == "result_unavailable"
    assert store.load_preview(second.handle, PreviewPolicy()).rows == ((2,),)
    assert tuple(store.open_rows(second.handle).iter_rows()) == ((2,),)
    replacement = store.begin_complete(sequence=3, columns=columns)
    replacement.append_payload(encode_row_payload((3,)))
    replacement.commit(elapsed_ms=1.0)

    assert store.workspace_path == workspace
    assert foreign_path.read_bytes() == foreign_content
    store.cleanup()
    assert foreign_path.read_bytes() == foreign_content


def test_read_invalidation_foreign_result_preserves_unrelated_handle_and_workspace(
    tmp_path: Path,
) -> None:
    columns = ("value",)
    payload = encode_row_payload((1,))
    exact_bytes = _artifact_bytes(columns, (payload,))
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes * 2)
    first = _commit_rows(store, sequence=1, rows=((1,),))
    second = _commit_rows(store, sequence=2, rows=((2,),))
    assert store.workspace_path is not None
    workspace = store.workspace_path
    foreign_path = workspace / "query-1.result"
    foreign_path.unlink()
    foreign_content = b"foreign replacement"
    foreign_path.write_bytes(foreign_content)

    with pytest.raises(TUIResultStorageError) as error:
        store.load_preview(first.handle, PreviewPolicy())

    assert error.value.kind == "result_unavailable"
    assert store.load_preview(second.handle, PreviewPolicy()).rows == ((2,),)
    assert tuple(store.open_rows(second.handle).iter_rows()) == ((2,),)
    replacement = store.begin_complete(sequence=3, columns=columns)
    replacement.append_payload(encode_row_payload((3,)))
    replacement.commit(elapsed_ms=1.0)

    assert store.workspace_path == workspace
    assert foreign_path.read_bytes() == foreign_content
    store.cleanup()
    assert foreign_path.read_bytes() == foreign_content


def test_remove_revalidates_identity_before_unlinking_a_matching_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    stored = _commit_rows(store, sequence=1, rows=())
    assert store.workspace_path is not None
    final_path = store.workspace_path / "query-1.result"
    real_lstat = Path.lstat
    real_unlink = Path.unlink
    foreign_content = b"foreign replacement"
    replace_once = True

    def replace_after_matching_lstat(path: Path) -> os.stat_result:
        nonlocal replace_once
        result = real_lstat(path)
        if path == final_path and replace_once:
            replace_once = False
            real_unlink(path)
            path.write_bytes(foreign_content)
        return result

    monkeypatch.setattr(Path, "lstat", replace_after_matching_lstat)
    with pytest.raises(TUIResultStorageError) as error:
        store.remove(stored.handle)

    assert error.value.kind == "result_unavailable"
    assert final_path.read_bytes() == foreign_content
    replacement = store.begin_complete(sequence=2, columns=columns)
    replacement.rollback()


def test_read_invalidation_revalidates_identity_before_unlinking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    stored = _commit_rows(store, sequence=1, rows=())
    assert store.workspace_path is not None
    final_path = store.workspace_path / "query-1.result"
    with final_path.open("r+b") as artifact:
        artifact.write(b"X")
    real_lstat = Path.lstat
    real_unlink = Path.unlink
    foreign_content = b"foreign replacement"
    result_observations = 0

    def replace_during_invalidation_lstat(path: Path) -> os.stat_result:
        nonlocal result_observations
        result = real_lstat(path)
        if path == final_path:
            result_observations += 1
            if result_observations == 2:
                real_unlink(path)
                path.write_bytes(foreign_content)
        return result

    monkeypatch.setattr(Path, "lstat", replace_during_invalidation_lstat)
    with pytest.raises(TUIResultStorageError) as error:
        store.load_preview(stored.handle, PreviewPolicy())

    assert error.value.kind == "result_unavailable"
    assert final_path.read_bytes() == foreign_content
    replacement = store.begin_complete(sequence=2, columns=columns)
    replacement.rollback()


def test_remove_same_identity_size_mismatch_preserves_path_and_releases_capacity(
    tmp_path: Path,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    stored = _commit_rows(store, sequence=1, rows=())
    assert store.workspace_path is not None
    final_path = store.workspace_path / "query-1.result"
    with final_path.open("ab") as artifact:
        artifact.write(b"X")

    with pytest.raises(TUIResultStorageError) as error:
        store.remove(stored.handle)

    assert error.value.kind == "result_unavailable"
    assert final_path.read_bytes().endswith(b"X")
    replacement = store.begin_complete(sequence=2, columns=columns)
    replacement.rollback()

    cleanup = store.cleanup()

    assert cleanup.workspaces_failed == 1
    assert final_path.read_bytes().endswith(b"X")


def test_remove_foreign_final_alias_cleanup_failure_remains_capacity_accounted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    real_unlink = Path.unlink

    def retain_staging(path: Path, missing_ok: bool = False) -> None:
        if path.name.endswith(".result.tmp"):
            raise OSError(errno.EBUSY, "staging busy")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", retain_staging)
    stored = _commit_rows(store, sequence=1, rows=())
    assert store.workspace_path is not None
    retained = tuple(store.workspace_path.glob(".query-1-*.result.tmp"))
    assert len(retained) == 1
    final_path = store.workspace_path / "query-1.result"
    final_path.unlink()
    foreign_content = b"foreign replacement"
    final_path.write_bytes(foreign_content)

    with pytest.raises(TUIResultStorageError) as error:
        store.remove(stored.handle)

    assert error.value.kind == "result_unavailable"
    assert retained[0].exists()
    assert final_path.read_bytes() == foreign_content
    monkeypatch.setattr(Path, "unlink", real_unlink)
    with pytest.raises(TUIResultStorageError) as capacity_error:
        store.begin_complete(sequence=2, columns=columns)
    assert capacity_error.value.kind == "capacity"

    store.cleanup()

    assert not retained[0].exists()
    assert final_path.read_bytes() == foreign_content


def test_remove_uncertain_missing_final_and_alias_cleanup_failure_retains_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    real_unlink = Path.unlink

    def retain_staging(path: Path, missing_ok: bool = False) -> None:
        if path.name.endswith(".result.tmp"):
            raise OSError(errno.EBUSY, "staging busy")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", retain_staging)
    stored = _commit_rows(store, sequence=1, rows=())
    assert store.workspace_path is not None
    retained = tuple(store.workspace_path.glob(".query-1-*.result.tmp"))
    assert len(retained) == 1
    final_path = store.workspace_path / "query-1.result"
    final_path.unlink()
    real_lstat = Path.lstat

    def fail_result_lstat(path: Path) -> os.stat_result:
        if path == final_path:
            raise OSError(errno.EIO, "result observation failed")
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", fail_result_lstat)
    with pytest.raises(TUIResultStorageError) as error:
        store.remove(stored.handle)

    assert error.value.kind == "result_unavailable"
    assert retained[0].exists()
    monkeypatch.setattr(Path, "lstat", real_lstat)
    monkeypatch.setattr(Path, "unlink", real_unlink)
    with pytest.raises(TUIResultStorageError) as capacity_error:
        store.begin_complete(sequence=2, columns=columns)
    assert capacity_error.value.kind == "capacity"

    cleanup = store.cleanup()

    assert cleanup.warning_count == 0
    assert not retained[0].exists()


def test_remove_lstat_uncertainty_retains_capacity_until_owned_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    stored = _commit_rows(store, sequence=1, rows=())
    assert store.workspace_path is not None
    final_path = store.workspace_path / "query-1.result"
    real_lstat = Path.lstat

    def fail_result_lstat(path: Path) -> os.stat_result:
        if path == final_path:
            raise OSError(errno.EIO, "result observation failed")
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", fail_result_lstat)
    with pytest.raises(TUIResultStorageError) as error:
        store.remove(stored.handle)

    assert error.value.kind == "result_unavailable"
    monkeypatch.setattr(Path, "lstat", real_lstat)
    assert final_path.exists()
    with pytest.raises(TUIResultStorageError) as capacity_error:
        store.begin_complete(sequence=2, columns=columns)
    assert capacity_error.value.kind == "capacity"

    cleanup = store.cleanup()

    assert cleanup.warning_count == 0
    assert not final_path.exists()


def test_read_invalidation_lstat_uncertainty_retains_capacity_until_owned_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    stored = _commit_rows(store, sequence=1, rows=())
    assert store.workspace_path is not None
    final_path = store.workspace_path / "query-1.result"
    real_lstat = Path.lstat

    def fail_result_lstat(path: Path) -> os.stat_result:
        if path == final_path:
            raise OSError(errno.EIO, "result observation failed")
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", fail_result_lstat)
    with pytest.raises(TUIResultStorageError) as error:
        store.load_preview(stored.handle, PreviewPolicy())

    assert error.value.kind == "result_unavailable"
    monkeypatch.setattr(Path, "lstat", real_lstat)
    assert final_path.exists()
    with pytest.raises(TUIResultStorageError) as capacity_error:
        store.begin_complete(sequence=2, columns=columns)
    assert capacity_error.value.kind == "capacity"

    cleanup = store.cleanup()

    assert cleanup.warning_count == 0
    assert not final_path.exists()


def test_footer_or_fsync_failure_releases_reserved_capacity_after_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    writer = store.begin_complete(sequence=1, columns=columns)

    def fail_fsync(_descriptor: int) -> None:
        raise OSError(errno.EIO, "private fsync detail")

    monkeypatch.setattr("csvql.result_spool.os.fsync", fail_fsync)

    with pytest.raises(TUIResultStorageError) as error:
        writer.commit(elapsed_ms=1.0)

    assert error.value.kind == "io"
    monkeypatch.setattr("csvql.result_spool.os.fsync", os.fsync)
    replacement = store.begin_complete(sequence=2, columns=columns)
    replacement.rollback()


def test_handle_nonce_failure_rolls_back_before_publication_and_releases_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    writer = store.begin_complete(sequence=1, columns=columns)

    def fail_nonce() -> str:
        raise TUIResultStorageError(
            "Unable to create a secure result handle.",
            kind="io",
        )

    monkeypatch.setattr(store, "_new_handle_nonce", fail_nonce)

    with pytest.raises(TUIResultStorageError) as error:
        writer.commit(elapsed_ms=1.0)

    assert error.value.kind == "io"
    assert store.workspace_path is not None
    assert not (store.workspace_path / "query-1.result").exists()
    replacement = store.begin_complete(sequence=2, columns=columns)
    replacement.rollback()


def test_unregistered_commit_cleanup_failure_remains_capacity_accounted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = ("value",)
    exact_bytes = _artifact_bytes(columns, ())
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=exact_bytes)
    writer = store.begin_complete(sequence=1, columns=columns)
    real_commit = writer._spool_writer.commit
    real_unlink = Path.unlink

    def mismatched_commit():
        metadata = real_commit()
        return replace(metadata, logical_bytes=metadata.logical_bytes + 1)

    def retain_unregistered_final(path: Path, missing_ok: bool = False) -> None:
        if path.name == "query-1.result":
            raise OSError(errno.EBUSY, "final busy")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(writer._spool_writer, "commit", mismatched_commit)
    monkeypatch.setattr(Path, "unlink", retain_unregistered_final)

    with pytest.raises(TUIResultStorageError) as error:
        writer.commit(elapsed_ms=1.0)

    assert error.value.kind == "serialization"
    monkeypatch.setattr(Path, "unlink", real_unlink)
    with pytest.raises(TUIResultStorageError) as capacity_error:
        store.begin_complete(sequence=2, columns=columns)
    assert capacity_error.value.kind == "capacity"
    cleanup = store.cleanup()
    assert cleanup.warning_count == 1
    assert cleanup.workspaces_removed == 1
