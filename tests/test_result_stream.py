from __future__ import annotations

from collections.abc import Callable

import duckdb
import pytest

from csvql.exceptions import QueryExecutionError
from csvql.operation import OperationContext, OperationToken
from csvql.result_stream import ResultBatch, ResultStream


class RecordingCursor:
    """Cursor double with deterministic batch and cleanup behavior."""

    def __init__(
        self,
        *,
        description: tuple[tuple[str], ...] = (("id",), ("label",)),
        batches: tuple[list[tuple[object, ...]], ...] = (),
        fetch_error: BaseException | None = None,
        close_error: BaseException | None = None,
        on_fetch: Callable[[], None] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.description = description
        self._batches = list(batches)
        self._fetch_error = fetch_error
        self._close_error = close_error
        self._on_fetch = on_fetch
        self._events = events if events is not None else []
        self.fetch_sizes: list[int] = []
        self.close_calls = 0

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        self.fetch_sizes.append(size)
        self._events.append(f"fetchmany:{size}")
        if self._on_fetch is not None:
            self._on_fetch()
        if self._fetch_error is not None:
            raise self._fetch_error
        if not self._batches:
            return []
        return self._batches.pop(0)

    def close(self) -> None:
        self.close_calls += 1
        self._events.append("cursor-close")
        if self._close_error is not None:
            raise self._close_error


def _stream(
    cursor: RecordingCursor,
    *,
    events: list[str] | None = None,
    close_owner: Callable[[], None] | None = None,
    request_interrupt: Callable[[], None] | None = None,
    discard_cursor: Callable[[], None] | None = None,
) -> ResultStream:
    event_log = events if events is not None else []
    return ResultStream(
        cursor=cursor,
        operation=OperationContext(token=OperationToken()),
        started_at=0.0,
        now=lambda: 0.25,
        close_owner=close_owner or (lambda: event_log.append("owner-close")),
        request_interrupt=request_interrupt or (lambda: event_log.append("interrupt")),
        discard_cursor=discard_cursor,
    )


def test_result_stream_captures_columns_and_fetches_only_requested_rows() -> None:
    cursor = RecordingCursor(
        batches=(
            [(1, "first"), [2, "second"]],
            [(3, "third")],
            [],
        )
    )
    stream = _stream(cursor)

    assert stream.columns == ("id", "label")
    assert stream.elapsed_ms == 0.0

    first = stream.fetch_rows(2)
    second = stream.fetch_rows(5)
    third = stream.fetch_rows(1)

    assert first == ResultBatch(rows=((1, "first"), (2, "second")), exhausted=False)
    assert second == ResultBatch(rows=((3, "third"),), exhausted=False)
    assert third == ResultBatch(rows=(), exhausted=True)
    assert cursor.fetch_sizes == [2, 5, 1]


def test_result_stream_rejects_non_positive_fetch_size() -> None:
    stream = _stream(RecordingCursor())

    with pytest.raises(ValueError, match="positive"):
        stream.fetch_rows(0)

    with pytest.raises(ValueError, match="positive"):
        stream.fetch_rows(-1)


def test_result_stream_fetch_failure_becomes_query_execution_error_and_closes() -> None:
    events: list[str] = []
    cursor = RecordingCursor(fetch_error=duckdb.Error("private fetch detail"), events=events)
    stream = _stream(cursor, events=events)

    with pytest.raises(QueryExecutionError, match="private fetch detail"):
        stream.fetch_rows(1)

    assert events == ["fetchmany:1", "cursor-close", "owner-close"]
    assert cursor.close_calls == 1


def test_result_stream_fetch_failure_uses_discard_callback_when_provided() -> None:
    events: list[str] = []
    cursor = RecordingCursor(fetch_error=duckdb.Error("private fetch detail"), events=events)
    stream = _stream(
        cursor,
        events=events,
        discard_cursor=lambda: events.append("discard-cursor"),
    )

    with pytest.raises(QueryExecutionError, match="private fetch detail"):
        stream.fetch_rows(1)

    assert events == ["fetchmany:1", "discard-cursor", "owner-close"]
    assert cursor.close_calls == 0


def test_result_stream_fetch_failure_preserves_primary_when_close_also_fails() -> None:
    cursor = RecordingCursor(
        fetch_error=duckdb.Error("private fetch detail"),
        close_error=RuntimeError("private close detail"),
    )
    stream = _stream(cursor)

    with pytest.raises(QueryExecutionError, match="private fetch detail") as captured:
        stream.fetch_rows(1)

    notes = "\n".join(getattr(captured.value, "__notes__", ()))
    assert "cursor could not be closed" in notes
    assert "private close detail" not in notes


def test_result_stream_request_interrupt_and_close_are_idempotent() -> None:
    events: list[str] = []
    stream = _stream(RecordingCursor(events=events), events=events)

    stream.request_interrupt()
    stream.close()
    stream.close()

    assert events == ["interrupt", "cursor-close", "owner-close"]


def test_result_stream_close_after_cancel_uses_discard_callback() -> None:
    events: list[str] = []
    operation = OperationContext(token=OperationToken())
    stream = ResultStream(
        cursor=RecordingCursor(events=events),
        operation=operation,
        started_at=0.0,
        now=lambda: 0.25,
        close_owner=lambda: events.append("owner-close"),
        request_interrupt=lambda: events.append("interrupt"),
        discard_cursor=lambda: events.append("discard-cursor"),
    )

    operation.request_cancel()
    stream.close()

    assert events == ["discard-cursor", "owner-close"]


def test_result_stream_close_failure_does_not_release_owner_and_repeats_failure() -> None:
    events: list[str] = []
    stream = _stream(
        RecordingCursor(events=events, close_error=RuntimeError("private close detail")),
        events=events,
    )

    with pytest.raises(RuntimeError, match="private close detail"):
        stream.close()

    with pytest.raises(RuntimeError, match="private close detail"):
        stream.close()

    assert events == ["cursor-close"]


def test_result_stream_close_runs_cursor_before_owner_and_tracks_elapsed_time() -> None:
    events: list[str] = []
    cursor = RecordingCursor(
        batches=([],),
        events=events,
    )
    elapsed_points = iter((0.125, 0.375))
    stream = ResultStream(
        cursor=cursor,
        operation=OperationContext(token=OperationToken()),
        started_at=0.0,
        now=lambda: next(elapsed_points),
        close_owner=lambda: events.append("owner-close"),
        request_interrupt=lambda: events.append("interrupt"),
    )

    batch = stream.fetch_rows(3)
    stream.close()

    assert batch == ResultBatch(rows=(), exhausted=True)
    assert stream.elapsed_ms == 125.0
    assert events == ["fetchmany:3", "cursor-close", "owner-close"]
