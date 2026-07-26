"""Private bounded preview result types for LocalQL query execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from csvql.exceptions import QueryExecutionError
from csvql.result_codec import encode_row_payload
from csvql.result_stream import CURSOR_CLEANUP_UNCERTAINTY_NOTE, ResultBatch, ResultStream

DEFAULT_INTERACTIVE_ROW_LIMIT = 1_000
MAX_PREVIEW_PAYLOAD_BYTES = 16 * 1024 * 1024
TruncationReason = Literal["row_limit", "byte_limit"]
_INVALID_BATCH_MESSAGE = "LocalQL internal error: invalid result stream batch."
_INVALID_BATCH_SUGGESTION = "Retry the query. If the problem persists, report this as a bug."


@dataclass(frozen=True, slots=True)
class PreviewPolicy:
    row_limit: int = DEFAULT_INTERACTIVE_ROW_LIMIT
    payload_limit_bytes: int = MAX_PREVIEW_PAYLOAD_BYTES

    def __post_init__(self) -> None:
        if self.row_limit <= 0:
            raise ValueError("row_limit must be positive")
        if self.payload_limit_bytes <= 0:
            raise ValueError("payload_limit_bytes must be positive")


@dataclass(frozen=True, slots=True)
class BoundedQueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    elapsed_ms: float
    preview_payload_bytes: int
    has_more_rows: bool
    truncation_reason: TruncationReason | None


@dataclass(slots=True)
class PreviewAccumulator:
    columns: tuple[str, ...]
    elapsed_ms: float
    policy: PreviewPolicy = PreviewPolicy()
    _rows: list[tuple[object, ...]] = field(init=False, default_factory=list)
    _preview_payload_bytes: int = field(init=False, default=0)
    _has_more_rows: bool = field(init=False, default=False)
    _truncation_reason: TruncationReason | None = field(init=False, default=None)

    def consider(self, row: tuple[object, ...], payload: bytes) -> bool:
        if self._truncation_reason is not None:
            self._has_more_rows = True
            return False
        if len(self._rows) >= self.policy.row_limit:
            self._record_truncation("row_limit")
            return False
        payload_size = len(payload)
        if self._preview_payload_bytes + payload_size > self.policy.payload_limit_bytes:
            self._record_truncation("byte_limit")
            return False
        self._rows.append(row)
        self._preview_payload_bytes += payload_size
        return True

    def finish(self) -> BoundedQueryResult:
        return BoundedQueryResult(
            columns=self.columns,
            rows=tuple(self._rows),
            elapsed_ms=self.elapsed_ms,
            preview_payload_bytes=self._preview_payload_bytes,
            has_more_rows=self._has_more_rows,
            truncation_reason=self._truncation_reason,
        )

    def _record_truncation(self, reason: TruncationReason) -> None:
        if self._truncation_reason is None:
            self._truncation_reason = reason
        self._has_more_rows = True


def collect_bounded_preview(
    stream: ResultStream,
    *,
    policy: PreviewPolicy,
    fetch_batch_size: int = 256,
) -> BoundedQueryResult:
    """Collect a bounded CLI preview without recounting or rerunning the query."""

    if fetch_batch_size <= 0:
        raise ValueError("fetch_batch_size must be positive")

    accumulator = PreviewAccumulator(
        columns=stream.columns,
        elapsed_ms=stream.elapsed_ms,
        policy=policy,
    )
    remaining_row_budget = policy.row_limit + 1

    while remaining_row_budget > 0:
        requested_rows = min(fetch_batch_size, remaining_row_budget)
        try:
            batch = stream.fetch_rows(requested_rows)
        except BaseException as exc:
            _close_preserving_primary(stream, exc)
            raise
        try:
            _validate_batch(batch=batch, requested_rows=requested_rows)
        except BaseException as exc:
            _close_preserving_primary(stream, exc)
            raise

        remaining_row_budget -= len(batch.rows)
        try:
            for raw_row in batch.rows:
                row = tuple(raw_row)
                if not accumulator.consider(row, encode_row_payload(row)):
                    break
        except BaseException as exc:
            _close_preserving_primary(stream, exc)
            raise
        if accumulator._truncation_reason is not None:
            try:
                accumulator.elapsed_ms = stream.elapsed_ms
                result = accumulator.finish()
            except BaseException as exc:
                _close_preserving_primary(stream, exc)
                raise
            _interrupt_then_close(stream)
            return result
        if batch.exhausted:
            break

    try:
        accumulator.elapsed_ms = stream.elapsed_ms
        result = accumulator.finish()
    except BaseException as exc:
        _close_preserving_primary(stream, exc)
        raise
    stream.close()
    return result


def _add_cleanup_note(primary: BaseException) -> None:
    notes = getattr(primary, "__notes__", ())
    if CURSOR_CLEANUP_UNCERTAINTY_NOTE not in notes:
        primary.add_note(CURSOR_CLEANUP_UNCERTAINTY_NOTE)


def _close_preserving_primary(stream: ResultStream, primary: BaseException) -> None:
    try:
        stream.close()
    except BaseException:
        _add_cleanup_note(primary)


def _interrupt_then_close(stream: ResultStream) -> None:
    try:
        stream.request_interrupt()
    except BaseException as exc:
        _close_preserving_primary(stream, exc)
        raise
    stream.close()


def _validate_batch(*, batch: ResultBatch, requested_rows: int) -> None:
    if len(batch.rows) > requested_rows or (not batch.rows and not batch.exhausted):
        raise QueryExecutionError(
            _INVALID_BATCH_MESSAGE,
            suggestion=_INVALID_BATCH_SUGGESTION,
        )
