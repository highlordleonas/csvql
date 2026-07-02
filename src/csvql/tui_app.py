"""Minimal Textual shell for the CSVQL menu TUI."""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Static, TextArea
from textual.worker import Worker, WorkerState

from csvql.exceptions import CSVQLError
from csvql.export import ExportFormat
from csvql.models import QueryResult
from csvql.output import format_profile_result_table
from csvql.table_mapping import parse_table_mapping
from csvql.tui_editor import selected_or_current_sql
from csvql.tui_help import WORKBENCH_HELP
from csvql.tui_results import make_result_view_state, populate_result_table
from csvql.tui_state import (
    TUIQueryHistoryItem,
    TUIQueryOutcome,
    TUIQueryRunMode,
    TUIResultViewState,
    TUISessionState,
    TUISource,
    TUISourceColumn,
)
from csvql.tui_workflows import (
    build_initial_state,
    export_last_result,
    inspect_source,
    inspect_source_columns,
    profile_source,
    render_duckdb_identifier,
    run_query_for_tui,
    sample_source,
    save_derived_result_source,
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

    #results-message {
        height: 1;
    }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit_from_non_editor", "Quit", show=False),
        Binding("f1", "show_help", "Help", priority=True),
        Binding("?", "show_contextual_help", "Help", priority=True),
        Binding("f2,ctrl+down", "focus_sql", "SQL", priority=True),
        Binding(
            "f4,ctrl+enter",
            "run_selected_or_current_query",
            "Run SQL",
            key_display="F4/Ctrl+Enter",
            priority=True,
        ),
        Binding(
            "f12",
            "run_query",
            "Run All",
            key_display="F12",
            priority=True,
        ),
        Binding("f5", "focus_results", "Results", priority=True),
        Binding("f6,ctrl+up", "focus_sources", "Sources", priority=True),
        Binding("f7", "export_last_result", "Export result", priority=True),
        Binding("f8", "focus_history", "History", priority=True),
        Binding("f9", "quit", "Quit", priority=True),
        Binding("f10,ctrl+n", "new_query", "New query", priority=True),
        Binding(
            "ctrl+s,alt+s,f11",
            "save_result_as_source",
            "Save result source",
            key_display="Ctrl+S/Alt+S",
            priority=True,
        ),
        Binding("i", "inspect_source", "Inspect", show=False),
        Binding("s", "sample_source", "Sample", show=False),
        Binding("p", "profile_source", "Profile", show=False),
        Binding("a", "add_source", "Add source", show=False),
        Binding("d", "remove_source", "Remove source", show=False),
        Binding("w", "save_sources", "Save sources", show=False),
        Binding("c", "show_source_columns", "Columns", show=False),
        Binding("l", "insert_source_alias", "Insert alias", show=False),
        Binding("x", "insert_starter_select", "Starter select", show=False),
        Binding("r", "rerun_history", "Rerun", show=False),
        Binding("enter", "reopen_history", "Open query", show=False),
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
        self._active_query_sql: dict[int, str] = {}
        self._active_query_run_modes: dict[int, TUIQueryRunMode] = {}
        self._run_editor_pending = False
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
                yield DataTable(id="results", cursor_type="cell")
                yield Static("", id="results-message")
        yield Footer()

    async def on_mount(self) -> None:
        self._refresh_sources_table()
        self._refresh_history_table()
        self._set_status(self._status_message())
        self.query_one("#run-status", Static).update("Ready.")
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

    def action_focus_results(self) -> None:
        self.query_one("#results", DataTable).focus()

    def action_focus_history(self) -> None:
        self.query_one("#history", DataTable).focus()

    def action_quit_from_non_editor(self) -> None:
        if isinstance(self.focused, TextArea):
            return
        self.exit()

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

        self.state.clear_last_result()
        column_names = ", ".join(column.name for column in result.columns) or "(none)"
        self._show_output_text(f"Columns: {column_names}")
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

        self.state.clear_last_result()
        self._show_output_text(format_profile_result_table(result))
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

        self.state.clear_last_result()
        query_result = QueryResult(
            columns=result.columns,
            rows=result.rows,
            elapsed_ms=0.0,
        )
        view = make_result_view_state(query_result, source_result_sequence=0)
        populate_result_table(self.query_one("#results", DataTable), view)
        self.query_one("#results-message", Static).update(_result_message(view))
        self._set_status(f"{source.name}: {len(result.rows)} sample row(s).")

    def action_show_source_columns(self) -> None:
        self.state.clear_last_result()
        source = self.state.selected_source()
        if source is None:
            self._show_error(CSVQLError("No source selected."))
            return

        try:
            columns = inspect_source_columns(source)
        except CSVQLError as exc:
            self._show_error(exc)
            return

        self.state.set_source_columns(source.name, columns)
        if not columns:
            self._show_error(CSVQLError(f"Source '{source.name}' has no columns."))
            return

        self._show_output_text(_format_source_columns(source.name, columns))
        self._set_status(f"{source.name}: {len(columns)} columns loaded.")

    def action_insert_source_alias(self) -> None:
        source = self.state.selected_source()
        if source is None:
            self.state.clear_last_result()
            self._show_error(CSVQLError("No source selected."))
            return

        self._append_sql_text(render_duckdb_identifier(source.name))

    def action_insert_starter_select(self) -> None:
        source = self.state.selected_source()
        if source is None:
            self.state.clear_last_result()
            self._show_error(CSVQLError("No source selected."))
            return

        alias = render_duckdb_identifier(source.name)
        self._append_sql_text(f"SELECT *\nFROM {alias}\nLIMIT 10;")

    def action_run_query(self) -> None:
        self._schedule_editor_query(self._run_query_from_editor, "Preparing editor query...")

    def action_run_selected_or_current_query(self) -> None:
        self._schedule_editor_query(
            self._run_selected_or_current_query_from_editor,
            "Preparing editor query...",
        )

    def _schedule_editor_query(
        self,
        callback: Callable[[], None],
        preparing_message: str,
    ) -> None:
        if self._run_editor_pending or self.state.query_run.is_running:
            self._set_status("Query already running.")
            return

        self._run_editor_pending = True
        self.query_one("#run-status", Static).update(preparing_message)
        if not self.call_after_refresh(callback):
            self._run_editor_pending = False
            self._show_error(
                CSVQLError(
                    "Unable to schedule query run.",
                    suggestion="Try running the query again.",
                )
            )

    def _run_query_from_editor(self) -> None:
        self._run_editor_pending = False
        sql_widget = self.query_one("#sql", TextArea)
        sql = sql_widget.text.strip()
        self._start_query_run(sql, run_label="editor query", run_mode="editor")

    def _run_selected_or_current_query_from_editor(self) -> None:
        self._run_editor_pending = False
        sql_widget = self.query_one("#sql", TextArea)
        sql = selected_or_current_sql(
            sql_widget.text,
            cursor_location=sql_widget.cursor_location,
            selected_text=sql_widget.selected_text,
        )
        self._start_query_run(sql, run_label="SQL query", run_mode="sql")

    def _start_query_run(
        self,
        sql: str,
        *,
        run_label: str,
        run_mode: TUIQueryRunMode,
        rerun_source_sequence: int | None = None,
    ) -> None:
        if not sql:
            self.state.clear_last_result()
            self._show_error(
                CSVQLError(
                    "Enter SQL before running a query.",
                    suggestion="Type SQL in the editor and try again.",
                )
            )
            return

        if not self.state.sources:
            self.state.clear_last_result()
            self._show_error(
                CSVQLError(
                    "No sources loaded.",
                    suggestion="Add a source before running SQL.",
                )
            )
            return

        try:
            sequence = self.state.begin_query_run(sql)
        except RuntimeError:
            self._set_status("Query already running.")
            return

        if run_mode == "rerun" and rerun_source_sequence is not None:
            message = f"Rerunning query {rerun_source_sequence} as query {sequence}..."
        else:
            message = f"Running {run_label} {sequence}..."

        self._set_status(message)
        self.query_one("#run-status", Static).update(message)
        self._active_query_sql[sequence] = sql
        self._active_query_run_modes[sequence] = run_mode
        sources = self.state.sources
        self.run_worker(
            lambda: run_query_for_tui(sources, sql, sequence=sequence),
            name=f"query-{sequence}",
            group="query",
            thread=True,
            exit_on_error=False,
        )

    def action_export_last_result(self) -> None:
        if self.state.last_result is None:
            self._show_error(CSVQLError("Run a query before exporting."))
            return

        self.push_screen(
            _PromptInputScreen("Enter an export path.", input_id="export-path"),
            callback=self._handle_export_last_result,
        )

    def action_save_result_as_source(self) -> None:
        result = self.state.last_result
        if result is None:
            if self.state.last_result_status == "no_result":
                self._show_error(CSVQLError("The last statement did not produce a tabular result."))
                return
            self._show_error(CSVQLError("Run a query before saving a result as a source."))
            return

        self.push_screen(
            _PromptInputScreen(
                "Enter a derived source alias.",
                input_id="derived-source-alias",
            ),
            callback=self._handle_save_result_as_source,
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
        self._show_output_text(f"Saved sources to {context.config_path}.")

    def action_reopen_history(self) -> None:
        item = self._selected_history_item()
        if item is None:
            return
        sql = self.query_one("#sql", TextArea)
        sql.load_text(item.sql)
        sql.focus()

    def action_rerun_history(self) -> None:
        item = self._selected_history_item()
        if item is None:
            return
        sql = self.query_one("#sql", TextArea)
        sql.load_text(item.sql)
        self._start_query_run(
            item.sql,
            run_label="query",
            run_mode="rerun",
            rerun_source_sequence=item.sequence,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.group != "query" or not worker.is_finished:
            return
        if event.state == WorkerState.ERROR:
            self._handle_query_worker_failure(worker, worker.error)
            return
        if event.state != WorkerState.SUCCESS:
            return

        outcome = worker.result
        if isinstance(outcome, TUIQueryOutcome):
            self._handle_query_outcome(outcome)
            return

        self._handle_query_worker_failure(
            worker,
            RuntimeError(f"Unexpected worker result type: {type(outcome).__name__}"),
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "sources":
            self._select_source_at_row(event.cursor_row)
        if event.data_table.id == "history":
            self.action_reopen_history()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "sources":
            self._select_source_at_row(event.cursor_row)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        del parameters
        if isinstance(self.focused, TextArea):
            text_entry_actions = {
                "show_contextual_help",
                "quit_from_non_editor",
                "inspect_source",
                "sample_source",
                "profile_source",
                "add_source",
                "remove_source",
                "save_sources",
                "show_source_columns",
                "insert_source_alias",
                "insert_starter_select",
                "rerun_history",
                "reopen_history",
            }
            if action in text_entry_actions:
                return False
        source_actions = {
            "inspect_source",
            "sample_source",
            "profile_source",
            "add_source",
            "remove_source",
            "save_sources",
            "show_source_columns",
            "insert_source_alias",
            "insert_starter_select",
        }
        if action in source_actions and not self._is_focused("#sources"):
            return False
        history_actions = {"rerun_history", "reopen_history"}
        if action in history_actions and not self._is_focused("#history"):
            return False
        if action == "show_contextual_help" and self._is_focused("#sql"):
            return False
        return True

    def _refresh_sources_table(self) -> None:
        sources_table = self.query_one("#sources", DataTable)
        sources_table.clear(columns=True)
        sources_table.add_columns("alias", "kind", "path", "origin")
        for source in self.state.sources:
            sources_table.add_row(source.name, source.kind, str(source.path), source.origin)

        selected_row = self._selected_source_row_index()
        if selected_row is not None:
            sources_table.move_cursor(row=selected_row)
        elif self.state.sources:
            sources_table.move_cursor(row=0)

    def _refresh_history_table(self) -> None:
        history_table = self.query_one("#history", DataTable)
        previous_row = history_table.cursor_row
        history_table.clear(columns=True)
        history_table.add_columns("seq", "run", "status", "rows", "sql")
        for item in self.state.query_history:
            rows = "" if item.row_count is None else str(item.row_count)
            history_table.add_row(
                str(item.sequence),
                item.run_mode,
                item.status,
                rows,
                _one_line_sql(item.sql),
            )
        if history_table.row_count:
            target_row = previous_row if 0 <= previous_row < history_table.row_count else 0
            history_table.move_cursor(row=target_row)

    def _status_message(self) -> str:
        source_count = len(self.state.sources)
        if source_count == 0:
            return "No sources loaded. Add a source before running SQL."
        if source_count == 1:
            return "1 source loaded."
        return f"{source_count} sources loaded."

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _clear_result_grid(self) -> None:
        self.query_one("#results", DataTable).clear(columns=True)

    def _show_output_text(self, message: str) -> None:
        self._clear_result_grid()
        self.query_one("#results-message", Static).update(message)

    def _show_error(self, error: CSVQLError) -> None:
        lines = [f"Error: {error.message}"]
        if error.suggestion:
            lines.append(f"Suggestion: {error.suggestion}")
        message = "\n".join(lines)
        self._set_status(message)
        self._show_output_text(message)

    def _append_sql_text(self, text: str) -> None:
        sql = self.query_one("#sql", TextArea)
        current = sql.text
        if not current:
            sql.load_text(text)
        elif current[-1].isspace():
            sql.load_text(f"{current}{text}")
        else:
            sql.load_text(f"{current}\n{text}")
        sql.focus()

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
        self._show_output_text(f"Exported to {export_path}.")

    def _handle_save_result_as_source(self, alias: str | None) -> None:
        if alias is None:
            return

        result = self.state.last_result
        if result is None:
            self._show_error(CSVQLError("Run a query before saving a result as a source."))
            return

        try:
            source = save_derived_result_source(
                result,
                alias,
                existing_sources=self.state.sources,
                start_dir=self.start_dir,
            )
            self.state.add_source(source)
            self.state.select_source(source.name)
        except CSVQLError as exc:
            self._show_error(exc)
            return

        self._refresh_sources_table()
        message = (
            f"Saved result as derived source {source.name} at {source.path}. "
            "Use Save sources to persist the alias in .csvql.yml."
        )
        self._set_status(message)
        self.query_one("#results-message", Static).update(message)

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

    def _selected_history_item(self) -> TUIQueryHistoryItem | None:
        history_table = self.query_one("#history", DataTable)
        row_index = history_table.cursor_row
        if row_index < 0 or row_index >= len(self.state.query_history):
            return None
        return self.state.query_history[row_index]

    def _is_focused(self, selector: str) -> bool:
        try:
            return self.focused is self.query_one(selector)
        except Exception:
            return False

    def _handle_query_outcome(self, outcome: TUIQueryOutcome) -> None:
        if not self.state.is_current_query_sequence(outcome.sequence):
            return
        self._active_query_sql.pop(outcome.sequence, None)
        run_mode = self._active_query_run_modes.pop(outcome.sequence, "sql")
        if outcome.status == "success" and outcome.result is not None:
            view = make_result_view_state(
                outcome.result,
                source_result_sequence=outcome.sequence,
            )
            self.state.record_query_success(
                outcome.sequence,
                outcome.sql,
                outcome.result,
                view,
                run_mode=run_mode,
            )
            populate_result_table(self.query_one("#results", DataTable), view)
            self._refresh_history_table()
            self._set_status(
                f"{outcome.result.row_count} returned row(s) in {outcome.result.elapsed_ms:.1f} ms."
            )
            self.query_one("#run-status", Static).update("Ready.")
            self.query_one("#results-message", Static).update(_result_message(view))
            self.query_one("#sql", TextArea).focus()
            return
        if outcome.status == "no_result":
            self.state.record_query_no_result(
                outcome.sequence,
                outcome.sql,
                outcome.elapsed_ms or 0.0,
                run_mode=run_mode,
            )
            self.query_one("#results", DataTable).clear(columns=True)
            message = "Statement completed; no tabular result to display."
            self._refresh_history_table()
            self._set_status(message)
            self.query_one("#run-status", Static).update("Ready.")
            self.query_one("#results-message", Static).update(message)
            self.query_one("#sql", TextArea).focus()
            return
        self.state.record_query_error(
            outcome.sequence,
            outcome.sql,
            outcome.error_message or "Query failed.",
            run_mode=run_mode,
        )
        self.query_one("#results", DataTable).clear(columns=True)
        error = CSVQLError(outcome.error_message or "Query failed.", suggestion=outcome.suggestion)
        self._refresh_history_table()
        self.query_one("#run-status", Static).update("Ready.")
        self._show_error(error)
        self.query_one("#sql", TextArea).focus()

    def _handle_query_worker_failure(
        self,
        worker: Worker[object],
        error: BaseException | None,
    ) -> None:
        sequence = self._sequence_from_worker(worker)
        if sequence is None or not self.state.is_current_query_sequence(sequence):
            return

        sql = self._active_query_sql.pop(sequence, "<unknown>")
        run_mode = self._active_query_run_modes.pop(sequence, "sql")
        error_message = "Unexpected worker failure while running query."
        if error is not None:
            error_message = f"{error_message} {error}"

        self.state.record_query_error(sequence, sql, error_message, run_mode=run_mode)
        self._refresh_history_table()
        self.query_one("#run-status", Static).update("Ready.")
        self._clear_result_grid()
        self._show_error(
            CSVQLError(
                error_message,
                suggestion="Try running the query again.",
            )
        )
        self.query_one("#sql", TextArea).focus()

    def _sequence_from_worker(self, worker: Worker[object]) -> int | None:
        worker_name = worker.name or ""
        if not worker_name.startswith("query-"):
            return None
        try:
            return int(worker_name.removeprefix("query-"))
        except ValueError:
            return None


def _export_format_for_path(path_value: str) -> ExportFormat:
    suffix = Path(path_value).suffix.lower()
    if suffix == ".csv":
        return ExportFormat.csv
    if suffix == ".md":
        return ExportFormat.markdown
    return ExportFormat.json


def _one_line_sql(sql: str) -> str:
    return " ".join(sql.split())


def _format_source_columns(alias: str, columns: tuple[TUISourceColumn, ...]) -> str:
    lines = [f"{alias} columns"]
    lines.extend(f"  {column.name} {column.duckdb_type}" for column in columns)
    return "\n".join(lines)


def _result_message(view: TUIResultViewState) -> str:
    if view.is_truncated:
        return f"Showing first {view.preview_row_cap} of {view.total_row_count} returned rows."
    return f"Showing {view.total_row_count} returned row(s)."
