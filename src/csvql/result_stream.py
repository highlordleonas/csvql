"""Private streaming query result primitives."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import duckdb

from csvql.exceptions import QueryExecutionError
from csvql.operation import OperationCancelled, OperationContext

CURSOR_CLEANUP_UNCERTAINTY_NOTE = (
    "Cleanup uncertainty: the active result cursor could not be closed."
)


@dataclass(frozen=True, slots=True)
class ResultBatch:
    """One bounded batch fetched from a live DuckDB cursor."""

    rows: tuple[tuple[object, ...], ...]
    exhausted: bool


class ResultStream:
    """Single-consumer wrapper around one live DuckDB cursor."""

    def __init__(
        self,
        *,
        cursor: duckdb.DuckDBPyConnection,
        operation: OperationContext,
        started_at: float,
        close_owner: Callable[[], None],
        request_interrupt: Callable[[], None],
        now: Callable[[], float],
    ) -> None:
        self._cursor = cursor
        self._operation = operation
        self._started_at = started_at
        self._close_owner = close_owner
        self._request_interrupt = request_interrupt
        self._now = now
        self._columns = tuple(column[0] for column in cursor.description or ())
        self._elapsed_ms = 0.0
        self._closed = False
        self._close_failure: BaseException | None = None
        self._exhausted = False

    @property
    def columns(self) -> tuple[str, ...]:
        return self._columns

    @property
    def elapsed_ms(self) -> float:
        return self._elapsed_ms

    def fetch_rows(self, max_rows: int) -> ResultBatch:
        if max_rows <= 0:
            raise ValueError("Result stream fetch size must be positive.")
        if self._close_failure is not None:
            raise self._close_failure
        if self._closed:
            return ResultBatch(rows=(), exhausted=True)
        if self._exhausted:
            return ResultBatch(rows=(), exhausted=True)

        try:
            self._operation.checkpoint()
            raw_rows = self._cursor.fetchmany(max_rows)
            self._operation.checkpoint()
        except OperationCancelled as exc:
            self._close_preserving(exc)
            raise
        except duckdb.Error as exc:
            self._update_elapsed()
            if self._operation.token.is_cancelled:
                cancelled = OperationCancelled("Operation cancelled.")
                self._close_preserving(cancelled)
                raise cancelled from exc
            public_error = QueryExecutionError(
                f"DuckDB query failed: {exc}",
                suggestion="Check table names, column names, and SQL syntax.",
            )
            self._close_preserving(public_error)
            raise public_error from exc
        except BaseException as exc:
            self._update_elapsed()
            self._close_preserving(exc)
            raise

        rows = tuple(_normalize_row(row) for row in raw_rows)
        exhausted = _is_exhausted(rows=rows)
        self._exhausted = exhausted
        self._update_elapsed()
        return ResultBatch(rows=rows, exhausted=exhausted)

    def request_interrupt(self) -> None:
        self._request_interrupt()

    def close(self) -> None:
        if self._close_failure is not None:
            raise self._close_failure
        if self._closed:
            return
        self._close_preserving(primary=None)

    def _close_preserving(self, primary: BaseException | None) -> None:
        if self._close_failure is not None:
            if primary is not None:
                _add_cleanup_note(primary)
                return
            raise self._close_failure
        if self._closed:
            return
        close_error: BaseException | None = None
        try:
            self._cursor.close()
        except BaseException as exc:
            close_error = exc
        if close_error is None:
            self._closed = True
            self._close_owner()
            return
        self._close_failure = close_error
        if primary is not None:
            _add_cleanup_note(primary)
            return
        raise close_error

    def _update_elapsed(self) -> None:
        self._elapsed_ms = (self._now() - self._started_at) * 1000


def _normalize_row(row: Sequence[object]) -> tuple[object, ...]:
    return tuple(row)


def _is_exhausted(*, rows: tuple[tuple[object, ...], ...]) -> bool:
    return len(rows) == 0


def _add_cleanup_note(primary: BaseException) -> None:
    notes = getattr(primary, "__notes__", ())
    if CURSOR_CLEANUP_UNCERTAINTY_NOTE not in notes:
        primary.add_note(CURSOR_CLEANUP_UNCERTAINTY_NOTE)
