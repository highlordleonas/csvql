# CSVQL Derived Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit TUI action that saves the last successful tabular query result as a CSV-backed derived source under `.csvql/results/` and makes that alias immediately queryable in the current session.

**Architecture:** Extend the TUI-only source model with a `kind` field so original CSV files and derived query results are distinguishable in the existing Sources pane. Add a workflow helper that writes the full stored `QueryResult` to `.csvql/results/{alias}.csv` using the existing CSV export formatter, then returns a `TUISource` registered by the app. Keep DuckDB as the only query engine and keep derived sources as normal CSV-backed sources.

**Tech Stack:** Python 3.11+, DuckDB, Textual, Typer, Rich, pytest, Ruff, mypy, uv.

---

## Scope Check

This plan implements:

- `docs/superpowers/specs/2026-07-01-csvql-derived-sources-design.md`

It does not implement:

- pandas or Polars dataframe helpers
- Parquet reads or writes
- persistent DuckDB scratch databases
- catalog schema changes
- hidden cache or automatic materialization
- safe-mode or sandbox behavior
- public `CSVQLSession` API changes

Resolved implementation decisions:

- Use `F11` as the first Save Result As Source binding.
- Refuse overwrites in this slice.
- Show both `kind` and `origin` in the Sources pane.
- Do not change `.gitignore`; `.csvql/` is already ignored.
- Use temporary directories for manual proof so no repo result artifacts are left behind.

## File Structure

Modify:

- `src/csvql/tui_state.py`: add `SourceKind`, default source kind, and last-result status needed for better save refusal messages.
- `src/csvql/tui_workflows.py`: add `save_derived_result_source`, project-root resolution, duplicate/path validation, and CSV artifact writing.
- `src/csvql/tui_app.py`: add `F11` binding, prompt flow, save action, Sources pane kind column, and status/error handling.
- `src/csvql/tui_help.py`: document `F11` and derived source behavior.
- `README.md`: document Derived Sources v1 in the TUI section.
- `tests/test_tui_state.py`: cover source kind defaults and last-result status transitions.
- `tests/test_tui_workflows.py`: cover CSV artifact writing, project-local path resolution, duplicate aliases, existing files, empty result headers, and joinability.
- `tests/test_tui_app.py`: cover Sources pane kind display, action eligibility, prompt flow, duplicate/overwrite refusal, and help text.

No new dependency, lockfile, CLI command, or config schema file is needed.

---

### Task 1: Add TUI Source Kind And Last-Result Status

**Files:**
- Modify: `src/csvql/tui_state.py`
- Modify: `tests/test_tui_state.py`

- [ ] **Step 1: Write failing state tests**

Add these tests to `tests/test_tui_state.py`:

```python
def test_tui_source_defaults_to_csv_kind(tmp_path: Path) -> None:
    source = TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument")

    assert source.kind == "csv"
    assert source.as_table_source() == TableSource(name="orders", path=tmp_path / "orders.csv")


def test_tui_source_accepts_derived_kind(tmp_path: Path) -> None:
    source = TUISource(
        name="order_names",
        path=tmp_path / ".csvql" / "results" / "order_names.csv",
        origin="session",
        kind="derived",
    )

    assert source.kind == "derived"
    assert source.as_table_source() == TableSource(
        name="order_names",
        path=tmp_path / ".csvql" / "results" / "order_names.csv",
    )


def test_last_result_status_tracks_query_no_result_and_error(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    result = QueryResult(columns=("count",), rows=((2,),), elapsed_ms=7.5)

    assert state.last_result_status == "none"

    sequence = state.begin_query_run("SELECT COUNT(*) FROM orders")
    state.record_query_success(sequence, "SELECT COUNT(*) FROM orders", result)

    assert state.last_result_status == "query"
    assert state.last_result == result

    no_result_sequence = state.begin_query_run("CREATE TABLE scratch AS SELECT 1")
    state.record_query_no_result(no_result_sequence, "CREATE TABLE scratch AS SELECT 1", 2.5)

    assert state.last_result_status == "no_result"
    assert state.last_result is None

    error_sequence = state.begin_query_run("SELECT * FROM missing")
    state.record_query_error(error_sequence, "SELECT * FROM missing", "missing table")

    assert state.last_result_status == "error"
    assert state.last_result is None
```

- [ ] **Step 2: Run state tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py -q
```

Expected result: fail because `TUISource.kind` and `TUISessionState.last_result_status` do not exist.

- [ ] **Step 3: Add kind and last-result status types**

In `src/csvql/tui_state.py`, add these aliases near the existing `SourceOrigin` alias:

```python
SourceOrigin = Literal["argument", "catalog", "session"]
SourceKind = Literal["csv", "derived"]
TUILastResultStatus = Literal["none", "query", "no_result", "error"]
```

Update `TUISource`:

```python
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
```

Add this field to `TUISessionState` after `last_result`:

```python
    last_result_status: TUILastResultStatus = "none"
```

Update result-state methods:

```python
    def set_last_result(self, result: QueryResult) -> None:
        """Store the most recent query result."""

        self.last_result = result
        self.last_result_status = "query"

    def clear_last_result(self) -> None:
        """Clear stored exportable result and visible result state."""

        self.last_result = None
        self.last_result_status = "none"
        self.result_view = TUIResultViewState()
```

Inside `record_query_success`, set the status after assigning `last_result`:

```python
        self.last_result = result
        self.last_result_status = "query"
```

Inside `record_query_no_result`, set the status after `self.clear_last_result()`:

```python
        self.clear_last_result()
        self.last_result_status = "no_result"
```

Inside `record_query_error`, set the status after `self.clear_last_result()`:

```python
        self.clear_last_result()
        self.last_result_status = "error"
```

- [ ] **Step 4: Run state tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py -q
```

Expected result: all `tests/test_tui_state.py` tests pass.

- [ ] **Step 5: Commit state contracts**

Run:

```bash
git add src/csvql/tui_state.py tests/test_tui_state.py
git commit -m "feat: add tui derived source state"
```

---

### Task 2: Add Derived Source Workflow Helper

**Files:**
- Modify: `src/csvql/tui_workflows.py`
- Modify: `tests/test_tui_workflows.py`

- [ ] **Step 1: Write failing workflow tests**

Update the import list in `tests/test_tui_workflows.py` to include `save_derived_result_source`:

```python
from csvql.tui_workflows import (
    build_initial_state,
    export_last_result,
    inspect_source,
    profile_source,
    query_sources,
    run_query_for_tui,
    sample_source,
    save_derived_result_source,
    save_sources_to_project_catalog,
)
```

Add these tests after `test_export_last_result_refuses_overwrite_without_force`:

```python
def test_save_derived_result_source_writes_project_local_csv_and_returns_source(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    initialize_project(project_root)
    result = QueryResult(
        columns=("id", "name"),
        rows=((1, "Ada"), (2, "Bea")),
        elapsed_ms=1.0,
    )

    source = save_derived_result_source(
        result,
        "order_names",
        existing_sources=(),
        start_dir=project_root,
    )

    output_path = project_root / ".csvql" / "results" / "order_names.csv"
    assert output_path.read_text(encoding="utf-8") == "id,name\n1,Ada\n2,Bea\n"
    assert source == TUISource(
        name="order_names",
        path=output_path.resolve(),
        origin="session",
        kind="derived",
    )


def test_save_derived_result_source_uses_start_dir_without_project_catalog(
    tmp_path: Path,
) -> None:
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)

    source = save_derived_result_source(
        result,
        "scratch_ids",
        existing_sources=(),
        start_dir=tmp_path,
    )

    output_path = tmp_path / ".csvql" / "results" / "scratch_ids.csv"
    assert output_path.exists()
    assert source.path == output_path.resolve()
    assert source.kind == "derived"


def test_save_derived_result_source_preserves_empty_result_headers(tmp_path: Path) -> None:
    result = QueryResult(columns=("id", "name"), rows=(), elapsed_ms=1.0)

    source = save_derived_result_source(
        result,
        "empty_names",
        existing_sources=(),
        start_dir=tmp_path,
    )

    assert source.kind == "derived"
    assert (tmp_path / ".csvql" / "results" / "empty_names.csv").read_text(
        encoding="utf-8"
    ) == "id,name\n"


def test_save_derived_result_source_refuses_duplicate_session_alias(tmp_path: Path) -> None:
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)
    existing = (
        TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"),
    )

    with pytest.raises(TableMappingError, match=r"Source alias 'orders' is already loaded"):
        save_derived_result_source(
            result,
            "ORDERS",
            existing_sources=existing,
            start_dir=tmp_path,
        )

    assert not (tmp_path / ".csvql" / "results").exists()


def test_save_derived_result_source_refuses_existing_output_file(tmp_path: Path) -> None:
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)
    output_dir = tmp_path / ".csvql" / "results"
    output_dir.mkdir(parents=True)
    output_path = output_dir / "orders.csv"
    output_path.write_text("id\nexisting\n", encoding="utf-8")

    with pytest.raises(ExportError, match=r"Derived result already exists"):
        save_derived_result_source(
            result,
            "orders",
            existing_sources=(),
            start_dir=tmp_path,
        )

    assert output_path.read_text(encoding="utf-8") == "id\nexisting\n"


def test_build_initial_state_does_not_create_results_directory(tmp_path: Path) -> None:
    state = build_initial_state(csv_path=None, table_mappings=(), start_dir=tmp_path)

    assert state == TUISessionState()
    assert not (tmp_path / ".csvql" / "results").exists()


def test_query_sources_can_join_derived_csv_source(tmp_path: Path) -> None:
    orders_csv = _write_csv(
        tmp_path / "orders.csv",
        "id,total\n1,10\n2,20\n",
    )
    result = QueryResult(columns=("id", "name"), rows=((1, "Ada"), (2, "Bea")), elapsed_ms=1.0)
    derived = save_derived_result_source(
        result,
        "order_names",
        existing_sources=(),
        start_dir=tmp_path,
    )
    orders = TUISource(name="orders", path=orders_csv.resolve(), origin="argument")

    joined = query_sources(
        (orders, derived),
        """
        SELECT orders.id, order_names.name, orders.total
        FROM orders
        JOIN order_names ON order_names.id = orders.id
        ORDER BY orders.id
        """,
    )

    assert joined.columns == ("id", "name", "total")
    assert joined.rows == ((1, "Ada", 10), (2, "Bea", 20))
```

- [ ] **Step 2: Run workflow tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_workflows.py -q
```

Expected result: fail because `save_derived_result_source` does not exist.

- [ ] **Step 3: Add workflow imports and constants**

In `src/csvql/tui_workflows.py`, update imports:

```python
from csvql.exceptions import CSVQLError, ExportError, ProjectConfigError, TableMappingError
```

Add this import:

```python
from csvql.table_mapping import parse_table_mapping, source_from_single_csv, validate_table_alias
```

Add this constant near `_MISSING_PROJECT_PREFIX`:

```python
_DERIVED_RESULTS_DIR = Path(".csvql") / "results"
```

- [ ] **Step 4: Add the derived-source workflow helper**

Add this function after `export_last_result` in `src/csvql/tui_workflows.py`:

```python
def save_derived_result_source(
    result: QueryResult,
    alias: str,
    *,
    existing_sources: Sequence[TUISource],
    start_dir: Path,
) -> TUISource:
    """Write a query result as a project-local CSV and return a derived source."""

    source_name = validate_table_alias(alias)
    for source in existing_sources:
        if source.name.casefold() == source_name.casefold():
            raise TableMappingError(
                f"Source alias '{source_name}' is already loaded in the TUI session.",
                suggestion="Choose a unique alias for the derived result source.",
            )

    result_root = _derived_result_root(start_dir)
    result_dir = result_root / _DERIVED_RESULTS_DIR
    output_path = (result_dir / f"{source_name}.csv").resolve(strict=False)
    if output_path.exists():
        raise ExportError(
            f"Derived result already exists at {output_path}.",
            suggestion="Choose a different alias for this derived result source.",
        )

    try:
        result_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError(
            f"Failed to create derived results directory: {result_dir}",
            suggestion="Check that the project directory is writable.",
        ) from exc

    content = format_query_result_for_export(result, ExportFormat.csv)
    try:
        write_export_file(output_path, content)
    except ExportError as exc:
        raise ExportError(
            f"Failed to write derived source to {output_path}.",
            suggestion="Check that the derived results directory is writable.",
        ) from exc

    return TUISource(
        name=source_name,
        path=output_path,
        origin="session",
        kind="derived",
    )
```

Add this helper near `_load_or_initialize_project`:

```python
def _derived_result_root(start_dir: Path) -> Path:
    try:
        return load_project(start_dir).project_root
    except ProjectConfigError as exc:
        if exc.message.startswith(_MISSING_PROJECT_PREFIX):
            return start_dir.expanduser().resolve()
        raise
```

- [ ] **Step 5: Run workflow tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_workflows.py -q
```

Expected result: all `tests/test_tui_workflows.py` tests pass.

- [ ] **Step 6: Commit workflow helper**

Run:

```bash
git add src/csvql/tui_workflows.py tests/test_tui_workflows.py
git commit -m "feat: save derived result sources"
```

---

### Task 3: Add TUI Save Result As Source Action

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Write failing app tests**

Add these tests to `tests/test_tui_app.py` after `test_export_last_result_writes_file_when_result_exists`:

```python
def test_sources_pane_shows_source_kind(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    state.add_source(
        TUISource(
            name="order_names",
            path=tmp_path / ".csvql" / "results" / "order_names.csv",
            origin="session",
            kind="derived",
        )
    )

    async def _inner() -> tuple[tuple[str, ...], int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sources = app.query_one("#sources", DataTable)
            return tuple(str(column.label) for column in sources.columns.values()), sources.row_count

    columns, row_count = asyncio.run(_inner())

    assert columns == ("alias", "kind", "path", "origin")
    assert row_count == 2


def test_save_result_as_source_requires_query_result(tmp_path: Path) -> None:
    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    status, message = asyncio.run(_inner())

    assert "Run a query before saving a result as a source." in status
    assert "Run a query before saving a result as a source." in message
    assert not (tmp_path / ".csvql" / "results").exists()


def test_save_result_as_source_writes_csv_and_adds_derived_source(tmp_path: Path) -> None:
    state = TUISessionState()
    state.set_last_result(
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=12.345,
        )
    )

    async def _inner() -> tuple[tuple[TUISource, ...], str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()

            alias_input = app.screen.query_one("#derived-source-alias", Input)
            alias_input.value = "customer_emails"
            await pilot.press("enter")
            await pilot.pause()

            output_path = tmp_path / ".csvql" / "results" / "customer_emails.csv"
            return (
                app.state.sources,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                output_path.read_text(encoding="utf-8"),
            )

    sources, status, message, content = asyncio.run(_inner())

    assert sources == (
        TUISource(
            name="customer_emails",
            path=(tmp_path / ".csvql" / "results" / "customer_emails.csv").resolve(),
            origin="session",
            kind="derived",
        ),
    )
    assert state.selected_alias == "customer_emails"
    assert "Saved result as derived source customer_emails" in status
    assert "Saved result as derived source customer_emails" in message
    assert content == "customer_id,email\nCUST-001,alex@example.com\n"


def test_save_result_as_source_refuses_after_no_result_statement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_last_result(QueryResult(columns=("old",), rows=(("stale",),), elapsed_ms=1.0))

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        from csvql.tui_state import TUIQueryOutcome

        return TUIQueryOutcome.no_result(sequence=sequence, sql=sql, elapsed_ms=4.0)

    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("CREATE TABLE scratch(id INTEGER)")
            await pilot.press("f4")
            await pilot.pause(0.2)

            await pilot.press("f11")
            await pilot.pause()

            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    status, message = asyncio.run(_inner())

    assert "The last statement did not produce a tabular result." in status
    assert "The last statement did not produce a tabular result." in message
    assert not (tmp_path / ".csvql" / "results").exists()


def test_save_result_as_source_refuses_duplicate_alias(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    state.set_last_result(QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0))

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()

            alias_input = app.screen.query_one("#derived-source-alias", Input)
            alias_input.value = "customers"
            await pilot.press("enter")
            await pilot.pause()

            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    status, message = asyncio.run(_inner())

    assert "Source alias 'customers' is already loaded" in status
    assert "Source alias 'customers' is already loaded" in message
    assert not (tmp_path / ".csvql" / "results").exists()
```

Update `test_printable_workbench_action_keys_type_in_sql_editor` so the printable-key list remains explicit and unchanged:

```python
            for key in ["?", "q", "i", "s", "p", "a", "d", "w", "r"]:
                await pilot.press(key)
```

No printable key is added for Save Result As Source because the plan uses `F11`.

- [ ] **Step 2: Run app tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected result: fail because the Sources pane has no `kind` column and `F11` is not bound.

- [ ] **Step 3: Update imports and bindings**

In `src/csvql/tui_app.py`, add `save_derived_result_source` to the workflow imports:

```python
from csvql.tui_workflows import (
    build_initial_state,
    export_last_result,
    inspect_source,
    profile_source,
    run_query_for_tui,
    sample_source,
    save_derived_result_source,
    save_sources_to_project_catalog,
)
```

Add this binding to `BINDINGS` after `F10`:

```python
        Binding("f11", "save_result_as_source", "Save result source", priority=True),
```

- [ ] **Step 4: Add the TUI action and callback**

Add this action after `action_export_last_result`:

```python
    def action_save_result_as_source(self) -> None:
        result = self.state.last_result
        if result is None:
            if self.state.last_result_status == "no_result":
                self._show_error(CSVQLError("The last statement did not produce a tabular result."))
                return
            self._show_error(CSVQLError("Run a query before saving a result as a source."))
            return

        self.push_screen(
            _PromptInputScreen("Enter a derived source alias.", input_id="derived-source-alias"),
            callback=self._handle_save_result_as_source,
        )
```

Add this callback after `_handle_export_last_result`:

```python
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
        message = f"Saved result as derived source {source.name} at {source.path}."
        self._set_status(message)
        self.query_one("#results-message", Static).update(message)
```

- [ ] **Step 5: Show kind in the Sources pane**

Update `_refresh_sources_table`:

```python
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
```

- [ ] **Step 6: Run app tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected result: all `tests/test_tui_app.py` tests pass.

- [ ] **Step 7: Commit app integration**

Run:

```bash
git add src/csvql/tui_app.py tests/test_tui_app.py
git commit -m "feat: add tui derived source action"
```

---

### Task 4: Document Derived Sources In Help And README

**Files:**
- Modify: `src/csvql/tui_help.py`
- Modify: `README.md`
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Write failing help assertion**

Find the existing help-modal test in `tests/test_tui_app.py` that asserts help text contains `F4 / Ctrl+Enter`. Add these assertions:

```python
    assert "F11" in help_text
    assert "Save last tabular result as a derived source" in help_text
```

- [ ] **Step 2: Run the focused help test and verify it fails**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q -k help
```

Expected result: fail because the help text does not mention `F11`.

- [ ] **Step 3: Update TUI help text**

In `src/csvql/tui_help.py`, update the `General` section:

```python
General
  F1                  Help
  ?                   Help outside the SQL editor
  F7                  Export last tabular result
  F11                 Save last tabular result as a derived source
  F9                  Quit
  Esc                 Close help or modal
```

- [ ] **Step 4: Update README TUI section**

In `README.md`, add this paragraph after the paragraph that starts with `Ctrl+N`:

```markdown
`F11` saves the last successful tabular query result as a derived source. CSVQL
prompts for an alias, writes `.csvql/results/{alias}.csv`, and adds that alias
to the Sources pane with kind `derived` so it can be queried or joined later in
the same TUI session. Derived result sources are explicit CSV-backed artifacts,
not hidden cache. They use the same trusted local DuckDB SQL posture as other
CSVQL sources.
```

- [ ] **Step 5: Run help and docs-adjacent tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py tests/test_cli_menu.py -q
```

Expected result: all selected tests pass.

- [ ] **Step 6: Commit docs and help**

Run:

```bash
git add README.md src/csvql/tui_help.py tests/test_tui_app.py
git commit -m "docs: document tui derived sources"
```

---

### Task 5: Run Full Verification And Manual Proof

**Files:**
- No planned file edits.
- Generated manual proof files should live under `/private/tmp`.

- [ ] **Step 1: Run focused TUI tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py tests/test_tui_workflows.py tests/test_tui_app.py -q
```

Expected result: all selected tests pass.

- [ ] **Step 2: Run formatting check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
```

Expected result: all files already formatted.

- [ ] **Step 3: Run lint**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
```

Expected result: all checks pass.

- [ ] **Step 4: Run type check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src
```

Expected result: success with no issues in source files.

- [ ] **Step 5: Run the full pytest suite**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest
```

Expected result: full suite passes.

- [ ] **Step 6: Run diff whitespace check**

Run:

```bash
git diff --check
```

Expected result: no output and exit code `0`.

- [ ] **Step 7: Manual proof in a temporary project**

Create a temporary proof directory and CSV:

```bash
proof_dir="$(mktemp -d /private/tmp/csvql-derived-sources.XXXXXX)"
printf 'id,name\n1,Ada\n2,Bea\n' > "$proof_dir/orders.csv"
printf 'id,total\n1,10\n2,20\n' > "$proof_dir/payments.csv"
```

Launch the TUI:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras csvql menu --table orders="$proof_dir/orders.csv" --table payments="$proof_dir/payments.csv"
```

Manual steps:

1. Run `SELECT id, name FROM orders ORDER BY id;`.
2. Press `F11`.
3. Save the result as `order_names`.
4. Confirm the Sources pane shows `order_names` with kind `derived`.
5. Run:

```sql
SELECT order_names.id, order_names.name, payments.total
FROM order_names
JOIN payments USING (id)
ORDER BY order_names.id;
```

6. Confirm the join returns two rows.
7. Quit with `F9`.
8. Confirm `$proof_dir/.csvql/results/order_names.csv` exists and contains:

```text
id,name
1,Ada
2,Bea
```

- [ ] **Step 8: Stop for concrete follow-up if verification fails**

If any verification command fails after Tasks 1-4 are complete, inspect the
failing output, identify the exact files and behavior involved, and write a
focused follow-up task before editing. Do not batch unknown fixes into a vague
final cleanup commit. If all verification passes, do not create an empty commit.

---

## Final Handoff Checklist

Before final response:

- [ ] Confirm `git status --short --branch`.
- [ ] Confirm `.superpowers/` remains untracked unless the user separately approves tracking it.
- [ ] Report commits created during implementation.
- [ ] Report verification commands and results.
- [ ] State any skipped manual proof or residual risk.
- [ ] Do not claim sandbox safety, production readiness, Parquet support, dataframe support, or large-result performance.
