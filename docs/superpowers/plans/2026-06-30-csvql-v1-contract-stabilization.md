# CSVQL v1 Contract Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize CSVQL's v1 contracts by freezing current CLI JSON, exit-code, and config behavior, raising the DuckDB dependency floor, and expanding the project-backed Python API to cover the core repeatable workflow.

**Architecture:** Keep CLI runtime behavior unchanged. Extend `CSVQLSession` as a thin project-backed wrapper over existing services, using short-lived DuckDB execution and existing `CSVQLError` subclasses. Update dependency metadata and authority docs so package constraints, docs, and tests agree before release-candidate proof.

**Tech Stack:** Python 3.11+, DuckDB, Typer, PyYAML, Rich, `uv`, pytest, Ruff, mypy, Markdown docs.

---

## Preconditions

- Start from a clean worktree on `main`.
- Use the committed spec at `docs/superpowers/specs/2026-06-30-csvql-v1-contract-stabilization-design.md` as the authority for this slice.
- Keep the status label `v1-hardening`; do not claim `release-candidate` or `v1-stable` in this plan.
- Do not change CLI command behavior, JSON output shapes, exit-code constants, or `.csvql.yml` schema behavior.
- Use `env UV_CACHE_DIR=/private/tmp/uv-cache uv ...` for dependency and test commands.

Run before editing:

```bash
git status --short --branch
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_api.py -q
```

Expected:

- `git status --short --branch` prints `## main`.
- Existing API tests pass before adding the new API contract tests.

## Scope And Constraints

Included:

- Add `CSVQLSession.tables()`.
- Add `CSVQLSession.inspect(table, exact=False)`.
- Add `CSVQLSession.sample(table, limit=10)`.
- Add `CSVQLSession.export(sql_file, out, format="json", force=False)`.
- Export documented public API result and format types from `src/csvql/__init__.py`.
- Raise DuckDB dependency from `duckdb>=1.0.0` to `duckdb>=1.5.0,<2`.
- Update docs to state the v1 contract freeze clearly.

Excluded:

- JSON envelope migration.
- Exit-code redesign.
- Config migration framework.
- Direct CSV path mode in the Python API.
- Ad hoc Python API table mappings.
- Config mutation helpers.
- Dataframe helpers.
- Async API.
- Plugin API.
- Persistent session-level DuckDB connection.
- Safe mode, sandbox claims, cache, materialization, web, cloud, notebook, AI, or dashboard scope.

## Command, JSON, Exit-Code, Config, Docs, And Test Impact

Command impact:

- No CLI commands change.

JSON impact:

- Current CLI JSON shapes are documented as stable for v1.
- No runtime JSON formatter changes are made.

Exit-code impact:

- Current exit-code behavior is documented as stable for v1.
- No exception exit-code constants change.

Config impact:

- `.csvql.yml` remains strict `version: 1`.
- No schema migration or new keys are added.

Docs impact:

- README, architecture, product direction, roadmap, JSON contracts, and release-readiness docs are aligned to the approved contract decisions.

Test impact:

- `tests/test_api.py` gains project-backed API parity tests.
- Existing CLI tests remain the contract guard for CLI behavior.

## File Structure

- Modify: `tests/test_api.py`
  - API parity tests for table listing, inspect, sample, export, imports, and error behavior.
- Modify: `src/csvql/api.py`
  - Public `CSVQLSession` methods and private catalog source helper.
- Modify: `src/csvql/__init__.py`
  - Package-root exports for documented API types.
- Modify: `pyproject.toml`
  - DuckDB dependency floor.
- Modify: `uv.lock`
  - Lock metadata for the updated DuckDB specifier while retaining DuckDB 1.5.x.
- Modify: `README.md`
  - Python API example and scope statement.
- Modify: `docs/ARCHITECTURE.md`
  - Expanded `api.py` boundary.
- Modify: `docs/PRODUCT_DIRECTION.md`
  - DuckDB support and contract decision language.
- Modify: `docs/ROADMAP.md`
  - v1 remaining work after contract stabilization.
- Modify: `docs/json-contracts.md`
  - Stable v1 JSON scope and current-shape coverage for sample, tables, and doctor.
- Modify: `docs/release-readiness.md`
  - Label rules after contract stabilization.

## Task 1: Add Failing API Parity Tests

**Files:**
- Modify: `tests/test_api.py`

- [ ] **Step 1: Replace `tests/test_api.py` with the expanded API contract tests**

Use this complete file:

```python
import json
from pathlib import Path

import pytest

from csvql import (
    CSVQLSession,
    ExportFormat,
    InspectResult,
    ProfileResult,
    ProjectTablesResult,
    QueryResult,
    SampleResult,
)
from csvql.exceptions import ExportError, ProjectConfigError, QueryExecutionError, SQLFileError
from csvql.quality import CheckRunResult


def _write_project(
    root: Path,
    *,
    rows: str = "ORD-001,paid\nORD-002,pending\n",
) -> None:
    (root / "data").mkdir(parents=True)
    (root / "queries").mkdir(parents=True)
    (root / "nested" / "child").mkdir(parents=True)
    (root / "output").mkdir(parents=True)
    (root / "data" / "orders.csv").write_text(
        "order_id,status\n" + rows,
        encoding="utf-8",
    )
    (root / "queries" / "count_orders.sql").write_text(
        "SELECT COUNT(*) AS order_count FROM orders",
        encoding="utf-8",
    )
    (root / "queries" / "list_orders.sql").write_text(
        "SELECT order_id, status FROM orders ORDER BY order_id",
        encoding="utf-8",
    )
    (root / ".csvql.yml").write_text(
        (
            "version: 1\n"
            "tables:\n"
            "  orders:\n"
            "    path: data/orders.csv\n"
            "    checks:\n"
            "      - name: order_id_required\n"
            "        type: not_null\n"
            "        column: order_id\n"
        ),
        encoding="utf-8",
    )


def test_session_query_uses_nearest_project_context(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)

    session = CSVQLSession.from_config(project_root / "nested" / "child")
    result = session.query("SELECT COUNT(*) AS order_count FROM orders")

    assert isinstance(result, QueryResult)
    assert result.columns == ("order_count",)
    assert result.rows == ((2,),)


def test_session_run_file_resolves_paths_from_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    _write_project(project_root)

    monkeypatch.chdir(outside_dir)
    session = CSVQLSession.from_config(project_root)
    result = session.run_file("queries/count_orders.sql")

    assert result.columns == ("order_count",)
    assert result.rows == ((2,),)


def test_session_tables_returns_project_table_listing(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    result = session.tables()

    assert isinstance(result, ProjectTablesResult)
    assert result.project_root == project_root.resolve()
    assert [table.name for table in result.tables] == ["orders"]
    assert result.tables[0].path == "data/orders.csv"
    assert result.tables[0].resolved_path == (project_root / "data" / "orders.csv").resolve()


def test_session_inspect_returns_inspect_result_for_catalog_alias(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    result = session.inspect("orders")

    assert isinstance(result, InspectResult)
    assert result.source["display_path"] == "orders"
    assert [column.name for column in result.columns] == ["order_id", "status"]
    assert result.row_count.mode == "not_counted"
    assert result.row_count.value is None


def test_session_inspect_exact_returns_exact_row_count(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    result = session.inspect("orders", exact=True)

    assert result.row_count.mode == "exact"
    assert result.row_count.value == 2
    assert result.row_count.exact is True


def test_session_sample_returns_sample_result_for_catalog_alias(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    result = session.sample("orders", limit=1)

    assert isinstance(result, SampleResult)
    assert result.source["display_path"] == "orders"
    assert result.limit == 1
    assert result.columns == ("order_id", "status")
    assert result.rows == (("ORD-001", "paid"),)


def test_session_sample_preserves_positive_limit_rule(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(ValueError, match="Sample limit must be greater than zero"):
        session.sample("orders", limit=0)


def test_session_profile_returns_profile_result_for_catalog_alias(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    result = session.profile("orders")

    assert isinstance(result, ProfileResult)
    assert result.source["display_path"] == "orders"
    assert result.row_count == 2
    assert result.column_count == 2


def test_session_export_writes_csv_and_returns_resolved_path(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    output_path = session.export(
        "queries/count_orders.sql",
        "output/count-orders.csv",
        format=ExportFormat.csv,
    )

    assert output_path == (project_root / "output" / "count-orders.csv").resolve()
    assert output_path.read_bytes() == b"order_count\r\n2\r\n"


def test_session_export_writes_json_with_query_result_shape(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    output_path = session.export(
        "queries/count_orders.sql",
        "output/count-orders.json",
        format="json",
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert set(payload) == {"columns", "rows", "row_count", "elapsed_ms"}
    assert payload["columns"] == ["order_count"]
    assert payload["rows"] == [{"order_count": 2}]
    assert payload["row_count"] == 1
    assert isinstance(payload["elapsed_ms"], float)


def test_session_export_writes_markdown(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    output_path = session.export(
        "queries/count_orders.sql",
        "output/count-orders.md",
        format=ExportFormat.markdown,
    )

    assert output_path.read_text(encoding="utf-8") == "| order_count |\n| --- |\n| 2 |\n"


def test_session_export_refuses_overwrite_without_force(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    output_path = project_root / "output" / "count-orders.csv"
    output_path.parent.mkdir()
    output_path.write_text("existing", encoding="utf-8")
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(ExportError, match="Export output already exists"):
        session.export("queries/count_orders.sql", "output/count-orders.csv", format="csv")

    assert output_path.read_text(encoding="utf-8") == "existing"


def test_session_export_force_overwrites_existing_file(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    output_path = project_root / "output" / "count-orders.csv"
    output_path.parent.mkdir()
    output_path.write_text("existing", encoding="utf-8")
    session = CSVQLSession.from_config(project_root)

    result_path = session.export(
        "queries/count_orders.sql",
        "output/count-orders.csv",
        format="csv",
        force=True,
    )

    assert result_path == output_path.resolve()
    assert output_path.read_bytes() == b"order_count\r\n2\r\n"


def test_session_export_rejects_unknown_format(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(ExportError, match="Unsupported export format"):
        session.export("queries/count_orders.sql", "output/count-orders.txt", format="txt")


def test_session_from_config_propagates_missing_project_error(tmp_path: Path) -> None:
    with pytest.raises(ProjectConfigError):
        CSVQLSession.from_config(tmp_path)


def test_session_query_propagates_query_execution_error(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(QueryExecutionError):
        session.query("SELECT missing_column FROM orders")


def test_session_run_file_propagates_missing_sql_file_error(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(SQLFileError):
        session.run_file("queries/missing.sql")


def test_session_alias_methods_propagate_invalid_table_alias_error(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(ProjectConfigError):
        session.inspect("missing")
    with pytest.raises(ProjectConfigError):
        session.sample("missing")
    with pytest.raises(ProjectConfigError):
        session.profile("missing")


def test_session_check_returns_failed_result_without_raising(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root, rows="ORD-001,paid\n,pending\n")
    session = CSVQLSession.from_config(project_root)

    result = session.check(show_failures=True, failure_limit=1)

    assert isinstance(result, CheckRunResult)
    assert result.status == "failed"
    assert result.check_count == 1
    assert result.failed_count == 1
    assert result.checks[0].failed_count == 1
    assert len(result.checks[0].failures) == 1
```

- [ ] **Step 2: Run the focused tests to verify the new contract tests fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_api.py -q
```

Expected: FAIL with import errors for `ExportFormat`, `InspectResult`, `ProjectTablesResult`, or `SampleResult` from `csvql`, or with `AttributeError` for missing `CSVQLSession.tables`, `inspect`, `sample`, or `export`.

- [ ] **Step 3: Commit the failing test contract**

Run:

```bash
git add tests/test_api.py
git commit -m "test: expand python api contract"
```

Expected: commit succeeds and contains only `tests/test_api.py`.

## Task 2: Implement Project-Backed API Parity

**Files:**
- Modify: `src/csvql/api.py`
- Modify: `src/csvql/__init__.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Replace `src/csvql/api.py` with the expanded session wrapper**

Use this complete file:

```python
"""Small public Python API for project-backed CSVQL workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from csvql.checks import run_configured_checks
from csvql.engine import CSVQLEngine
from csvql.exceptions import ExportError, ProjectConfigError
from csvql.export import (
    ExportFormat,
    format_query_result_for_export,
    resolve_export_path,
    write_export_file,
)
from csvql.inspection import inspect_csv_source, sample_csv_source
from csvql.models import InspectResult, ProfileResult, QueryResult, SampleResult
from csvql.profiling import profile_csv_source
from csvql.project_config import (
    ProjectContext,
    ProjectTable,
    ProjectTablesResult,
    build_project_tables_result,
    load_project,
    project_tables_to_sources,
    resolve_catalog_path,
)
from csvql.quality import CheckRunResult
from csvql.source import CSVSource, source_from_path
from csvql.sql_file import load_sql_file


@dataclass(frozen=True, slots=True)
class CSVQLSession:
    """Thin project-backed API over existing CSVQL services."""

    _context: ProjectContext

    @classmethod
    def from_config(cls, start_dir: str | Path = ".") -> CSVQLSession:
        return cls(load_project(Path(start_dir)))

    def tables(self) -> ProjectTablesResult:
        return build_project_tables_result(self._context)

    def query(self, sql: str) -> QueryResult:
        with CSVQLEngine() as engine:
            engine.register_tables(project_tables_to_sources(self._context))
            return engine.query(sql)

    def run_file(self, path: str | Path) -> QueryResult:
        sql_file = load_sql_file(str(path), base_dir=self._context.project_root)
        return self.query(sql_file.sql)

    def inspect(self, table: str, *, exact: bool = False) -> InspectResult:
        return inspect_csv_source(_catalog_source(self._context, table), exact=exact)

    def sample(self, table: str, *, limit: int = 10) -> SampleResult:
        return sample_csv_source(_catalog_source(self._context, table), limit=limit)

    def profile(self, table: str) -> ProfileResult:
        return profile_csv_source(_catalog_source(self._context, table))

    def check(
        self,
        table: str | None = None,
        *,
        show_failures: bool = False,
        failure_limit: int = 5,
    ) -> CheckRunResult:
        return run_configured_checks(
            self._context,
            table_name=table,
            show_failures=show_failures,
            failure_limit=failure_limit,
        )

    def export(
        self,
        sql_file: str | Path,
        out: str | Path,
        *,
        format: ExportFormat | str,
        force: bool = False,
    ) -> Path:
        output_path = resolve_export_path(
            str(out),
            base_dir=self._context.project_root,
            force=force,
        )
        result = self.run_file(sql_file)
        content = format_query_result_for_export(result, _export_format(format))
        write_export_file(output_path, content)
        return output_path


def _catalog_source(context: ProjectContext, table_name: str) -> CSVSource:
    project_table = _project_table(context, table_name)
    resolved_path = resolve_catalog_path(project_table, context)
    resolved_source = source_from_path(
        str(resolved_path),
        base_dir=context.project_root,
    )
    return CSVSource(
        path=resolved_source.path,
        display_path=table_name,
        fingerprint=resolved_source.fingerprint,
    )


def _project_table(context: ProjectContext, table_name: str) -> ProjectTable:
    normalized = table_name.strip().lower()
    match = next(
        (table for table in context.config.tables if table.name.lower() == normalized),
        None,
    )
    if match is None:
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' was not found in {context.config_path}.",
            suggestion="Run csvql tables to list configured table aliases.",
        )
    return match


def _export_format(value: ExportFormat | str) -> ExportFormat:
    if isinstance(value, ExportFormat):
        return value
    try:
        return ExportFormat(value)
    except ValueError as exc:
        raise ExportError(
            f"Unsupported export format: {value}",
            suggestion="Use csv, json, or markdown.",
        ) from exc
```

- [ ] **Step 2: Replace `src/csvql/__init__.py` with package-root exports for the documented API**

Use this complete file:

```python
"""CSVQL public package interface."""

from csvql.api import CSVQLSession
from csvql.engine import CSVQLEngine
from csvql.export import ExportFormat
from csvql.models import InspectResult, ProfileResult, QueryResult, SampleResult, TableSource
from csvql.project_config import ProjectTablesResult
from csvql.quality import CheckRunResult

__all__ = [
    "CSVQLEngine",
    "CSVQLSession",
    "CheckRunResult",
    "ExportFormat",
    "InspectResult",
    "ProfileResult",
    "ProjectTablesResult",
    "QueryResult",
    "SampleResult",
    "TableSource",
]

__version__ = "0.1.0"
```

- [ ] **Step 3: Run focused API tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_api.py -q
```

Expected: PASS for all tests in `tests/test_api.py`.

- [ ] **Step 4: Run type and lint checks for touched source**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check src/csvql/api.py src/csvql/__init__.py tests/test_api.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: PASS for both commands.

- [ ] **Step 5: Commit API implementation**

Run:

```bash
git add src/csvql/api.py src/csvql/__init__.py tests/test_api.py
git commit -m "feat: expand project-backed python api"
```

Expected: commit succeeds and includes only the API source, package exports, and API tests.

## Task 3: Raise DuckDB Dependency Floor

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Change the DuckDB requirement in `pyproject.toml`**

Replace this dependency entry:

```toml
"duckdb>=1.0.0",
```

with:

```toml
"duckdb>=1.5.0,<2",
```

- [ ] **Step 2: Refresh lock metadata**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv lock
```

Expected: command exits `0`. If the sandbox blocks dependency index access, rerun the same command with escalation. The locked DuckDB package version remains `1.5.4`.

- [ ] **Step 3: Verify the lock metadata records the new specifier**

Run:

```bash
rg -n 'duckdb", specifier = ">=1\.5\.0,<2"|name = "duckdb"|version = "1\.5\.4"' pyproject.toml uv.lock
```

Expected: `pyproject.toml` contains `duckdb>=1.5.0,<2`, `uv.lock` package metadata contains `specifier = ">=1.5.0,<2"`, and `uv.lock` still contains `name = "duckdb"` followed by `version = "1.5.4"`.

- [ ] **Step 4: Commit dependency floor**

Run:

```bash
git add pyproject.toml uv.lock
git commit -m "chore: raise duckdb dependency floor"
```

Expected: commit succeeds and includes only `pyproject.toml` and `uv.lock`.

## Task 4: Update User And Architecture Docs

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/PRODUCT_DIRECTION.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Update the README Python API example**

Replace the current `## Python API Example` section in `README.md` with:

````markdown
## Python API Example

CSVQL also exposes a project-backed Python API:

```python
from csvql import CSVQLSession

session = CSVQLSession.from_config("examples/saas_revenue")

tables = session.tables()
sample = session.sample("revenue_movements", limit=5)
profile = session.profile("revenue_movements")
result = session.run_file("queries/revenue_health.sql")
output_path = session.export(
    "queries/revenue_health.sql",
    "output/revenue-health.json",
    format="json",
    force=True,
)

for row in result.as_records():
    print(row)
```

The Python API is intentionally project-backed: table listing, trusted SQL,
saved SQL files, inspect, sample, profile, configured checks, and export. It
does not provide direct-path sessions, ad hoc table mappings, config mutation,
dataframe helpers, async execution, plugins, or a second execution engine.
````

- [ ] **Step 2: Update `docs/ARCHITECTURE.md` API boundary**

Replace the `api.py` boundary entry with:

```markdown
`api.py`
: Small public Python wrapper around project-backed table listing, query, saved
  SQL, inspect, sample, profile, configured checks, and export services. It
  stores resolved project context, not a persistent DuckDB connection, and does
  not own CLI formatting or process-exit behavior.
```

Replace the current Python API design-choice bullet with:

```markdown
- The small Python API is project-config-only and uses short-lived execution per method for table listing, query, saved SQL, inspect, sample, profile, configured checks, and export.
```

- [ ] **Step 3: Update `docs/PRODUCT_DIRECTION.md` DuckDB support language**

Replace the paragraph that says `pyproject.toml` allows `duckdb>=1.0.0` and must raise or document the minimum with:

```markdown
The v1 contract-stabilization slice raises the package dependency floor to
`duckdb>=1.5.0,<2`, matching the current DuckDB 1.5.x lockfile family while
avoiding silent acceptance of old 1.0-era engines or a future DuckDB major
version.
```

- [ ] **Step 4: Update `docs/ROADMAP.md` Python API and remaining v1 bullets**

In the v0.8 implemented Python API list, replace the existing API bullets with:

```markdown
- `CSVQLSession.from_config(".csvql.yml")`
- `session.tables()`
- `session.query(sql)`
- `session.run_file(path)`
- `session.inspect(table, exact=False)`
- `session.sample(table, limit=10)`
- `session.profile(table)`
- `session.check(table=None)`
- `session.export(sql_file, out, format="json", force=False)`
- small typed result objects that wrap existing CLI-tested internals
- no direct-path session mode, dataframe framework, notebook integration, async API, plugin API, config mutation helpers, or second execution engine
```

Replace the `Remaining before v1` list with:

```markdown
Remaining before v1:

- release workflow and changelog or release-note material
- final release-candidate eligibility check after release workflow and release
  notes exist
```

- [ ] **Step 5: Review doc diffs**

Run:

```bash
git diff -- README.md docs/ARCHITECTURE.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md
```

Expected: diff only updates API scope, DuckDB support, and remaining v1 work.

- [ ] **Step 6: Commit user and architecture docs**

Run:

```bash
git add README.md docs/ARCHITECTURE.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md
git commit -m "docs: align v1 api and duckdb contracts"
```

Expected: commit succeeds and includes only the four documentation files.

## Task 5: Update JSON Contract And Release Readiness Docs

**Files:**
- Modify: `docs/json-contracts.md`
- Modify: `docs/release-readiness.md`

- [ ] **Step 1: Update `docs/json-contracts.md` scope**

Replace the opening scope list with:

```markdown
This document records the current `v1` JSON output contract for CSVQL's
automation-oriented command surfaces:

- `csvql query --output json`
- `csvql run --output json`
- `csvql inspect --output json`
- `csvql sample --output json`
- `csvql profile --output json`
- `csvql check --output json`
- `csvql doctor --output json`
- `csvql tables --output json`
- `csvql export --format json`
```

Replace the open-decision paragraph with:

```markdown
V1 decision: the current v0.8 JSON shapes are the stable v1 runtime contract. A
normalized envelope is not implemented in the current runtime and must not be
described as current behavior.
```

Replace the `Not covered here` list with:

```markdown
Not covered here:

- benchmark artifact JSON
- Python API result objects
```

- [ ] **Step 2: Add `sample --output json` current contract section**

Insert this section after the `inspect --output json` section:

````markdown
### sample --output json

Current top-level fields:

- `source`
- `limit`
- `columns`
- `rows`
- `warnings`

`sample.rows` is record-oriented JSON keyed by column name. `limit` is the
requested maximum row count, not a guarantee that the source contains that many
rows.

Example shape:

```json
{
  "columns": [
    "order_id",
    "status"
  ],
  "limit": 1,
  "rows": [
    {
      "order_id": "ORD-1",
      "status": "paid"
    }
  ],
  "source": {
    "display_path": "data/orders.csv",
    "fingerprint": {
      "modified_at": "<modified-at>",
      "size_bytes": 64,
      "version": 1
    },
    "modified_at": "<modified-at>",
    "resolved_path": "<tmp>/csvql-json-contracts-fixture/data/orders.csv",
    "size_bytes": 64
  },
  "warnings": []
}
```
````

- [ ] **Step 3: Add `doctor` and `tables` current contract sections**

Insert this section after the `check --output json` section:

```markdown
### doctor --output json

Current top-level fields:

- `status`
- `probe_count`
- `passed_count`
- `warning_count`
- `failed_count`
- `project`
- `probes`

`doctor` exits `0` for `passed` and `warning` results. It exits `12` when
concrete project-health failures are found.

### tables --output json

Current top-level fields:

- `config_path`
- `project_root`
- `tables`

Each `tables` entry includes:

- `name`
- `path`
- `resolved_path`

`config_path`, `project_root`, and `resolved_path` are machine-local absolute
paths.
```

- [ ] **Step 4: Update cross-command rules**

Add these bullets to `Cross-Command Rules In v0.8`:

```markdown
- `sample`, `inspect`, `profile`, `check`, and `doctor` include `warnings` or warning counts in their current shape.
- `tables` exposes machine-local absolute paths because it is a project catalog listing.
- `doctor` has a status-bearing JSON shape separate from `check`.
```

- [ ] **Step 5: Update possible future normalized contract wording**

Replace the heading `## Possible Future Normalized Contract` with:

```markdown
## Possible Post-v1 Normalized Contract
```

Replace `If adopted, normalization could use these rules:` with:

```markdown
If a post-v1 compatibility break adopts normalization, it should use these
rules:
```

- [ ] **Step 6: Update release-readiness label rules**

In `docs/release-readiness.md`, replace this sentence:

```markdown
Use `v1-hardening` for the current lane while authority docs, release notes,
and contract decisions are still being reconciled.
```

with:

```markdown
Use `v1-hardening` for the current lane while release workflow, release notes,
and final candidate proof are still being reconciled.
```

Add this bullet under `Use release-candidate only after:`:

```markdown
- current JSON shapes, exit codes, config schema, DuckDB dependency floor, and
  Python API surface are documented and test-backed
```

- [ ] **Step 7: Review contract doc diffs**

Run:

```bash
git diff -- docs/json-contracts.md docs/release-readiness.md
```

Expected: diff states current JSON shapes are stable for v1, adds sample/tables/doctor coverage, and updates release label rules.

- [ ] **Step 8: Commit contract docs**

Run:

```bash
git add docs/json-contracts.md docs/release-readiness.md
git commit -m "docs: stabilize v1 contract references"
```

Expected: commit succeeds and includes only `docs/json-contracts.md` and `docs/release-readiness.md`.

## Task 6: Run Full Local Proof

**Files:**
- No source edits in this task.
- Generated output under `output/` remains ignored.

- [ ] **Step 1: Run formatting check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
```

Expected: PASS.

- [ ] **Step 2: Run lint check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
```

Expected: PASS.

- [ ] **Step 3: Run type check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: PASS.

- [ ] **Step 4: Run test suite**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest
```

Expected: PASS for the full test suite.

- [ ] **Step 5: Run release-readiness proof**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

Expected: PASS. If this fails because dependency build or index access is blocked by the sandbox, rerun the same command with escalation.

- [ ] **Step 6: Run stale-claim scans**

Run:

```bash
rg -n "release-candidate|v1-stable|sandbox-safe|production-ready|large-file-proven|duckdb>=1\.0\.0|Open v1 decision" AGENTS.md README.md docs/ARCHITECTURE.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/json-contracts.md docs/release-readiness.md pyproject.toml
```

Expected: no unsupported `release-candidate`, `v1-stable`, sandbox, production, large-file, old DuckDB range, or open contract-decision claims remain. Mentions inside historical design or plan files are acceptable when they are explicitly historical or future-facing.

- [ ] **Step 7: Check whitespace and final diff**

Run:

```bash
git diff --check
git status --short --branch
```

Expected:

- `git diff --check` exits `0`.
- `git status --short --branch` shows no unstaged source/doc changes except ignored generated proof output.

- [ ] **Step 8: Commit proof status docs only when proof changes tracked docs**

Run this only if proof results require tracked documentation updates:

```bash
git add README.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/release-readiness.md
git commit -m "docs: refresh v1 contract proof status"
```

Expected: commit is skipped when no tracked docs changed during proof. Generated output under `output/` remains unstaged and ignored.

## Task 7: Final Review Before Execution Handoff

**Files:**
- No file edits in this task.

- [ ] **Step 1: Inspect final history**

Run:

```bash
git log --oneline -6
git status --short --branch
```

Expected:

- Recent commits show test, API, dependency, and docs commits from this plan.
- Worktree is clean on `main`, except ignored generated proof artifacts.

- [ ] **Step 2: Summarize implementation outcome**

Prepare a handoff summary with:

```markdown
Implemented:
- DuckDB dependency floor: `duckdb>=1.5.0,<2`
- Python API parity: `tables`, `inspect`, `sample`, `export`
- v1 contract docs: JSON shapes, exit codes, config schema, DuckDB support, API surface

Verification:
- `env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .`
- `env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .`
- `env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src`
- `env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest`
- `env UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness`

Remaining before release-candidate:
- release workflow and changelog or release-note material
- final release-candidate eligibility check after that material exists
```

Expected: summary does not claim `release-candidate` or `v1-stable`.

## Self-Review Checklist

- Spec coverage: every approved spec item maps to Tasks 1-6.
- Placeholder scan: the plan contains no incomplete task or unspecified implementation instruction.
- Type consistency: method names and return types match the spec and code snippets.
- Scope check: no direct-path API mode, config mutation, JSON envelope migration, exit-code redesign, dataframe helpers, async API, plugins, or safe-mode work is included.
- Verification: the plan requires focused API tests, full local gate, release-readiness proof, stale-claim scans, and final status review.
