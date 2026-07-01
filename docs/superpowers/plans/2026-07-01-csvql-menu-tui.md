# CSVQL Menu TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `csvql menu` as an optional Textual-powered terminal UI that manages session-only CSV sources, runs existing inspect/sample/profile/query/export workflows, and leaves the public Python API unchanged.

**Architecture:** Keep `cli.py` as a thin Typer boundary and put TUI behavior in focused modules. `tui_state.py` owns in-memory source/result state, `tui_workflows.py` adapts existing CSVQL services, `tui_launcher.py` owns the optional dependency guard, and `tui_app.py` owns Textual screens and key bindings.

**Tech Stack:** Python 3.11+, Typer, DuckDB, Rich, Textual as optional `tui` extra, pytest, Ruff, mypy, uv.

---

## Scope Check

This plan implements one additive frontend: `csvql menu`.

It does not change:

- `csvql` root no-argument behavior
- existing `query`, `inspect`, `sample`, `profile`, `run`, `export`, `check`, `doctor`, `init`, `add`, or `tables` contracts
- `CSVQLSession` or package root exports
- DuckDB trusted-SQL posture
- project catalog schema

## Test Strategy

Use the repo's flat pytest layout. Target ratio for this slice:

- 70% fast unit tests for state and workflow orchestration
- 25% CLI/adapter tests with `CliRunner`
- 5% Textual app smoke tests through Textual's test harness

Run focused tests after each task and the full local gate at the end:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest
```

## File Structure

Create:

- `src/csvql/tui_state.py`: session-only source list, selected source, last query result, duplicate alias validation.
- `src/csvql/tui_workflows.py`: startup source loading and wrappers over inspect, sample, profile, query, export, and explicit catalog save.
- `src/csvql/tui_launcher.py`: lazy Textual import and install-extra error.
- `src/csvql/tui_app.py`: Textual app shell, source/result panels, key bindings, modal prompts.
- `tests/test_tui_state.py`: unit tests for session state.
- `tests/test_tui_workflows.py`: unit/integration tests for workflow adapters.
- `tests/test_cli_menu.py`: Typer command tests and dependency guard tests.
- `tests/test_tui_app.py`: minimal Textual smoke tests.

Modify:

- `pyproject.toml`: add optional `tui` extra with Textual.
- `uv.lock`: intentional dependency resolution update from `uv add`.
- `src/csvql/cli.py`: add thin `menu` command.
- `README.md`: add short TUI usage section.
- `docs/ROADMAP.md`: record the post-v1 TUI surface.

---

### Task 1: Add Optional Textual Dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Add Textual as an optional TUI dependency**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv add --optional tui textual
```

Expected:

- `pyproject.toml` has a `[project.optional-dependencies]` entry named `tui`.
- `uv.lock` changes intentionally.
- Existing `dev` optional dependencies remain intact.

The relevant `pyproject.toml` shape should be:

```toml
[project.optional-dependencies]
dev = [
    "mypy>=1.11.0",
    "pytest>=8.2.0",
    "ruff>=0.6.0",
]
tui = [
    "textual",
]
```

Keep the version constraint that `uv add` writes unless it is invalid or too loose for the project. Do not manually broaden unrelated dependencies.

- [ ] **Step 2: Verify Textual import through the extra-enabled environment**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras python -c "import textual; print(textual.__name__)"
```

Expected:

```text
textual
```

- [ ] **Step 3: Run dependency-change smoke checks**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected:

- Ruff format passes.
- Ruff lint passes.
- mypy passes.

- [ ] **Step 4: Commit dependency update**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add optional tui dependency"
```

---

### Task 2: Add Session State Model

**Files:**
- Create: `src/csvql/tui_state.py`
- Create: `tests/test_tui_state.py`

- [ ] **Step 1: Write failing state tests**

Create `tests/test_tui_state.py`:

```python
from pathlib import Path

import pytest

from csvql.exceptions import TableMappingError
from csvql.models import QueryResult, TableSource
from csvql.tui_state import TUISessionState, TUISource


def test_tui_source_converts_to_table_source(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    source = TUISource(name="orders", path=csv_path, origin="session")

    table_source = source.as_table_source()

    assert table_source == TableSource(name="orders", path=csv_path)


def test_session_state_adds_sources_in_order(tmp_path: Path) -> None:
    orders = TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument")
    customers = TUISource(name="customers", path=tmp_path / "customers.csv", origin="session")
    state = TUISessionState()

    state.add_source(orders)
    state.add_source(customers)

    assert state.sources == (orders, customers)
    assert state.selected_alias == "orders"
    assert state.table_sources == (
        TableSource(name="orders", path=orders.path),
        TableSource(name="customers", path=customers.path),
    )


def test_session_state_rejects_case_insensitive_duplicate_alias(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="Orders", path=tmp_path / "orders.csv", origin="session"))

    with pytest.raises(TableMappingError, match="Duplicate table alias"):
        state.add_source(TUISource(name="orders", path=tmp_path / "other.csv", origin="session"))


def test_session_state_removes_source_and_moves_selection(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="session"))
    state.add_source(TUISource(name="customers", path=tmp_path / "customers.csv", origin="session"))

    removed = state.remove_source("orders")

    assert removed.name == "orders"
    assert [source.name for source in state.sources] == ["customers"]
    assert state.selected_alias == "customers"


def test_session_state_remove_unknown_alias_fails(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="session"))

    with pytest.raises(TableMappingError, match="Source alias 'missing' is not loaded"):
        state.remove_source("missing")


def test_session_state_tracks_last_result() -> None:
    state = TUISessionState()
    result = QueryResult(columns=("count",), rows=((2,),), elapsed_ms=1.2)

    state.set_last_result(result)

    assert state.last_result == result
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_tui_state.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'csvql.tui_state'`.

- [ ] **Step 3: Implement TUI state**

Create `src/csvql/tui_state.py`:

```python
"""Session state for the interactive CSVQL terminal UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from csvql.exceptions import TableMappingError
from csvql.models import QueryResult, TableSource
from csvql.table_mapping import validate_table_alias

SourceOrigin = Literal["argument", "catalog", "session"]


@dataclass(frozen=True, slots=True)
class TUISource:
    """A CSV source loaded into the current TUI session."""

    name: str
    path: Path
    origin: SourceOrigin

    def __post_init__(self) -> None:
        validate_table_alias(self.name)

    def as_table_source(self) -> TableSource:
        """Return the query-engine table source for this TUI source."""

        return TableSource(name=self.name, path=self.path)


@dataclass(slots=True)
class TUISessionState:
    """Mutable in-memory state for one TUI run."""

    _sources: dict[str, TUISource] = field(default_factory=dict)
    _source_order: list[str] = field(default_factory=list)
    selected_alias: str | None = None
    last_result: QueryResult | None = None

    @property
    def sources(self) -> tuple[TUISource, ...]:
        return tuple(self._sources[key] for key in self._source_order)

    @property
    def table_sources(self) -> tuple[TableSource, ...]:
        return tuple(source.as_table_source() for source in self.sources)

    def add_source(self, source: TUISource) -> None:
        key = _alias_key(source.name)
        if key in self._sources:
            raise TableMappingError(
                f"Duplicate table alias '{source.name}' in TUI session.",
                suggestion="Choose a unique alias before adding the CSV source.",
            )
        self._sources[key] = source
        self._source_order.append(key)
        if self.selected_alias is None:
            self.selected_alias = source.name

    def remove_source(self, alias: str) -> TUISource:
        key = _alias_key(alias)
        try:
            source = self._sources.pop(key)
        except KeyError as exc:
            raise TableMappingError(
                f"Source alias '{alias}' is not loaded in the TUI session.",
                suggestion="Choose a loaded source alias from the source manager.",
            ) from exc
        self._source_order.remove(key)
        if self.selected_alias is not None and _alias_key(self.selected_alias) == key:
            self.selected_alias = self.sources[0].name if self.sources else None
        return source

    def select_source(self, alias: str) -> TUISource:
        source = self.get_source(alias)
        self.selected_alias = source.name
        return source

    def get_source(self, alias: str) -> TUISource:
        key = _alias_key(alias)
        try:
            return self._sources[key]
        except KeyError as exc:
            raise TableMappingError(
                f"Source alias '{alias}' is not loaded in the TUI session.",
                suggestion="Choose a loaded source alias from the source manager.",
            ) from exc

    def selected_source(self) -> TUISource | None:
        if self.selected_alias is None:
            return None
        return self.get_source(self.selected_alias)

    def set_last_result(self, result: QueryResult) -> None:
        self.last_result = result


def _alias_key(alias: str) -> str:
    return validate_table_alias(alias).casefold()
```

- [ ] **Step 4: Run state tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_tui_state.py -q
```

Expected: PASS.

- [ ] **Step 5: Run type and lint checks for the new module**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format src/csvql/tui_state.py tests/test_tui_state.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check src/csvql/tui_state.py tests/test_tui_state.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: all commands pass.

- [ ] **Step 6: Commit state model**

```bash
git add src/csvql/tui_state.py tests/test_tui_state.py
git commit -m "feat: add tui session state"
```

---

### Task 3: Add Startup Source Loading Workflows

**Files:**
- Create: `src/csvql/tui_workflows.py`
- Create: `tests/test_tui_workflows.py`

- [ ] **Step 1: Write failing startup workflow tests**

Create `tests/test_tui_workflows.py` with these initial tests:

```python
from pathlib import Path

import pytest

from csvql.exceptions import ProjectConfigError, TableMappingError
from csvql.tui_workflows import build_initial_state


def _write_csv(path: Path, content: str = "id,value\n1,alpha\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_initial_state_starts_empty_without_catalog(tmp_path: Path) -> None:
    state = build_initial_state(csv_path=None, table_mappings=(), start_dir=tmp_path)

    assert state.sources == ()


def test_build_initial_state_loads_catalog_sources(tmp_path: Path) -> None:
    orders = tmp_path / "data" / "orders.csv"
    _write_csv(orders)
    (tmp_path / ".csvql.yml").write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: data/orders.csv\n",
        encoding="utf-8",
    )

    state = build_initial_state(csv_path=None, table_mappings=(), start_dir=tmp_path)

    assert [(source.name, source.path, source.origin) for source in state.sources] == [
        ("orders", orders.resolve(), "catalog")
    ]


def test_build_initial_state_uses_single_csv_argument(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders-2026.csv"
    _write_csv(csv_path)

    state = build_initial_state(csv_path=str(csv_path), table_mappings=(), start_dir=tmp_path)

    assert [(source.name, source.path, source.origin) for source in state.sources] == [
        ("orders_2026", csv_path.resolve(), "argument")
    ]


def test_build_initial_state_uses_table_mappings(tmp_path: Path) -> None:
    customers = tmp_path / "customers.csv"
    orders = tmp_path / "orders.csv"
    _write_csv(customers)
    _write_csv(orders)

    state = build_initial_state(
        csv_path=None,
        table_mappings=(f"customers={customers}", f"orders={orders}"),
        start_dir=tmp_path,
    )

    assert [source.name for source in state.sources] == ["customers", "orders"]
    assert [source.origin for source in state.sources] == ["argument", "argument"]


def test_build_initial_state_rejects_duplicate_sources(tmp_path: Path) -> None:
    first = tmp_path / "orders.csv"
    second = tmp_path / "other.csv"
    _write_csv(first)
    _write_csv(second)

    with pytest.raises(TableMappingError, match="Duplicate table alias"):
        build_initial_state(
            csv_path=str(first),
            table_mappings=(f"orders={second}",),
            start_dir=tmp_path,
        )


def test_build_initial_state_preserves_invalid_catalog_errors(tmp_path: Path) -> None:
    (tmp_path / ".csvql.yml").write_text("version: [bad\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="Invalid YAML"):
        build_initial_state(csv_path=None, table_mappings=(), start_dir=tmp_path)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_tui_workflows.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'csvql.tui_workflows'`.

- [ ] **Step 3: Implement startup workflow helpers**

Create `src/csvql/tui_workflows.py`:

```python
"""Workflow adapters used by the interactive CSVQL terminal UI."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from csvql.exceptions import ProjectConfigError
from csvql.project_config import load_project, resolve_catalog_path
from csvql.table_mapping import parse_table_mapping, source_from_single_csv
from csvql.tui_state import TUISessionState, TUISource

_MISSING_PROJECT_PREFIX = "No .csvql.yml project catalog found."


def build_initial_state(
    *,
    csv_path: str | None,
    table_mappings: Sequence[str],
    start_dir: Path,
) -> TUISessionState:
    """Build the initial in-memory TUI session state."""

    state = TUISessionState()
    if csv_path is None and not table_mappings:
        for source in _catalog_sources(start_dir=start_dir):
            state.add_source(source)
        return state

    if csv_path is not None:
        table_source = source_from_single_csv(csv_path, base_dir=start_dir)
        state.add_source(
            TUISource(
                name=table_source.name,
                path=table_source.path,
                origin="argument",
            )
        )

    for raw_mapping in table_mappings:
        table_source = parse_table_mapping(raw_mapping, base_dir=start_dir)
        state.add_source(
            TUISource(
                name=table_source.name,
                path=table_source.path,
                origin="argument",
            )
        )

    return state


def _catalog_sources(*, start_dir: Path) -> tuple[TUISource, ...]:
    try:
        context = load_project(start_dir)
    except ProjectConfigError as exc:
        if exc.message.startswith(_MISSING_PROJECT_PREFIX):
            return ()
        raise

    return tuple(
        TUISource(
            name=table.name,
            path=resolve_catalog_path(table, context),
            origin="catalog",
        )
        for table in context.config.tables
    )
```

- [ ] **Step 4: Run startup workflow tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_tui_workflows.py -q
```

Expected: PASS.

- [ ] **Step 5: Run focused checks**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format src/csvql/tui_workflows.py tests/test_tui_workflows.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check src/csvql/tui_workflows.py tests/test_tui_workflows.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: all commands pass.

- [ ] **Step 6: Commit startup workflows**

```bash
git add src/csvql/tui_workflows.py tests/test_tui_workflows.py
git commit -m "feat: load tui startup sources"
```

---

### Task 4: Add TUI Service Workflows

**Files:**
- Modify: `src/csvql/tui_workflows.py`
- Modify: `tests/test_tui_workflows.py`

- [ ] **Step 1: Add failing workflow action tests**

Append to `tests/test_tui_workflows.py`:

```python
import json

from csvql.export import ExportFormat
from csvql.models import QueryResult
from csvql.project_config import load_project
from csvql.tui_state import TUISource
from csvql.tui_workflows import (
    export_last_result,
    inspect_source,
    profile_source,
    query_sources,
    sample_source,
    save_sources_to_project_catalog,
)


def test_inspect_sample_and_profile_source_return_typed_results(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path, "order_id,status\nORD-1,paid\n")
    source = TUISource(name="orders", path=csv_path, origin="session")

    inspect_result = inspect_source(source)
    sample_result = sample_source(source, limit=1)
    profile_result = profile_source(source)

    assert inspect_result.source["display_path"] == "orders"
    assert sample_result.rows == (("ORD-1", "paid"),)
    assert profile_result.row_count == 1


def test_query_sources_supports_joins(tmp_path: Path) -> None:
    customers = tmp_path / "customers.csv"
    orders = tmp_path / "orders.csv"
    _write_csv(customers, "customer_id,email\nCUST-1,a@example.com\n")
    _write_csv(orders, "order_id,customer_id,total_amount\nORD-1,CUST-1,12.50\n")

    result = query_sources(
        (
            TUISource(name="customers", path=customers, origin="session"),
            TUISource(name="orders", path=orders, origin="session"),
        ),
        (
            "SELECT c.email, SUM(o.total_amount) AS revenue "
            "FROM customers c JOIN orders o USING (customer_id) "
            "GROUP BY c.email"
        ),
    )

    assert result.columns == ("email", "revenue")
    assert result.rows == (("a@example.com", 12.5),)


def test_export_last_result_writes_selected_format(tmp_path: Path) -> None:
    output_path = tmp_path / "result.json"
    result = QueryResult(columns=("count",), rows=((2,),), elapsed_ms=1.2)

    written_path = export_last_result(
        result,
        str(output_path),
        export_format=ExportFormat.json,
        base_dir=tmp_path,
        force=False,
    )

    assert written_path == output_path
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["rows"] == [{"count": 2}]


def test_save_sources_to_project_catalog_creates_catalog_when_missing(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    source = TUISource(name="orders", path=csv_path, origin="session")

    context = save_sources_to_project_catalog((source,), start_dir=tmp_path, replace=True)

    assert context.config_path == tmp_path / ".csvql.yml"
    reloaded = load_project(tmp_path)
    assert [table.name for table in reloaded.config.tables] == ["orders"]
    assert reloaded.config.tables[0].path == "orders.csv"
```

- [ ] **Step 2: Run action tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_tui_workflows.py -q
```

Expected: FAIL with import errors for `inspect_source`, `sample_source`, `profile_source`, `query_sources`, `export_last_result`, and `save_sources_to_project_catalog`.

- [ ] **Step 3: Add service workflow functions**

Append these imports and functions to `src/csvql/tui_workflows.py`:

```python
from csvql.engine import CSVQLEngine
from csvql.export import (
    ExportFormat,
    format_query_result_for_export,
    resolve_export_path,
    write_export_file,
)
from csvql.inspection import inspect_csv_source, sample_csv_source
from csvql.models import InspectResult, ProfileResult, QueryResult, SampleResult
from csvql.profiling import profile_csv_source
from csvql.project_config import ProjectContext, add_project_table, initialize_project
from csvql.source import CSVSource, source_from_path
```

Then add:

```python
def inspect_source(source: TUISource, *, exact: bool = False) -> InspectResult:
    """Inspect a TUI source using existing CSVQL inspect behavior."""

    return inspect_csv_source(_csv_source(source), exact=exact)


def sample_source(source: TUISource, *, limit: int = 10) -> SampleResult:
    """Sample a TUI source using existing CSVQL sample behavior."""

    return sample_csv_source(_csv_source(source), limit=limit)


def profile_source(source: TUISource) -> ProfileResult:
    """Profile a TUI source using existing CSVQL profile behavior."""

    return profile_csv_source(_csv_source(source))


def query_sources(sources: Sequence[TUISource], sql: str) -> QueryResult:
    """Run trusted SQL against currently loaded TUI sources."""

    with CSVQLEngine() as engine:
        engine.register_tables(source.as_table_source() for source in sources)
        return engine.query(sql)


def export_last_result(
    result: QueryResult,
    path_value: str,
    *,
    export_format: ExportFormat,
    base_dir: Path,
    force: bool = False,
) -> Path:
    """Write an explicit export for the current query result."""

    output_path = resolve_export_path(path_value, base_dir=base_dir, force=force)
    content = format_query_result_for_export(result, export_format)
    write_export_file(output_path, content)
    return output_path


def save_sources_to_project_catalog(
    sources: Sequence[TUISource],
    *,
    start_dir: Path,
    replace: bool,
) -> ProjectContext:
    """Persist loaded TUI sources to the nearest project catalog explicitly."""

    context = _load_or_initialize_project(start_dir)
    for source in sources:
        context = add_project_table(
            context,
            source.name,
            str(source.path),
            replace=replace,
            invocation_dir=context.project_root,
        )
    return context


def _csv_source(source: TUISource) -> CSVSource:
    resolved = source_from_path(str(source.path))
    return CSVSource(
        path=resolved.path,
        display_path=source.name,
        fingerprint=resolved.fingerprint,
    )


def _load_or_initialize_project(start_dir: Path) -> ProjectContext:
    try:
        return load_project(start_dir)
    except ProjectConfigError as exc:
        if exc.message.startswith(_MISSING_PROJECT_PREFIX):
            return initialize_project(start_dir)
        raise
```

- [ ] **Step 4: Run workflow tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_tui_workflows.py -q
```

Expected: PASS.

- [ ] **Step 5: Run query/export regression tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_query_workflow.py tests/test_export.py tests/test_project_config.py -q
```

Expected: PASS.

- [ ] **Step 6: Run focused checks**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format src/csvql/tui_workflows.py tests/test_tui_workflows.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check src/csvql/tui_workflows.py tests/test_tui_workflows.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: all commands pass.

- [ ] **Step 7: Commit service workflows**

```bash
git add src/csvql/tui_workflows.py tests/test_tui_workflows.py
git commit -m "feat: add tui workflow adapters"
```

---

### Task 5: Add Thin CLI Command And Optional Dependency Guard

**Files:**
- Create: `src/csvql/tui_launcher.py`
- Modify: `src/csvql/cli.py`
- Create: `tests/test_cli_menu.py`

- [ ] **Step 1: Write failing CLI command tests**

Create `tests/test_cli_menu.py`:

```python
from pathlib import Path

from typer.testing import CliRunner

from csvql.cli import app
from csvql.exceptions import CSVQLError

runner = CliRunner()


def test_root_no_args_still_shows_help() -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "Query local CSV files with DuckDB SQL." in result.output


def test_menu_help_lists_startup_options() -> None:
    result = runner.invoke(app, ["menu", "--help"])

    assert result.exit_code == 0
    assert "Open the interactive CSVQL terminal menu." in result.output
    assert "--table" in result.output
    assert "CSV file to preload" in result.output


def test_menu_delegates_startup_arguments(
    tmp_path: Path,
    monkeypatch,
) -> None:
    csv_path = tmp_path / "orders.csv"
    customers = tmp_path / "customers.csv"
    csv_path.write_text("id\n1\n", encoding="utf-8")
    customers.write_text("id\n1\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_menu_command(
        *,
        csv_path: str | None,
        table_mappings: tuple[str, ...],
        start_dir: Path,
    ) -> None:
        captured["csv_path"] = csv_path
        captured["table_mappings"] = table_mappings
        captured["start_dir"] = start_dir

    monkeypatch.setattr("csvql.cli.run_menu_command", fake_run_menu_command)

    result = runner.invoke(
        app,
        ["menu", str(csv_path), "--table", f"customers={customers}"],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "csv_path": str(csv_path),
        "table_mappings": (f"customers={customers}",),
        "start_dir": Path.cwd(),
    }


def test_menu_errors_use_existing_cli_error_path(monkeypatch) -> None:
    def fake_run_menu_command(
        *,
        csv_path: str | None,
        table_mappings: tuple[str, ...],
        start_dir: Path,
    ) -> None:
        raise CSVQLError(
            "CSVQL TUI dependency is not installed.",
            suggestion='Install with pip install "csvql[tui]".',
        )

    monkeypatch.setattr("csvql.cli.run_menu_command", fake_run_menu_command)

    result = runner.invoke(app, ["menu"])

    assert result.exit_code == 1
    assert "CSVQL TUI dependency is not installed." in result.output
    assert 'Install with pip install "csvql[tui]".' in result.output
```

- [ ] **Step 2: Run CLI tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_menu.py -q
```

Expected: FAIL because `menu` and `run_menu_command` do not exist.

- [ ] **Step 3: Add lazy TUI launcher**

Create `src/csvql/tui_launcher.py`:

```python
"""Lazy launcher for the optional Textual-powered CSVQL TUI."""

from collections.abc import Sequence
from pathlib import Path

from csvql.exceptions import CSVQLError


def run_menu_command(
    *,
    csv_path: str | None,
    table_mappings: Sequence[str],
    start_dir: Path,
) -> None:
    """Run the Textual TUI or raise a clear install-extra error."""

    try:
        from csvql.tui_app import CSVQLMenuApp
    except ModuleNotFoundError as exc:
        if exc.name == "textual":
            raise CSVQLError(
                "CSVQL TUI dependency is not installed.",
                suggestion='Install with pip install "csvql[tui]" or run uv sync --all-extras.',
            ) from exc
        raise

    CSVQLMenuApp(
        csv_path=csv_path,
        table_mappings=tuple(table_mappings),
        start_dir=start_dir,
    ).run()
```

- [ ] **Step 4: Add `menu` command to `src/csvql/cli.py`**

Add this import near the other local imports:

```python
from csvql.tui_launcher import run_menu_command
```

Add this command before `inspect`:

```python
@app.command()
def menu(
    csv_path: Annotated[
        str | None,
        typer.Argument(help="CSV file to preload into the TUI session."),
    ] = None,
    table: Annotated[
        list[str] | None,
        typer.Option(
            "--table",
            "-t",
            help="Table mapping in name=path form. Repeat for multiple CSV files.",
        ),
    ] = None,
) -> None:
    """Open the interactive CSVQL terminal menu."""

    try:
        run_menu_command(
            csv_path=csv_path,
            table_mappings=tuple(table or ()),
            start_dir=Path.cwd(),
        )
    except CSVQLError as exc:
        _exit_with_error(exc)
```

- [ ] **Step 5: Add temporary Textual app stub for CLI import**

Create `src/csvql/tui_app.py` with a minimal stub that Task 6 replaces:

```python
"""Textual application shell for the interactive CSVQL terminal UI."""


class CSVQLMenuApp:
    """Temporary TUI shell replaced by the Textual app implementation."""

    def __init__(
        self,
        *,
        csv_path: str | None,
        table_mappings: tuple[str, ...],
        start_dir,
    ) -> None:
        self.csv_path = csv_path
        self.table_mappings = table_mappings
        self.start_dir = start_dir

    def run(self) -> None:
        return None
```

- [ ] **Step 6: Run CLI menu tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_menu.py -q
```

Expected: PASS.

- [ ] **Step 7: Run CLI regression tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_query.py tests/test_cli_inspect_sample.py tests/test_cli_profile.py -q
```

Expected: PASS.

- [ ] **Step 8: Run focused checks**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format src/csvql/cli.py src/csvql/tui_launcher.py src/csvql/tui_app.py tests/test_cli_menu.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check src/csvql/cli.py src/csvql/tui_launcher.py src/csvql/tui_app.py tests/test_cli_menu.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: all commands pass.

- [ ] **Step 9: Commit CLI command**

```bash
git add src/csvql/cli.py src/csvql/tui_launcher.py src/csvql/tui_app.py tests/test_cli_menu.py
git commit -m "feat: add menu command"
```

---

### Task 6: Add Textual App Shell

**Files:**
- Modify: `src/csvql/tui_app.py`
- Create: `tests/test_tui_app.py`

- [ ] **Step 1: Write failing Textual smoke tests**

Create `tests/test_tui_app.py`:

```python
import asyncio
from pathlib import Path

from textual.widgets import DataTable, Static

from csvql.tui_app import CSVQLMenuApp
from csvql.tui_state import TUISessionState, TUISource


def test_tui_app_renders_loaded_sources(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("id\n1\n", encoding="utf-8")
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=csv_path, origin="session"))

    async def run_app() -> None:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            table = pilot.app.query_one("#sources", DataTable)
            status = pilot.app.query_one("#status", Static)
            assert table.row_count == 1
            assert "1 source loaded" in str(status.renderable)

    asyncio.run(run_app())


def test_tui_app_starts_empty_without_sources(tmp_path: Path) -> None:
    async def run_app() -> None:
        app = CSVQLMenuApp(initial_state=TUISessionState(), start_dir=tmp_path)
        async with app.run_test() as pilot:
            table = pilot.app.query_one("#sources", DataTable)
            status = pilot.app.query_one("#status", Static)
            assert table.row_count == 0
            assert "No sources loaded" in str(status.renderable)

    asyncio.run(run_app())
```

- [ ] **Step 2: Run Textual smoke tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: FAIL because `CSVQLMenuApp` is still the temporary stub.

- [ ] **Step 3: Replace app stub with Textual shell**

Replace `src/csvql/tui_app.py` with:

```python
"""Textual application shell for the interactive CSVQL terminal UI."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Static, TextArea

from csvql.exceptions import CSVQLError
from csvql.output import format_table_result
from csvql.tui_state import TUISessionState
from csvql.tui_workflows import build_initial_state, query_sources


class CSVQLMenuApp(App[None]):
    """Interactive terminal app for session-backed CSVQL workflows."""

    CSS = """
    #layout {
        height: 1fr;
    }

    #left-pane {
        width: 36%;
        min-width: 32;
    }

    #right-pane {
        width: 1fr;
    }

    #sql {
        height: 10;
    }

    #results {
        height: 1fr;
    }

    #status {
        height: 3;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "run_query", "Run SQL"),
    ]

    def __init__(
        self,
        *,
        csv_path: str | None = None,
        table_mappings: tuple[str, ...] = (),
        start_dir: Path | None = None,
        initial_state: TUISessionState | None = None,
    ) -> None:
        super().__init__()
        self.start_dir = (start_dir or Path.cwd()).resolve()
        self.state = initial_state or build_initial_state(
            csv_path=csv_path,
            table_mappings=table_mappings,
            start_dir=self.start_dir,
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="layout"):
            with Vertical(id="left-pane"):
                yield Static("Sources", id="sources-title")
                yield DataTable(id="sources")
            with Vertical(id="right-pane"):
                yield TextArea("", language="sql", id="sql")
                yield Static("Run a query with Ctrl+R or press r.", id="status")
                yield Static("", id="results")
        yield Footer()

    def on_mount(self) -> None:
        sources = self.query_one("#sources", DataTable)
        sources.cursor_type = "row"
        sources.add_columns("alias", "path", "origin")
        self._refresh_sources()
        self._set_status(_source_status_text(self.state))

    def action_run_query(self) -> None:
        sql = self.query_one("#sql", TextArea).text.strip()
        if not sql:
            self._set_status("Enter SQL before running a query.")
            return
        if not self.state.sources:
            self._set_status("Add at least one source before running SQL.")
            return
        try:
            result = query_sources(self.state.sources, sql)
        except CSVQLError as exc:
            self._set_status(_error_text(exc))
            return
        self.state.set_last_result(result)
        self.query_one("#results", Static).update(format_table_result(result))
        self._set_status(f"{result.row_count} row(s) returned.")

    def _refresh_sources(self) -> None:
        table = self.query_one("#sources", DataTable)
        table.clear()
        for source in self.state.sources:
            table.add_row(source.name, str(source.path), source.origin)

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)


def _source_status_text(state: TUISessionState) -> str:
    count = len(state.sources)
    if count == 0:
        return "No sources loaded. Add a source before running SQL."
    if count == 1:
        return "1 source loaded."
    return f"{count} sources loaded."


def _error_text(error: CSVQLError) -> str:
    if error.suggestion:
        return f"Error: {error.message}\nSuggestion: {error.suggestion}"
    return f"Error: {error.message}"
```

- [ ] **Step 4: Run Textual smoke tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: PASS.

- [ ] **Step 5: Run focused checks**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format src/csvql/tui_app.py tests/test_tui_app.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check src/csvql/tui_app.py tests/test_tui_app.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src
```

Expected: all commands pass.

- [ ] **Step 6: Commit Textual shell**

```bash
git add src/csvql/tui_app.py tests/test_tui_app.py
git commit -m "feat: add textual menu shell"
```

---

### Task 7: Add TUI Source And Result Actions

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Add failing action tests**

Append to `tests/test_tui_app.py`:

```python
from textual.widgets import Input


def test_tui_app_add_source_action_adds_mapping(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("id\n1\n", encoding="utf-8")

    async def run_app() -> None:
        app = CSVQLMenuApp(initial_state=TUISessionState(), start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("a")
            input_widget = pilot.app.query_one("#mapping-input", Input)
            input_widget.value = f"orders={csv_path}"
            await pilot.press("enter")
            table = pilot.app.query_one("#sources", DataTable)
            assert table.row_count == 1
            assert [source.name for source in pilot.app.state.sources] == ["orders"]

    asyncio.run(run_app())


def test_tui_app_export_action_requires_last_result(tmp_path: Path) -> None:
    async def run_app() -> None:
        app = CSVQLMenuApp(initial_state=TUISessionState(), start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("e")
            status = pilot.app.query_one("#status", Static)
            assert "Run a query before exporting" in str(status.renderable)

    asyncio.run(run_app())
```

- [ ] **Step 2: Run action tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: FAIL because add-source and export actions do not exist.

- [ ] **Step 3: Add source modal and action bindings**

Update `src/csvql/tui_app.py` imports:

```python
from textual.screen import ModalScreen
from textual.widgets import Button, Input

from csvql.export import ExportFormat
from csvql.table_mapping import parse_table_mapping
from csvql.tui_state import TUISessionState, TUISource
from csvql.tui_workflows import (
    build_initial_state,
    export_last_result,
    inspect_source,
    profile_source,
    query_sources,
    sample_source,
    save_sources_to_project_catalog,
)
```

Update `BINDINGS`:

```python
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("a", "add_source", "Add Source"),
        ("d", "remove_selected_source", "Remove Source"),
        ("i", "inspect_selected_source", "Inspect"),
        ("p", "profile_selected_source", "Profile"),
        ("m", "sample_selected_source", "Sample"),
        ("r", "run_query", "Run SQL"),
        ("e", "export_last_result", "Export"),
        ("s", "save_sources", "Save Sources"),
    ]
```

Add modal screens above `CSVQLMenuApp`:

```python
class MappingInputScreen(ModalScreen[str | None]):
    """Prompt for a name=path mapping."""

    def compose(self) -> ComposeResult:
        yield Static("Add source as name=path")
        yield Input(placeholder="orders=/path/to/orders.csv", id="mapping-input")
        yield Button("Add", id="confirm")
        yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self.dismiss(self.query_one("#mapping-input", Input).value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)


class ExportInputScreen(ModalScreen[str | None]):
    """Prompt for an export output path."""

    def compose(self) -> ComposeResult:
        yield Static("Export last result")
        yield Input(placeholder="output/result.csv", id="export-path")
        yield Button("Export", id="confirm")
        yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self.dismiss(self.query_one("#export-path", Input).value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)
```

Add these methods to `CSVQLMenuApp`:

```python
    def action_add_source(self) -> None:
        self.push_screen(MappingInputScreen(), self._add_source_from_mapping)

    def action_remove_selected_source(self) -> None:
        selected = self.state.selected_source()
        if selected is None:
            self._set_status("No source selected.")
            return
        try:
            removed = self.state.remove_source(selected.name)
        except CSVQLError as exc:
            self._set_status(_error_text(exc))
            return
        self._refresh_sources()
        self._set_status(f"Removed source {removed.name}.")

    def action_inspect_selected_source(self) -> None:
        selected = self.state.selected_source()
        if selected is None:
            self._set_status("No source selected.")
            return
        try:
            result = inspect_source(selected)
        except CSVQLError as exc:
            self._set_status(_error_text(exc))
            return
        column_names = ", ".join(column.name for column in result.columns)
        self._set_status(f"{selected.name}: {len(result.columns)} columns.")
        self.query_one("#results", Static).update(column_names)

    def action_sample_selected_source(self) -> None:
        selected = self.state.selected_source()
        if selected is None:
            self._set_status("No source selected.")
            return
        try:
            result = sample_source(selected, limit=10)
        except CSVQLError as exc:
            self._set_status(_error_text(exc))
            return
        preview = QueryResult(columns=result.columns, rows=result.rows, elapsed_ms=0.0)
        self.query_one("#results", Static).update(format_table_result(preview))
        self._set_status(f"Sampled {len(result.rows)} row(s) from {selected.name}.")

    def action_profile_selected_source(self) -> None:
        selected = self.state.selected_source()
        if selected is None:
            self._set_status("No source selected.")
            return
        try:
            result = profile_source(selected)
        except CSVQLError as exc:
            self._set_status(_error_text(exc))
            return
        self._set_status(
            f"{selected.name}: {result.row_count} rows, {result.column_count} columns."
        )
        lines = [
            f"Rows: {result.row_count}",
            f"Columns: {result.column_count}",
            f"Duplicate rows: {result.duplicate_row_count}",
        ]
        self.query_one("#results", Static).update("\n".join(lines))

    def action_export_last_result(self) -> None:
        if self.state.last_result is None:
            self._set_status("Run a query before exporting.")
            return
        self.push_screen(ExportInputScreen(), self._export_to_path)

    def action_save_sources(self) -> None:
        if not self.state.sources:
            self._set_status("No sources loaded to save.")
            return
        try:
            context = save_sources_to_project_catalog(
                self.state.sources,
                start_dir=self.start_dir,
                replace=True,
            )
        except CSVQLError as exc:
            self._set_status(_error_text(exc))
            return
        self._set_status(f"Saved sources to {context.config_path}.")

    def _add_source_from_mapping(self, raw_mapping: str | None) -> None:
        if not raw_mapping:
            self._set_status("Add source cancelled.")
            return
        try:
            table_source = parse_table_mapping(raw_mapping, base_dir=self.start_dir)
            self.state.add_source(
                TUISource(
                    name=table_source.name,
                    path=table_source.path,
                    origin="session",
                )
            )
        except CSVQLError as exc:
            self._set_status(_error_text(exc))
            return
        self._refresh_sources()
        self._set_status(f"Added source {table_source.name}.")

    def _export_to_path(self, path_value: str | None) -> None:
        if not path_value:
            self._set_status("Export cancelled.")
            return
        result = self.state.last_result
        if result is None:
            self._set_status("Run a query before exporting.")
            return
        export_format = _export_format_from_path(path_value)
        try:
            output_path = export_last_result(
                result,
                path_value,
                export_format=export_format,
                base_dir=self.start_dir,
                force=False,
            )
        except CSVQLError as exc:
            self._set_status(_error_text(exc))
            return
        self._set_status(f"Wrote export to {output_path}.")
```

Add this helper near `_error_text`:

```python
def _export_format_from_path(path_value: str) -> ExportFormat:
    suffix = Path(path_value).suffix.lower()
    if suffix == ".csv":
        return ExportFormat.csv
    if suffix == ".md":
        return ExportFormat.markdown
    return ExportFormat.json
```

- [ ] **Step 4: Keep selected source in sync with DataTable cursor**

Add this method to `CSVQLMenuApp`:

```python
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "sources":
            return
        row_index = event.cursor_row
        if row_index < 0 or row_index >= len(self.state.sources):
            return
        self.state.select_source(self.state.sources[row_index].name)
```

- [ ] **Step 5: Run Textual action tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: PASS.

- [ ] **Step 6: Run TUI workflow and CLI tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py tests/test_tui_workflows.py tests/test_cli_menu.py tests/test_tui_app.py -q
```

Expected: PASS.

- [ ] **Step 7: Run focused checks**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format src/csvql/tui_app.py tests/test_tui_app.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check src/csvql/tui_app.py tests/test_tui_app.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src
```

Expected: all commands pass.

- [ ] **Step 8: Commit TUI actions**

```bash
git add src/csvql/tui_app.py tests/test_tui_app.py
git commit -m "feat: add tui source actions"
```

---

### Task 8: Document TUI Usage

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Update README**

Add this section after the development install instructions:

```markdown
## Interactive Terminal Menu

CSVQL can also run an optional Textual-powered terminal menu:

```bash
csvql menu
csvql menu /path/to/orders.csv
csvql menu --table customers=customers.csv --table orders=orders.csv
```

Install the optional TUI dependency before using the menu:

```bash
pip install "csvql[tui]"
```

The menu is session-backed by default. Sources added inside the TUI live only
for the current session unless you explicitly save them to a `.csvql.yml`
project catalog. Exports are written only when you choose the export action.

The SQL editor uses the same trusted local DuckDB execution posture as the rest
of CSVQL. Do not run untrusted SQL.
```

- [ ] **Step 2: Update roadmap**

In `docs/ROADMAP.md`, add under `Post-v1 - Future Expansion Candidates` or the current completed post-v1 area:

```markdown
- optional Textual-powered `csvql menu` TUI for session-backed source
  management, inspect/sample/profile, SQL querying, and explicit exports
```

- [ ] **Step 3: Run docs diff check**

Run:

```bash
git diff --check README.md docs/ROADMAP.md
```

Expected: no output.

- [ ] **Step 4: Commit docs**

```bash
git add README.md docs/ROADMAP.md
git commit -m "docs: document menu tui"
```

---

### Task 9: Final Verification

**Files:**
- Read: full working tree diff and latest commits

- [ ] **Step 1: Run full format check**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
```

Expected: `58 files already formatted` or an updated formatted-file count with exit code `0`.

- [ ] **Step 2: Run full lint check**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 3: Run full type check with all extras**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src
```

Expected: `Success: no issues found in 29 source files` or the correct updated source-file count.

- [ ] **Step 4: Run full test suite with all extras**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest
```

Expected: all tests pass.

- [ ] **Step 5: Run CLI smoke checks**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras csvql --help
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras csvql menu --help
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql --version
```

Expected:

- root help still shows normal CSVQL help
- menu help lists `csv_path` and repeated `--table`
- version still prints `1.0.0`

- [ ] **Step 6: Run real CSV query regression**

Use the user CSV if it exists locally:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query --table payloads=/Users/richarddemke/Desktop/enerflo_payloads.csv "SELECT COUNT(*) AS row_count FROM payloads"
```

Expected: one table is printed, not duplicated.

- [ ] **Step 7: Inspect final diff**

```bash
git status --short --branch
git diff --stat
git diff --check
```

Expected:

- only intended TUI files, docs, `pyproject.toml`, and `uv.lock` changed
- no whitespace errors

---

## Spec Coverage Review

- Source manager: Tasks 2, 3, 6, and 7.
- `csvql menu` command shapes: Tasks 3 and 5.
- Session-only default: Tasks 2, 3, and 7.
- Multiple CSV joins: Task 4.
- Explicit export: Tasks 4 and 7.
- Explicit project catalog save: Tasks 4 and 7.
- Python API unchanged: Tasks 5 and 9 keep `CSVQLSession` untouched and run API regression tests through the full suite.
- Optional Textual dependency: Tasks 1 and 5.
- Existing CLI behavior unchanged: Tasks 5 and 9.
- Trusted SQL boundary and no safe-mode claim: Tasks 4, 8, and 9.
