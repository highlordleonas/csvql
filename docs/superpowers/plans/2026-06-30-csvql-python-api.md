# CSVQL Small Python API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a small project-config-only Python API centered on `CSVQLSession.from_config(...)` for query, saved SQL, profiling, and configured checks.

**Architecture:** Add one thin public wrapper module at `src/csvql/api.py` that stores resolved `ProjectContext` and delegates to existing CSVQL services with short-lived execution per method. Reuse the current `CSVQLError` hierarchy and existing typed result objects, avoid persistent DuckDB session state, and keep the file set tight: one new API module, one new API test module, and two small docs updates.

**Tech Stack:** Python 3.12, DuckDB, existing CSVQL service modules, `uv`, pytest, Ruff, mypy, Markdown docs.

---

## Preconditions

- Start from a clean worktree on the current feature branch.
- Use the committed spec at `docs/superpowers/specs/2026-06-30-csvql-python-api-design.md` as the authority for scope.
- Keep the slice project-config-only. Do not add direct-path sessions, persistent engines, `inspect()`/`sample()` methods, export helpers, or a new exception hierarchy.
- Sync the environment before editing:

```bash
uv sync --all-extras --frozen
```

- Confirm the repo gate is green before touching code:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

Expected: PASS for all commands.

## Scope And Constraints

- Add only this public API surface:
  - `CSVQLSession.from_config(start_dir=".")`
  - `session.query(sql)`
  - `session.run_file(path)`
  - `session.profile(table)`
  - `session.check(table=None, show_failures=False, failure_limit=5)`
- Return existing typed result objects:
  - `QueryResult`
  - `ProfileResult`
  - `CheckRunResult`
- Reuse the existing `CSVQLError` family directly.
- Resolve `run_file()` paths relative to the stored project root, not ambient `cwd`.
- Do not change CLI semantics, CLI JSON output, exit codes, or `.csvql.yml` schema.
- Do not add custom API result wrappers unless a test proves an existing type is insufficient.

## Command, JSON, Exit-Code, Docs, And Test Impact

Command impact:

- none
- this slice adds a library API only

JSON impact:

- none
- the API returns typed Python objects, not JSON payload helpers

Exit-code impact:

- none
- API methods should raise existing exceptions or return result objects; they do not own process exit behavior

Docs impact:

- modify `README.md` with a short Python API example
- modify `docs/ARCHITECTURE.md` to document `api.py` as a thin wrapper over existing services

Test impact:

- create `tests/test_api.py`
- keep existing repo gates unchanged

## File Structure

- Create: `src/csvql/api.py`
- Create: `tests/test_api.py`
- Modify: `src/csvql/__init__.py`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`

`src/csvql/api.py`
: public `CSVQLSession` wrapper over existing project-backed query, saved SQL, profiling, and configured-check services

`tests/test_api.py`
: focused library tests for session discovery, query/run/profile/check behavior, and error propagation

`src/csvql/__init__.py`
: export `CSVQLSession` from the package root

`README.md`
: small user-facing Python API example

`docs/ARCHITECTURE.md`
: note `api.py` as a thin public boundary over existing services

## Task 1: Add Failing API Proof Tests For Session Query And Saved SQL

**Files:**
- Create: `tests/test_api.py`

- [ ] **Step 1: Write the failing API tests for `from_config()`, `query()`, and `run_file()`**

Create `tests/test_api.py` with:

```python
from pathlib import Path

import pytest

from csvql.api import CSVQLSession
from csvql.exceptions import ProjectConfigError, QueryExecutionError, SQLFileError
from csvql.models import QueryResult


def _write_project(root: Path, *, rows: str = "ORD-001,paid\nORD-002,pending\n") -> None:
    (root / "data").mkdir(parents=True)
    (root / "queries").mkdir(parents=True)
    (root / "nested" / "child").mkdir(parents=True)
    (root / "data" / "orders.csv").write_text(
        "order_id,status\n" + rows,
        encoding="utf-8",
    )
    (root / "queries" / "count_orders.sql").write_text(
        "SELECT COUNT(*) AS order_count FROM orders",
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
```

- [ ] **Step 2: Run the focused failing API tests**

Run:

```bash
uv run pytest tests/test_api.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'csvql.api'`.

- [ ] **Step 3: Commit the failing test baseline**

```bash
git add tests/test_api.py
git commit -m "test: add python api query contract"
```

## Task 2: Implement `CSVQLSession.from_config()`, `query()`, And `run_file()`

**Files:**
- Create: `src/csvql/api.py`
- Modify: `src/csvql/__init__.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Implement the first thin API wrapper**

Create `src/csvql/api.py` with:

```python
"""Small public Python API for project-backed CSVQL workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from csvql.engine import CSVQLEngine
from csvql.models import QueryResult
from csvql.project_config import ProjectContext, load_project, project_tables_to_sources
from csvql.sql_file import load_sql_file


@dataclass(frozen=True, slots=True)
class CSVQLSession:
    """Thin project-backed API over existing CSVQL services."""

    _context: ProjectContext

    @classmethod
    def from_config(cls, start_dir: str | Path = ".") -> "CSVQLSession":
        return cls(load_project(Path(start_dir)))

    def query(self, sql: str) -> QueryResult:
        with CSVQLEngine() as engine:
            engine.register_tables(project_tables_to_sources(self._context))
            return engine.query(sql)

    def run_file(self, path: str | Path) -> QueryResult:
        sql_file = load_sql_file(str(path), base_dir=self._context.project_root)
        return self.query(sql_file.sql)
```

- [ ] **Step 2: Export the new API entrypoint from the package root**

Update `src/csvql/__init__.py` to:

```python
"""CSVQL public package interface."""

from csvql.api import CSVQLSession
from csvql.engine import CSVQLEngine
from csvql.models import QueryResult, TableSource

__all__ = ["CSVQLSession", "CSVQLEngine", "QueryResult", "TableSource"]

__version__ = "0.1.0"
```

- [ ] **Step 3: Run the focused API tests**

Run:

```bash
uv run pytest tests/test_api.py -q
```

Expected: PASS for the five tests from Task 1.

- [ ] **Step 4: Run narrow lint and type checks for the new module**

Run:

```bash
uv run ruff check src/csvql/api.py src/csvql/__init__.py tests/test_api.py
uv run mypy src
```

Expected: PASS.

- [ ] **Step 5: Commit the first API slice**

```bash
git add src/csvql/api.py src/csvql/__init__.py tests/test_api.py
git commit -m "feat: add python api query session"
```

## Task 3: Add Failing Tests For `profile()` And `check()`

**Files:**
- Modify: `tests/test_api.py`

- [ ] **Step 1: Extend the API test module with profile/check behavior and alias-error coverage**

Update the import blocks in `tests/test_api.py` to:

```python
from csvql.api import CSVQLSession
from csvql.exceptions import ProjectConfigError, QueryExecutionError, SQLFileError
from csvql.models import ProfileResult, QueryResult
from csvql.quality import CheckRunResult
```

Then append these tests to `tests/test_api.py`:

```python
def test_session_profile_returns_profile_result_for_catalog_alias(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    result = session.profile("orders")

    assert isinstance(result, ProfileResult)
    assert result.source["display_path"] == "orders"
    assert result.row_count == 2
    assert result.column_count == 2


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


def test_session_profile_propagates_invalid_table_alias_error(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(ProjectConfigError):
        session.profile("missing")
```

- [ ] **Step 2: Run the new focused tests and confirm they fail**

Run:

```bash
uv run pytest \
  tests/test_api.py::test_session_profile_returns_profile_result_for_catalog_alias \
  tests/test_api.py::test_session_check_returns_failed_result_without_raising \
  tests/test_api.py::test_session_profile_propagates_invalid_table_alias_error \
  -q
```

Expected: FAIL with `AttributeError: 'CSVQLSession' object has no attribute 'profile'`.

- [ ] **Step 3: Commit the failing profile/check proof**

```bash
git add tests/test_api.py
git commit -m "test: add python api profile and check coverage"
```

## Task 4: Implement `profile()` And `check()` Without Widening The API

**Files:**
- Modify: `src/csvql/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Extend `CSVQLSession` with profile/check methods and one private alias helper**

Update `src/csvql/api.py` to:

```python
"""Small public Python API for project-backed CSVQL workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from csvql.checks import run_configured_checks
from csvql.engine import CSVQLEngine
from csvql.exceptions import ProjectConfigError
from csvql.models import ProfileResult, QueryResult
from csvql.profiling import profile_csv_source
from csvql.project_config import (
    ProjectContext,
    ProjectTable,
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
    def from_config(cls, start_dir: str | Path = ".") -> "CSVQLSession":
        return cls(load_project(Path(start_dir)))

    def query(self, sql: str) -> QueryResult:
        with CSVQLEngine() as engine:
            engine.register_tables(project_tables_to_sources(self._context))
            return engine.query(sql)

    def run_file(self, path: str | Path) -> QueryResult:
        sql_file = load_sql_file(str(path), base_dir=self._context.project_root)
        return self.query(sql_file.sql)

    def profile(self, table: str) -> ProfileResult:
        project_table = _project_table(self._context, table)
        resolved_path = resolve_catalog_path(project_table, self._context)
        resolved_source = source_from_path(
            str(resolved_path),
            base_dir=self._context.project_root,
        )
        source = CSVSource(
            path=resolved_source.path,
            display_path=table,
            fingerprint=resolved_source.fingerprint,
        )
        return profile_csv_source(source)

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
```

- [ ] **Step 2: Run the API test module again**

Run:

```bash
uv run pytest tests/test_api.py -q
```

Expected: PASS for all eight tests.

- [ ] **Step 3: Run narrow formatting, lint, and type checks**

Run:

```bash
uv run ruff format --check src/csvql/api.py tests/test_api.py
uv run ruff check src/csvql/api.py tests/test_api.py
uv run mypy src
```

Expected: PASS.

- [ ] **Step 4: Commit the completed Python API implementation**

```bash
git add src/csvql/api.py tests/test_api.py
git commit -m "feat: add python api profile and checks"
```

## Task 5: Document The API And Run The Full Gate

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Test: `tests/test_api.py`

- [ ] **Step 1: Add a short Python API example to the README**

Insert this section in `README.md` after the development install / CLI introduction area:

````markdown
## Python API Example

CSVQL also exposes a small project-backed Python API:

```python
from csvql import CSVQLSession

session = CSVQLSession.from_config("examples/saas_revenue")
result = session.run_file("queries/revenue_health.sql")

for row in result.as_records():
    print(row)
```

The Python API is intentionally small: project-backed SQL, saved SQL files,
profiling, and configured checks only.
```
````

- [ ] **Step 2: Document `api.py` in the architecture boundaries**

In `docs/ARCHITECTURE.md`, add this new boundary entry near the other public surfaces:

```markdown
`api.py`
: Small public Python wrapper around project-backed query, saved SQL, profile,
  and check services. It stores resolved project context, not a persistent
  DuckDB connection, and does not own CLI formatting or exit behavior.
```

Also add this design-choice bullet in the lower list:

```markdown
- The small Python API is project-config-only and uses short-lived execution per method.
```

- [ ] **Step 3: Run the focused API tests plus the full repo gate**

Run:

```bash
uv run pytest tests/test_api.py -q
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
git diff --check
```

Expected: PASS for all commands.

- [ ] **Step 4: Commit the docs and final verification state**

```bash
git add README.md docs/ARCHITECTURE.md tests/test_api.py src/csvql/api.py src/csvql/__init__.py
git commit -m "docs: add python api usage"
```
