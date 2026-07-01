"""Minimal Textual shell for the CSVQL menu TUI."""

from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Static, TextArea

from csvql.exceptions import CSVQLError
from csvql.export import ExportFormat
from csvql.models import QueryResult
from csvql.output import format_profile_result_table, format_table_result
from csvql.table_mapping import parse_table_mapping
from csvql.tui_help import WORKBENCH_HELP
from csvql.tui_state import TUISessionState, TUISource
from csvql.tui_workflows import (
    build_initial_state,
    export_last_result,
    inspect_source,
    profile_source,
    query_sources,
    sample_source,
    save_sources_to_project_catalog,
)


class _PromptInputScreen(ModalScreen[str | None]):
    """Generic modal prompt for one-line TUI input."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, prompt: str, *, input_id: str) -> None:
        super().__init__()
        self.prompt = prompt
        self.input_id = input_id

    def compose(self) -> ComposeResult:
        yield Static(self.prompt)
        yield Input(id=self.input_id)

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class _HelpScreen(ModalScreen[None]):
    """Workbench help modal."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("escape", "cancel", "Close"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(WORKBENCH_HELP, id="help-text")

    def action_cancel(self) -> None:
        self.dismiss(None)


class CSVQLMenuApp(App[None]):
    """Minimal interactive menu for loading sources and running SQL."""

    CSS = """
    #status {
        height: 1;
    }

    #sources {
        height: 5;
    }

    #workbench {
        height: 1fr;
    }

    #left-pane {
        width: 32%;
    }

    #right-pane {
        width: 68%;
    }

    #history {
        height: 1fr;
    }

    #run-status {
        height: 1;
    }

    #sql {
        height: 8;
    }

    #results {
        height: 1fr;
        overflow-y: auto;
    }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit", "Quit", show=False),
        Binding("f1", "inspect_source", "Inspect", priority=True),
        Binding("f2", "sample_source", "Sample", priority=True),
        Binding("f3", "profile_source", "Profile", priority=True),
        Binding(
            "f4,ctrl+enter",
            "run_query",
            "Run SQL",
            key_display="F4/Ctrl+Enter",
            priority=True,
        ),
        Binding("f5", "add_source", "Add source", priority=True),
        Binding("f6", "remove_source", "Remove source", priority=True),
        Binding("f7", "export_last_result", "Export result", priority=True),
        Binding("f8", "save_sources", "Save sources", priority=True),
        Binding("f9", "quit", "Quit", priority=True),
        Binding("f10,ctrl+n", "new_query", "New query", priority=True),
        Binding("ctrl+up", "focus_sources", "Sources", priority=True),
        Binding("ctrl+down", "focus_sql", "SQL", priority=True),
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
        with Horizontal(id="workbench"):
            with Vertical(id="left-pane"):
                yield DataTable(id="sources", cursor_type="row")
                yield DataTable(id="history", cursor_type="row")
            with Vertical(id="right-pane"):
                yield TextArea(id="sql")
                yield Static("", id="run-status")
                yield Static("", id="results")
        yield Footer()

    async def on_mount(self) -> None:
        self._refresh_sources_table()
        self._refresh_history_table()
        self._set_status(self._status_message())
        self.query_one("#sql", TextArea).focus()

    def action_add_source(self) -> None:
        self.push_screen(
            _PromptInputScreen("Enter a name=path mapping.", input_id="mapping-input"),
            callback=self._handle_add_source,
        )

    def action_show_help(self) -> None:
        self.push_screen(_HelpScreen())

    def action_show_contextual_help(self) -> None:
        self.push_screen(_HelpScreen())

    def action_focus_sources(self) -> None:
        self.query_one("#sources", DataTable).focus()

    def action_focus_sql(self) -> None:
        self.query_one("#sql", TextArea).focus()

    def action_new_query(self) -> None:
        sql_widget = self.query_one("#sql", TextArea)
        sql_widget.load_text("")
        sql_widget.focus()
        self._set_status("Ready for next query.")

    def action_remove_source(self) -> None:
        selected_source = self.state.selected_source()
        if selected_source is None:
            self._show_error(CSVQLError("No source selected."))
            return

        removed_source = self.state.remove_source(selected_source.name)
        self._refresh_sources_table()
        self._set_status(f"Removed source {removed_source.name}. {self._status_message()}")

    def action_inspect_source(self) -> None:
        source = self.state.selected_source()
        if source is None:
            self._show_error(CSVQLError("No source selected."))
            return

        try:
            result = inspect_source(source)
        except CSVQLError as exc:
            self._show_error(exc)
            return

        column_names = ", ".join(column.name for column in result.columns) or "(none)"
        self.query_one("#results", Static).update(f"Columns: {column_names}")
        self._set_status(f"{source.name}: {len(result.columns)} columns.")

    def action_profile_source(self) -> None:
        source = self.state.selected_source()
        if source is None:
            self._show_error(CSVQLError("No source selected."))
            return

        try:
            result = profile_source(source)
        except CSVQLError as exc:
            self._show_error(exc)
            return

        self.query_one("#results", Static).update(format_profile_result_table(result))
        self._set_status(
            f"{source.name}: {result.row_count} rows, "
            f"{result.column_count} columns, {result.duplicate_row_count} duplicate rows.",
        )

    def action_sample_source(self) -> None:
        source = self.state.selected_source()
        if source is None:
            self._show_error(CSVQLError("No source selected."))
            return

        try:
            result = sample_source(source)
        except CSVQLError as exc:
            self._show_error(exc)
            return

        query_result = QueryResult(
            columns=result.columns,
            rows=result.rows,
            elapsed_ms=0.0,
        )
        self.query_one("#results", Static).update(format_table_result(query_result))
        self._set_status(f"{source.name}: {len(result.rows)} sample row(s).")

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
        sql_widget.focus()

    def action_export_last_result(self) -> None:
        if self.state.last_result is None:
            self._show_error(CSVQLError("Run a query before exporting."))
            return

        self.push_screen(
            _PromptInputScreen("Enter an export path.", input_id="export-path"),
            callback=self._handle_export_last_result,
        )

    def action_save_sources(self) -> None:
        if not self.state.sources:
            self._show_error(CSVQLError("No sources loaded to save."))
            return

        try:
            context = save_sources_to_project_catalog(
                self.state.sources,
                start_dir=self.start_dir,
                replace=True,
            )
        except CSVQLError as exc:
            self._show_error(exc)
            return

        self._set_status(f"Saved sources to {context.config_path}.")
        self.query_one("#results", Static).update(f"Saved sources to {context.config_path}.")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._select_source_at_row(event.cursor_row)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._select_source_at_row(event.cursor_row)

    def _refresh_sources_table(self) -> None:
        sources_table = self.query_one("#sources", DataTable)
        sources_table.clear(columns=True)
        sources_table.add_columns("alias", "path", "origin")
        for source in self.state.sources:
            sources_table.add_row(source.name, str(source.path), source.origin)

        selected_row = self._selected_source_row_index()
        if selected_row is not None:
            sources_table.move_cursor(row=selected_row)
        elif self.state.sources:
            sources_table.move_cursor(row=0)

    def _refresh_history_table(self) -> None:
        history_table = self.query_one("#history", DataTable)
        history_table.clear(columns=True)
        history_table.add_columns("seq", "status", "rows", "sql")
        for item in self.state.query_history:
            rows = "" if item.row_count is None else str(item.row_count)
            history_table.add_row(
                str(item.sequence),
                item.status,
                rows,
                _one_line_sql(item.sql),
            )

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

    def _handle_add_source(self, raw_mapping: str | None) -> None:
        if raw_mapping is None:
            return

        try:
            mapping_source = parse_table_mapping(raw_mapping, base_dir=self.start_dir)
            self.state.add_source(
                TUISource(
                    name=mapping_source.name,
                    path=mapping_source.path,
                    origin="session",
                ),
            )
        except CSVQLError as exc:
            self._show_error(exc)
            return

        self._refresh_sources_table()
        self._set_status(f"Added source {mapping_source.name}. {self._status_message()}")

    def _handle_export_last_result(self, path_value: str | None) -> None:
        if path_value is None:
            return

        result = self.state.last_result
        if result is None:
            self._show_error(CSVQLError("Run a query before exporting."))
            return

        export_format = _export_format_for_path(path_value)
        try:
            export_path = export_last_result(
                result,
                path_value,
                export_format=export_format,
                base_dir=self.start_dir,
                force=False,
            )
        except CSVQLError as exc:
            self._show_error(exc)
            return

        self._set_status(f"Exported to {export_path}.")
        self.query_one("#results", Static).update(f"Exported to {export_path}.")

    def _selected_source_row_index(self) -> int | None:
        selected_alias = self.state.selected_alias
        if selected_alias is None:
            return None

        for index, source in enumerate(self.state.sources):
            if source.name.casefold() == selected_alias.casefold():
                return index
        return None

    def _select_source_at_row(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self.state.sources):
            return
        self.state.select_source(self.state.sources[row_index].name)


def _export_format_for_path(path_value: str) -> ExportFormat:
    suffix = Path(path_value).suffix.lower()
    if suffix == ".csv":
        return ExportFormat.csv
    if suffix == ".md":
        return ExportFormat.markdown
    return ExportFormat.json


def _one_line_sql(sql: str) -> str:
    return " ".join(sql.split())
