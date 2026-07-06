# TUI QoL Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the release-blocking TUI QoL issues around Run Buffer, active result ownership, help/modal behavior, portable key fallbacks, pasted CSV paths, and manual QA coverage.

**Architecture:** Keep the current Textual app shape and split behavior across existing modules. `tui_state.py` owns active-result and buffer-tab state, `tui_workflows.py` owns DuckDB execution helpers, `tui_app.py` wires key actions and visible UI, `tui_results.py` keeps display-only result table helpers, and docs/tests define the user-facing contract.

**Tech Stack:** Python, Textual, DuckDB via `CSVQLEngine`, pytest, Ruff, mypy, uv.

---

## File Structure

- Modify `src/csvql/tui_state.py`: add explicit active-result state, buffer result tabs, and rename query run mode from `editor` to `buffer`.
- Modify `src/csvql/tui_workflows.py`: add `run_buffer_for_tui()` that uses one DuckDB engine for all statements in a buffer run.
- Modify `src/csvql/tui_app.py`: rename `F12` action to Run Buffer, wire shared-session buffer outcomes, render/select buffer result tabs, use active result for export/save, harden modal stacking, add portable key fallbacks, and remove embedded SQL path consumption.
- Modify `src/csvql/tui_help.py`: update help text for Run Buffer, active result actions, and portable fallbacks.
- Modify `src/csvql/tui_results.py`: keep existing result-grid helpers; only extend if a selected buffer-tab label belongs in `TUIResultViewState`.
- Modify `tests/test_tui_state.py`: cover active result and buffer tab state transitions.
- Modify `tests/test_tui_workflows.py`: cover shared DuckDB session buffer execution and stop-on-failure behavior.
- Modify `tests/test_tui_app.py`: cover Textual actions, help/modal behavior, active-result export/save targeting, fallback keys, and pasted-path safety.
- Modify `tests/test_v1_polish_docs.py`: update documentation assertions for the new TUI wording.
- Modify `docs/tui-guide.md`, `docs/getting-started.md`, `docs/troubleshooting.md`, `docs/tui-qol-qa.md`, and `docs/v1-manual-qa.md`: align user-facing docs and QA gates with repaired behavior.
- Do not modify version files, publishing workflow, release labels, tags, remotes, or package publication artifacts.

---

### Task 1: State Model For Active Results And Buffer Tabs

**Files:**
- Modify: `src/csvql/tui_state.py`
- Test: `tests/test_tui_state.py`

- [ ] **Step 1: Write failing state tests**

Add these imports in `tests/test_tui_state.py`:

```python
from csvql.tui_state import TUIActiveResultState, TUIBufferResultTab
```

Add these tests near the existing result-state tests:

```python
def test_query_success_sets_active_query_result(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    result = QueryResult(columns=("count",), rows=((2,),), elapsed_ms=7.5)

    sequence = state.begin_query_run("SELECT COUNT(*) FROM orders")
    state.record_query_success(sequence, "SELECT COUNT(*) FROM orders", result)

    assert state.active_result == TUIActiveResultState(
        kind="query",
        label="Active result: query 1",
        sequence=1,
    )
    assert state.last_result == result
    assert state.last_result_status == "query"
```

```python
def test_restore_query_result_marks_history_preview(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    result = QueryResult(columns=("count",), rows=((2,),), elapsed_ms=7.5)
    sequence = state.begin_query_run("SELECT COUNT(*) FROM orders")
    state.record_query_success(sequence, "SELECT COUNT(*) FROM orders", result)

    assert state.restore_query_result(sequence) is True

    assert state.active_result == TUIActiveResultState(
        kind="history",
        label="History preview: query 1",
        sequence=1,
    )
    assert state.last_result == result
```

```python
def test_buffer_result_tabs_select_active_result(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    first = QueryResult(columns=("first",), rows=((1,),), elapsed_ms=1.0)
    second = QueryResult(columns=("second",), rows=((2,),), elapsed_ms=1.0)

    first_sequence = state.begin_query_run("SELECT 1 AS first")
    state.record_query_success(
        first_sequence,
        "SELECT 1 AS first",
        first,
        run_mode="buffer",
        buffer_result_index=1,
    )
    second_sequence = state.begin_query_run("SELECT 2 AS second")
    state.record_query_success(
        second_sequence,
        "SELECT 2 AS second",
        second,
        run_mode="buffer",
        buffer_result_index=2,
    )
    state.set_buffer_result_tabs(
        (
            TUIBufferResultTab(sequence=1, index=1, label="query 1"),
            TUIBufferResultTab(sequence=2, index=2, label="query 2"),
        ),
        selected_sequence=1,
    )

    assert state.select_buffer_result(2) is True

    assert state.active_result == TUIActiveResultState(
        kind="buffer",
        label="Active result: buffer 2.2",
        sequence=2,
        buffer_result_index=2,
    )
    assert state.last_result == second
```

```python
def test_clear_last_result_resets_active_result_and_buffer_tabs(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    sequence = state.begin_query_run("SELECT 1")
    state.record_query_success(
        sequence,
        "SELECT 1",
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        run_mode="buffer",
        buffer_result_index=1,
    )
    state.set_buffer_result_tabs((TUIBufferResultTab(sequence=1, index=1, label="query 1"),))

    state.clear_last_result()

    assert state.last_result is None
    assert state.active_result == TUIActiveResultState()
    assert state.buffer_result_tabs == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_state.py -q
```

Expected: failure because `TUIActiveResultState`, `TUIBufferResultTab`, `buffer_result_index`, `set_buffer_result_tabs`, and `select_buffer_result` do not exist yet.

- [ ] **Step 3: Implement state dataclasses and mode rename**

In `src/csvql/tui_state.py`, replace the run mode literal and add active-result dataclasses:

```python
TUIQueryRunMode = Literal["current", "buffer", "rerun"]
TUIActiveResultKind = Literal["none", "query", "history", "buffer"]
```

```python
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
```

Update `TUIQueryHistoryItem.run_mode` default:

```python
run_mode: TUIQueryRunMode = "current"
```

Add these fields to `TUISessionState`:

```python
_buffer_result_tabs: list[TUIBufferResultTab] = field(default_factory=list)
active_result: TUIActiveResultState = field(default_factory=TUIActiveResultState)
```

Add properties and helpers:

```python
@property
def buffer_result_tabs(self) -> tuple[TUIBufferResultTab, ...]:
    return tuple(self._buffer_result_tabs)

def set_buffer_result_tabs(
    self,
    tabs: tuple[TUIBufferResultTab, ...],
    *,
    selected_sequence: int | None = None,
) -> None:
    self._buffer_result_tabs = list(tabs)
    if selected_sequence is not None:
        self.select_buffer_result(selected_sequence)

def clear_buffer_result_tabs(self) -> None:
    self._buffer_result_tabs.clear()

def select_buffer_result(self, sequence: int) -> bool:
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
```

Update `clear_last_result()`:

```python
def clear_last_result(self) -> None:
    """Clear stored exportable result and visible result state."""

    self.last_result = None
    self.last_result_status = "none"
    self.result_view = TUIResultViewState()
    self.active_result = TUIActiveResultState()
    self.clear_buffer_result_tabs()
```

Update `record_query_success()` signature:

```python
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
```

Inside `record_query_success()`, set active result:

```python
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
```

Use `run_mode: TUIQueryRunMode = "current"` in `record_query_no_result()` and `record_query_error()`. In those methods, call `clear_last_result()` and then set `last_result_status` to `"no_result"` or `"error"`.

Update `restore_query_result()`:

```python
self.active_result = TUIActiveResultState(
    kind="history",
    label=f"History preview: query {sequence}",
    sequence=sequence,
)
```

- [ ] **Step 4: Update existing state tests for new mode names**

In `tests/test_tui_state.py`, replace old internal modes:

```python
assert item.run_mode == "current"
```

```python
run_mode="buffer"
```

```python
assert state.query_history[-1].run_mode == "buffer"
```

Keep `rerun` assertions unchanged.

- [ ] **Step 5: Run state tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_state.py -q
```

Expected: all `tests/test_tui_state.py` tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/csvql/tui_state.py tests/test_tui_state.py
git commit -m "fix: model TUI active result state"
```

---

### Task 2: Shared DuckDB Session For Run Buffer

**Files:**
- Modify: `src/csvql/tui_workflows.py`
- Test: `tests/test_tui_workflows.py`

- [ ] **Step 1: Write failing workflow tests**

Add `run_buffer_for_tui` to the import list in `tests/test_tui_workflows.py`.

Add this test near `run_query_for_tui` tests:

```python
def test_run_buffer_for_tui_shares_duckdb_session_across_statements(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv", "id,value\n1,alpha\n")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    outcomes = run_buffer_for_tui(
        (source,),
        (
            "CREATE TEMP TABLE scratch AS SELECT * FROM orders",
            "SELECT COUNT(*) AS row_count FROM scratch",
        ),
        sequences=(1, 2),
    )

    assert [outcome.status for outcome in outcomes] == ["success", "success"]
    assert outcomes[0].result is not None
    assert outcomes[0].result.columns == ("Count",)
    assert outcomes[1].result is not None
    assert outcomes[1].result.rows == ((1,),)
```

Add this failure-order test:

```python
def test_run_buffer_for_tui_stops_after_first_failure(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv", "id,value\n1,alpha\n")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    outcomes = run_buffer_for_tui(
        (source,),
        (
            "SELECT COUNT(*) AS row_count FROM orders",
            "SELECT * FROM missing_table",
            "SELECT 3 AS should_not_run",
        ),
        sequences=(1, 2, 3),
    )

    assert [outcome.sequence for outcome in outcomes] == [1, 2]
    assert [outcome.status for outcome in outcomes] == ["success", "error"]
    assert outcomes[1].error_message is not None
    assert "missing_table" in outcomes[1].error_message
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_workflows.py::test_run_buffer_for_tui_shares_duckdb_session_across_statements tests/test_tui_workflows.py::test_run_buffer_for_tui_stops_after_first_failure -q
```

Expected: import failure because `run_buffer_for_tui` does not exist yet.

- [ ] **Step 3: Implement shared-session workflow**

In `src/csvql/tui_workflows.py`, add:

```python
def run_buffer_for_tui(
    sources: Sequence[TUISource],
    statements: Sequence[str],
    *,
    sequences: Sequence[int],
) -> tuple[TUIQueryOutcome, ...]:
    """Run trusted local SQL statements in one DuckDB session for Run Buffer."""

    if len(statements) != len(sequences):
        raise ValueError("Run Buffer statements and sequences must have the same length.")

    outcomes: list[TUIQueryOutcome] = []
    with CSVQLEngine() as engine:
        engine.register_tables(source.as_table_source() for source in sources)
        for sql, sequence in zip(statements, sequences, strict=True):
            try:
                result = engine.query(sql)
            except CSVQLError as exc:
                outcomes.append(
                    TUIQueryOutcome.error(
                        sequence=sequence,
                        sql=sql,
                        error_message=exc.message,
                        suggestion=exc.suggestion,
                    )
                )
                break

            if not result.columns:
                outcomes.append(
                    TUIQueryOutcome.no_result(
                        sequence=sequence,
                        sql=sql,
                        elapsed_ms=result.elapsed_ms,
                    )
                )
            else:
                outcomes.append(TUIQueryOutcome.success(sequence=sequence, sql=sql, result=result))

    return tuple(outcomes)
```

- [ ] **Step 4: Run workflow tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_workflows.py::test_run_buffer_for_tui_shares_duckdb_session_across_statements tests/test_tui_workflows.py::test_run_buffer_for_tui_stops_after_first_failure -q
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/csvql/tui_workflows.py tests/test_tui_workflows.py
git commit -m "fix: run TUI buffer in one DuckDB session"
```

---

### Task 3: Textual Run Buffer UI And Result Selection

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `src/csvql/tui_state.py`
- Test: `tests/test_tui_app.py`

- [ ] **Step 1: Write failing app tests for Run Buffer**

Update imports in `tests/test_tui_app.py` if needed:

```python
from csvql.tui_state import TUIBufferResultTab
```

Replace the old `test_run_all_shortcut_runs_whole_editor_when_current_statement_is_not_enough` expectations with:

```python
def test_run_buffer_shortcut_records_buffer_rows_and_selects_latest_tab(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    seen_runs: list[tuple[tuple[str, ...], tuple[int, ...]]] = []

    def fake_run_buffer_for_tui(sources: object, statements: object, *, sequences: object):
        del sources
        from csvql.tui_state import TUIQueryOutcome

        seen_runs.append((tuple(statements), tuple(sequences)))
        return (
            TUIQueryOutcome.success(
                sequence=1,
                sql="SELECT 1 AS first",
                result=QueryResult(columns=("first",), rows=((1,),), elapsed_ms=1.0),
            ),
            TUIQueryOutcome.success(
                sequence=2,
                sql="SELECT 2 AS second",
                result=QueryResult(columns=("second",), rows=((2,),), elapsed_ms=1.0),
            ),
        )

    monkeypatch.setattr("csvql.tui_app.run_buffer_for_tui", fake_run_buffer_for_tui)

    async def _inner() -> tuple[
        list[tuple[tuple[str, ...], tuple[int, ...]]],
        list[str],
        tuple[str, ...],
        str,
        str,
        object,
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 1 AS first;\nSELECT 2 AS second;")

            await pilot.press("ctrl+b")
            await pilot.pause(0.2)

            return (
                seen_runs,
                app_history_run_modes(app.state),
                _history_run_column_values(app),
                app.query_one("#results-title", Static).content,
                app.query_one("#result-tabs", Static).content,
                app.state.last_result.rows if app.state.last_result is not None else (),
            )

    seen_runs, run_modes, run_labels, title, tabs, active_rows = asyncio.run(_inner())

    assert seen_runs == [
        (
            ("SELECT 1 AS first", "SELECT 2 AS second"),
            (1, 2),
        )
    ]
    assert run_modes == ["buffer", "buffer"]
    assert run_labels == ("buffer", "buffer")
    assert "Active result: buffer 2.2" in title
    assert "1: query 1" in tabs
    assert "2: query 2" in tabs
    assert active_rows == ((2,),)
```

Add a selector/export test:

```python
def test_buffer_result_selector_controls_export_target(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    first_sequence = state.begin_query_run("SELECT 'first' AS label")
    state.record_query_success(
        first_sequence,
        "SELECT 'first' AS label",
        QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
        run_mode="buffer",
        buffer_result_index=1,
    )
    second_sequence = state.begin_query_run("SELECT 'second' AS label")
    state.record_query_success(
        second_sequence,
        "SELECT 'second' AS label",
        QueryResult(columns=("label",), rows=(("second",),), elapsed_ms=1.0),
        run_mode="buffer",
        buffer_result_index=2,
    )
    state.set_buffer_result_tabs(
        (
            TUIBufferResultTab(sequence=1, index=1, label="query 1"),
            TUIBufferResultTab(sequence=2, index=2, label="query 2"),
        ),
        selected_sequence=2,
    )
    export_path = tmp_path / "exports" / "buffer-first.csv"
    export_path.parent.mkdir()

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#results", DataTable).focus()
            await pilot.press("[")
            await pilot.pause()
            await pilot.press("f7")
            await pilot.pause()
            export_input = app.screen.query_one("#export-path", Input)
            export_input.value = str(export_path)
            await pilot.press("enter")
            await pilot.pause()
            return export_path.read_text(encoding="utf-8")

    content = asyncio.run(_inner())

    assert content == "label\nfirst\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_run_buffer_shortcut_records_buffer_rows_and_selects_latest_tab tests/test_tui_app.py::test_buffer_result_selector_controls_export_target -q
```

Expected: failures because `run_buffer_for_tui` is not imported in `tui_app.py`, `#result-tabs` does not exist, and buffer result selection is not wired.

- [ ] **Step 3: Add UI node and bindings**

In `CSVQLMenuApp.compose()`, insert a result-tabs line before the results grid:

```python
yield Static("", id="result-tabs")
yield DataTable(id="results", cursor_type="cell")
```

Add CSS:

```css
#result-tabs {
    height: 1;
}
```

Change bindings:

```python
Binding("f12,ctrl+b", "run_buffer", "Run Buffer", key_display="F12", priority=True),
Binding("[", "previous_buffer_result", "Previous result", show=False),
Binding("]", "next_buffer_result", "Next result", show=False),
```

Rename `action_run_query()` to:

```python
def action_run_buffer(self) -> None:
    self._schedule_editor_query(self._run_buffer_from_editor, "Preparing buffer SQL...")
```

Update `check_action()` so `previous_buffer_result` and `next_buffer_result` are disabled while the SQL editor has focus.

- [ ] **Step 4: Wire buffer worker**

Import `run_buffer_for_tui` from `csvql.tui_workflows`.

Add a batch sequence allocator to `TUISessionState`:

```python
def begin_query_batch(self, statements: Sequence[str]) -> tuple[int, ...]:
    """Start a Run Buffer batch and return allocated sequence ids."""

    if self.query_run.is_running:
        raise RuntimeError("A query is already running.")
    sequences = tuple(range(self._next_query_sequence, self._next_query_sequence + len(statements)))
    self._next_query_sequence += len(statements)
    self.query_run = TUIQueryRunState(is_running=True, sequence=sequences[0] if sequences else None)
    return sequences
```

In `CSVQLMenuApp`, replace `_run_query_from_editor()` with:

```python
def _run_buffer_from_editor(self) -> None:
    self._run_editor_pending = False
    sql_widget = self.query_one("#sql", TextArea)
    statements = all_sql_statements(sql_widget.text)
    self._start_buffer_run(statements)
```

Add:

```python
def _start_buffer_run(self, statements: Sequence[str]) -> None:
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
            CSVQLError("Query already running.", suggestion="Wait for the current query to finish."),
            reset_run_status=False,
            simple_message_without_previous=True,
        )
        return

    message = f"Running buffer as queries {sequences[0]}-{sequences[-1]}..."
    self._set_status(message)
    self.query_one("#run-status", Static).update(message)
    sources = self.state.sources
    self.run_worker(
        lambda: run_buffer_for_tui(sources, statements, sequences=sequences),
        name=f"buffer-{sequences[0]}-{sequences[-1]}",
        group="query",
        thread=True,
        exit_on_error=False,
    )
```

In `on_worker_state_changed()`, route tuple outcomes:

```python
if isinstance(outcome, tuple) and all(isinstance(item, TUIQueryOutcome) for item in outcome):
    self._handle_buffer_outcomes(outcome)
    return
```

Add:

```python
def _handle_buffer_outcomes(self, outcomes: tuple[TUIQueryOutcome, ...]) -> None:
    tabs: list[TUIBufferResultTab] = []
    tab_index = 0
    last_success_sequence: int | None = None
    for outcome in outcomes:
        if outcome.status == "success" and outcome.result is not None:
            tab_index += 1
            view = make_result_view_state(outcome.result, source_result_sequence=outcome.sequence)
            self.state.record_query_success(
                outcome.sequence,
                outcome.sql,
                outcome.result,
                view,
                run_mode="buffer",
                buffer_result_index=tab_index,
            )
            tabs.append(
                TUIBufferResultTab(
                    sequence=outcome.sequence,
                    index=tab_index,
                    label=f"query {outcome.sequence}",
                )
            )
            last_success_sequence = outcome.sequence
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

    self.state.set_buffer_result_tabs(tuple(tabs), selected_sequence=last_success_sequence)
    self._refresh_history_table_selecting(outcomes[-1].sequence)
    self._refresh_result_tabs()
    if last_success_sequence is not None:
        self._show_active_result()
    else:
        self._clear_result_grid()
        self.query_one("#results-message", Static).update("Buffer produced no tabular result.")
    self.query_one("#run-status", Static).update("Ready.")
    self.query_one("#sql", TextArea).focus()
```

Add display helpers:

```python
def _show_active_result(self) -> None:
    populate_result_table(self.query_one("#results", DataTable), self.state.result_view)
    self.query_one("#results-title", Static).update(self.state.active_result.label)
    self.query_one("#results-message", Static).update(_result_message(self.state.result_view))

def _refresh_result_tabs(self) -> None:
    tabs = self.state.buffer_result_tabs
    if not tabs:
        self.query_one("#result-tabs", Static).update("")
        return
    active_sequence = self.state.active_result.sequence
    parts = []
    for tab in tabs:
        label = f"{tab.index}: {tab.label}"
        parts.append(f"[{label}]" if tab.sequence == active_sequence else label)
    self.query_one("#result-tabs", Static).update("Buffer results: " + " | ".join(parts))
```

Add tab actions:

```python
def action_previous_buffer_result(self) -> None:
    self._select_adjacent_buffer_result(-1)

def action_next_buffer_result(self) -> None:
    self._select_adjacent_buffer_result(1)

def _select_adjacent_buffer_result(self, delta: int) -> None:
    tabs = self.state.buffer_result_tabs
    if not tabs:
        return
    active_sequence = self.state.active_result.sequence
    active_index = next(
        (index for index, tab in enumerate(tabs) if tab.sequence == active_sequence),
        0,
    )
    target = tabs[(active_index + delta) % len(tabs)]
    if self.state.select_buffer_result(target.sequence):
        self._show_active_result()
        self._refresh_result_tabs()
        self._set_status(self.state.active_result.label)
```

- [ ] **Step 5: Update old run-mode display**

In `_run_mode_display()`:

```python
def _run_mode_display(run_mode: TUIQueryRunMode) -> str:
    if run_mode == "current":
        return "current"
    if run_mode == "buffer":
        return "buffer"
    return "rerun"
```

In current-statement run calls, use `run_mode="current"`.

In History rerun calls, keep `run_mode="rerun"`.

- [ ] **Step 6: Run focused app tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_run_buffer_shortcut_records_buffer_rows_and_selects_latest_tab tests/test_tui_app.py::test_buffer_result_selector_controls_export_target tests/test_tui_app.py::test_history_rerun_records_rerun_mode_and_status_message tests/test_tui_app.py::test_history_refresh_selects_new_query_sequence_after_append -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/csvql/tui_app.py src/csvql/tui_state.py tests/test_tui_app.py
git commit -m "fix: clarify TUI run buffer results"
```

---

### Task 4: Help, Modal Stacking, And Portable Key Fallbacks

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `src/csvql/tui_help.py`
- Modify: `docs/tui-guide.md`
- Modify: `docs/troubleshooting.md`
- Test: `tests/test_tui_app.py`

- [ ] **Step 1: Write failing help and fallback tests**

Add:

```python
def test_f1_does_not_stack_help_over_add_source_prompt(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+o")
            await pilot.pause()
            first_screen = app.screen
            await pilot.press("f1")
            await pilot.pause()
            still_prompt = app.screen is first_screen
            input_id = app.screen.query_one(Input).id
            return input_id or "", still_prompt

    input_id, still_prompt = asyncio.run(_inner())

    assert input_id == "mapping-input"
    assert still_prompt is True
```

Add:

```python
def test_portable_open_csv_fallback_opens_add_source_prompt(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+o")
            await pilot.pause()
            return app.screen.query_one(Input).id or ""

    assert asyncio.run(_inner()) == "mapping-input"
```

Update `test_help_text_documents_workbench_keymap()` assertions:

```python
assert "F12 / Ctrl+B        Run Buffer" in help_text
assert "F3 / Ctrl+O         Choose CSV file(s) or prompt for paths" in help_text
assert "F7                  Export active result" in help_text
assert "F9 / q              Quit outside text entry" in help_text
assert "?                   Help" not in help_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_f1_does_not_stack_help_over_add_source_prompt tests/test_tui_app.py::test_portable_open_csv_fallback_opens_add_source_prompt tests/test_tui_app.py::test_help_text_documents_workbench_keymap -q
```

Expected: failures because `ctrl+o` is not bound and help still documents old labels.

- [ ] **Step 3: Implement modal guard and fallback bindings**

In `CSVQLMenuApp.BINDINGS`, update:

```python
Binding("f3,ctrl+o", "choose_csv_source", "Open CSV", key_display="F3", priority=True),
Binding("f12,ctrl+b", "run_buffer", "Run Buffer", key_display="F12", priority=True),
Binding("f7", "export_last_result", "Export active result", priority=True),
Binding("q", "quit_from_non_editor", "Quit", show=False),
```

In `_show_help_once()`:

```python
def _show_help_once(self) -> None:
    if self._help_screen_open or isinstance(self.screen, (_HelpScreen, _PromptInputScreen)):
        return
    self._help_screen_open = True
    self.push_screen(_HelpScreen(), callback=lambda _: self._mark_help_closed())
```

Update `action_export_last_result()` errors:

```python
self._show_error(CSVQLError("Run or recall a tabular result before exporting."))
```

Update `action_save_result_as_source()` errors:

```python
self._show_error(CSVQLError("Run or recall a tabular result before saving it as a source."))
```

- [ ] **Step 4: Update help text**

In `src/csvql/tui_help.py`, replace the relevant blocks:

```python
Run SQL
  F4 / Ctrl+R         Run selected SQL, otherwise current statement
  F12 / Ctrl+B        Run Buffer
  Ctrl+N / F10        Clear editor for a new query
```

```python
Source pane
  F3 / Ctrl+O         Choose CSV file(s) or prompt for paths
```

```python
General
  F1                  Help
  F7                  Export active result
  F9 / q              Quit outside text entry
  Esc                 Close help or modal
```

```python
Derived sources
  Ctrl+S              Save active result to .csvql/results/{alias}.csv
  Alt+S / F11         Alternate save-result shortcuts
```

- [ ] **Step 5: Update user docs**

In `docs/tui-guide.md`, update Core Keys:

```markdown
| `F4` or `Ctrl+R` | Run selected SQL or the current statement |
| `F12` or `Ctrl+B` | Run Buffer: run all semicolon-delimited SQL in the editor |
| `F3` or `Ctrl+O` | Choose CSV file(s) on macOS or open a CSV path prompt elsewhere |
| `F7` | Export active result |
| `F9` or `q` | Quit outside text entry |
```

Update the run-label paragraph:

```markdown
The History run column uses semantic labels: `current` for F4/Ctrl+R runs,
`buffer` for F12/Ctrl+B runs, and `rerun` for History reruns.
```

In `docs/troubleshooting.md`, ensure the fallback list includes `Ctrl+O` for Open CSV/Add Source and `Ctrl+B` for Run Buffer.

- [ ] **Step 6: Run focused tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_f1_does_not_stack_help_over_add_source_prompt tests/test_tui_app.py::test_portable_open_csv_fallback_opens_add_source_prompt tests/test_tui_app.py::test_help_text_documents_workbench_keymap tests/test_tui_app.py::test_question_mark_types_in_sql_editor_and_f1_opens_help -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/csvql/tui_app.py src/csvql/tui_help.py docs/tui-guide.md docs/troubleshooting.md tests/test_tui_app.py
git commit -m "fix: harden TUI help and fallback keys"
```

---

### Task 5: Pasted CSV Path Safety

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `docs/tui-guide.md`
- Test: `tests/test_tui_app.py`
- Test: `tests/test_tui_workflows.py`

- [ ] **Step 1: Write failing path-safety tests**

Keep `test_pasted_csv_path_adds_source_without_inserting_editor_text()` and `test_inserted_csv_path_text_adds_source_after_editor_settles()`.

Replace `test_embedded_terminal_path_text_adds_source_and_removes_path_text()` with:

```python
def test_embedded_terminal_path_text_inside_sql_is_not_consumed(tmp_path: Path) -> None:
    csv_path = _create_csv(
        tmp_path,
        "embedded_path.csv",
        "id,value\n1,alpha\n",
    )

    async def _inner() -> tuple[tuple[TUISource, ...], str, str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text(f"SELECT '{csv_path}' AS file_path;")
            await pilot.pause(0.2)
            return app.state.sources, sql.text, app.query_one("#status", Static).content

    sources, editor_text, status = asyncio.run(_inner())

    assert sources == ()
    assert editor_text == f"SELECT '{csv_path}' AS file_path;"
    assert "Added source" not in status
```

Add:

```python
def test_sql_comment_with_csv_path_is_not_consumed(tmp_path: Path) -> None:
    csv_path = _create_csv(tmp_path, "comment_path.csv", "id,value\n1,alpha\n")

    async def _inner() -> tuple[tuple[TUISource, ...], str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text(f"-- inspect {csv_path}\nSELECT 1 AS value;")
            await pilot.pause(0.2)
            return app.state.sources, sql.text

    sources, editor_text = asyncio.run(_inner())

    assert sources == ()
    assert editor_text == f"-- inspect {csv_path}\nSELECT 1 AS value;"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_embedded_terminal_path_text_inside_sql_is_not_consumed tests/test_tui_app.py::test_sql_comment_with_csv_path_is_not_consumed -q
```

Expected: failure because embedded path detection consumes the CSV path.

- [ ] **Step 3: Remove embedded SQL path consumption**

In `_consume_sql_editor_csv_path_text()`, remove this block:

```python
sources, cleaned_text = self._sources_from_embedded_editor_csv_paths(raw_text)
if sources:
    return self._add_editor_path_sources(
        sources,
        sql_widget=sql_widget,
        cleaned_text=cleaned_text,
    )
```

Delete `_sources_from_embedded_editor_csv_paths()`, `_editor_csv_path_fragments()`, `_has_editor_path_text_boundary()`, `_remove_text_spans()`, `_QUOTED_CSV_PATH_FRAGMENT`, and `_UNQUOTED_CSV_PATH_FRAGMENT` from `src/csvql/tui_app.py` if they are no longer referenced.

Keep this standalone path behavior:

```python
sources = sources_from_csv_path_text(
    raw_text,
    existing_sources=self.state.sources,
    start_dir=self.start_dir,
)
```

- [ ] **Step 4: Update docs wording**

In `docs/tui-guide.md`, change the launch section sentence to:

```markdown
Pasting one or more standalone `.csv` paths into the SQL editor also turns those
paths into session sources immediately. CSV paths inside SQL strings, comments,
or expressions stay as SQL text.
```

- [ ] **Step 5: Run path tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_pasted_csv_path_adds_source_without_inserting_editor_text tests/test_tui_app.py::test_inserted_csv_path_text_adds_source_after_editor_settles tests/test_tui_app.py::test_embedded_terminal_path_text_inside_sql_is_not_consumed tests/test_tui_app.py::test_sql_comment_with_csv_path_is_not_consumed tests/test_tui_workflows.py::test_sources_from_csv_path_text_ignores_non_path_sql_paste -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/csvql/tui_app.py docs/tui-guide.md tests/test_tui_app.py tests/test_tui_workflows.py
git commit -m "fix: avoid consuming CSV paths inside SQL"
```

---

### Task 6: Manual QA And Authority Docs

**Files:**
- Modify: `docs/tui-qol-qa.md`
- Modify: `docs/v1-manual-qa.md`
- Modify: `docs/getting-started.md`
- Modify: `tests/test_v1_polish_docs.py`

- [ ] **Step 1: Write failing docs assertions**

In `tests/test_v1_polish_docs.py`, update or add assertions:

```python
def test_tui_qol_gate_documents_run_buffer_active_result_and_fallbacks() -> None:
    matrix = Path("docs/tui-qol-qa.md").read_text(encoding="utf-8")

    assert "Run Buffer" in matrix
    assert "multi-result selection" in matrix
    assert "active result" in matrix
    assert "`Ctrl+B`" in matrix
    assert "`Ctrl+O`" in matrix
    assert "CSV paths inside SQL strings, comments, or expressions" in matrix
```

Update existing assertions from:

```python
"Run full-buffer multi-statement SQL with `F12`"
```

to:

```python
"Run Buffer with `F12` or `Ctrl+B`"
```

- [ ] **Step 2: Run docs tests to verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py -q
```

Expected: failures for old TUI wording.

- [ ] **Step 3: Update `docs/tui-qol-qa.md` matrix**

Change QOL rows:

```markdown
| QOL-04 | Add a source with `F3` or `Ctrl+O` | Native picker works where available; otherwise the documented path prompt appears and accepts a CSV path. |
| QOL-06 | Add a source by pasted standalone path | Standalone pasted CSV path becomes a session source and does not remain as SQL text. CSV paths inside SQL strings, comments, or expressions remain SQL text. |
| QOL-09 | Run Buffer with `F12` or `Ctrl+B` | Statements run in order in one DuckDB session, each statement is recorded as a separate History row, temp tables/DDL can feed later statements, and execution stops on first failure. |
| QOL-10 | Select multi-result output from Run Buffer | Successful tabular buffer results are selectable, and the selected result becomes the active result. |
| QOL-12 | Export active result | Export writes the active result, including a recalled History result or selected buffer result. |
| QOL-13 | Save active result as a derived source | Derived CSV is written under `.csvql/results/`, added as a session source, and queryable. |
```

Add a pass-condition sentence:

```markdown
The footer, pane title, result selector, or status line must identify the active
result before export or save-source actions are accepted.
```

- [ ] **Step 4: Update `docs/v1-manual-qa.md`**

In the interactive TUI section, replace old F12 wording with this Markdown:

````markdown
Run a buffer containing:

```sql
CREATE TEMP TABLE movement_counts AS
SELECT name, COUNT(*) AS movement_count
FROM enerflo_payloads
GROUP BY name;

SELECT * FROM movement_counts ORDER BY movement_count DESC;
```

Expected: `F12` or `Ctrl+B` records one History row per statement, preserves the
temporary table for the second statement, shows a selectable tabular buffer
result, and labels that result as active.
````

- [ ] **Step 5: Update `docs/getting-started.md`**

Update the TUI shortcut paragraph:

```markdown
Use `F4` or `Ctrl+R` to run selected SQL or the current statement, `F12` or
`Ctrl+B` to run the full editor buffer, `F6` for sources, `F5` for results,
`F8` for history, and `F9` or `q` outside text entry to quit.
```

- [ ] **Step 6: Run docs tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py -q
```

Expected: all docs tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add docs/tui-qol-qa.md docs/v1-manual-qa.md docs/getting-started.md tests/test_v1_polish_docs.py
git commit -m "docs: refresh TUI QoL gate for run buffer"
```

---

### Task 7: Focused Verification And Final Gate

**Files:**
- Verify only unless a prior task left a failing check.

- [ ] **Step 1: Run focused TUI suite**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_state.py tests/test_tui_workflows.py tests/test_tui_results.py tests/test_tui_app.py -q
```

Expected: all focused TUI tests pass.

- [ ] **Step 2: Run docs tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py -q
```

Expected: docs assertions pass.

- [ ] **Step 3: Run formatting and lint checks**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff format --check .
```

Expected: formatted check passes.

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check .
```

Expected: lint check passes.

- [ ] **Step 4: Run typing**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras mypy src
```

Expected: mypy reports no issues.

- [ ] **Step 5: Run full tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest
```

Expected: full pytest suite passes.

- [ ] **Step 6: Check Git diff cleanliness**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

Run:

```bash
git status --short --branch
```

Expected: branch name plus a clean working tree after the final implementation commit.

- [ ] **Step 7: Record release status accurately**

Do not claim `release-candidate eligible` after automated proof alone. The status remains `not eligible yet` until the terminal-by-terminal TUI QoL manual matrix passes with required media evidence and the broader authority-doc agreement proof is complete.
