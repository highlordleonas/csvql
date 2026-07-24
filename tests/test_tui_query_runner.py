"""Pure preservation-runner contracts for the LocalQL TUI."""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from csvql.bounded_result import PreviewPolicy
from csvql.engine import CSVQLEngine
from csvql.operation import OperationContext, OperationToken
from csvql.result_codec import encode_row_payload
from csvql.tui_query_runner import (
    TUICancelledBeforePreviewEvent,
    TUICompleteEvent,
    TUIFailedBeforePreviewEvent,
    TUINoResultEvent,
    TUIPreservationProgressEvent,
    TUIPreviewOnlyEvent,
    TUIPreviewReadyEvent,
    TUIRunRequest,
    run_tui_request,
)
from csvql.tui_result_store import (
    TUIResultStorageError,
    TUIResultStore,
    TUIResultWriter,
)
from csvql.tui_state import TUISource
from csvql.tui_workflows import build_tui_run_request

_HEADER_PREFIX_BYTES = 14
_LENGTH_BYTES = 8
_FRAME_PREFIX_BYTES = 9
_FOOTER_BYTES = 9
_DEFAULT_TEST_POLICY = PreviewPolicy(row_limit=2, payload_limit_bytes=1_024)


def _request(
    *statements: str,
    sequences: tuple[int, ...] | None = None,
    policy: PreviewPolicy = _DEFAULT_TEST_POLICY,
) -> TUIRunRequest:
    effective_sequences = sequences or tuple(range(1, len(statements) + 1))
    return TUIRunRequest(
        statements=tuple(statements),
        sequences=effective_sequences,
        sources=(),
        fallback_sources=(),
        preview_policy=policy,
        run_mode="buffer" if len(statements) > 1 else "current",
        submission_order=1,
    )


def _header_bytes(columns: tuple[str, ...]) -> int:
    return (
        _HEADER_PREFIX_BYTES
        + _LENGTH_BYTES
        + sum(_LENGTH_BYTES + len(column.encode("utf-8")) for column in columns)
    )


class _RecordingEngine(CSVQLEngine):
    def __init__(
        self,
        *,
        operation: OperationContext,
        statements: list[str],
        closed: list[bool],
    ) -> None:
        super().__init__(operation=operation)
        self._recorded_statements = statements
        self._recorded_closed = closed

    def stream(
        self,
        sql: str,
        params: tuple[object, ...] | None = None,
    ):
        self._recorded_statements.append(sql)
        return super().stream(sql, params)

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._recorded_closed.append(True)


def _recording_engine_factory(
    statements: list[str],
    closed: list[bool],
):
    def factory(*, operation: OperationContext) -> CSVQLEngine:
        return _RecordingEngine(
            operation=operation,
            statements=statements,
            closed=closed,
        )

    return factory


def test_run_request_and_events_are_frozen_value_snapshots() -> None:
    request = _request("SELECT 1")
    preview_event = TUIPreviewReadyEvent(
        sequence=1,
        preview=None,  # type: ignore[arg-type]
    )

    with pytest.raises(FrozenInstanceError):
        request.statements = ("SELECT 2",)
    with pytest.raises(FrozenInstanceError):
        preview_event.sequence = 2

    assert request.statements == ("SELECT 1",)
    assert request.sequences == (1,)
    assert request.sources == ()
    assert request.fallback_sources == ()


def test_one_execution_encodes_each_row_once_and_preserves_complete_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded_rows: list[tuple[object, ...]] = []
    real_encode = encode_row_payload

    def recording_encode(row: tuple[object, ...]) -> bytes:
        encoded_rows.append(row)
        return real_encode(row)

    monkeypatch.setattr(
        "csvql.tui_query_runner.encode_row_payload",
        recording_encode,
    )
    events: list[object] = []
    statements: list[str] = []
    closed: list[bool] = []
    store = TUIResultStore(temp_root=tmp_path)

    run_tui_request(
        _request("SELECT range AS value FROM range(5)"),
        result_store=store,
        event_sink=events.append,
        operation=OperationContext(OperationToken()),
        engine_factory=_recording_engine_factory(statements, closed),
        fetch_batch_size=2,
        progress_row_interval=2,
    )

    previews = [event for event in events if isinstance(event, TUIPreviewReadyEvent)]
    completes = [event for event in events if isinstance(event, TUICompleteEvent)]
    assert statements == ["SELECT range AS value FROM range(5)"]
    assert closed == [True]
    assert encoded_rows == [(0,), (1,), (2,), (3,), (4,)]
    assert len(previews) == 1
    assert previews[0].preview.rows == ((0,), (1,))
    assert previews[0].preview.has_more_rows is True
    assert len(completes) == 1
    assert completes[0].stored.stored_row_count == 5
    assert events.index(previews[0]) < events.index(completes[0])
    assert tuple(store.open_rows(completes[0].stored.handle).iter_rows()) == (
        (0,),
        (1,),
        (2,),
        (3,),
        (4,),
    )


def test_eof_publishes_complete_preview_before_final_progress_and_commit(
    tmp_path: Path,
) -> None:
    events: list[object] = []
    store = TUIResultStore(temp_root=tmp_path)

    run_tui_request(
        _request(
            "SELECT range AS value FROM range(2)",
            policy=PreviewPolicy(row_limit=10, payload_limit_bytes=1_024),
        ),
        result_store=store,
        event_sink=events.append,
        operation=OperationContext(OperationToken()),
        fetch_batch_size=1,
    )

    preview_index = next(
        index for index, event in enumerate(events) if isinstance(event, TUIPreviewReadyEvent)
    )
    progress_indexes = [
        index
        for index, event in enumerate(events)
        if isinstance(event, TUIPreservationProgressEvent)
    ]
    complete_index = next(
        index for index, event in enumerate(events) if isinstance(event, TUICompleteEvent)
    )
    preview = events[preview_index]
    complete = events[complete_index]
    assert isinstance(preview, TUIPreviewReadyEvent)
    assert isinstance(complete, TUICompleteEvent)
    assert preview.preview.rows == ((0,), (1,))
    assert preview.preview.has_more_rows is False
    assert progress_indexes
    assert preview_index < progress_indexes[-1] < complete_index
    final_progress = events[progress_indexes[-1]]
    assert isinstance(final_progress, TUIPreservationProgressEvent)
    assert final_progress.progress.rows_written == 2
    assert final_progress.progress.logical_bytes_written == complete.stored.logical_bytes


def test_capacity_after_preview_rolls_back_full_spool_and_persists_preview_only(
    tmp_path: Path,
) -> None:
    columns = ("value",)
    payload = encode_row_payload((0,))
    capacity = _header_bytes(columns) + _FOOTER_BYTES + (2 * (_FRAME_PREFIX_BYTES + len(payload)))
    store = TUIResultStore(temp_root=tmp_path, capacity_bytes=capacity)
    events: list[object] = []

    run_tui_request(
        _request(
            "SELECT range AS value FROM range(10)",
            policy=PreviewPolicy(row_limit=1, payload_limit_bytes=1_024),
        ),
        result_store=store,
        event_sink=events.append,
        operation=OperationContext(OperationToken()),
        fetch_batch_size=1,
    )

    preview_only = next(event for event in events if isinstance(event, TUIPreviewOnlyEvent))
    assert preview_only.reason == "session_spool_limit"
    assert preview_only.preview.rows == ((0,),)
    assert preview_only.stored is not None
    assert preview_only.stored.kind == "preview_only"
    assert preview_only.stored.stored_row_count == 1
    assert not any(isinstance(event, TUICompleteEvent) for event in events)
    assert store.load_preview(
        preview_only.stored.handle,
        PreviewPolicy(row_limit=10, payload_limit_bytes=1_024),
    ).rows == ((0,),)


def test_cancellation_after_preview_persists_preview_only(
    tmp_path: Path,
) -> None:
    events: list[object] = []
    operation = OperationContext(OperationToken())
    store = TUIResultStore(temp_root=tmp_path)

    def emit(event: object) -> None:
        events.append(event)
        if isinstance(event, TUIPreviewReadyEvent):
            operation.request_cancel()

    run_tui_request(
        _request(
            "SELECT range AS value FROM range(10)",
            policy=PreviewPolicy(row_limit=1, payload_limit_bytes=1_024),
        ),
        result_store=store,
        event_sink=emit,
        operation=operation,
        fetch_batch_size=1,
    )

    preview_only = next(event for event in events if isinstance(event, TUIPreviewOnlyEvent))
    assert preview_only.reason == "user_cancelled"
    assert preview_only.stored is not None
    assert not any(isinstance(event, TUICompleteEvent) for event in events)


def test_pre_cancelled_request_emits_cancelled_before_preview_without_workspace(
    tmp_path: Path,
) -> None:
    operation = OperationContext(OperationToken())
    operation.request_cancel()
    store = TUIResultStore(temp_root=tmp_path)
    events: list[object] = []

    run_tui_request(
        _request("SELECT 1"),
        result_store=store,
        event_sink=events.append,
        operation=operation,
    )

    assert [type(event) for event in events] == [TUICancelledBeforePreviewEvent]
    assert store.workspace_path is None


def test_run_buffer_is_sequential_in_one_session_and_stops_on_sql_failure(
    tmp_path: Path,
) -> None:
    statements: list[str] = []
    closed: list[bool] = []
    events: list[object] = []
    store = TUIResultStore(temp_root=tmp_path)

    run_tui_request(
        _request(
            "CREATE TEMP TABLE scratch AS SELECT 7 AS value",
            "SELECT value FROM scratch",
            "SELECT * FROM missing_table",
            "SELECT 99",
            sequences=(1, 2, 3, 4),
        ),
        result_store=store,
        event_sink=events.append,
        operation=OperationContext(OperationToken()),
        engine_factory=_recording_engine_factory(statements, closed),
    )

    assert statements == [
        "CREATE TEMP TABLE scratch AS SELECT 7 AS value",
        "SELECT value FROM scratch",
        "SELECT * FROM missing_table",
    ]
    assert closed == [True]
    assert len([event for event in events if isinstance(event, TUICompleteEvent)]) == 2
    failure = next(event for event in events if isinstance(event, TUIFailedBeforePreviewEvent))
    assert failure.sequence == 3
    assert failure.error_message.startswith("DuckDB query failed:")
    assert failure.suggestion == "Check table names, column names, and SQL syntax."


def test_failure_after_preview_rolls_back_and_persists_preview_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []
    store = TUIResultStore(temp_root=tmp_path)
    real_append = TUIResultWriter.append_payload
    complete_payload_calls = 0

    def fail_third_complete_payload(
        writer: TUIResultWriter,
        payload: bytes,
    ) -> None:
        nonlocal complete_payload_calls
        if writer._kind == "complete":
            complete_payload_calls += 1
            if complete_payload_calls == 3:
                raise TUIResultStorageError(
                    "Sanitized preservation failure.",
                    kind="io",
                )
        real_append(writer, payload)

    monkeypatch.setattr(
        TUIResultWriter,
        "append_payload",
        fail_third_complete_payload,
    )

    run_tui_request(
        _request(
            "SELECT range AS value FROM range(10)",
            policy=PreviewPolicy(row_limit=1, payload_limit_bytes=1_024),
        ),
        result_store=store,
        event_sink=events.append,
        operation=OperationContext(OperationToken()),
        fetch_batch_size=1,
    )

    preview_only = next(event for event in events if isinstance(event, TUIPreviewOnlyEvent))
    assert preview_only.reason == "preservation_failed"
    assert preview_only.stored is not None
    assert preview_only.stored.kind == "preview_only"
    assert preview_only.preview.rows == ((0,),)
    assert not any(isinstance(event, TUICompleteEvent) for event in events)


def test_no_column_stream_closes_without_creating_result_artifact(
    tmp_path: Path,
) -> None:
    closed: list[str] = []

    class EmptyStream:
        columns: tuple[str, ...] = ()
        elapsed_ms = 2.5

        def close(self) -> None:
            closed.append("stream")

        def request_interrupt(self) -> None:
            closed.append("interrupt")

    class EmptyEngine:
        def __enter__(self) -> EmptyEngine:
            return self

        def __exit__(self, *exc_info: object) -> None:
            closed.append("engine")

        def prepare_sources(self, sources: object) -> None:
            assert sources == ()

        def stream(self, sql: str) -> EmptyStream:
            assert sql == "CREATE TABLE scratch(id INTEGER)"
            return EmptyStream()

    events: list[object] = []
    store = TUIResultStore(temp_root=tmp_path)

    run_tui_request(
        _request("CREATE TABLE scratch(id INTEGER)"),
        result_store=store,
        event_sink=events.append,
        operation=OperationContext(OperationToken()),
        engine_factory=lambda **_kwargs: EmptyEngine(),  # type: ignore[arg-type]
    )

    assert events == [TUINoResultEvent(sequence=1, elapsed_ms=2.5)]
    assert closed == ["stream", "engine"]
    assert store.workspace_path is None


def test_request_builder_snapshots_inputs_and_runtime_revalidates_source(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("id\n1\n", encoding="utf-8")
    source_inputs = [TUISource(name="orders", path=csv_path, origin="session")]
    statement_inputs = ["SELECT * FROM orders"]
    sequence_inputs = [7]
    policy = PreviewPolicy(row_limit=3, payload_limit_bytes=1_024)

    request = build_tui_run_request(
        source_inputs,
        statement_inputs,
        sequences=sequence_inputs,
        preview_policy=policy,
        run_mode="current",
        submission_order=4,
        start_dir=tmp_path,
    )
    source_inputs.clear()
    statement_inputs[0] = "SELECT 99"
    sequence_inputs[0] = 99

    assert request.statements == ("SELECT * FROM orders",)
    assert request.sequences == (7,)
    assert request.preview_policy is policy
    assert request.sources[0].spec.alias == "orders"
    assert request.submission_order == 4

    csv_path.write_text("id\n1\n2\n", encoding="utf-8")
    events: list[object] = []
    run_tui_request(
        request,
        result_store=TUIResultStore(temp_root=tmp_path),
        event_sink=events.append,
        operation=OperationContext(OperationToken()),
    )

    failure = next(event for event in events if isinstance(event, TUIFailedBeforePreviewEvent))
    assert failure.sequence == 7
    assert "changed" in failure.error_message.lower()
    assert not any(isinstance(event, TUIPreviewReadyEvent) for event in events)


def test_runner_has_no_textual_dependency() -> None:
    import csvql.tui_query_runner as runner

    source = inspect.getsource(runner)
    assert "import textual" not in source
    assert "from textual" not in source
