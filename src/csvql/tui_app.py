"""Minimal Textual shell for the CSVQL menu TUI."""

from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Static, TextArea

from csvql.exceptions import CSVQLError
from csvql.output import format_table_result
from csvql.tui_state import TUISessionState
from csvql.tui_workflows import build_initial_state, query_sources


class CSVQLMenuApp(App[None]):
    """Minimal interactive menu for loading sources and running SQL."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "run_query", "Run query"),
    ]

    def __init__(
        self,
        *,
        csv_path: str | None = None,
        table_mappings: Sequence[str] = (),
        start_dir: Path | None = None,
        initial_state: TUISessionState | None = None,
    ) -> None:
        super().__init__()
        self.start_dir = (start_dir or Path.cwd()).resolve()
        if initial_state is not None:
            self.state = initial_state
        else:
            self.state = build_initial_state(
                csv_path=csv_path,
                table_mappings=table_mappings,
                start_dir=self.start_dir,
            )

    def compose(self) -> ComposeResult:
        yield Static("", id="status")
        yield DataTable(id="sources")
        yield TextArea(id="sql")
        yield Static("", id="results")

    async def on_mount(self) -> None:
        self._refresh_sources_table()
        self._set_status(self._status_message())

    def action_run_query(self) -> None:
        sql_widget = self.query_one("#sql", TextArea)
        sql = sql_widget.text.strip()
        if not sql:
            self.state.last_result = None
            self._show_error(
                CSVQLError(
                    "Enter SQL before running a query.",
                    suggestion="Type a SQL statement in the editor and try again.",
                )
            )
            return

        if not self.state.sources:
            self.state.last_result = None
            self._show_error(
                CSVQLError(
                    "No sources loaded.",
                    suggestion="Add a source before running SQL.",
                )
            )
            return

        try:
            result = query_sources(self.state.sources, sql)
        except CSVQLError as exc:
            self.state.last_result = None
            self._show_error(exc)
            return

        self.state.set_last_result(result)
        self.query_one("#results", Static).update(format_table_result(result))
        self._set_status(f"{result.row_count} row(s) returned.")

    def _refresh_sources_table(self) -> None:
        sources_table = self.query_one("#sources", DataTable)
        sources_table.clear(columns=True)
        sources_table.add_columns("alias", "path", "origin")
        for source in self.state.sources:
            sources_table.add_row(source.name, str(source.path), source.origin)

    def _status_message(self) -> str:
        source_count = len(self.state.sources)
        if source_count == 0:
            return "No sources loaded. Add a source before running SQL."
        if source_count == 1:
            return "1 source loaded."
        return f"{source_count} sources loaded."

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _show_error(self, error: CSVQLError) -> None:
        lines = [f"Error: {error.message}"]
        if error.suggestion:
            lines.append(f"Suggestion: {error.suggestion}")
        message = "\n".join(lines)
        self._set_status(message)
        self.query_one("#results", Static).update(message)
