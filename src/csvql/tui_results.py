"""Result-grid display helpers for the CSVQL Workbench TUI."""

from typing import Protocol

from rich.text import Text

from csvql.models import QueryResult
from csvql.terminal_text import literal_terminal_text, terminal_safe_text
from csvql.tui_state import TUIResultViewState


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


def result_preview_message(view: TUIResultViewState) -> str:
    """Return the status text for the current result preview."""

    if view.is_truncated:
        return (
            f"Showing first {view.preview_row_cap:,} of {view.total_row_count:,} "
            "returned row(s). Export/save use the full active result."
        )
    return f"Showing {view.total_row_count} returned row(s)."


def _display_cell(value: object, *, cell_char_cap: int) -> str:
    text = terminal_safe_text(value)
    if len(text) <= cell_char_cap:
        return text
    if cell_char_cap <= 3:
        return text[:cell_char_cap]
    return f"{text[: cell_char_cap - 3]}..."
