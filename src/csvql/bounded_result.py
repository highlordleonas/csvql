"""Private bounded preview result types for LocalQL query execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from csvql.result_codec import encode_row_payload
from csvql.result_stream import CURSOR_CLEANUP_UNCERTAINTY_NOTE, ResultStream

DEFAULT_INTERACTIVE_ROW_LIMIT = 1_000
MAX_PREVIEW_PAYLOAD_BYTES = 16 * 1024 * 1024
TruncationReason = Literal["row_limit", "byte_limit"]


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
    primary: BaseException | None = None
    result: BoundedQueryResult | None = None

    try:
        while remaining_row_budget > 0:
            batch = stream.fetch_rows(min(fetch_batch_size, remaining_row_budget))
            remaining_row_budget -= len(batch.rows)

            for raw_row in batch.rows:
                row = tuple(raw_row)
                if not accumulator.consider(row, encode_row_payload(row)):
                    break
            if accumulator._truncation_reason is not None:
                break
            if batch.exhausted:
                break

        accumulator.elapsed_ms = stream.elapsed_ms
        result = accumulator.finish()
    except BaseException as exc:
        primary = exc
    finally:
        if accumulator._truncation_reason is not None:
            try:
                stream.request_interrupt()
            except BaseException as exc:
                if primary is None:
                    primary = exc
        try:
            stream.close()
        except BaseException:
            if primary is None:
                raise
            _add_cleanup_note(primary)
    if primary is not None:
        raise primary
    if result is None:
        raise AssertionError("Bounded preview collection did not produce a result.")
    return result


def _add_cleanup_note(primary: BaseException) -> None:
    notes = getattr(primary, "__notes__", ())
    if CURSOR_CLEANUP_UNCERTAINTY_NOTE not in notes:
        primary.add_note(CURSOR_CLEANUP_UNCERTAINTY_NOTE)
