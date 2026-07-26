"""Result-grid display helpers for the CSVQL Workbench TUI."""

from typing import Protocol

from rich.text import Text

from csvql.bounded_result import BoundedQueryResult
from csvql.models import QueryResult
from csvql.terminal_text import literal_terminal_text, terminal_safe_text
from csvql.tui_result_store import TUIResultReason
from csvql.tui_state import TUIResultRecord, TUIResultViewState


class _ResultTable(Protocol):
    def clear(self, *, columns: bool = False) -> object: ...

    def add_columns(self, *labels: Text) -> object: ...

    def add_row(self, *cells: Text) -> object: ...


DEFAULT_RESULT_PREVIEW_ROWS = 1000
DEFAULT_CELL_CHAR_CAP = 120


def make_result_view_state(
    result: QueryResult,
    *,
    source_result_sequence: int,
    preview_row_cap: int = DEFAULT_RESULT_PREVIEW_ROWS,
    cell_char_cap: int = DEFAULT_CELL_CHAR_CAP,
) -> TUIResultViewState:
    """Return capped, display-only state for the results grid."""

    capped_rows = result.rows[:preview_row_cap]
    display_rows = tuple(
        tuple(_display_cell(value, cell_char_cap=cell_char_cap) for value in row)
        for row in capped_rows
    )
    return TUIResultViewState(
        columns=result.columns,
        display_rows=display_rows,
        total_row_count=result.row_count,
        preview_row_cap=preview_row_cap,
        cell_char_cap=cell_char_cap,
        is_truncated=result.row_count > preview_row_cap,
        truncation_reason="row_limit" if result.row_count > preview_row_cap else None,
        source_result_sequence=source_result_sequence,
    )


def make_bounded_result_view_state(
    result: BoundedQueryResult,
    *,
    source_result_sequence: int,
    cell_char_cap: int = DEFAULT_CELL_CHAR_CAP,
) -> TUIResultViewState:
    """Return display-only state for an already-bounded preview result."""

    display_rows = tuple(
        tuple(_display_cell(value, cell_char_cap=cell_char_cap) for value in row)
        for row in result.rows
    )
    preview_row_count = len(result.rows)
    return TUIResultViewState(
        columns=result.columns,
        display_rows=display_rows,
        total_row_count=preview_row_count,
        preview_row_cap=preview_row_count,
        cell_char_cap=cell_char_cap,
        is_truncated=result.has_more_rows,
        truncation_reason=result.truncation_reason,
        source_result_sequence=source_result_sequence,
    )


def populate_result_table(table: _ResultTable, view: TUIResultViewState) -> None:
    """Populate a Textual table from display state."""

    table.clear(columns=True)
    if not view.columns:
        return
    table.add_columns(*(literal_terminal_text(column) for column in view.columns))
    for row in view.display_rows:
        table.add_row(*(literal_terminal_text(cell) for cell in row))


def result_preview_message(
    view: TUIResultViewState,
    *,
    record: TUIResultRecord | None = None,
) -> str:
    """Return the status text for the current result preview."""

    if record is None:
        return _legacy_result_preview_message(view)

    if record.state == "executing":
        return "Running query. Results will appear when the bounded preview is ready."
    if record.state == "cancelled":
        return "Query cancelled before a preview was retained."
    if record.state == "failed":
        return "Query failed before a preview was retained."
    if record.state == "preserving":
        message = f"Showing {record.preview_row_count:,} retained preview row(s)."
        if view.is_truncated:
            truncation_detail = _truncation_detail(view)
            message = (
                f"{message} {truncation_detail or 'More rows exist beyond the retained preview.'}"
            )
        return (
            f"{message} Full result preservation is still running. "
            "Full export/save stay unavailable until it finishes."
        )
    if record.state == "complete":
        if record.full_row_count == record.preview_row_count and not view.is_truncated:
            return (
                f"Showing {record.full_row_count:,} total row(s). "
                "Full export/save use the preserved result."
            )
        return (
            f"Showing {record.preview_row_count:,} retained preview row(s) from "
            f"{record.full_row_count:,} total row(s). Full export/save use the preserved result."
        )
    if record.state == "preview_only":
        return (
            f"Showing {record.preview_row_count:,} retained preview row(s). "
            f"{_preview_only_reason_message(record.reason)} "
            "Full export/save are unavailable for this result."
        )

    return _legacy_result_preview_message(view)


def _legacy_result_preview_message(view: TUIResultViewState) -> str:
    if view.is_truncated:
        return (
            f"Showing first {view.preview_row_cap:,} of {view.total_row_count:,} "
            "returned row(s). Export/save use the full active result."
        )
    return f"Showing {view.total_row_count} returned row(s)."


def _truncation_detail(view: TUIResultViewState) -> str | None:
    if not view.is_truncated:
        return None
    if view.truncation_reason == "row_limit":
        return "More rows exist beyond the interactive row limit."
    if view.truncation_reason == "byte_limit":
        return "More rows exist beyond the fixed preview byte ceiling."
    return "More rows exist beyond the retained preview."


def _preview_only_reason_message(reason: TUIResultReason | None) -> str:
    if reason == "user_cancelled":
        return "Preservation stopped because it was cancelled."
    if reason == "session_spool_limit":
        return "Preservation stopped because the TUI session capacity was exhausted."
    if reason == "preservation_failed":
        return "Preservation stopped because writing the full result failed."
    return "Preservation stopped before the full result was retained."


def _display_cell(value: object, *, cell_char_cap: int) -> str:
    text = terminal_safe_text(value)
    if len(text) <= cell_char_cap:
        return text
    if cell_char_cap <= 3:
        return text[:cell_char_cap]
    return f"{text[: cell_char_cap - 3]}..."
