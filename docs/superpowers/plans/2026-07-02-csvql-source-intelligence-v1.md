# CSVQL Source Intelligence V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit source-column display and source-aware SQL snippet insertion to the optional `csvql menu` TUI.

**Architecture:** Keep the feature TUI-only. Store column metadata in `TUISessionState`, adapt existing `inspect_source()` behavior in `tui_workflows.py`, and keep Textual keybindings, output replacement, and append-only editor insertion inside `tui_app.py`.

**Tech Stack:** Python 3.11+, DuckDB, Textual `TextArea` and `DataTable`, pytest, Ruff, mypy, uv.

---

## Review Status

This plan follows:

- `docs/superpowers/specs/2026-07-02-csvql-source-intelligence-v1-design.md`
- hostile-review revision commit `5807595`

Hostile review before this plan found no blocking mismatch after these checks:

- `env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest -q`
- `git diff --check HEAD^ HEAD`
- scope scans for stale first-column, `.` shortcut, sandbox, production, and large-file claims

## Scope Check

This plan implements only Source Intelligence v1 inside the optional TUI.

It does not implement:

- CLI command changes
- Python API changes
- project catalog schema changes
- automatic startup inspection of all sources
- durable column metadata
- background source indexing
- query autocomplete
- syntax highlighting
- SQL formatting
- selected SQL or current-statement execution
- error-recovery suggestions from failed SQL
- column picker
- first-column insertion shortcut
- pandas, Polars, parquet, notebooks, dashboards, web UI, AI, or plugins

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

Modify:

- `src/csvql/tui_state.py`: add `TUISourceColumn` and session-local source-column cache methods.
- `src/csvql/tui_workflows.py`: add `inspect_source_columns()` and `render_duckdb_identifier()`.
- `src/csvql/tui_app.py`: add `c`, `l`, and `x` source actions, result-state clearing, column display, and append-only editor insertion.
- `src/csvql/tui_help.py`: document the new source-pane actions.
- `README.md`: update the TUI keymap section.
- `tests/test_tui_state.py`: cover column cache behavior.
- `tests/test_tui_workflows.py`: cover column inspection and identifier rendering.
- `tests/test_tui_app.py`: cover key gating, display, insertion, and result/export state.

Preserve:

- `src/csvql/cli.py`
- `src/csvql/engine.py`
- `src/csvql/session.py`
- `pyproject.toml`
- `uv.lock`
- `.superpowers/`

---

### Task 1: Add Session-Local Source Column State

**Files:**
- Modify: `src/csvql/tui_state.py`
- Modify: `tests/test_tui_state.py`

- [ ] **Step 1: Write failing state tests**

Modify the import in `tests/test_tui_state.py`:

```python
from csvql.tui_state import TUISourceColumn, TUIResultViewState, TUISessionState, TUISource
```

Append these tests to `tests/test_tui_state.py`:

```python
def test_tui_source_column_stores_name_and_duckdb_type() -> None:
    column = TUISourceColumn(name="Customer ID", duckdb_type="VARCHAR")

    assert column.name == "Customer ID"
    assert column.duckdb_type == "VARCHAR"


def test_session_source_columns_are_case_insensitive_by_alias(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    columns = (
        TUISourceColumn(name="order_id", duckdb_type="VARCHAR"),
        TUISourceColumn(name="total", duckdb_type="DOUBLE"),
    )

    state.set_source_columns("ORDERS", columns)

    assert state.source_columns("orders") == columns
    assert state.source_columns("ORDERS") == columns


def test_removing_source_clears_cached_columns_for_that_alias(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    state.add_source(
        TUISource(name="customers", path=tmp_path / "customers.csv", origin="argument")
    )
    state.set_source_columns(
        "orders",
        (TUISourceColumn(name="order_id", duckdb_type="VARCHAR"),),
    )
    state.set_source_columns(
        "customers",
        (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),),
    )

    state.remove_source("ORDERS")

    assert state.source_columns("orders") == ()
    assert state.source_columns("customers") == (
        TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),
    )
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py::test_tui_source_column_stores_name_and_duckdb_type tests/test_tui_state.py::test_session_source_columns_are_case_insensitive_by_alias tests/test_tui_state.py::test_removing_source_clears_cached_columns_for_that_alias -q
```

Expected: failure because `TUISourceColumn`, `set_source_columns()`, and `source_columns()` do not exist yet.

- [ ] **Step 3: Add the column state model**

Add this dataclass after `TUIQueryOutcome` in `src/csvql/tui_state.py`:

```python
@dataclass(frozen=True, slots=True)
class TUISourceColumn:
    """Column metadata loaded for a TUI source in the current session."""

    name: str
    duckdb_type: str
```

Add this field to `TUISessionState`:

```python
    _source_columns: dict[str, tuple[TUISourceColumn, ...]] = field(default_factory=dict)
```

Add these methods to `TUISessionState`:

```python
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
```

In `remove_source()`, add this line immediately after `removed_source = self._sources.pop(index)`:

```python
        self._source_columns.pop(removed_source.name.casefold(), None)
```

- [ ] **Step 4: Run state tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py -q
```

Expected: all `tests/test_tui_state.py` tests pass.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add src/csvql/tui_state.py tests/test_tui_state.py
git commit -m "feat: add tui source column state"
```

Expected: commit succeeds. `.superpowers/` remains untracked.

---

### Task 2: Add Source Column Workflow And Identifier Rendering

**Files:**
- Modify: `src/csvql/tui_workflows.py`
- Modify: `tests/test_tui_workflows.py`

- [ ] **Step 1: Write failing workflow tests**

Modify imports in `tests/test_tui_workflows.py`:

```python
from csvql.tui_state import TUISessionState, TUISource, TUISourceColumn
from csvql.tui_workflows import (
    build_initial_state,
    export_last_result,
    inspect_source,
    inspect_source_columns,
    profile_source,
    query_sources,
    render_duckdb_identifier,
    run_query_for_tui,
    sample_source,
    save_derived_result_source,
    save_sources_to_project_catalog,
)
```

Append these tests to `tests/test_tui_workflows.py`:

```python
def test_inspect_source_columns_returns_names_and_duckdb_types(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "orders.csv",
        "Customer ID,select,total\nC-1,paid,12.5\n",
    )
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    columns = inspect_source_columns(source)

    assert columns == (
        TUISourceColumn(name="Customer ID", duckdb_type="VARCHAR"),
        TUISourceColumn(name="select", duckdb_type="VARCHAR"),
        TUISourceColumn(name="total", duckdb_type="DOUBLE"),
    )


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("orders", '"orders"'),
        ("Customer ID", '"Customer ID"'),
        ("select", '"select"'),
        ('a"b', '"a""b"'),
    ],
)
def test_render_duckdb_identifier_quotes_generated_sql_identifiers(
    identifier: str,
    expected: str,
) -> None:
    assert render_duckdb_identifier(identifier) == expected
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_workflows.py::test_inspect_source_columns_returns_names_and_duckdb_types tests/test_tui_workflows.py::test_render_duckdb_identifier_quotes_generated_sql_identifiers -q
```

Expected: failure because `inspect_source_columns()` and `render_duckdb_identifier()` do not exist yet.

- [ ] **Step 3: Implement workflow helpers**

Modify the import in `src/csvql/tui_workflows.py`:

```python
from csvql.tui_state import TUIQueryOutcome, TUISessionState, TUISource, TUISourceColumn
```

Add these helpers after `inspect_source()`:

```python
def inspect_source_columns(source: TUISource) -> tuple[TUISourceColumn, ...]:
    """Inspect a TUI source and return its columns for source intelligence."""

    result = inspect_source(source)
    return tuple(
        TUISourceColumn(name=column.name, duckdb_type=column.duckdb_type)
        for column in result.columns
    )


def render_duckdb_identifier(identifier: str) -> str:
    """Render one DuckDB delimited identifier for generated SQL snippets."""

    escaped_identifier = identifier.replace('"', '""')
    return f'"{escaped_identifier}"'
```

- [ ] **Step 4: Run workflow tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_workflows.py -q
```

Expected: all `tests/test_tui_workflows.py` tests pass.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add src/csvql/tui_workflows.py tests/test_tui_workflows.py
git commit -m "feat: add tui source intelligence workflows"
```

Expected: commit succeeds. `.superpowers/` remains untracked.

---

### Task 3: Add TUI Source Intelligence Actions

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Write failing app tests for column display and focus gating**

Append these tests to `tests/test_tui_app.py`:

```python
def test_source_columns_loads_displays_and_disables_export(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    state.set_last_result(QueryResult(columns=("old",), rows=(("stale",),), elapsed_ms=1.0))

    async def _inner() -> tuple[object | None, str, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("c")
            await pilot.pause()
            column_status = app.query_one("#status", Static).content
            column_message = app.query_one("#results-message", Static).content

            await pilot.press("f7")
            await pilot.pause()

            return (
                app.state.last_result,
                column_status,
                column_message,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    last_result, column_status, column_message, export_status, export_message = asyncio.run(_inner())

    assert last_result is None
    assert "customers: 2 columns loaded." in column_status
    assert "customers columns" in column_message
    assert "customer_id VARCHAR" in column_message
    assert "email VARCHAR" in column_message
    assert "Run a query before exporting." in export_status
    assert "Run a query before exporting." in export_message


def test_source_intelligence_printable_keys_only_work_when_sources_focused(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.press("l")
            await pilot.press("x")
            await pilot.pause()
            editor_text = app.query_one("#sql", TextArea).text

            app.query_one("#sources", DataTable).focus()
            await pilot.press("c")
            await pilot.pause()
            message = app.query_one("#results-message", Static).content
            return editor_text, message

    editor_text, message = asyncio.run(_inner())

    assert editor_text == "clx"
    assert "customers columns" in message
```

- [ ] **Step 2: Write failing app tests for insertions**

Append these tests to `tests/test_tui_app.py`:

```python
def test_insert_source_alias_appends_rendered_alias_and_preserves_result(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    existing_result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)
    state.set_last_result(existing_result)

    async def _inner() -> tuple[str, object | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM")
            app.query_one("#sources", DataTable).focus()
            await pilot.press("l")
            await pilot.pause()
            return sql.text, app.state.last_result

    editor_text, last_result = asyncio.run(_inner())

    assert editor_text == 'SELECT * FROM\n"customers"'
    assert last_result == existing_result


def test_insert_starter_select_appends_rendered_select_and_preserves_result(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    existing_result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)
    state.set_last_result(existing_result)

    async def _inner() -> tuple[str, object | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("x")
            await pilot.pause()
            return app.query_one("#sql", TextArea).text, app.state.last_result

    editor_text, last_result = asyncio.run(_inner())

    assert editor_text == 'SELECT *\nFROM "customers"\nLIMIT 10;'
    assert last_result == existing_result


def test_source_insert_error_clears_exportable_result_when_no_source_selected(
    tmp_path: Path,
) -> None:
    state = TUISessionState()
    state.set_last_result(QueryResult(columns=("old",), rows=(("stale",),), elapsed_ms=1.0))

    async def _inner() -> tuple[object | None, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("l")
            await pilot.pause()
            return (
                app.state.last_result,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    last_result, status, message = asyncio.run(_inner())

    assert last_result is None
    assert "No source selected." in status
    assert "No source selected." in message
```

- [ ] **Step 3: Run the new app tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py::test_source_columns_loads_displays_and_disables_export tests/test_tui_app.py::test_source_intelligence_printable_keys_only_work_when_sources_focused tests/test_tui_app.py::test_insert_source_alias_appends_rendered_alias_and_preserves_result tests/test_tui_app.py::test_insert_starter_select_appends_rendered_select_and_preserves_result tests/test_tui_app.py::test_source_insert_error_clears_exportable_result_when_no_source_selected -q
```

Expected: failure because the actions and keybindings do not exist yet.

- [ ] **Step 4: Add imports and keybindings**

Modify the workflow imports in `src/csvql/tui_app.py`:

```python
    inspect_source,
    inspect_source_columns,
    profile_source,
    render_duckdb_identifier,
```

Modify the state import in `src/csvql/tui_app.py`:

```python
    TUISourceColumn,
```

Add these bindings after the existing `w` source binding:

```python
        Binding("c", "show_source_columns", "Columns", show=False),
        Binding("l", "insert_source_alias", "Insert alias", show=False),
        Binding("x", "insert_starter_select", "Starter select", show=False),
```

- [ ] **Step 5: Add source intelligence actions**

Add these methods after `action_sample_source()` in `src/csvql/tui_app.py`:

```python
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
```

- [ ] **Step 6: Add append and formatting helpers**

Add this method after `_show_error()` in `src/csvql/tui_app.py`:

```python
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
```

Add this module helper near `_one_line_sql()`:

```python
def _format_source_columns(alias: str, columns: tuple[TUISourceColumn, ...]) -> str:
    lines = [f"{alias} columns"]
    lines.extend(f"  {column.name} {column.duckdb_type}" for column in columns)
    return "\n".join(lines)
```

- [ ] **Step 7: Add focus gating for new actions**

In `check_action()`, add these actions to `text_entry_actions`:

```python
                "show_source_columns",
                "insert_source_alias",
                "insert_starter_select",
```

Add these actions to `source_actions`:

```python
            "show_source_columns",
            "insert_source_alias",
            "insert_starter_select",
```

- [ ] **Step 8: Run app tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: all `tests/test_tui_app.py` tests pass.

- [ ] **Step 9: Commit Task 3**

Run:

```bash
git add src/csvql/tui_app.py tests/test_tui_app.py
git commit -m "feat: add tui source intelligence actions"
```

Expected: commit succeeds. `.superpowers/` remains untracked.

---

### Task 4: Document Source Intelligence Keymap

**Files:**
- Modify: `src/csvql/tui_help.py`
- Modify: `README.md`
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Write failing help/docs assertions**

Modify `test_help_text_documents_workbench_keymap` in `tests/test_tui_app.py` by adding:

```python
    assert "c                   Load/show selected source columns" in help_text
    assert "l                   Insert selected source alias" in help_text
    assert "x                   Insert SELECT * starter query" in help_text
```

Append this README regression test to `tests/test_tui_app.py`:

```python
def test_readme_documents_source_intelligence_keymap() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "`c` to load/show columns" in readme
    assert "`l` to insert the selected source alias" in readme
    assert "`x` to insert a `SELECT *` starter query" in readme
    assert "Column metadata is session-local" in readme
```

- [ ] **Step 2: Run the docs tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py::test_help_text_documents_workbench_keymap tests/test_tui_app.py::test_readme_documents_source_intelligence_keymap -q
```

Expected: failure because help and README do not document the new actions yet.

- [ ] **Step 3: Update TUI help text**

Modify the `Source pane` section in `src/csvql/tui_help.py` so it contains:

```text
Source pane
  i                   Inspect selected source
  s                   Sample selected source
  p                   Profile selected source
  c                   Load/show selected source columns
  l                   Insert selected source alias
  x                   Insert SELECT * starter query
  a                   Add source
  d                   Remove source
  w                   Save sources to project catalog
```

- [ ] **Step 4: Update README TUI keymap text**

Modify the TUI keymap paragraph in `README.md` to include this sentence:

```markdown
Source Intelligence actions use `c` to load/show columns, `l` to insert the selected source alias, and `x` to insert a `SELECT *` starter query. Column metadata is session-local and is not written to `.csvql.yml`.
```

- [ ] **Step 5: Run docs tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py::test_help_text_documents_workbench_keymap tests/test_tui_app.py::test_readme_documents_source_intelligence_keymap -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add src/csvql/tui_help.py README.md tests/test_tui_app.py
git commit -m "docs: document tui source intelligence"
```

Expected: commit succeeds. `.superpowers/` remains untracked.

---

### Task 5: Final Verification And Manual Proof

**Files:**
- Review: all files changed by Tasks 1 through 4

- [ ] **Step 1: Run focused Source Intelligence tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py tests/test_tui_workflows.py tests/test_tui_app.py -q
```

Expected: all focused TUI tests pass.

- [ ] **Step 2: Run format check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
```

Expected: all files already formatted.

- [ ] **Step 3: Run lint check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
```

Expected: all checks pass.

- [ ] **Step 4: Run type check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src
```

Expected: mypy reports success with no issues.

- [ ] **Step 5: Run full test suite**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest
```

Expected: all tests pass.

- [ ] **Step 6: Run whitespace check**

Run:

```bash
git diff --check HEAD~4 HEAD
```

Expected: no whitespace errors.

- [ ] **Step 7: Run manual TUI proof**

Launch the TUI:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras csvql menu /Users/richarddemke/Desktop/enerflo_payloads.csv
```

Manual proof steps:

- Focus Sources with `F6`.
- Press `c`.
- Confirm the output area shows `enerflo_payloads columns`.
- Confirm the output area shows `name VARCHAR`, `controller_id BIGINT`, `name_1 VARCHAR`, and `payload VARCHAR`.
- Press `l`.
- Confirm the editor contains `"enerflo_payloads"`.
- Clear editor with `F10`.
- Focus Sources with `F6`.
- Press `x`.
- Confirm the editor contains:

```sql
SELECT *
FROM "enerflo_payloads"
LIMIT 10;
```

- Press `F4`.
- Confirm the result grid shows rows from `enerflo_payloads`.
- Focus SQL with `F2`, type `clx`, and confirm those characters type into the editor instead of firing source actions.
- Quit with `F9`.

- [ ] **Step 8: Commit final verification note if docs changed during proof**

If manual proof requires a README or help wording correction, make that correction, rerun the relevant automated check, then run:

```bash
git add README.md src/csvql/tui_help.py tests/test_tui_app.py
git commit -m "docs: refine tui source intelligence proof"
```

Expected: commit succeeds only if proof caused tracked docs or tests to change.

---

## Self-Review Checklist

- Spec coverage: Tasks 1 through 5 cover state, workflow, identifier rendering, app behavior, docs/help, tests, automated gates, and manual proof.
- Scope guard: no CLI command, Python API, project catalog schema, hidden persistence, dataframe, parquet, safe-mode, sandbox, or large-file claim is introduced.
- Result state: Task 3 requires column display and source-intelligence errors to clear exportable state, while successful insertions preserve it.
- Key safety: Task 3 requires `c`, `l`, and `x` focus-gating tests.
- Identifier rendering: Task 2 requires double-quoted DuckDB identifiers and embedded quote doubling.
- Execution order: Tasks are TDD-first and commit after each vertical slice.
