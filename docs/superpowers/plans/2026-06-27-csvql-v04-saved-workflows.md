# CSVQL v0.4 Saved Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build v0.4 saved workflows: SQL-file execution, catalog aliases for inspect/sample, and export to CSV, JSON, and Markdown.

**Architecture:** Keep `cli.py` as a thin Typer boundary by moving shared query orchestration into `query_workflow.py`, SQL-file loading into `sql_file.py`, inspect/sample source selection into `source_resolver.py`, and export validation/serialization into `export.py`. Reuse DuckDB execution through `CSVQLEngine`, existing `TableSource` and `CSVSource` models, v0.3 project catalog loading, and existing output JSON shape.

**Tech Stack:** Python 3.12, Typer, DuckDB, Rich, PyYAML, standard-library `csv`, pytest, Ruff, mypy, uv.

---

## File Structure

Create:

- `src/csvql/sql_file.py`: typed SQL-file path resolution and UTF-8 loading.
- `src/csvql/query_workflow.py`: shared query request construction, table registration, lazy catalog fallback, and SQL execution for `query`, `run`, and `export`.
- `src/csvql/source_resolver.py`: path-or-catalog-alias source resolution for `inspect` and `sample`.
- `src/csvql/export.py`: export format enum, output path validation, CSV/JSON/Markdown serializers, and file writing.
- `tests/test_sql_file.py`: unit tests for SQL-file loading.
- `tests/test_query_workflow.py`: focused tests for shared query workflow behavior where CLI tests would be too broad.
- `tests/test_source_resolver.py`: unit tests for path-or-alias source resolution.
- `tests/test_export.py`: unit tests for export validation and serializers.
- `tests/test_cli_run_export.py`: CLI integration tests for `run` and `export`.

Modify:

- `src/csvql/exceptions.py`: add `SQLFileError` and `ExportError`.
- `src/csvql/cli.py`: add `run` and `export`; update `query`, `inspect`, and `sample` to call shared helpers.
- `tests/test_cli_inspect_sample.py`: add catalog-backed inspect/sample cases.
- `README.md`: document v0.4 command examples and status.
- `docs/ARCHITECTURE.md`: document new modules and saved workflow flow.
- `docs/ROADMAP.md`: move v0.4 items into implemented once behavior lands.

Testing target: roughly 70% focused unit tests for helper modules, 25% CLI integration tests for command behavior, and 5% smoke/manual verification. This repo does not currently separate `unit/` and `integration/` directories, so keep tests in the existing flat `tests/` layout and name by behavior.

---

### Task 1: Add Typed Error Boundaries

**Files:**
- Modify: `src/csvql/exceptions.py`
- Test: no direct test file; errors are asserted through later unit and CLI tests

- [ ] **Step 1: Add SQL-file and export errors**

Append these classes after `ProjectConfigError` in `src/csvql/exceptions.py`:

```python
class SQLFileError(CSVQLError):
    """Raised when a saved SQL file cannot be used."""

    exit_code = 9


class ExportError(CSVQLError):
    """Raised when an export output path or format cannot be used."""

    exit_code = 10
```

- [ ] **Step 2: Run a narrow import/type check**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: `Success: no issues found in 11 source files`.

- [ ] **Step 3: Commit**

Run:

```bash
git add src/csvql/exceptions.py
git commit -m "feat: add saved workflow error types"
```

---

### Task 2: Add SQL File Loading

**Files:**
- Create: `src/csvql/sql_file.py`
- Create: `tests/test_sql_file.py`

- [ ] **Step 1: Write failing SQL-file tests**

Create `tests/test_sql_file.py`:

```python
from pathlib import Path

import pytest

from csvql.exceptions import SQLFileError
from csvql.sql_file import SQLFile, load_sql_file


def test_load_sql_file_reads_utf8_sql_from_invocation_directory(tmp_path: Path) -> None:
    query_path = tmp_path / "queries" / "revenue.sql"
    query_path.parent.mkdir()
    query_path.write_text("SELECT COUNT(*) AS order_count FROM orders;\n", encoding="utf-8")

    loaded = load_sql_file("queries/revenue.sql", base_dir=tmp_path)

    assert loaded == SQLFile(
        display_path="queries/revenue.sql",
        path=query_path.resolve(),
        sql="SELECT COUNT(*) AS order_count FROM orders;\n",
    )


def test_load_sql_file_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SQLFileError) as exc_info:
        load_sql_file("missing.sql", base_dir=tmp_path)

    assert exc_info.value.exit_code == 9
    assert "SQL file not found" in exc_info.value.message


def test_load_sql_file_rejects_directory(tmp_path: Path) -> None:
    query_dir = tmp_path / "queries"
    query_dir.mkdir()

    with pytest.raises(SQLFileError) as exc_info:
        load_sql_file("queries", base_dir=tmp_path)

    assert "SQL file path is a directory" in exc_info.value.message


@pytest.mark.parametrize("content", ["", "   \n\t"])
def test_load_sql_file_rejects_empty_or_whitespace_only_sql(
    tmp_path: Path,
    content: str,
) -> None:
    query_path = tmp_path / "empty.sql"
    query_path.write_text(content, encoding="utf-8")

    with pytest.raises(SQLFileError) as exc_info:
        load_sql_file("empty.sql", base_dir=tmp_path)

    assert "SQL file is empty" in exc_info.value.message
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_sql_file.py -q
```

Expected: fails because `csvql.sql_file` does not exist.

- [ ] **Step 3: Implement SQL-file loading**

Create `src/csvql/sql_file.py`:

```python
"""Saved SQL file loading."""

from dataclasses import dataclass
from pathlib import Path

from csvql.exceptions import SQLFileError


@dataclass(frozen=True, slots=True)
class SQLFile:
    """A resolved local SQL file and its text."""

    display_path: str
    path: Path
    sql: str


def load_sql_file(path_value: str, *, base_dir: Path | None = None) -> SQLFile:
    """Resolve and read a non-empty UTF-8 SQL file."""

    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = (base_dir or Path.cwd()) / candidate
    resolved_path = candidate.resolve(strict=False)

    if not resolved_path.exists():
        raise SQLFileError(
            f"SQL file not found: {path_value}",
            suggestion="Check the path or run from the directory that contains the SQL file.",
        )
    if resolved_path.is_dir():
        raise SQLFileError(
            f"SQL file path is a directory: {path_value}",
            suggestion="Choose a .sql file instead of a directory.",
        )

    try:
        sql = resolved_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SQLFileError(
            f"Failed to read SQL file: {path_value}",
            suggestion="Check that the SQL file is readable.",
        ) from exc

    if not sql.strip():
        raise SQLFileError(
            f"SQL file is empty: {path_value}",
            suggestion="Add a SQL statement before running it.",
        )

    return SQLFile(display_path=path_value, path=resolved_path, sql=sql)
```

- [ ] **Step 4: Run SQL-file tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_sql_file.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Run narrow quality checks**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format src/csvql/sql_file.py tests/test_sql_file.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check src/csvql/sql_file.py tests/test_sql_file.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: Ruff passes and mypy reports no issues.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/csvql/sql_file.py tests/test_sql_file.py
git commit -m "feat: load saved SQL files"
```

---

### Task 3: Move Query Workflow Out Of CLI

**Files:**
- Create: `src/csvql/query_workflow.py`
- Create: `tests/test_query_workflow.py`
- Modify: `src/csvql/cli.py`
- Test: `tests/test_cli_query.py`

- [ ] **Step 1: Write focused workflow tests**

Create `tests/test_query_workflow.py`:

```python
from pathlib import Path

import pytest

from csvql.engine import CSVQLEngine
from csvql.exceptions import TableMappingError
from csvql.query_workflow import (
    build_inline_query_request,
    execute_query_request,
)


def _write_csv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_inline_query_request_rejects_table_mappings_for_single_file_mode(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path, "order_id,total_amount\nORD-001,20.00\n")

    with pytest.raises(TableMappingError):
        build_inline_query_request(
            str(csv_path),
            "SELECT * FROM orders",
            ["orders=orders.csv"],
            base_dir=tmp_path,
        )


def test_execute_query_request_lazily_loads_missing_catalog_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".csvql.yml").write_text(
        "version: 1\ntables:\n  customers:\n    path: customers.csv\n",
        encoding="utf-8",
    )
    orders = tmp_path / "orders.csv"
    customers = tmp_path / "customers.csv"
    _write_csv(orders, "order_id,customer_id,total_amount\nORD-001,CUST-001,20.00\n")
    _write_csv(customers, "customer_id,email\nCUST-001,alex@example.com\n")
    request = build_inline_query_request(
        (
            "SELECT c.email, SUM(o.total_amount) AS total_amount "
            "FROM orders o JOIN customers c USING (customer_id) "
            "GROUP BY c.email"
        ),
        None,
        [f"orders={orders}"],
        base_dir=tmp_path,
    )

    with CSVQLEngine() as engine:
        result = execute_query_request(engine, request)

    assert result.as_records() == [{"email": "alex@example.com", "total_amount": 20.0}]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_query_workflow.py -q
```

Expected: fails because `csvql.query_workflow` does not exist.

- [ ] **Step 3: Implement query workflow module**

Create `src/csvql/query_workflow.py` by moving the current non-Typer query helpers from `src/csvql/cli.py` into this module:

```python
"""Shared query workflow orchestration."""

import re
from dataclasses import dataclass
from pathlib import Path

from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVQLError, QueryExecutionError, TableMappingError
from csvql.models import QueryResult, TableSource
from csvql.project_config import discover_project, load_project, resolve_catalog_path
from csvql.table_mapping import parse_table_mapping, source_from_single_csv

_DUCKDB_MISSING_TABLE_RE = re.compile(
    r"Table with name (?P<name>[A-Za-z_][A-Za-z0-9_]*) does not exist!"
)


@dataclass(frozen=True, slots=True)
class QueryRequest:
    """SQL text plus registered table sources needed to execute it."""

    sql: str
    table_sources: tuple[TableSource, ...]
    catalog_fallback: bool


def build_inline_query_request(
    sql_or_csv: str,
    sql: str | None,
    table_mappings: list[str],
    *,
    base_dir: Path | None = None,
) -> QueryRequest:
    """Build a query request for existing `csvql query` modes."""

    if sql is None:
        explicit_sources = [
            parse_table_mapping(mapping, base_dir=base_dir) for mapping in table_mappings
        ]
        if explicit_sources:
            return QueryRequest(
                sql=sql_or_csv,
                table_sources=tuple(explicit_sources),
                catalog_fallback=True,
            )
        catalog_sources = _catalog_table_sources(start_dir=base_dir)
        return QueryRequest(
            sql=sql_or_csv,
            table_sources=tuple(catalog_sources),
            catalog_fallback=False,
        )

    if table_mappings:
        raise TableMappingError(
            "Single-file shortcut mode cannot be combined with --table mappings.",
            suggestion='Use either csvql query data/orders.csv "SELECT ..." or --table mappings.',
        )
    return QueryRequest(
        sql=sql,
        table_sources=(source_from_single_csv(sql_or_csv, base_dir=base_dir),),
        catalog_fallback=False,
    )


def build_saved_sql_query_request(
    sql: str,
    table_mappings: list[str],
    *,
    base_dir: Path | None = None,
) -> QueryRequest:
    """Build a query request for SQL loaded from a saved file."""

    explicit_sources = [
        parse_table_mapping(mapping, base_dir=base_dir) for mapping in table_mappings
    ]
    if explicit_sources:
        return QueryRequest(
            sql=sql,
            table_sources=tuple(explicit_sources),
            catalog_fallback=True,
        )
    catalog_sources = _catalog_table_sources(start_dir=base_dir)
    return QueryRequest(
        sql=sql,
        table_sources=tuple(catalog_sources),
        catalog_fallback=False,
    )


def execute_query_request(engine: CSVQLEngine, request: QueryRequest) -> QueryResult:
    """Register sources and execute a query request."""

    engine.register_tables(request.table_sources)
    if not request.catalog_fallback:
        return engine.query(request.sql)

    registered_names = {source.name.lower() for source in request.table_sources}
    while True:
        try:
            return engine.query(request.sql)
        except QueryExecutionError as exc:
            missing_name = _missing_duckdb_table_name(exc)
            if missing_name is None or missing_name.lower() in registered_names:
                raise

            catalog_source = _catalog_table_source_by_name(
                missing_name,
                excluded_names=registered_names,
            )
            if catalog_source is None:
                raise
            engine.register_tables([catalog_source])
            registered_names.add(catalog_source.name.lower())


def _catalog_table_sources(*, start_dir: Path | None = None) -> list[TableSource]:
    project_root, _ = discover_project(start_dir)
    context = load_project(project_root)
    return [
        TableSource(name=table.name, path=resolve_catalog_path(table, context))
        for table in context.config.tables
    ]


def _missing_duckdb_table_name(error: QueryExecutionError) -> str | None:
    match = _DUCKDB_MISSING_TABLE_RE.search(error.message)
    if match is None:
        return None
    return match.group("name")


def _catalog_table_source_by_name(
    table_name: str,
    *,
    excluded_names: set[str],
) -> TableSource | None:
    table_key = table_name.lower()
    if table_key in excluded_names:
        return None

    try:
        context = load_project()
    except CSVQLError:
        return None

    table = next(
        (
            catalog_table
            for catalog_table in context.config.tables
            if catalog_table.name.lower() == table_key
        ),
        None,
    )
    if table is None:
        return None
    return TableSource(name=table.name, path=resolve_catalog_path(table, context))
```

- [ ] **Step 4: Update `cli.py` query command**

In `src/csvql/cli.py`:

- remove `import re`;
- remove imports of `QueryExecutionError`, `TableMappingError`, `QueryResult`, `TableSource`, `discover_project`, `resolve_catalog_path`, `parse_table_mapping`, and `source_from_single_csv` if no longer used;
- add:

```python
from csvql.query_workflow import build_inline_query_request, execute_query_request
```

Replace the body inside `query()` with:

```python
    try:
        request = build_inline_query_request(
            sql_or_csv,
            sql,
            table or [],
            base_dir=Path.cwd(),
        )
        with CSVQLEngine() as engine:
            result = execute_query_request(engine, request)
        if output is OutputFormat.json:
            typer.echo(format_json_result(result))
        else:
            typer.echo(format_table_result(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)
```

Delete the private helper functions now owned by `query_workflow.py`:

- `_build_query_request`
- `_catalog_table_sources`
- `_query_with_catalog_fallback`
- `_missing_duckdb_table_name`
- `_catalog_table_source_by_name`
- `_merge_table_sources`

- [ ] **Step 5: Run query workflow and existing query CLI tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_query_workflow.py tests/test_cli_query.py -q
```

Expected: both files pass.

- [ ] **Step 6: Run narrow quality checks**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format src/csvql/cli.py src/csvql/query_workflow.py tests/test_query_workflow.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check src/csvql/cli.py src/csvql/query_workflow.py tests/test_query_workflow.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: Ruff passes and mypy reports no issues.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/csvql/cli.py src/csvql/query_workflow.py tests/test_query_workflow.py
git commit -m "refactor: share query workflow"
```

---

### Task 4: Add `csvql run`

**Files:**
- Modify: `src/csvql/cli.py`
- Test: `tests/test_cli_run_export.py`
- Uses: `src/csvql/sql_file.py`, `src/csvql/query_workflow.py`

- [ ] **Step 1: Write failing CLI run tests**

Create `tests/test_cli_run_export.py` with the run tests first:

```python
import json
from pathlib import Path

from typer.testing import CliRunner

from csvql.cli import app

runner = CliRunner()


def _write_csv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_catalog(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output


def test_run_sql_file_uses_catalog_tables(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\nORD-002,10.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(app, ["run", "queries/count_orders.sql", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [{"order_count": 2}]


def test_run_sql_file_with_explicit_table_works_without_catalog(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "orders.csv"
    query = tmp_path / "count_orders.sql"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "count_orders.sql",
            "--table",
            "orders=orders.csv",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [{"order_count": 1}]


def test_run_sql_file_rejects_empty_sql_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    query = tmp_path / "empty.sql"
    query.write_text("   \n", encoding="utf-8")

    result = runner.invoke(app, ["run", "empty.sql"])

    assert result.exit_code == 9
    assert "SQL file is empty" in result.output
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_run_export.py -q
```

Expected: fails because `run` command does not exist.

- [ ] **Step 3: Add imports for run command**

In `src/csvql/cli.py`, add:

```python
from csvql.query_workflow import (
    build_inline_query_request,
    build_saved_sql_query_request,
    execute_query_request,
)
from csvql.sql_file import load_sql_file
```

If `build_inline_query_request` and `execute_query_request` are already imported from Task 3, expand that import rather than duplicating it.

- [ ] **Step 4: Add `run` command**

Insert this Typer command after `query()` and before `init()` in `src/csvql/cli.py`:

```python
@app.command()
def run(
    sql_file: Annotated[
        str,
        typer.Argument(help="SQL file to run."),
    ],
    table: Annotated[
        list[str] | None,
        typer.Option(
            "--table",
            "-t",
            help="Table mapping in name=path form. Repeat for multiple CSV files.",
        ),
    ] = None,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="Result output format.",
        ),
    ] = OutputFormat.table,
) -> None:
    """Run SQL from a local file."""

    try:
        loaded_sql = load_sql_file(sql_file, base_dir=Path.cwd())
        request = build_saved_sql_query_request(
            loaded_sql.sql,
            table or [],
            base_dir=Path.cwd(),
        )
        with CSVQLEngine() as engine:
            result = execute_query_request(engine, request)
        if output is OutputFormat.json:
            typer.echo(format_json_result(result))
        else:
            typer.echo(format_table_result(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)
```

- [ ] **Step 5: Run run-command tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_run_export.py tests/test_query_workflow.py -q
```

Expected: run-related tests pass.

- [ ] **Step 6: Run existing query regression tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_query.py -q
```

Expected: query regression tests pass.

- [ ] **Step 7: Run narrow quality checks**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format src/csvql/cli.py tests/test_cli_run_export.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check src/csvql/cli.py tests/test_cli_run_export.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: Ruff passes and mypy reports no issues.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/csvql/cli.py tests/test_cli_run_export.py
git commit -m "feat: run saved SQL files"
```

---

### Task 5: Add Catalog Alias Resolution For Inspect And Sample

**Files:**
- Create: `src/csvql/source_resolver.py`
- Create: `tests/test_source_resolver.py`
- Modify: `src/csvql/cli.py`
- Modify: `tests/test_cli_inspect_sample.py`

- [ ] **Step 1: Write source resolver tests**

Create `tests/test_source_resolver.py`:

```python
from pathlib import Path

import pytest

from csvql.exceptions import FileMissingError, ProjectConfigError
from csvql.source_resolver import resolve_path_or_catalog_source


def _write_csv(path: Path, content: str = "id,value\n1,2\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_resolve_path_or_catalog_source_treats_path_looking_input_as_path(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "data" / "orders.csv"
    _write_csv(csv_path)

    source = resolve_path_or_catalog_source("data/orders.csv", base_dir=tmp_path)

    assert source.path == csv_path.resolve()
    assert source.display_path == "data/orders.csv"


def test_resolve_path_or_catalog_source_resolves_catalog_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    csv_path = tmp_path / "data" / "orders.csv"
    _write_csv(csv_path)
    (tmp_path / ".csvql.yml").write_text(
        "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n",
        encoding="utf-8",
    )

    source = resolve_path_or_catalog_source("orders", base_dir=tmp_path)

    assert source.path == csv_path.resolve()
    assert source.display_path == "orders"


def test_resolve_path_or_catalog_source_falls_back_to_path_error_for_unknown_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".csvql.yml").write_text("version: 1\ntables: {}\n", encoding="utf-8")

    with pytest.raises(FileMissingError) as exc_info:
        resolve_path_or_catalog_source("orders", base_dir=tmp_path)

    assert "CSV file not found: orders" in exc_info.value.message


def test_resolve_path_or_catalog_source_preserves_invalid_catalog_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".csvql.yml").write_text("version: [1\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError) as exc_info:
        resolve_path_or_catalog_source("orders", base_dir=tmp_path)

    assert "Invalid YAML" in exc_info.value.message
```

- [ ] **Step 2: Run source resolver tests to verify failure**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_source_resolver.py -q
```

Expected: fails because `csvql.source_resolver` does not exist.

- [ ] **Step 3: Implement source resolver**

Create `src/csvql/source_resolver.py`:

```python
"""Resolve inspect/sample inputs as CSV paths or project catalog aliases."""

from pathlib import Path

from csvql.exceptions import ProjectConfigError
from csvql.project_config import load_project, resolve_catalog_path
from csvql.source import CSVSource, source_from_path


def resolve_path_or_catalog_source(
    path_or_alias: str,
    *,
    base_dir: Path | None = None,
) -> CSVSource:
    """Resolve an inspect/sample argument as a path or catalog alias."""

    if _looks_like_path(path_or_alias):
        return source_from_path(path_or_alias, base_dir=base_dir)

    try:
        context = load_project(base_dir)
    except ProjectConfigError as exc:
        if "No .csvql.yml project catalog found." not in exc.message:
            raise
        return source_from_path(path_or_alias, base_dir=base_dir)

    table = next(
        (
            catalog_table
            for catalog_table in context.config.tables
            if catalog_table.name == path_or_alias
        ),
        None,
    )
    if table is None:
        return source_from_path(path_or_alias, base_dir=base_dir)

    resolved_path = resolve_catalog_path(table, context)
    source = source_from_path(str(resolved_path), base_dir=base_dir)
    return CSVSource(
        path=source.path,
        display_path=path_or_alias,
        fingerprint=source.fingerprint,
    )


def _looks_like_path(value: str) -> bool:
    return (
        "/" in value
        or "\\" in value
        or value.startswith(".")
        or value.startswith("~")
        or value.endswith(".csv")
    )
```

- [ ] **Step 4: Update CLI inspect/sample**

In `src/csvql/cli.py`, replace:

```python
from csvql.source import source_from_path
```

with:

```python
from csvql.source_resolver import resolve_path_or_catalog_source
```

In `inspect()`, replace:

```python
        source = source_from_path(csv_path)
```

with:

```python
        source = resolve_path_or_catalog_source(csv_path, base_dir=Path.cwd())
```

In `sample()`, replace:

```python
        source = source_from_path(csv_path)
```

with:

```python
        source = resolve_path_or_catalog_source(csv_path, base_dir=Path.cwd())
```

- [ ] **Step 5: Add CLI inspect/sample alias tests**

Append to `tests/test_cli_inspect_sample.py`:

```python
def test_inspect_catalog_alias_outputs_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "data" / "orders.csv"
    orders.parent.mkdir(parents=True)
    orders.write_text("order_id,total_amount\nORD-001,20.00\n", encoding="utf-8")
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(app, ["inspect", "orders", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"]["display_path"] == "orders"
    assert payload["columns"][0]["name"] == "order_id"


def test_sample_catalog_alias_outputs_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "data" / "orders.csv"
    orders.parent.mkdir(parents=True)
    orders.write_text("order_id,total_amount\nORD-001,20.00\n", encoding="utf-8")
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(app, ["sample", "orders", "--limit", "1", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"]["display_path"] == "orders"
    assert payload["rows"] == [{"order_id": "ORD-001", "total_amount": 20.0}]
```

- [ ] **Step 6: Run inspect/sample tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_source_resolver.py tests/test_cli_inspect_sample.py -q
```

Expected: source resolver and CLI inspect/sample tests pass.

- [ ] **Step 7: Run narrow quality checks**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format src/csvql/source_resolver.py src/csvql/cli.py tests/test_source_resolver.py tests/test_cli_inspect_sample.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check src/csvql/source_resolver.py src/csvql/cli.py tests/test_source_resolver.py tests/test_cli_inspect_sample.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: Ruff passes and mypy reports no issues.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/csvql/source_resolver.py src/csvql/cli.py tests/test_source_resolver.py tests/test_cli_inspect_sample.py
git commit -m "feat: inspect and sample catalog aliases"
```

---

### Task 6: Add Export Serializers And Output Path Validation

**Files:**
- Create: `src/csvql/export.py`
- Create: `tests/test_export.py`

- [ ] **Step 1: Write export unit tests**

Create `tests/test_export.py`:

```python
import json
from pathlib import Path

import pytest

from csvql.exceptions import ExportError
from csvql.export import (
    ExportFormat,
    format_query_result_for_export,
    resolve_export_path,
    write_export_file,
)
from csvql.models import QueryResult


def _result() -> QueryResult:
    return QueryResult(
        columns=("name", "note", "amount"),
        rows=(("Alex", "pipe | value", 20.5), ("Blair", "line\nbreak", None)),
        elapsed_ms=1.234,
    )


def test_format_query_result_for_csv_export() -> None:
    output = format_query_result_for_export(_result(), ExportFormat.csv)

    assert output == (
        "name,note,amount\r\n"
        'Alex,"pipe | value",20.5\r\n'
        'Blair,"line\nbreak",\r\n'
    )


def test_format_query_result_for_json_export_matches_query_json_shape() -> None:
    output = format_query_result_for_export(_result(), ExportFormat.json)

    payload = json.loads(output)
    assert payload["columns"] == ["name", "note", "amount"]
    assert payload["row_count"] == 2
    assert payload["rows"][0] == {"name": "Alex", "note": "pipe | value", "amount": 20.5}


def test_format_query_result_for_markdown_export_escapes_cells() -> None:
    output = format_query_result_for_export(_result(), ExportFormat.markdown)

    assert output == (
        "| name | note | amount |\n"
        "| --- | --- | --- |\n"
        "| Alex | pipe \\| value | 20.5 |\n"
        "| Blair | line<br>break |  |\n"
    )


def test_resolve_export_path_refuses_existing_file_without_force(tmp_path: Path) -> None:
    output_path = tmp_path / "result.csv"
    output_path.write_text("existing", encoding="utf-8")

    with pytest.raises(ExportError) as exc_info:
        resolve_export_path("result.csv", base_dir=tmp_path, force=False)

    assert "Export output already exists" in exc_info.value.message


def test_resolve_export_path_requires_existing_parent_directory(tmp_path: Path) -> None:
    with pytest.raises(ExportError) as exc_info:
        resolve_export_path("missing/result.csv", base_dir=tmp_path, force=False)

    assert "Export output directory does not exist" in exc_info.value.message


def test_write_export_file_writes_utf8_text(tmp_path: Path) -> None:
    output_path = tmp_path / "result.md"

    write_export_file(output_path, "hello\n")

    assert output_path.read_text(encoding="utf-8") == "hello\n"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_export.py -q
```

Expected: fails because `csvql.export` does not exist.

- [ ] **Step 3: Implement export module**

Create `src/csvql/export.py`:

```python
"""Export query results to local text files."""

import csv
from enum import StrEnum
from io import StringIO
from pathlib import Path

from csvql.exceptions import ExportError
from csvql.models import QueryResult
from csvql.output import format_json_result


class ExportFormat(StrEnum):
    """Supported export file formats."""

    csv = "csv"
    json = "json"
    markdown = "markdown"


def resolve_export_path(
    path_value: str,
    *,
    base_dir: Path | None = None,
    force: bool = False,
) -> Path:
    """Resolve and validate an export output path."""

    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = (base_dir or Path.cwd()) / candidate
    resolved_path = candidate.resolve(strict=False)

    if not resolved_path.parent.is_dir():
        raise ExportError(
            f"Export output directory does not exist: {resolved_path.parent}",
            suggestion="Create the directory or choose an existing output directory.",
        )
    if resolved_path.exists() and not force:
        raise ExportError(
            f"Export output already exists: {resolved_path}",
            suggestion="Pass --force to overwrite it or choose a different output path.",
        )
    if resolved_path.is_dir():
        raise ExportError(
            f"Export output path is a directory: {resolved_path}",
            suggestion="Choose a file path for the export output.",
        )
    return resolved_path


def format_query_result_for_export(result: QueryResult, export_format: ExportFormat) -> str:
    """Serialize a query result for an export format."""

    if export_format is ExportFormat.csv:
        return _format_csv(result)
    if export_format is ExportFormat.json:
        return format_json_result(result) + "\n"
    if export_format is ExportFormat.markdown:
        return _format_markdown(result)
    raise ExportError(
        f"Unsupported export format: {export_format}",
        suggestion="Use csv, json, or markdown.",
    )


def write_export_file(path: Path, content: str) -> None:
    """Write export content as UTF-8 text."""

    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ExportError(
            f"Failed to write export output: {path}",
            suggestion="Check that the output path is writable.",
        ) from exc


def _format_csv(result: QueryResult) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(result.columns)
    writer.writerows(result.rows)
    return buffer.getvalue()


def _format_markdown(result: QueryResult) -> str:
    header = "| " + " | ".join(_format_markdown_cell(column) for column in result.columns) + " |"
    separator = "| " + " | ".join("---" for _ in result.columns) + " |"
    rows = [
        "| " + " | ".join(_format_markdown_cell(value) for value in row) + " |"
        for row in result.rows
    ]
    return "\n".join([header, separator, *rows]) + "\n"


def _format_markdown_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")
```

- [ ] **Step 4: Run export tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_export.py -q
```

Expected: export tests pass.

- [ ] **Step 5: Run narrow quality checks**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format src/csvql/export.py tests/test_export.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check src/csvql/export.py tests/test_export.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: Ruff passes and mypy reports no issues.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/csvql/export.py tests/test_export.py
git commit -m "feat: serialize query exports"
```

---

### Task 7: Add `csvql export`

**Files:**
- Modify: `src/csvql/cli.py`
- Modify: `tests/test_cli_run_export.py`
- Uses: `src/csvql/export.py`, `src/csvql/sql_file.py`, `src/csvql/query_workflow.py`

- [ ] **Step 1: Add failing export CLI tests**

Append to `tests/test_cli_run_export.py`:

```python
def test_export_sql_file_writes_csv(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.csv"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\nORD-002,10.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "queries/count_orders.sql", "--format", "csv", "--out", "result.csv"],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_text(encoding="utf-8") == "order_count\r\n2\r\n"
    assert "Wrote export" in result.output


def test_export_sql_file_writes_json(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.json"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "queries/count_orders.sql", "--format", "json", "--out", "result.json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["rows"] == [{"order_count": 1}]


def test_export_sql_file_writes_markdown(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.md"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "queries/count_orders.sql", "--format", "markdown", "--out", "result.md"],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_text(encoding="utf-8") == (
        "| order_count |\n| --- |\n| 1 |\n"
    )


def test_export_refuses_overwrite_without_force(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "count_orders.sql"
    output_path = tmp_path / "result.csv"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    output_path.write_text("existing", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "count_orders.sql", "--format", "csv", "--out", "result.csv"],
    )

    assert result.exit_code == 10
    assert "Export output already exists" in result.output
    assert output_path.read_text(encoding="utf-8") == "existing"


def test_export_force_overwrites_existing_file(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "count_orders.sql"
    output_path = tmp_path / "result.csv"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    output_path.write_text("existing", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "count_orders.sql", "--format", "csv", "--out", "result.csv", "--force"],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_text(encoding="utf-8") == "order_count\r\n1\r\n"
```

- [ ] **Step 2: Run export CLI tests to verify failure**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_run_export.py -q
```

Expected: export tests fail because `export` command does not exist.

- [ ] **Step 3: Add export imports to CLI**

In `src/csvql/cli.py`, add:

```python
from csvql.export import (
    ExportFormat,
    format_query_result_for_export,
    resolve_export_path,
    write_export_file,
)
```

- [ ] **Step 4: Add `export` command**

Insert this command after `run()` in `src/csvql/cli.py`:

```python
@app.command()
def export(
    sql_file: Annotated[
        str,
        typer.Argument(help="SQL file to run and export."),
    ],
    export_format: Annotated[
        ExportFormat,
        typer.Option(
            "--format",
            case_sensitive=False,
            help="Export output format.",
        ),
    ],
    out: Annotated[
        str,
        typer.Option(
            "--out",
            help="Output file path.",
        ),
    ],
    table: Annotated[
        list[str] | None,
        typer.Option(
            "--table",
            "-t",
            help="Table mapping in name=path form. Repeat for multiple CSV files.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite an existing export output file.",
        ),
    ] = False,
) -> None:
    """Run SQL from a local file and write the result to a file."""

    try:
        loaded_sql = load_sql_file(sql_file, base_dir=Path.cwd())
        output_path = resolve_export_path(out, base_dir=Path.cwd(), force=force)
        request = build_saved_sql_query_request(
            loaded_sql.sql,
            table or [],
            base_dir=Path.cwd(),
        )
        with CSVQLEngine() as engine:
            result = execute_query_request(engine, request)
        content = format_query_result_for_export(result, export_format)
        write_export_file(output_path, content)
        typer.echo(f"Wrote export to {output_path}.")
    except CSVQLError as exc:
        _exit_with_error(exc)
```

- [ ] **Step 5: Run export CLI tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_run_export.py tests/test_export.py -q
```

Expected: run and export CLI tests pass.

- [ ] **Step 6: Run narrow quality checks**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format src/csvql/cli.py tests/test_cli_run_export.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check src/csvql/cli.py tests/test_cli_run_export.py
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: Ruff passes and mypy reports no issues.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/csvql/cli.py tests/test_cli_run_export.py
git commit -m "feat: export saved query results"
```

---

### Task 8: Update Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Update README status and examples**

In `README.md`, update the "Implemented now" list to include:

```markdown
- `csvql run queries/file.sql`
- `csvql export queries/file.sql --format csv|json|markdown --out path`
- catalog-backed `csvql inspect alias`
- catalog-backed `csvql sample alias`
```

Add a new section after "Project Catalog Examples":

```markdown
## Saved Workflow Examples

Run SQL from a file using catalog aliases:

```bash
uv run csvql run examples/sales/queries/revenue_by_month.sql --output json
```

Inspect and sample registered catalog aliases:

```bash
uv run csvql inspect orders --output json
uv run csvql sample orders --limit 5 --output json
```

Export SQL-file results:

```bash
uv run csvql export examples/sales/queries/revenue_by_month.sql \
  --format csv \
  --out out/revenue.csv

uv run csvql export examples/sales/queries/revenue_by_month.sql \
  --format json \
  --out out/revenue.json

uv run csvql export examples/sales/queries/revenue_by_month.sql \
  --format markdown \
  --out out/revenue.md
```

`csvql export` refuses to overwrite an existing output file unless `--force` is passed. The output directory must already exist.
```

Keep the existing security model section unchanged or strengthen it only with the current trusted-local-SQL boundary.

- [ ] **Step 2: Update architecture module list**

In `docs/ARCHITECTURE.md`, add these boundaries:

```markdown
`sql_file.py`
: Resolve and read saved SQL files, rejecting missing, directory, unreadable, and empty SQL inputs.

`query_workflow.py`
: Shared query request construction and execution for inline query, saved SQL run, and export workflows.

`source_resolver.py`
: Resolve inspect/sample inputs as direct CSV paths or project catalog aliases.

`export.py`
: Validate export output paths and serialize query results to CSV, JSON, or Markdown.
```

Update the flow diagram to include:

```text
CLI arguments
  -> path/sql-file/input parser
  -> explicit table mapping parser or project catalog discovery
  -> validated table aliases and resolved CSV paths
  -> in-memory DuckDB engine
  -> query/inspect/sample/export output
```

- [ ] **Step 3: Update roadmap**

In `docs/ROADMAP.md`, replace the v0.4 section with:

```markdown
## v0.4.0 - Saved Workflows

Implemented:

- `csvql run queries/file.sql`
- registered-table support for `csvql inspect`
- registered-table support for `csvql sample`
- `csvql export queries/file.sql --format csv|json|markdown --out path`
- overwrite protection for export outputs with explicit `--force`
```

Do not move profiling, data-quality checks, benchmarks, release workflow, or changelog out of their later sections.

- [ ] **Step 4: Run docs-oriented checks**

Run:

```bash
git diff --check
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_run_export.py tests/test_cli_inspect_sample.py -q
```

Expected: no whitespace errors and relevant CLI docs behavior tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add README.md docs/ARCHITECTURE.md docs/ROADMAP.md
git commit -m "docs: document saved workflows"
```

---

### Task 9: Full Verification And Smoke

**Files:**
- No source changes unless verification exposes a defect

- [ ] **Step 1: Run full quality gate**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest
git diff --check
```

Expected:

- Ruff format passes.
- Ruff lint passes.
- mypy reports no issues.
- pytest passes.
- `git diff --check` prints no output.

- [ ] **Step 2: Run red-flag and trailing-whitespace scans**

Run:

```bash
rg -n "production|sandbox|safe mode|large-file|untrusted|parquet|parameters|templating" src tests README.md docs
rg -n "[[:blank:]]$" src tests README.md docs
```

Expected:

- The first command only finds intended negative-boundary language and deferred/non-goal references.
- The second command exits with no matches.

- [ ] **Step 3: Run sequential CLI smoke in a temporary project**

Run these commands one at a time, using a fresh temporary directory:

```bash
SMOKE_DIR="$(mktemp -d /private/tmp/csvql-v04-smoke.XXXXXX)"
cd "$SMOKE_DIR"
/Users/richarddemke/.codex/worktrees/a6fd/csvql/.venv/bin/csvql init
/Users/richarddemke/.codex/worktrees/a6fd/csvql/.venv/bin/csvql add orders /Users/richarddemke/.codex/worktrees/a6fd/csvql/examples/sales/data/orders.csv
/Users/richarddemke/.codex/worktrees/a6fd/csvql/.venv/bin/csvql run /Users/richarddemke/.codex/worktrees/a6fd/csvql/examples/sales/queries/revenue_by_month.sql --output json
/Users/richarddemke/.codex/worktrees/a6fd/csvql/.venv/bin/csvql inspect orders --output json
/Users/richarddemke/.codex/worktrees/a6fd/csvql/.venv/bin/csvql sample orders --limit 2 --output json
/Users/richarddemke/.codex/worktrees/a6fd/csvql/.venv/bin/csvql export /Users/richarddemke/.codex/worktrees/a6fd/csvql/examples/sales/queries/revenue_by_month.sql --format csv --out revenue.csv
/Users/richarddemke/.codex/worktrees/a6fd/csvql/.venv/bin/csvql export /Users/richarddemke/.codex/worktrees/a6fd/csvql/examples/sales/queries/revenue_by_month.sql --format json --out revenue.json
/Users/richarddemke/.codex/worktrees/a6fd/csvql/.venv/bin/csvql export /Users/richarddemke/.codex/worktrees/a6fd/csvql/examples/sales/queries/revenue_by_month.sql --format markdown --out revenue.md
```

Expected:

- `run` JSON returns rows grouped by `order_month`.
- `inspect orders --output json` returns source display path `orders`.
- `sample orders --limit 2 --output json` returns two rows.
- `revenue.csv`, `revenue.json`, and `revenue.md` exist in the smoke directory.

- [ ] **Step 4: Final diff review**

Run:

```bash
git status --short --branch
git log --oneline -12
```

Expected:

- Branch is clean after committed changes.
- Recent commits show the v0.4 task commits in order.

- [ ] **Step 5: Request final code review**

Use a fresh read-only reviewer subagent with this scope:

```text
Review CSVQL v0.4 Saved Workflows implementation. Focus on command contracts from docs/superpowers/specs/2026-06-27-csvql-v04-saved-workflows-design.md, query_workflow table-source behavior, SQL-file loading, inspect/sample alias resolution, export overwrite/path validation, CSV/JSON/Markdown serialization, tests, docs, and unsupported safety/performance claims. Do not edit files.
```

Expected: reviewer either approves or returns concrete blockers. Fix blockers in follow-up commits and rerun the full quality gate.

---

## Plan Self-Review

Spec coverage:

- `csvql run <sql-file>`: Tasks 2, 3, and 4.
- catalog-backed `inspect` and `sample`: Task 5.
- `csvql export` to CSV, JSON, Markdown: Tasks 6 and 7.
- docs and roadmap updates: Task 8.
- verification and smoke: Task 9.

Completeness scan:

- No incomplete requirement markers, vague edge-case instructions, or deferred implementation notes are intentionally present.
- Each task includes exact files, test examples, implementation snippets, commands, and expected outcomes.

Type consistency:

- `SQLFile`, `QueryRequest`, `ExportFormat`, `SQLFileError`, and `ExportError` are introduced before later tasks depend on them.
- `build_saved_sql_query_request()` is used by both `run` and `export`.
- `execute_query_request()` owns registration and lazy catalog fallback for all query execution paths.

Known implementation cautions:

- Run catalog mutation smoke commands sequentially; parallel `csvql add` writes are outside v0.4 and can corrupt the YAML file.
- Keep SQL trusted-local-only language in docs. Do not add sandbox, production, or large-file performance claims.
