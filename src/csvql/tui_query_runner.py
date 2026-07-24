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
    kind: Literal["preview_only"] = field(init=False, default="preview_only")


@dataclass(frozen=True, slots=True)
class TUINoResultEvent:
    sequence: int
    elapsed_ms: float
    kind: Literal["no_result"] = field(init=False, default="no_result")


@dataclass(frozen=True, slots=True)
class TUICancelledBeforePreviewEvent:
    sequence: int
    kind: Literal["cancelled_before_preview"] = field(
        init=False,
        default="cancelled_before_preview",
    )


@dataclass(frozen=True, slots=True)
class TUIFailedBeforePreviewEvent:
    sequence: int
    error_message: str
    suggestion: str | None = None
    kind: Literal["failed_before_preview"] = field(
        init=False,
        default="failed_before_preview",
    )


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
    try:
        with engine_factory(operation=operation) as engine:
            operation.checkpoint()
            engine.prepare_sources(request.sources)
            for statement, sequence in zip(
                request.statements,
                request.sequences,
                strict=True,
            ):
                if not _run_statement(
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
                ):
                    return
    except OperationCancelled:
        event_sink(TUICancelledBeforePreviewEvent(sequence=first_sequence))
    except BaseException as exc:
        message, suggestion = _public_failure(exc)
        event_sink(
            TUIFailedBeforePreviewEvent(
                sequence=first_sequence,
                error_message=message,
                suggestion=suggestion,
            )
        )


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
) -> bool:
    stream: ResultStream | None = None
    writer = None
    preview: BoundedQueryResult | None = None
    try:
        operation.checkpoint()
        stream = _start_statement_stream(
            engine=engine,
            statement=statement,
            fallback_sources=fallback_sources,
            attempted_aliases=attempted_aliases,
            operation=operation,
        )
        if not stream.columns:
            _close_stream(stream, primary=None, interrupt=False)
            event_sink(
                TUINoResultEvent(
                    sequence=sequence,
                    elapsed_ms=stream.elapsed_ms,
                )
            )
            return True

        writer = result_store.begin_complete(
            sequence=sequence,
            columns=stream.columns,
        )
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
                writer.append_payload(payload)
                retained = accumulator.consider(row, payload)
                if not retained and preview is None:
                    accumulator.elapsed_ms = stream.elapsed_ms
                    preview = accumulator.finish()
                    event_sink(
                        TUIPreviewReadyEvent(
                            sequence=sequence,
                            preview=preview,
                        )
                    )
                    operation.checkpoint()

                current_time = now()
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
                event_sink(
                    TUIPreviewReadyEvent(
                        sequence=sequence,
                        preview=preview,
                    )
                )
                operation.checkpoint()
            _close_stream(stream, primary=None, interrupt=False)
            stored = writer.commit(elapsed_ms=stream.elapsed_ms)
            _emit_progress(
                sequence=sequence,
                elapsed_ms=stored.elapsed_ms,
                writer_progress=writer.progress,
                event_sink=event_sink,
            )
            event_sink(TUICompleteEvent(sequence=sequence, stored=stored))
            return True
    except OperationCancelled as exc:
        if stream is not None:
            _close_stream(stream, primary=exc, interrupt=True)
        if writer is not None:
            writer.rollback()
        if preview is None:
            event_sink(TUICancelledBeforePreviewEvent(sequence=sequence))
        else:
            _emit_preview_only(
                sequence=sequence,
                preview=preview,
                reason="user_cancelled",
                elapsed_ms=_elapsed_ms(stream),
                result_store=result_store,
                event_sink=event_sink,
            )
        return False
    except TUIResultStorageError as exc:
        if stream is not None:
            _close_stream(stream, primary=exc, interrupt=True)
        if writer is not None:
            writer.rollback()
        if preview is not None:
            reason: TUIResultReason = (
                "session_spool_limit" if exc.kind == "capacity" else "preservation_failed"
            )
            _emit_preview_only(
                sequence=sequence,
                preview=preview,
                reason=reason,
                elapsed_ms=_elapsed_ms(stream),
                result_store=result_store,
                event_sink=event_sink,
            )
        else:
            event_sink(
                TUIFailedBeforePreviewEvent(
                    sequence=sequence,
                    error_message=exc.user_message,
                )
            )
        return False
    except BaseException as exc:
        if stream is not None:
            _close_stream(stream, primary=exc, interrupt=True)
        if writer is not None:
            writer.rollback()
        if preview is not None:
            _emit_preview_only(
                sequence=sequence,
                preview=preview,
                reason="preservation_failed",
                elapsed_ms=_elapsed_ms(stream),
                result_store=result_store,
                event_sink=event_sink,
            )
        else:
            message, suggestion = _public_failure(exc)
            event_sink(
                TUIFailedBeforePreviewEvent(
                    sequence=sequence,
                    error_message=message,
                    suggestion=suggestion,
                )
            )
        return False


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
    result_store: TUIResultStore,
    event_sink: TUIQueryEventSink,
) -> None:
    stored = result_store.persist_preview(
        sequence=sequence,
        preview=preview,
        reason=reason,
        elapsed_ms=elapsed_ms,
    )
    event_sink(
        TUIPreviewOnlyEvent(
            sequence=sequence,
            preview=preview,
            reason=reason,
            stored=stored,
        )
    )


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
    event_sink(
        TUIPreservationProgressEvent(
            sequence=sequence,
            progress=progress,
        )
    )


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
