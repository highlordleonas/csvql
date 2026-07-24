"""In-memory session state for the CSVQL menu TUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from csvql.bounded_result import TruncationReason
from csvql.exceptions import TableMappingError
from csvql.export import ExportFormat
from csvql.models import QueryResult, TableSource
from csvql.table_mapping import validate_table_alias
from csvql.tui_query_runner import TUIRunRequest
from csvql.tui_result_store import TUIResultHandle, TUIResultReason

SourceOrigin = Literal["argument", "catalog", "session", "derived"]
SourceKind = Literal["csv"]
TUILastResultStatus = Literal["none", "query", "no_result", "error"]
TUIQueryHistoryStatus = Literal["success", "no_result", "error", "cancelled"]
TUIFocusPane = Literal["sources", "editor", "results", "history"]
TUIQueryRunMode = Literal["current", "buffer", "rerun"]
TUIActiveResultKind = Literal["none", "query", "history", "buffer"]
TUIQueryOutcomeStatus = Literal["success", "no_result", "error"]
TUIOperationKind = Literal["inspect", "sample", "profile", "columns", "export", "save_result"]
TUIResultState = Literal[
    "executing",
    "preserving",
    "complete",
    "preview_only",
    "cancelled",
    "failed",
]


@dataclass(frozen=True, slots=True)
class TUIQueryHistoryItem:
    """One in-memory query attempt in the current TUI session."""

    sequence: int
    sql: str
    status: TUIQueryHistoryStatus
    run_mode: TUIQueryRunMode = "current"
    row_count: int | None = None
    elapsed_ms: float | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class TUIActiveResultState:
    """Human-facing ownership state for the selected result."""

    kind: TUIActiveResultKind = "none"
    label: str = "No active result"
    sequence: int | None = None
    buffer_result_index: int | None = None


@dataclass(frozen=True, slots=True)
class TUIBufferResultTab:
    """One tabular result produced by the latest Run Buffer action."""

    sequence: int
    index: int
    label: str


@dataclass(frozen=True, slots=True)
class TUIResultViewState:
    """Display state for the one active results grid."""

    columns: tuple[str, ...] = ()
    display_rows: tuple[tuple[str, ...], ...] = ()
    total_row_count: int = 0
    preview_row_cap: int = 1000
    cell_char_cap: int = 120
    is_truncated: bool = False
    truncation_reason: TruncationReason | None = None
    source_result_sequence: int | None = None


@dataclass(frozen=True, slots=True)
class TUIResultCapabilities:
    """Derived user actions for one result lifecycle state."""

    can_view: bool
    can_cancel: bool
    can_export_full: bool
    can_save_as_source: bool
    can_remove: bool


@dataclass(frozen=True, slots=True)
class TUIResultRecord:
    """Immutable result metadata with no retained historical preview rows."""

    handle: TUIResultHandle | None
    state: TUIResultState
    reason: TUIResultReason | None
    columns: tuple[str, ...]
    preview_row_count: int
    full_row_count: int | None
    elapsed_ms: float

    def __post_init__(self) -> None:
        if self.handle is not None and type(self.handle) is not TUIResultHandle:
            raise TypeError("handle must be an opaque TUIResultHandle")
        if type(self.preview_row_count) is not int or self.preview_row_count < 0:
            raise ValueError("preview_row_count must be non-negative")
        if self.full_row_count is not None and (
            type(self.full_row_count) is not int or self.full_row_count < 0
        ):
            raise ValueError("full_row_count must be non-negative")
        if not isinstance(self.columns, tuple) or not all(
            isinstance(column, str) for column in self.columns
        ):
            raise ValueError("columns must be an immutable tuple of strings")
        if self.elapsed_ms < 0:
            raise ValueError("elapsed_ms must be non-negative")

        if self.state == "executing":
            if (
                self.handle is not None
                or self.reason is not None
                or self.full_row_count is not None
            ):
                raise ValueError("executing results cannot retain handles, reasons, or totals")
            if self.columns or self.preview_row_count:
                raise ValueError("executing results cannot retain preview metadata")
            return

        if self.state in {"cancelled", "failed"}:
            if (
                self.handle is not None
                or self.reason is not None
                or self.full_row_count is not None
            ):
                raise ValueError(
                    "terminal non-preview results cannot retain handles, reasons, or totals"
                )
            if self.columns or self.preview_row_count:
                raise ValueError("terminal non-preview results cannot retain preview metadata")
            return

        if self.state == "preserving":
            if (
                self.handle is not None
                or self.reason is not None
                or self.full_row_count is not None
            ):
                raise ValueError("preserving results cannot retain handles, reasons, or totals")
            if self.preview_row_count > 0 and not self.columns:
                raise ValueError("preserving preview rows require columns")
            return

        if self.state == "complete":
            if self.handle is None:
                raise ValueError("complete results require a durable handle")
            if self.reason is not None:
                raise ValueError("complete results cannot retain a reason")
            if self.full_row_count is None:
                raise ValueError("complete results require a full row count")
            if self.preview_row_count > self.full_row_count:
                raise ValueError("preview row count cannot exceed the full row count")
            if self.preview_row_count > 0 and not self.columns:
                raise ValueError("complete preview rows require columns")
            return

        if self.state == "preview_only":
            if self.reason is None:
                raise ValueError("preview_only results require a reason")
            if self.full_row_count is not None:
                raise ValueError("preview_only results cannot retain a full row count")
            if self.preview_row_count > 0 and not self.columns:
                raise ValueError("preview_only preview rows require columns")
            return

        raise ValueError(f"unsupported result state: {self.state}")


@dataclass(frozen=True, slots=True)
class TUIQueuedRun:
    """Exactly one queued immutable run request."""

    request: TUIRunRequest

    def __post_init__(self) -> None:
        if type(self.request) is not TUIRunRequest:
            raise TypeError("request must be an immutable TUIRunRequest")


@dataclass(frozen=True, slots=True)
class TUIQueuedRunReplacement:
    """Confirmation payload for replacing an occupied queued run slot."""

    existing: TUIQueuedRun
    proposed: TUIQueuedRun


@dataclass(frozen=True, slots=True)
class TUIExportIntent:
    """Exactly one immutable export intent attached to the active preserving result."""

    result_sequence: int
    destination: Path
    format: ExportFormat

    def __post_init__(self) -> None:
        if type(self.result_sequence) is not int or self.result_sequence <= 0:
            raise ValueError("result_sequence must be positive")
        if not isinstance(self.destination, Path):
            raise TypeError("destination must be a Path")
        if not isinstance(self.format, ExportFormat):
            raise TypeError("format must be an ExportFormat")


@dataclass(frozen=True, slots=True)
class TUIExportIntentReplacement:
    """Confirmation payload for replacing an occupied export-intent slot."""

    existing: TUIExportIntent
    proposed: TUIExportIntent


@dataclass(frozen=True, slots=True)
class TUIQueryRunState:
    """Current query-worker state, including the active immutable request snapshot."""

    request: TUIRunRequest | None = None

    @property
    def is_running(self) -> bool:
        return self.request is not None

    @property
    def sequence(self) -> int | None:
        return None if self.request is None else self.request.sequences[0]

    @property
    def sequences(self) -> tuple[int, ...]:
        return () if self.request is None else self.request.sequences


@dataclass(frozen=True, slots=True)
class TUIOperationRunState:
    """Current cancellable non-query operation state."""

    is_running: bool = False
    kind: TUIOperationKind | None = None
    label: str = ""


@dataclass(frozen=True, slots=True)
class TUIQueryOutcome:
    """TUI-local worker outcome wrapper around existing query behavior."""

    sequence: int
    sql: str
    status: TUIQueryOutcomeStatus
    result: QueryResult | None = None
    elapsed_ms: float | None = None
    error_message: str | None = None
    suggestion: str | None = None

    @classmethod
    def success(cls, *, sequence: int, sql: str, result: QueryResult) -> TUIQueryOutcome:
        return cls(
            sequence=sequence,
            sql=sql,
            status="success",
            result=result,
            elapsed_ms=result.elapsed_ms,
        )

    @classmethod
    def no_result(cls, *, sequence: int, sql: str, elapsed_ms: float) -> TUIQueryOutcome:
        return cls(sequence=sequence, sql=sql, status="no_result", elapsed_ms=elapsed_ms)

    @classmethod
    def error(
        cls,
        *,
        sequence: int,
        sql: str,
        error_message: str,
        suggestion: str | None,
    ) -> TUIQueryOutcome:
        return cls(
            sequence=sequence,
            sql=sql,
            status="error",
            error_message=error_message,
            suggestion=suggestion,
        )


@dataclass(frozen=True, slots=True)
class TUISourceColumn:
    """Column metadata loaded for a TUI source in the current session."""

    name: str
    duckdb_type: str


@dataclass(frozen=True, slots=True)
class TUISource:
    """A source available to the TUI session."""

    name: str
    path: Path
    origin: SourceOrigin
    kind: SourceKind = "csv"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", validate_table_alias(self.name))

    def as_table_source(self) -> TableSource:
        """Convert the TUI source into a DuckDB registration source."""

        return TableSource(name=self.name, path=self.path)


def derive_result_capabilities(state: TUIResultState) -> TUIResultCapabilities:
    """Return the user-visible capabilities for a result lifecycle state."""

    if state == "executing":
        return TUIResultCapabilities(False, True, False, False, False)
    if state == "preserving":
        return TUIResultCapabilities(True, True, False, False, False)
    if state == "complete":
        return TUIResultCapabilities(True, False, True, True, True)
    if state == "preview_only":
        return TUIResultCapabilities(True, False, False, False, True)
    return TUIResultCapabilities(False, False, False, False, False)


def transition_result_record(
    record: TUIResultRecord,
    *,
    state: TUIResultState,
    handle: TUIResultHandle | None = None,
    reason: TUIResultReason | None = None,
    columns: tuple[str, ...] | None = None,
    preview_row_count: int | None = None,
    full_row_count: int | None = None,
    elapsed_ms: float | None = None,
) -> TUIResultRecord:
    """Return a new record after validating one legal lifecycle transition."""

    allowed: dict[TUIResultState, set[TUIResultState]] = {
        "executing": {"preserving", "cancelled", "failed"},
        "preserving": {"complete", "preview_only"},
        "complete": set(),
        "preview_only": set(),
        "cancelled": set(),
        "failed": set(),
    }
    if state not in allowed[record.state]:
        raise ValueError(f"illegal result transition: {record.state} -> {state}")
    return TUIResultRecord(
        handle=handle,
        state=state,
        reason=reason,
        columns=record.columns if columns is None else columns,
        preview_row_count=(
            record.preview_row_count if preview_row_count is None else preview_row_count
        ),
        full_row_count=full_row_count,
        elapsed_ms=record.elapsed_ms if elapsed_ms is None else elapsed_ms,
    )


@dataclass(slots=True)
class TUISessionState:
    """Mutable session state for the CSVQL menu TUI."""

    _sources: list[TUISource] = field(default_factory=list)
    _source_columns: dict[str, tuple[TUISourceColumn, ...]] = field(default_factory=dict)
    _selected_alias: str | None = None
    _query_history: list[TUIQueryHistoryItem] = field(default_factory=list)
    _query_result_records: dict[int, TUIResultRecord] = field(default_factory=dict)
    _active_result_record: TUIResultRecord | None = None
    _next_query_sequence: int = 1
    active_pane: TUIFocusPane = "editor"
    last_result_status: TUILastResultStatus = "none"
    active_result: TUIActiveResultState = field(default_factory=TUIActiveResultState)
    _buffer_result_tabs: list[TUIBufferResultTab] = field(default_factory=list)
    result_view: TUIResultViewState = field(default_factory=TUIResultViewState)
    query_run: TUIQueryRunState = field(default_factory=TUIQueryRunState)
    queued_run: TUIQueuedRun | None = None
    export_intent: TUIExportIntent | None = None
    operation_run: TUIOperationRunState = field(default_factory=TUIOperationRunState)

    @property
    def sources(self) -> tuple[TUISource, ...]:
        return tuple(self._sources)

    @property
    def table_sources(self) -> tuple[TableSource, ...]:
        return tuple(source.as_table_source() for source in self._sources)

    @property
    def selected_alias(self) -> str | None:
        return self._selected_alias

    def add_source(self, source: TUISource) -> None:
        """Add a source and select it if the session is empty."""

        if self._find_source_index(source.name) is not None:
            raise TableMappingError(
                f"Duplicate table alias '{source.name}'.",
                suggestion="Choose a unique alias for each TUI source.",
            )
        self._sources.append(source)
        if self._selected_alias is None:
            self._selected_alias = source.name

    def remove_source(self, alias: str) -> TUISource:
        """Remove a source by alias, update selection, and return it."""

        index = self._require_source_index(alias)
        removed = self._sources.pop(index)
        self._source_columns.pop(removed.name.casefold(), None)
        if (
            self._selected_alias is not None
            and self._selected_alias.casefold() == removed.name.casefold()
        ):
            self._selected_alias = self._sources[0].name if self._sources else None
        return removed

    def set_source_columns(self, alias: str, columns: tuple[TUISourceColumn, ...]) -> None:
        source = self.get_source(alias)
        self._source_columns[source.name.casefold()] = columns

    def source_columns(self, alias: str) -> tuple[TUISourceColumn, ...]:
        try:
            source = self.get_source(alias)
        except TableMappingError:
            return ()
        return self._source_columns.get(source.name.casefold(), ())

    def get_source(self, alias: str) -> TUISource:
        return self._sources[self._require_source_index(alias)]

    def select_source(self, alias: str) -> TUISource:
        source = self.get_source(alias)
        self._selected_alias = source.name
        return source

    def selected_source(self) -> TUISource | None:
        if self._selected_alias is None:
            return None
        return self.get_source(self._selected_alias)

    @property
    def query_history(self) -> tuple[TUIQueryHistoryItem, ...]:
        return tuple(self._query_history)

    @property
    def active_result_record(self) -> TUIResultRecord | None:
        return self._active_result_record

    def query_result_record(self, sequence: int) -> TUIResultRecord | None:
        return self._query_result_records.get(sequence)

    def query_result_handle(self, sequence: int) -> TUIResultHandle | None:
        record = self.query_result_record(sequence)
        return record.handle if record is not None else None

    def active_query_result_handle(self) -> TUIResultHandle | None:
        sequence = self.active_result.sequence
        if sequence is None:
            return None
        return self.query_result_handle(sequence)

    @property
    def has_active_result(self) -> bool:
        return self.active_result.sequence is not None

    def active_query_result_record(self) -> TUIResultRecord | None:
        return self._active_result_record

    def active_result_capabilities(self) -> TUIResultCapabilities:
        if self._active_result_record is None:
            return TUIResultCapabilities(False, False, False, False, False)
        return derive_result_capabilities(self._active_result_record.state)

    @property
    def buffer_result_tabs(self) -> tuple[TUIBufferResultTab, ...]:
        return tuple(self._buffer_result_tabs)

    def set_buffer_result_tabs(
        self,
        tabs: tuple[TUIBufferResultTab, ...],
        *,
        selected_sequence: int | None = None,
    ) -> None:
        previous = self.active_result
        self._buffer_result_tabs = list(tabs)
        if selected_sequence is not None:
            if self.select_buffer_result(selected_sequence):
                return
            self.active_result = TUIActiveResultState()
            self._active_result_record = None
            self.result_view = TUIResultViewState()
            return
        if previous.kind == "buffer" and previous.sequence is not None:
            if self.select_buffer_result(previous.sequence):
                return
            self.active_result = TUIActiveResultState()
            self._active_result_record = None
            self.result_view = TUIResultViewState()

    def clear_buffer_result_tabs(self) -> None:
        self._buffer_result_tabs.clear()
        if self.active_result.kind == "buffer":
            self.active_result = TUIActiveResultState()
            self._active_result_record = None
            self.result_view = TUIResultViewState()

    def select_buffer_result(self, sequence: int) -> bool:
        record = self.query_result_record(sequence)
        tab = next((item for item in self._buffer_result_tabs if item.sequence == sequence), None)
        if record is None or tab is None:
            return False
        self._active_result_record = record
        self.result_view = TUIResultViewState()
        self.last_result_status = "query"
        self.active_result = TUIActiveResultState(
            kind="buffer",
            label=f"Active result: buffer {sequence}.{tab.index}",
            sequence=sequence,
            buffer_result_index=tab.index,
        )
        return True

    def restore_query_result(self, sequence: int) -> bool:
        record = self.query_result_record(sequence)
        if record is None:
            return False
        self._active_result_record = record
        self.result_view = TUIResultViewState()
        self.last_result_status = "query"
        self.active_result = TUIActiveResultState(
            kind="history",
            label=f"History preview: query {sequence}",
            sequence=sequence,
        )
        return True

    def reserve_query_sequences(self, count: int) -> tuple[int, ...]:
        """Reserve contiguous sequence IDs without starting a run."""

        if type(count) is not int or count <= 0:
            raise ValueError("count must be positive")
        start = self._next_query_sequence
        sequences = tuple(range(start, start + count))
        self._next_query_sequence += count
        return sequences

    def start_query_request(self, request: TUIRunRequest) -> None:
        if self.query_run.is_running:
            raise RuntimeError("A query is already running.")
        self._validate_request_sequences_unused(request)
        self._next_query_sequence = max(self._next_query_sequence, max(request.sequences) + 1)
        self.query_run = TUIQueryRunState(request=request)

    def enqueue_run(self, request: TUIRunRequest) -> TUIQueuedRunReplacement | None:
        if self.query_run.request is None:
            raise RuntimeError("queued run requires an active query request")
        self._validate_request_sequences_unused(request)
        proposed = TUIQueuedRun(request=request)
        if self.queued_run is None:
            self.queued_run = proposed
            return None
        return TUIQueuedRunReplacement(existing=self.queued_run, proposed=proposed)

    def replace_queued_run(self, replacement: TUIQueuedRunReplacement) -> None:
        if self.queued_run is not replacement.existing:
            raise RuntimeError("queued run changed before confirmation")
        self.queued_run = replacement.proposed

    def dequeue_run(self) -> TUIQueuedRun | None:
        queued = self.queued_run
        self.queued_run = None
        return queued

    def clear_last_result(self) -> None:
        self.last_result_status = "none"
        self.result_view = TUIResultViewState()
        self.active_result = TUIActiveResultState()
        self._active_result_record = None
        self.export_intent = None
        self.clear_buffer_result_tabs()

    def set_active_result_record(
        self,
        sequence: int,
        record: TUIResultRecord,
        *,
        run_mode: TUIQueryRunMode = "current",
        buffer_result_index: int | None = None,
        result_view: TUIResultViewState | None = None,
    ) -> None:
        """Set the one active in-memory result record and optional visible preview."""

        self._validate_record_sequence(sequence, record)
        current = self._active_result_record if self.active_result.sequence == sequence else None
        if current is None:
            if record.state != "executing":
                raise ValueError("a result lifecycle must begin in executing state")
        else:
            record = transition_result_record(
                current,
                state=record.state,
                handle=record.handle,
                reason=record.reason,
                columns=record.columns,
                preview_row_count=record.preview_row_count,
                full_row_count=record.full_row_count,
                elapsed_ms=record.elapsed_ms,
            )
        if run_mode == "buffer" and buffer_result_index is None:
            raise ValueError("buffer_result_index is required for buffer results.")
        if record.state == "preserving" and result_view is None:
            raise ValueError("preserving results require an active bounded preview")
        if result_view is not None:
            if result_view.source_result_sequence not in {None, sequence}:
                raise ValueError("active preview sequence must match the result sequence")
            if result_view.columns != record.columns:
                raise ValueError("active preview columns must match the result record")
        if run_mode != "buffer":
            self._buffer_result_tabs.clear()
        self._active_result_record = record
        if result_view is not None:
            self.result_view = result_view
        elif record.state == "executing":
            self.result_view = TUIResultViewState()
        self.last_result_status = "query"
        if run_mode == "buffer":
            self.active_result = TUIActiveResultState(
                kind="buffer",
                label=f"Active result: buffer {sequence}.{buffer_result_index}",
                sequence=sequence,
                buffer_result_index=buffer_result_index,
            )
            return
        self.active_result = TUIActiveResultState(
            kind="query",
            label=f"Active result: query {sequence}",
            sequence=sequence,
        )

    def record_query_result(
        self,
        sequence: int,
        sql: str,
        *,
        record: TUIResultRecord,
        result_view: TUIResultViewState | None = None,
        run_mode: TUIQueryRunMode = "current",
        buffer_result_index: int | None = None,
        complete_run: bool = True,
    ) -> None:
        if record.state not in {"complete", "preview_only"}:
            raise ValueError("only final result states can be recorded in session history")
        self._validate_record_sequence(sequence, record)
        active = self._active_result_record if self.active_result.sequence == sequence else None
        if active is None:
            if result_view is None:
                raise ValueError("a final result requires its active bounded preview")
            self.set_active_result_record(
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
                run_mode=run_mode,
                buffer_result_index=buffer_result_index,
            )
            active = self._active_result_record
        if active is not None and active.state == "executing":
            self.set_active_result_record(
                sequence,
                transition_result_record(
                    active,
                    state="preserving",
                    columns=record.columns,
                    preview_row_count=record.preview_row_count,
                    elapsed_ms=record.elapsed_ms,
                ),
                run_mode=run_mode,
                buffer_result_index=buffer_result_index,
                result_view=result_view,
            )
        self.set_active_result_record(
            sequence,
            record,
            run_mode=run_mode,
            buffer_result_index=buffer_result_index,
            result_view=result_view,
        )
        if record.handle is not None:
            self._query_result_records[sequence] = record
        else:
            self._query_result_records.pop(sequence, None)
        self._query_history.append(
            TUIQueryHistoryItem(
                sequence=sequence,
                sql=sql,
                status="success",
                run_mode=run_mode,
                row_count=record.full_row_count if record.state == "complete" else None,
                elapsed_ms=record.elapsed_ms,
            )
        )
        if complete_run:
            self.finish_query_run()

    def record_query_success(
        self,
        sequence: int,
        sql: str,
        *,
        handle: TUIResultHandle,
        result_view: TUIResultViewState,
        elapsed_ms: float,
        run_mode: TUIQueryRunMode = "current",
        buffer_result_index: int | None = None,
        complete_run: bool = True,
    ) -> None:
        self.record_query_result(
            sequence,
            sql,
            record=TUIResultRecord(
                handle=handle,
                state="complete",
                reason=None,
                columns=result_view.columns,
                preview_row_count=len(result_view.display_rows),
                full_row_count=result_view.total_row_count,
                elapsed_ms=elapsed_ms,
            ),
            result_view=result_view,
            run_mode=run_mode,
            buffer_result_index=buffer_result_index,
            complete_run=complete_run,
        )

    def record_query_storage_error(
        self,
        sequence: int,
        sql: str,
        error_message: str,
        *,
        run_mode: TUIQueryRunMode = "current",
        complete_run: bool = True,
    ) -> None:
        self._query_history.append(
            TUIQueryHistoryItem(
                sequence=sequence,
                sql=sql,
                status="error",
                run_mode=run_mode,
                error_message=error_message,
            )
        )
        if complete_run:
            self.finish_query_run()

    def record_query_cancelled(
        self,
        sequence: int,
        sql: str,
        *,
        elapsed_ms: float | None = None,
        run_mode: TUIQueryRunMode = "current",
        complete_run: bool = True,
    ) -> None:
        self._validate_non_preview_terminal(sequence, state="cancelled")
        self.clear_last_result()
        self._query_history.append(
            TUIQueryHistoryItem(
                sequence=sequence,
                sql=sql,
                status="cancelled",
                run_mode=run_mode,
                elapsed_ms=elapsed_ms,
            )
        )
        if complete_run:
            self.finish_query_run()

    def record_query_no_result(
        self,
        sequence: int,
        sql: str,
        elapsed_ms: float,
        *,
        run_mode: TUIQueryRunMode = "current",
        complete_run: bool = True,
    ) -> None:
        active = self._active_result_record if self.active_result.sequence == sequence else None
        if active is not None and active.state != "executing":
            raise ValueError("no-result terminalization requires an executing result")
        self.clear_last_result()
        self.last_result_status = "no_result"
        self._query_history.append(
            TUIQueryHistoryItem(
                sequence=sequence,
                sql=sql,
                status="no_result",
                run_mode=run_mode,
                elapsed_ms=elapsed_ms,
            )
        )
        if complete_run:
            self.finish_query_run()

    def record_query_failed(
        self,
        sequence: int,
        sql: str,
        error_message: str,
        *,
        run_mode: TUIQueryRunMode = "current",
        complete_run: bool = True,
    ) -> None:
        self._validate_non_preview_terminal(sequence, state="failed")
        self.clear_last_result()
        self.last_result_status = "error"
        self._query_history.append(
            TUIQueryHistoryItem(
                sequence=sequence,
                sql=sql,
                status="error",
                run_mode=run_mode,
                error_message=error_message,
            )
        )
        if complete_run:
            self.finish_query_run()

    def record_query_error(
        self,
        sequence: int,
        sql: str,
        error_message: str,
        *,
        run_mode: TUIQueryRunMode = "current",
        complete_run: bool = True,
    ) -> None:
        self.record_query_failed(
            sequence,
            sql,
            error_message,
            run_mode=run_mode,
            complete_run=complete_run,
        )

    def mark_results_unavailable(self, sequences: tuple[int, ...], message: str) -> None:
        del message
        for sequence in sequences:
            record = self._query_result_records.pop(sequence, None)
            self._buffer_result_tabs = [
                tab for tab in self._buffer_result_tabs if tab.sequence != sequence
            ]
            if record is not None and self.active_result.sequence == sequence:
                self.active_result = TUIActiveResultState()
                self._active_result_record = None
                self.result_view = TUIResultViewState()
            if self.export_intent is not None and self.export_intent.result_sequence == sequence:
                self.export_intent = None

    def remove_query_result(self, sequence: int) -> TUIResultHandle | None:
        record = self._query_result_records.pop(sequence, None)
        self._buffer_result_tabs = [
            tab for tab in self._buffer_result_tabs if tab.sequence != sequence
        ]
        if self.active_result.sequence == sequence:
            self.active_result = TUIActiveResultState()
            self.result_view = TUIResultViewState()
            self._active_result_record = None
            self.last_result_status = "none"
        if self.export_intent is not None and self.export_intent.result_sequence == sequence:
            self.export_intent = None
        return None if record is None else record.handle

    def attach_export_intent(self, intent: TUIExportIntent) -> TUIExportIntentReplacement | None:
        self._require_active_preserving_result(intent.result_sequence)
        if self.export_intent is None:
            self.export_intent = intent
            return None
        return TUIExportIntentReplacement(existing=self.export_intent, proposed=intent)

    def replace_export_intent(self, replacement: TUIExportIntentReplacement) -> None:
        if self.export_intent is not replacement.existing:
            raise RuntimeError("export intent changed before confirmation")
        self._require_active_preserving_result(replacement.proposed.result_sequence)
        self.export_intent = replacement.proposed

    def clear_export_intent(self, intent: TUIExportIntent) -> None:
        if self.export_intent is not intent:
            raise RuntimeError("export intent changed before confirmation")
        self.export_intent = None

    def finish_query_run(self) -> None:
        self.query_run = TUIQueryRunState()

    def is_current_query_sequence(self, sequence: int) -> bool:
        return self.query_run.is_running and sequence in self.query_run.sequences

    def _require_active_preserving_result(self, sequence: int) -> None:
        record = self._active_result_record
        if (
            record is None
            or record.state != "preserving"
            or self.active_result.sequence != sequence
        ):
            raise RuntimeError("export intents require the active preserving result")

    def _validate_non_preview_terminal(
        self,
        sequence: int,
        *,
        state: Literal["cancelled", "failed"],
    ) -> None:
        active = self._active_result_record if self.active_result.sequence == sequence else None
        if active is None:
            active = TUIResultRecord(
                handle=None,
                state="executing",
                reason=None,
                columns=(),
                preview_row_count=0,
                full_row_count=None,
                elapsed_ms=0.0,
            )
        transition_result_record(active, state=state)

    def _validate_record_sequence(self, sequence: int, record: TUIResultRecord) -> None:
        if record.handle is not None and record.handle.sequence != sequence:
            raise ValueError("result handle sequence must match query sequence")

    def _validate_request_sequences_unused(self, request: TUIRunRequest) -> None:
        requested = set(request.sequences)
        used = {item.sequence for item in self._query_history}
        if self.query_run.request is not None:
            used.update(self.query_run.request.sequences)
        if self.queued_run is not None:
            used.update(self.queued_run.request.sequences)
        if requested & used:
            raise ValueError("query request sequence IDs must not be reused")

    def _find_source_index(self, alias: str) -> int | None:
        alias_key = alias.casefold()
        for index, source in enumerate(self._sources):
            if source.name.casefold() == alias_key:
                return index
        return None

    def _require_source_index(self, alias: str) -> int:
        index = self._find_source_index(alias)
        if index is None:
            raise TableMappingError(
                f"Source alias '{alias}' is not loaded in the TUI session.",
                suggestion="Choose a loaded source alias from source manager.",
            )
        return index
