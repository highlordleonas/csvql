"""Pure same-execution preview and preservation runner for the LocalQL TUI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Literal, TypeAlias

from csvql.bounded_result import BoundedQueryResult, PreviewAccumulator, PreviewPolicy
from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVQLError, QueryExecutionError
from csvql.operation import OperationCancelled, OperationContext
from csvql.query_workflow import (
    SourceCandidate,
    _missing_duckdb_table_name,
    _resolve_fallback_candidate,
)
from csvql.result_codec import encode_row_payload
from csvql.result_stream import CURSOR_CLEANUP_UNCERTAINTY_NOTE, ResultStream
from csvql.source import ResolvedSource
from csvql.tui_result_store import (
    TUIResultReason,
    TUIResultStorageError,
    TUIResultStore,
    TUIResultStoreProgress,
    TUIResultWriter,
    TUIStoredResult,
)

TUIQueryRunMode = Literal["current", "buffer", "rerun"]
TUIResultState = Literal[
    "executing",
    "preserving",
    "complete",
    "preview_only",
    "cancelled",
    "failed",
]
TUIQueryEventKind = Literal[
    "preview_ready",
    "progress",
    "complete",
    "preview_only",
    "no_result",
    "cancelled_before_preview",
    "failed_before_preview",
]


@dataclass(frozen=True, slots=True)
class TUIRunRequest:
    """Immutable execution snapshot captured before a TUI worker starts."""

    statements: tuple[str, ...]
    sequences: tuple[int, ...]
    sources: tuple[ResolvedSource, ...]
    fallback_sources: tuple[SourceCandidate, ...]
    preview_policy: PreviewPolicy
    run_mode: TUIQueryRunMode
    submission_order: int

    def __post_init__(self) -> None:
        if not self.statements:
            raise ValueError("At least one SQL statement is required.")
        if len(self.statements) != len(self.sequences):
            raise ValueError("SQL statements and result sequences must have the same length.")
        if any(
            not isinstance(statement, str) or not statement.strip() for statement in self.statements
        ):
            raise ValueError("SQL statements must be non-empty strings.")
        if any(type(sequence) is not int or sequence <= 0 for sequence in self.sequences):
            raise ValueError("Result sequences must be positive integers.")
        if len(set(self.sequences)) != len(self.sequences):
            raise ValueError("Result sequences must be unique.")
        if self.run_mode not in {"current", "buffer", "rerun"}:
            raise ValueError("run_mode must be current, buffer, or rerun.")
        if type(self.submission_order) is not int or self.submission_order <= 0:
            raise ValueError("submission_order must be a positive integer.")


@dataclass(frozen=True, slots=True)
class TUIPreservationProgress:
    """Truthful progress for a preservation stream with no estimated total."""

    sequence: int
    rows_written: int
    logical_bytes_written: int
    elapsed_ms: float
    remaining_capacity_bytes: int


@dataclass(frozen=True, slots=True)
class TUIPreviewReadyEvent:
    sequence: int
    preview: BoundedQueryResult
    kind: Literal["preview_ready"] = field(init=False, default="preview_ready")


@dataclass(frozen=True, slots=True)
class TUIPreservationProgressEvent:
    sequence: int
    progress: TUIPreservationProgress
    kind: Literal["progress"] = field(init=False, default="progress")


@dataclass(frozen=True, slots=True)
class TUICompleteEvent:
    sequence: int
    stored: TUIStoredResult
    kind: Literal["complete"] = field(init=False, default="complete")


@dataclass(frozen=True, slots=True)
class TUIPreviewOnlyEvent:
    sequence: int
    preview: BoundedQueryResult
    reason: TUIResultReason
    stored: TUIStoredResult | None
    primary_error_message: str | None = None
    primary_suggestion: str | None = None
    persistence_error_message: str | None = None
    persistence_suggestion: str | None = None
    cleanup_notes: tuple[str, ...] = field(default_factory=tuple)
    kind: Literal["preview_only"] = field(init=False, default="preview_only")


@dataclass(frozen=True, slots=True)
class TUINoResultEvent:
    sequence: int
    elapsed_ms: float
    kind: Literal["no_result"] = field(init=False, default="no_result")


@dataclass(frozen=True, slots=True)
class TUICancelledBeforePreviewEvent:
    sequence: int
    cleanup_notes: tuple[str, ...] = field(default_factory=tuple)
    kind: Literal["cancelled_before_preview"] = field(
        init=False,
        default="cancelled_before_preview",
    )


@dataclass(frozen=True, slots=True)
class TUIFailedBeforePreviewEvent:
    sequence: int
    error_message: str
    suggestion: str | None = None
    cleanup_notes: tuple[str, ...] = field(default_factory=tuple)
    kind: Literal["failed_before_preview"] = field(
        init=False,
        default="failed_before_preview",
    )


class _EventSinkFailure(Exception):
    """Carry an event callback failure through runner cleanup without relabelling it."""

    def __init__(self, cause: BaseException) -> None:
        super().__init__("The TUI event sink rejected an event.")
        self.cause = cause


class _CleanupCarrier(Exception):
    """Collect cleanup notes without replacing a primary terminal outcome."""


@dataclass(frozen=True, slots=True)
class _DeferredPreviewOnlyOutcome:
    sequence: int
    preview: BoundedQueryResult
    reason: TUIResultReason
    elapsed_ms: float
    encoded_payloads: tuple[bytes, ...]
    primary_error_message: str | None = None
    primary_suggestion: str | None = None
    persistence_error_message: str | None = None
    persistence_suggestion: str | None = None
    publish_preview_ready: bool = False
    cleanup_notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _DeferredCancelledBeforePreviewOutcome:
    sequence: int
    cleanup_notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _DeferredFailedBeforePreviewOutcome:
    sequence: int
    error_message: str
    suggestion: str | None
    cleanup_notes: tuple[str, ...] = ()


TUIQueryEvent: TypeAlias = (
    TUIPreviewReadyEvent
    | TUIPreservationProgressEvent
    | TUICompleteEvent
    | TUIPreviewOnlyEvent
    | TUINoResultEvent
    | TUICancelledBeforePreviewEvent
    | TUIFailedBeforePreviewEvent
)
TUIQueryEventSink: TypeAlias = Callable[[TUIQueryEvent], None]
TUIEngineFactory: TypeAlias = Callable[..., CSVQLEngine]
_Now: TypeAlias = Callable[[], float]

_DEFAULT_FETCH_BATCH_SIZE = 256
_DEFAULT_PROGRESS_ROW_INTERVAL = 256
_DEFAULT_PROGRESS_INTERVAL_SECONDS = 0.1
_EVENT_DELIVERY_CLEANUP_UNCERTAINTY_NOTE = (
    "LocalQL could not confirm result cleanup after a TUI event delivery failure."
)
_RESULT_ROLLBACK_CLEANUP_UNCERTAINTY_NOTE = (
    "Cleanup uncertainty: the incomplete preserved result could not be fully removed."
)
_BINDING_CLEANUP_UNCERTAINTY_NOTE = (
    "Cleanup uncertainty: one or more source bindings could not be closed."
)
_CONNECTION_CLEANUP_UNCERTAINTY_NOTE = (
    "Cleanup uncertainty: the engine connection could not be closed."
)
_SANITIZED_CLEANUP_NOTES = frozenset(
    {
        CURSOR_CLEANUP_UNCERTAINTY_NOTE,
        _RESULT_ROLLBACK_CLEANUP_UNCERTAINTY_NOTE,
        _BINDING_CLEANUP_UNCERTAINTY_NOTE,
        _CONNECTION_CLEANUP_UNCERTAINTY_NOTE,
    }
)
_DeferredTerminalOutcome: TypeAlias = (
    _DeferredPreviewOnlyOutcome
    | _DeferredCancelledBeforePreviewOutcome
    | _DeferredFailedBeforePreviewOutcome
)


def run_tui_request(
    request: TUIRunRequest,
    *,
    result_store: TUIResultStore,
    event_sink: TUIQueryEventSink,
    operation: OperationContext,
    engine_factory: TUIEngineFactory = CSVQLEngine,
    fetch_batch_size: int = _DEFAULT_FETCH_BATCH_SIZE,
    progress_row_interval: int = _DEFAULT_PROGRESS_ROW_INTERVAL,
    progress_interval_seconds: float = _DEFAULT_PROGRESS_INTERVAL_SECONDS,
    now: _Now = monotonic,
) -> None:
    """Execute an immutable request once while publishing bounded TUI values."""

    if fetch_batch_size <= 0:
        raise ValueError("fetch_batch_size must be positive.")
    if progress_row_interval <= 0:
        raise ValueError("progress_row_interval must be positive.")
    if progress_interval_seconds <= 0:
        raise ValueError("progress_interval_seconds must be positive.")

    first_sequence = request.sequences[0]
    attempted_aliases = {source.spec.alias.casefold() for source in request.sources}
    statement_started = False
    deferred_terminal: _DeferredTerminalOutcome | None = None
    engine_entered = False
    engine_context: object | None = None
    try:
        engine_context = engine_factory(operation=operation)
        engine = engine_context.__enter__()
        engine_entered = True
        operation.checkpoint()
        engine.prepare_sources(request.sources)
        for statement, sequence in zip(
            request.statements,
            request.sequences,
            strict=True,
        ):
            statement_started = True
            statement_result = _run_statement(
                engine=engine,
                statement=statement,
                sequence=sequence,
                fallback_sources=request.fallback_sources,
                attempted_aliases=attempted_aliases,
                preview_policy=request.preview_policy,
                result_store=result_store,
                event_sink=event_sink,
                operation=operation,
                fetch_batch_size=fetch_batch_size,
                progress_row_interval=progress_row_interval,
                progress_interval_seconds=progress_interval_seconds,
                now=now,
            )
            if statement_result is not True:
                deferred_terminal = statement_result
                break
    except _EventSinkFailure as exc:
        if engine_entered:
            assert engine_context is not None
            _exit_engine_context(
                engine_context, type(exc.cause), exc.cause, exc.cause.__traceback__
            )
        raise exc.cause from exc
    except OperationCancelled as exc:
        if engine_entered:
            assert engine_context is not None
            _exit_engine_context(engine_context, type(exc), exc, exc.__traceback__)
        if statement_started:
            raise
        event_sink(
            TUICancelledBeforePreviewEvent(
                sequence=first_sequence,
                cleanup_notes=_notes_tuple(exc),
            )
        )
    except BaseException as exc:
        if engine_entered:
            assert engine_context is not None
            _exit_engine_context(engine_context, type(exc), exc, exc.__traceback__)
        if statement_started:
            raise
        message, suggestion = _public_failure(exc)
        event_sink(
            TUIFailedBeforePreviewEvent(
                sequence=first_sequence,
                error_message=message,
                suggestion=suggestion,
                cleanup_notes=_notes_tuple(exc),
            )
        )
    else:
        if engine_entered:
            assert engine_context is not None
            if deferred_terminal is None:
                _exit_engine_context(engine_context, None, None, None)
            else:
                cleanup_carrier = _CleanupCarrier()
                _exit_engine_context(
                    engine_context,
                    _CleanupCarrier,
                    cleanup_carrier,
                    cleanup_carrier.__traceback__,
                )
                deferred_terminal = _with_cleanup_notes(
                    deferred_terminal,
                    _notes_tuple(cleanup_carrier),
                )
    if deferred_terminal is not None:
        try:
            _publish_deferred_terminal(
                deferred_terminal,
                result_store=result_store,
                event_sink=event_sink,
            )
        except _EventSinkFailure as exc:
            raise exc.cause from exc


def _run_statement(
    *,
    engine: CSVQLEngine,
    statement: str,
    sequence: int,
    fallback_sources: tuple[SourceCandidate, ...],
    attempted_aliases: set[str],
    preview_policy: PreviewPolicy,
    result_store: TUIResultStore,
    event_sink: TUIQueryEventSink,
    operation: OperationContext,
    fetch_batch_size: int,
    progress_row_interval: int,
    progress_interval_seconds: float,
    now: _Now,
) -> Literal[True] | _DeferredTerminalOutcome:
    stream: ResultStream | None = None
    writer = None
    stored: TUIStoredResult | None = None
    preview: BoundedQueryResult | None = None
    accumulator: PreviewAccumulator | None = None
    retained_payloads: list[bytes] = []
    stream_active = False
    writer_committed = False
    preview_ready_emitted = False
    stop_after_preview_reason: TUIResultReason | None = None
    try:
        operation.checkpoint()
        stream = _start_statement_stream(
            engine=engine,
            statement=statement,
            fallback_sources=fallback_sources,
            attempted_aliases=attempted_aliases,
            operation=operation,
        )
        stream_active = True
        if not stream.columns:
            _close_stream(stream, primary=None, interrupt=False)
            stream_active = False
            _publish_event(
                event_sink,
                TUINoResultEvent(
                    sequence=sequence,
                    elapsed_ms=stream.elapsed_ms,
                ),
            )
            return True

        try:
            writer = result_store.begin_complete(
                sequence=sequence,
                columns=stream.columns,
            )
        except TUIResultStorageError as exc:
            if exc.kind == "capacity":
                stop_after_preview_reason = "session_spool_limit"
            else:
                raise
        accumulator = PreviewAccumulator(
            columns=stream.columns,
            elapsed_ms=stream.elapsed_ms,
            policy=preview_policy,
        )
        last_progress_rows = 0
        last_progress_at = now()

        while True:
            operation.checkpoint()
            batch = stream.fetch_rows(fetch_batch_size)
            if not batch.rows and not batch.exhausted:
                raise RuntimeError("Result stream returned an empty non-exhausted batch.")
            for raw_row in batch.rows:
                operation.checkpoint()
                row = tuple(raw_row)
                payload = encode_row_payload(row)
                retained = accumulator.consider(row, payload)
                if retained:
                    retained_payloads.append(payload)
                if not retained and preview is None:
                    accumulator.elapsed_ms = stream.elapsed_ms
                    preview = accumulator.finish()
                    _publish_event(
                        event_sink,
                        TUIPreviewReadyEvent(
                            sequence=sequence,
                            preview=preview,
                        ),
                    )
                    preview_ready_emitted = True
                    operation.checkpoint()
                    if stop_after_preview_reason is not None:
                        cleanup_carrier = _CleanupCarrier()
                        _close_stream(stream, primary=cleanup_carrier, interrupt=True)
                        stream_active = False
                        return _DeferredPreviewOnlyOutcome(
                            sequence=sequence,
                            preview=preview,
                            reason=stop_after_preview_reason,
                            elapsed_ms=_elapsed_ms(stream),
                            encoded_payloads=tuple(retained_payloads),
                            cleanup_notes=_notes_tuple(cleanup_carrier),
                        )
                if writer is not None:
                    writer.append_payload(payload)

                current_time = now()
                if writer is not None:
                    progress = writer.progress
                    if (
                        progress.rows_written - last_progress_rows >= progress_row_interval
                        or current_time - last_progress_at >= progress_interval_seconds
                    ):
                        _emit_progress(
                            sequence=sequence,
                            elapsed_ms=stream.elapsed_ms,
                            writer_progress=progress,
                            event_sink=event_sink,
                        )
                        last_progress_rows = progress.rows_written
                        last_progress_at = current_time

            if not batch.exhausted:
                continue

            accumulator.elapsed_ms = stream.elapsed_ms
            if preview is None:
                preview = accumulator.finish()
                _publish_event(
                    event_sink,
                    TUIPreviewReadyEvent(
                        sequence=sequence,
                        preview=preview,
                    ),
                )
                preview_ready_emitted = True
                operation.checkpoint()
            if stop_after_preview_reason is not None:
                cleanup_carrier = _CleanupCarrier()
                _close_stream(stream, primary=cleanup_carrier, interrupt=False)
                stream_active = False
                return _DeferredPreviewOnlyOutcome(
                    sequence=sequence,
                    preview=preview,
                    reason=stop_after_preview_reason,
                    elapsed_ms=_elapsed_ms(stream),
                    encoded_payloads=tuple(retained_payloads),
                    cleanup_notes=_notes_tuple(cleanup_carrier),
                )
            _close_stream(stream, primary=None, interrupt=False)
            stream_active = False
            assert writer is not None
            stored = writer.commit(elapsed_ms=stream.elapsed_ms)
            writer_committed = True
            _emit_progress(
                sequence=sequence,
                elapsed_ms=stored.elapsed_ms,
                writer_progress=writer.progress,
                event_sink=event_sink,
            )
            _publish_event(
                event_sink,
                TUICompleteEvent(sequence=sequence, stored=stored),
            )
            return True
    except _EventSinkFailure as exc:
        if stream is not None and stream_active:
            _close_stream(stream, primary=exc.cause, interrupt=True)
        if writer is not None and not writer_committed:
            _rollback_writer_preserving_primary(writer, primary=exc.cause)
        if stored is not None:
            _remove_rejected_stored_result(
                result_store=result_store,
                stored=stored,
                failure=exc,
            )
        raise
    except OperationCancelled as exc:
        if stream is not None and stream_active:
            _close_stream(stream, primary=exc, interrupt=True)
        cleanup_notes = _rollback_writer_preserving_primary(writer, primary=exc)
        if preview is None:
            return _DeferredCancelledBeforePreviewOutcome(
                sequence=sequence,
                cleanup_notes=_notes_tuple(exc, cleanup_notes),
            )
        return _DeferredPreviewOnlyOutcome(
            sequence=sequence,
            preview=preview,
            reason="user_cancelled",
            elapsed_ms=_elapsed_ms(stream),
            encoded_payloads=tuple(retained_payloads),
            persistence_error_message=None,
            persistence_suggestion=None,
            publish_preview_ready=False,
            cleanup_notes=_notes_tuple(exc, cleanup_notes),
        )
    except TUIResultStorageError as exc:
        if stream is not None and stream_active:
            _close_stream(stream, primary=exc, interrupt=True)
        cleanup_notes = _rollback_writer_preserving_primary(writer, primary=exc)
        if (
            preview is None
            and exc.kind == "capacity"
            and accumulator is not None
            and retained_payloads
        ):
            preview = _finish_capacity_interrupted_preview(
                accumulator,
                elapsed_ms=_elapsed_ms(stream),
            )
        if preview is not None:
            reason: TUIResultReason = (
                "session_spool_limit" if exc.kind == "capacity" else "preservation_failed"
            )
            return _DeferredPreviewOnlyOutcome(
                sequence=sequence,
                preview=preview,
                reason=reason,
                elapsed_ms=_elapsed_ms(stream),
                encoded_payloads=tuple(retained_payloads),
                primary_error_message=None if exc.kind == "capacity" else exc.user_message,
                persistence_error_message=None,
                persistence_suggestion=None,
                publish_preview_ready=exc.kind == "capacity" and not preview_ready_emitted,
                cleanup_notes=_notes_tuple(exc, cleanup_notes),
            )
        return _DeferredFailedBeforePreviewOutcome(
            sequence=sequence,
            error_message=exc.user_message,
            suggestion=None,
            cleanup_notes=_notes_tuple(exc, cleanup_notes),
        )
    except BaseException as exc:
        if stream is not None and stream_active:
            _close_stream(stream, primary=exc, interrupt=True)
        cleanup_notes = _rollback_writer_preserving_primary(writer, primary=exc)
        if preview is not None:
            message, suggestion = _public_failure(exc)
            return _DeferredPreviewOnlyOutcome(
                sequence=sequence,
                preview=preview,
                reason="preservation_failed",
                elapsed_ms=_elapsed_ms(stream),
                encoded_payloads=tuple(retained_payloads),
                primary_error_message=message,
                primary_suggestion=suggestion,
                persistence_error_message=None,
                persistence_suggestion=None,
                cleanup_notes=_notes_tuple(exc, cleanup_notes),
            )
        message, suggestion = _public_failure(exc)
        return _DeferredFailedBeforePreviewOutcome(
            sequence=sequence,
            error_message=message,
            suggestion=suggestion,
            cleanup_notes=_notes_tuple(exc, cleanup_notes),
        )


def _publish_deferred_terminal(
    outcome: _DeferredTerminalOutcome,
    *,
    result_store: TUIResultStore,
    event_sink: TUIQueryEventSink,
) -> None:
    if isinstance(outcome, _DeferredPreviewOnlyOutcome):
        if outcome.publish_preview_ready:
            _publish_event(
                event_sink,
                TUIPreviewReadyEvent(
                    sequence=outcome.sequence,
                    preview=outcome.preview,
                ),
            )
        _emit_preview_only(
            sequence=outcome.sequence,
            preview=outcome.preview,
            reason=outcome.reason,
            elapsed_ms=outcome.elapsed_ms,
            encoded_payloads=outcome.encoded_payloads,
            primary_error_message=outcome.primary_error_message,
            primary_suggestion=outcome.primary_suggestion,
            persistence_error_message=outcome.persistence_error_message,
            persistence_suggestion=outcome.persistence_suggestion,
            cleanup_notes=outcome.cleanup_notes,
            result_store=result_store,
            event_sink=event_sink,
        )
        return
    if isinstance(outcome, _DeferredCancelledBeforePreviewOutcome):
        _publish_event(
            event_sink,
            TUICancelledBeforePreviewEvent(
                sequence=outcome.sequence,
                cleanup_notes=outcome.cleanup_notes,
            ),
        )
        return
    _publish_event(
        event_sink,
        TUIFailedBeforePreviewEvent(
            sequence=outcome.sequence,
            error_message=outcome.error_message,
            suggestion=outcome.suggestion,
            cleanup_notes=outcome.cleanup_notes,
        ),
    )


def _start_statement_stream(
    *,
    engine: CSVQLEngine,
    statement: str,
    fallback_sources: tuple[SourceCandidate, ...],
    attempted_aliases: set[str],
    operation: OperationContext,
) -> ResultStream:
    while True:
        operation.checkpoint()
        try:
            return engine.stream(statement)
        except QueryExecutionError as exc:
            if CURSOR_CLEANUP_UNCERTAINTY_NOTE in getattr(exc, "__notes__", ()):
                raise
            missing_name = _missing_duckdb_table_name(exc)
            if missing_name is None:
                raise
            missing_key = missing_name.casefold()
            candidate = next(
                (
                    fallback
                    for fallback in fallback_sources
                    if fallback.spec.alias.casefold() == missing_key
                    and missing_key not in attempted_aliases
                ),
                None,
            )
            if candidate is None:
                raise
            attempted_aliases.add(missing_key)
            resolved = _resolve_fallback_candidate(candidate, operation=operation)
            engine.prepare_sources((resolved,))


def _emit_preview_only(
    *,
    sequence: int,
    preview: BoundedQueryResult,
    reason: TUIResultReason,
    elapsed_ms: float,
    encoded_payloads: tuple[bytes, ...],
    primary_error_message: str | None,
    primary_suggestion: str | None,
    persistence_error_message: str | None,
    persistence_suggestion: str | None,
    cleanup_notes: tuple[str, ...],
    result_store: TUIResultStore,
    event_sink: TUIQueryEventSink,
) -> None:
    persisted_cleanup_notes = cleanup_notes
    effective_persistence_error_message = persistence_error_message
    effective_persistence_suggestion = persistence_suggestion
    try:
        stored = result_store.persist_preview(
            sequence=sequence,
            preview=preview,
            reason=reason,
            elapsed_ms=elapsed_ms,
            encoded_payloads=encoded_payloads,
        )
    except BaseException as exc:
        stored = None
        message, suggestion = _public_failure(exc)
        if isinstance(exc, TUIResultStorageError):
            message = exc.user_message
            suggestion = None
        effective_persistence_error_message = message
        effective_persistence_suggestion = suggestion
        persisted_cleanup_notes = _merge_cleanup_notes(cleanup_notes, _notes_tuple(exc))
    try:
        _publish_event(
            event_sink,
            TUIPreviewOnlyEvent(
                sequence=sequence,
                preview=preview,
                reason=reason,
                stored=stored,
                primary_error_message=primary_error_message,
                primary_suggestion=primary_suggestion,
                persistence_error_message=effective_persistence_error_message,
                persistence_suggestion=effective_persistence_suggestion,
                cleanup_notes=persisted_cleanup_notes,
            ),
        )
    except _EventSinkFailure as exc:
        if stored is not None:
            _remove_rejected_stored_result(
                result_store=result_store,
                stored=stored,
                failure=exc,
            )
        raise


def _emit_progress(
    *,
    sequence: int,
    elapsed_ms: float,
    writer_progress: TUIResultStoreProgress,
    event_sink: TUIQueryEventSink,
) -> None:
    progress = TUIPreservationProgress(
        sequence=sequence,
        rows_written=writer_progress.rows_written,
        logical_bytes_written=writer_progress.logical_bytes_written,
        elapsed_ms=elapsed_ms,
        remaining_capacity_bytes=writer_progress.remaining_capacity_bytes,
    )
    _publish_event(
        event_sink,
        TUIPreservationProgressEvent(
            sequence=sequence,
            progress=progress,
        ),
    )


def _publish_event(
    event_sink: TUIQueryEventSink,
    event: TUIQueryEvent,
) -> None:
    try:
        event_sink(event)
    except BaseException as exc:
        raise _EventSinkFailure(exc) from exc


def _exit_engine_context(
    engine_context: object,
    exc_type: type[BaseException] | None,
    exc: BaseException | None,
    traceback: object,
) -> None:
    engine_context.__exit__(exc_type, exc, traceback)  # type: ignore[attr-defined]


def _remove_rejected_stored_result(
    *,
    result_store: TUIResultStore,
    stored: TUIStoredResult,
    failure: _EventSinkFailure,
) -> None:
    try:
        result_store.remove(stored.handle)
    except BaseException:
        if _EVENT_DELIVERY_CLEANUP_UNCERTAINTY_NOTE not in getattr(
            failure.cause,
            "__notes__",
            (),
        ):
            failure.cause.add_note(_EVENT_DELIVERY_CLEANUP_UNCERTAINTY_NOTE)


def _close_stream(
    stream: ResultStream,
    *,
    primary: BaseException | None,
    interrupt: bool,
) -> None:
    if interrupt:
        try:
            stream.request_interrupt()
        except BaseException:
            if primary is None:
                raise
            _add_cleanup_note(primary)
    try:
        stream.close()
    except BaseException:
        if primary is None:
            raise
        _add_cleanup_note(primary)


def _elapsed_ms(stream: ResultStream | None) -> float:
    return 0.0 if stream is None else stream.elapsed_ms


def _finish_capacity_interrupted_preview(
    accumulator: PreviewAccumulator,
    *,
    elapsed_ms: float,
) -> BoundedQueryResult:
    finished = accumulator.finish()
    return BoundedQueryResult(
        columns=finished.columns,
        rows=finished.rows,
        elapsed_ms=elapsed_ms,
        preview_payload_bytes=finished.preview_payload_bytes,
        has_more_rows=True,
        truncation_reason=finished.truncation_reason,
    )


def _public_failure(error: BaseException) -> tuple[str, str | None]:
    if isinstance(error, CSVQLError):
        return (error.message, error.suggestion)
    return (
        "LocalQL could not preserve the query result.",
        "Retry the query. If the problem persists, report this as a bug.",
    )


def _add_cleanup_note(primary: BaseException) -> None:
    if CURSOR_CLEANUP_UNCERTAINTY_NOTE not in getattr(primary, "__notes__", ()):
        primary.add_note(CURSOR_CLEANUP_UNCERTAINTY_NOTE)


def _rollback_writer_preserving_primary(
    writer: TUIResultWriter | None,
    *,
    primary: BaseException,
) -> tuple[str, ...]:
    if writer is None:
        return ()
    try:
        cleanup_notes = writer.rollback()
    except BaseException:
        _add_note_once(primary, _RESULT_ROLLBACK_CLEANUP_UNCERTAINTY_NOTE)
        return (_RESULT_ROLLBACK_CLEANUP_UNCERTAINTY_NOTE,)
    sanitized_notes = _sanitize_cleanup_notes(cleanup_notes)
    for note in sanitized_notes:
        _add_note_once(primary, note)
    return sanitized_notes


def _notes_tuple(
    primary: BaseException,
    extra_notes: tuple[str, ...] = (),
) -> tuple[str, ...]:
    notes = list(_sanitize_cleanup_notes(getattr(primary, "__notes__", ())))
    for note in extra_notes:
        if note not in notes:
            notes.append(note)
    return tuple(notes)


def _with_cleanup_notes(
    outcome: _DeferredTerminalOutcome,
    cleanup_notes: tuple[str, ...],
) -> _DeferredTerminalOutcome:
    if not cleanup_notes:
        return outcome
    if isinstance(outcome, _DeferredPreviewOnlyOutcome):
        return _DeferredPreviewOnlyOutcome(
            sequence=outcome.sequence,
            preview=outcome.preview,
            reason=outcome.reason,
            elapsed_ms=outcome.elapsed_ms,
            encoded_payloads=outcome.encoded_payloads,
            primary_error_message=outcome.primary_error_message,
            primary_suggestion=outcome.primary_suggestion,
            persistence_error_message=outcome.persistence_error_message,
            persistence_suggestion=outcome.persistence_suggestion,
            publish_preview_ready=outcome.publish_preview_ready,
            cleanup_notes=_merge_cleanup_notes(outcome.cleanup_notes, cleanup_notes),
        )
    if isinstance(outcome, _DeferredCancelledBeforePreviewOutcome):
        return _DeferredCancelledBeforePreviewOutcome(
            sequence=outcome.sequence,
            cleanup_notes=_merge_cleanup_notes(outcome.cleanup_notes, cleanup_notes),
        )
    return _DeferredFailedBeforePreviewOutcome(
        sequence=outcome.sequence,
        error_message=outcome.error_message,
        suggestion=outcome.suggestion,
        cleanup_notes=_merge_cleanup_notes(outcome.cleanup_notes, cleanup_notes),
    )


def _merge_cleanup_notes(
    existing: tuple[str, ...],
    incoming: tuple[str, ...],
) -> tuple[str, ...]:
    merged = list(existing)
    for note in incoming:
        if note not in merged:
            merged.append(note)
    return tuple(merged)


def _add_note_once(primary: BaseException, note: str) -> None:
    if note not in getattr(primary, "__notes__", ()):
        primary.add_note(note)


def _sanitize_cleanup_notes(notes: tuple[str, ...] | list[str] | object) -> tuple[str, ...]:
    sanitized: list[str] = []
    for note in notes if isinstance(notes, (tuple, list)) else ():
        if not isinstance(note, str):
            continue
        if note in _SANITIZED_CLEANUP_NOTES:
            if note not in sanitized:
                sanitized.append(note)
    return tuple(sanitized)
