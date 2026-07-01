# CSVQL Workbench Lite TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `csvql menu` from a thin command wrapper into a small Workbench Lite query loop with typed session history, worker-backed whole-editor execution, a navigable results grid, safe keybindings, and documented help.

**Architecture:** Keep `cli.py` untouched and continue routing behavior through the existing TUI entrypoint. Add small typed TUI-only helpers for history, query outcomes, result-grid display, and help content, while leaving `QueryResult`, CLI output contracts, and `CSVQLSession` unchanged. Refactor `tui_app.py` only enough to compose panes, dispatch actions, start query workers, and apply typed outcomes on the UI thread.

**Tech Stack:** Python 3.11+, Typer, DuckDB, Textual `run_worker(..., thread=True)`, Rich/Textual widgets, pytest, Ruff, mypy, uv.

---

## Scope Check

This plan implements the first Workbench Lite query-loop slice from:

- `docs/superpowers/specs/2026-07-01-csvql-workbench-lite-design.md`

It does not implement:

- selected-SQL execution
- current-statement execution
- named buffers or tabs
- SQL autocomplete or formatting
- persisted query history
- source-column expansion
- AI SQL generation
- safe-mode or sandbox claims
- public `QueryResult`, CLI JSON/table, or `CSVQLSession` API changes

## Execution Notes

At plan creation, the branch already has uncommitted MVP TUI edits in:

- `README.md`
- `src/csvql/tui_app.py`
- `tests/test_tui_app.py`
- `.superpowers/` generated brainstorming artifacts

Before implementation, run `git status --short --branch`. Preserve those changes. Do not discard or overwrite them. The `.superpowers/` directory is generated brainstorming state and should not be committed unless the user separately approves a tracked-artifact decision.

## File Structure

Create:

- `src/csvql/tui_results.py`: pure result-display helpers that turn `QueryResult` into capped, truncated, grid-ready display state.
- `src/csvql/tui_help.py`: Workbench keybinding/help text kept outside the app class.
- `tests/test_tui_results.py`: unit tests for row caps, cell truncation, and wide-column preservation.

Modify:

- `src/csvql/tui_state.py`: add `TUIFocusPane`, query-history records, result-view state, query-run state, and TUI-local query outcomes.
- `src/csvql/tui_workflows.py`: add a TUI-local query runner wrapper that returns typed success/no-result/error outcomes while reusing existing `query_sources`.
- `src/csvql/tui_app.py`: refactor composition into workbench panes, migrate keybindings, render results in `DataTable`, run queries in Textual workers, and keep printable keys safe in the SQL editor.
- `tests/test_tui_state.py`: cover state contracts and history/run state transitions.
- `tests/test_tui_workflows.py`: cover TUI query outcomes without changing public query contracts.
- `tests/test_tui_app.py`: cover app keybindings, result grid, worker outcomes, history, help, quit semantics, and text-entry safety.
- `tests/test_cli_menu.py`: keep root help and `csvql menu --help` coverage intact; add only if the Workbench help/docs changes require a new assertion.
- `README.md`: update the TUI usage section to match the Workbench keymap and whole-editor run semantics.

---

### Task 1: Add Workbench State Contracts

**Files:**
- Modify: `src/csvql/tui_state.py`
- Modify: `tests/test_tui_state.py`

- [ ] **Step 1: Write failing tests for query history and run state**

Append these tests to `tests/test_tui_state.py`:

```python
def test_query_history_records_success_error_and_no_result(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    result = QueryResult(columns=("count",), rows=((2,),), elapsed_ms=7.5)

    sequence = state.begin_query_run("SELECT COUNT(*) FROM orders")
    state.record_query_success(sequence, "SELECT COUNT(*) FROM orders", result)
    no_result_sequence = state.begin_query_run("CREATE TABLE scratch AS SELECT 1")
    state.record_query_no_result(no_result_sequence, "CREATE TABLE scratch AS SELECT 1", 2.5)
    error_sequence = state.begin_query_run("SELECT * FROM missing")
    state.record_query_error(error_sequence, "SELECT * FROM missing", "missing table")

    assert [item.status for item in state.query_history] == ["success", "no_result", "error"]
    assert state.query_history[0].row_count == 1
    assert state.query_history[0].elapsed_ms == 7.5
    assert state.query_history[1].row_count is None
    assert state.query_history[1].error_message is None
    assert state.query_history[2].error_message == "missing table"
    assert state.query_run.is_running is False
    assert state.last_result is None
```

Add this test for active run tracking:

```python
def test_begin_query_run_prevents_overlapping_runs(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))

    sequence = state.begin_query_run("SELECT * FROM orders")

    assert sequence == 1
    assert state.query_run.is_running is True
    assert state.query_run.sequence == 1

    with pytest.raises(RuntimeError, match="query is already running"):
        state.begin_query_run("SELECT COUNT(*) FROM orders")
```

- [ ] **Step 2: Run state tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py -q
```

Expected: failure because `begin_query_run`, `query_history`, `query_run`, and history record types do not exist yet.

- [ ] **Step 3: Add state contracts and methods**

Modify `src/csvql/tui_state.py` by adding these imports:

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
```

Then add these TUI-only types after `SourceOrigin`:

```python
TUIFocusPane = Literal["sources", "editor", "results", "history"]
TUIQueryHistoryStatus = Literal["success", "no_result", "error"]
TUIQueryOutcomeStatus = Literal["success", "no_result", "error"]


@dataclass(frozen=True, slots=True)
class TUIQueryHistoryItem:
    """One in-memory query attempt in the current TUI session."""

    sequence: int
    sql: str
    status: TUIQueryHistoryStatus
    row_count: int | None = None
    elapsed_ms: float | None = None
    error_message: str | None = None


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
```

Update `TUISessionState` fields:

```python
    _sources: list[TUISource] = field(default_factory=list)
    _selected_alias: str | None = None
    _query_history: list[TUIQueryHistoryItem] = field(default_factory=list)
    _next_query_sequence: int = 1
    active_pane: TUIFocusPane = "editor"
    last_result: QueryResult | None = None
    result_view: TUIResultViewState = field(default_factory=TUIResultViewState)
    query_run: TUIQueryRunState = field(default_factory=TUIQueryRunState)
```

Add these properties and methods to `TUISessionState`:

```python
    @property
    def query_history(self) -> tuple[TUIQueryHistoryItem, ...]:
        return tuple(self._query_history)

    def begin_query_run(self, sql: str) -> int:
        """Start a query run and return its sequence id."""

        if self.query_run.is_running:
            raise RuntimeError("A query is already running.")
        sequence = self._next_query_sequence
        self._next_query_sequence += 1
        self.query_run = TUIQueryRunState(is_running=True, sequence=sequence)
        return sequence

    def clear_last_result(self) -> None:
        """Clear stored exportable result and visible result state."""

        self.last_result = None
        self.result_view = TUIResultViewState()

    def record_query_success(
        self,
        sequence: int,
        sql: str,
        result: QueryResult,
        result_view: TUIResultViewState | None = None,
    ) -> None:
        """Record a successful query and store its result."""

        self.last_result = result
        self.result_view = result_view or TUIResultViewState(
            columns=result.columns,
            display_rows=tuple(tuple(str(value) for value in row) for row in result.rows),
            total_row_count=result.row_count,
            source_result_sequence=sequence,
        )
        self._query_history.append(
            TUIQueryHistoryItem(
                sequence=sequence,
                sql=sql,
                status="success",
                row_count=result.row_count,
                elapsed_ms=result.elapsed_ms,
            )
        )
        self.query_run = TUIQueryRunState()

    def record_query_no_result(self, sequence: int, sql: str, elapsed_ms: float) -> None:
        """Record a successful statement with no tabular result."""

        self.clear_last_result()
        self._query_history.append(
            TUIQueryHistoryItem(
                sequence=sequence,
                sql=sql,
                status="no_result",
                elapsed_ms=elapsed_ms,
            )
        )
        self.query_run = TUIQueryRunState()

    def record_query_error(self, sequence: int, sql: str, error_message: str) -> None:
        """Record a failed query attempt."""

        self.clear_last_result()
        self._query_history.append(
            TUIQueryHistoryItem(
                sequence=sequence,
                sql=sql,
                status="error",
                error_message=error_message,
            )
        )
        self.query_run = TUIQueryRunState()

    def is_current_query_sequence(self, sequence: int) -> bool:
        """Return true when a worker result belongs to the active query run."""

        return self.query_run.is_running and self.query_run.sequence == sequence
```

- [ ] **Step 4: Run state tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py -q
```

Expected: all state tests pass.

- [ ] **Step 5: Commit state contracts**

```bash
git add src/csvql/tui_state.py tests/test_tui_state.py
git commit -m "feat: add tui workbench state"
```

---

### Task 2: Add Result Grid Display Helpers

**Files:**
- Create: `src/csvql/tui_results.py`
- Create: `tests/test_tui_results.py`

- [ ] **Step 1: Write failing result-helper tests**

Create `tests/test_tui_results.py`:

```python
from csvql.models import QueryResult
from csvql.tui_results import make_result_view_state


def test_result_view_caps_display_rows_without_mutating_source_result() -> None:
    result = QueryResult(
        columns=("id",),
        rows=tuple((index,) for index in range(5)),
        elapsed_ms=1.2,
    )

    view = make_result_view_state(result, source_result_sequence=7, preview_row_cap=3)

    assert view.columns == ("id",)
    assert view.display_rows == (("0",), ("1",), ("2",))
    assert view.total_row_count == 5
    assert view.is_truncated is True
    assert view.source_result_sequence == 7
    assert result.row_count == 5


def test_result_view_truncates_wide_cells_for_display_only() -> None:
    result = QueryResult(
        columns=("payload",),
        rows=(("abcdef",),),
        elapsed_ms=1.2,
    )

    view = make_result_view_state(result, source_result_sequence=1, cell_char_cap=5)

    assert view.display_rows == (("ab...",),)
    assert result.rows == (("abcdef",),)


def test_result_view_preserves_all_columns_for_horizontal_scroll() -> None:
    result = QueryResult(
        columns=("c1", "c2", "c3", "c4"),
        rows=((1, 2, 3, 4),),
        elapsed_ms=1.2,
    )

    view = make_result_view_state(result, source_result_sequence=2)

    assert view.columns == ("c1", "c2", "c3", "c4")
    assert view.display_rows == (("1", "2", "3", "4"),)
```

- [ ] **Step 2: Run result-helper tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_results.py -q
```

Expected: import failure because `csvql.tui_results` does not exist.

- [ ] **Step 3: Implement result helpers**

Create `src/csvql/tui_results.py`:

```python
"""Result-grid display helpers for the CSVQL Workbench TUI."""

from textual.widgets import DataTable

from csvql.models import QueryResult
from csvql.tui_state import TUIResultViewState

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


def populate_result_table(table: DataTable[object], view: TUIResultViewState) -> None:
    """Populate a Textual table from display state."""

    table.clear(columns=True)
    if not view.columns:
        return
    table.add_columns(*view.columns)
    for row in view.display_rows:
        table.add_row(*row)


def _display_cell(value: object, *, cell_char_cap: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= cell_char_cap:
        return text
    if cell_char_cap <= 3:
        return text[:cell_char_cap]
    return f"{text[: cell_char_cap - 3]}..."
```

- [ ] **Step 4: Run result-helper tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_results.py -q
```

Expected: all result-helper tests pass.

- [ ] **Step 5: Commit result helpers**

```bash
git add src/csvql/tui_results.py tests/test_tui_results.py
git commit -m "feat: add tui result display helpers"
```

---

### Task 3: Add TUI-Local Query Outcomes

**Files:**
- Modify: `src/csvql/tui_workflows.py`
- Modify: `tests/test_tui_workflows.py`

- [ ] **Step 1: Write failing workflow tests for TUI query outcomes**

Append these tests to `tests/test_tui_workflows.py`:

```python
def test_run_query_for_tui_returns_success_outcome(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv", "id,value\n1,alpha\n")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    outcome = run_query_for_tui((source,), "SELECT * FROM orders", sequence=4)

    assert outcome.sequence == 4
    assert outcome.status == "success"
    assert outcome.result is not None
    assert outcome.result.columns == ("id", "value")
    assert outcome.error_message is None


def test_run_query_for_tui_returns_no_result_for_empty_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_query_sources(sources: object, sql: str) -> QueryResult:
        return QueryResult(columns=(), rows=(), elapsed_ms=3.25)

    monkeypatch.setattr("csvql.tui_workflows.query_sources", fake_query_sources)

    outcome = run_query_for_tui((), "CREATE TABLE scratch(id INTEGER)", sequence=8)

    assert outcome.sequence == 8
    assert outcome.status == "no_result"
    assert outcome.result is None
    assert outcome.elapsed_ms == 3.25


def test_run_query_for_tui_returns_error_outcome(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv", "id,value\n1,alpha\n")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    outcome = run_query_for_tui((source,), "SELECT * FROM missing_alias", sequence=9)

    assert outcome.sequence == 9
    assert outcome.status == "error"
    assert outcome.result is None
    assert "DuckDB query failed" in (outcome.error_message or "")
    assert outcome.suggestion == "Check table names, column names, and SQL syntax."
```

Update the imports in `tests/test_tui_workflows.py` to include:

```python
    run_query_for_tui,
```

- [ ] **Step 2: Run workflow tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_workflows.py -q
```

Expected: failure because `run_query_for_tui` does not exist.

- [ ] **Step 3: Add query outcome wrapper**

Modify `src/csvql/tui_workflows.py` imports:

```python
from csvql.exceptions import CSVQLError, ProjectConfigError
from csvql.tui_state import TUIQueryOutcome, TUISessionState, TUISource
```

Add this function below `query_sources`:

```python
def run_query_for_tui(
    sources: Sequence[TUISource],
    sql: str,
    *,
    sequence: int,
) -> TUIQueryOutcome:
    """Run trusted local SQL and return a TUI-local typed outcome."""

    try:
        result = query_sources(sources, sql)
    except CSVQLError as exc:
        return TUIQueryOutcome.error(
            sequence=sequence,
            sql=sql,
            error_message=exc.message,
            suggestion=exc.suggestion,
        )

    if not result.columns:
        return TUIQueryOutcome.no_result(
            sequence=sequence,
            sql=sql,
            elapsed_ms=result.elapsed_ms,
        )
    return TUIQueryOutcome.success(sequence=sequence, sql=sql, result=result)
```

- [ ] **Step 4: Run workflow tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_workflows.py -q
```

Expected: all workflow tests pass.

- [ ] **Step 5: Commit TUI query outcomes**

```bash
git add src/csvql/tui_workflows.py tests/test_tui_workflows.py
git commit -m "feat: add tui query outcomes"
```

---

### Task 4: Add Workbench Pane Layout And Help Screen

**Files:**
- Create: `src/csvql/tui_help.py`
- Modify: `src/csvql/tui_app.py`
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Write failing app tests for panes, help, and result grid**

Append these tests to `tests/test_tui_app.py`:

```python
def test_workbench_history_pane_mounts_with_editor_focused(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[object | None, int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            history = app.query_one("#history", DataTable)
            return app.focused, history.row_count

    focused, history_rows = asyncio.run(_inner())

    assert isinstance(focused, TextArea)
    assert history_rows == 0


def test_help_action_opens_and_escape_restores_editor_focus(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, object | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_show_help()
            await pilot.pause()
            help_text = app.screen.query_one("#help-text", Static).content
            await pilot.press("escape")
            await pilot.pause()
            return help_text, app.focused

    help_text, focused = asyncio.run(_inner())

    assert "Run Editor" in help_text
    assert "F4" in help_text
    assert isinstance(focused, TextArea)
```

- [ ] **Step 2: Run app tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: failure because `#history` and the help screen are not implemented.

- [ ] **Step 3: Add help screen content**

Create `src/csvql/tui_help.py`:

```python
"""Help text for the CSVQL Workbench TUI."""

WORKBENCH_HELP = """CSVQL Workbench Lite

Run Editor
  F4 / Ctrl+Enter     Run the whole SQL editor
  Ctrl+N / F10        Clear editor for a new query

Focus
  F2 / Ctrl+Down      SQL editor
  F5                  Results
  F6 / Ctrl+Up        Sources
  F8                  History

Source pane
  i                   Inspect selected source
  s                   Sample selected source
  p                   Profile selected source
  a                   Add source
  d                   Remove source
  w                   Save sources to project catalog

History pane
  Enter               Reopen selected query
  r                   Rerun selected query with current session sources

General
  F1                  Help
  ?                   Help outside the SQL editor
  F7                  Export last tabular result
  F9                  Quit
  Esc                 Close help or modal
"""
```

- [ ] **Step 4: Refactor app composition into workbench panes**

Modify `src/csvql/tui_app.py` imports:

```python
from textual.containers import Horizontal, Vertical
from csvql.tui_help import WORKBENCH_HELP
```

Add a help modal:

```python
class _HelpScreen(ModalScreen[None]):
    """Workbench help modal."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("escape", "cancel", "Close"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(WORKBENCH_HELP, id="help-text")

    def action_cancel(self) -> None:
        self.dismiss(None)
```

Replace `compose` with:

```python
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
```

Add CSS blocks for the new ids:

```css
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

#results {
    height: 1fr;
    overflow-y: auto;
}
```

Add this helper to the app:

```python
    def _refresh_history_table(self) -> None:
        history_table = self.query_one("#history", DataTable)
        history_table.clear(columns=True)
        history_table.add_columns("seq", "status", "rows", "sql")
        for item in self.state.query_history:
            rows = "" if item.row_count is None else str(item.row_count)
            history_table.add_row(str(item.sequence), item.status, rows, _one_line_sql(item.sql))
```

Add this module-level helper:

```python
def _one_line_sql(sql: str) -> str:
    return " ".join(sql.split())
```

- [ ] **Step 5: Add help actions without changing keybindings yet**

Add actions that Task 6 will bind to keys:

```python
    def action_show_help(self) -> None:
        self.push_screen(_HelpScreen())

    def action_show_contextual_help(self) -> None:
        self.push_screen(_HelpScreen())
```

- [ ] **Step 6: Run app tests and verify pane/help tests pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: all app tests pass. This task adds the help action but does not yet migrate `F1`, so existing source-action bindings remain intact until Task 6.

- [ ] **Step 7: Commit workbench panes and help**

```bash
git add src/csvql/tui_app.py src/csvql/tui_help.py tests/test_tui_app.py
git commit -m "feat: add tui workbench panes"
```

---

### Task 5: Add Worker-Backed Run Editor Flow

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Write failing app tests for worker outcomes**

Append these tests to `tests/test_tui_app.py`:

```python
def test_no_result_outcome_clears_last_result_and_disables_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_last_result(QueryResult(columns=("old",), rows=(("stale",),), elapsed_ms=1.0))

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        from csvql.tui_state import TUIQueryOutcome

        return TUIQueryOutcome.no_result(sequence=sequence, sql=sql, elapsed_ms=4.0)

    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[object | None, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("CREATE TABLE scratch(id INTEGER)")
            await pilot.press("f4")
            await pilot.pause(0.2)
            status = app.query_one("#status", Static).content
            message = app.query_one("#results-message", Static).content
            return app.state.last_result, status, message

    last_result, status, message = asyncio.run(_inner())

    assert last_result is None
    assert "no tabular result" in status
    assert "no tabular result" in message
    assert app_history_statuses(state) == ["no_result"]
```

Add this helper near the top of `tests/test_tui_app.py`:

```python
def app_history_statuses(state: TUISessionState) -> list[str]:
    return [item.status for item in state.query_history]
```

Add this successful result-grid test:

```python
def test_successful_query_populates_results_datatable(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[tuple[str, ...], int, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers ORDER BY customer_id")
            await pilot.press("f4")
            await pilot.pause(0.2)
            results = app.query_one("#results", DataTable)
            status = app.query_one("#status", Static).content
            return (
                tuple(str(column.label) for column in results.columns.values()),
                results.row_count,
                status,
            )

    columns, row_count, status = asyncio.run(_inner())

    assert columns == ("customer_id", "email")
    assert row_count == 2
    assert "2 returned row(s)" in status
```

Add stale worker test:

```python
def test_stale_worker_outcome_is_ignored(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    stale_result = QueryResult(columns=("value",), rows=(("stale",),), elapsed_ms=1.0)

    async def _inner() -> tuple[object | None, tuple[object, ...]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            active_sequence = app.state.begin_query_run("SELECT 'newer'")
            stale_sequence = active_sequence - 1
            from csvql.tui_state import TUIQueryOutcome

            app._handle_query_outcome(
                TUIQueryOutcome.success(
                    sequence=stale_sequence,
                    sql="SELECT 'stale'",
                    result=stale_result,
                )
            )
            return app.state.last_result, app.state.query_history

    last_result, history = asyncio.run(_inner())

    assert last_result is None
    assert history == ()
```

- [ ] **Step 2: Run app tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: failure because `run_query_for_tui` is not imported into `tui_app.py`, query workers do not exist, and `_handle_query_outcome` does not exist.

- [ ] **Step 3: Wire query workers**

Modify `src/csvql/tui_app.py` imports:

```python
from textual.worker import Worker
from csvql.tui_results import make_result_view_state, populate_result_table
from csvql.tui_state import TUIQueryOutcome, TUIResultViewState, TUISessionState, TUISource
from csvql.tui_workflows import (
    build_initial_state,
    export_last_result,
    inspect_source,
    profile_source,
    run_query_for_tui,
    sample_source,
    save_sources_to_project_catalog,
)
```

Replace the right-pane result widgets in `compose`:

```python
                yield DataTable(id="results", cursor_type="cell")
                yield Static("", id="results-message")
```

Add CSS for the message line:

```css
#results-message {
    height: 1;
}
```

Add text-output helpers so inspect/profile/errors do not try to write rich text
into the result grid:

```python
    def _clear_result_grid(self) -> None:
        self.query_one("#results", DataTable).clear(columns=True)

    def _show_output_text(self, message: str) -> None:
        self._clear_result_grid()
        self.query_one("#results-message", Static).update(message)
```

Update `_show_error`:

```python
    def _show_error(self, error: CSVQLError) -> None:
        lines = [f"Error: {error.message}"]
        if error.suggestion:
            lines.append(f"Suggestion: {error.suggestion}")
        message = "\n".join(lines)
        self._set_status(message)
        self._show_output_text(message)
```

Update source actions:

```python
        self._show_output_text(f"Columns: {column_names}")
```

```python
        self._show_output_text(format_profile_result_table(result))
```

For sample output, populate the result grid:

```python
        query_result = QueryResult(
            columns=result.columns,
            rows=result.rows,
            elapsed_ms=0.0,
        )
        view = make_result_view_state(query_result, source_result_sequence=0)
        populate_result_table(self.query_one("#results", DataTable), view)
        self.query_one("#results-message", Static).update(_result_message(view))
```

Replace `action_run_query` with:

```python
    def action_run_query(self) -> None:
        sql_widget = self.query_one("#sql", TextArea)
        sql = sql_widget.text.strip()
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

        self._set_status(f"Running editor query {sequence}...")
        self.query_one("#run-status", Static).update(f"Running editor query {sequence}...")
        sources = self.state.sources
        self.run_worker(
            lambda: run_query_for_tui(sources, sql, sequence=sequence),
            name=f"query-{sequence}",
            group="query",
            thread=True,
            exit_on_error=False,
        )
```

Add worker event handling:

```python
    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.group != "query" or not worker.is_finished:
            return
        outcome = worker.result
        if isinstance(outcome, TUIQueryOutcome):
            self._handle_query_outcome(outcome)

    def _handle_query_outcome(self, outcome: TUIQueryOutcome) -> None:
        if not self.state.is_current_query_sequence(outcome.sequence):
            return
        if outcome.status == "success" and outcome.result is not None:
            view = make_result_view_state(outcome.result, source_result_sequence=outcome.sequence)
            self.state.record_query_success(outcome.sequence, outcome.sql, outcome.result, view)
            populate_result_table(self.query_one("#results", DataTable), view)
            self._refresh_history_table()
            self._set_status(f"{outcome.result.row_count} returned row(s) in {outcome.result.elapsed_ms:.1f} ms.")
            self.query_one("#run-status", Static).update("Ready.")
            self.query_one("#results-message", Static).update(_result_message(view))
            self.query_one("#sql", TextArea).focus()
            return
        if outcome.status == "no_result":
            self.state.record_query_no_result(outcome.sequence, outcome.sql, outcome.elapsed_ms or 0.0)
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
        )
        self.query_one("#results", DataTable).clear(columns=True)
        error = CSVQLError(outcome.error_message or "Query failed.", suggestion=outcome.suggestion)
        self._refresh_history_table()
        self.query_one("#run-status", Static).update("Ready.")
        self._show_error(error)
        self.query_one("#sql", TextArea).focus()
```

Add helper:

```python
def _result_message(view: TUIResultViewState) -> str:
    if view.is_truncated:
        return f"Showing first {view.preview_row_cap} of {view.total_row_count} returned rows."
    return f"Showing {view.total_row_count} returned row(s)."
```

- [ ] **Step 4: Run worker outcome tests**

Before running tests, update existing `tests/test_tui_app.py` assertions that
read textual output from `#results`:

- Error, inspect, profile, save, and export text should read `#results-message`
  as a `Static`.
- Query and sample tables should read `#results` as a `DataTable`.
- Existing checks that looked for strings inside static table output should be
  replaced with row-count, column-label, or status assertions on `DataTable`.

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: worker outcome tests pass. If `Worker.StateChanged` timing requires a longer pause, use `await pilot.pause(0.3)` in the worker tests only.

- [ ] **Step 5: Commit worker-backed query flow**

```bash
git add src/csvql/tui_app.py tests/test_tui_app.py
git commit -m "feat: run tui queries in workers"
```

---

### Task 6: Migrate Keybindings And Text Entry Safety

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Write failing keybinding tests**

Append these tests to `tests/test_tui_app.py`:

```python
@pytest.mark.parametrize("key", ["?", "q", "i", "s", "p", "a", "d", "w", "r"])
def test_printable_keys_type_in_sql_editor(tmp_path: Path, key: str) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            await pilot.press(key)
            await pilot.pause()
            return sql.text

    assert asyncio.run(_inner()) == key


def test_source_letter_actions_only_work_when_sources_focused(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            source_status = app.query_one("#status", Static).content
            await pilot.press("f2")
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            sql_text = app.query_one("#sql", TextArea).text
            return source_status, sql_text

    source_status, sql_text = asyncio.run(_inner())

    assert "customers: 2 columns." in source_status
    assert sql_text == "i"
```

Add focus tests:

```python
def test_workbench_focus_shortcuts_cover_all_panes(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[type[object], type[object], type[object], type[object]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()
            sources_focus = type(app.focused)
            await pilot.press("f8")
            await pilot.pause()
            history_focus = type(app.focused)
            await pilot.press("f5")
            await pilot.pause()
            results_focus = type(app.focused)
            await pilot.press("f2")
            await pilot.pause()
            editor_focus = type(app.focused)
            return sources_focus, history_focus, results_focus, editor_focus

    sources_focus, history_focus, results_focus, editor_focus = asyncio.run(_inner())

    assert sources_focus is DataTable
    assert history_focus is DataTable
    assert results_focus is DataTable
    assert editor_focus is TextArea
```

- [ ] **Step 2: Run app tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: source action letters and safe printable-key behavior are not fully implemented.

- [ ] **Step 3: Replace bindings with Workbench-safe actions**

Update `CSVQLMenuApp.BINDINGS`:

```python
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit_from_non_editor", "Quit", show=False),
        Binding("f1", "show_help", "Help", priority=True),
        Binding("?", "show_contextual_help", "Help", show=False, priority=True),
        Binding("f2,ctrl+down", "focus_sql", "SQL", priority=True),
        Binding("f4,ctrl+enter", "run_query", "Run Editor", key_display="F4/Ctrl+Enter", priority=True),
        Binding("f5", "focus_results", "Results", priority=True),
        Binding("f6,ctrl+up", "focus_sources", "Sources", priority=True),
        Binding("f7", "export_last_result", "Export result", priority=True),
        Binding("f8", "focus_history", "History", priority=True),
        Binding("f9", "quit", "Quit", priority=True),
        Binding("f10,ctrl+n", "new_query", "New query", priority=True),
        Binding("i", "inspect_source", "Inspect", show=False),
        Binding("s", "sample_source", "Sample", show=False),
        Binding("p", "profile_source", "Profile", show=False),
        Binding("a", "add_source", "Add source", show=False),
        Binding("d", "remove_source", "Remove source", show=False),
        Binding("w", "save_sources", "Save sources", show=False),
        Binding("r", "rerun_history", "Rerun", show=False),
        Binding("enter", "reopen_history", "Reopen", show=False),
    ]
```

Add focus helpers:

```python
    def _focused_id(self) -> str | None:
        focused = self.focused
        return None if focused is None else focused.id

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        focused_id = self._focused_id()
        if action in {"show_contextual_help", "quit_from_non_editor"}:
            return False if focused_id == "sql" else True
        if action in {
            "inspect_source",
            "sample_source",
            "profile_source",
            "add_source",
            "remove_source",
            "save_sources",
        }:
            return focused_id == "sources"
        if action in {"rerun_history", "reopen_history"}:
            return focused_id == "history"
        return True
```

Add actions:

```python
    def action_focus_results(self) -> None:
        self.state.active_pane = "results"
        self.query_one("#results", DataTable).focus()

    def action_focus_history(self) -> None:
        self.state.active_pane = "history"
        self.query_one("#history", DataTable).focus()

    def action_quit_from_non_editor(self) -> None:
        self.exit()
```

Update existing focus actions:

```python
    def action_focus_sources(self) -> None:
        self.state.active_pane = "sources"
        self.query_one("#sources", DataTable).focus()

    def action_focus_sql(self) -> None:
        self.state.active_pane = "editor"
        self.query_one("#sql", TextArea).focus()
```

- [ ] **Step 4: Implement history reopen and rerun actions**

Add helpers:

```python
    def _selected_history_item(self) -> TUIQueryHistoryItem | None:
        history_table = self.query_one("#history", DataTable)
        row_index = history_table.cursor_row
        if row_index < 0 or row_index >= len(self.state.query_history):
            return None
        return self.state.query_history[row_index]

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
        self.action_run_query()
```

Import `TUIQueryHistoryItem` from `csvql.tui_state`.

- [ ] **Step 5: Update source action tests for letter bindings**

In `tests/test_tui_app.py`, replace old source action presses:

```python
await pilot.press("f1")
await pilot.press("f2")
await pilot.press("f3")
```

with:

```python
await pilot.press("f6")
await pilot.pause()
await pilot.press("i")
await pilot.press("s")
await pilot.press("p")
```

Replace add/remove/save source action presses similarly:

- add source: focus sources with `f6`, then press `a`
- remove source: focus sources with `f6`, then press `d`
- save sources: focus sources with `f6`, then press `w`

- [ ] **Step 6: Run app tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: all TUI app tests pass.

- [ ] **Step 7: Commit keybinding migration**

```bash
git add src/csvql/tui_app.py tests/test_tui_app.py
git commit -m "feat: refine tui workbench keybindings"
```

---

### Task 7: Document Workbench Usage

**Files:**
- Modify: `README.md`
- Modify: `tests/test_cli_menu.py`
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Add README wording for Workbench keymap**

Replace the current keybinding paragraph in `README.md` under `Interactive Terminal Menu` with:

```markdown
The SQL editor is focused when the menu opens. Type SQL directly, then press
`Ctrl+Enter` or `F4` to run the whole editor. The action is labeled "Run
Editor" because selected-SQL and current-statement execution are not part of
this slice. `F4` is the reliable fallback if your terminal does not emit
`Ctrl+Enter`.

Use `F2` or `Ctrl+Down` for the SQL editor, `F5` for results, `F6` or
`Ctrl+Up` for sources, and `F8` for history. Printable keys type into SQL while
the editor is focused. Source actions use letters only when the source pane is
focused: `i` inspect, `s` sample, `p` profile, `a` add, `d` remove, and `w`
save sources. History actions use `Enter` to reopen a query and `r` to rerun a
query against the current session sources. `F1` opens help; `?` is a help
fallback only outside the SQL editor.

`Ctrl+N` or `F10` clears the editor for a new query while keeping history and
the last result view visible. Query history is in-memory session state only: it
is not written to disk, logged, or sent anywhere by CSVQL, and it clears when
the TUI exits.
```

- [ ] **Step 2: Add app help regression test**

Append to `tests/test_tui_app.py`:

```python
def test_help_text_documents_workbench_keymap(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f1")
            await pilot.pause()
            return app.screen.query_one("#help-text", Static).content

    help_text = asyncio.run(_inner())

    assert "Run Editor" in help_text
    assert "F4 / Ctrl+Enter" in help_text
    assert "F6 / Ctrl+Up" in help_text
    assert "History pane" in help_text
```

- [ ] **Step 3: Verify CLI help tests still protect root/menu behavior**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_cli_menu.py -q
```

Expected: `test_root_help_is_still_shown_for_no_args` and `test_menu_help_lists_startup_arguments` pass unchanged.

- [ ] **Step 4: Run README/help focused checks**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py::test_help_text_documents_workbench_keymap tests/test_cli_menu.py::test_root_help_is_still_shown_for_no_args tests/test_cli_menu.py::test_menu_help_lists_startup_arguments -q
```

Expected: all focused docs/help checks pass.

- [ ] **Step 5: Commit docs and help tests**

```bash
git add README.md tests/test_tui_app.py tests/test_cli_menu.py
git commit -m "docs: document tui workbench keymap"
```

---

### Task 8: Final Verification And Manual Proof

**Files:**
- Verify only unless a previous task exposed a direct issue.

- [ ] **Step 1: Run focused TUI test suite**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py tests/test_tui_results.py tests/test_tui_workflows.py tests/test_tui_app.py tests/test_cli_menu.py -q
```

Expected: all focused TUI and CLI-menu tests pass.

- [ ] **Step 2: Run local quality gate**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest
```

Expected:

- Ruff format passes.
- Ruff lint passes.
- mypy passes.
- Full pytest passes.

- [ ] **Step 3: Run manual TUI proof against the user's CSV**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras csvql menu --table payloads=/Users/richarddemke/Desktop/enerflo_payloads.csv
```

Manual proof script:

1. Confirm SQL editor is focused.
2. Type:

```sql
SELECT COUNT(*) AS row_count FROM payloads
```

3. Press `F4`.
4. Confirm results grid shows `row_count`.
5. Press `Ctrl+N`.
6. Confirm editor clears and prior result/history stay visible.
7. Type:

```sql
SELECT name FROM payloads LIMIT 3
```

8. Press `Ctrl+Enter`.
9. Confirm results grid updates.
10. Press `F8`, select the first history item, and press `Enter`.
11. Confirm the SQL editor reloads that query.
12. Press `F8`, select the second history item, and press `r`.
13. Confirm rerun uses the current `payloads` source.
14. Press `F1`, confirm help opens, then press `Esc`.
15. Press `F9` to quit.

Expected: no implicit `.csvql.yml`, query-history, cache, or export files are created.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git status --short --branch
git diff --stat
git diff --check
```

Expected:

- Only Workbench Lite implementation/docs/test files are modified.
- `.superpowers/` remains untracked unless separately approved.
- `git diff --check` passes.

- [ ] **Step 5: Commit final verification-only cleanup if needed**

If Step 4 exposes only formatting or documentation corrections from the Workbench slice, commit them:

```bash
git add README.md src/csvql/tui_app.py src/csvql/tui_help.py src/csvql/tui_results.py src/csvql/tui_state.py src/csvql/tui_workflows.py tests/test_tui_app.py tests/test_tui_results.py tests/test_tui_state.py tests/test_tui_workflows.py tests/test_cli_menu.py
git commit -m "test: verify tui workbench"
```

If there are no cleanup changes, skip the commit and report that the prior task commits are the final implementation commits.

---

## Self-Review Notes

Spec coverage:

- Whole-editor Run Editor semantics: Tasks 3, 5, 6, and 7.
- No public API changes: Tasks 1 and 3 keep TUI-only types in TUI modules.
- Results row cap, cell truncation, and wide columns: Task 2 and Task 4.
- Current-session history rerun semantics: Task 6.
- Worker correctness and stale outcome handling: Task 5.
- Printable-key safety and `Tab` behavior: Task 6.
- Help/docs/CLI help regression: Task 7.
- Manual proof and full gates: Task 8.

Known execution risk:

- Textual worker timing in `run_test()` may require short `pilot.pause(0.2)` waits in worker tests. Keep waits focused to worker tests and avoid arbitrary sleeps elsewhere.
- DuckDB may return a tabular `Count` result for some DDL/DML. The implementation should classify `no_result` only when the returned `QueryResult` has no columns, and tests should monkeypatch no-result outcomes instead of relying on SQL keyword guesses.
