"""Minimal Textual shell for the CSVQL menu TUI."""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import ClassVar

from textual import events
from textual.app import App, ComposeResult, ScreenStackError
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import DataTable, Footer, Input, Static, TextArea
from textual.widgets._footer import FooterKey
from textual.worker import Worker, WorkerState

from csvql.bounded_result import BoundedQueryResult, PreviewPolicy
from csvql.exceptions import CSVQLError
from csvql.export import ExportFormat
from csvql.models import InspectResult, ProfileResult, QueryResult, SampleResult
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.source import SourceCapability
from csvql.table_mapping import parse_table_mapping
from csvql.terminal_text import literal_terminal_text, terminal_safe_text
from csvql.tui_editor import all_sql_statements, selected_or_current_sql
from csvql.tui_help import WORKBENCH_HELP
from csvql.tui_native_picker import (
    choose_csv_paths_with_native_picker as _choose_csv_paths_with_native_picker,
)
from csvql.tui_query_runner import (
    TUICancelledBeforePreviewEvent,
    TUICompleteEvent,
    TUIFailedBeforePreviewEvent,
    TUINoResultEvent,
    TUIPreservationProgressEvent,
    TUIPreviewOnlyEvent,
    TUIPreviewReadyEvent,
    TUIQueryEvent,
    TUIRunRequest,
    run_tui_request,
)
from csvql.tui_result_store import (
    DEFAULT_TUI_RESULT_CAPACITY_BYTES,
    TUIResultCleanupSummary,
    TUIResultHandle,
    TUIResultStorageError,
    TUIResultStore,
)
from csvql.tui_results import (
    make_bounded_result_view_state,
    make_result_view_state,
    populate_result_table,
    result_preview_message,
)
from csvql.tui_sql_assist import (
    SQLAssistSource,
    SQLCompletionItem,
    SQLTemplateOption,
    build_assist_sources,
    build_completion_items,
    build_template_options,
    completion_edit,
)
from csvql.tui_state import (
    TUIBufferResultTab,
    TUIExportIntent,
    TUIExportIntentReplacement,
    TUIFocusPane,
    TUIOperationKind,
    TUIOperationRunState,
    TUIQueryHistoryItem,
    TUIQueryRunMode,
    TUIQueuedRunReplacement,
    TUIResultRecord,
    TUIResultViewState,
    TUISessionState,
    TUISource,
    TUISourceColumn,
    transition_result_record,
)
from csvql.tui_workflows import (
    build_initial_state,
    build_tui_export_intent,
    build_tui_run_request,
    export_last_result,
    external_catalog_source_paths,
    inspect_source,
    inspect_source_columns,
    profile_source,
    render_duckdb_identifier,
    sample_source,
    save_derived_result_source,
    save_sources_to_project_catalog,
    source_capability_status,
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

_FOOTER_KEY_ORDER_BY_PANE: dict[TUIFocusPane, tuple[str, ...]] = {
    "editor": ("f1", "f3", "f4", "f5", "f6", "f8", "f9", "f10", "f12"),
    "sources": ("f1", "f2", "f3", "f5", "f8", "f9"),
    "history": ("f1", "f2", "f5", "f6", "f7", "f9", "ctrl+s"),
    "results": ("f1", "f2", "f6", "f7", "f8", "f9", "ctrl+s"),
}

_MODAL_BLOCKED_APP_ACTIONS = {
    "add_source",
    "choose_csv_source",
    "export_last_result",
    "focus_history",
    "focus_results",
    "focus_sources",
    "focus_sql",
    "inspect_source",
    "insert_source_alias",
    "insert_starter_select",
    "open_sql_completion",
    "new_query",
    "profile_source",
    "quit",
    "quit_from_non_editor",
    "delete_result",
    "remove_source",
    "reopen_history",
    "rerun_history",
    "run_buffer",
    "run_query",
    "run_selected_or_current_query",
    "sample_source",
    "save_result_as_source",
    "save_sources",
    "select_next_buffer_result",
    "select_previous_buffer_result",
    "show_help",
    "show_source_columns",
}

_RESULTS_ONLY_ACTIONS = {
    "select_next_buffer_result",
    "select_previous_buffer_result",
}

_CLICK_FOCUS_TARGETS: dict[str, str] = {
    "sources-title": "sources",
    "history-title": "history",
    "sql-title": "sql",
    "run-status": "sql",
    "results-title": "results",
    "result-tabs": "results",
    "results-message": "results",
}

_MIN_TERMINAL_WIDTH = 100
_MIN_TERMINAL_HEIGHT = 30
_RECOMMENDED_TERMINAL_WIDTH = 120
_RECOMMENDED_TERMINAL_HEIGHT = 36
_FULL_RESULT_UNAVAILABLE_MESSAGE = (
    "The full result is no longer available because its temporary storage was lost."
)
_UNEXPECTED_QUERY_WORKER_FAILURE_MESSAGE = "Unable to complete the query. Try running it again."
_UNEXPECTED_OPERATION_WORKER_FAILURE_MESSAGE = "Unable to complete this action. Try again."


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
        yield Static(terminal_safe_text(self.prompt), markup=False)
        yield Input(id=self.input_id)

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class _ConfirmationScreen(ModalScreen[bool]):
    """Small yes/no confirmation modal for destructive TUI actions."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("y,enter", "confirm", "Confirm"),
        Binding("n,escape", "cancel", "Cancel"),
    ]

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        yield Static(terminal_safe_text(self.prompt), id="confirm-text", markup=False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


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


@dataclass(frozen=True, slots=True)
class _SourceInspectOutcome:
    source_name: str
    result: InspectResult
    columns: tuple[TUISourceColumn, ...]


@dataclass(frozen=True, slots=True)
class _SourceSampleOutcome:
    source_name: str
    result: SampleResult


@dataclass(frozen=True, slots=True)
class _SourceProfileOutcome:
    source_name: str
    result: ProfileResult


@dataclass(frozen=True, slots=True)
class _SourceColumnsOutcome:
    source_name: str
    columns: tuple[TUISourceColumn, ...]


@dataclass(frozen=True, slots=True)
class _ExportOutcome:
    path: Path


@dataclass(frozen=True, slots=True)
class _SaveResultSourceOutcome:
    source: TUISource


@dataclass(frozen=True, slots=True)
class _PendingExportPrompt:
    result_sequence: int
    expected_existing_intent: TUIExportIntent | None


@dataclass(frozen=True, slots=True)
class _TransientPreviewOnlyResult:
    sequence: int
    preview: BoundedQueryResult
    reason: str
    primary_error_message: str | None = None
    primary_suggestion: str | None = None
    persistence_error_message: str | None = None
    persistence_suggestion: str | None = None
    cleanup_notes: tuple[str, ...] = ()


class _SQLAssistPickerScreen(ModalScreen[str | None]):
    """Picker screen for SQL templates and completion items."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("enter", "choose", "Choose"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, choices: Sequence[tuple[str, str, str, str]]) -> None:
        super().__init__()
        self._choices = tuple(choices)

    def compose(self) -> ComposeResult:
        yield DataTable(id="sql-assist-options", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one("#sql-assist-options", DataTable)
        table.add_columns("label", "kind", "detail")
        for row_key, label, kind, detail in self._choices:
            table.add_row(
                literal_terminal_text(label),
                literal_terminal_text(kind),
                literal_terminal_text(detail),
                key=row_key,
            )
        if table.row_count:
            table.focus()
            table.move_cursor(row=0)

    def action_choose(self) -> None:
        table = self.query_one("#sql-assist-options", DataTable)
        row_key, _column_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        self.dismiss(None if row_key is None else str(row_key.value))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "sql-assist-options":
            return
        self.dismiss(None if event.row_key is None else str(event.row_key.value))


class _OrderedFooter(Footer):
    """Footer that keeps CSVQL's key order stable across focused widgets."""

    def compose(self) -> ComposeResult:
        if not self._bindings_ready:
            return

        active_bindings = self.screen.active_bindings
        ordered_footer_keys: list[FooterKey] = []
        for key in self._active_footer_key_order():
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

    def _active_footer_key_order(self) -> tuple[str, ...]:
        if isinstance(self.app, CSVQLMenuApp):
            return _FOOTER_KEY_ORDER_BY_PANE.get(self.app.state.active_pane, _FOOTER_KEY_ORDER)
        return _FOOTER_KEY_ORDER


class _TrackedThreadCallable:
    """Track the real lifetime of one executor callable."""

    def __init__(
        self,
        operation: OperationContext,
        terminal: asyncio.Future[None],
    ) -> None:
        self.operation = operation
        self.terminal = terminal
        self._state = "pending"
        self._lock = Lock()

    def try_start(self) -> bool:
        """Claim pending work for execution unless shutdown already cancelled it."""

        with self._lock:
            if self._state != "pending":
                return False
            self._state = "running"
            return True

    def cancel_before_start(self) -> bool:
        """Terminalize pending work so a later executor dispatch becomes a no-op."""

        with self._lock:
            if self._state != "pending":
                return False
            self._state = "terminal"
            return True

    def finish(self) -> bool:
        """Record actual callable terminalization once."""

        with self._lock:
            if self._state == "terminal":
                return False
            self._state = "terminal"
            return True


class CSVQLMenuApp(App[None]):
    """Minimal interactive menu for loading sources and running SQL."""

    CSS = """
    #status {
        height: 1;
    }

    #sources {
        height: 7;
    }

    #workbench {
        height: 1fr;
    }

    #left-pane {
        width: 38%;
    }

    #right-pane {
        width: 62%;
    }

    #history {
        height: 1fr;
    }

    #run-status {
        height: 1;
    }

    #sql {
        height: 10;
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
        Binding("f2,ctrl+down", "focus_sql", "SQL", key_display="F2", priority=True),
        Binding("f3,ctrl+o", "choose_csv_source", "Open CSV", key_display="F3", priority=True),
        Binding(
            "f4",
            "run_selected_or_current_query",
            "Run current",
            key_display="F4",
            priority=True,
        ),
        Binding("ctrl+r", "run_selected_or_current_query", "Run SQL", show=False),
        Binding("f5", "focus_results", "Results", key_display="F5", priority=True),
        Binding("f6,ctrl+up", "focus_sources", "Sources", key_display="F6", priority=True),
        Binding("f7", "export_last_result", "Export active", key_display="F7", priority=True),
        Binding("f8", "focus_history", "History", key_display="F8", priority=True),
        Binding("f9", "quit", "Quit", key_display="F9", priority=True),
        Binding("f10,ctrl+n", "new_query", "New query", key_display="F10", priority=True),
        Binding("[", "select_previous_buffer_result", "Previous buffer result", show=False),
        Binding("]", "select_next_buffer_result", "Next buffer result", show=False),
        Binding(
            "f12,ctrl+b",
            "run_buffer",
            "Run buffer",
            key_display="F12",
            priority=True,
        ),
        Binding(
            "ctrl+s,alt+s,f11",
            "save_result_as_source",
            "Save active",
            key_display="Ctrl+S/Alt+S",
            priority=True,
        ),
        Binding("i", "inspect_source", "Inspect", show=False),
        Binding("s", "sample_source", "Sample", show=False),
        Binding("p", "profile_source", "Profile", show=False),
        Binding("a", "add_source", "Add source", show=False),
        Binding("d", "remove_source", "Remove source", show=False),
        Binding("delete", "delete_result", "Delete result", show=False),
        Binding("w", "save_sources", "Save sources", show=False),
        Binding("c", "show_source_columns", "Columns", show=False),
        Binding("l", "insert_source_alias", "Insert alias", show=False),
        Binding("x", "insert_starter_select", "Starter select", show=False),
        Binding("ctrl+space", "open_sql_completion", "Complete SQL", show=False),
        Binding("escape", "cancel_operation", "Cancel operation", show=False),
        Binding("r", "rerun_history", "Rerun", show=False),
        Binding("enter", "reopen_history", "Open query", show=False),
    ]

    def __init__(
        self,
        *,
        csv_path: str | None = None,
        table_mappings: Sequence[str] = (),
        start_dir: Path | None = None,
        preview_policy: PreviewPolicy | None = None,
        result_store_capacity_bytes: int | None = None,
        initial_state: TUISessionState | None = None,
        result_store: TUIResultStore | None = None,
        initial_cleanup_summary: TUIResultCleanupSummary | None = None,
    ) -> None:
        super().__init__()
        self.start_dir = (start_dir or Path.cwd()).resolve()
        self._active_query_sql: dict[int, str] = {}
        self._active_query_records: dict[int, TUIResultRecord] = {}
        self._active_query_run_modes: dict[int, TUIQueryRunMode] = {}
        self._next_query_submission_order = 1
        self._next_operation_worker_id = 1
        self._run_editor_pending = False
        self._help_screen_open = False
        self._terminal_size_warning_initialized = False
        self._terminal_size_warning_active = False
        self._active_operation_worker: Worker[object] | None = None
        self._active_operation_context: OperationContext | None = None
        self._active_operation_token: OperationToken | None = None
        self._active_operation_result_sequence: int | None = None
        self._active_operation_worker_name: str | None = None
        self._active_query_worker: Worker[object] | None = None
        self._active_query_operation: OperationContext | None = None
        self._query_terminal_event_sequence: int | None = None
        self._attached_export_intent_in_flight: TUIExportIntent | None = None
        self._pending_export_prompt: _PendingExportPrompt | None = None
        self._transient_preview_only_result: _TransientPreviewOnlyResult | None = None
        self._cancelled_operation_names: set[str] = set()
        self._sql_assist_choices: dict[str, SQLTemplateOption | SQLCompletionItem] = {}
        self._preview_policy = preview_policy or PreviewPolicy()
        if initial_state is not None:
            self.state = initial_state
        else:
            self.state = build_initial_state(
                csv_path=csv_path,
                table_mappings=table_mappings,
                start_dir=self.start_dir,
            )
        if result_store is None:
            capacity_bytes = (
                DEFAULT_TUI_RESULT_CAPACITY_BYTES
                if result_store_capacity_bytes is None
                else result_store_capacity_bytes
            )
            self._result_store = TUIResultStore(capacity_bytes=capacity_bytes)
        else:
            if result_store_capacity_bytes is not None:
                raise ValueError(
                    "result_store_capacity_bytes cannot be overridden "
                    "when result_store is injected."
                )
            self._result_store = result_store
        self._cleanup_summary = initial_cleanup_summary or TUIResultCleanupSummary()
        self._did_cleanup = False
        self._cleanup_task: asyncio.Task[None] | None = None
        self._thread_callables: set[_TrackedThreadCallable] = set()

    @property
    def cleanup_summary(self) -> TUIResultCleanupSummary:
        """Return bounded recovery and shutdown cleanup counts."""

        return self._cleanup_summary

    def compose(self) -> ComposeResult:
        yield Static("", id="status", markup=False)
        with Horizontal(id="workbench"):
            with Vertical(id="left-pane"):
                yield Static("", id="sources-title", classes="pane-title", markup=False)
                yield DataTable(id="sources", cursor_type="row")
                yield Static("", id="history-title", classes="pane-title", markup=False)
                yield DataTable(id="history", cursor_type="row")
            with Vertical(id="right-pane"):
                yield Static("", id="sql-title", classes="pane-title", markup=False)
                yield _SourcePathTextArea(id="sql")
                yield Static("", id="run-status", markup=False)
                yield Static("", id="results-title", classes="pane-title", markup=False)
                yield Static("", id="result-tabs", markup=False)
                yield DataTable(id="results", cursor_type="cell")
                yield Static("", id="results-message", markup=False)
        yield Static("", id="context", markup=False)
        yield _OrderedFooter()

    async def on_mount(self) -> None:
        self._refresh_sources_table()
        self._refresh_history_table()
        self._set_status(self._status_message())
        self._set_run_status_ready()
        self._refresh_results_display()
        self.query_one("#sql", TextArea).focus()
        self._refresh_pane_context()
        self._apply_terminal_size_warning(width=self.size.width, height=self.size.height)
        self._terminal_size_warning_initialized = True

    async def on_unmount(self) -> None:
        if self._did_cleanup:
            return
        cleanup_task = self._cleanup_task
        if cleanup_task is None:
            cleanup_task = asyncio.create_task(self._drain_and_cleanup())
            self._cleanup_task = cleanup_task

        cancellation: asyncio.CancelledError | None = None
        current_task = asyncio.current_task()
        try:
            while True:
                try:
                    await asyncio.shield(cleanup_task)
                    break
                except asyncio.CancelledError as error:
                    if current_task is None or current_task.cancelling() == 0:
                        raise
                    cancellation = error
                    while current_task.cancelling():
                        current_task.uncancel()
        finally:
            if cleanup_task.done() and not self._did_cleanup and self._cleanup_task is cleanup_task:
                self._cleanup_task = None

        if cancellation is not None:
            raise cancellation

    async def _drain_and_cleanup(self) -> None:
        while self._thread_callables:
            callables = tuple(self._thread_callables)
            for tracked in callables:
                tracked.operation.request_cancel()
            for tracked in callables:
                if tracked.cancel_before_start():
                    self._finish_thread_callable(tracked)
            await asyncio.gather(*(asyncio.shield(tracked.terminal) for tracked in callables))
        self._cleanup_summary = self._cleanup_summary.merge(self._result_store.cleanup())
        self._did_cleanup = True

    def _track_thread_callable(
        self,
        operation: OperationContext,
        work: Callable[[], object],
    ) -> Callable[[], object | None]:
        loop = asyncio.get_running_loop()
        tracked = _TrackedThreadCallable(operation, loop.create_future())
        self._thread_callables.add(tracked)

        def run() -> object | None:
            if not tracked.try_start():
                return None
            try:
                operation.checkpoint()
                return work()
            finally:
                if tracked.finish():
                    loop.call_soon_threadsafe(self._finish_thread_callable, tracked)

        return run

    def _finish_thread_callable(self, tracked: _TrackedThreadCallable) -> None:
        if not tracked.terminal.done():
            tracked.terminal.set_result(None)
        self._thread_callables.discard(tracked)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        del event
        self._refresh_pane_context()

    def on_resize(self, event: events.Resize) -> None:
        if not self._terminal_size_warning_initialized:
            return
        self._apply_terminal_size_warning(width=event.size.width, height=event.size.height)

    def _set_run_status_ready(self) -> None:
        self._update_static_text("#run-status", "Ready.")

    def action_add_source(self) -> None:
        self._open_add_source_prompt("Enter name=path or paste CSV path(s).")

    def _open_add_source_prompt(self, prompt: str) -> None:
        if self._prompt_screen_active():
            return
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
        if self._help_screen_open or isinstance(
            self.screen,
            (_HelpScreen, _PromptInputScreen, _ConfirmationScreen),
        ):
            return
        self._help_screen_open = True
        self.push_screen(_HelpScreen(), callback=lambda _: self._mark_help_closed())

    def _mark_help_closed(self) -> None:
        self._help_screen_open = False

    def _prompt_screen_active(self) -> bool:
        return isinstance(self.screen, (_HelpScreen, _PromptInputScreen, _ConfirmationScreen))

    def _input_or_confirmation_screen_active(self) -> bool:
        return isinstance(self.screen, (_PromptInputScreen, _ConfirmationScreen))

    def action_choose_csv_source(self) -> None:
        if self._prompt_screen_active():
            return
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
        if self._input_or_confirmation_screen_active():
            return
        sql_widget = self.query_one("#sql", TextArea)
        sql_widget.load_text("")
        sql_widget.focus()
        self._set_status("Ready for next query.")

    def action_remove_source(self) -> None:
        selected_source = self.state.selected_source()
        if selected_source is None:
            self._show_error(CSVQLError("No source selected."))
            return

        source_name = selected_source.name
        self.push_screen(
            _ConfirmationScreen(f"Remove source {source_name}? Press y to remove or n to cancel."),
            callback=lambda confirmed: self._handle_remove_source_confirmation(
                source_name,
                confirmed,
            ),
        )

    def _handle_remove_source_confirmation(self, source_name: str, confirmed: bool | None) -> None:
        if not confirmed:
            self._set_status("Source removal cancelled.")
            self.query_one("#sources", DataTable).focus()
            return

        try:
            removed_source = self.state.remove_source(source_name)
        except CSVQLError as exc:
            self._show_error(exc)
            return

        self._refresh_sources_table()
        self._set_status(f"Removed source {removed_source.name}. {self._status_message()}")
        self.query_one("#sources", DataTable).focus()

    def action_delete_result(self) -> None:
        if self._input_or_confirmation_screen_active():
            return
        sequence = self._selected_result_sequence_for_delete()
        if sequence is None:
            self._show_error(CSVQLError("No preserved result selected."))
            return
        record = self._result_record_for_sequence(sequence)
        if record is None:
            self._show_error(CSVQLError("No preserved result selected."))
            return
        self.push_screen(
            _ConfirmationScreen(
                f"Delete preserved result {sequence}? Press y to delete or n to keep it."
            ),
            callback=lambda confirmed: self._handle_delete_result_confirmation(
                sequence,
                record.handle,
                record.state,
                confirmed,
            ),
        )

    def _handle_delete_result_confirmation(
        self,
        sequence: int,
        expected_handle: TUIResultHandle | None,
        expected_state: str,
        confirmed: bool | None,
    ) -> None:
        if not confirmed:
            self._set_status("Result deletion cancelled.")
            return
        record = self._result_record_for_sequence(sequence)
        if (
            record is None
            or record.state not in {"complete", "preview_only"}
            or expected_state not in {"complete", "preview_only"}
            or record.handle != expected_handle
            or record.state != expected_state
        ):
            self._show_error(CSVQLError("The selected preserved result is no longer available."))
            return
        if record.handle is not None:
            try:
                self._result_store.remove(record.handle)
            except TUIResultStorageError as exc:
                invalidated_sequences = tuple(sorted({sequence, *exc.invalidated_sequences}))
                self.state.mark_results_unavailable(
                    invalidated_sequences,
                    exc.user_message,
                )
                self._refresh_history_table()
                self._refresh_results_display()
                self._refresh_pane_context()
                self._show_error(CSVQLError(exc.user_message))
                return
        self.state.remove_query_result(sequence)
        self._refresh_history_table()
        self._refresh_results_display()
        self._refresh_pane_context()
        if expected_handle is None:
            self._clear_transient_preview_only(sequence)
            self._set_status(f"Deleted preserved result {sequence}.")
            if self._continue_after_query_worker_terminalized():
                return
            return
        if self._offer_paused_preview_retry(sequence):
            return
        self._set_status(f"Deleted preserved result {sequence}.")

    def action_inspect_source(self) -> None:
        if self._operation_running():
            self._set_status(f"{self.state.operation_run.label} already running.")
            return
        if self.state.query_run.is_running:
            self._set_status("Query already running. Wait for the current query to finish.")
            return
        if self._reject_result_replacing_action_for_transient_preview():
            return

        source = self.state.selected_source()
        if source is None:
            self._show_error(CSVQLError("No source selected."))
            return
        if self._reject_unavailable_source_action(source, "inspect"):
            return

        self._start_operation_worker(
            kind="inspect",
            label=f"Inspecting {source.name}",
            work=lambda operation: _inspect_source_outcome(source, operation=operation),
        )

    def action_profile_source(self) -> None:
        if self._operation_running():
            self._set_status(f"{self.state.operation_run.label} already running.")
            return
        if self.state.query_run.is_running:
            self._set_status("Query already running. Wait for the current query to finish.")
            return
        if self._reject_result_replacing_action_for_transient_preview():
            return

        source = self.state.selected_source()
        if source is None:
            self._show_error(CSVQLError("No source selected."))
            return
        if self._reject_unavailable_source_action(source, "profile"):
            return

        self._start_operation_worker(
            kind="profile",
            label=f"Profiling {source.name}",
            work=lambda operation: _SourceProfileOutcome(
                source_name=source.name,
                result=profile_source(source, operation=operation),
            ),
        )

    def action_sample_source(self) -> None:
        if self._operation_running():
            self._set_status(f"{self.state.operation_run.label} already running.")
            return
        if self.state.query_run.is_running:
            self._set_status("Query already running. Wait for the current query to finish.")
            return
        if self._reject_result_replacing_action_for_transient_preview():
            return

        source = self.state.selected_source()
        if source is None:
            self._show_error(CSVQLError("No source selected."))
            return
        if self._reject_unavailable_source_action(source, "sample"):
            return

        self._start_operation_worker(
            kind="sample",
            label=f"Sampling {source.name}",
            work=lambda operation: _SourceSampleOutcome(
                source_name=source.name,
                result=sample_source(source, operation=operation),
            ),
        )

    def action_show_source_columns(self) -> None:
        if self._operation_running():
            self._set_status(f"{self.state.operation_run.label} already running.")
            return
        if self.state.query_run.is_running:
            self._set_status("Query already running. Wait for the current query to finish.")
            return
        if self._reject_result_replacing_action_for_transient_preview():
            return
        self.state.clear_last_result()
        source = self.state.selected_source()
        if source is None:
            self._show_error(CSVQLError("No source selected."))
            return
        if self._reject_unavailable_source_action(source, "inspect"):
            return

        self._start_operation_worker(
            kind="columns",
            label=f"Loading columns for {source.name}",
            work=lambda operation: _SourceColumnsOutcome(
                source_name=source.name,
                columns=inspect_source_columns(source, operation=operation),
            ),
        )

    def _reject_unavailable_source_action(
        self,
        source: TUISource,
        operation: SourceCapability,
    ) -> bool:
        status = source_capability_status(source, operation)
        if status.state == "available":
            return False
        self._show_error(
            CSVQLError(
                (f"Source capability '{operation}' is {status.state} ({status.reason_code})."),
                suggestion=status.remediation,
            )
        )
        return True

    def action_insert_source_alias(self) -> None:
        source = self.state.selected_source()
        if source is None:
            self._clear_last_result_unless_transient_preview_active()
            self._show_error(CSVQLError("No source selected."))
            return

        self._append_sql_text(render_duckdb_identifier(source.name))
        self._set_status(f"Inserted alias {source.name} into SQL editor.")

    def action_insert_starter_select(self) -> None:
        source = self.state.selected_source()
        if source is None:
            self._clear_last_result_unless_transient_preview_active()
            self._show_error(CSVQLError("No source selected."))
            return

        options = build_template_options(self._assist_sources(), source.name)
        self._sql_assist_choices = {option.key: option for option in options}
        if len(options) <= 2:
            self._set_status(
                f"Press c or i for column-aware templates. {source.name} preview templates ready."
            )
        self.push_screen(
            _SQLAssistPickerScreen(
                tuple((option.key, option.label, "template", option.detail) for option in options)
            ),
            callback=self._handle_sql_template_selection,
        )

    def _sql_completion_items_for_editor(self, sql: TextArea) -> tuple[SQLCompletionItem, ...]:
        return build_completion_items(
            self._assist_sources(),
            text=sql.text,
            cursor_index=_text_index_from_location(sql.text, sql.selection.end),
        )

    def _open_sql_completion_for_editor(
        self,
        sql: TextArea,
        *,
        empty_status_message: str | None,
    ) -> bool:
        items = self._sql_completion_items_for_editor(sql)
        if not items:
            if empty_status_message is not None:
                self._set_status(empty_status_message)
            return False

        self._sql_assist_choices = {item.key: item for item in items}
        self.push_screen(
            _SQLAssistPickerScreen(
                tuple((item.key, item.label, item.item_kind, item.detail) for item in items)
            ),
            callback=self._handle_sql_completion_selection,
        )
        return True

    def action_open_sql_completion(self) -> None:
        if not isinstance(self.focused, TextArea):
            return

        self._open_sql_completion_for_editor(
            self.query_one("#sql", TextArea),
            empty_status_message="No completion items available.",
        )

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
        if self._operation_running():
            self._show_rejected_run(
                CSVQLError(
                    f"{self.state.operation_run.label} already running.",
                    suggestion="Wait for the current action to finish.",
                )
            )
            return
        if self._run_editor_pending:
            self._show_rejected_run(
                CSVQLError(
                    "A run request is already being prepared.",
                    suggestion="Wait for the editor snapshot to settle.",
                ),
                reset_run_status=False,
                simple_message_without_previous=True,
            )
            return

        self._run_editor_pending = True
        self._update_static_text("#run-status", preparing_message)
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
        paused_preview_message = self._active_transient_preview_pause_message()
        if paused_preview_message is not None:
            self._show_rejected_run(CSVQLError(paused_preview_message))
            return
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
            sequences = self.state.reserve_query_sequences(len(statements))
            request = self._build_query_request(
                statements,
                sequences=sequences,
                run_mode="buffer",
            )
            if self.state.query_run.is_running:
                self._enqueue_query_request(request)
                return
            self._activate_query_request(request)
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
        except CSVQLError as exc:
            self._show_rejected_run(exc)
            return
        except ValueError as exc:
            self._show_rejected_run(CSVQLError(str(exc)))
            return

    def _run_selected_or_current_query_from_editor(self) -> None:
        self._run_editor_pending = False
        sql_widget = self.query_one("#sql", TextArea)
        sql = selected_or_current_sql(
            sql_widget.text,
            cursor_location=sql_widget.cursor_location,
            selected_text=sql_widget.selected_text,
        )
        self._start_query_run(sql, run_label="current SQL", run_mode="current")

    def _build_query_request(
        self,
        statements: Sequence[str],
        *,
        sequences: Sequence[int],
        run_mode: TUIQueryRunMode,
    ) -> TUIRunRequest:
        operation = OperationContext(OperationToken())
        request = build_tui_run_request(
            self.state.sources,
            tuple(statements),
            sequences=tuple(sequences),
            preview_policy=self._preview_policy,
            run_mode=run_mode,
            submission_order=self._next_query_submission_order,
            start_dir=self.start_dir,
            operation=operation,
        )
        self._next_query_submission_order += 1
        return request

    def _enqueue_query_request(self, request: TUIRunRequest) -> None:
        replacement = self.state.enqueue_run(request)
        if replacement is None:
            message = f"Queued 1 run request: {_run_request_description(request)}."
            self._set_status(message)
            self._update_static_text("#run-status", message)
            self.query_one("#sql", TextArea).focus()
            return

        prompt = (
            "Replace queued run "
            f"{_run_request_description(replacement.existing.request)} "
            f"with {_run_request_description(replacement.proposed.request)}? "
            "Press y to replace or n to keep the existing request."
        )
        self.push_screen(
            _ConfirmationScreen(prompt),
            callback=lambda confirmed: self._handle_queued_run_replacement(
                replacement,
                confirmed,
            ),
        )

    def _handle_queued_run_replacement(
        self,
        replacement: TUIQueuedRunReplacement,
        confirmed: bool | None,
    ) -> None:
        if not confirmed:
            self._set_status(
                "Queued run replacement cancelled; "
                f"kept {_run_request_description(replacement.existing.request)}."
            )
            self.query_one("#sql", TextArea).focus()
            return
        try:
            self.state.replace_queued_run(replacement)
        except RuntimeError as exc:
            self._show_error(CSVQLError(str(exc)))
            return
        message = (
            f"Replaced queued run with {_run_request_description(replacement.proposed.request)}."
        )
        self._set_status(message)
        self._update_static_text("#run-status", message)
        self.query_one("#sql", TextArea).focus()

    def _activate_query_request(
        self,
        request: TUIRunRequest,
        *,
        run_label: str | None = None,
        rerun_source_sequence: int | None = None,
    ) -> None:
        self._transient_preview_only_result = None
        self._query_terminal_event_sequence = None
        self.state.start_query_request(request)
        if request.run_mode != "buffer":
            sequence = request.sequences[0]
            executing_record = TUIResultRecord(
                handle=None,
                state="executing",
                reason=None,
                columns=(),
                preview_row_count=0,
                full_row_count=None,
                elapsed_ms=0.0,
            )
            self.state.set_active_result_record(
                sequence,
                executing_record,
                run_mode=request.run_mode,
            )
            self._active_query_records[sequence] = executing_record

        for sequence, statement in zip(
            request.sequences,
            request.statements,
            strict=True,
        ):
            self._active_query_sql[sequence] = statement
            self._active_query_run_modes[sequence] = request.run_mode

        message = _run_start_message(
            sequence=request.sequences[0],
            run_label=(
                run_label
                if run_label is not None
                else ("buffer SQL" if request.run_mode == "buffer" else "query")
            ),
            run_mode=request.run_mode,
            rerun_source_sequence=rerun_source_sequence,
        )
        self._set_status(message)
        self._update_static_text("#run-status", message)
        self._start_query_worker(request)

    def _start_query_worker(self, request: TUIRunRequest) -> None:
        if self._active_query_worker is not None and not self._active_query_worker.is_finished:
            raise RuntimeError("query worker already active")
        operation = OperationContext(OperationToken())
        self._active_query_operation = operation

        self._active_query_worker = self.run_worker(
            self._track_thread_callable(
                operation,
                lambda: run_tui_request(
                    request,
                    result_store=self._result_store,
                    event_sink=self._schedule_query_event,
                    operation=operation,
                ),
            ),
            name=f"query-{request.sequences[0]}",
            group="query",
            thread=True,
            exit_on_error=False,
        )

    def _schedule_query_event(self, event: TUIQueryEvent) -> None:
        self.call_from_thread(self._handle_query_event, event)

    def _is_last_sequence_in_request(self, sequence: int) -> bool:
        request = self.state.query_run.request
        return request is not None and request.sequences[-1] == sequence

    def _buffer_result_index(self, sequence: int) -> int | None:
        for tab in self.state.buffer_result_tabs:
            if tab.sequence == sequence:
                return tab.index
        return None

    def _ensure_buffer_tab(self, sequence: int) -> int:
        existing_index = self._buffer_result_index(sequence)
        if existing_index is not None:
            return existing_index
        next_index = len(self.state.buffer_result_tabs) + 1
        self.state.set_buffer_result_tabs(
            (
                *self.state.buffer_result_tabs,
                TUIBufferResultTab(
                    sequence=sequence,
                    index=next_index,
                    label=f"query {next_index}",
                ),
            )
        )
        return next_index

    def _begin_buffer_result_lifecycle(
        self,
        sequence: int,
    ) -> int:
        buffer_result_index = self._ensure_buffer_tab(sequence)
        self.state.set_active_result_record(
            sequence,
            TUIResultRecord(
                handle=None,
                state="executing",
                reason=None,
                columns=(),
                preview_row_count=0,
                full_row_count=None,
                elapsed_ms=0.0,
            ),
            run_mode="buffer",
            buffer_result_index=buffer_result_index,
        )
        return buffer_result_index

    def _restore_previous_buffer_selection(
        self,
        previous_tabs: tuple[TUIBufferResultTab, ...],
        previous_sequence: int | None,
    ) -> None:
        if not previous_tabs:
            return
        self.state.set_buffer_result_tabs(previous_tabs, selected_sequence=previous_sequence)
        if previous_sequence is None:
            return
        tab = next((item for item in previous_tabs if item.sequence == previous_sequence), None)
        if tab is None:
            return
        self._show_buffer_result_at_tab(tab)

    def _start_query_run(
        self,
        sql: str,
        *,
        run_label: str,
        run_mode: TUIQueryRunMode,
        rerun_source_sequence: int | None = None,
    ) -> None:
        paused_preview_message = self._active_transient_preview_pause_message()
        if paused_preview_message is not None:
            self._show_rejected_run(CSVQLError(paused_preview_message))
            return
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
            sequence = self.state.reserve_query_sequences(1)[0]
            request = self._build_query_request(
                (sql,),
                sequences=(sequence,),
                run_mode=run_mode,
            )
            if self.state.query_run.is_running:
                self._enqueue_query_request(request)
                return
            self._activate_query_request(
                request,
                run_label=run_label,
                rerun_source_sequence=rerun_source_sequence,
            )
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
        except CSVQLError as exc:
            self._show_rejected_run(exc)
            return
        except ValueError as exc:
            self._show_rejected_run(CSVQLError(str(exc)))
            return

    def action_export_last_result(self) -> None:
        if self._prompt_screen_active():
            return
        if self._is_focused("#history"):
            self._show_selected_history_result()
        if self._show_active_result_unavailable():
            return
        record = self.state.active_query_result_record()
        result_sequence = self.state.active_result.sequence
        if (
            record is None
            or result_sequence is None
            or record.state not in {"preserving", "complete"}
        ):
            self._show_error(CSVQLError("Run a query before exporting."))
            return
        prompt = _PromptInputScreen(
            (
                "Export active result to path "
                "(.csv, .json, .md, .markdown, .txt; blank suffix uses .csv)."
            ),
            input_id="export-path",
        )
        if record.state == "preserving":
            if self._pending_export_prompt is not None:
                self._show_error(CSVQLError("An export path prompt is already pending."))
                return
            pending = _PendingExportPrompt(
                result_sequence=result_sequence,
                expected_existing_intent=self.state.export_intent,
            )
            self._pending_export_prompt = pending
            try:
                self.push_screen(
                    prompt,
                    callback=lambda path_value: self._handle_pending_export_prompt(
                        pending,
                        path_value,
                    ),
                )
            except ScreenStackError:
                if self._pending_export_prompt is pending:
                    self._pending_export_prompt = None
                self._show_error(CSVQLError("Unable to open the export path prompt."))
            return

        self.push_screen(
            prompt,
            callback=lambda path_value: self._handle_export_last_result(
                path_value,
                result_sequence=result_sequence,
            ),
        )

    def action_save_result_as_source(self) -> None:
        if self._prompt_screen_active():
            return
        if self._is_focused("#history"):
            self._show_selected_history_result()
        if self._show_active_result_unavailable():
            return
        record = self.state.active_query_result_record()
        result_sequence = self.state.active_result.sequence
        if (
            record is None
            or result_sequence is None
            or record.state != "complete"
            or record.handle is None
        ):
            if self._show_active_result_unavailable():
                return
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
            callback=lambda alias: self._handle_save_result_as_source(
                alias,
                result_sequence=result_sequence,
                expected_handle=record.handle,
            ),
        )

    def action_save_sources(self) -> None:
        if self._input_or_confirmation_screen_active():
            return
        if not self.state.sources:
            self._show_error(CSVQLError("No sources loaded to save."))
            return

        source_count = len(self.state.sources)
        noun = "source path" if source_count == 1 else "source paths"
        external_paths = external_catalog_source_paths(self.state.sources, start_dir=self.start_dir)
        warning = ""
        if external_paths:
            warning = (
                " Warning: this catalog will persist external local filesystem paths "
                "and may reveal machine-specific locations if shared."
            )
        prompt = (
            f"Save {source_count} {noun} to .csvql.yml?{warning} Press y to save or n to cancel."
        )
        self.push_screen(
            _ConfirmationScreen(prompt),
            callback=self._handle_save_sources_confirmation,
        )

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

    def _operation_running(self) -> bool:
        return self.state.operation_run.is_running

    def _start_operation_worker(
        self,
        *,
        kind: TUIOperationKind,
        label: str,
        result_sequence: int | None = None,
        work: Callable[[OperationContext], object],
    ) -> bool:
        if self._operation_running():
            self._set_status(f"{self.state.operation_run.label} already running.")
            return False

        self.state.operation_run = TUIOperationRunState(is_running=True, kind=kind, label=label)
        self._set_status(f"{label}...")
        operation = OperationContext(OperationToken())
        token = operation.token
        self._active_operation_context = operation
        self._active_operation_token = token
        self._active_operation_result_sequence = result_sequence
        worker_name = f"operation-{kind}-{self._next_operation_worker_id}"
        self._active_operation_worker_name = worker_name
        self._next_operation_worker_id += 1
        worker = self.run_worker(
            self._track_thread_callable(operation, lambda: work(operation)),
            name=worker_name,
            group="operation",
            thread=True,
            exit_on_error=False,
        )
        self._active_operation_worker = worker
        return True

    def action_cancel_operation(self) -> None:
        if self.state.query_run.is_running:
            worker = self._active_query_worker
            operation = self._active_query_operation
            if worker is None or worker.is_finished or operation is None:
                return
            operation.request_cancel()
            self._set_status("Cancelling query preservation...")
            return

        worker = self._active_operation_worker
        if worker is None or worker.is_finished:
            return

        operation = self._active_operation_context
        label = self.state.operation_run.label
        worker_name = worker.name or ""
        ordered_chain_pending = (
            self._attached_export_intent_in_flight is not None
            or self.state.export_intent is not None
        )
        if ordered_chain_pending:
            if operation is None:
                self._show_error(
                    CSVQLError(
                        f"Unable to cancel {label}.",
                        suggestion="Wait for the current action to finish.",
                    )
                )
                return
            operation.request_cancel()
            self._set_status(f"Cancelling {label}...")
            return
        self._cancelled_operation_names.add(worker_name)
        if operation is not None:
            operation.request_cancel()
        worker.cancel()
        self.state.operation_run = TUIOperationRunState()
        self._active_operation_worker = None
        self._set_status(f"Cancelled {label}.")

    def _handle_operation_worker_state(
        self,
        worker: Worker[object],
        state: WorkerState,
    ) -> None:
        if not worker.is_finished:
            return

        worker_name = worker.name or ""
        if worker_name in self._cancelled_operation_names:
            self._cancelled_operation_names.discard(worker_name)
            if self._active_operation_worker_name == worker_name:
                self._active_operation_worker_name = None
                self._active_operation_context = None
                self._active_operation_token = None
                self._active_operation_result_sequence = None
            if self._active_operation_worker is worker:
                self._active_operation_worker = None
                self.state.operation_run = TUIOperationRunState()
            self._resume_deferred_attached_export()
            return

        if self._active_operation_worker is not worker:
            return

        attached_intent = self._attached_export_intent_in_flight
        operation_label = self.state.operation_run.label.strip()
        self._active_operation_worker = None
        self.state.operation_run = TUIOperationRunState()
        if self._active_operation_worker_name == worker_name:
            self._active_operation_worker_name = None
            self._active_operation_context = None
            self._active_operation_token = None
            operation_result_sequence = self._active_operation_result_sequence
            self._active_operation_result_sequence = None
        else:
            operation_result_sequence = None

        if state == WorkerState.CANCELLED:
            if attached_intent is not None:
                self._set_status(
                    "Cancelled attached export to "
                    f"{_display_path(attached_intent.destination, self.start_dir)}."
                )
                self._finish_attached_export(attached_intent)
            else:
                self._resume_deferred_attached_export()
            return
        if state == WorkerState.ERROR:
            self._handle_operation_worker_failure(
                worker.error,
                operation_label=operation_label,
                operation_result_sequence=operation_result_sequence,
            )
            if attached_intent is not None:
                self._finish_attached_export(attached_intent)
            else:
                self._resume_deferred_attached_export()
            return
        if state != WorkerState.SUCCESS:
            self._resume_deferred_attached_export()
            return

        self._apply_operation_outcome(worker.result, operation_label=operation_label)
        if attached_intent is not None:
            self._finish_attached_export(attached_intent)
        else:
            self._resume_deferred_attached_export()

    def _apply_operation_outcome(self, outcome: object, *, operation_label: str) -> None:
        query_running = self.state.query_run.is_running
        if isinstance(outcome, _SourceInspectOutcome):
            self.state.set_source_columns(outcome.source_name, outcome.columns)
            if query_running:
                self._set_status(
                    f"{outcome.source_name}: inspect completed. "
                    "Query results remain visible until the current query finishes."
                )
                return
            self._show_source_inspect_table(outcome.result, outcome.columns)
            self._set_status(f"{outcome.source_name}: {len(outcome.columns)} columns inspected.")
            return
        if isinstance(outcome, _SourceProfileOutcome):
            if query_running:
                self._set_status(
                    f"{outcome.source_name}: profile completed. "
                    "Query results remain visible until the current query finishes."
                )
                return
            self._show_source_profile_table(outcome.result)
            self._set_status(
                f"{outcome.source_name}: {outcome.result.row_count} rows, "
                f"{outcome.result.column_count} columns, "
                f"{outcome.result.duplicate_row_count} duplicate rows.",
            )
            return
        if isinstance(outcome, _SourceSampleOutcome):
            if query_running:
                self._set_status(
                    f"{outcome.source_name}: sample completed. "
                    "Query results remain visible until the current query finishes."
                )
                return
            self.state.clear_last_result()
            query_result = QueryResult(
                columns=outcome.result.columns,
                rows=outcome.result.rows,
                elapsed_ms=0.0,
            )
            view = make_result_view_state(query_result, source_result_sequence=0)
            populate_result_table(self.query_one("#results", DataTable), view)
            self._refresh_results_title()
            self._refresh_result_tabs()
            self._update_static_text("#results-message", result_preview_message(view))
            self._set_status(f"{outcome.source_name}: {len(outcome.result.rows)} sample row(s).")
            return
        if isinstance(outcome, _SourceColumnsOutcome):
            self.state.set_source_columns(outcome.source_name, outcome.columns)
            if query_running:
                if not outcome.columns:
                    self._set_status(
                        f"{outcome.source_name}: no columns available. "
                        "Query results remain visible until the current query finishes."
                    )
                    return
                self._set_status(
                    f"{outcome.source_name}: columns loaded. "
                    "Query results remain visible until the current query finishes."
                )
                return
            if not outcome.columns:
                self._show_error(CSVQLError(f"Source '{outcome.source_name}' has no columns."))
                return
            self._show_source_columns_table(
                outcome.columns,
                message=f"Source columns: {outcome.source_name}.",
            )
            self._set_status(f"{outcome.source_name}: {len(outcome.columns)} columns loaded.")
            return
        if isinstance(outcome, _ExportOutcome):
            display_path = _display_path(outcome.path, self.start_dir)
            self._set_status(f"Exported to {display_path}.")
            if not self.state.result_view.is_truncated:
                self._update_static_text("#results-message", f"Exported to {display_path}.")
            return
        if isinstance(outcome, _SaveResultSourceOutcome):
            source = outcome.source
            self.state.add_source(source)
            self.state.select_source(source.name)
            self._refresh_sources_table()
            display_path = _display_path(source.path, self.start_dir)
            message = (
                f"Saved result as derived source {source.name} at {display_path}. "
                "Use Save sources to persist the alias in .csvql.yml."
            )
            self._set_status(message)
            if not self.state.result_view.is_truncated:
                self._update_static_text("#results-message", message)
            return

        self._show_error(
            CSVQLError(
                self._unexpected_operation_worker_result_message(operation_label),
                suggestion="Try the action again.",
            )
        )

    def _handle_operation_worker_failure(
        self,
        error: BaseException | None,
        *,
        operation_label: str,
        operation_result_sequence: int | None = None,
    ) -> None:
        if isinstance(error, OperationCancelled):
            return
        if isinstance(error, TUIResultStorageError):
            invalidated_sequences = set(error.invalidated_sequences)
            if operation_result_sequence is not None:
                invalidated_sequences.add(operation_result_sequence)
            self.state.mark_results_unavailable(
                tuple(sorted(invalidated_sequences)),
                error.user_message,
            )
            self._refresh_history_table()
            self._refresh_results_display()
            self._refresh_pane_context()
            self._show_error(CSVQLError(error.user_message))
            return
        if self.state.query_run.is_running:
            self._set_status(
                f"{operation_label or 'Action'} failed while a query result is active. "
                "Query results remain visible."
            )
            return
        if isinstance(error, CSVQLError):
            self._show_error(error)
            return

        self._show_error(CSVQLError(_UNEXPECTED_OPERATION_WORKER_FAILURE_MESSAGE))

    def _unexpected_operation_worker_result_message(self, operation_label: str) -> str:
        if not operation_label:
            return "Unexpected worker result while running the operation."
        return f"Unexpected worker result while {operation_label.lower()}."

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.group == "operation":
            self._handle_operation_worker_state(worker, event.state)
            return
        if worker.group != "query" or not worker.is_finished:
            return
        request = self.state.query_run.request
        if self._active_query_worker is worker:
            self._active_query_worker = None
            self._active_query_operation = None
        if self._query_terminal_event_sequence is not None:
            self.state.finish_query_run()
        elif event.state == WorkerState.ERROR:
            self._handle_query_worker_failure(worker, worker.error)
        elif (
            event.state == WorkerState.SUCCESS
            and request is not None
            and request.run_mode == "buffer"
        ):
            handled_sequences = {
                item.sequence
                for item in self.state.query_history
                if item.sequence in request.sequences
            }
            if not handled_sequences:
                self._handle_empty_buffer_outcome(worker)
            else:
                self.state.finish_query_run()
        elif event.state == WorkerState.SUCCESS:
            self.state.finish_query_run()
        elif request is not None:
            self._handle_query_worker_failure(worker, worker.error)

        if not self.state.query_run.is_running:
            self._query_terminal_event_sequence = None
        if self._continue_after_query_worker_terminalized():
            return
        if not self.state.query_run.is_running:
            self._update_static_text("#run-status", "Ready.")
            self.query_one("#sql", TextArea).focus()

    def _continue_after_query_worker_terminalized(self) -> bool:
        if self.state.query_run.is_running:
            return False

        pending = self._pending_export_prompt
        if pending is not None:
            record = self._result_record_for_sequence(pending.result_sequence)
            result_is_complete = (
                record is not None and record.state == "complete" and record.handle is not None
            )
            if not result_is_complete:
                self._pending_export_prompt = None
                self._dismiss_pending_export_prompt()
                if self.state.export_intent is None:
                    message = (
                        f"Pending export for query {pending.result_sequence} was not "
                        "started because preservation did not produce a complete result."
                    )
                    self._set_status(message)
                    self._update_static_text("#results-message", message)
            elif pending.expected_existing_intent is None:
                if (
                    self.state.export_intent is None
                    and self._attached_export_intent_in_flight is None
                ):
                    return True
                self._pending_export_prompt = None
                self._dismiss_pending_export_prompt()
            elif self.state.export_intent is not pending.expected_existing_intent:
                self._pending_export_prompt = None
                self._dismiss_pending_export_prompt()

        intent = self.state.export_intent
        if intent is not None:
            record = self.state.query_result_record(intent.result_sequence)
            if record is not None and record.state == "complete" and record.handle is not None:
                return self._start_attached_export(intent, record)

            self.state.clear_export_intent(intent)
            message = (
                f"Attached export for query {intent.result_sequence} was not started "
                "because preservation did not produce a complete result."
            )
            self._set_status(message)
            self._update_static_text("#results-message", message)

        paused_preview = self._paused_preview_only_sequence()
        if paused_preview is not None:
            self._set_status(self._paused_preview_status_message(paused_preview))
            return True

        return self._start_next_queued_request()

    def _start_attached_export(
        self,
        intent: TUIExportIntent,
        record: TUIResultRecord,
    ) -> bool:
        if self._attached_export_intent_in_flight is not None:
            raise RuntimeError("an attached export is already active")
        if self._operation_running():
            return True
        handle = record.handle
        if record.state != "complete" or handle is None:
            raise RuntimeError("attached export requires a complete preserved result")
        self._attached_export_intent_in_flight = intent
        started = self._start_operation_worker(
            kind="export",
            label=(
                f"Exporting preserved query {intent.result_sequence} to "
                f"{_display_path(intent.destination, self.start_dir)}"
            ),
            result_sequence=handle.sequence,
            work=lambda operation: _ExportOutcome(
                path=export_last_result(
                    self._result_store,
                    handle,
                    str(intent.destination),
                    columns=record.columns,
                    elapsed_ms=record.elapsed_ms,
                    export_format=intent.format,
                    base_dir=self.start_dir,
                    force=False,
                    token=operation.token,
                )
            ),
        )
        if started:
            return True
        self._attached_export_intent_in_flight = None
        return True

    def _resume_deferred_attached_export(self) -> None:
        if (
            self.state.query_run.is_running
            or self._operation_running()
            or self._attached_export_intent_in_flight is not None
            or self.state.export_intent is None
        ):
            return
        self._continue_after_query_worker_terminalized()

    def _finish_attached_export(self, intent: TUIExportIntent) -> None:
        if self._attached_export_intent_in_flight is not intent:
            return
        current_intent = self.state.export_intent
        if current_intent is intent:
            self.state.clear_export_intent(intent)
        elif current_intent is not None:
            self._show_error(
                CSVQLError("Attached export identity changed while the export was running.")
            )
            return
        self._attached_export_intent_in_flight = None
        if self._start_next_queued_request():
            return
        self._update_static_text("#run-status", "Ready.")
        self.query_one("#sql", TextArea).focus()

    def _start_next_queued_request(self) -> bool:
        queued = self.state.dequeue_run()
        if queued is None:
            return False
        try:
            self._activate_query_request(queued.request)
        except (CSVQLError, RuntimeError, ValueError) as exc:
            self._show_error(CSVQLError(f"Unable to start queued run: {exc}"))
            self._update_static_text("#run-status", "Ready.")
            return False
        return True

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

    def on_click(self, event: events.Click) -> None:
        target = _click_focus_target(event.widget)
        if target is None:
            return
        self.query_one(f"#{target}", Widget).focus()
        self._refresh_pane_context()

    def on_paste(self, event: events.Paste) -> None:
        if isinstance(self.focused, Input):
            return
        if self._handle_pasted_csv_sources(event.text):
            event.stop()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        del parameters
        if self._app_action_blocked_by_modal(action):
            return False
        if action in _RESULTS_ONLY_ACTIONS and not self._is_focused("#results"):
            return False
        operation_actions = {
            "delete_result",
            "inspect_source",
            "sample_source",
            "profile_source",
            "show_source_columns",
            "remove_source",
            "export_last_result",
            "save_result_as_source",
        }
        if self._operation_running() and action in operation_actions:
            return False
        if self.state.query_run.is_running and action in {
            "inspect_source",
            "sample_source",
            "profile_source",
            "show_source_columns",
        }:
            return False
        if isinstance(self.focused, TextArea):
            text_entry_actions = {
                "quit_from_non_editor",
                "delete_result",
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
        if action == "open_sql_completion" and not isinstance(self.focused, TextArea):
            return False
        history_actions = {"rerun_history", "reopen_history"}
        if action in history_actions and not self._is_focused("#history"):
            return False
        if action == "export_last_result":
            record = self.state.active_query_result_record()
            return (
                record is not None and record.state == "preserving"
            ) or self.state.active_result_capabilities().can_export_full
        if action == "save_result_as_source":
            return self.state.active_result_capabilities().can_save_as_source
        if action == "delete_result":
            return self._selected_result_sequence_for_delete() is not None
        return True

    def _app_action_blocked_by_modal(self, action: str) -> bool:
        return self._input_or_confirmation_screen_active() and action in _MODAL_BLOCKED_APP_ACTIONS

    def _refresh_sources_table(self) -> None:
        sources_table = self.query_one("#sources", DataTable)
        sources_table.clear(columns=True)
        sources_table.add_columns("alias", "kind", "origin", "path")
        for source in self.state.sources:
            sources_table.add_row(
                literal_terminal_text(source.name),
                literal_terminal_text(source.kind),
                literal_terminal_text(source.origin),
                literal_terminal_text(_display_path(source.path, self.start_dir)),
            )

        selected_row = self._selected_source_row_index()
        if selected_row is not None:
            sources_table.move_cursor(row=selected_row)
        elif self.state.sources:
            sources_table.move_cursor(row=0)

    def _refresh_pane_context(self) -> None:
        try:
            current_screen = self.screen
        except ScreenStackError:
            return
        if isinstance(current_screen, (_HelpScreen, _PromptInputScreen)):
            return
        try:
            active_pane = self._active_focus_pane()
            self.state.active_pane = active_pane
            self._update_static_text(
                "#sources-title", _pane_title("Sources", active_pane == "sources")
            )
            self._update_static_text(
                "#history-title", _pane_title("History", active_pane == "history")
            )
            self._update_static_text(
                "#sql-title", _pane_title("SQL editor", active_pane == "editor")
            )
            self._refresh_results_title(is_active=active_pane == "results")
            self._update_static_text("#context", _pane_context(active_pane))
            self.query_one(_OrderedFooter).refresh(recompose=True)
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
            row_index = self._append_history_row(item)
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
            row_index = self._append_history_row(item)
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

    def _set_status(self, message: str, *, already_safe: bool = False) -> None:
        self._update_static_text("#status", message, already_safe=already_safe)

    def _append_history_row(self, item: TUIQueryHistoryItem) -> int:
        history_table = self.query_one("#history", DataTable)
        row_index = history_table.row_count
        rows = "" if item.row_count is None else str(item.row_count)
        history_table.add_row(
            literal_terminal_text(item.sequence),
            literal_terminal_text(_run_mode_display(item.run_mode)),
            literal_terminal_text(item.status),
            literal_terminal_text(rows),
            literal_terminal_text(_one_line_sql(item.sql)),
        )
        return row_index

    def _append_latest_history_row_preserving_selection(self) -> None:
        if not self.state.query_history:
            return
        self._append_history_row(self.state.query_history[-1])

    def _update_static_text(
        self,
        selector: str,
        message: str,
        *,
        already_safe: bool = False,
    ) -> None:
        content = message if already_safe else terminal_safe_text(message)
        self.query_one(selector, Static).update(content)

    def _clear_result_grid(self) -> None:
        self.query_one("#results", DataTable).clear(columns=True)

    def _refresh_results_title(self, *, is_active: bool | None = None) -> None:
        if is_active is None:
            is_active = self._is_focused("#results")
        self._update_static_text(
            "#results-title", _results_title(self.state.active_result.label, is_active)
        )

    def _result_tabs_text(self) -> str:
        tabs = self.state.buffer_result_tabs
        if not tabs:
            return ""

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
        return "Buffer results ([ and ] in Results): " + " | ".join(entries)

    def _terminal_size_warning(self, *, width: int, height: int) -> str | None:
        if width < _MIN_TERMINAL_WIDTH or height < _MIN_TERMINAL_HEIGHT:
            return (
                "Terminal too small for full workbench; "
                f"use at least {_MIN_TERMINAL_WIDTH}x{_MIN_TERMINAL_HEIGHT}."
            )
        return None

    def _apply_terminal_size_warning(self, *, width: int, height: int) -> None:
        warning = self._terminal_size_warning(width=width, height=height)
        current_status = self.query_one("#status", Static).content
        if warning is not None:
            self._terminal_size_warning_active = True
            self._set_status(warning)
            return

        if not self._terminal_size_warning_active:
            return

        self._terminal_size_warning_active = False
        warning_message = (
            "Terminal too small for full workbench; "
            f"use at least {_MIN_TERMINAL_WIDTH}x{_MIN_TERMINAL_HEIGHT}."
        )
        if current_status == warning_message:
            self._set_status(self._status_message())

    def _refresh_result_tabs(self) -> None:
        self._update_static_text("#result-tabs", self._result_tabs_text())

    def _refresh_results_display(self) -> None:
        view = self.state.result_view
        if view.columns:
            populate_result_table(self.query_one("#results", DataTable), view)
        else:
            self._clear_result_grid()
        self._refresh_results_title()
        self._refresh_result_tabs()
        if view.columns or view.total_row_count:
            self._update_static_text(
                "#results-message",
                result_preview_message(view, record=self.state.active_query_result_record()),
            )

    def _show_output_text(self, message: str, *, already_safe: bool = False) -> None:
        self._clear_result_grid()
        self._update_static_text("#results-message", message, already_safe=already_safe)

    def _show_non_query_result_table(
        self,
        columns: tuple[str, ...],
        rows: Sequence[Sequence[object]],
        *,
        message: str,
    ) -> None:
        if self._reject_result_replacing_action_for_transient_preview():
            return
        self.state.clear_last_result()
        results_table = self.query_one("#results", DataTable)
        results_table.clear(columns=True)
        results_table.add_columns(*(literal_terminal_text(column) for column in columns))
        for row in rows:
            results_table.add_row(*(literal_terminal_text(value) for value in row))
        self._refresh_results_title()
        self._refresh_result_tabs()
        self._update_static_text("#results-message", message)

    def _show_source_columns_table(
        self,
        columns: tuple[TUISourceColumn, ...],
        *,
        message: str,
    ) -> None:
        self._show_non_query_result_table(
            ("column", "type"),
            tuple((column.name, column.duckdb_type) for column in columns),
            message=message,
        )

    def _show_source_inspect_table(
        self,
        result: InspectResult,
        columns: tuple[TUISourceColumn, ...],
    ) -> None:
        source = self.state.get_source(str(result.source["display_path"]))
        if result.row_count.exact and result.row_count.value is not None:
            row_count_status = str(result.row_count.value)
        else:
            row_count_status = result.row_count.mode.replace("_", " ")
        warning_text = "; ".join(result.warnings) if result.warnings else "none"
        rows: list[tuple[object, object]] = [
            ("source alias/table name", source.name),
            ("origin", source.origin),
            ("display path", _display_path(source.path, self.start_dir)),
            ("row-count status", row_count_status),
            ("column count", len(columns)),
            ("delimiter", result.dialect.delimiter or ""),
            ("quote", result.dialect.quote or ""),
            ("escape", result.dialect.escape or ""),
            ("header", "" if result.dialect.header is None else str(result.dialect.header)),
            ("encoding", result.dialect.encoding or ""),
            ("warnings", warning_text),
        ]
        rows.extend((f"column: {column.name}", column.duckdb_type) for column in columns)
        self._show_non_query_result_table(
            ("field", "value"),
            rows,
            message=f"Source inspect: {source.name}.",
        )

    def _show_source_profile_table(self, result: ProfileResult) -> None:
        self._show_non_query_result_table(
            ("column", "type", "non_null", "null", "null_%", "distinct", "min", "max"),
            tuple(
                (
                    column.name,
                    column.duckdb_type,
                    column.non_null_count,
                    column.null_count,
                    f"{column.null_percentage:.1f}",
                    column.distinct_count,
                    column.min,
                    column.max,
                )
                for column in result.columns
            ),
            message=f"Source profile: {result.source.get('display_path', 'source')}.",
        )

    def _show_error(self, error: CSVQLError) -> None:
        message = _error_message(error)
        self._set_status(message, already_safe=True)
        self._show_output_text(message, already_safe=True)

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
        if self.state.has_active_result:
            rejected_error = _with_previous_result_suggestion(error)

        if simple_message_without_previous and not self.state.has_active_result:
            message = rejected_error.message
            already_safe = False
        else:
            message = _error_message(rejected_error)
            already_safe = True

        self._set_status(message, already_safe=already_safe)
        self._update_static_text("#results-message", message, already_safe=already_safe)
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

    def _replace_sql_editor_text(self, start_index: int, end_index: int, replacement: str) -> None:
        sql = self.query_one("#sql", TextArea)
        before_text = sql.text
        updated_text = f"{before_text[:start_index]}{replacement}{before_text[end_index:]}"
        sql.load_text(updated_text)
        sql.move_cursor(_text_location_from_index(updated_text, start_index + len(replacement)))
        sql.focus()

    def _replace_sql_editor_selection(self, replacement: str) -> None:
        sql = self.query_one("#sql", TextArea)
        self._replace_sql_editor_text(
            _text_index_from_location(sql.text, sql.selection.start),
            _text_index_from_location(sql.text, sql.selection.end),
            replacement,
        )

    def _assist_sources(self) -> tuple[SQLAssistSource, ...]:
        columns_by_source = {
            source.name: self.state.source_columns(source.name) for source in self.state.sources
        }
        return build_assist_sources(self.state.sources, columns_by_source)

    def _handle_sql_template_selection(self, selection_key: str | None) -> None:
        if selection_key is None:
            return
        option = self._sql_assist_choices.get(selection_key)
        if not isinstance(option, SQLTemplateOption):
            return
        self._append_sql_text(option.sql)
        self._set_status(f"Inserted template: {option.label}.")

    def _handle_sql_completion_selection(self, selection_key: str | None) -> None:
        if selection_key is None:
            return
        item = self._sql_assist_choices.get(selection_key)
        if not isinstance(item, SQLCompletionItem):
            return
        sql = self.query_one("#sql", TextArea)
        edit = completion_edit(
            sql.text,
            _text_index_from_location(sql.text, sql.selection.start),
            _text_index_from_location(sql.text, sql.selection.end),
            item,
        )
        self._replace_sql_editor_text(edit.start_index, edit.end_index, edit.replacement)
        self._set_status(f"Inserted completion: {item.label}.")

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

    def _handle_pending_export_prompt(
        self,
        pending: _PendingExportPrompt,
        path_value: str | None,
    ) -> None:
        if self._pending_export_prompt is not pending:
            if path_value is not None:
                self._set_status("Export path prompt expired; no export was started.")
            return

        if path_value is None:
            self._pending_export_prompt = None
            self._set_status("Export path prompt cancelled.")
            self._continue_after_pending_export_prompt()
            return

        record = self._result_record_for_sequence(pending.result_sequence)
        expected_intent = pending.expected_existing_intent
        if expected_intent is not None:
            replacement_window_open = (
                record is not None
                and record.state == "preserving"
                and self.state.export_intent is expected_intent
                and self._attached_export_intent_in_flight is None
            )
            if not replacement_window_open:
                self._pending_export_prompt = None
                self._set_status(
                    "Export path prompt expired; kept the existing export destination."
                )
                self._continue_after_pending_export_prompt()
                return
        elif (
            self.state.export_intent is not None
            or self._attached_export_intent_in_flight is not None
        ):
            self._pending_export_prompt = None
            self._set_status("Export path prompt expired; no export was started.")
            self._continue_after_pending_export_prompt()
            return

        try:
            export_path_value, export_format = _export_path_and_format_for_prompt(path_value)
            intent = build_tui_export_intent(
                result_sequence=pending.result_sequence,
                path_value=export_path_value,
                export_format=export_format,
                base_dir=self.start_dir,
            )
        except CSVQLError as exc:
            self._pending_export_prompt = None
            self._show_error(exc)
            self._continue_after_pending_export_prompt()
            return

        if record is not None and record.state == "preserving":
            try:
                replacement = self.state.attach_export_intent(intent)
            except RuntimeError as exc:
                self._pending_export_prompt = None
                self._show_error(CSVQLError(str(exc)))
                self._continue_after_pending_export_prompt()
                return
            self._pending_export_prompt = None
            if replacement is None:
                if expected_intent is not None:
                    self._show_error(CSVQLError("Export intent changed while the prompt was open."))
                    return
                self._set_status(
                    f"Attached export for query {pending.result_sequence}: "
                    f"{_display_path(intent.destination, self.start_dir)}."
                )
                return
            if replacement.existing is not expected_intent:
                self._show_error(CSVQLError("Export intent changed while the prompt was open."))
                return
            self._confirm_export_intent_replacement(replacement)
            return

        if record is not None and record.state == "complete" and record.handle is not None:
            self._pending_export_prompt = None
            if self._operation_running():
                self._show_error(
                    CSVQLError(
                        "Unable to schedule the attached export.",
                        suggestion="The queued run will continue without exporting.",
                    )
                )
                self._continue_after_pending_export_prompt()
                return
            self._start_attached_export(intent, record)
            if self._attached_export_intent_in_flight is intent:
                return
            self._show_error(
                CSVQLError(
                    "Unable to schedule the attached export.",
                    suggestion="The queued run will continue without exporting.",
                )
            )
            self._continue_after_pending_export_prompt()
            return

        self._pending_export_prompt = None
        self._show_error(
            CSVQLError(
                f"Export for query {pending.result_sequence} was not started.",
                suggestion="Preservation did not produce a complete result.",
            )
        )
        self._continue_after_pending_export_prompt()

    def _continue_after_pending_export_prompt(self) -> None:
        if (
            self.state.query_run.is_running
            or self.state.export_intent is not None
            or self._attached_export_intent_in_flight is not None
        ):
            return
        if self._continue_after_query_worker_terminalized():
            return
        self._update_static_text("#run-status", "Ready.")
        self.query_one("#sql", TextArea).focus()

    def _dismiss_pending_export_prompt(self) -> None:
        try:
            screen = self.screen
            if not isinstance(screen, _PromptInputScreen):
                return
            screen.query_one("#export-path", Input)
            screen.dismiss(None)
        except (NoMatches, ScreenStackError):
            return

    def _handle_export_last_result(
        self,
        path_value: str | None,
        *,
        result_sequence: int | None = None,
    ) -> None:
        if path_value is None:
            return

        if result_sequence is None:
            result_sequence = self.state.active_result.sequence
        if result_sequence is None:
            self._show_error(CSVQLError("Run a query before exporting."))
            return
        record = self._result_record_for_sequence(result_sequence)

        try:
            export_path_value, export_format = _export_path_and_format_for_prompt(path_value)
            if record is not None and record.state == "preserving":
                intent = build_tui_export_intent(
                    result_sequence=result_sequence,
                    path_value=export_path_value,
                    export_format=export_format,
                    base_dir=self.start_dir,
                )
                replacement = self.state.attach_export_intent(intent)
                if replacement is None:
                    self._set_status(
                        f"Attached export for query {result_sequence}: "
                        f"{_display_path(intent.destination, self.start_dir)}."
                    )
                    return
                self._confirm_export_intent_replacement(replacement)
                return

            if record is None or record.state != "complete" or record.handle is None:
                if self._show_active_result_unavailable():
                    return
                self._show_error(CSVQLError("Run a query before exporting."))
                return
            handle = record.handle
            if not self.call_after_refresh(
                lambda: self._start_operation_worker(
                    kind="export",
                    label="Exporting active result",
                    result_sequence=handle.sequence,
                    work=lambda operation: _ExportOutcome(
                        path=export_last_result(
                            self._result_store,
                            handle,
                            export_path_value,
                            columns=record.columns,
                            elapsed_ms=record.elapsed_ms,
                            export_format=export_format,
                            base_dir=self.start_dir,
                            force=False,
                            token=operation.token,
                        )
                    ),
                )
            ):
                self._show_error(
                    CSVQLError(
                        "Unable to schedule export.",
                        suggestion="Try exporting the active result again.",
                    )
                )
        except CSVQLError as exc:
            self._show_error(exc)
            return

    def _confirm_export_intent_replacement(
        self,
        replacement: TUIExportIntentReplacement,
    ) -> None:
        prompt = (
            "Replace attached export "
            f"{replacement.existing.destination} with {replacement.proposed.destination}? "
            "Press y to replace or n to keep the existing destination."
        )
        self.push_screen(
            _ConfirmationScreen(prompt),
            callback=lambda confirmed: self._handle_export_intent_replacement(
                replacement,
                confirmed,
            ),
        )

    def _handle_export_intent_replacement(
        self,
        replacement: TUIExportIntentReplacement,
        confirmed: bool | None,
    ) -> None:
        if not confirmed:
            self._set_status(
                f"Attached export replacement cancelled; kept {replacement.existing.destination}."
            )
            return
        if self._attached_export_intent_in_flight is replacement.existing:
            self._set_status(
                f"Attached export already started; kept {replacement.existing.destination}."
            )
            return
        try:
            self.state.replace_export_intent(replacement)
        except RuntimeError as exc:
            self._show_error(CSVQLError(str(exc)))
            return
        self._set_status(f"Attached export updated to {replacement.proposed.destination}.")

    def _handle_save_sources_confirmation(self, confirmed: bool | None) -> None:
        if not confirmed:
            self._set_status("Source catalog save cancelled.")
            self.query_one("#sources", DataTable).focus()
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

        display_path = _display_path(context.config_path, self.start_dir)
        self._set_status(f"Saved sources to {display_path}.")
        self._update_static_text("#results-message", f"Saved sources to {display_path}.")
        self.query_one("#sources", DataTable).focus()

    def _handle_save_result_as_source(
        self,
        alias: str | None,
        *,
        result_sequence: int,
        expected_handle: TUIResultHandle,
    ) -> None:
        if alias is None:
            return

        record = self._result_record_for_sequence(result_sequence)
        if (
            record is None
            or record.state != "complete"
            or record.handle is None
            or record.handle != expected_handle
        ):
            if self._show_active_result_unavailable():
                return
            self._show_error(CSVQLError("The selected preserved result is no longer available."))
            return

        if any(source.name.casefold() == alias.casefold() for source in self.state.sources):
            self._show_error(
                CSVQLError(
                    f"Source alias '{alias}' is already loaded in the TUI session.",
                    suggestion="Choose a unique alias for the derived result source.",
                )
            )
            return

        handle = record.handle
        try:
            if not self.call_after_refresh(
                lambda: self._start_operation_worker(
                    kind="save_result",
                    label="Saving active result as source",
                    result_sequence=handle.sequence,
                    work=lambda operation: _SaveResultSourceOutcome(
                        source=save_derived_result_source(
                            self._result_store,
                            handle,
                            alias,
                            columns=record.columns,
                            elapsed_ms=record.elapsed_ms,
                            existing_sources=self.state.sources,
                            start_dir=self.start_dir,
                            token=operation.token,
                        )
                    ),
                )
            ):
                self._show_error(
                    CSVQLError(
                        "Unable to schedule save-result export.",
                        suggestion="Try saving the active result again.",
                    )
                )
        except CSVQLError as exc:
            self._show_error(exc)
            return

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

    def _selected_result_sequence_for_delete(self) -> int | None:
        if self._is_focused("#history"):
            sequence = self._selected_history_sequence()
        elif self._is_focused("#results"):
            sequence = self.state.active_result.sequence
        else:
            return None
        if sequence is None:
            return None
        record = self._result_record_for_sequence(sequence)
        if record is None or record.state not in {"complete", "preview_only"}:
            return None
        return sequence

    def _result_record_for_sequence(
        self,
        sequence: int | None,
    ) -> TUIResultRecord | None:
        if sequence is None:
            return None
        if self.state.active_result.sequence == sequence:
            active_record = self.state.active_query_result_record()
            if active_record is not None:
                return active_record
        return self.state.query_result_record(sequence)

    def _show_active_result_unavailable(self) -> bool:
        record = self.state.active_query_result_record()
        if record is not None and record.state == "preview_only":
            message = result_preview_message(self.state.result_view, record=record)
            self._set_status(message)
            self._update_static_text("#results-message", message)
            return True
        item = self._selected_history_item()
        if item is None or item.status != "success":
            return False
        if self.state.query_result_record(item.sequence) is not None:
            return False
        message = _FULL_RESULT_UNAVAILABLE_MESSAGE
        self._set_status(message)
        self._update_static_text("#results-message", message)
        return True

    def _load_record_preview(
        self,
        record: TUIResultRecord,
    ) -> TUIResultViewState | None:
        handle = record.handle
        if handle is None:
            if self.state.active_result.sequence is not None and self.state.result_view.columns:
                return self.state.result_view
            return None
        try:
            preview = self._result_store.load_preview(handle, self._preview_policy)
        except TUIResultStorageError as exc:
            invalidated_sequences = tuple(sorted({handle.sequence, *exc.invalidated_sequences}))
            self.state.mark_results_unavailable(
                invalidated_sequences,
                _FULL_RESULT_UNAVAILABLE_MESSAGE,
            )
            self._set_status(_FULL_RESULT_UNAVAILABLE_MESSAGE)
            self._update_static_text("#results-message", _FULL_RESULT_UNAVAILABLE_MESSAGE)
            return None
        return make_bounded_result_view_state(
            preview,
            source_result_sequence=handle.sequence,
        )

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
        transient_sequence = self._active_transient_preview_only_sequence()
        if transient_sequence is not None and item.sequence != transient_sequence:
            self._set_status(self._paused_preview_status_message(transient_sequence))
            return
        if item.status == "success":
            if not self.state.restore_query_result(item.sequence):
                self._set_status(_FULL_RESULT_UNAVAILABLE_MESSAGE)
                self._update_static_text("#results-message", _FULL_RESULT_UNAVAILABLE_MESSAGE)
                return
            record = self.state.query_result_record(item.sequence)
            assert record is not None
            view = self._load_record_preview(record)
            if view is None:
                return
            self.state.result_view = view
            populate_result_table(self.query_one("#results", DataTable), view)
            self._refresh_results_title()
            self._refresh_result_tabs()
            message = (
                f"History query {item.sequence}. {result_preview_message(view, record=record)}"
            )
            status = f"Showing query {item.sequence} result from History."
            self._update_static_text("#results-message", message)
            self._set_status(status)
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
        self._update_static_text("#results-message", message)
        self._set_status(message)

    def _is_focused(self, selector: str) -> bool:
        try:
            return self.focused is self.query_one(selector)
        except (NoMatches, ScreenStackError):
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
        if self._reject_result_replacing_action_for_transient_preview(
            allowed_sequence=tab.sequence
        ):
            return
        if not self.state.select_buffer_result(tab.sequence):
            return

        record = self.state.query_result_record(tab.sequence)
        if record is None:
            return
        view = self._load_record_preview(record)
        if view is None:
            return
        self.state.result_view = view
        populate_result_table(self.query_one("#results", DataTable), view)
        self._refresh_results_title()
        self._refresh_result_tabs()
        self._update_static_text(
            "#results-message",
            (
                f"Buffer result {tab.sequence}.{tab.index}. "
                f"{result_preview_message(view, record=record)}"
            ),
        )
        self._set_status(f"Showing buffer result {tab.sequence}.{tab.index}.")

    def _handle_empty_buffer_outcome(self, worker: Worker[object]) -> None:
        sequence = self._sequence_from_worker(worker)
        if sequence is None or not self.state.is_current_query_sequence(sequence):
            return

        self._clear_remaining_request_metadata()
        self.state.clear_last_result()
        self.state.finish_query_run()
        self.state.set_buffer_result_tabs(tuple(), selected_sequence=None)
        self._clear_result_grid()
        self._refresh_results_title()
        self._refresh_result_tabs()
        message = "Run Buffer returned no tabular result."
        self._set_status(message)
        self._update_static_text("#results-message", message)
        self._update_static_text("#run-status", "Ready.")
        self.query_one("#sql", TextArea).focus()

    def _handle_query_event(self, event: TUIQueryEvent) -> None:
        if (
            self._query_terminal_event_sequence is not None
            or not self.state.is_current_query_sequence(event.sequence)
        ):
            return
        if isinstance(event, TUIPreviewReadyEvent):
            self._handle_preview_ready_event(event)
            return
        if isinstance(event, TUIPreservationProgressEvent):
            self._handle_preservation_progress_event(event)
            return
        if isinstance(event, TUICompleteEvent):
            self._handle_complete_event(event)
            if self._is_last_sequence_in_request(event.sequence):
                self._query_terminal_event_sequence = event.sequence
            return
        if isinstance(event, TUIPreviewOnlyEvent):
            self._handle_preview_only_event(event)
            self._query_terminal_event_sequence = event.sequence
            return
        if isinstance(event, TUINoResultEvent):
            self._handle_no_result_event(event)
            if self._is_last_sequence_in_request(event.sequence):
                self._query_terminal_event_sequence = event.sequence
            return
        if isinstance(event, TUICancelledBeforePreviewEvent):
            self._handle_cancelled_before_preview_event(event)
            self._query_terminal_event_sequence = event.sequence
            return
        self._handle_failed_before_preview_event(event)
        self._query_terminal_event_sequence = event.sequence

    def _handle_preview_ready_event(self, event: TUIPreviewReadyEvent) -> None:
        if not self.state.is_current_query_sequence(event.sequence):
            return
        run_mode = self._active_query_run_modes.get(event.sequence, "current")
        buffer_result_index = None
        if run_mode == "buffer":
            buffer_result_index = self._begin_buffer_result_lifecycle(event.sequence)
        view = make_bounded_result_view_state(
            event.preview,
            source_result_sequence=event.sequence,
        )
        record = TUIResultRecord(
            handle=None,
            state="preserving",
            reason=None,
            columns=view.columns,
            preview_row_count=len(view.display_rows),
            full_row_count=None,
            elapsed_ms=event.preview.elapsed_ms,
        )
        self.state.set_active_result_record(
            event.sequence,
            record,
            run_mode=run_mode,
            buffer_result_index=buffer_result_index,
            result_view=view,
        )
        self._active_query_records[event.sequence] = record
        populate_result_table(self.query_one("#results", DataTable), view)
        self._refresh_results_title()
        self._refresh_result_tabs()
        self._update_static_text("#results-message", result_preview_message(view, record=record))
        self._set_status(result_preview_message(view, record=record))
        self.query_one("#sql", TextArea).focus()

    def _handle_preservation_progress_event(self, event: TUIPreservationProgressEvent) -> None:
        if not self.state.is_current_query_sequence(event.sequence):
            return
        progress = event.progress
        message = (
            f"Preserving query {event.sequence}: "
            f"{progress.rows_written:,} rows, "
            f"{progress.logical_bytes_written:,} logical bytes, "
            f"{progress.elapsed_ms:.1f} ms elapsed, "
            f"{progress.remaining_capacity_bytes:,} bytes remaining."
        )
        self._set_status(message)
        self._update_static_text("#run-status", message)

    def _handle_complete_event(self, event: TUICompleteEvent) -> None:
        if not self.state.is_current_query_sequence(event.sequence):
            return
        run_mode = self._active_query_run_modes.get(event.sequence, "current")
        buffer_result_index = self._buffer_result_index(event.sequence)
        preserve_active_result = self._preserve_unrelated_active_result(event.sequence)
        metadata = self._take_preserving_metadata(
            event.sequence,
            expected_columns=event.stored.columns,
        )
        if metadata is None:
            self._record_terminal_metadata_failure(
                event.sequence,
                run_mode=run_mode,
                sql=self._active_query_sql.pop(event.sequence, "<unknown>"),
            )
            return
        view = None
        preview_row_count = metadata.preview_row_count
        if not preserve_active_result:
            view = self._terminal_result_view(
                sequence=event.sequence,
                record_columns=event.stored.columns,
                handle=event.stored.handle,
            )
            preview_row_count = len(view.display_rows)
        record = transition_result_record(
            metadata,
            state="complete",
            handle=event.stored.handle,
            full_row_count=event.stored.stored_row_count,
            elapsed_ms=event.stored.elapsed_ms,
            preview_row_count=preview_row_count,
        )
        sql = self._active_query_sql.pop(event.sequence, "<unknown>")
        self.state.record_query_result(
            event.sequence,
            sql,
            record=record,
            result_view=view,
            run_mode=run_mode,
            buffer_result_index=buffer_result_index,
            complete_run=False,
            activate_result=not preserve_active_result,
        )
        self._active_query_run_modes.pop(event.sequence, None)
        if preserve_active_result:
            self._append_latest_history_row_preserving_selection()
        else:
            self._refresh_history_table()
        if not preserve_active_result:
            self._refresh_results_display()
            status_message = (
                f"{event.stored.stored_row_count:,} returned row(s) "
                f"in {event.stored.elapsed_ms:.1f} ms."
            )
            self._set_status(status_message)
        else:
            self._set_status(
                f"Query {event.sequence} completed in the background: "
                f"{event.stored.stored_row_count:,} row(s) preserved for later recall."
            )
        if not self.state.query_run.is_running:
            self._update_static_text("#run-status", "Ready.")
            self.query_one("#sql", TextArea).focus()

    def _handle_preview_only_event(self, event: TUIPreviewOnlyEvent) -> None:
        if not self.state.is_current_query_sequence(event.sequence):
            return
        run_mode = self._active_query_run_modes.pop(event.sequence, "current")
        self._clear_remaining_request_metadata(excluding=(event.sequence,))
        buffer_result_index = (
            self._ensure_buffer_tab(event.sequence) if run_mode == "buffer" else None
        )
        preserve_active_result = (
            self._preserve_unrelated_active_result(event.sequence) and event.stored is not None
        )
        metadata = self._take_preserving_metadata(
            event.sequence,
            expected_columns=event.preview.columns,
            expected_preview_row_count=len(event.preview.rows),
        )
        if metadata is None:
            self._record_terminal_metadata_failure(
                event.sequence,
                run_mode=run_mode,
                sql=self._active_query_sql.pop(event.sequence, "<unknown>"),
            )
            return
        sql = self._active_query_sql.pop(event.sequence, "<unknown>")
        view = None
        if not preserve_active_result:
            view = make_bounded_result_view_state(
                event.preview,
                source_result_sequence=event.sequence,
            )
        record = transition_result_record(
            metadata,
            state="preview_only",
            handle=None if event.stored is None else event.stored.handle,
            reason=event.reason,
            elapsed_ms=event.preview.elapsed_ms,
        )
        self.state.record_query_result(
            event.sequence,
            sql,
            record=record,
            result_view=view,
            run_mode=run_mode,
            buffer_result_index=buffer_result_index,
            complete_run=False,
            activate_result=not preserve_active_result,
        )
        if not preserve_active_result:
            assert view is not None
            populate_result_table(self.query_one("#results", DataTable), view)
            self._refresh_results_display()
            self._set_status(
                _status_with_terminal_warnings(
                    result_preview_message(view, record=record),
                    primary_error_message=event.primary_error_message,
                    primary_suggestion=event.primary_suggestion,
                    persistence_error_message=event.persistence_error_message,
                    persistence_suggestion=event.persistence_suggestion,
                    cleanup_notes=event.cleanup_notes,
                )
            )
        else:
            self._set_status(
                _status_with_terminal_warnings(
                    f"Query {event.sequence} finished with a retained preview only.",
                    primary_error_message=event.primary_error_message,
                    primary_suggestion=event.primary_suggestion,
                    persistence_error_message=event.persistence_error_message,
                    persistence_suggestion=event.persistence_suggestion,
                    cleanup_notes=event.cleanup_notes,
                )
            )
        if preserve_active_result:
            self._append_latest_history_row_preserving_selection()
        else:
            if event.stored is None:
                self._refresh_history_table_selecting(event.sequence)
            else:
                self._refresh_history_table()
        if event.stored is None and not preserve_active_result:
            self._transient_preview_only_result = _TransientPreviewOnlyResult(
                sequence=event.sequence,
                preview=event.preview,
                reason=event.reason,
                primary_error_message=event.primary_error_message,
                primary_suggestion=event.primary_suggestion,
                persistence_error_message=event.persistence_error_message,
                persistence_suggestion=event.persistence_suggestion,
                cleanup_notes=event.cleanup_notes,
            )
        else:
            self._clear_transient_preview_only(event.sequence)
        self._update_static_text("#run-status", "Finalizing query...")
        self.query_one("#sql", TextArea).focus()

    def _reject_result_replacing_action_for_transient_preview(
        self,
        *,
        allowed_sequence: int | None = None,
    ) -> bool:
        sequence = self._active_transient_preview_only_sequence()
        if sequence is None or sequence == allowed_sequence:
            return False
        self._set_status(self._paused_preview_status_message(sequence))
        return True

    def _clear_last_result_unless_transient_preview_active(self) -> None:
        if self._active_transient_preview_only_sequence() is not None:
            return
        self.state.clear_last_result()

    def _active_transient_preview_only_sequence(self) -> int | None:
        sequence = self.state.active_result.sequence
        record = self.state.active_query_result_record()
        transient = self._transient_preview_only_result
        if (
            sequence is None
            or record is None
            or record.state != "preview_only"
            or record.handle is not None
            or transient is None
            or transient.sequence != sequence
        ):
            return None
        return sequence

    def _active_transient_preview_pause_message(self) -> str | None:
        sequence = self._active_transient_preview_only_sequence()
        if sequence is None:
            return None
        return self._paused_preview_status_message(sequence)

    def _paused_preview_only_sequence(self) -> int | None:
        sequence = self._active_transient_preview_only_sequence()
        if sequence is None or self.state.queued_run is None:
            return None
        return sequence

    def _retry_paused_preview_persistence(self) -> bool:
        sequence = self._active_transient_preview_only_sequence()
        if sequence is None:
            return False
        record = self.state.active_query_result_record()
        transient = self._transient_preview_only_result
        preview = None if transient is None or transient.sequence != sequence else transient.preview
        if record is None or record.reason is None or preview is None:
            return False
        try:
            stored = self._result_store.persist_preview(
                sequence=sequence,
                preview=preview,
                reason=record.reason,
                elapsed_ms=preview.elapsed_ms,
            )
        except BaseException as exc:
            self._record_transient_preview_persistence_failure(sequence, exc)
            self._set_status(self._paused_preview_status_message(sequence))
            return False
        if stored is None:
            self._set_status(self._paused_preview_status_message(sequence))
            return False
        self._clear_transient_preview_only(sequence)
        updated_record = self.state.bind_preview_only_result_handle(sequence, handle=stored.handle)
        self._refresh_history_table()
        self._refresh_results_display()
        self._refresh_pane_context()
        if not self._continue_after_query_worker_terminalized():
            self._set_status(result_preview_message(self.state.result_view, record=updated_record))
        return True

    def _offer_paused_preview_retry(self, deleted_sequence: int) -> bool:
        paused_sequence = self._active_transient_preview_only_sequence()
        if paused_sequence is None or paused_sequence == deleted_sequence:
            return False
        self.push_screen(
            _ConfirmationScreen(
                f"Retry preview preservation for query {paused_sequence} now that result "
                f"{deleted_sequence} was deleted? Press y to retry or n to keep "
                "the preview in memory."
            ),
            callback=lambda confirmed: self._handle_paused_preview_retry_confirmation(
                paused_sequence,
                confirmed,
            ),
        )
        return True

    def _handle_paused_preview_retry_confirmation(
        self,
        sequence: int,
        confirmed: bool | None,
    ) -> None:
        if self._active_transient_preview_only_sequence() != sequence:
            self._show_error(CSVQLError("The paused preview is no longer available."))
            return
        if not confirmed:
            self._set_status(self._paused_preview_status_message(sequence))
            return
        if not self._retry_paused_preview_persistence():
            self._set_status(self._paused_preview_status_message(sequence))

    def _clear_transient_preview_only(self, sequence: int) -> None:
        transient = self._transient_preview_only_result
        if transient is not None and transient.sequence == sequence:
            self._transient_preview_only_result = None

    def _paused_preview_status_message(self, sequence: int) -> str:
        transient = self._transient_preview_only_result
        if transient is None or transient.sequence != sequence:
            return _non_durable_preview_pause_message(sequence, reason="session_spool_limit")
        return _status_with_terminal_warnings(
            _non_durable_preview_pause_message(sequence, reason=transient.reason),
            primary_error_message=transient.primary_error_message,
            primary_suggestion=transient.primary_suggestion,
            persistence_error_message=transient.persistence_error_message,
            persistence_suggestion=transient.persistence_suggestion,
            cleanup_notes=transient.cleanup_notes,
        )

    def _record_transient_preview_persistence_failure(
        self,
        sequence: int,
        error: BaseException,
    ) -> None:
        transient = self._transient_preview_only_result
        if transient is None or transient.sequence != sequence:
            return
        message, suggestion = _public_persistence_failure(error)
        self._transient_preview_only_result = _TransientPreviewOnlyResult(
            sequence=transient.sequence,
            preview=transient.preview,
            reason=transient.reason,
            primary_error_message=transient.primary_error_message,
            primary_suggestion=transient.primary_suggestion,
            persistence_error_message=message,
            persistence_suggestion=suggestion,
            cleanup_notes=_merge_cleanup_notes(
                transient.cleanup_notes,
                _sanitize_cleanup_notes(getattr(error, "__notes__", ())),
            ),
        )

    def _handle_no_result_event(self, event: TUINoResultEvent) -> None:
        if not self.state.is_current_query_sequence(event.sequence):
            return
        run_mode = self._active_query_run_modes.pop(event.sequence, "current")
        sql = self._active_query_sql.pop(event.sequence, "<unknown>")
        preserve_active_result = self._preserve_unrelated_active_result(event.sequence)
        self._active_query_records.pop(event.sequence, None)
        previous_tabs = self.state.buffer_result_tabs if run_mode == "buffer" else ()
        previous_sequence = self.state.active_result.sequence if run_mode == "buffer" else None
        self.state.record_query_no_result(
            event.sequence,
            sql,
            event.elapsed_ms,
            run_mode=run_mode,
            complete_run=False,
            preserve_active_result=preserve_active_result,
        )
        if preserve_active_result:
            self._append_latest_history_row_preserving_selection()
        elif run_mode == "buffer" and previous_tabs:
            self._restore_previous_buffer_selection(previous_tabs, previous_sequence)
        else:
            self._clear_result_grid()
            self._refresh_results_title()
            self._refresh_result_tabs()
        status_message = "Statement completed; no tabular result to display."
        self._set_status(status_message)
        if not preserve_active_result:
            self._update_static_text(
                "#results-message", "Statement completed; no tabular result to display."
            )
        if not self.state.query_run.is_running:
            self._update_static_text("#run-status", "Ready.")
            self.query_one("#sql", TextArea).focus()

    def _handle_cancelled_before_preview_event(
        self,
        event: TUICancelledBeforePreviewEvent,
    ) -> None:
        if not self.state.is_current_query_sequence(event.sequence):
            return
        run_mode = self._active_query_run_modes.pop(event.sequence, "current")
        sql = self._active_query_sql.pop(event.sequence, "<unknown>")
        self._clear_remaining_request_metadata(excluding=(event.sequence,))
        preserve_active_result = self._preserve_unrelated_active_result(event.sequence)
        self._active_query_records.pop(event.sequence, None)
        previous_tabs = self.state.buffer_result_tabs if run_mode == "buffer" else ()
        previous_sequence = self.state.active_result.sequence if run_mode == "buffer" else None
        self.state.record_query_cancelled(
            event.sequence,
            sql,
            run_mode=run_mode,
            complete_run=False,
            preserve_active_result=preserve_active_result,
        )
        if preserve_active_result:
            self._append_latest_history_row_preserving_selection()
        elif run_mode == "buffer" and previous_tabs:
            self._restore_previous_buffer_selection(previous_tabs, previous_sequence)
        else:
            self._clear_result_grid()
            self._refresh_results_title()
            self._refresh_result_tabs()
        message = f"Query {event.sequence} was cancelled before a preview was retained."
        self._set_status(
            _status_with_terminal_warnings(
                message,
                primary_error_message=None,
                primary_suggestion=None,
                persistence_error_message=None,
                persistence_suggestion=None,
                cleanup_notes=event.cleanup_notes,
            )
        )
        if not preserve_active_result:
            self._update_static_text("#results-message", message)
        self._update_static_text("#run-status", "Finalizing query...")
        self.query_one("#sql", TextArea).focus()

    def _handle_failed_before_preview_event(
        self,
        event: TUIFailedBeforePreviewEvent,
    ) -> None:
        if not self.state.is_current_query_sequence(event.sequence):
            return
        run_mode = self._active_query_run_modes.pop(event.sequence, "current")
        sql = self._active_query_sql.pop(event.sequence, "<unknown>")
        self._clear_remaining_request_metadata(excluding=(event.sequence,))
        preserve_active_result = self._preserve_unrelated_active_result(event.sequence)
        self._active_query_records.pop(event.sequence, None)
        previous_tabs = self.state.buffer_result_tabs if run_mode == "buffer" else ()
        previous_sequence = self.state.active_result.sequence if run_mode == "buffer" else None
        self.state.record_query_failed(
            event.sequence,
            sql,
            event.error_message,
            run_mode=run_mode,
            complete_run=False,
            preserve_active_result=preserve_active_result,
        )
        if preserve_active_result:
            self._append_latest_history_row_preserving_selection()
        elif run_mode == "buffer" and previous_tabs:
            self._restore_previous_buffer_selection(previous_tabs, previous_sequence)
        else:
            self._clear_result_grid()
            self._refresh_results_title()
            self._refresh_result_tabs()
        self._update_static_text("#run-status", "Finalizing query...")
        if preserve_active_result:
            self._set_status(
                _status_with_cleanup_notes(
                    _error_message(CSVQLError(event.error_message, suggestion=event.suggestion)),
                    event.cleanup_notes,
                ),
                already_safe=True,
            )
        else:
            self._show_error(CSVQLError(event.error_message, suggestion=event.suggestion))
            if event.cleanup_notes:
                self._set_status(
                    _status_with_terminal_warnings(
                        _error_message(
                            CSVQLError(event.error_message, suggestion=event.suggestion)
                        ),
                        primary_error_message=None,
                        primary_suggestion=None,
                        persistence_error_message=None,
                        persistence_suggestion=None,
                        cleanup_notes=event.cleanup_notes,
                    ),
                    already_safe=True,
                )
        self.query_one("#sql", TextArea).focus()

    def _handle_query_worker_failure(
        self,
        worker: Worker[object],
        error: BaseException | None,
    ) -> None:
        del error
        sequence = self._failure_sequence_from_worker(worker)
        if sequence is None or not self.state.is_current_query_sequence(sequence):
            return

        sql = self._active_query_sql.pop(sequence, "<unknown>")
        run_mode = self._active_query_run_modes.pop(sequence, "current")
        self._clear_remaining_request_metadata(excluding=(sequence,))
        error_message = _UNEXPECTED_QUERY_WORKER_FAILURE_MESSAGE
        active_record = (
            self.state.active_query_result_record()
            if self.state.active_result.sequence == sequence
            else None
        )
        preserve_active_result = self._preserve_unrelated_active_result(sequence)
        self._active_query_records.pop(sequence, None)

        if active_record is not None and active_record.state == "preserving":
            preview_only_record = TUIResultRecord(
                handle=None,
                state="preview_only",
                reason="preservation_failed",
                columns=active_record.columns,
                preview_row_count=active_record.preview_row_count,
                full_row_count=None,
                elapsed_ms=active_record.elapsed_ms,
            )
            self.state.record_query_result(
                sequence,
                sql,
                record=preview_only_record,
                result_view=self.state.result_view,
                run_mode=run_mode,
                buffer_result_index=self._buffer_result_index(sequence),
                complete_run=True,
            )
            self._refresh_history_table_selecting(sequence)
            self._refresh_results_display()
            self._update_static_text("#run-status", "Ready.")
            self._set_status(
                result_preview_message(self.state.result_view, record=preview_only_record)
            )
            self.query_one("#sql", TextArea).focus()
            return

        self.state.record_query_error(
            sequence,
            sql,
            error_message,
            run_mode=run_mode,
            preserve_active_result=preserve_active_result,
        )
        if preserve_active_result:
            self._append_latest_history_row_preserving_selection()
        else:
            self._refresh_history_table()
        self._update_static_text("#run-status", "Ready.")
        if preserve_active_result:
            self._set_status(_error_message(CSVQLError(error_message)), already_safe=True)
        else:
            self._clear_result_grid()
            self._refresh_results_title()
            self._refresh_result_tabs()
            self._show_error(CSVQLError(error_message))
        self.query_one("#sql", TextArea).focus()

    def _preserve_unrelated_active_result(self, sequence: int) -> bool:
        active_sequence = self.state.active_result.sequence
        return (
            self.state.active_result.kind in {"history", "buffer"}
            and active_sequence is not None
            and active_sequence != sequence
        )

    def _take_preserving_metadata(
        self,
        sequence: int,
        *,
        expected_columns: tuple[str, ...],
        expected_preview_row_count: int | None = None,
    ) -> TUIResultRecord | None:
        metadata = self._active_query_records.pop(sequence, None)
        if metadata is None and self.state.active_result.sequence == sequence:
            metadata = self.state.active_query_result_record()
        if (
            metadata is None
            or metadata.state != "preserving"
            or metadata.columns != expected_columns
            or (
                expected_preview_row_count is not None
                and metadata.preview_row_count != expected_preview_row_count
            )
        ):
            return None
        return metadata

    def _record_terminal_metadata_failure(
        self,
        sequence: int,
        *,
        run_mode: TUIQueryRunMode,
        sql: str,
    ) -> None:
        preserve_active_result = self._preserve_unrelated_active_result(sequence)
        message = _UNEXPECTED_QUERY_WORKER_FAILURE_MESSAGE
        self.state.record_query_error(
            sequence,
            sql,
            message,
            run_mode=run_mode,
            complete_run=False,
            preserve_active_result=preserve_active_result,
        )
        self._active_query_run_modes.pop(sequence, None)
        if preserve_active_result:
            self._append_latest_history_row_preserving_selection()
        else:
            self._refresh_history_table()
        self._update_static_text("#run-status", "Finalizing query...")
        if preserve_active_result:
            self._set_status(_error_message(CSVQLError(message)), already_safe=True)
        else:
            self._clear_result_grid()
            self._refresh_results_title()
            self._refresh_result_tabs()
            self._show_error(CSVQLError(message))
        self.query_one("#sql", TextArea).focus()

    def _terminal_result_view(
        self,
        *,
        sequence: int,
        record_columns: tuple[str, ...],
        handle: TUIResultHandle,
    ) -> TUIResultViewState:
        active_record = (
            self.state.active_query_result_record()
            if self.state.active_result.sequence == sequence
            else None
        )
        active_view = self.state.result_view
        if (
            active_record is not None
            and active_record.state == "preserving"
            and active_view.source_result_sequence == sequence
            and active_view.columns == record_columns
        ):
            return active_view
        preview = self._result_store.load_preview(handle, self._preview_policy)
        return make_bounded_result_view_state(
            preview,
            source_result_sequence=handle.sequence,
        )

    def _clear_remaining_request_metadata(self, *, excluding: Sequence[int] = ()) -> None:
        request = self.state.query_run.request
        if request is None:
            return
        excluded = set(excluding)
        for sequence in request.sequences:
            if sequence in excluded:
                continue
            self._active_query_sql.pop(sequence, None)
            self._active_query_run_modes.pop(sequence, None)
            self._active_query_records.pop(sequence, None)

    def _failure_sequence_from_worker(self, worker: Worker[object]) -> int | None:
        request = self.state.query_run.request
        if request is None:
            return self._sequence_from_worker(worker)

        active_sequence = self.state.active_result.sequence
        active_record = self.state.active_query_result_record()
        if (
            active_sequence in request.sequences
            and active_record is not None
            and active_record.state in {"executing", "preserving"}
        ):
            return active_sequence

        pending_sequences = tuple(
            sequence
            for sequence in request.sequences
            if sequence in self._active_query_sql or sequence in self._active_query_run_modes
        )
        if pending_sequences:
            return pending_sequences[0]

        worker_sequence = self._sequence_from_worker(worker)
        if worker_sequence in request.sequences:
            return worker_sequence
        return request.sequences[0]

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


class _SourcePathTextArea(TextArea):
    """SQL editor that turns pasted CSV path payloads into sources."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("tab", "complete_or_indent", "Complete SQL", show=False),
    ]

    _last_regular_paste_text: str | None = None
    _last_regular_paste_result_text: str | None = None

    def action_complete_or_indent(self) -> None:
        if not isinstance(self.app, CSVQLMenuApp):
            return
        if self.app._open_sql_completion_for_editor(self, empty_status_message=None):
            return
        self.app._replace_sql_editor_selection("    ")

    async def _on_paste(self, event: events.Paste) -> None:
        if not isinstance(self.app, CSVQLMenuApp):
            return

        event.stop()
        event.prevent_default()
        before_text, expected_single_paste_text, expected_double_paste_text = (
            self._paste_text_expectations(event.text)
        )
        if self.app._handle_pasted_csv_sources(event.text):
            self.call_after_refresh(
                lambda: self.app._remove_pasted_text_from_sql_editor(
                    before_text=before_text,
                    expected_single_paste_text=expected_single_paste_text,
                    expected_double_paste_text=expected_double_paste_text,
                )
            )
            self.focus()
            return

        if deduplicated_text := self._deduplicated_regular_paste_text(event.text, before_text):
            self.load_text(deduplicated_text)
            self.focus()
            return

        if default_inserted_text := self._default_inserted_regular_paste_text(
            event.text,
            before_text,
        ):
            self._remember_regular_paste_event(
                pasted_text=event.text,
                result_text=default_inserted_text,
            )
            self.call_after_refresh(
                lambda: self.app._normalize_pasted_text_in_sql_editor(
                    expected_single_paste_text=default_inserted_text,
                    expected_double_paste_text=f"{default_inserted_text}{event.text}",
                )
            )
            self.focus()
            return

        if not self.read_only:
            if result := self._replace_via_keyboard(event.text, *self.selection):
                self.move_cursor(result.end_location)
                self.focus()
        self._remember_regular_paste_event(
            pasted_text=event.text,
            result_text=expected_single_paste_text,
        )
        self.call_after_refresh(
            lambda: self.app._normalize_pasted_text_in_sql_editor(
                expected_single_paste_text=expected_single_paste_text,
                expected_double_paste_text=expected_double_paste_text,
            )
        )

    def _deduplicated_regular_paste_text(
        self,
        pasted_text: str,
        before_text: str,
    ) -> str | None:
        if pasted_text != self._last_regular_paste_text:
            return None
        result_text = self._last_regular_paste_result_text
        if result_text is None:
            return None
        if before_text in {result_text, f"{result_text}{pasted_text}"}:
            return result_text
        return None

    def _default_inserted_regular_paste_text(
        self,
        pasted_text: str,
        before_text: str,
    ) -> str | None:
        if not pasted_text or self.selection.start != self.selection.end:
            return None
        cursor_index = _text_index_from_location(before_text, self.selection.end)
        pasted_start_index = cursor_index - len(pasted_text)
        if pasted_start_index < 0:
            return None
        if before_text[pasted_start_index:cursor_index] != pasted_text:
            return None
        return before_text

    def _remember_regular_paste_event(self, *, pasted_text: str, result_text: str) -> None:
        self._last_regular_paste_text = pasted_text
        self._last_regular_paste_result_text = result_text
        self.call_after_refresh(lambda: self._clear_regular_paste_event(pasted_text, result_text))

    def _clear_regular_paste_event(self, pasted_text: str, result_text: str) -> None:
        if (
            self._last_regular_paste_text == pasted_text
            and self._last_regular_paste_result_text == result_text
        ):
            self._last_regular_paste_text = None
            self._last_regular_paste_result_text = None

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


def _export_path_and_format_for_prompt(path_value: str) -> tuple[str, ExportFormat]:
    cleaned_path = path_value.strip()
    if not cleaned_path:
        raise CSVQLError("Enter an export path.")

    path = Path(cleaned_path)
    suffix = path.suffix.lower()
    if not suffix:
        return str(path.with_suffix(".csv")), ExportFormat.csv
    if suffix == ".csv":
        return cleaned_path, ExportFormat.csv
    if suffix == ".json":
        return cleaned_path, ExportFormat.json
    if suffix in {".md", ".markdown"}:
        return cleaned_path, ExportFormat.markdown
    if suffix == ".txt":
        return cleaned_path, ExportFormat.text
    raise CSVQLError(
        f"Unsupported export file type: {suffix}",
        suggestion="Use .csv, .json, .md, .markdown, or .txt.",
    )


def _display_path(path: Path, base_dir: Path) -> str:
    try:
        resolved_path = path.resolve(strict=False)
        resolved_base = base_dir.resolve(strict=False)
        return resolved_path.relative_to(resolved_base).as_posix()
    except (OSError, ValueError):
        return str(path)


_PREVIOUS_RESULT_AVAILABLE = "Previous result is still available."


def _error_message(error: CSVQLError) -> str:
    lines = [f"Error: {terminal_safe_text(error.message)}"]
    if error.suggestion:
        lines.append(f"Suggestion: {terminal_safe_text(error.suggestion)}")
    return "\n".join(lines)


def _with_previous_result_suggestion(error: CSVQLError) -> CSVQLError:
    if error.suggestion:
        suggestion = f"{error.suggestion} {_PREVIOUS_RESULT_AVAILABLE}"
    else:
        suggestion = _PREVIOUS_RESULT_AVAILABLE
    return CSVQLError(error.message, suggestion=suggestion)


def _non_durable_preview_pause_message(sequence: int, *, reason: str) -> str:
    if reason == "session_spool_limit":
        detail = "session result storage is full"
    elif reason == "user_cancelled":
        detail = "preview preservation did not complete after cancellation"
    else:
        detail = "preview preservation did not complete after a preservation failure"
    return (
        f"Query {sequence} kept only its active preview because {detail}. "
        "Remove older stored results and retry preview preservation, or delete this preview to "
        "continue the queued run."
    )


def _status_with_cleanup_notes(message: str, cleanup_notes: tuple[str, ...]) -> str:
    if not cleanup_notes:
        return message
    return f"{message} {' '.join(cleanup_notes)}"


def _status_with_terminal_warnings(
    message: str,
    *,
    primary_error_message: str | None,
    primary_suggestion: str | None,
    persistence_error_message: str | None,
    persistence_suggestion: str | None,
    cleanup_notes: tuple[str, ...],
) -> str:
    warning_parts: list[str] = []
    if primary_error_message is not None:
        warning_parts.append(
            _error_message(
                CSVQLError(primary_error_message, suggestion=primary_suggestion),
            )
        )
    if persistence_error_message is not None:
        warning_parts.append(
            _error_message(
                CSVQLError(
                    persistence_error_message,
                    suggestion=persistence_suggestion,
                ),
            )
        )
    warning_parts.extend(cleanup_notes)
    return _status_with_cleanup_notes(message, tuple(warning_parts))


def _public_persistence_failure(error: BaseException) -> tuple[str, str | None]:
    if isinstance(error, CSVQLError):
        return (error.message, error.suggestion)
    if isinstance(error, TUIResultStorageError):
        return (error.user_message, None)
    return (
        "Unable to serialize the query result for temporary storage.",
        None,
    )


def _sanitize_cleanup_notes(notes: object) -> tuple[str, ...]:
    sanitized_allowlist = frozenset(
        {
            "Cleanup uncertainty: the active result cursor could not be closed.",
            "Cleanup uncertainty: the incomplete preserved result could not be fully removed.",
            "Cleanup uncertainty: one or more source bindings could not be closed.",
            "Cleanup uncertainty: the engine connection could not be closed.",
        }
    )
    sanitized: list[str] = []
    for note in notes if isinstance(notes, (tuple, list)) else ():
        if isinstance(note, str) and note in sanitized_allowlist and note not in sanitized:
            sanitized.append(note)
    return tuple(sanitized)


def _merge_cleanup_notes(
    existing: tuple[str, ...],
    incoming: tuple[str, ...],
) -> tuple[str, ...]:
    merged = list(existing)
    for note in incoming:
        if note not in merged:
            merged.append(note)
    return tuple(merged)


def _one_line_sql(sql: str) -> str:
    return " ".join(sql.split())


def _run_request_description(request: TUIRunRequest) -> str:
    first_sql = _one_line_sql(request.statements[0])
    if len(first_sql) > 80:
        first_sql = f"{first_sql[:77]}..."
    if len(request.statements) == 1:
        return (
            f"{request.run_mode} query {request.sequences[0]} "
            f"(submission {request.submission_order}: {first_sql})"
        )
    return (
        f"{request.run_mode} queries {request.sequences[0]}-{request.sequences[-1]} "
        f"(submission {request.submission_order}, {len(request.statements)} statements: "
        f"{first_sql})"
    )


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
    if run_mode == "rerun":
        return f"Running queued rerun as query {sequence}..."
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
    if is_active:
        return f"ACTIVE: {label}"
    return f"        {label}"


def _click_focus_target(widget: Widget | None) -> str | None:
    if widget is None or widget.id is None:
        return None
    return _CLICK_FOCUS_TARGETS.get(widget.id)


def _results_title(active_result_label: str, is_active: bool) -> str:
    if active_result_label == "No active result":
        return _pane_title("Results", is_active)
    if is_active:
        result_label = active_result_label.removeprefix("Active result: ")
        return f"ACTIVE RESULT: {result_label}"
    return _pane_title(active_result_label, is_active)


def _pane_context(active_pane: TUIFocusPane) -> str:
    if active_pane == "sources":
        return (
            "Sources: F3 pick | a add | i inspect | s sample | p profile | "
            "c columns | l alias | x starter | d remove | w save catalog"
        )
    if active_pane == "history":
        return (
            "History: selected row | Enter reopen | r rerun | Delete remove preserved | "
            "F7 export active | Ctrl+S/Alt+S save active"
        )
    if active_pane == "results":
        return (
            "Result target: active result. Delete removes the selected preserved result. "
            "Export and save use the active result shown above."
        )
    return "Editor target: current SQL buffer. Buffer run keeps statements in one DuckDB session."


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


def _text_location_from_index(text: str, index: int) -> tuple[int, int]:
    bounded_index = min(max(index, 0), len(text))
    lines = text.splitlines(keepends=True)
    if not lines:
        return (0, 0)

    remaining = bounded_index
    for row, line in enumerate(lines):
        line_length = len(line)
        if remaining <= line_length:
            line_text = line.removesuffix("\n").removesuffix("\r")
            return (row, min(remaining, len(line_text)))
        remaining -= line_length
    return (len(lines) - 1, len(lines[-1].removesuffix("\n").removesuffix("\r")))


def _inspect_source_outcome(
    source: TUISource,
    *,
    operation: OperationContext,
) -> _SourceInspectOutcome:
    result = inspect_source(source, operation=operation)
    return _SourceInspectOutcome(
        source_name=source.name,
        result=result,
        columns=tuple(
            TUISourceColumn(name=column.name, duckdb_type=column.duckdb_type)
            for column in result.columns
        ),
    )


def _added_sources_message(sources: Sequence[TUISource]) -> str:
    if len(sources) == 1:
        return f"Added source {sources[0].name}."
    source_names = ", ".join(source.name for source in sources)
    return f"Added {len(sources)} sources: {source_names}."
