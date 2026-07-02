# CSVQL Editor Quality V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the optional TUI editor run/repeat workflow so users can run selected SQL, the current statement, the whole editor, and history reruns with clear status and history labels.

**Architecture:** Keep the work TUI-only. Put statement selection in `tui_editor.py`, store session-local run-mode metadata in `tui_state.py`, keep Textual bindings/status/history rendering in `tui_app.py`, and keep user-facing keymap text in `tui_help.py` and `README.md`.

**Tech Stack:** Python 3.11+, DuckDB, Textual `TextArea` and `DataTable`, pytest, Ruff, mypy, uv.

---

## Review Status

This plan follows:

- `docs/superpowers/specs/2026-07-02-csvql-editor-quality-v2-design.md`
- spec commit `46c17ee`

At plan-writing time, the repository has an uncommitted Editor Quality v2 draft:

- modified: `README.md`
- modified: `src/csvql/tui_app.py`
- modified: `src/csvql/tui_help.py`
- modified: `tests/test_tui_app.py`
- untracked: `src/csvql/tui_editor.py`
- untracked: `tests/test_tui_editor.py`
- untracked: `.superpowers/`

Execution should reconcile the draft with this plan. Do not stage or commit
`.superpowers/` unless Richard explicitly approves tracking generated state.

## Scope Check

This plan implements only Editor Quality v2 inside the optional `csvql menu`
TUI.

It does not implement:

- CLI command changes
- Python API changes
- DuckDB engine changes
- project catalog schema changes
- persisted query history
- cursor-exact source insertion changes
- SQL formatter
- SQL autocomplete
- SQL parser replacement
- syntax highlighting
- line numbers
- multi-cursor editing
- safe mode, sandboxing, production-readiness, or large-file proof claims

## Required Skills At Execution Time

Before executing code tasks, load:

- `python-codebase-standards`
- `testing-strategy`
- `security-best-practices`
- `documentation` and `readme` for Task 4
- `superpowers:test-driven-development`
- `code-review`
- `superpowers:verification-before-completion`

## File Structure

Create or modify:

- `src/csvql/tui_editor.py`: editor SQL selection helpers.
- `tests/test_tui_editor.py`: focused unit tests for current-statement selection.
- `src/csvql/tui_state.py`: query-history run-mode metadata.
- `tests/test_tui_state.py`: state tests for run-mode defaults and recording.
- `src/csvql/tui_app.py`: run bindings, run-mode scheduling, status text, history rendering, and rerun behavior.
- `tests/test_tui_app.py`: app tests for `F4`, `F12`, history reopen/rerun, status text, and history run column.
- `src/csvql/tui_help.py`: in-app TUI keymap text.
- `README.md`: user-facing TUI keymap text.

Preserve:

- `src/csvql/cli.py`
- `src/csvql/engine.py`
- `src/csvql/session.py`
- `pyproject.toml`
- `uv.lock`
- `.superpowers/`

---

### Task 1: Finalize Editor Statement Selection Helpers

**Files:**
- Create or modify: `src/csvql/tui_editor.py`
- Create or modify: `tests/test_tui_editor.py`

- [ ] **Step 1: Write the focused editor-helper tests**

Create or replace `tests/test_tui_editor.py` with:

```python
from csvql.tui_editor import current_statement_at_offset, selected_or_current_sql


def test_selected_sql_wins_over_current_statement() -> None:
    sql = "SELECT * FROM missing;\nSELECT COUNT(*) FROM customers;"

    assert (
        selected_or_current_sql(
            sql,
            cursor_location=(0, 8),
            selected_text="  SELECT COUNT(*) FROM customers;  ",
        )
        == "SELECT COUNT(*) FROM customers;"
    )


def test_current_statement_uses_cursor_location_between_semicolons() -> None:
    sql = "SELECT * FROM missing;\nSELECT COUNT(*) FROM customers;\nSELECT * FROM also_missing;"

    assert (
        selected_or_current_sql(sql, cursor_location=(1, 8), selected_text="")
        == "SELECT COUNT(*) FROM customers"
    )


def test_current_statement_does_not_split_on_semicolon_inside_single_quotes() -> None:
    sql = "SELECT 'a;b' AS value;\nSELECT 2 AS value;"

    assert current_statement_at_offset(sql, 10) == "SELECT 'a;b' AS value"


def test_current_statement_does_not_split_on_semicolon_inside_double_quotes() -> None:
    sql = 'SELECT "a;b" AS value;\nSELECT 2 AS value;'

    assert current_statement_at_offset(sql, 10) == 'SELECT "a;b" AS value'


def test_current_statement_does_not_split_on_semicolon_inside_line_comment() -> None:
    sql = "SELECT 1 -- keep ; inside comment\n;\nSELECT 2 AS value;"

    assert current_statement_at_offset(sql, 8) == "SELECT 1 -- keep ; inside comment"


def test_current_statement_does_not_split_on_semicolon_inside_block_comment() -> None:
    sql = "SELECT /* keep ; inside comment */ 1 AS value;\nSELECT 2 AS value;"

    assert current_statement_at_offset(sql, 12) == (
        "SELECT /* keep ; inside comment */ 1 AS value"
    )


def test_current_statement_at_end_after_trailing_semicolon_uses_previous_statement() -> None:
    sql = "SELECT COUNT(*) FROM customers;  "

    assert current_statement_at_offset(sql, len(sql)) == "SELECT COUNT(*) FROM customers"
```

- [ ] **Step 2: Run the editor-helper tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_editor.py -q
```

Expected on a clean baseline: failure because `csvql.tui_editor` does not exist.
Expected with the current dirty draft: the tests may already pass. If they pass,
continue because the draft already satisfies this helper contract.

- [ ] **Step 3: Implement the editor helper**

Create or replace `src/csvql/tui_editor.py` with:

```python
"""SQL editor text helpers for the CSVQL menu TUI."""

Location = tuple[int, int]


def selected_or_current_sql(
    text: str,
    *,
    cursor_location: Location,
    selected_text: str,
) -> str:
    """Return selected SQL, or the current semicolon-delimited statement."""

    selected_sql = selected_text.strip()
    if selected_sql:
        return selected_sql
    return current_statement_at_offset(text, _offset_for_location(text, cursor_location))


def current_statement_at_offset(text: str, cursor_offset: int) -> str:
    """Return the statement around a text offset, ignoring semicolons inside SQL literals."""

    bounded_offset = max(0, min(cursor_offset, len(text)))
    segments = _statement_segments(text)
    current_segment_index = len(segments) - 1
    for index, (_, end_offset) in enumerate(segments):
        if bounded_offset <= end_offset:
            current_segment_index = index
            break

    statement = _segment_text(text, segments[current_segment_index])
    if statement:
        return statement

    for index in range(current_segment_index - 1, -1, -1):
        statement = _segment_text(text, segments[index])
        if statement:
            return statement

    return ""


def _statement_segments(text: str) -> tuple[tuple[int, int], ...]:
    segments: list[tuple[int, int]] = []
    statement_start = 0
    for separator_offset in _statement_separator_offsets(text):
        segments.append((statement_start, separator_offset))
        statement_start = separator_offset + 1
    segments.append((statement_start, len(text)))
    return tuple(segments)


def _segment_text(text: str, segment: tuple[int, int]) -> str:
    start_offset, end_offset = segment
    return text[start_offset:end_offset].strip()


def _offset_for_location(text: str, location: Location) -> int:
    row, column = location
    lines = text.splitlines(keepends=True)
    if not lines:
        return 0
    if row <= 0:
        return max(0, min(column, _line_body_length(lines[0])))
    if row >= len(lines):
        return len(text)

    offset = sum(len(line) for line in lines[:row])
    return offset + max(0, min(column, _line_body_length(lines[row])))


def _line_body_length(line: str) -> int:
    return len(line.rstrip("\r\n"))


def _statement_separator_offsets(text: str) -> tuple[int, ...]:
    separators: list[int] = []
    index = 0
    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False

    while index < len(text):
        character = text[index]
        next_character = text[index + 1] if index + 1 < len(text) else ""

        if in_line_comment:
            if character == "\n":
                in_line_comment = False
            index += 1
            continue

        if in_block_comment:
            if character == "*" and next_character == "/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue

        if in_single_quote:
            if character == "'" and next_character == "'":
                index += 2
                continue
            if character == "'":
                in_single_quote = False
            index += 1
            continue

        if in_double_quote:
            if character == '"' and next_character == '"':
                index += 2
                continue
            if character == '"':
                in_double_quote = False
            index += 1
            continue

        if character == "-" and next_character == "-":
            in_line_comment = True
            index += 2
            continue
        if character == "/" and next_character == "*":
            in_block_comment = True
            index += 2
            continue
        if character == "'":
            in_single_quote = True
            index += 1
            continue
        if character == '"':
            in_double_quote = True
            index += 1
            continue
        if character == ";":
            separators.append(index)
        index += 1

    return tuple(separators)
```

- [ ] **Step 4: Run the editor-helper tests again**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_editor.py -q
```

Expected: all `tests/test_tui_editor.py` tests pass.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add src/csvql/tui_editor.py tests/test_tui_editor.py
git commit -m "feat: add tui editor statement selection"
```

Expected: commit succeeds. `.superpowers/` remains untracked.

---

### Task 2: Add Query Run Mode To Session History

**Files:**
- Modify: `src/csvql/tui_state.py`
- Modify: `tests/test_tui_state.py`

- [ ] **Step 1: Write run-mode state tests**

Update the import in `tests/test_tui_state.py` to include
`TUIQueryHistoryItem`:

```python
from csvql.tui_state import (
    TUIQueryHistoryItem,
    TUIResultViewState,
    TUISessionState,
    TUISource,
    TUISourceColumn,
)
```

Append these tests to `tests/test_tui_state.py`:

```python
def test_query_history_item_defaults_to_sql_run_mode() -> None:
    item = TUIQueryHistoryItem(sequence=1, sql="SELECT 1", status="success")

    assert item.run_mode == "sql"


def test_record_query_success_stores_run_mode(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="customers", path=tmp_path / "customers.csv", origin="argument"))
    sequence = state.begin_query_run("SELECT 1")

    state.record_query_success(
        sequence,
        "SELECT 1",
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        run_mode="editor",
    )

    assert state.query_history[-1].run_mode == "editor"


def test_record_query_no_result_stores_run_mode(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="customers", path=tmp_path / "customers.csv", origin="argument"))
    sequence = state.begin_query_run("CREATE TEMP TABLE t AS SELECT 1")

    state.record_query_no_result(
        sequence,
        "CREATE TEMP TABLE t AS SELECT 1",
        elapsed_ms=1.0,
        run_mode="rerun",
    )

    assert state.query_history[-1].run_mode == "rerun"


def test_record_query_error_stores_run_mode(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="customers", path=tmp_path / "customers.csv", origin="argument"))
    sequence = state.begin_query_run("SELECT * FROM missing")

    state.record_query_error(
        sequence,
        "SELECT * FROM missing",
        "Catalog Error: missing table",
        run_mode="rerun",
    )

    assert state.query_history[-1].run_mode == "rerun"
```

- [ ] **Step 2: Run the run-mode state tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py::test_query_history_item_defaults_to_sql_run_mode tests/test_tui_state.py::test_record_query_success_stores_run_mode tests/test_tui_state.py::test_record_query_no_result_stores_run_mode tests/test_tui_state.py::test_record_query_error_stores_run_mode -q
```

Expected: failure because `run_mode` and `TUIQueryRunMode` have not been added.

- [ ] **Step 3: Add run-mode types and history fields**

In `src/csvql/tui_state.py`, add this alias near the existing query-history
aliases:

```python
TUIQueryRunMode = Literal["sql", "editor", "rerun"]
```

Update `TUIQueryHistoryItem`:

```python
@dataclass(frozen=True, slots=True)
class TUIQueryHistoryItem:
    """One in-memory query attempt in the current TUI session."""

    sequence: int
    sql: str
    status: TUIQueryHistoryStatus
    run_mode: TUIQueryRunMode = "sql"
    row_count: int | None = None
    elapsed_ms: float | None = None
    error_message: str | None = None
```

Update `record_query_success()` to accept and store `run_mode`:

```python
    def record_query_success(
        self,
        sequence: int,
        sql: str,
        result: QueryResult,
        result_view: TUIResultViewState | None = None,
        *,
        run_mode: TUIQueryRunMode = "sql",
    ) -> None:
        """Record a successful query and store its result."""

        self.last_result = result
        self.last_result_status = "query"
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
                run_mode=run_mode,
                row_count=result.row_count,
                elapsed_ms=result.elapsed_ms,
            )
        )
        self.query_run = TUIQueryRunState()
```

Update `record_query_no_result()`:

```python
    def record_query_no_result(
        self,
        sequence: int,
        sql: str,
        elapsed_ms: float,
        *,
        run_mode: TUIQueryRunMode = "sql",
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
```

Update `record_query_error()`:

```python
    def record_query_error(
        self,
        sequence: int,
        sql: str,
        error_message: str,
        *,
        run_mode: TUIQueryRunMode = "sql",
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
```

- [ ] **Step 4: Run state tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py -q
```

Expected: all `tests/test_tui_state.py` tests pass.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add src/csvql/tui_state.py tests/test_tui_state.py
git commit -m "feat: track tui query run modes"
```

Expected: commit succeeds. `.superpowers/` remains untracked.

---

### Task 3: Wire Run Modes Through App Status, History, And Rerun

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Add app tests for run-mode history and rerun clarity**

Add this helper near `app_history_statuses()` in `tests/test_tui_app.py`:

```python
def app_history_run_modes(state: TUISessionState) -> list[str]:
    return [item.run_mode for item in state.query_history]
```

Add these tests to `tests/test_tui_app.py` near the existing run/history tests:

```python
def test_run_shortcut_records_sql_run_mode_and_history_column(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[list[str], tuple[str, ...], str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT COUNT(*) AS count FROM customers")

            await pilot.press("f4")
            await pilot.pause(0.2)

            history = app.query_one("#history", DataTable)
            return (
                app_history_run_modes(app.state),
                tuple(str(column.label) for column in history.columns.values()),
                app.query_one("#status", Static).content,
            )

    run_modes, columns, status = asyncio.run(_inner())

    assert run_modes == ["sql"]
    assert columns == ("seq", "run", "status", "rows", "sql")
    assert "1 returned row(s)" in status


def test_run_all_shortcut_records_editor_run_mode(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[list[str], str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT COUNT(*) AS count FROM customers")

            await pilot.press("f12")
            await pilot.pause(0.2)

            return app_history_run_modes(app.state), app.query_one("#status", Static).content

    run_modes, status = asyncio.run(_inner())

    assert run_modes == ["editor"]
    assert "1 returned row(s)" in status


def test_history_rerun_records_rerun_mode_and_status_message(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    first_sequence = state.begin_query_run("SELECT COUNT(*) AS count FROM customers")
    state.record_query_success(
        first_sequence,
        "SELECT COUNT(*) AS count FROM customers",
        QueryResult(columns=("count",), rows=((2,),), elapsed_ms=1.0),
    )

    async def _inner() -> tuple[list[str], str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=0)
            await pilot.press("r")
            await pilot.pause(0.05)
            run_status = app.query_one("#run-status", Static).content
            await pilot.pause(0.2)
            return (
                app_history_run_modes(app.state),
                run_status,
                app.query_one("#sql", TextArea).text,
            )

    run_modes, run_status, sql_text = asyncio.run(_inner())

    assert run_modes == ["sql", "rerun"]
    assert run_status == "Rerunning query 1 as query 2..."
    assert sql_text == "SELECT COUNT(*) AS count FROM customers"
```

- [ ] **Step 2: Run the app run-mode tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py::test_run_shortcut_records_sql_run_mode_and_history_column tests/test_tui_app.py::test_run_all_shortcut_records_editor_run_mode tests/test_tui_app.py::test_history_rerun_records_rerun_mode_and_status_message -q
```

Expected: failure because the history table lacks the `run` column and app code
does not pass run modes into history recording.

- [ ] **Step 3: Import and initialize run-mode tracking**

In `src/csvql/tui_app.py`, add `TUIQueryRunMode` to the `csvql.tui_state`
import block:

```python
    TUIQueryRunMode,
```

In `CSVQLMenuApp.__init__()`, add a run-mode map after `_active_query_sql`:

```python
        self._active_query_sql: dict[int, str] = {}
        self._active_query_run_modes: dict[int, TUIQueryRunMode] = {}
        self._run_editor_pending = False
```

- [ ] **Step 4: Pass run modes into query start paths**

Update the run-from-editor methods in `src/csvql/tui_app.py`:

```python
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
```

Replace `_start_query_run()` with:

```python
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
            running_message = f"Rerunning query {rerun_source_sequence} as query {sequence}..."
        else:
            running_message = f"Running {run_label} {sequence}..."

        self._set_status(running_message)
        self.query_one("#run-status", Static).update(running_message)
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
```

- [ ] **Step 5: Make history rerun use stored SQL with run mode**

Replace `action_rerun_history()` in `src/csvql/tui_app.py` with:

```python
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
```

- [ ] **Step 6: Record run modes from worker outcomes**

In `_handle_query_outcome()`, after `_active_query_sql.pop(...)`, add:

```python
        run_mode = self._active_query_run_modes.pop(outcome.sequence, "sql")
```

Update the success record call:

```python
            self.state.record_query_success(
                outcome.sequence,
                outcome.sql,
                outcome.result,
                view,
                run_mode=run_mode,
            )
```

Update the no-result record call:

```python
            self.state.record_query_no_result(
                outcome.sequence,
                outcome.sql,
                outcome.elapsed_ms or 0.0,
                run_mode=run_mode,
            )
```

Update the error record call:

```python
        self.state.record_query_error(
            outcome.sequence,
            outcome.sql,
            outcome.error_message or "Query failed.",
            run_mode=run_mode,
        )
```

In `_handle_query_worker_failure()`, after `_active_query_sql.pop(...)`, add:

```python
        run_mode = self._active_query_run_modes.pop(sequence, "sql")
```

Update the worker-failure record call:

```python
        self.state.record_query_error(sequence, sql, error_message, run_mode=run_mode)
```

- [ ] **Step 7: Add the history `run` column**

Update `_refresh_history_table()` in `src/csvql/tui_app.py`:

```python
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
```

- [ ] **Step 8: Run the focused app tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py::test_run_shortcut_runs_selected_sql_when_editor_has_selection tests/test_tui_app.py::test_run_shortcut_runs_current_statement_when_editor_has_no_selection tests/test_tui_app.py::test_run_all_shortcut_runs_whole_editor_when_current_statement_is_not_enough tests/test_tui_app.py::test_run_shortcut_records_sql_run_mode_and_history_column tests/test_tui_app.py::test_run_all_shortcut_records_editor_run_mode tests/test_tui_app.py::test_history_enter_reopens_query_in_editor tests/test_tui_app.py::test_history_rerun_uses_current_session_sources tests/test_tui_app.py::test_history_rerun_records_rerun_mode_and_status_message -q
```

Expected: all listed tests pass.

- [ ] **Step 9: Commit Task 3**

Run:

```bash
git add src/csvql/tui_app.py tests/test_tui_app.py
git commit -m "feat: clarify tui query run modes"
```

Expected: commit succeeds. `.superpowers/` remains untracked.

---

### Task 4: Align Help, README, And Docs Tests

**Files:**
- Modify: `src/csvql/tui_help.py`
- Modify: `README.md`
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Add docs/help assertions**

Ensure `tests/test_tui_app.py` contains these assertions in the existing help
and README tests:

```python
assert "Run SQL" in help_text
assert "F4 / Ctrl+Enter" in help_text
assert "Run selected SQL, otherwise current statement" in help_text
assert "F12                 Run the whole SQL editor" in help_text
assert "r                   Rerun selected query with current session sources" in help_text
```

Ensure the README test contains:

```python
assert "`Ctrl+Enter` or `F4` to run selected SQL" in readme
assert "current statement around the cursor" in readme
assert "`F12` runs the whole editor" in readme
assert "History" in readme
assert "rerun" in readme
```

- [ ] **Step 2: Run docs/help tests and verify failures where text is stale**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py::test_help_text_documents_workbench_keymap tests/test_tui_app.py::test_readme_documents_source_intelligence_keymap tests/test_tui_app.py::test_readme_documents_editor_quality_keymap -q
```

Expected: tests fail if help or README text does not describe the approved keymap.
If the current draft already updated the text, the tests may pass.

- [ ] **Step 3: Update in-app help text**

Ensure the relevant sections of `src/csvql/tui_help.py` read:

```python
Run SQL
  F4 / Ctrl+Enter     Run selected SQL, otherwise current statement
  F12                 Run the whole SQL editor
  Ctrl+N / F10        Clear editor for a new query
```

and:

```python
History pane
  Enter               Reopen selected query
  r                   Rerun selected query with current session sources
```

- [ ] **Step 4: Update README TUI keymap text**

Ensure the TUI section of `README.md` includes this user-facing text:

```markdown
Use `Ctrl+Enter` or `F4` to run selected SQL. If nothing is selected, CSVQL falls
back to the current statement around the cursor. `F12` runs the whole editor
when you want to execute the complete SQL buffer. `F4` is the reliable fallback
for terminals that do not emit `Ctrl+Enter`.
```

Ensure the history sentence includes:

```markdown
Use History to reopen previous queries or rerun them against the current
session sources.
```

- [ ] **Step 5: Run docs/help tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py::test_help_text_documents_workbench_keymap tests/test_tui_app.py::test_readme_documents_source_intelligence_keymap tests/test_tui_app.py::test_readme_documents_editor_quality_keymap -q
```

Expected: all listed tests pass.

- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add src/csvql/tui_help.py README.md tests/test_tui_app.py
git commit -m "docs: document tui editor run modes"
```

Expected: commit succeeds. `.superpowers/` remains untracked.

---

### Task 5: Run Focused And Full Verification

**Files:**
- Review: all files changed by Tasks 1-4

- [ ] **Step 1: Run focused TUI/editor tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_editor.py tests/test_tui_state.py tests/test_tui_workflows.py tests/test_tui_results.py tests/test_tui_app.py tests/test_cli_menu.py -q
```

Expected: all focused TUI/editor tests pass.

- [ ] **Step 2: Run format check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
```

Expected: Ruff reports all files already formatted.

- [ ] **Step 3: Run lint**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
```

Expected: Ruff reports all checks passed.

- [ ] **Step 4: Run typecheck**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src
```

Expected: mypy reports success with no issues.

- [ ] **Step 5: Run full pytest**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest
```

Expected: full pytest passes.

- [ ] **Step 6: Run whitespace diff check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 7: Inspect final diff**

Run:

```bash
git status --short --branch
git diff --stat
git diff -- README.md src/csvql/tui_app.py src/csvql/tui_editor.py src/csvql/tui_help.py src/csvql/tui_state.py tests/test_tui_app.py tests/test_tui_editor.py tests/test_tui_state.py
```

Expected: only Editor Quality v2 implementation and docs files are modified or
untracked. `.superpowers/` remains untracked and unstaged.

---

### Task 6: Manual TUI Proof And Completion Review

**Files:**
- Review: `README.md`
- Review: `src/csvql/tui_app.py`
- Review: `src/csvql/tui_editor.py`
- Review: `src/csvql/tui_state.py`
- Review: `tests/test_tui_app.py`
- Review: `tests/test_tui_editor.py`
- Review: `tests/test_tui_state.py`

- [ ] **Step 1: Confirm sample CSV shape**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql inspect examples/saas_revenue/data/revenue_movements.csv
```

Expected: command succeeds and shows columns for `revenue_movements`.

- [ ] **Step 2: Launch the TUI for manual proof**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras csvql menu examples/saas_revenue/data/revenue_movements.csv
```

Expected: TUI opens with `revenue_movements` loaded as a source.

- [ ] **Step 3: Prove current-statement execution**

In the editor, enter:

```sql
SELECT * FROM missing_table;
SELECT COUNT(*) AS proof_count FROM revenue_movements;
```

Place the cursor in the second statement and press `F4`.

Expected:

- status reports one returned row;
- result column is `proof_count`;
- result value matches the sample row count;
- history records the new item with run mode `sql`;
- the missing first statement is not executed.

- [ ] **Step 4: Prove whole-editor execution**

Press `F12` with the same editor buffer.

Expected:

- the whole editor is submitted;
- DuckDB reports the expected missing-table error;
- history records the new item with run mode `editor`.

- [ ] **Step 5: Prove history reopen**

Focus History with `F8`, select the successful `sql` run, and press `Enter`.

Expected:

- the selected history SQL loads into the editor;
- focus returns to the SQL editor;
- no new query runs only from pressing `Enter`.

- [ ] **Step 6: Prove history rerun**

Focus History with `F8`, select the successful history item again, and press
`r`.

Expected:

- status or run-status reports `Rerunning query N as query M...`;
- a new history item is recorded with run mode `rerun`;
- the stored history SQL is used, even if the editor had different text before
  pressing `r`.

- [ ] **Step 7: Run code-review pass**

Use the `code-review` skill and review for:

- behavior mismatch with the approved spec;
- missing run-mode recording on success, no-result, and error paths;
- stale result/export state regressions;
- focus-gating regressions for printable keys;
- unsupported safe-mode, sandbox, production, or large-file claims;
- missed tests for the current-statement delimiter contract.

Expected: no blocking findings remain.

- [ ] **Step 8: Commit final verified implementation if needed**

If Tasks 1-4 were committed as separate commits, skip this step.

If execution batched implementation into one diff, run:

```bash
git add README.md src/csvql/tui_app.py src/csvql/tui_editor.py src/csvql/tui_help.py src/csvql/tui_state.py tests/test_tui_app.py tests/test_tui_editor.py tests/test_tui_state.py
git commit -m "feat: improve tui editor run ergonomics"
```

Expected: commit succeeds. `.superpowers/` remains untracked.

## Completion Handoff

When implementation is complete, report:

- commits created;
- files changed;
- skills used;
- focused tests, format check, lint, typecheck, full pytest, and `git diff --check`;
- manual TUI proof result;
- code-review result;
- remaining terminal caveats around `Ctrl+Enter`, function keys, and synthetic
  PTY bursts;
- that `.superpowers/` remained untracked unless Richard approved otherwise;
- that the next lane is Release Candidate Proof Packet with no new product
  scope.
