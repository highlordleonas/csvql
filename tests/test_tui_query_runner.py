"""Pure preservation-runner contracts for the LocalQL TUI."""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from csvql.bounded_result import PreviewPolicy
from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVQLError
from csvql.operation import OperationContext, OperationToken
from csvql.result_codec import encode_row_payload
from csvql.result_stream import CURSOR_CLEANUP_UNCERTAINTY_NOTE, ResultBatch
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
    TUIStoredResult,
)
from csvql.tui_state import TUISource
from csvql.tui_workflows import build_tui_run_request

_HEADER_PREFIX_BYTES = 14
_LENGTH_BYTES = 8
_FRAME_PREFIX_BYTES = 9
_FOOTER_BYTES = 9
_DEFAULT_TEST_POLICY = PreviewPolicy(row_limit=2, payload_limit_bytes=1_024)
_BINDING_CLEANUP_NOTE = "Cleanup uncertainty: one or more source bindings could not be closed."
_CONNECTION_CLEANUP_NOTE = "Cleanup uncertainty: the engine connection could not be closed."


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
        super().close()

    def __exit__(self, *exc_info: object) -> None:
        try:
            super().__exit__(*exc_info)
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


class _StaticStream:
    def __init__(
        self,
        batches: list[ResultBatch],
        *,
        elapsed_ms: float = 1.0,
        close_error: BaseException | None = None,
        interrupt_error: BaseException | None = None,
    ) -> None:
        self.columns = ("value",)
        self.elapsed_ms = elapsed_ms
        self._batches = list(batches)
        self._close_error = close_error
        self._interrupt_error = interrupt_error

    def fetch_rows(self, _max_rows: int) -> ResultBatch:
        return self._batches.pop(0)

    def request_interrupt(self) -> None:
        if self._interrupt_error is not None:
            raise self._interrupt_error

    def close(self) -> None:
        if self._close_error is not None:
            raise self._close_error


class _StaticEngine:
    def __init__(
        self,
        stream: _StaticStream,
        *,
        exit_notes: tuple[str, ...] = (),
    ) -> None:
        self._stream = stream
        self._exit_notes = exit_notes

    def __enter__(self) -> _StaticEngine:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        _tb: object,
    ) -> None:
        if exc is not None:
            for note in self._exit_notes:
                exc.add_note(note)

    def prepare_sources(self, sources: object) -> None:
        assert sources == ()

    def stream(self, sql: str) -> _StaticStream:
        assert sql
        return self._stream


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


def test_initial_full_spool_capacity_shortfall_still_yields_same_execution_preview_only(
    tmp_path: Path,
) -> None:
    events: list[tuple[object, list[bool]]] = []
    statements: list[str] = []
    closed: list[bool] = []
    columns = ("value",)
    store = TUIResultStore(
        temp_root=tmp_path,
        capacity_bytes=_header_bytes(columns) + _FOOTER_BYTES - 1,
    )

    def emit(event: object) -> None:
        events.append((event, closed.copy()))

    run_tui_request(
        _request(
            "SELECT range AS value FROM range(10)",
            policy=PreviewPolicy(row_limit=1, payload_limit_bytes=1_024),
        ),
        result_store=store,
        event_sink=emit,
        operation=OperationContext(OperationToken()),
        engine_factory=_recording_engine_factory(statements, closed),
        fetch_batch_size=1,
    )

    preview = next(event for event, _closed in events if isinstance(event, TUIPreviewReadyEvent))
    preview_only, closed_at_preview_only = next(
        (event, event_closed)
        for event, event_closed in events
        if isinstance(event, TUIPreviewOnlyEvent)
    )
    assert isinstance(preview, TUIPreviewReadyEvent)
    assert isinstance(preview_only, TUIPreviewOnlyEvent)
    assert statements == ["SELECT range AS value FROM range(10)"]
    assert preview.preview.rows == ((0,),)
    assert preview_only.reason == "session_spool_limit"
    assert preview_only.preview.rows == ((0,),)
    assert preview_only.stored is None
    assert closed_at_preview_only == [True]
    assert not any(isinstance(event, TUIFailedBeforePreviewEvent) for event, _ in events)


def test_mid_spool_capacity_before_preview_finalization_keeps_same_execution_preview_only(
    tmp_path: Path,
) -> None:
    events: list[object] = []
    columns = ("value",)
    store = TUIResultStore(
        temp_root=tmp_path,
        capacity_bytes=_header_bytes(columns) + _FOOTER_BYTES,
    )

    run_tui_request(
        _request(
            "SELECT range AS value FROM range(10)",
            policy=PreviewPolicy(row_limit=10, payload_limit_bytes=1_024),
        ),
        result_store=store,
        event_sink=events.append,
        operation=OperationContext(OperationToken()),
        fetch_batch_size=1,
    )

    preview_only = next(event for event in events if isinstance(event, TUIPreviewOnlyEvent))
    assert preview_only.reason == "session_spool_limit"
    assert preview_only.preview.rows == ((0,),)
    assert preview_only.preview.has_more_rows is True
    assert preview_only.preview.truncation_reason is None
    assert preview_only.stored is None
    assert not any(isinstance(event, TUIFailedBeforePreviewEvent) for event in events)


def test_initial_capacity_preview_only_carries_interrupt_cleanup_note(tmp_path: Path) -> None:
    events: list[object] = []
    columns = ("value",)
    store = TUIResultStore(
        temp_root=tmp_path,
        capacity_bytes=_header_bytes(columns) + _FOOTER_BYTES - 1,
    )
    stream = _StaticStream(
        [
            ResultBatch(rows=((0,),), exhausted=False),
            ResultBatch(rows=((1,),), exhausted=False),
        ],
        interrupt_error=RuntimeError("private interrupt detail"),
    )

    run_tui_request(
        _request(
            "SELECT range AS value FROM range(10)",
            policy=PreviewPolicy(row_limit=1, payload_limit_bytes=1_024),
        ),
        result_store=store,
        event_sink=events.append,
        operation=OperationContext(OperationToken()),
        engine_factory=lambda **_kwargs: _StaticEngine(stream),  # type: ignore[arg-type]
        fetch_batch_size=1,
    )

    preview_only = next(event for event in events if isinstance(event, TUIPreviewOnlyEvent))
    assert preview_only.reason == "session_spool_limit"
    assert preview_only.cleanup_notes == (CURSOR_CLEANUP_UNCERTAINTY_NOTE,)


def test_mid_spool_capacity_before_preview_finalization_persists_preview_only_when_it_fits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []
    store = TUIResultStore(temp_root=tmp_path)
    complete_payload_calls = 0
    real_append = TUIResultWriter.append_payload
    statements: list[str] = []
    closed: list[bool] = []

    def fail_first_complete_row_after_retention(
        writer: TUIResultWriter,
        payload: bytes,
    ) -> None:
        nonlocal complete_payload_calls
        if writer._kind == "complete":
            complete_payload_calls += 1
            if complete_payload_calls == 1:
                raise TUIResultStorageError(
                    "Unable to store the query result because session result storage is full.",
                    kind="capacity",
                )
        real_append(writer, payload)

    monkeypatch.setattr(TUIResultWriter, "append_payload", fail_first_complete_row_after_retention)

    run_tui_request(
        _request(
            "SELECT range AS value FROM range(10)",
            policy=PreviewPolicy(row_limit=10, payload_limit_bytes=1_024),
        ),
        result_store=store,
        event_sink=events.append,
        operation=OperationContext(OperationToken()),
        engine_factory=_recording_engine_factory(statements, closed),
        fetch_batch_size=1,
    )

    preview_only = next(event for event in events if isinstance(event, TUIPreviewOnlyEvent))
    assert statements == ["SELECT range AS value FROM range(10)"]
    assert closed == [True]
    assert preview_only.reason == "session_spool_limit"
    assert preview_only.preview.rows == ((0,),)
    assert preview_only.preview.has_more_rows is True
    assert preview_only.preview.truncation_reason is None
    assert preview_only.stored is not None
    assert preview_only.stored.kind == "preview_only"


def test_cancellation_after_preview_persists_preview_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []
    operation = OperationContext(OperationToken())
    store = TUIResultStore(temp_root=tmp_path)
    runner_encoded_rows: list[tuple[object, ...]] = []
    store_encoded_rows: list[tuple[object, ...]] = []
    real_encode = encode_row_payload

    def runner_encode(row: tuple[object, ...]) -> bytes:
        runner_encoded_rows.append(row)
        return real_encode(row)

    def store_encode(row: tuple[object, ...]) -> bytes:
        store_encoded_rows.append(row)
        return real_encode(row)

    monkeypatch.setattr("csvql.tui_query_runner.encode_row_payload", runner_encode)
    monkeypatch.setattr("csvql.tui_result_store.encode_row_payload", store_encode)
    statements: list[str] = []
    closed: list[bool] = []

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
        engine_factory=_recording_engine_factory(statements, closed),
        fetch_batch_size=1,
    )

    preview_only = next(event for event in events if isinstance(event, TUIPreviewOnlyEvent))
    assert preview_only.reason == "user_cancelled"
    assert preview_only.stored is not None
    assert not any(isinstance(event, TUICompleteEvent) for event in events)
    assert runner_encoded_rows == [(0,), (1,)]
    assert store_encoded_rows == []
    assert closed == [True]


def test_cancelled_preview_only_carries_close_cleanup_note(tmp_path: Path) -> None:
    events: list[object] = []
    operation = OperationContext(OperationToken())
    stream = _StaticStream(
        [
            ResultBatch(rows=((0,),), exhausted=False),
            ResultBatch(rows=((1,),), exhausted=False),
        ],
        close_error=RuntimeError("private close detail"),
    )

    def emit(event: object) -> None:
        events.append(event)
        if isinstance(event, TUIPreviewReadyEvent):
            operation.request_cancel()

    run_tui_request(
        _request(
            "SELECT range AS value FROM range(10)",
            policy=PreviewPolicy(row_limit=1, payload_limit_bytes=1_024),
        ),
        result_store=TUIResultStore(temp_root=tmp_path),
        event_sink=emit,
        operation=operation,
        engine_factory=lambda **_kwargs: _StaticEngine(stream),  # type: ignore[arg-type]
        fetch_batch_size=1,
    )

    preview_only = next(event for event in events if isinstance(event, TUIPreviewOnlyEvent))
    assert preview_only.reason == "user_cancelled"
    assert preview_only.cleanup_notes == (CURSOR_CLEANUP_UNCERTAINTY_NOTE,)


@pytest.mark.parametrize(
    "failing_event_type",
    [TUIPreservationProgressEvent, TUICompleteEvent],
)
def test_callback_failure_after_commit_propagates_without_false_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_event_type: type[object],
) -> None:
    class SinkFailure(RuntimeError):
        pass

    committed: list[TUIStoredResult] = []
    events: list[object] = []
    store = TUIResultStore(temp_root=tmp_path)
    real_commit = TUIResultWriter.commit

    def record_commit(
        writer: TUIResultWriter,
        *,
        elapsed_ms: float,
    ) -> TUIStoredResult:
        stored = real_commit(writer, elapsed_ms=elapsed_ms)
        committed.append(stored)
        return stored

    monkeypatch.setattr(TUIResultWriter, "commit", record_commit)

    def emit(event: object) -> None:
        events.append(event)
        if isinstance(event, failing_event_type):
            raise SinkFailure("event delivery failed")

    with pytest.raises(SinkFailure, match="event delivery failed"):
        run_tui_request(
            _request("SELECT 1 AS value"),
            result_store=store,
            event_sink=emit,
            operation=OperationContext(OperationToken()),
            progress_row_interval=10_000,
            progress_interval_seconds=60.0,
        )

    assert len(committed) == 1
    assert not any(isinstance(event, TUIFailedBeforePreviewEvent) for event in events)
    assert not any(isinstance(event, TUIPreviewOnlyEvent) for event in events)
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.open_rows(committed[0].handle)


def test_buffer_callback_failure_is_not_relabelled_as_first_sequence_failure(
    tmp_path: Path,
) -> None:
    class SinkFailure(RuntimeError):
        pass

    events: list[object] = []
    store = TUIResultStore(temp_root=tmp_path)

    def emit(event: object) -> None:
        events.append(event)
        if isinstance(event, TUICompleteEvent) and event.sequence == 11:
            raise SinkFailure("second completion delivery failed")

    with pytest.raises(SinkFailure, match="second completion delivery failed"):
        run_tui_request(
            _request(
                "SELECT 10 AS value",
                "SELECT 11 AS value",
                sequences=(10, 11),
            ),
            result_store=store,
            event_sink=emit,
            operation=OperationContext(OperationToken()),
        )

    assert any(isinstance(event, TUICompleteEvent) and event.sequence == 10 for event in events)
    assert any(isinstance(event, TUICompleteEvent) and event.sequence == 11 for event in events)
    assert not any(isinstance(event, TUIFailedBeforePreviewEvent) for event in events)
    assert not any(isinstance(event, TUIPreviewOnlyEvent) for event in events)
    first_complete = next(
        event for event in events if isinstance(event, TUICompleteEvent) and event.sequence == 10
    )
    rejected_complete = next(
        event for event in events if isinstance(event, TUICompleteEvent) and event.sequence == 11
    )
    assert tuple(store.open_rows(first_complete.stored.handle).iter_rows()) == ((10,),)
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.open_rows(rejected_complete.stored.handle)


def test_preview_only_callback_failure_removes_rejected_snapshot(
    tmp_path: Path,
) -> None:
    class SinkFailure(RuntimeError):
        pass

    events: list[object] = []
    operation = OperationContext(OperationToken())
    store = TUIResultStore(temp_root=tmp_path)

    def emit(event: object) -> None:
        events.append(event)
        if isinstance(event, TUIPreviewReadyEvent):
            operation.request_cancel()
        if isinstance(event, TUIPreviewOnlyEvent):
            raise SinkFailure("preview-only delivery failed")

    with pytest.raises(SinkFailure, match="preview-only delivery failed"):
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

    rejected = next(event for event in events if isinstance(event, TUIPreviewOnlyEvent))
    assert rejected.stored is not None
    assert not any(isinstance(event, TUIFailedBeforePreviewEvent) for event in events)
    with pytest.raises(TUIResultStorageError, match="no longer available"):
        store.load_preview(rejected.stored.handle, _DEFAULT_TEST_POLICY)


def test_preview_event_delivery_failure_preserves_primary_when_rollback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SinkFailure(RuntimeError):
        pass

    store = TUIResultStore(temp_root=tmp_path)
    real_rollback = TUIResultWriter.rollback

    def failing_rollback(writer: TUIResultWriter) -> tuple[str, ...]:
        real_rollback(writer)
        raise RuntimeError("private rollback detail")

    monkeypatch.setattr(TUIResultWriter, "rollback", failing_rollback)

    def emit(event: object) -> None:
        if isinstance(event, TUIPreviewReadyEvent):
            raise SinkFailure("preview delivery failed")

    with pytest.raises(SinkFailure, match="preview delivery failed") as captured:
        run_tui_request(
            _request(
                "SELECT range AS value FROM range(10)",
                policy=PreviewPolicy(row_limit=1, payload_limit_bytes=1_024),
            ),
            result_store=store,
            event_sink=emit,
            operation=OperationContext(OperationToken()),
            fetch_batch_size=1,
        )

    notes = "\n".join(getattr(captured.value, "__notes__", ()))
    assert "incomplete preserved result could not be fully removed" in notes


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


def test_factory_construction_failure_emits_failed_before_preview(tmp_path: Path) -> None:
    events: list[object] = []

    def fail_factory(*, operation: OperationContext) -> CSVQLEngine:
        del operation
        raise CSVQLError("Factory failed.", suggestion="Retry after reinitializing.")

    run_tui_request(
        _request("SELECT 1"),
        result_store=TUIResultStore(temp_root=tmp_path),
        event_sink=events.append,
        operation=OperationContext(OperationToken()),
        engine_factory=fail_factory,
    )

    failed = events[0]
    assert isinstance(failed, TUIFailedBeforePreviewEvent)
    assert failed.error_message == "Factory failed."
    assert failed.suggestion == "Retry after reinitializing."


def test_prepare_cancellation_preserves_cancelled_terminal_cleanup_notes(tmp_path: Path) -> None:
    events: list[object] = []
    operation = OperationContext(OperationToken())
    operation.request_cancel()

    class PrepareCancelledEngine:
        def __enter__(self) -> PrepareCancelledEngine:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            _tb: object,
        ) -> None:
            if exc is not None:
                exc.add_note(_BINDING_CLEANUP_NOTE)

        def prepare_sources(self, sources: object) -> None:
            assert sources == ()
            operation.checkpoint()

    run_tui_request(
        _request("SELECT 1"),
        result_store=TUIResultStore(temp_root=tmp_path),
        event_sink=events.append,
        operation=operation,
        engine_factory=lambda **_kwargs: PrepareCancelledEngine(),  # type: ignore[arg-type]
    )

    cancelled = events[0]
    assert isinstance(cancelled, TUICancelledBeforePreviewEvent)
    assert cancelled.cleanup_notes == (_BINDING_CLEANUP_NOTE,)


def test_prepare_failure_preserves_failed_terminal_cleanup_notes(tmp_path: Path) -> None:
    events: list[object] = []

    class PrepareFailureEngine:
        def __enter__(self) -> PrepareFailureEngine:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            _tb: object,
        ) -> None:
            if exc is not None:
                exc.add_note(_CONNECTION_CLEANUP_NOTE)

        def prepare_sources(self, sources: object) -> None:
            assert sources == ()
            raise CSVQLError("Prepare failed.", suggestion="Fix the source.")

    run_tui_request(
        _request("SELECT 1"),
        result_store=TUIResultStore(temp_root=tmp_path),
        event_sink=events.append,
        operation=OperationContext(OperationToken()),
        engine_factory=lambda **_kwargs: PrepareFailureEngine(),  # type: ignore[arg-type]
    )

    failed = events[0]
    assert isinstance(failed, TUIFailedBeforePreviewEvent)
    assert failed.error_message == "Prepare failed."
    assert failed.suggestion == "Fix the source."
    assert failed.cleanup_notes == (_CONNECTION_CLEANUP_NOTE,)


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
    statements: list[str] = []
    closed: list[bool] = []
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
        engine_factory=_recording_engine_factory(statements, closed),
        fetch_batch_size=1,
    )

    preview_only = next(event for event in events if isinstance(event, TUIPreviewOnlyEvent))
    assert preview_only.reason == "preservation_failed"
    assert preview_only.stored is not None
    assert preview_only.stored.kind == "preview_only"
    assert preview_only.preview.rows == ((0,),)
    assert not any(isinstance(event, TUICompleteEvent) for event in events)
    assert closed == [True]


def test_preservation_failure_carries_real_rollback_cleanup_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []
    store = TUIResultStore(temp_root=tmp_path)
    real_append = TUIResultWriter.append_payload
    complete_payload_calls = 0
    real_remove_staging_file = TUIResultStore._remove_staging_file

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

    def fail_staging_removal(store_: TUIResultStore, path: Path) -> bool:
        return False if path.name.endswith(".tmp") else real_remove_staging_file(store_, path)

    monkeypatch.setattr(TUIResultWriter, "append_payload", fail_third_complete_payload)
    monkeypatch.setattr(TUIResultStore, "_remove_staging_file", fail_staging_removal)

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
    assert preview_only.cleanup_notes == (
        "Cleanup uncertainty: the incomplete preserved result could not be fully removed.",
    )


def test_engine_exit_cleanup_notes_attach_to_preserved_terminal_event(tmp_path: Path) -> None:
    events: list[object] = []
    columns = ("value",)
    store = TUIResultStore(
        temp_root=tmp_path,
        capacity_bytes=_header_bytes(columns) + _FOOTER_BYTES - 1,
    )
    stream = _StaticStream(
        [
            ResultBatch(rows=((0,),), exhausted=False),
            ResultBatch(rows=((1,),), exhausted=False),
        ]
    )

    run_tui_request(
        _request(
            "SELECT range AS value FROM range(10)",
            policy=PreviewPolicy(row_limit=1, payload_limit_bytes=1_024),
        ),
        result_store=store,
        event_sink=events.append,
        operation=OperationContext(OperationToken()),
        engine_factory=lambda **_kwargs: _StaticEngine(  # type: ignore[arg-type]
            stream,
            exit_notes=(_BINDING_CLEANUP_NOTE, _CONNECTION_CLEANUP_NOTE, "private detail"),
        ),
        fetch_batch_size=1,
    )

    preview_only = next(event for event in events if isinstance(event, TUIPreviewOnlyEvent))
    assert preview_only.reason == "session_spool_limit"
    assert preview_only.cleanup_notes == (_BINDING_CLEANUP_NOTE, _CONNECTION_CLEANUP_NOTE)


def test_preview_persist_capacity_none_keeps_primary_reason_without_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []
    operation = OperationContext(OperationToken())
    store = TUIResultStore(temp_root=tmp_path)

    def persist_none(*args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(store, "persist_preview", persist_none)

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
    assert preview_only.stored is None
    assert preview_only.primary_error_message is None


def test_preview_persist_failure_keeps_reason_and_reports_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []
    operation = OperationContext(OperationToken())
    store = TUIResultStore(temp_root=tmp_path)
    persist_error = TUIResultStorageError(
        "Unable to serialize the query result for temporary storage.",
        kind="serialization",
    )
    persist_error.add_note(_CONNECTION_CLEANUP_NOTE)
    persist_error.add_note("private detail")

    def raise_persist_error(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise persist_error

    monkeypatch.setattr(store, "persist_preview", raise_persist_error)

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
    assert preview_only.stored is None
    assert preview_only.primary_error_message is None
    assert preview_only.persistence_error_message == (
        "Unable to serialize the query result for temporary storage."
    )
    assert preview_only.cleanup_notes == (_CONNECTION_CLEANUP_NOTE,)


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
