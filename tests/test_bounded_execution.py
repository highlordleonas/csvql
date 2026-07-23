from __future__ import annotations

import gc
import weakref
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast
from unittest.mock import patch

import pytest

from csvql.bounded_result import PreviewPolicy, collect_bounded_preview
from csvql.exceptions import QueryExecutionError
from csvql.result_codec import encode_row_payload
from csvql.result_stream import CURSOR_CLEANUP_UNCERTAINTY_NOTE, ResultBatch


@dataclass(frozen=True, slots=True)
class _FetchStep:
    rows: tuple[Sequence[object], ...] = ()
    exhausted: bool | None = None
    error: BaseException | None = None


class _RecordingStream:
    def __init__(
        self,
        steps: tuple[_FetchStep, ...],
        *,
        columns: tuple[str, ...] = ("id", "label"),
        elapsed_ms: float = 12.5,
        interrupt_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.columns = columns
        self.elapsed_ms = elapsed_ms
        self._steps = list(steps)
        self._interrupt_error = interrupt_error
        self._close_error = close_error
        self.fetch_sizes: list[int] = []
        self.returned_row_total = 0
        self.events: list[str] = []
        self.interrupt_calls = 0
        self.close_calls = 0

    @property
    def remaining_steps(self) -> int:
        return len(self._steps)

    def fetch_rows(self, max_rows: int) -> ResultBatch:
        self.fetch_sizes.append(max_rows)
        self.events.append(f"fetch:{max_rows}")
        if not self._steps:
            raise AssertionError("Unexpected fetch after scripted proof.")
        step = self._steps.pop(0)
        if step.error is not None:
            raise step.error
        rows = cast(tuple[tuple[object, ...], ...], step.rows)
        self.returned_row_total += len(rows)
        exhausted = len(rows) == 0 if step.exhausted is None else step.exhausted
        return ResultBatch(rows=rows, exhausted=exhausted)

    def request_interrupt(self) -> None:
        self.interrupt_calls += 1
        self.events.append("interrupt")
        if self._interrupt_error is not None:
            raise self._interrupt_error

    def close(self) -> None:
        self.close_calls += 1
        self.events.append("close")
        if self._close_error is not None:
            raise self._close_error


class _UninspectableRow(Sequence[object]):
    def __len__(self) -> int:
        return 1

    def __getitem__(self, index: int) -> object:
        raise AssertionError(f"Row should not be inspected: {index}")


class _LargePayload:
    def __init__(self, text: str) -> None:
        self.text = text

    def __reduce__(self) -> tuple[object, tuple[str]]:
        return (_LargePayload, (self.text,))


def test_collect_bounded_preview_rejects_zero_fetch_batch_size_before_stream_use() -> None:
    stream = _RecordingStream((_FetchStep(rows=((1,),)),), columns=("id",))

    with pytest.raises(ValueError, match="fetch_batch_size must be positive"):
        collect_bounded_preview(
            stream,
            policy=PreviewPolicy(row_limit=2, payload_limit_bytes=100),
            fetch_batch_size=0,
        )

    assert stream.fetch_sizes == []
    assert stream.interrupt_calls == 0
    assert stream.close_calls == 0
    assert stream.events == []


def test_collect_bounded_preview_rejects_negative_fetch_batch_size_before_stream_use() -> None:
    stream = _RecordingStream((_FetchStep(rows=((1,),)),), columns=("id",))

    with pytest.raises(ValueError, match="fetch_batch_size must be positive"):
        collect_bounded_preview(
            stream,
            policy=PreviewPolicy(row_limit=2, payload_limit_bytes=100),
            fetch_batch_size=-1,
        )

    assert stream.fetch_sizes == []
    assert stream.interrupt_calls == 0
    assert stream.close_calls == 0
    assert stream.events == []


def test_collect_bounded_preview_returns_zero_rows_without_truncation() -> None:
    stream = _RecordingStream((_FetchStep(),))

    result = collect_bounded_preview(
        stream,
        policy=PreviewPolicy(row_limit=3, payload_limit_bytes=100),
        fetch_batch_size=5,
    )

    assert result.columns == ("id", "label")
    assert result.rows == ()
    assert result.preview_payload_bytes == 0
    assert result.has_more_rows is False
    assert result.truncation_reason is None
    assert result.elapsed_ms == 12.5
    assert stream.fetch_sizes == [4]
    assert stream.returned_row_total == 0
    assert stream.interrupt_calls == 0
    assert stream.close_calls == 1
    assert stream.events == ["fetch:4", "close"]


def test_collect_bounded_preview_stops_after_exhaustion_below_row_limit() -> None:
    stream = _RecordingStream((_FetchStep(rows=((1, "one"), (2, "two"))), _FetchStep()))

    result = collect_bounded_preview(
        stream,
        policy=PreviewPolicy(row_limit=5, payload_limit_bytes=1_000),
        fetch_batch_size=2,
    )

    assert result.rows == ((1, "one"), (2, "two"))
    assert result.preview_payload_bytes == sum(len(encode_row_payload(row)) for row in result.rows)
    assert result.has_more_rows is False
    assert result.truncation_reason is None
    assert stream.fetch_sizes == [2, 2]
    assert stream.returned_row_total == 2
    assert stream.interrupt_calls == 0
    assert stream.close_calls == 1


def test_collect_bounded_preview_requires_exhaustion_probe_at_exact_row_limit() -> None:
    stream = _RecordingStream((_FetchStep(rows=([1, "one"], [2, "two"])), _FetchStep()))

    result = collect_bounded_preview(
        stream,
        policy=PreviewPolicy(row_limit=2, payload_limit_bytes=1_000),
        fetch_batch_size=5,
    )

    assert result.rows == ((1, "one"), (2, "two"))
    assert result.preview_payload_bytes == sum(len(encode_row_payload(row)) for row in result.rows)
    assert result.has_more_rows is False
    assert result.truncation_reason is None
    assert stream.fetch_sizes == [3, 1]
    assert stream.returned_row_total == 2
    assert stream.interrupt_calls == 0
    assert stream.close_calls == 1
    assert stream.events == ["fetch:3", "fetch:1", "close"]


def test_collect_bounded_preview_accepts_exact_row_limit_when_batch_is_marked_exhausted() -> None:
    stream = _RecordingStream((_FetchStep(rows=((1, "one"), (2, "two")), exhausted=True),))

    result = collect_bounded_preview(
        stream,
        policy=PreviewPolicy(row_limit=2, payload_limit_bytes=1_000),
        fetch_batch_size=5,
    )

    assert result.rows == ((1, "one"), (2, "two"))
    assert result.preview_payload_bytes == sum(len(encode_row_payload(row)) for row in result.rows)
    assert result.has_more_rows is False
    assert result.truncation_reason is None
    assert stream.fetch_sizes == [3]
    assert stream.returned_row_total == 2
    assert stream.interrupt_calls == 0
    assert stream.close_calls == 1
    assert stream.events == ["fetch:3", "close"]


def test_collect_bounded_preview_detects_limit_plus_one_without_extra_fetch() -> None:
    stream = _RecordingStream(
        (
            _FetchStep(rows=((1, "one"), (2, "two"), (3, "three"))),
            _FetchStep(rows=((4, "four"),)),
        )
    )

    result = collect_bounded_preview(
        stream,
        policy=PreviewPolicy(row_limit=2, payload_limit_bytes=1_000),
        fetch_batch_size=8,
    )

    assert result.rows == ((1, "one"), (2, "two"))
    assert result.has_more_rows is True
    assert result.truncation_reason == "row_limit"
    assert stream.fetch_sizes == [3]
    assert stream.returned_row_total == 3
    assert stream.interrupt_calls == 1
    assert stream.close_calls == 1
    assert stream.events == ["fetch:3", "interrupt", "close"]
    assert stream.remaining_steps == 1


def test_collect_bounded_preview_caps_row_limit_budget_across_multiple_fetches() -> None:
    stream = _RecordingStream(
        (
            _FetchStep(rows=((1, "one"), (2, "two"))),
            _FetchStep(rows=((3, "three"), (4, "four"))),
        )
    )

    result = collect_bounded_preview(
        stream,
        policy=PreviewPolicy(row_limit=3, payload_limit_bytes=1_000),
        fetch_batch_size=2,
    )

    assert result.rows == ((1, "one"), (2, "two"), (3, "three"))
    assert result.has_more_rows is True
    assert result.truncation_reason == "row_limit"
    assert all(size > 0 for size in stream.fetch_sizes)
    assert all(size <= 2 for size in stream.fetch_sizes)
    assert stream.fetch_sizes == [2, 2]
    assert stream.returned_row_total == 4
    assert stream.interrupt_calls == 1
    assert stream.close_calls == 1


def test_collect_bounded_preview_large_stream_keeps_only_limit_and_one_probe() -> None:
    class LargeRecordingStream:
        def __init__(self, total_rows: int) -> None:
            self.columns = ("row_id",)
            self.elapsed_ms = 25.0
            self._next_row = 0
            self._total_rows = total_rows
            self.fetch_sizes: list[int] = []
            self.returned_row_total = 0
            self.events: list[str] = []
            self.interrupt_calls = 0
            self.close_calls = 0
            self.count_calls = 0
            self.reexecute_calls = 0

        def fetch_rows(self, max_rows: int) -> ResultBatch:
            self.fetch_sizes.append(max_rows)
            self.events.append(f"fetch:{max_rows}")
            remaining = self._total_rows - self._next_row
            emitted = min(max_rows, remaining)
            rows = tuple((row_id,) for row_id in range(self._next_row, self._next_row + emitted))
            self._next_row += emitted
            self.returned_row_total += emitted
            return ResultBatch(rows=rows, exhausted=self._next_row >= self._total_rows)

        def request_interrupt(self) -> None:
            self.interrupt_calls += 1
            self.events.append("interrupt")

        def close(self) -> None:
            self.close_calls += 1
            self.events.append("close")

        def count_rows(self) -> int:
            self.count_calls += 1
            raise AssertionError("bounded preview must not issue a count")

        def reexecute(self) -> None:
            self.reexecute_calls += 1
            raise AssertionError("bounded preview must not rerun the query")

    stream = LargeRecordingStream(total_rows=10_000)

    result = collect_bounded_preview(
        stream,
        policy=PreviewPolicy(row_limit=1_000, payload_limit_bytes=16 * 1024 * 1024),
        fetch_batch_size=512,
    )

    assert len(result.rows) == 1_000
    assert result.rows[0] == (0,)
    assert result.rows[-1] == (999,)
    assert result.has_more_rows is True
    assert result.truncation_reason == "row_limit"
    assert stream.fetch_sizes == [512, 489]
    assert stream.returned_row_total == 1_001
    assert stream.interrupt_calls == 1
    assert stream.close_calls == 1
    assert stream.count_calls == 0
    assert stream.reexecute_calls == 0
    assert stream.events == ["fetch:512", "fetch:489", "interrupt", "close"]


def test_collect_bounded_preview_stops_on_first_row_that_exceeds_byte_limit() -> None:
    kept = (1, "one")
    omitted = (2, "two")
    stream = _RecordingStream((_FetchStep(rows=(kept, omitted, (3, "three"))),))
    payload_limit = len(encode_row_payload(kept))

    result = collect_bounded_preview(
        stream,
        policy=PreviewPolicy(row_limit=5, payload_limit_bytes=payload_limit),
        fetch_batch_size=5,
    )

    assert result.rows == (kept,)
    assert result.preview_payload_bytes == payload_limit
    assert result.has_more_rows is True
    assert result.truncation_reason == "byte_limit"
    assert stream.fetch_sizes == [5]
    assert stream.interrupt_calls == 1
    assert stream.close_calls == 1
    assert stream.events == ["fetch:5", "interrupt", "close"]


def test_collect_bounded_preview_marks_oversized_first_row_as_byte_truncation() -> None:
    oversized = ("x" * 200,)
    stream = _RecordingStream((_FetchStep(rows=(oversized,)),), columns=("payload",))

    result = collect_bounded_preview(
        stream,
        policy=PreviewPolicy(row_limit=3, payload_limit_bytes=10),
        fetch_batch_size=1,
    )

    assert result.columns == ("payload",)
    assert result.rows == ()
    assert result.preview_payload_bytes == 0
    assert result.has_more_rows is True
    assert result.truncation_reason == "byte_limit"
    assert stream.fetch_sizes == [1]
    assert stream.interrupt_calls == 1
    assert stream.close_calls == 1


def test_collect_bounded_preview_does_not_retain_oversized_row_object() -> None:
    oversized = _LargePayload("x" * (16 * 1024 * 1024 + 1))
    released: list[str] = []
    finalized = weakref.finalize(oversized, released.append, "released")
    stream = _RecordingStream((_FetchStep(rows=((oversized,),)),), columns=("payload",))

    result = collect_bounded_preview(
        stream,
        policy=PreviewPolicy(row_limit=3, payload_limit_bytes=16 * 1024 * 1024),
        fetch_batch_size=1,
    )

    del oversized
    gc.collect()

    assert result.rows == ()
    assert result.preview_payload_bytes == 0
    assert result.has_more_rows is True
    assert result.truncation_reason == "byte_limit"
    assert stream.fetch_sizes == [1]
    assert stream.interrupt_calls == 1
    assert stream.close_calls == 1
    assert finalized.alive is False
    assert released == ["released"]


def test_collect_bounded_preview_preserves_fetch_failure_when_close_also_fails() -> None:
    stream = _RecordingStream(
        (_FetchStep(error=QueryExecutionError("DuckDB query failed: fetch broke")),),
        close_error=RuntimeError("private close detail"),
    )

    with pytest.raises(QueryExecutionError, match="fetch broke") as captured:
        collect_bounded_preview(
            stream,
            policy=PreviewPolicy(row_limit=3, payload_limit_bytes=100),
            fetch_batch_size=2,
        )

    notes = "\n".join(getattr(captured.value, "__notes__", ()))
    assert CURSOR_CLEANUP_UNCERTAINTY_NOTE in notes
    assert "private close detail" not in notes
    assert stream.interrupt_calls == 0
    assert stream.close_calls == 1


def test_collect_bounded_preview_preserves_base_exception_primary_when_close_fails() -> None:
    primary = KeyboardInterrupt()
    stream = _RecordingStream(
        (_FetchStep(error=primary),),
        close_error=RuntimeError("private close detail"),
    )

    with pytest.raises(KeyboardInterrupt) as captured:
        collect_bounded_preview(
            stream,
            policy=PreviewPolicy(row_limit=3, payload_limit_bytes=100),
            fetch_batch_size=2,
        )

    assert captured.value is primary
    notes = "\n".join(getattr(captured.value, "__notes__", ()))
    assert CURSOR_CLEANUP_UNCERTAINTY_NOTE in notes
    assert "private close detail" not in notes
    assert stream.events == ["fetch:2", "close"]


def test_collect_bounded_preview_preserves_encode_primary_when_close_fails() -> None:
    primary = SystemExit(3)
    stream = _RecordingStream(
        (_FetchStep(rows=((1,),)),),
        close_error=RuntimeError("private close detail"),
    )

    with (
        patch("csvql.bounded_result.encode_row_payload", side_effect=primary),
        pytest.raises(SystemExit) as captured,
    ):
        collect_bounded_preview(
            stream,
            policy=PreviewPolicy(row_limit=3, payload_limit_bytes=100),
            fetch_batch_size=2,
        )

    assert captured.value is primary
    notes = "\n".join(getattr(captured.value, "__notes__", ()))
    assert CURSOR_CLEANUP_UNCERTAINTY_NOTE in notes
    assert "private close detail" not in notes
    assert stream.events == ["fetch:2", "close"]


def test_collect_bounded_preview_raises_interrupt_failure_after_successful_close() -> None:
    stream = _RecordingStream(
        (_FetchStep(rows=((1,), (2,), (3,))),),
        interrupt_error=RuntimeError("private interrupt detail"),
        columns=("id",),
    )

    with pytest.raises(RuntimeError, match="private interrupt detail"):
        collect_bounded_preview(
            stream,
            policy=PreviewPolicy(row_limit=2, payload_limit_bytes=100),
            fetch_batch_size=4,
        )

    assert stream.events == ["fetch:3", "interrupt", "close"]
    assert stream.close_calls == 1


def test_collect_bounded_preview_preserves_interrupt_failure_when_close_also_fails() -> None:
    stream = _RecordingStream(
        (_FetchStep(rows=((1,), (2,), (3,))),),
        interrupt_error=RuntimeError("private interrupt detail"),
        close_error=RuntimeError("private close detail"),
        columns=("id",),
    )

    with pytest.raises(RuntimeError, match="private interrupt detail") as captured:
        collect_bounded_preview(
            stream,
            policy=PreviewPolicy(row_limit=2, payload_limit_bytes=100),
            fetch_batch_size=4,
        )

    notes = "\n".join(getattr(captured.value, "__notes__", ()))
    assert CURSOR_CLEANUP_UNCERTAINTY_NOTE in notes
    assert "private close detail" not in notes
    assert stream.events == ["fetch:3", "interrupt", "close"]


def test_collect_bounded_preview_rejects_over_returned_batch_before_row_inspection() -> None:
    stream = _RecordingStream(
        (
            _FetchStep(
                rows=(
                    _UninspectableRow(),
                    _UninspectableRow(),
                    _UninspectableRow(),
                )
            ),
            _FetchStep(rows=((4,),)),
        ),
        columns=("id",),
    )

    with pytest.raises(QueryExecutionError, match="invalid result stream batch") as captured:
        collect_bounded_preview(
            stream,
            policy=PreviewPolicy(row_limit=5, payload_limit_bytes=100),
            fetch_batch_size=2,
        )

    assert captured.value.suggestion == (
        "Retry the query. If the problem persists, report this as a bug."
    )
    assert stream.fetch_sizes == [2]
    assert stream.returned_row_total == 3
    assert stream.interrupt_calls == 0
    assert stream.close_calls == 1
    assert stream.events == ["fetch:2", "close"]
    assert stream.remaining_steps == 1


def test_collect_bounded_preview_rejects_empty_non_exhausted_batch_without_retry() -> None:
    stream = _RecordingStream(
        (
            _FetchStep(rows=(), exhausted=False),
            _FetchStep(rows=((1,),), exhausted=True),
        ),
        columns=("id",),
    )

    with pytest.raises(QueryExecutionError, match="invalid result stream batch") as captured:
        collect_bounded_preview(
            stream,
            policy=PreviewPolicy(row_limit=5, payload_limit_bytes=100),
            fetch_batch_size=2,
        )

    assert captured.value.suggestion == (
        "Retry the query. If the problem persists, report this as a bug."
    )
    assert stream.fetch_sizes == [2]
    assert stream.interrupt_calls == 0
    assert stream.close_calls == 1
    assert stream.events == ["fetch:2", "close"]
    assert stream.remaining_steps == 1


def test_collect_bounded_preview_preserves_invalid_batch_primary_when_close_also_fails() -> None:
    stream = _RecordingStream(
        (_FetchStep(rows=(), exhausted=False),),
        close_error=RuntimeError("private close detail"),
        columns=("id",),
    )

    with pytest.raises(QueryExecutionError, match="invalid result stream batch") as captured:
        collect_bounded_preview(
            stream,
            policy=PreviewPolicy(row_limit=5, payload_limit_bytes=100),
            fetch_batch_size=2,
        )

    notes = "\n".join(getattr(captured.value, "__notes__", ()))
    assert CURSOR_CLEANUP_UNCERTAINTY_NOTE in notes
    assert "private close detail" not in notes
