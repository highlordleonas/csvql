"""Minimal Textual shell for the CSVQL menu TUI."""

import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import ClassVar

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Static, TextArea
from textual.widgets._footer import FooterKey
from textual.worker import Worker, WorkerState

from csvql.exceptions import CSVQLError
from csvql.export import ExportFormat
from csvql.models import QueryResult
from csvql.output import format_profile_result_table
from csvql.table_mapping import parse_table_mapping
from csvql.tui_editor import all_sql_statements, selected_or_current_sql
from csvql.tui_help import WORKBENCH_HELP
from csvql.tui_results import make_result_view_state, populate_result_table
from csvql.tui_state import (
    TUIBufferResultTab,
    TUIFocusPane,
    TUIQueryHistoryItem,
    TUIQueryOutcome,
    TUIQueryRunMode,
    TUIQueryRunState,
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
    run_buffer_for_tui,
    run_query_for_tui,
    sample_source,
    save_derived_result_source,
    save_sources_to_project_catalog,
    sources_from_csv_path_text,
)

_FOOTER_KEY_ORDER = (
    "f1",
    "f2",
    "f3",
    "f4",
    "f5",
    "f6",
    "f7",
    "f8",
    "f9",
    "f10",
    "f12",
    "ctrl+s",
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

    def on_mount(self) -> None:
        self.call_after_refresh(lambda: self.scroll_home(animate=False))

    def action_cancel(self) -> None:
        self.dismiss(None)


class _OrderedFooter(Footer):
    """Footer that keeps CSVQL's key order stable across focused widgets."""

    def compose(self) -> ComposeResult:
        if not self._bindings_ready:
            return

        active_bindings = self.screen.active_bindings
        ordered_footer_keys: list[FooterKey] = []
        for key in _FOOTER_KEY_ORDER:
            if active_binding := active_bindings.get(key):
                binding = active_binding.binding
                if not binding.show:
                    continue
                ordered_footer_keys.append(
                    FooterKey(
                        binding.key,
                        self.app.get_key_display(binding),
                        binding.description,
                        binding.action,
                        disabled=not active_binding.enabled,
                        tooltip=active_binding.tooltip or binding.tooltip or binding.description,
                    ).data_bind(compact=Footer.compact)
                )
        self.styles.grid_size_columns = len(ordered_footer_keys)

        yield from ordered_footer_keys

        if self.show_command_palette and self.app.ENABLE_COMMAND_PALETTE:
            try:
                active_binding = active_bindings[self.app.COMMAND_PALETTE_BINDING]
            except KeyError:
                return
            binding = active_binding.binding
            yield FooterKey(
                binding.key,
                self.app.get_key_display(binding),
                binding.description,
                binding.action,
                classes="-command-palette",
                disabled=not active_binding.enabled,
                tooltip=binding.tooltip or binding.description,
            )


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

    #result-tabs {
        height: 1;
    }

    .pane-title {
        height: 1;
    }

    #context {
        height: 1;
    }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit_from_non_editor", "Quit", show=False),
        Binding("f1", "show_help", "Help", key_display="F1", priority=True),
        Binding("f2,ctrl+down", "focus_sql", "SQL", priority=True),
        Binding("f3,ctrl+o", "choose_csv_source", "Open CSV", key_display="F3", priority=True),
        Binding(
            "f4",
            "run_selected_or_current_query",
            "Run SQL",
            key_display="F4",
            priority=True,
        ),
        Binding("ctrl+r", "run_selected_or_current_query", "Run SQL", show=False),
        Binding("f5", "focus_results", "Results", priority=True),
        Binding("f6,ctrl+up", "focus_sources", "Sources", priority=True),
        Binding("f7", "export_last_result", "Export active result", priority=True),
        Binding("f8", "focus_history", "History", priority=True),
        Binding("f9", "quit", "Quit", priority=True),
        Binding("f10,ctrl+n", "new_query", "New query", priority=True),
        Binding("[", "select_previous_buffer_result", "Previous buffer result", show=False),
        Binding("]", "select_next_buffer_result", "Next buffer result", show=False),
        Binding(
            "f12,ctrl+b",
            "run_buffer",
            "Run Buffer",
            key_display="F12",
            priority=True,
        ),
        Binding(
            "ctrl+s,alt+s,f11",
            "save_result_as_source",
            "Save active result",
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
        self._help_screen_open = False
        self._suppress_sql_source_text_detection = False
        self._sql_source_text_revision = 0
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
                yield Static("", id="sources-title", classes="pane-title")
                yield DataTable(id="sources", cursor_type="row")
                yield Static("", id="history-title", classes="pane-title")
                yield DataTable(id="history", cursor_type="row")
            with Vertical(id="right-pane"):
                yield Static("", id="sql-title", classes="pane-title")
                yield _SourcePathTextArea(id="sql")
                yield Static("", id="run-status")
                yield Static("", id="results-title", classes="pane-title")
                yield Static("", id="result-tabs")
                yield DataTable(id="results", cursor_type="cell")
                yield Static("", id="results-message")
        yield Static("", id="context")
        yield _OrderedFooter()

    async def on_mount(self) -> None:
        self._refresh_sources_table()
        self._refresh_history_table()
        self._set_status(self._status_message())
        self._set_run_status_ready()
        self._refresh_results_display()
        self.query_one("#sql", TextArea).focus()
        self._refresh_pane_context()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        del event
        self._refresh_pane_context()

    def _set_run_status_ready(self) -> None:
        self.query_one("#run-status", Static).update("Ready.")

    def action_add_source(self) -> None:
        self._open_add_source_prompt("Enter name=path or paste CSV path(s).")

    def _open_add_source_prompt(self, prompt: str) -> None:
        self.push_screen(
            _PromptInputScreen(
                prompt,
                input_id="mapping-input",
            ),
            callback=self._handle_add_source,
        )

    def action_show_help(self) -> None:
        self._show_help_once()

    def _show_help_once(self) -> None:
        if self._help_screen_open or isinstance(self.screen, (_HelpScreen, _PromptInputScreen)):
            return
        self._help_screen_open = True
        self.push_screen(_HelpScreen(), callback=lambda _: self._mark_help_closed())

    def _mark_help_closed(self) -> None:
        self._help_screen_open = False

    def action_choose_csv_source(self) -> None:
        try:
            path_values = _choose_csv_paths_with_native_picker()
            sources = self._sources_from_csv_path_values(path_values)
        except CSVQLError as exc:
            fallback_message = exc.message
            if exc.suggestion:
                fallback_message = f"{fallback_message} {exc.suggestion}"
            self._set_status(fallback_message)
            self._open_add_source_prompt("Paste CSV path(s) or enter name=path.")
            return

        if not sources:
            self._set_status("No CSV selected. " + self._status_message())
            return

        self._add_session_sources(sources)
        self.query_one("#sql", TextArea).focus()

    def action_focus_sources(self) -> None:
        self.query_one("#sources", DataTable).focus()
        self._refresh_pane_context()

    def action_focus_sql(self) -> None:
        self.query_one("#sql", TextArea).focus()
        self._refresh_pane_context()

    def action_focus_results(self) -> None:
        self.query_one("#results", DataTable).focus()
        self._refresh_pane_context()

    def action_focus_history(self) -> None:
        self.query_one("#history", DataTable).focus()
        self._refresh_pane_context()
        self._show_selected_history_result()

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
        self.action_run_buffer()

    def action_run_buffer(self) -> None:
        self._schedule_editor_query(self._run_buffer_from_editor, "Preparing buffer SQL...")

    def action_run_selected_or_current_query(self) -> None:
        self._schedule_editor_query(
            self._run_selected_or_current_query_from_editor,
            "Preparing current SQL...",
        )

    def _schedule_editor_query(
        self,
        callback: Callable[[], None],
        preparing_message: str,
    ) -> None:
        if self._consume_sql_editor_csv_path_text(self.query_one("#sql", TextArea)):
            return

        if self._run_editor_pending or self.state.query_run.is_running:
            self._show_rejected_run(
                CSVQLError(
                    "Query already running.",
                    suggestion="Wait for the current query to finish.",
                ),
                reset_run_status=False,
                simple_message_without_previous=True,
            )
            return

        self._run_editor_pending = True
        self.query_one("#run-status", Static).update(preparing_message)
        if not self.call_after_refresh(callback):
            self._run_editor_pending = False
            self._show_rejected_run(
                CSVQLError(
                    "Unable to schedule query run.",
                    suggestion="Try running the query again.",
                )
            )

    def _run_query_from_editor(self) -> None:
        self.action_run_buffer()

    def _run_buffer_from_editor(self) -> None:
        self._run_editor_pending = False
        sql_widget = self.query_one("#sql", TextArea)
        statements = all_sql_statements(sql_widget.text)
        if not statements:
            self._show_rejected_run(
                CSVQLError(
                    "Enter SQL before running a query.",
                    suggestion="Type SQL in the editor and try again.",
                )
            )
            return

        if not self.state.sources:
            self._show_rejected_run(
                CSVQLError(
                    "No sources loaded.",
                    suggestion="Add a source before running SQL.",
                )
            )
            return

        try:
            sequences = self.state.begin_query_batch(statements)
        except RuntimeError:
            self._show_rejected_run(
                CSVQLError(
                    "Query already running.",
                    suggestion="Wait for the current query to finish.",
                ),
                reset_run_status=False,
                simple_message_without_previous=True,
            )
            return

        message = _run_start_message(
            sequence=sequences[0],
            run_label="buffer SQL",
            run_mode="buffer",
            rerun_source_sequence=None,
        )
        self._set_status(message)
        self.query_one("#run-status", Static).update(message)
        self._active_query_sql[sequences[0]] = "\n".join(statements)
        self._active_query_run_modes[sequences[0]] = "buffer"
        sources = self.state.sources
        self.run_worker(
            lambda: run_buffer_for_tui(sources, statements, sequences=sequences),
            name=f"buffer-{sequences[0]}-{sequences[-1]}",
            group="query",
            thread=True,
            exit_on_error=False,
        )

    def _run_selected_or_current_query_from_editor(self) -> None:
        self._run_editor_pending = False
        sql_widget = self.query_one("#sql", TextArea)
        sql = selected_or_current_sql(
            sql_widget.text,
            cursor_location=sql_widget.cursor_location,
            selected_text=sql_widget.selected_text,
        )
        self._start_query_run(sql, run_label="current SQL", run_mode="current")

    def _start_query_run(
        self,
        sql: str,
        *,
        run_label: str,
        run_mode: TUIQueryRunMode,
        rerun_source_sequence: int | None = None,
    ) -> None:
        if not sql:
            self._show_rejected_run(
                CSVQLError(
                    "Enter SQL before running a query.",
                    suggestion="Type SQL in the editor and try again.",
                )
            )
            return

        if not self.state.sources:
            self._show_rejected_run(
                CSVQLError(
                    "No sources loaded.",
                    suggestion="Add a source before running SQL.",
                )
            )
            return

        try:
            sequence = self.state.begin_query_run(sql)
        except RuntimeError:
            self._show_rejected_run(
                CSVQLError(
                    "Query already running.",
                    suggestion="Wait for the current query to finish.",
                ),
                reset_run_status=False,
                simple_message_without_previous=True,
            )
            return

        message = _run_start_message(
            sequence=sequence,
            run_label=run_label,
            run_mode=run_mode,
            rerun_source_sequence=rerun_source_sequence,
        )

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
        if self._is_focused("#history"):
            self._show_selected_history_result()
        if self.state.last_result is None:
            self._show_error(CSVQLError("Run a query before exporting."))
            return

        self.push_screen(
            _PromptInputScreen("Enter an export path.", input_id="export-path"),
            callback=self._handle_export_last_result,
        )

    def action_save_result_as_source(self) -> None:
        if self._is_focused("#history"):
            self._show_selected_history_result()
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

    def action_select_previous_buffer_result(self) -> None:
        self._select_relative_buffer_result(-1)

    def action_select_next_buffer_result(self) -> None:
        self._select_relative_buffer_result(1)

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
        if isinstance(outcome, tuple) and len(outcome) == 0:
            self._handle_empty_buffer_outcome(worker)
            return
        if isinstance(outcome, tuple) and all(
            isinstance(item, TUIQueryOutcome) for item in outcome
        ):
            self._handle_buffer_outcomes(outcome)
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
        if event.data_table.id == "history" and self._is_focused("#history"):
            self._show_history_result_at_row(event.cursor_row)

    def on_focus(self, event: events.Focus) -> None:
        self._refresh_pane_context()
        if getattr(event.control, "id", None) == "history":
            self._show_selected_history_result()

    def on_paste(self, event: events.Paste) -> None:
        if isinstance(self.focused, Input):
            return
        if self._handle_pasted_csv_sources(event.text):
            event.stop()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "sql" or self._suppress_sql_source_text_detection:
            return
        self._sql_source_text_revision += 1
        revision = self._sql_source_text_revision
        self.set_timer(
            0.05,
            lambda: self._consume_sql_editor_csv_path_text(
                event.text_area,
                revision=revision,
            ),
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        del parameters
        if isinstance(self.focused, TextArea):
            text_entry_actions = {
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
                "select_previous_buffer_result",
                "select_next_buffer_result",
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

    def _refresh_pane_context(self) -> None:
        if isinstance(self.screen, (_HelpScreen, _PromptInputScreen)):
            return
        try:
            active_pane = self._active_focus_pane()
            self.state.active_pane = active_pane
            self.query_one("#sources-title", Static).update(
                _pane_title("Sources", active_pane == "sources")
            )
            self.query_one("#history-title", Static).update(
                _pane_title("History", active_pane == "history")
            )
            self.query_one("#sql-title", Static).update(
                _pane_title("SQL editor", active_pane == "editor")
            )
            self._refresh_results_title(is_active=active_pane == "results")
            self.query_one("#context", Static).update(_pane_context(active_pane))
        except NoMatches:
            return

    def _active_focus_pane(self) -> TUIFocusPane:
        focused = self.focused
        if focused is self.query_one("#sources", DataTable):
            return "sources"
        if focused is self.query_one("#history", DataTable):
            return "history"
        if focused is self.query_one("#results", DataTable):
            return "results"
        return "editor"

    def _refresh_history_table(self) -> None:
        history_table = self.query_one("#history", DataTable)
        selected_sequence = self._selected_history_sequence()
        history_table.clear(columns=True)
        history_table.add_columns("seq", "run", "status", "rows", "sql")
        target_row = 0
        for item in self.state.query_history:
            row_index = history_table.row_count
            rows = "" if item.row_count is None else str(item.row_count)
            history_table.add_row(
                str(item.sequence),
                _run_mode_display(item.run_mode),
                item.status,
                rows,
                _one_line_sql(item.sql),
            )
            if selected_sequence == item.sequence:
                target_row = row_index
        if history_table.row_count:
            history_table.move_cursor(row=target_row)

    def _refresh_history_table_selecting(self, sequence: int) -> None:
        history_table = self.query_one("#history", DataTable)
        history_table.clear(columns=True)
        history_table.add_columns("seq", "run", "status", "rows", "sql")
        target_row = 0
        for item in self.state.query_history:
            row_index = history_table.row_count
            rows = "" if item.row_count is None else str(item.row_count)
            history_table.add_row(
                str(item.sequence),
                _run_mode_display(item.run_mode),
                item.status,
                rows,
                _one_line_sql(item.sql),
            )
            if item.sequence == sequence:
                target_row = row_index
        if history_table.row_count:
            history_table.move_cursor(row=target_row)

    def _status_message(self) -> str:
        source_count = len(self.state.sources)
        if source_count == 0:
            return "No sources loaded. Press F3 to choose a CSV or add a source before running SQL."
        if source_count == 1:
            return "1 source loaded."
        return f"{source_count} sources loaded."

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _clear_result_grid(self) -> None:
        self.query_one("#results", DataTable).clear(columns=True)

    def _refresh_results_title(self, *, is_active: bool | None = None) -> None:
        label = self.state.active_result.label
        if self.state.active_result.kind == "none":
            label = "Results"
        if is_active is None:
            is_active = self._is_focused("#results")
        self.query_one("#results-title", Static).update(_pane_title(label, is_active))

    def _result_tabs_text(self) -> str:
        tabs = self.state.buffer_result_tabs
        if not tabs:
            return "Buffer results: none"

        active_result = self.state.active_result
        entries: list[str] = []
        for tab in tabs:
            label = f"{tab.index}: {tab.label}"
            if (
                active_result.kind == "buffer"
                and active_result.sequence == tab.sequence
                and active_result.buffer_result_index == tab.index
            ):
                label = f"[{label}]"
            entries.append(label)
        return "Buffer results: " + " | ".join(entries)

    def _refresh_result_tabs(self) -> None:
        self.query_one("#result-tabs", Static).update(self._result_tabs_text())

    def _refresh_results_display(self) -> None:
        view = self.state.result_view
        if view.columns:
            populate_result_table(self.query_one("#results", DataTable), view)
        else:
            self._clear_result_grid()
        self._refresh_results_title()
        self._refresh_result_tabs()

    def _show_output_text(self, message: str) -> None:
        self._clear_result_grid()
        self.query_one("#results-message", Static).update(message)

    def _show_error(self, error: CSVQLError) -> None:
        message = _error_message(error)
        self._set_status(message)
        self._show_output_text(message)

    def _show_rejected_run(
        self,
        error: CSVQLError,
        *,
        reset_run_status: bool = True,
        simple_message_without_previous: bool = False,
    ) -> None:
        if reset_run_status:
            self._set_run_status_ready()

        rejected_error = error
        if self.state.last_result is not None:
            rejected_error = _with_previous_result_suggestion(error)

        if simple_message_without_previous and self.state.last_result is None:
            message = rejected_error.message
        else:
            message = _error_message(rejected_error)

        self._set_status(message)
        self.query_one("#results-message", Static).update(message)
        self.query_one("#sql", TextArea).focus()

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
            sources: tuple[TUISource, ...]
            if "=" in raw_mapping:
                mapping_source = parse_table_mapping(raw_mapping, base_dir=self.start_dir)
                sources = (
                    TUISource(
                        name=mapping_source.name,
                        path=mapping_source.path,
                        origin="session",
                    ),
                )
            else:
                sources = sources_from_csv_path_text(
                    raw_mapping,
                    existing_sources=self.state.sources,
                    start_dir=self.start_dir,
                )
                if not sources:
                    raise CSVQLError(
                        "Invalid source input.",
                        suggestion="Use name=path or paste one or more .csv file paths.",
                    )
            self._add_session_sources(sources)
        except CSVQLError as exc:
            self._show_error(exc)
            return

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
        return self._history_item_at_row(history_table.cursor_row)

    def _history_item_at_row(self, row_index: int) -> TUIQueryHistoryItem | None:
        if row_index < 0 or row_index >= len(self.state.query_history):
            return None
        return self.state.query_history[row_index]

    def _selected_history_sequence(self) -> int | None:
        item = self._selected_history_item()
        if item is None:
            return None
        return item.sequence

    def _show_selected_history_result(self) -> None:
        item = self._selected_history_item()
        if item is None:
            return
        self._show_history_item_result(item)

    def _show_history_result_at_row(self, row_index: int) -> None:
        item = self._history_item_at_row(row_index)
        if item is None:
            return
        self._show_history_item_result(item)

    def _show_history_item_result(self, item: TUIQueryHistoryItem) -> None:
        if item.status == "success":
            if not self.state.restore_query_result(item.sequence):
                return
            view = self.state.result_view
            populate_result_table(self.query_one("#results", DataTable), view)
            self._refresh_results_title()
            self._refresh_result_tabs()
            self.query_one("#results-message", Static).update(
                f"History query {item.sequence}. {_result_message(view)}"
            )
            self._set_status(f"Showing query {item.sequence} result from History.")
            return

        self.state.clear_last_result()
        self._clear_result_grid()
        self._refresh_results_title()
        self._refresh_result_tabs()
        if item.status == "no_result":
            self.state.last_result_status = "no_result"
            message = f"History query {item.sequence} completed with no tabular result."
        else:
            self.state.last_result_status = "error"
            detail = item.error_message or "Query failed."
            message = f"History query {item.sequence} failed. {detail}"
        self.query_one("#results-message", Static).update(message)
        self._set_status(message)

    def _is_focused(self, selector: str) -> bool:
        try:
            return self.focused is self.query_one(selector)
        except Exception:
            return False

    def _select_relative_buffer_result(self, offset: int) -> None:
        tabs = self.state.buffer_result_tabs
        if not tabs:
            return

        active_index = self._active_buffer_tab_index()
        if active_index is None:
            target_index = 0 if offset > 0 else len(tabs) - 1
        else:
            target_index = (active_index + offset) % len(tabs)
        self._show_buffer_result_at_tab(tabs[target_index])

    def _active_buffer_tab_index(self) -> int | None:
        active_result = self.state.active_result
        if active_result.kind != "buffer" or active_result.buffer_result_index is None:
            return None

        for index, tab in enumerate(self.state.buffer_result_tabs):
            if (
                tab.sequence == active_result.sequence
                and tab.index == active_result.buffer_result_index
            ):
                return index
        return None

    def _show_buffer_result_at_tab(self, tab: TUIBufferResultTab) -> None:
        if not self.state.select_buffer_result(tab.sequence):
            return

        view = self.state.result_view
        populate_result_table(self.query_one("#results", DataTable), view)
        self._refresh_results_title()
        self._refresh_result_tabs()
        self.query_one("#results-message", Static).update(
            f"Buffer result {tab.sequence}.{tab.index}. {_result_message(view)}"
        )
        self._set_status(f"Showing buffer result {tab.sequence}.{tab.index}.")

    def _handle_empty_buffer_outcome(self, worker: Worker[object]) -> None:
        sequence = self._sequence_from_worker(worker)
        if sequence is None or not self.state.is_current_query_sequence(sequence):
            return

        self._active_query_sql.pop(sequence, None)
        self._active_query_run_modes.pop(sequence, None)
        self.state.clear_last_result()
        self.state.query_run = TUIQueryRunState()
        self.state.set_buffer_result_tabs(tuple(), selected_sequence=None)
        self._clear_result_grid()
        self._refresh_results_title()
        self._refresh_result_tabs()
        message = "Run Buffer returned no tabular result."
        self._set_status(message)
        self.query_one("#results-message", Static).update(message)
        self.query_one("#run-status", Static).update("Ready.")
        self.query_one("#sql", TextArea).focus()

    def _handle_buffer_outcomes(self, outcomes: tuple[TUIQueryOutcome, ...]) -> None:
        batch_sequence = outcomes[0].sequence if outcomes else self.state.query_run.sequence
        if batch_sequence is not None:
            self._active_query_sql.pop(batch_sequence, None)
            self._active_query_run_modes.pop(batch_sequence, None)

        buffer_tabs: list[TUIBufferResultTab] = []
        latest_tabular_sequence: int | None = None
        latest_outcome: TUIQueryOutcome | None = None
        next_buffer_index = 0

        for outcome in outcomes:
            latest_outcome = outcome
            if outcome.status == "success" and outcome.result is not None:
                next_buffer_index += 1
                view = make_result_view_state(
                    outcome.result,
                    source_result_sequence=outcome.sequence,
                )
                self.state.record_query_success(
                    outcome.sequence,
                    outcome.sql,
                    outcome.result,
                    view,
                    run_mode="buffer",
                    buffer_result_index=next_buffer_index,
                )
                buffer_tabs.append(
                    TUIBufferResultTab(
                        sequence=outcome.sequence,
                        index=next_buffer_index,
                        label=f"query {next_buffer_index}",
                    )
                )
                latest_tabular_sequence = outcome.sequence
                continue

            if outcome.status == "no_result":
                self.state.record_query_no_result(
                    outcome.sequence,
                    outcome.sql,
                    outcome.elapsed_ms or 0.0,
                    run_mode="buffer",
                )
                continue

            self.state.record_query_error(
                outcome.sequence,
                outcome.sql,
                outcome.error_message or "Query failed.",
                run_mode="buffer",
            )
            break

        if latest_tabular_sequence is None:
            self.state.set_buffer_result_tabs(tuple(), selected_sequence=None)
            self._clear_result_grid()
            self._refresh_results_title()
            self._refresh_result_tabs()
            if latest_outcome is not None:
                self._refresh_history_table_selecting(latest_outcome.sequence)
            if latest_outcome is None:
                message = "Statement completed; no tabular result to display."
            elif latest_outcome.status == "error":
                message = latest_outcome.error_message or "Query failed."
            else:
                message = "Statement completed; no tabular result to display."
            self._set_status(message)
            self.query_one("#results-message", Static).update(message)
            self.query_one("#run-status", Static).update("Ready.")
            self.query_one("#sql", TextArea).focus()
            return

        self.state.set_buffer_result_tabs(
            tuple(buffer_tabs),
            selected_sequence=latest_tabular_sequence,
        )
        self._refresh_results_display()
        self._refresh_history_table_selecting(
            latest_outcome.sequence if latest_outcome is not None else latest_tabular_sequence
        )
        self.query_one("#run-status", Static).update("Ready.")
        if (
            latest_outcome is not None
            and latest_outcome.status == "success"
            and latest_outcome.result is not None
        ):
            completion_message = (
                f"{latest_outcome.result.row_count} returned row(s) "
                f"in {latest_outcome.result.elapsed_ms:.1f} ms."
            )
            self._set_status(completion_message)
            self.query_one("#results-message", Static).update(
                _result_message(self.state.result_view)
            )
        elif latest_outcome is not None and latest_outcome.status == "no_result":
            message = "Statement completed; no tabular result to display."
            self._set_status(message)
            self.query_one("#results-message", Static).update(message)
        elif latest_outcome is not None and latest_outcome.status == "error":
            error_message = latest_outcome.error_message or "Query failed."
            self._set_status(error_message)
            self.query_one("#results-message", Static).update(error_message)
        self.query_one("#sql", TextArea).focus()

    def _handle_query_outcome(self, outcome: TUIQueryOutcome) -> None:
        if not self.state.is_current_query_sequence(outcome.sequence):
            return
        self._active_query_sql.pop(outcome.sequence, None)
        run_mode = self._active_query_run_modes.pop(outcome.sequence, "current")
        if run_mode == "buffer":
            self._handle_buffer_outcomes((outcome,))
            return
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
            self._refresh_results_title()
            self._refresh_result_tabs()
            self._refresh_history_table_selecting(outcome.sequence)
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
            self._refresh_results_title()
            self._refresh_result_tabs()
            message = "Statement completed; no tabular result to display."
            self._refresh_history_table_selecting(outcome.sequence)
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
        self._refresh_results_title()
        self._refresh_result_tabs()
        error = CSVQLError(outcome.error_message or "Query failed.", suggestion=outcome.suggestion)
        self._refresh_history_table_selecting(outcome.sequence)
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
        run_mode = self._active_query_run_modes.pop(sequence, "current")
        error_message = "Unexpected worker failure while running query."
        if error is not None:
            error_message = f"{error_message} {error}"

        self.state.record_query_error(sequence, sql, error_message, run_mode=run_mode)
        self._refresh_history_table_selecting(sequence)
        self.query_one("#run-status", Static).update("Ready.")
        self._clear_result_grid()
        self._refresh_results_title()
        self._refresh_result_tabs()
        self._show_error(
            CSVQLError(
                error_message,
                suggestion="Try running the query again.",
            )
        )
        self.query_one("#sql", TextArea).focus()

    def _sequence_from_worker(self, worker: Worker[object]) -> int | None:
        worker_name = worker.name or ""
        if worker_name.startswith("query-"):
            try:
                return int(worker_name.removeprefix("query-"))
            except ValueError:
                return None
        if worker_name.startswith("buffer-"):
            try:
                return int(worker_name.removeprefix("buffer-").split("-", 1)[0])
            except ValueError:
                return None
        try:
            return int(worker_name)
        except ValueError:
            return None

    def _handle_pasted_csv_sources(self, raw_text: str) -> bool:
        try:
            sources = self._sources_from_csv_path_values((raw_text,))
        except CSVQLError as exc:
            self._show_error(exc)
            return True

        if not sources:
            return False

        self._add_session_sources(sources)
        return True

    def _sources_from_csv_path_values(self, path_values: Sequence[str]) -> tuple[TUISource, ...]:
        raw_text = "\n".join(path_values)
        return sources_from_csv_path_text(
            raw_text,
            existing_sources=self.state.sources,
            start_dir=self.start_dir,
        )

    def _consume_sql_editor_csv_path_text(
        self,
        sql_widget: TextArea,
        *,
        revision: int | None = None,
    ) -> bool:
        if revision is not None and revision != self._sql_source_text_revision:
            return False

        raw_text = sql_widget.text
        if not raw_text.strip():
            return False

        sources, cleaned_text = self._sources_from_embedded_editor_csv_paths(raw_text)
        if sources:
            return self._add_editor_path_sources(
                sources,
                sql_widget=sql_widget,
                cleaned_text=cleaned_text,
            )

        try:
            sources = sources_from_csv_path_text(
                raw_text,
                existing_sources=self.state.sources,
                start_dir=self.start_dir,
            )
        except CSVQLError as exc:
            self._show_error(exc)
            return True

        if sources:
            return self._add_editor_path_sources(
                sources,
                sql_widget=sql_widget,
                cleaned_text="",
            )

        return False

    def _sources_from_embedded_editor_csv_paths(
        self,
        raw_text: str,
    ) -> tuple[tuple[TUISource, ...], str]:
        fragments = _editor_csv_path_fragments(raw_text)
        if not fragments:
            return (), raw_text

        reserved_sources = list(self.state.sources)
        sources: list[TUISource] = []
        consumed_spans: list[tuple[int, int]] = []
        for start_index, end_index, candidate_text in fragments:
            try:
                candidate_sources = sources_from_csv_path_text(
                    candidate_text,
                    existing_sources=tuple(reserved_sources),
                    start_dir=self.start_dir,
                )
            except CSVQLError:
                continue

            if not candidate_sources:
                continue

            sources.extend(candidate_sources)
            reserved_sources.extend(candidate_sources)
            consumed_spans.append((start_index, end_index))

        if not sources:
            return (), raw_text

        return tuple(sources), _remove_text_spans(raw_text, consumed_spans)

    def _remove_pasted_text_from_sql_editor(
        self,
        *,
        before_text: str,
        expected_single_paste_text: str,
        expected_double_paste_text: str,
    ) -> None:
        sql = self.query_one("#sql", TextArea)
        current_text = sql.text
        if current_text not in {expected_single_paste_text, expected_double_paste_text}:
            return
        sql.load_text(before_text)
        sql.focus()

    def _remove_pasted_source_text_from_sql_editor(
        self,
        *,
        before_text: str,
        expected_single_paste_text: str,
        expected_double_paste_text: str,
    ) -> None:
        try:
            self._remove_pasted_text_from_sql_editor(
                before_text=before_text,
                expected_single_paste_text=expected_single_paste_text,
                expected_double_paste_text=expected_double_paste_text,
            )
        finally:
            self._suppress_sql_source_text_detection = False

    def _normalize_pasted_text_in_sql_editor(
        self,
        *,
        expected_single_paste_text: str,
        expected_double_paste_text: str,
    ) -> None:
        sql = self.query_one("#sql", TextArea)
        if sql.text not in {expected_single_paste_text, expected_double_paste_text}:
            return
        sql.load_text(expected_single_paste_text)
        sql.focus()

    def _add_session_sources(self, sources: Sequence[TUISource]) -> None:
        for source in sources:
            self.state.add_source(source)
        if sources:
            self.state.select_source(sources[0].name)
        self._refresh_sources_table()
        self._set_status(f"{_added_sources_message(sources)} {self._status_message()}")

    def _add_editor_path_sources(
        self,
        sources: Sequence[TUISource],
        *,
        sql_widget: TextArea,
        cleaned_text: str,
    ) -> bool:
        self._suppress_sql_source_text_detection = True
        try:
            sql_widget.load_text(cleaned_text)
        finally:
            self._suppress_sql_source_text_detection = False
        self._add_session_sources(sources)
        sql_widget.focus()
        return True


class _SourcePathTextArea(TextArea):
    """SQL editor that turns pasted CSV path payloads into sources."""

    async def _on_paste(self, event: events.Paste) -> None:
        if not isinstance(self.app, CSVQLMenuApp):
            return

        before_text, expected_single_paste_text, expected_double_paste_text = (
            self._paste_text_expectations(event.text)
        )
        if self.app._handle_pasted_csv_sources(event.text):
            self.app._suppress_sql_source_text_detection = True
            event.stop()
            if not self.call_after_refresh(
                lambda: self.app._remove_pasted_source_text_from_sql_editor(
                    before_text=before_text,
                    expected_single_paste_text=expected_single_paste_text,
                    expected_double_paste_text=expected_double_paste_text,
                )
            ):
                self.app._suppress_sql_source_text_detection = False
            self.focus()
            return

        if not self.read_only:
            if result := self._replace_via_keyboard(event.text, *self.selection):
                self.move_cursor(result.end_location)
                self.focus()
        event.stop()
        self.call_after_refresh(
            lambda: self.app._normalize_pasted_text_in_sql_editor(
                expected_single_paste_text=expected_single_paste_text,
                expected_double_paste_text=expected_double_paste_text,
            )
        )

    def _paste_text_expectations(self, pasted_text: str) -> tuple[str, str, str]:
        before_text = self.text
        start_index = _text_index_from_location(before_text, self.selection.start)
        end_index = _text_index_from_location(before_text, self.selection.end)
        if start_index > end_index:
            start_index, end_index = end_index, start_index

        before_selection = before_text[:start_index]
        after_selection = before_text[end_index:]
        expected_single_paste_text = f"{before_selection}{pasted_text}{after_selection}"
        expected_double_paste_text = (
            f"{before_selection}{pasted_text}{pasted_text}{after_selection}"
        )
        return before_text, expected_single_paste_text, expected_double_paste_text


def _export_format_for_path(path_value: str) -> ExportFormat:
    suffix = Path(path_value).suffix.lower()
    if suffix == ".csv":
        return ExportFormat.csv
    if suffix == ".md":
        return ExportFormat.markdown
    return ExportFormat.json


_PREVIOUS_RESULT_AVAILABLE = "Previous result is still available."


def _error_message(error: CSVQLError) -> str:
    lines = [f"Error: {error.message}"]
    if error.suggestion:
        lines.append(f"Suggestion: {error.suggestion}")
    return "\n".join(lines)


def _with_previous_result_suggestion(error: CSVQLError) -> CSVQLError:
    if error.suggestion:
        suggestion = f"{error.suggestion} {_PREVIOUS_RESULT_AVAILABLE}"
    else:
        suggestion = _PREVIOUS_RESULT_AVAILABLE
    return CSVQLError(error.message, suggestion=suggestion)


def _one_line_sql(sql: str) -> str:
    return " ".join(sql.split())


def _run_mode_display(run_mode: TUIQueryRunMode) -> str:
    return run_mode


def _run_start_message(
    *,
    sequence: int,
    run_label: str,
    run_mode: TUIQueryRunMode,
    rerun_source_sequence: int | None,
) -> str:
    if run_mode == "rerun" and rerun_source_sequence is not None:
        return f"Rerunning history query {rerun_source_sequence} as query {sequence}..."
    if run_mode == "current":
        return f"Running current SQL as query {sequence}..."
    if run_mode == "buffer":
        if run_label.startswith("statement "):
            return f"Running buffer {run_label} as query {sequence}..."
        return f"Running buffer SQL as query {sequence}..."
    if run_label.startswith("statement "):
        return f"Running all SQL {run_label} as query {sequence}..."
    return f"Running all SQL as query {sequence}..."


def _pane_title(label: str, is_active: bool) -> str:
    prefix = ">" if is_active else " "
    return f"{prefix} {label}"


def _pane_context(active_pane: TUIFocusPane) -> str:
    if active_pane == "sources":
        return (
            "Sources: F3 picker | a add source | i inspect | s sample | p profile | "
            "c columns | l alias | x starter | d remove | w save"
        )
    if active_pane == "history":
        return (
            "History: highlight recall | Enter reopen | r rerun | F7 export active result | "
            "Ctrl+S/Alt+S save active result"
        )
    if active_pane == "results":
        return (
            "Results: arrow keys move | F7 export active result | "
            "Ctrl+S/Alt+S save active result | "
            "F8 history"
        )
    return (
        "SQL editor: type SQL | F4/Ctrl+R current | F12/Ctrl+B buffer | F10 new query | "
        "paste CSV path to add source"
    )


def _text_index_from_location(text: str, location: tuple[int, int]) -> int:
    row, column = location
    if row < 0:
        return 0

    lines = text.splitlines(keepends=True)
    if not lines or row >= len(lines):
        return len(text)

    index = sum(len(line) for line in lines[:row])
    line_text = lines[row].removesuffix("\n").removesuffix("\r")
    return index + min(max(column, 0), len(line_text))


_QUOTED_CSV_PATH_FRAGMENT = re.compile(
    r"(?P<quote>['\"])(?P<path>(?:file://)?(?:~|/).*?\.csv)(?P=quote)",
    flags=re.IGNORECASE,
)
_UNQUOTED_CSV_PATH_FRAGMENT = re.compile(
    r"(?P<path>(?:file://)?(?:~|/)(?:\\.|[^\s'\"<>|])+?\.csv)",
    flags=re.IGNORECASE,
)


def _editor_csv_path_fragments(text: str) -> tuple[tuple[int, int, str], ...]:
    fragments: list[tuple[int, int, str]] = []
    occupied_spans: list[tuple[int, int]] = []

    for match in _QUOTED_CSV_PATH_FRAGMENT.finditer(text):
        start_index, end_index = match.span()
        if not _has_editor_path_text_boundary(text, start_index, end_index):
            continue
        fragments.append((start_index, end_index, match.group()))
        occupied_spans.append((start_index, end_index))

    for match in _UNQUOTED_CSV_PATH_FRAGMENT.finditer(text):
        start_index, end_index = match.span()
        if any(
            start_index < occupied_end and end_index > occupied_start
            for occupied_start, occupied_end in occupied_spans
        ):
            continue
        if not _has_editor_path_text_boundary(text, start_index, end_index):
            continue
        fragments.append((start_index, end_index, match.group("path")))

    return tuple(sorted(fragments, key=lambda fragment: fragment[0]))


def _has_editor_path_text_boundary(text: str, start_index: int, end_index: int) -> bool:
    before = text[start_index - 1] if start_index > 0 else ""
    after = text[end_index] if end_index < len(text) else ""
    before_ok = not before or before.isspace() or before in ";,"
    after_ok = not after or after.isspace() or after in ";,"
    return before_ok and after_ok


def _remove_text_spans(text: str, spans: Sequence[tuple[int, int]]) -> str:
    if not spans:
        return text

    chunks: list[str] = []
    cursor = 0
    for start_index, end_index in sorted(spans):
        chunks.append(text[cursor:start_index])
        cursor = end_index
    chunks.append(text[cursor:])
    return "".join(chunks).strip()


def _choose_csv_paths_with_native_picker() -> tuple[str, ...]:
    """Return CSV candidate paths selected through the local macOS file picker."""

    if sys.platform != "darwin":
        raise CSVQLError(
            "Native CSV picker is only available on macOS.",
            suggestion="Use Add source and paste a CSV path instead.",
        )

    script_lines = [
        'set chosenFiles to choose file with prompt "Choose CSV file(s) to add to CSVQL." '
        "with multiple selections allowed",
        "set outputPaths to {}",
        "repeat with chosenFile in chosenFiles",
        "set end of outputPaths to POSIX path of chosenFile",
        "end repeat",
        "set AppleScript's text item delimiters to linefeed",
        "return outputPaths as text",
    ]

    try:
        result = subprocess.run(
            ["osascript", *(argument for line in script_lines for argument in ("-e", line))],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise CSVQLError(
            "Native CSV picker is unavailable.",
            suggestion="Use Add source and paste a CSV path instead.",
        ) from exc

    if result.returncode != 0:
        error_text = result.stderr.strip()
        if "User canceled" in error_text:
            return ()
        raise CSVQLError(
            "Native CSV picker failed.",
            suggestion="Use Add source and paste a CSV path instead.",
        )

    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _format_source_columns(alias: str, columns: tuple[TUISourceColumn, ...]) -> str:
    lines = [f"{alias} columns"]
    lines.extend(f"  {column.name} {column.duckdb_type}" for column in columns)
    return "\n".join(lines)


def _result_message(view: TUIResultViewState) -> str:
    if view.is_truncated:
        return f"Showing first {view.preview_row_cap} of {view.total_row_count} returned rows."
    return f"Showing {view.total_row_count} returned row(s)."


def _added_sources_message(sources: Sequence[TUISource]) -> str:
    if len(sources) == 1:
        return f"Added source {sources[0].name}."
    source_names = ", ".join(source.name for source in sources)
    return f"Added {len(sources)} sources: {source_names}."
