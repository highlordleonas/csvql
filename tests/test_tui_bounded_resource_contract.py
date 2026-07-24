"""End-to-end bounded ownership contracts for retained TUI results."""

from dataclasses import fields
from pathlib import Path

import pytest

from csvql.bounded_result import PreviewPolicy
from csvql.result_codec import encode_row_payload
from csvql.tui_result_store import (
    TUIResultStorageError,
    TUIResultStore,
    TUIStoredResult,
)
from csvql.tui_results import make_bounded_result_view_state
from csvql.tui_state import TUIQueryHistoryItem, TUIResultRecord, TUISessionState

_HEADER_PREFIX_BYTES = 14
_LENGTH_BYTES = 8
_FRAME_PREFIX_BYTES = 9
_FOOTER_BYTES = 9


def _artifact_bytes(columns: tuple[str, ...], payloads: tuple[bytes, ...]) -> int:
    header_bytes = (
        _HEADER_PREFIX_BYTES
        + _LENGTH_BYTES
        + sum(_LENGTH_BYTES + len(column.encode("utf-8")) for column in columns)
    )
    return (
        header_bytes
        + sum(_FRAME_PREFIX_BYTES + len(payload) for payload in payloads)
        + _FOOTER_BYTES
    )


def _large_result_payloads(sequence: int) -> tuple[bytes, ...]:
    return tuple(
        encode_row_payload((row_index, f"{sequence}:{row_index:02d}:" + ("x" * 2_048)))
        for row_index in range(48)
    )


def _commit_payloads(
    store: TUIResultStore,
    *,
    sequence: int,
    columns: tuple[str, ...],
    payloads: tuple[bytes, ...],
) -> TUIStoredResult:
    writer = store.begin_complete(sequence=sequence, columns=columns)
    for payload in payloads:
        writer.append_payload(payload)
    return writer.commit(elapsed_ms=float(sequence))


def _complete_artifact_path(store: TUIResultStore, sequence: int) -> Path:
    workspace = store.workspace_path
    assert workspace is not None
    return workspace / f"query-{sequence}.result"


def test_many_large_results_remain_bounded_without_eviction_or_preview_multiplication(
    tmp_path: Path,
) -> None:
    columns = ("row_index", "payload")
    payloads_by_sequence = {sequence: _large_result_payloads(sequence) for sequence in range(1, 9)}
    capacity_bytes = sum(
        _artifact_bytes(columns, payloads) for payloads in payloads_by_sequence.values()
    )
    assert capacity_bytes < 1_000_000
    store = TUIResultStore(
        temp_root=tmp_path,
        capacity_bytes=capacity_bytes,
    )
    state = TUISessionState()
    preview_policy = PreviewPolicy(row_limit=3, payload_limit_bytes=32 * 1024)
    stored_results: list[TUIStoredResult] = []

    for sequence, payloads in payloads_by_sequence.items():
        stored = _commit_payloads(
            store,
            sequence=sequence,
            columns=columns,
            payloads=payloads,
        )
        stored_results.append(stored)
        artifact_path = _complete_artifact_path(store, sequence)
        assert stored.logical_bytes == artifact_path.stat().st_size
        assert sum(result.logical_bytes for result in stored_results) <= capacity_bytes
        assert (
            sum(
                _complete_artifact_path(store, result.handle.sequence).stat().st_size
                for result in stored_results
            )
            <= capacity_bytes
        )

        preview = store.load_preview(stored.handle, preview_policy)
        view = make_bounded_result_view_state(
            preview,
            source_result_sequence=sequence,
        )
        state.record_query_result(
            sequence,
            f"SELECT {sequence}",
            record=TUIResultRecord(
                handle=stored.handle,
                state="complete",
                reason=None,
                columns=columns,
                preview_row_count=len(view.display_rows),
                full_row_count=stored.stored_row_count,
                elapsed_ms=stored.elapsed_ms,
            ),
            result_view=view,
        )

    assert len(state.query_history) == len(stored_results)
    assert {field.name for field in fields(TUIQueryHistoryItem)}.isdisjoint(
        {"rows", "display_rows", "preview_rows"}
    )
    assert {field.name for field in fields(TUIResultRecord)}.isdisjoint(
        {"rows", "display_rows", "preview_rows"}
    )
    assert len(state.result_view.display_rows) == preview_policy.row_limit

    with pytest.raises(TUIResultStorageError) as capacity_error:
        store.begin_complete(sequence=9, columns=columns)
    assert capacity_error.value.kind == "capacity"

    for stored in stored_results:
        assert state.restore_query_result(stored.handle.sequence) is True
        preview = store.load_preview(stored.handle, preview_policy)
        state.result_view = make_bounded_result_view_state(
            preview,
            source_result_sequence=stored.handle.sequence,
        )
        assert len(state.result_view.display_rows) == preview_policy.row_limit
        assert len(tuple(store.open_rows(stored.handle).iter_rows())) == 48

    selected = stored_results[3]
    selected_bytes = selected.logical_bytes
    store.remove(selected.handle)
    assert state.remove_query_result(selected.handle.sequence) == selected.handle
    assert not _complete_artifact_path(store, selected.handle.sequence).exists()
    assert (
        sum(
            _complete_artifact_path(store, result.handle.sequence).stat().st_size
            for result in stored_results
            if result is not selected
        )
        == capacity_bytes - selected_bytes
    )
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.open_rows(selected.handle)

    replacement = _commit_payloads(
        store,
        sequence=9,
        columns=columns,
        payloads=payloads_by_sequence[selected.handle.sequence],
    )
    assert replacement.logical_bytes == selected_bytes
    assert (
        sum(
            _complete_artifact_path(store, result.handle.sequence).stat().st_size
            for result in stored_results
            if result is not selected
        )
        + _complete_artifact_path(store, replacement.handle.sequence).stat().st_size
        == capacity_bytes
    )
    for stored in stored_results:
        if stored is selected:
            continue
        assert len(tuple(store.open_rows(stored.handle).iter_rows())) == 48
