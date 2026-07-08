# TUI SQL Assistance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic local SQL assistance for `csvql menu`: richer source inspection, metadata-aware starter templates, and explicit SQL-editor completion.

**Architecture:** Keep SQL generation and completion decisions in a focused helper module, then wire those helpers into the existing Textual TUI. Generated templates may declare generated SQL range aliases; normal SQL-editor completion never inserts generated range aliases and never parses freeform SQL.

**Tech Stack:** Python 3.11+, Textual 8.2.8, DuckDB, Ruff, mypy, pytest, uv.

## Global Constraints

- LocalQL remains the installable distribution name.
- Runtime surfaces remain `csvql` CLI, `csvql` import package, `.csvql.yml`, and `csvql menu`.
- User-authored SQL remains trusted local DuckDB SQL.
- No NLP, natural-language query generation, AI insight generation, hidden execution, or automatic background file scans while typing.
- No SQL parser, completion engine, or new runtime/development dependency by default.
- Do not change dependencies, `uv.lock`, or package metadata without separate approval.
- Do not add a web app, cloud connectors, dataframe-first API, plugin system, or platform behavior.
- Do not claim sandbox safety, safe untrusted SQL, production readiness, broad large-file proof, hidden cache/materialization, or `v1-stable`.
- Do not tag, publish, upload artifacts, change version, configure remotes, push, run hosted CI, or create a GitHub release.
- Use repo-local `uv`; do not install global dependencies.
- Before code/test edits, use `python-codebase-standards`.
- Before behavior or guard-test changes, use `superpowers:test-driven-development` unless the executor embeds failing-test-first steps.
- Before completion claims, use `superpowers:verification-before-completion`.

---

## File Structure

Create:

- `src/csvql/tui_sql_assist.py`: pure helper module for type classification, generated aliases, template SQL, completion items, and replacement spans.
- `tests/test_tui_sql_assist.py`: focused unit coverage for all helper behavior.

Modify:

- `src/csvql/tui_app.py`: Textual bindings, template picker, completion picker, completion insertion, richer inspect rendering.
- `src/csvql/tui_help.py`: in-app help text for `x`, `Ctrl+Space`, and source intelligence behavior.
- `README.md`: user-facing TUI keymap and local deterministic SQL assistance wording.
- `docs/tui-guide.md`: focused guide update for starter templates and completion.
- `docs/release-notes/v1.md`: v1 TUI contract wording without release-status escalation.
- `tests/test_tui_app.py`: interaction tests for `i`, `x`, completion, and no hidden work.

No dependency, lockfile, package metadata, CI, release, or remote files are in scope.

---

### Task 1: SQL Assistance Helper Module

**Files:**
- Create: `src/csvql/tui_sql_assist.py`
- Create: `tests/test_tui_sql_assist.py`

**Interfaces:**
- Consumes: `csvql.tui_state.TUISource`, `csvql.tui_state.TUISourceColumn`, `csvql.tui_workflows.render_duckdb_identifier`.
- Produces:
  - `ColumnKind = Literal["numeric", "date_trend", "time_only", "text", "unknown"]`
  - `SQLAssistColumn(name: str, duckdb_type: str, kind: ColumnKind)`
  - `SQLAssistSource(name: str, columns: tuple[SQLAssistColumn, ...])`
  - `SQLTemplateOption(key: str, label: str, detail: str, sql: str, requires_columns: bool)`
  - `SQLCompletionItem(key: str, label: str, detail: str, insert_text: str, item_kind: Literal["source", "column", "keyword", "snippet"])`
  - `CompletionEdit(start_index: int, end_index: int, replacement: str)`
  - `classify_duckdb_type(duckdb_type: str) -> ColumnKind`
  - `safe_generated_identifier(stem: str, *, reserved_prefix: str) -> str`
  - `make_range_aliases(source_names: Sequence[str]) -> dict[str, str]`
  - `make_output_alias(prefix: str, column_name: str, used_aliases: set[str]) -> str`
  - `build_assist_sources(sources: Sequence[TUISource], columns_by_source: Mapping[str, Sequence[TUISourceColumn]]) -> tuple[SQLAssistSource, ...]`
  - `build_template_options(sources: Sequence[SQLAssistSource], selected_source_name: str) -> tuple[SQLTemplateOption, ...]`
  - `build_completion_items(sources: Sequence[SQLAssistSource], *, text: str, cursor_index: int) -> tuple[SQLCompletionItem, ...]`
  - `completion_edit(text: str, selection_start: int, selection_end: int, item: SQLCompletionItem) -> CompletionEdit`

- [ ] **Step 1: Write failing helper tests**

Create `tests/test_tui_sql_assist.py` with these tests:

```python
from csvql.tui_sql_assist import (
    CompletionEdit,
    SQLAssistColumn,
    SQLAssistSource,
    build_completion_items,
    build_template_options,
    classify_duckdb_type,
    completion_edit,
    make_output_alias,
    make_range_aliases,
    safe_generated_identifier,
)


def _source(name: str, *columns: SQLAssistColumn) -> SQLAssistSource:
    return SQLAssistSource(name=name, columns=columns)


def test_classify_duckdb_type_splits_date_timestamp_and_time_only() -> None:
    assert classify_duckdb_type("DOUBLE") == "numeric"
    assert classify_duckdb_type("DECIMAL(12,2)") == "numeric"
    assert classify_duckdb_type("DATE") == "date_trend"
    assert classify_duckdb_type("TIMESTAMP") == "date_trend"
    assert classify_duckdb_type("TIME") == "time_only"
    assert classify_duckdb_type("VARCHAR") == "text"
    assert classify_duckdb_type("STRUCT(a INTEGER)") == "unknown"


def test_generated_identifiers_are_safe_and_reserved_words_are_prefixed() -> None:
    assert safe_generated_identifier("Customer ID", reserved_prefix="col_") == "customer_id"
    assert safe_generated_identifier("select", reserved_prefix="col_") == "col_select"
    assert safe_generated_identifier("2026 total", reserved_prefix="col_") == "col_2026_total"


def test_range_aliases_are_deterministic_collision_safe_and_reserved_safe() -> None:
    assert make_range_aliases(("revenue_movements", "revenue_metrics")) == {
        "revenue_movements": "rm",
        "revenue_metrics": "rm_2",
    }
    assert make_range_aliases(("select",)) == {"select": "t_select"}


def test_output_aliases_sanitize_spaced_mixed_case_and_reserved_columns() -> None:
    used: set[str] = set()
    assert make_output_alias("non_null", "Customer ID", used) == "non_null_customer_id"
    assert make_output_alias("sum", "select", used) == "sum_col_select"
    assert make_output_alias("sum", "select", used) == "sum_col_select_2"


def test_templates_include_metadata_free_options_without_columns() -> None:
    options = build_template_options((_source("customers"),), "customers")
    assert [option.key for option in options] == ["preview", "row_count"]
    assert options[0].sql == 'SELECT *\nFROM "customers"\nLIMIT 10;'
    assert options[1].sql == 'SELECT COUNT(*) AS row_count\nFROM "customers";'


def test_templates_use_first_deterministic_eligible_columns() -> None:
    source = _source(
        "revenue_movements",
        SQLAssistColumn("movement_id", "VARCHAR", "text"),
        SQLAssistColumn("mrr_delta", "DOUBLE", "numeric"),
        SQLAssistColumn("movement_month", "DATE", "date_trend"),
        SQLAssistColumn("created_at_time", "TIME", "time_only"),
    )
    sql_by_key = {option.key: option.sql for option in build_template_options((source,), source.name)}

    assert 'COUNT(rm."mrr_delta") AS non_null_mrr_delta' in sql_by_key["numeric_summary"]
    assert 'rm."movement_id"' in sql_by_key["text_grouping"]
    assert 'date_trunc(\'month\', rm."movement_month") AS month' in sql_by_key["date_trend"]
    assert "created_at_time" not in sql_by_key["date_trend"]
    assert 'COUNT(rm."movement_id") AS non_null_movement_id' in sql_by_key["missingness"]


def test_join_template_requires_exact_shared_column() -> None:
    left = _source("orders", SQLAssistColumn("customer_id", "VARCHAR", "text"))
    right = _source("customers", SQLAssistColumn("customer_id", "VARCHAR", "text"))
    no_match = _source("products", SQLAssistColumn("product_id", "VARCHAR", "text"))

    with_join = {option.key: option.sql for option in build_template_options((left, right), "orders")}
    without_join = {option.key: option.sql for option in build_template_options((left, no_match), "orders")}

    assert 'JOIN "customers" AS c' in with_join["join_customer_id"]
    assert 'ON o."customer_id" = c."customer_id"' in with_join["join_customer_id"]
    assert not any(key.startswith("join_") for key in without_join)


def test_single_source_completion_uses_bare_columns() -> None:
    source = _source("customers", SQLAssistColumn("customer_id", "VARCHAR", "text"))
    items = build_completion_items((source,), text="SELECT cust", cursor_index=len("SELECT cust"))

    column_items = [item for item in items if item.item_kind == "column"]
    assert len(column_items) == 1
    assert column_items[0].insert_text == "customer_id"


def test_multi_source_completion_uses_source_qualified_columns() -> None:
    customers = _source("customers", SQLAssistColumn("customer_id", "VARCHAR", "text"))
    orders = _source("orders", SQLAssistColumn("customer_id", "VARCHAR", "text"))

    items = build_completion_items((customers, orders), text="SELECT ", cursor_index=len("SELECT "))
    inserts = {item.insert_text for item in items if item.item_kind == "column"}

    assert '"customers"."customer_id"' in inserts
    assert '"orders"."customer_id"' in inserts
    assert not any(insert.startswith("c.") or insert.startswith("o.") for insert in inserts)


def test_unknown_qualifier_does_not_infer_range_alias() -> None:
    source = _source("revenue_movements", SQLAssistColumn("mrr_delta", "DOUBLE", "numeric"))
    items = build_completion_items((source,), text="SELECT rm.", cursor_index=len("SELECT rm."))

    assert [item for item in items if item.item_kind == "column"] == []


def test_source_qualified_prefix_returns_source_qualified_columns() -> None:
    source = _source("revenue_movements", SQLAssistColumn("mrr_delta", "DOUBLE", "numeric"))
    text = 'SELECT "revenue_movements".'
    items = build_completion_items((source,), text=text, cursor_index=len(text))

    assert [item.insert_text for item in items if item.item_kind == "column"] == [
        '"revenue_movements"."mrr_delta"'
    ]


def test_completion_edit_replaces_selection_or_current_token_prefix() -> None:
    items = build_completion_items(
        (_source("customers", SQLAssistColumn("customer_id", "VARCHAR", "text")),),
        text="SELECT cust",
        cursor_index=len("SELECT cust"),
    )
    column_item = next(item for item in items if item.item_kind == "column")

    prefix_edit = completion_edit(
        "SELECT cust",
        len("SELECT cust"),
        len("SELECT cust"),
        column_item,
    )
    selection_edit = completion_edit("SELECT abc", len("SELECT "), len("SELECT abc"), column_item)

    assert prefix_edit == CompletionEdit(
        start_index=len("SELECT "),
        end_index=len("SELECT cust"),
        replacement=column_item.insert_text,
    )
    assert selection_edit == CompletionEdit(
        start_index=len("SELECT "),
        end_index=len("SELECT abc"),
        replacement=column_item.insert_text,
    )
```

- [ ] **Step 2: Run the helper tests and verify failure**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_sql_assist.py -q
```

Expected: import failure for `csvql.tui_sql_assist`.

- [ ] **Step 3: Implement the helper module**

Create `src/csvql/tui_sql_assist.py` with the dataclasses and functions named in this task. Keep it pure: no file reads, no DuckDB execution, no Textual imports.

Use these constants and helpers:

```python
_RESERVED_GENERATED_IDENTIFIERS = {
    "all",
    "and",
    "as",
    "by",
    "case",
    "cast",
    "create",
    "delete",
    "from",
    "group",
    "insert",
    "join",
    "limit",
    "not",
    "null",
    "or",
    "order",
    "select",
    "table",
    "update",
    "where",
    "with",
}

_KEYWORD_SNIPPETS = (
    ("select_from", "SELECT ... FROM ...", "SELECT *\nFROM "),
    ("where", "WHERE", "WHERE "),
    ("group_by", "GROUP BY", "GROUP BY "),
    ("order_by", "ORDER BY", "ORDER BY "),
    ("count", "COUNT(*)", "COUNT(*)"),
)
```

Use `render_duckdb_identifier()` for source and column references. Use `[a-z_][a-z0-9_]*` generated aliases after lowercasing and replacing every non-alphanumeric run with `_`.

- [ ] **Step 4: Run helper tests and verify pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_sql_assist.py -q
```

Expected: all tests in `tests/test_tui_sql_assist.py` pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/csvql/tui_sql_assist.py tests/test_tui_sql_assist.py
git commit -m "feat: add tui sql assistance helpers"
```

---

### Task 2: TUI Integration For Inspect, Templates, And Completion

**Files:**
- Modify: `src/csvql/tui_app.py`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes Task 1 helpers.
- Produces TUI actions:
  - `action_insert_starter_select()` opens a template picker for `x`.
  - `action_open_sql_completion()` opens completion from the SQL editor.
  - `_apply_template_option(option: SQLTemplateOption) -> None`
  - `_apply_completion_item(item: SQLCompletionItem) -> None`
  - `_replace_sql_editor_text(start_index: int, end_index: int, replacement: str) -> None`

- [ ] **Step 1: Add failing interaction tests for richer inspect**

Add this test near the existing source-intelligence tests in `tests/test_tui_app.py`:

```python
def test_inspect_source_is_distinct_from_columns_and_loads_completion_metadata(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[tuple[str, ...], tuple[str, ...], tuple[TUISourceColumn, ...], str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("i")
            await pilot.pause()

            table = app.query_one("#results", DataTable)
            headers = tuple(str(column.label) for column in table.columns.values())
            values = tuple(str(table.get_cell_at(Coordinate(row, 0))) for row in range(table.row_count))
            return headers, values, app.state.source_columns("customers"), app.query_one("#status", Static).content

    headers, values, cached_columns, status = asyncio.run(_inner())

    assert headers == ("field", "value")
    assert "source alias/table name" in values
    assert "column count" in values
    assert cached_columns == (
        TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),
        TUISourceColumn(name="email", duckdb_type="VARCHAR"),
    )
    assert "customers: 2 columns inspected." in status
```

- [ ] **Step 2: Add failing interaction tests for `x` template picker**

Add:

```python
def test_starter_picker_offers_metadata_free_templates_without_loading_columns(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("x")
            await pilot.pause()
            screen_name = type(app.screen).__name__
            table = app.screen.query_one("#sql-assist-options", DataTable)
            first_label = str(table.get_cell_at(Coordinate(0, 0)))
            await pilot.press("enter")
            await pilot.pause()
            return screen_name, app.query_one("#sql", TextArea).text

    screen_name, editor_text = asyncio.run(_inner())

    assert screen_name == "_SQLAssistPickerScreen"
    assert editor_text == 'SELECT *\nFROM "customers"\nLIMIT 10;'
```

```python
def test_starter_picker_adds_column_templates_after_columns_are_loaded(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[tuple[str, ...], str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            table = app.screen.query_one("#sql-assist-options", DataTable)
            labels = tuple(str(table.get_cell_at(Coordinate(row, 0))) for row in range(table.row_count))
            return labels, app.query_one("#status", Static).content

    labels, status = asyncio.run(_inner())

    assert "Preview rows" in labels
    assert "Row count" in labels
    assert "Group by category" in labels
    assert "Press c or i for column-aware templates" not in status
```

- [ ] **Step 3: Add failing interaction tests for completion**

Add:

```python
def test_sql_completion_single_source_replaces_token_with_bare_column(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    state.set_source_columns(
        "customers",
        (
            TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),
            TUISourceColumn(name="email", duckdb_type="VARCHAR"),
        ),
    )

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT cust")
            sql.move_cursor((0, len("SELECT cust")))
            await pilot.press("ctrl+space")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            return sql.text

    assert asyncio.run(_inner()) == "SELECT customer_id"
```

```python
def test_sql_completion_multi_source_uses_source_qualified_column(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    orders_csv = tmp_path / "orders.csv"
    orders_csv.write_text("customer_id,total\nCUST-001,10\n", encoding="utf-8")
    state.add_source(TUISource(name="orders", path=orders_csv, origin="argument"))
    state.set_source_columns("customers", (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),))
    state.set_source_columns("orders", (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),))

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT ")
            sql.move_cursor((0, len("SELECT ")))
            await pilot.press("ctrl+space")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            return sql.text

    assert asyncio.run(_inner()).startswith('SELECT "customers"."customer_id"')
```

```python
def test_sql_completion_unknown_range_alias_prefix_has_no_column_items(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    state.set_source_columns("customers", (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),))

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT rm.")
            sql.move_cursor((0, len("SELECT rm.")))
            await pilot.press("ctrl+space")
            await pilot.pause()
            return type(app.screen).__name__, app.query_one("#status", Static).content

    screen_name, status = asyncio.run(_inner())

    assert screen_name == "CSVQLMenuApp"
    assert "No completion items" in status
```

- [ ] **Step 4: Implement Textual picker and actions**

In `src/csvql/tui_app.py`:

- Import Task 1 helpers.
- Add `Binding("ctrl+space", "open_sql_completion", "Complete SQL", show=False)`.
- Add `_SQLAssistPickerScreen(ModalScreen[str | None])` using a `DataTable(id="sql-assist-options")` with `label`, `kind`, and `detail` columns. Store choices in a `dict[str, SQLTemplateOption | SQLCompletionItem]` keyed by row key string.
- Change `_SourceInspectOutcome` to carry `InspectResult` and columns.
- Change inspect worker to call `inspect_source(source)` once and pass the full result to `_SourceInspectOutcome`.
- Add `_show_source_inspect_table()` that renders rows such as source alias/table name, origin, display path, row-count status, column count, delimiter, quote, escape, header, encoding, warnings, then updates cached columns.
- Change `action_insert_starter_select()` to build template options and push `_SQLAssistPickerScreen`.
- Add `action_open_sql_completion()` that only runs from the SQL editor, builds completion items from loaded metadata, and never inspects sources.
- Add `_text_location_from_index(text: str, index: int) -> tuple[int, int]` next to `_text_index_from_location()`.
- Add `_replace_sql_editor_text()` using `TextArea.load_text()` and `TextArea.move_cursor()`.

- [ ] **Step 5: Run focused interaction tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_inspect_source_is_distinct_from_columns_and_loads_completion_metadata \
  tests/test_tui_app.py::test_starter_picker_offers_metadata_free_templates_without_loading_columns \
  tests/test_tui_app.py::test_starter_picker_adds_column_templates_after_columns_are_loaded \
  tests/test_tui_app.py::test_sql_completion_single_source_replaces_token_with_bare_column \
  tests/test_tui_app.py::test_sql_completion_multi_source_uses_source_qualified_column \
  tests/test_tui_app.py::test_sql_completion_unknown_range_alias_prefix_has_no_column_items -q
```

Expected: all listed tests pass.

- [ ] **Step 6: Add no-hidden-work regression tests**

Add tests that monkeypatch `csvql.tui_app.inspect_source`, `inspect_source_columns`, `sample_source`, `profile_source`, `run_query_for_tui`, and `run_buffer_for_tui` to raise `AssertionError`. Open completion and template picker; assert no patched function is called until the user explicitly runs SQL.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/csvql/tui_app.py tests/test_tui_app.py
git commit -m "feat: wire tui sql assistance"
```

---

### Task 3: User-Facing TUI Docs And Help

**Files:**
- Modify: `src/csvql/tui_help.py`
- Modify: `README.md`
- Modify: `docs/tui-guide.md`
- Modify: `docs/release-notes/v1.md`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes Task 2 keybindings and behavior.
- Produces docs that describe deterministic local SQL assistance without AI, hidden execution, sandbox safety, production readiness, or large-file claims.

- [ ] **Step 1: Add failing docs tests**

Add to `tests/test_tui_app.py`:

```python
def test_help_text_documents_sql_assistance_keymap() -> None:
    from csvql.tui_help import WORKBENCH_HELP

    assert "Ctrl+Space          Complete SQL from loaded source metadata" in WORKBENCH_HELP
    assert "x                   Open starter SQL templates" in WORKBENCH_HELP
    assert "i                   Inspect selected source and load columns" in WORKBENCH_HELP
```

```python
def test_readme_documents_deterministic_sql_assistance() -> None:
    readme = _normalized_markdown_text(_read_readme_text())

    assert "Ctrl+Space opens explicit SQL completion from loaded source metadata" in readme
    assert "`x` opens deterministic starter SQL templates" in readme
    assert "Generated SQL is inserted into the editor and does not run until you run it" in readme
    assert "natural-language" not in readme.lower()
```

```python
def test_tui_guide_documents_completion_and_templates_without_ai_claims() -> None:
    guide = _normalized_markdown_text(_read_doc_text("docs/tui-guide.md"))

    assert "`Ctrl+Space` opens explicit SQL completion" in guide
    assert "column-aware templates appear after `c` or `i` loads metadata" in guide
    assert "Generated SQL is editable and does not execute automatically" in guide
    assert "AI insight" not in guide
```

- [ ] **Step 2: Run docs tests and verify failure**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_help_text_documents_sql_assistance_keymap \
  tests/test_tui_app.py::test_readme_documents_deterministic_sql_assistance \
  tests/test_tui_app.py::test_tui_guide_documents_completion_and_templates_without_ai_claims -q
```

Expected: failures because docs and help still describe the old single starter query.

- [ ] **Step 3: Update help and docs**

Update:

- `src/csvql/tui_help.py`: Source actions and SQL editor sections.
- `README.md`: TUI section around source intelligence and editor workflow.
- `docs/tui-guide.md`: keymap table and source intelligence section.
- `docs/release-notes/v1.md`: TUI contract bullets only; do not change release status.

Use installed-command examples such as `csvql menu`; keep `uv run --all-extras csvql menu` only in source-checkout/developer context.

- [ ] **Step 4: Run docs tests and verify pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_help_text_documents_sql_assistance_keymap \
  tests/test_tui_app.py::test_readme_documents_deterministic_sql_assistance \
  tests/test_tui_app.py::test_tui_guide_documents_completion_and_templates_without_ai_claims -q
```

Expected: all listed docs tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/csvql/tui_help.py README.md docs/tui-guide.md docs/release-notes/v1.md tests/test_tui_app.py
git commit -m "docs: document tui sql assistance"
```

---

### Task 4: Full Verification And Review

**Files:**
- No new files.
- Review: `src/csvql/tui_sql_assist.py`, `src/csvql/tui_app.py`, `src/csvql/tui_help.py`, `README.md`, `docs/tui-guide.md`, `docs/release-notes/v1.md`, `tests/test_tui_sql_assist.py`, `tests/test_tui_app.py`

**Interfaces:**
- Consumes all previous tasks.
- Produces verified local implementation state, not release status.

- [ ] **Step 1: Run focused tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_sql_assist.py \
  tests/test_tui_app.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run formatting and lint**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff format --check src tests
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check
```

Expected: both commands exit 0.

- [ ] **Step 3: Run type check**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run mypy src
```

Expected: exits 0.

- [ ] **Step 4: Run full pytest**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest
```

Expected: full suite passes.

- [ ] **Step 5: Run claim-boundary scans**

```bash
rg -n "natural-language|AI insight|hidden execution|safe untrusted|safe-untrusted|sandbox-safe|sandbox safety|production ready|production-readiness|large-file proven|large file proven|v1-stable" README.md docs src tests
```

Expected: only intentional boundary language appears.

- [ ] **Step 6: Review diff before completion**

```bash
git diff -- src/csvql/tui_sql_assist.py src/csvql/tui_app.py src/csvql/tui_help.py README.md docs/tui-guide.md docs/release-notes/v1.md tests/test_tui_sql_assist.py tests/test_tui_app.py
git status --short --branch
```

Expected: diff is scoped to SQL assistance; no dependency, lockfile, CI, release, tag, or remote changes.

- [ ] **Step 7: Commit Task 4 only if previous tasks were not already committed**

If previous tasks were committed separately, skip this step. If execution was intentionally batched, run:

```bash
git add src/csvql/tui_sql_assist.py src/csvql/tui_app.py src/csvql/tui_help.py README.md docs/tui-guide.md docs/release-notes/v1.md tests/test_tui_sql_assist.py tests/test_tui_app.py
git commit -m "feat: add deterministic tui sql assistance"
```

---

## Self-Review

- Spec coverage: The plan covers richer `i`, explicit `c`, `x` starter templates, `Ctrl+Space` completion, no generated range aliases in editor completion, deterministic generated identifiers, no hidden execution, no auto file reads, no dependency changes, docs/help, and verification.
- Red-flag scan: This plan contains concrete file paths, function names, commands, expected outcomes, and test code.
- Type consistency: Task 1 defines the helper dataclasses/functions that Task 2 consumes. Task 2 exposes only app-private integration helpers. Task 3 consumes Task 2 user-facing behavior.
- Scope control: No web app, NLP, SQL parser, new dependency, lockfile, package metadata, CI, hosted proof, release status, push, tag, or publish work is included.
