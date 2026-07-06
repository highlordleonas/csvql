"""In-memory session state for the CSVQL menu TUI."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from csvql.exceptions import TableMappingError
from csvql.models import QueryResult, TableSource
from csvql.table_mapping import validate_table_alias
from csvql.tui_result_store import TUIResultHandle

SourceOrigin = Literal["argument", "catalog", "session"]
SourceKind = Literal["csv", "derived"]
TUILastResultStatus = Literal["none", "query", "no_result", "error"]
TUIFocusPane = Literal["sources", "editor", "results", "history"]
TUIQueryHistoryStatus = Literal["success", "no_result", "error"]
TUIQueryRunMode = Literal["current", "buffer", "rerun"]
TUIActiveResultKind = Literal["none", "query", "history", "buffer"]
TUIQueryOutcomeStatus = Literal["success", "no_result", "error"]
TUIOperationKind = Literal["inspect", "sample", "profile", "columns", "export", "save_result"]


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
    """Human-facing ownership state for exportable/saveable tabular results."""

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
    """Display state for the visible results grid."""

    columns: tuple[str, ...] = ()
    display_rows: tuple[tuple[str, ...], ...] = ()
    total_row_count: int = 0
    preview_row_cap: int = 1000
    cell_char_cap: int = 120
    is_truncated: bool = False
    source_result_sequence: int | None = None


@dataclass(frozen=True, slots=True)
class TUIQueryRunState:
    """Current query-worker state."""

    is_running: bool = False
    sequence: int | None = None


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
    def success(cls, *, sequence: int, sql: str, result: QueryResult) -> "TUIQueryOutcome":
        return cls(
            sequence=sequence,
            sql=sql,
            status="success",
            result=result,
            elapsed_ms=result.elapsed_ms,
        )

    @classmethod
    def no_result(cls, *, sequence: int, sql: str, elapsed_ms: float) -> "TUIQueryOutcome":
        return cls(sequence=sequence, sql=sql, status="no_result", elapsed_ms=elapsed_ms)

    @classmethod
    def error(
        cls,
        *,
        sequence: int,
        sql: str,
        error_message: str,
        suggestion: str | None,
    ) -> "TUIQueryOutcome":
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
        validated_name = validate_table_alias(self.name)
        object.__setattr__(self, "name", validated_name)

    def as_table_source(self) -> TableSource:
        """Convert the TUI source into a DuckDB registration source."""

        return TableSource(name=self.name, path=self.path)


@dataclass(slots=True)
class TUISessionState:
    """Mutable session state for the CSVQL menu TUI."""

    _sources: list[TUISource] = field(default_factory=list)
    _source_columns: dict[str, tuple[TUISourceColumn, ...]] = field(default_factory=dict)
    _selected_alias: str | None = None
    _query_history: list[TUIQueryHistoryItem] = field(default_factory=list)
    _query_results: dict[int, QueryResult] = field(default_factory=dict)
    _query_result_handles: dict[int, TUIResultHandle] = field(default_factory=dict)
    _query_result_views: dict[int, TUIResultViewState] = field(default_factory=dict)
    _next_query_sequence: int = 1
    active_pane: TUIFocusPane = "editor"
    last_result: QueryResult | None = None
    last_result_status: TUILastResultStatus = "none"
    active_result: TUIActiveResultState = field(default_factory=TUIActiveResultState)
    _buffer_result_tabs: list[TUIBufferResultTab] = field(default_factory=list)
    result_view: TUIResultViewState = field(default_factory=TUIResultViewState)
    query_run: TUIQueryRunState = field(default_factory=TUIQueryRunState)
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
        removed_source = self._sources.pop(index)
        self._source_columns.pop(removed_source.name.casefold(), None)
        if (
            self._selected_alias is not None
            and self._selected_alias.casefold() == removed_source.name.casefold()
        ):
            self._selected_alias = self._sources[0].name if self._sources else None
        return removed_source

    def set_source_columns(self, alias: str, columns: tuple[TUISourceColumn, ...]) -> None:
        """Store session-local columns for a source alias."""

        source = self.get_source(alias)
        self._source_columns[source.name.casefold()] = columns

    def source_columns(self, alias: str) -> tuple[TUISourceColumn, ...]:
        """Return cached source columns by alias, if any."""

        try:
            source = self.get_source(alias)
        except TableMappingError:
            return ()
        return self._source_columns.get(source.name.casefold(), ())

    def get_source(self, alias: str) -> TUISource:
        """Return a source by alias."""

        return self._sources[self._require_source_index(alias)]

    def select_source(self, alias: str) -> TUISource:
        """Select a source by alias and return it."""

        source = self.get_source(alias)
        self._selected_alias = source.name
        return source

    def selected_source(self) -> TUISource | None:
        """Return the selected source, if any."""

        if self._selected_alias is None:
            return None
        return self.get_source(self._selected_alias)

    @property
    def query_history(self) -> tuple[TUIQueryHistoryItem, ...]:
        return tuple(self._query_history)

    def query_result(self, sequence: int) -> QueryResult | None:
        """Return the stored tabular result for a successful query."""

        return self._query_results.get(sequence)

    def record_query_result_handle(self, sequence: int, handle: TUIResultHandle) -> None:
        """Store the result-store handle for a successful query."""

        self._query_result_handles[sequence] = handle

    def query_result_handle(self, sequence: int) -> TUIResultHandle | None:
        """Return the stored result-store handle for a successful query."""

        return self._query_result_handles.get(sequence)

    def active_query_result_handle(self) -> TUIResultHandle | None:
        """Return the handle for the currently active exportable result, if any."""

        sequence = self.active_result.sequence
        if sequence is None:
            return None
        return self.query_result_handle(sequence)

    def query_result_view(self, sequence: int) -> TUIResultViewState | None:
        """Return the stored result-grid view for a successful query."""

        return self._query_result_views.get(sequence)

    @property
    def buffer_result_tabs(self) -> tuple[TUIBufferResultTab, ...]:
        """Return the buffered result tabs as a read-only tuple."""

        return tuple(self._buffer_result_tabs)

    def set_buffer_result_tabs(
        self,
        tabs: tuple[TUIBufferResultTab, ...],
        *,
        selected_sequence: int | None = None,
    ) -> None:
        """Store the current buffered-result tabs and optionally select one."""

        previous_active_result = self.active_result
        self._buffer_result_tabs = list(tabs)
        if selected_sequence is not None:
            if self.select_buffer_result(selected_sequence):
                return
            self.active_result = TUIActiveResultState()
            return
        if previous_active_result.kind == "buffer" and previous_active_result.sequence is not None:
            if self.select_buffer_result(previous_active_result.sequence):
                return
        self.active_result = TUIActiveResultState()

    def clear_buffer_result_tabs(self) -> None:
        """Clear all buffered-result tabs."""

        self._buffer_result_tabs.clear()
        if self.active_result.kind == "buffer":
            self.active_result = TUIActiveResultState()

    def select_buffer_result(self, sequence: int) -> bool:
        """Select a buffered query result for viewing."""

        result = self.query_result(sequence)
        view = self.query_result_view(sequence)
        tab = next((item for item in self._buffer_result_tabs if item.sequence == sequence), None)
        if result is None or view is None or tab is None:
            return False
        self.last_result = result
        self.last_result_status = "query"
        self.result_view = view
        self.active_result = TUIActiveResultState(
            kind="buffer",
            label=f"Active result: buffer {sequence}.{tab.index}",
            sequence=sequence,
            buffer_result_index=tab.index,
        )
        return True

    def restore_query_result(self, sequence: int) -> bool:
        """Make a successful history row's result the active visible result."""

        result = self.query_result(sequence)
        view = self.query_result_view(sequence)
        if result is None or view is None:
            return False
        self.last_result = result
        self.last_result_status = "query"
        self.result_view = view
        self.active_result = TUIActiveResultState(
            kind="history",
            label=f"History preview: query {sequence}",
            sequence=sequence,
        )
        return True

    def set_last_result(self, result: QueryResult) -> None:
        """Store the most recent query result."""

        self.last_result = result
        self.last_result_status = "query"

    def begin_query_run(self, sql: str) -> int:
        """Start a query run and return its sequence id."""

        return self.begin_query_batch((sql,))[0]

    def begin_query_batch(self, statements: Sequence[str]) -> tuple[int, ...]:
        """Start a batch run and reserve sequence ids for each statement."""

        if self.query_run.is_running:
            raise RuntimeError("A query is already running.")
        if not statements:
            raise ValueError("At least one statement is required.")

        start_sequence = self._next_query_sequence
        sequences = tuple(range(start_sequence, start_sequence + len(statements)))
        self._next_query_sequence += len(statements)
        self.query_run = TUIQueryRunState(is_running=True, sequence=start_sequence)
        return sequences

    def clear_last_result(self) -> None:
        """Clear stored exportable result and visible result state."""

        self.last_result = None
        self.last_result_status = "none"
        self.result_view = TUIResultViewState()
        self.active_result = TUIActiveResultState()
        self.clear_buffer_result_tabs()

    def record_query_success(
        self,
        sequence: int,
        sql: str,
        result: QueryResult,
        result_view: TUIResultViewState | None = None,
        *,
        run_mode: TUIQueryRunMode = "current",
        buffer_result_index: int | None = None,
    ) -> None:
        """Record a successful query and store its result."""

        if run_mode == "buffer" and buffer_result_index is None:
            raise ValueError("buffer_result_index is required for buffer results.")

        self.last_result = result
        self.last_result_status = "query"
        self.result_view = result_view or TUIResultViewState(
            columns=result.columns,
            display_rows=tuple(tuple(str(value) for value in row) for row in result.rows),
            total_row_count=result.row_count,
            source_result_sequence=sequence,
        )
        self._query_results[sequence] = result
        self._query_result_views[sequence] = self.result_view
        if run_mode == "buffer" and buffer_result_index is not None:
            self.active_result = TUIActiveResultState(
                kind="buffer",
                label=f"Active result: buffer {sequence}.{buffer_result_index}",
                sequence=sequence,
                buffer_result_index=buffer_result_index,
            )
        else:
            self.clear_buffer_result_tabs()
            self.active_result = TUIActiveResultState(
                kind="query",
                label=f"Active result: query {sequence}",
                sequence=sequence,
            )
        self._query_history.append(
            TUIQueryHistoryItem(
                sequence=sequence,
                sql=sql,
                status="success",
                run_mode=run_mode,
                row_count=result.row_count,
                elapsed_ms=result.elapsed_ms,
            )
        )
        self.query_run = TUIQueryRunState()

    def record_query_no_result(
        self,
        sequence: int,
        sql: str,
        elapsed_ms: float,
        *,
        run_mode: TUIQueryRunMode = "current",
    ) -> None:
        """Record a successful statement with no tabular result."""

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
        self.query_run = TUIQueryRunState()

    def record_query_error(
        self,
        sequence: int,
        sql: str,
        error_message: str,
        *,
        run_mode: TUIQueryRunMode = "current",
    ) -> None:
        """Record a failed query attempt."""

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
        self.query_run = TUIQueryRunState()

    def is_current_query_sequence(self, sequence: int) -> bool:
        """Return true when a worker result belongs to the active query run."""

        return self.query_run.is_running and self.query_run.sequence == sequence

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
