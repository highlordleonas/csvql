# Project Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add v0.3 project catalog support so users can register CSV tables in `.csvql.yml` and query them without repeating `--table` mappings.

**Architecture:** Add a focused `project_config.py` layer for catalog discovery, safe YAML load/dump, validation, mutation, and table-source conversion. Keep `cli.py` as a thin Typer boundary, reuse existing table alias/path validation, and keep DuckDB execution in `engine.py`.

**Tech Stack:** Python 3.11+, Typer, DuckDB, Rich, PyYAML, pytest, Ruff, mypy, `uv`.

---

## Scope Boundaries

Implement this batch:

- `.csvql.yml` with `version: 1` and `tables.<name>.path`
- `PyYAML` runtime dependency using `yaml.safe_load` and `yaml.safe_dump`
- `csvql init [--force]`
- `csvql add <name> <path> [--replace]`
- `csvql tables --output table|json`
- project discovery by walking upward from the current directory
- catalog paths resolved relative to the project root
- catalog-backed inline `csvql query "SELECT ..."`
- explicit `--table` mappings merged over catalog aliases for that invocation
- focused unit, CLI, docs, and verification coverage

Do not implement this batch:

- registered-table support for `csvql inspect`
- registered-table support for `csvql sample`
- `csvql run`
- `csvql export`
- profiling
- data quality checks
- reader options
- type overrides
- safe mode
- sandboxing
- cache or materialization
- Python API
- cloud or remote data sources

## Execution Starting Point

Start from the clean committed branch:

```bash
cd /Users/richarddemke/.codex/worktrees/ea7e/csvql
git status --short --branch
git log --oneline -3
```

Expected:

```text
## codex/inspect-sample-stabilization
?? docs/superpowers/plans/
ef78127 docs: design project catalog workflow
89c7d6d chore: stabilize inspect and sample workflow
81884b2 docs: document inspect and sample workflow
```

Create a feature branch before implementation:

```bash
git switch -c codex/project-catalog
```

Keep the older untracked `docs/superpowers/plans/2026-06-26-inspect-sample.md` out of all commits unless the user explicitly asks to commit it.

## File Structure

- Modify `pyproject.toml`: add `PyYAML` runtime dependency and mypy override if needed.
- Modify `uv.lock`: intentional lock update from adding `PyYAML`.
- Modify `src/csvql/exceptions.py`: add `ProjectConfigError`.
- Create `src/csvql/project_config.py`: catalog constants, value objects, discovery, validation, safe YAML load/dump, add/replace, listing, and `TableSource` conversion.
- Modify `src/csvql/output.py`: add table and JSON renderers for project table listings.
- Modify `src/csvql/cli.py`: add `init`, `add`, `tables`; update inline query request building for catalog tables and explicit override behavior.
- Create `tests/test_project_config.py`: unit tests for catalog behavior.
- Create `tests/test_cli_project_catalog.py`: CLI workflow and failure tests.
- Modify `README.md`: document the project catalog workflow.
- Modify `docs/ARCHITECTURE.md`: document `project_config.py` and catalog-backed query flow.
- Modify `docs/ROADMAP.md`: mark v0.3 as implemented after the batch is complete.

## Task 1: Dependency And Error Type

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/csvql/exceptions.py`

- [ ] **Step 1: Add PyYAML through uv**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv add PyYAML
```

Expected:

- `pyproject.toml` includes a runtime dependency similar to `"PyYAML>=6.0.0"`.
- `uv.lock` changes.
- No source files change from this command.

- [ ] **Step 2: Add the project config error type**

In `src/csvql/exceptions.py`, append this class after `CSVInspectionError`:

```python
class ProjectConfigError(CSVQLError):
    """Raised when project catalog discovery, parsing, or validation fails."""

    exit_code = 8
```

- [ ] **Step 3: Verify dependency import and current tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run python -c "import yaml; print(yaml.__name__)"
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_query.py tests/test_table_mapping.py -q
```

Expected:

- Python command prints `yaml`.
- Focused tests pass.

- [ ] **Step 4: Commit Task 1**

```bash
git add pyproject.toml uv.lock src/csvql/exceptions.py
git commit -m "feat: add project catalog dependency"
```

## Task 2: Project Config Discovery And Validation

**Files:**
- Create: `src/csvql/project_config.py`
- Create: `tests/test_project_config.py`
- Modify: `pyproject.toml` only if mypy needs a `yaml` override

- [ ] **Step 1: Write failing project config tests**

Create `tests/test_project_config.py` with:

```python
from pathlib import Path

import pytest

from csvql.exceptions import ProjectConfigError
from csvql.project_config import (
    CONFIG_FILENAME,
    SUPPORTED_VERSION,
    ProjectConfig,
    ProjectTable,
    discover_project,
    initialize_project,
    load_project,
    project_tables_to_sources,
)


def test_initialize_project_creates_empty_config(tmp_path: Path) -> None:
    context = initialize_project(project_dir=tmp_path)

    assert context.project_root == tmp_path
    assert context.config_path == tmp_path / CONFIG_FILENAME
    assert context.config == ProjectConfig(version=SUPPORTED_VERSION, tables=())
    assert context.config_path.read_text(encoding="utf-8") == "version: 1\ntables: {}\n"


def test_initialize_project_refuses_existing_config(tmp_path: Path) -> None:
    initialize_project(project_dir=tmp_path)

    with pytest.raises(ProjectConfigError) as exc_info:
        initialize_project(project_dir=tmp_path)

    assert str(exc_info.value) == f"{CONFIG_FILENAME} already exists."
    assert exc_info.value.suggestion == "Use --force to overwrite the existing project catalog."


def test_initialize_project_force_overwrites_existing_config(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables:\n  old:\n    path: old.csv\n", encoding="utf-8")

    context = initialize_project(project_dir=tmp_path, force=True)

    assert context.config == ProjectConfig(version=SUPPORTED_VERSION, tables=())
    assert config_path.read_text(encoding="utf-8") == "version: 1\ntables: {}\n"


def test_discover_project_walks_upward(tmp_path: Path) -> None:
    initialize_project(project_dir=tmp_path)
    nested = tmp_path / "queries" / "monthly"
    nested.mkdir(parents=True)

    context = discover_project(start_dir=nested)

    assert context.project_root == tmp_path
    assert context.config_path == tmp_path / CONFIG_FILENAME


def test_discover_project_reports_missing_catalog(tmp_path: Path) -> None:
    with pytest.raises(ProjectConfigError) as exc_info:
        discover_project(start_dir=tmp_path)

    assert str(exc_info.value) == f"No {CONFIG_FILENAME} project catalog found."
    assert exc_info.value.suggestion == (
        "Run csvql init and csvql add, or pass --table name=path for ad hoc queries."
    )


def test_load_project_rejects_invalid_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: [", encoding="utf-8")

    with pytest.raises(ProjectConfigError) as exc_info:
        load_project(config_path)

    assert str(exc_info.value) == f"Failed to parse {CONFIG_FILENAME}."
    assert exc_info.value.suggestion == "Fix the YAML syntax in the project catalog."


def test_load_project_rejects_unsupported_version(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 99\ntables: {}\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError) as exc_info:
        load_project(config_path)

    assert str(exc_info.value) == "Unsupported project config version: 99."
    assert exc_info.value.suggestion == "Use version: 1."


def test_load_project_rejects_non_mapping_tables(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables: []\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError) as exc_info:
        load_project(config_path)

    assert str(exc_info.value) == "Project config field 'tables' must be a mapping."


def test_load_project_rejects_invalid_table_alias(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables:\n  123orders:\n    path: orders.csv\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError) as exc_info:
        load_project(config_path)

    assert "Invalid table alias" in str(exc_info.value)


def test_load_project_rejects_table_without_path(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables:\n  orders: {}\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError) as exc_info:
        load_project(config_path)

    assert str(exc_info.value) == "Project table 'orders' must define a string path."


def test_project_tables_to_sources_resolves_paths_relative_to_root(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv_path = data_dir / "orders.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables:\n  orders:\n    path: data/orders.csv\n", encoding="utf-8")
    context = load_project(config_path)

    sources = project_tables_to_sources(context)

    assert sources == (ProjectTable(name="orders", path="data/orders.csv").to_table_source(tmp_path),)
    assert sources[0].name == "orders"
    assert sources[0].path == csv_path
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_project_config.py -q
```

Expected: FAIL because `csvql.project_config` does not exist.

- [ ] **Step 3: Create `project_config.py`**

Create `src/csvql/project_config.py` with:

```python
"""Project catalog discovery, validation, and persistence."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from csvql.exceptions import FileMissingError, ProjectConfigError, TableMappingError
from csvql.models import TableSource
from csvql.source import resolve_csv_path
from csvql.table_mapping import validate_table_alias

CONFIG_FILENAME = ".csvql.yml"
SUPPORTED_VERSION = 1


@dataclass(frozen=True, slots=True)
class ProjectTable:
    """A table entry stored in a CSVQL project catalog."""

    name: str
    path: str

    def as_config_entry(self) -> dict[str, str]:
        """Return the YAML mapping for this table."""

        return {"path": self.path}

    def resolved_path(self, project_root: Path) -> Path:
        """Resolve this table path relative to the project root."""

        return resolve_catalog_path(self.path, project_root=project_root)

    def to_table_source(self, project_root: Path) -> TableSource:
        """Convert this project table into a DuckDB table source."""

        return TableSource(name=self.name, path=self.resolved_path(project_root))


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """Validated CSVQL project catalog contents."""

    version: int
    tables: tuple[ProjectTable, ...]

    @classmethod
    def empty(cls) -> "ProjectConfig":
        """Return an empty supported project config."""

        return cls(version=SUPPORTED_VERSION, tables=())

    def table_map(self) -> dict[str, ProjectTable]:
        """Return tables keyed by table name."""

        return {table.name: table for table in self.tables}

    def as_dict(self) -> dict[str, object]:
        """Return a deterministic YAML-friendly config mapping."""

        return {
            "version": self.version,
            "tables": {
                table.name: table.as_config_entry()
                for table in sorted(self.tables, key=lambda item: item.name)
            },
        }


@dataclass(frozen=True, slots=True)
class ProjectContext:
    """A discovered project root, config path, and validated config."""

    project_root: Path
    config_path: Path
    config: ProjectConfig


def initialize_project(*, project_dir: Path | None = None, force: bool = False) -> ProjectContext:
    """Create an empty project catalog in a directory."""

    root = (project_dir or Path.cwd()).resolve()
    config_path = root / CONFIG_FILENAME
    if config_path.exists() and not force:
        raise ProjectConfigError(
            f"{CONFIG_FILENAME} already exists.",
            suggestion="Use --force to overwrite the existing project catalog.",
        )

    config = ProjectConfig.empty()
    save_project(config_path, config)
    return ProjectContext(project_root=root, config_path=config_path, config=config)


def discover_project(*, start_dir: Path | None = None) -> ProjectContext:
    """Find and load the nearest project catalog walking upward from a directory."""

    start = (start_dir or Path.cwd()).resolve()
    search_dirs = (start, *start.parents)
    for directory in search_dirs:
        config_path = directory / CONFIG_FILENAME
        if config_path.is_file():
            return load_project(config_path)

    raise ProjectConfigError(
        f"No {CONFIG_FILENAME} project catalog found.",
        suggestion="Run csvql init and csvql add, or pass --table name=path for ad hoc queries.",
    )


def load_project(config_path: Path) -> ProjectContext:
    """Load and validate a project catalog from disk."""

    root = config_path.parent.resolve()
    raw_config = _load_yaml_mapping(config_path)
    config = _parse_project_config(raw_config)
    return ProjectContext(project_root=root, config_path=config_path, config=config)


def save_project(config_path: Path, config: ProjectConfig) -> None:
    """Write a project catalog with deterministic key ordering."""

    payload = config.as_dict()
    text = yaml.safe_dump(payload, sort_keys=False)
    config_path.write_text(text, encoding="utf-8")


def resolve_catalog_path(path_value: str, *, project_root: Path) -> Path:
    """Resolve and validate a path from a project catalog."""

    return resolve_csv_path(path_value, base_dir=project_root)


def project_tables_to_sources(context: ProjectContext) -> tuple[TableSource, ...]:
    """Convert all project catalog tables into engine table sources."""

    sources: list[TableSource] = []
    for table in context.config.tables:
        try:
            sources.append(table.to_table_source(context.project_root))
        except FileMissingError as exc:
            raise ProjectConfigError(
                f"CSV file for project table '{table.name}' not found: {table.path}",
                suggestion="Update the table path in .csvql.yml or run csvql add with --replace.",
            ) from exc
    return tuple(sources)


def _load_yaml_mapping(config_path: Path) -> dict[str, object]:
    try:
        raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProjectConfigError(
            f"Failed to parse {CONFIG_FILENAME}.",
            suggestion="Fix the YAML syntax in the project catalog.",
        ) from exc

    if not isinstance(raw_config, dict):
        raise ProjectConfigError(
            f"{CONFIG_FILENAME} must contain a YAML mapping.",
            suggestion="Use version: 1 and tables: {} at the top level.",
        )
    return cast(dict[str, object], raw_config)


def _parse_project_config(raw_config: dict[str, object]) -> ProjectConfig:
    raw_version = raw_config.get("version")
    if raw_version != SUPPORTED_VERSION:
        raise ProjectConfigError(
            f"Unsupported project config version: {raw_version}.",
            suggestion="Use version: 1.",
        )

    raw_tables = raw_config.get("tables")
    if not isinstance(raw_tables, dict):
        raise ProjectConfigError("Project config field 'tables' must be a mapping.")

    tables: list[ProjectTable] = []
    for raw_name, raw_entry in raw_tables.items():
        name = _validate_project_table_name(raw_name)
        if not isinstance(raw_entry, dict) or not isinstance(raw_entry.get("path"), str):
            raise ProjectConfigError(f"Project table '{name}' must define a string path.")
        path_value = raw_entry["path"].strip()
        if not path_value:
            raise ProjectConfigError(f"Project table '{name}' must define a non-empty path.")
        tables.append(ProjectTable(name=name, path=path_value))

    return ProjectConfig(version=SUPPORTED_VERSION, tables=tuple(sorted(tables, key=lambda item: item.name)))


def _validate_project_table_name(raw_name: object) -> str:
    if not isinstance(raw_name, str):
        raise ProjectConfigError("Project table names must be strings.")
    try:
        return validate_table_alias(raw_name)
    except TableMappingError as exc:
        raise ProjectConfigError(str(exc), suggestion=exc.suggestion) from exc
```

- [ ] **Step 4: Run tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_project_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Run mypy**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: PASS.

If mypy reports missing `yaml` stubs, add `yaml` to the existing override in `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = ["duckdb", "yaml"]
ignore_missing_imports = true
```

Then rerun:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

- [ ] **Step 6: Commit Task 2**

```bash
git add src/csvql/project_config.py tests/test_project_config.py pyproject.toml
git commit -m "feat: load project catalog config"
```

## Task 3: Project Catalog Mutation And Listing Models

**Files:**
- Modify: `src/csvql/project_config.py`
- Modify: `tests/test_project_config.py`

- [ ] **Step 1: Add failing mutation and listing tests**

Append to `tests/test_project_config.py`:

```python
from csvql.project_config import add_project_table, build_project_tables_result


def test_add_project_table_stores_project_relative_path(tmp_path: Path) -> None:
    initialize_project(project_dir=tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv_path = data_dir / "orders.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")

    context = add_project_table("orders", str(csv_path), start_dir=tmp_path)

    assert context.config.tables == (ProjectTable(name="orders", path="data/orders.csv"),)
    assert "orders:\n    path: data/orders.csv\n" in context.config_path.read_text(encoding="utf-8")


def test_add_project_table_resolves_relative_input_from_current_directory(tmp_path: Path) -> None:
    initialize_project(project_dir=tmp_path)
    nested = tmp_path / "queries"
    nested.mkdir()
    data_dir = nested / "data"
    data_dir.mkdir()
    csv_path = data_dir / "orders.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")

    context = add_project_table("orders", "data/orders.csv", start_dir=nested)

    assert context.config.tables == (ProjectTable(name="orders", path="queries/data/orders.csv"),)


def test_add_project_table_stores_absolute_path_outside_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    csv_path = outside_dir / "orders.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    initialize_project(project_dir=project_dir)

    context = add_project_table("orders", str(csv_path), start_dir=project_dir)

    assert context.config.tables == (ProjectTable(name="orders", path=str(csv_path)),)


def test_add_project_table_rejects_duplicate_without_replace(tmp_path: Path) -> None:
    initialize_project(project_dir=tmp_path)
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    add_project_table("orders", str(csv_path), start_dir=tmp_path)

    with pytest.raises(ProjectConfigError) as exc_info:
        add_project_table("orders", str(csv_path), start_dir=tmp_path)

    assert str(exc_info.value) == "Project table 'orders' already exists."
    assert exc_info.value.suggestion == "Use --replace to update the existing table entry."


def test_add_project_table_replace_updates_path(tmp_path: Path) -> None:
    initialize_project(project_dir=tmp_path)
    first = tmp_path / "orders.csv"
    first.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    second = tmp_path / "scratch_orders.csv"
    second.write_text("order_id,total_amount\nORD-2,99.00\n", encoding="utf-8")
    add_project_table("orders", str(first), start_dir=tmp_path)

    context = add_project_table("orders", str(second), start_dir=tmp_path, replace=True)

    assert context.config.tables == (ProjectTable(name="orders", path="scratch_orders.csv"),)


def test_build_project_tables_result_returns_resolved_paths(tmp_path: Path) -> None:
    initialize_project(project_dir=tmp_path)
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    context = add_project_table("orders", str(csv_path), start_dir=tmp_path)

    result = build_project_tables_result(context)

    assert result.as_dict() == {
        "project_root": str(tmp_path),
        "config_path": str(tmp_path / CONFIG_FILENAME),
        "tables": [
            {
                "name": "orders",
                "path": "orders.csv",
                "resolved_path": str(csv_path),
            }
        ],
    }
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_project_config.py -q
```

Expected: FAIL because `add_project_table` and `build_project_tables_result` do not exist.

- [ ] **Step 3: Add listing value objects and mutation functions**

Append to `src/csvql/project_config.py` after `ProjectContext`:

```python
@dataclass(frozen=True, slots=True)
class ProjectTableListing:
    """Resolved table metadata for `csvql tables` output."""

    name: str
    path: str
    resolved_path: Path

    def as_dict(self) -> dict[str, str]:
        """Return JSON-friendly table listing metadata."""

        return {
            "name": self.name,
            "path": self.path,
            "resolved_path": str(self.resolved_path),
        }


@dataclass(frozen=True, slots=True)
class ProjectTablesResult:
    """Structured result for project table listing output."""

    project_root: Path
    config_path: Path
    tables: tuple[ProjectTableListing, ...]

    def as_dict(self) -> dict[str, object]:
        """Return JSON-friendly project table listing output."""

        return {
            "project_root": str(self.project_root),
            "config_path": str(self.config_path),
            "tables": [table.as_dict() for table in self.tables],
        }
```

Append these functions after `project_tables_to_sources`:

```python
def add_project_table(
    name: str,
    path_value: str,
    *,
    start_dir: Path | None = None,
    replace: bool = False,
) -> ProjectContext:
    """Add or replace a table entry in the nearest project catalog."""

    context = discover_project(start_dir=start_dir)
    table_name = _validate_project_table_name(name)
    stored_path = _stored_catalog_path(path_value, project_root=context.project_root, base_dir=start_dir)
    table_map = context.config.table_map()
    if table_name in table_map and not replace:
        raise ProjectConfigError(
            f"Project table '{table_name}' already exists.",
            suggestion="Use --replace to update the existing table entry.",
        )

    table_map[table_name] = ProjectTable(name=table_name, path=stored_path)
    updated_config = ProjectConfig(
        version=SUPPORTED_VERSION,
        tables=tuple(sorted(table_map.values(), key=lambda item: item.name)),
    )
    save_project(context.config_path, updated_config)
    return ProjectContext(
        project_root=context.project_root,
        config_path=context.config_path,
        config=updated_config,
    )


def build_project_tables_result(context: ProjectContext) -> ProjectTablesResult:
    """Build output metadata for project table listing."""

    listings = tuple(
        ProjectTableListing(
            name=table.name,
            path=table.path,
            resolved_path=table.resolved_path(context.project_root),
        )
        for table in context.config.tables
    )
    return ProjectTablesResult(
        project_root=context.project_root,
        config_path=context.config_path,
        tables=listings,
    )
```

Append this helper near the private helpers:

```python
def _stored_catalog_path(path_value: str, *, project_root: Path, base_dir: Path | None) -> str:
    resolved_path = resolve_csv_path(path_value, base_dir=base_dir)
    resolved_root = project_root.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        return str(resolved_path)
```

- [ ] **Step 4: Run project config tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_project_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Run type check**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/csvql/project_config.py tests/test_project_config.py
git commit -m "feat: manage project catalog tables"
```

## Task 4: Project Tables Output Renderers

**Files:**
- Modify: `src/csvql/output.py`
- Modify: `tests/test_output.py`

- [ ] **Step 1: Add failing output tests**

Append to `tests/test_output.py`:

```python
from pathlib import Path

from csvql.project_config import ProjectTableListing, ProjectTablesResult
from csvql.output import format_project_tables_json, format_project_tables_table


def _project_tables_result() -> ProjectTablesResult:
    return ProjectTablesResult(
        project_root=Path("/project"),
        config_path=Path("/project/.csvql.yml"),
        tables=(
            ProjectTableListing(
                name="orders",
                path="data/orders.csv",
                resolved_path=Path("/project/data/orders.csv"),
            ),
        ),
    )


def test_format_project_tables_json_is_deterministic() -> None:
    payload = json.loads(format_project_tables_json(_project_tables_result()))

    assert payload == {
        "config_path": "/project/.csvql.yml",
        "project_root": "/project",
        "tables": [
            {
                "name": "orders",
                "path": "data/orders.csv",
                "resolved_path": "/project/data/orders.csv",
            }
        ],
    }


def test_format_project_tables_table_contains_core_fields() -> None:
    output = format_project_tables_table(_project_tables_result())

    assert "orders" in output
    assert "data/orders.csv" in output
    assert "/project/data/orders.csv" in output
```

- [ ] **Step 2: Run output tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_output.py -q
```

Expected: FAIL because the project table renderer functions do not exist.

- [ ] **Step 3: Add renderer imports**

In `src/csvql/output.py`, add:

```python
from csvql.project_config import ProjectTablesResult
```

- [ ] **Step 4: Add renderer functions**

Append to `src/csvql/output.py` before `_format_cell`:

```python
def format_project_tables_json(result: ProjectTablesResult) -> str:
    """Format project table listings as deterministic JSON."""

    return json.dumps(result.as_dict(), default=str, indent=2, sort_keys=True)


def format_project_tables_table(result: ProjectTablesResult) -> str:
    """Format project table listings as Rich table text."""

    console = Console(color_system=None, force_terminal=False, record=True, width=120)
    console.print(f"Project: {result.project_root}")
    table = Table(show_header=True)
    table.add_column("name")
    table.add_column("path")
    table.add_column("resolved_path")
    for table_info in result.tables:
        table.add_row(table_info.name, table_info.path, str(table_info.resolved_path))
    console.print(table)
    return console.export_text(clear=True)
```

- [ ] **Step 5: Run output tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_output.py -q
```

Expected: PASS.

- [ ] **Step 6: Run type check**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/csvql/output.py tests/test_output.py
git commit -m "feat: render project catalog tables"
```

## Task 5: Catalog CLI Commands

**Files:**
- Modify: `src/csvql/cli.py`
- Create: `tests/test_cli_project_catalog.py`

- [ ] **Step 1: Write failing CLI command tests**

Create `tests/test_cli_project_catalog.py` with:

```python
import json
from pathlib import Path

from typer.testing import CliRunner

from csvql.cli import app

runner = CliRunner()


def test_init_creates_project_catalog(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        assert Path(".csvql.yml").read_text(encoding="utf-8") == "version: 1\ntables: {}\n"
        assert "Created" in result.output


def test_init_refuses_existing_project_catalog(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 8
        assert ".csvql.yml already exists" in result.output
        assert "--force" in result.output


def test_init_force_rewrites_project_catalog(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path(".csvql.yml").write_text(
            "version: 1\ntables:\n  old:\n    path: old.csv\n",
            encoding="utf-8",
        )

        result = runner.invoke(app, ["init", "--force"])

        assert result.exit_code == 0, result.output
        assert Path(".csvql.yml").read_text(encoding="utf-8") == "version: 1\ntables: {}\n"


def test_add_registers_table(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("orders.csv").write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
        runner.invoke(app, ["init"])

        result = runner.invoke(app, ["add", "orders", "orders.csv"])

        assert result.exit_code == 0, result.output
        assert "Added table orders" in result.output
        assert "orders:\n    path: orders.csv\n" in Path(".csvql.yml").read_text(encoding="utf-8")


def test_add_rejects_duplicate_without_replace(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("orders.csv").write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
        runner.invoke(app, ["init"])
        runner.invoke(app, ["add", "orders", "orders.csv"])

        result = runner.invoke(app, ["add", "orders", "orders.csv"])

        assert result.exit_code == 8
        assert "already exists" in result.output
        assert "--replace" in result.output


def test_add_replace_updates_table(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("orders.csv").write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
        Path("scratch_orders.csv").write_text(
            "order_id,total_amount\nORD-2,99.00\n",
            encoding="utf-8",
        )
        runner.invoke(app, ["init"])
        runner.invoke(app, ["add", "orders", "orders.csv"])

        result = runner.invoke(app, ["add", "orders", "scratch_orders.csv", "--replace"])

        assert result.exit_code == 0, result.output
        assert "scratch_orders.csv" in Path(".csvql.yml").read_text(encoding="utf-8")


def test_tables_outputs_json(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("orders.csv").write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
        runner.invoke(app, ["init"])
        runner.invoke(app, ["add", "orders", "orders.csv"])

        result = runner.invoke(app, ["tables", "--output", "json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["tables"] == [
            {
                "name": "orders",
                "path": "orders.csv",
                "resolved_path": str(Path.cwd() / "orders.csv"),
            }
        ]


def test_tables_outputs_table_by_default(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("orders.csv").write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
        runner.invoke(app, ["init"])
        runner.invoke(app, ["add", "orders", "orders.csv"])

        result = runner.invoke(app, ["tables"])

        assert result.exit_code == 0, result.output
        assert "orders" in result.output
        assert "orders.csv" in result.output
```

- [ ] **Step 2: Run CLI tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_project_catalog.py -q
```

Expected: FAIL because `init`, `add`, and `tables` commands do not exist.

- [ ] **Step 3: Add CLI imports**

In `src/csvql/cli.py`, add project config imports:

```python
from csvql.project_config import (
    add_project_table,
    build_project_tables_result,
    discover_project,
    initialize_project,
)
```

Extend the output imports:

```python
    format_project_tables_json,
    format_project_tables_table,
```

- [ ] **Step 4: Add `init`, `add`, and `tables` commands**

Add these commands above `inspect` in `src/csvql/cli.py`:

```python
@app.command()
def init(
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite an existing .csvql.yml project catalog.",
        ),
    ] = False,
) -> None:
    """Create an empty CSVQL project catalog."""

    try:
        context = initialize_project(force=force)
        typer.echo(f"Created {context.config_path}")
    except CSVQLError as exc:
        _exit_with_error(exc)


@app.command()
def add(
    name: Annotated[
        str,
        typer.Argument(help="Table alias to register."),
    ],
    csv_path: Annotated[
        str,
        typer.Argument(help="CSV file path to register."),
    ],
    replace: Annotated[
        bool,
        typer.Option(
            "--replace",
            help="Replace an existing project table entry.",
        ),
    ] = False,
) -> None:
    """Register a CSV file in the project catalog."""

    try:
        add_project_table(name, csv_path, replace=replace)
        typer.echo(f"Added table {name}")
    except CSVQLError as exc:
        _exit_with_error(exc)


@app.command()
def tables(
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="Project table listing output format.",
        ),
    ] = OutputFormat.table,
) -> None:
    """List registered project catalog tables."""

    try:
        context = discover_project()
        result = build_project_tables_result(context)
        if output is OutputFormat.json:
            typer.echo(format_project_tables_json(result))
        else:
            typer.echo(format_project_tables_table(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)
```

- [ ] **Step 5: Run CLI command tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_project_catalog.py -q
```

Expected: PASS.

- [ ] **Step 6: Run existing CLI tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_query.py tests/test_cli_inspect_sample.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add src/csvql/cli.py tests/test_cli_project_catalog.py
git commit -m "feat: add project catalog CLI commands"
```

## Task 6: Catalog-Backed Query

**Files:**
- Modify: `src/csvql/cli.py`
- Modify: `tests/test_cli_project_catalog.py`
- Modify: `tests/test_cli_query.py`

- [ ] **Step 1: Add failing catalog-backed query tests**

Append to `tests/test_cli_project_catalog.py`:

```python
def test_query_uses_project_catalog_table(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("orders.csv").write_text(
            "order_id,total_amount\nORD-1,12.34\nORD-2,99.00\n",
            encoding="utf-8",
        )
        runner.invoke(app, ["init"])
        runner.invoke(app, ["add", "orders", "orders.csv"])

        result = runner.invoke(
            app,
            [
                "query",
                "--output",
                "json",
                "SELECT COUNT(*) AS order_count FROM orders",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["rows"] == [{"order_count": 2}]


def test_query_explicit_table_overrides_catalog_alias(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("orders.csv").write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
        Path("scratch_orders.csv").write_text(
            "order_id,total_amount\nORD-2,99.00\nORD-3,100.00\n",
            encoding="utf-8",
        )
        runner.invoke(app, ["init"])
        runner.invoke(app, ["add", "orders", "orders.csv"])

        result = runner.invoke(
            app,
            [
                "query",
                "--table",
                "orders=scratch_orders.csv",
                "--output",
                "json",
                "SELECT COUNT(*) AS order_count FROM orders",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["rows"] == [{"order_count": 2}]


def test_query_uses_project_catalog_from_subdirectory(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("data").mkdir()
        Path("data/orders.csv").write_text(
            "order_id,total_amount\nORD-1,12.34\n",
            encoding="utf-8",
        )
        Path("queries").mkdir()
        runner.invoke(app, ["init"])
        runner.invoke(app, ["add", "orders", "data/orders.csv"])

        original_cwd = Path.cwd()
        try:
            import os

            os.chdir("queries")
            result = runner.invoke(
                app,
                [
                    "query",
                    "--output",
                    "json",
                    "SELECT COUNT(*) AS order_count FROM orders",
                ],
            )
        finally:
            os.chdir(original_cwd)

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["rows"] == [{"order_count": 1}]


def test_query_without_tables_or_catalog_reports_project_config_error(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["query", "SELECT 1"])

        assert result.exit_code == 8
        assert "No .csvql.yml project catalog found" in result.output
        assert "--table name=path" in result.output
```

Modify `tests/test_cli_query.py::test_query_requires_table_mapping_for_inline_sql` to preserve explicit no-catalog behavior by passing a missing catalog directory and explicit table mapping is already covered. Replace the old assertion test with:

```python
def test_query_with_explicit_table_mapping_does_not_require_project_catalog(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id,total_amount\nORD-001,120.50\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            f"orders={orders}",
            "--output",
            "json",
            "SELECT COUNT(*) AS order_count FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [{"order_count": 1}]
```

- [ ] **Step 2: Run query tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_project_catalog.py tests/test_cli_query.py -q
```

Expected: FAIL because inline query without explicit table mappings still errors before reading the catalog.

- [ ] **Step 3: Add catalog source merge support**

In `src/csvql/cli.py`, add this import:

```python
from csvql.exceptions import CSVQLError, ProjectConfigError, TableMappingError
from csvql.project_config import project_tables_to_sources
```

Replace `_build_query_request` with:

```python
def _build_query_request(
    sql_or_csv: str,
    sql: str | None,
    table_mappings: list[str],
) -> tuple[str, list[TableSource]]:
    if sql is None:
        explicit_sources = [parse_table_mapping(mapping) for mapping in table_mappings]
        catalog_sources = _catalog_table_sources(required=not explicit_sources)
        return sql_or_csv, _merge_table_sources(catalog_sources, explicit_sources)

    if table_mappings:
        raise TableMappingError(
            "Single-file shortcut mode cannot be combined with --table mappings.",
            suggestion='Use either csvql query data/orders.csv "SELECT ..." or --table mappings.',
        )
    return sql, [source_from_single_csv(sql_or_csv)]
```

Add these helper functions below `_build_query_request`:

```python
def _catalog_table_sources(*, required: bool) -> list[TableSource]:
    try:
        context = discover_project()
    except ProjectConfigError:
        if required:
            raise
        return []
    return list(project_tables_to_sources(context))


def _merge_table_sources(
    catalog_sources: list[TableSource],
    explicit_sources: list[TableSource],
) -> list[TableSource]:
    sources_by_name = {source.name: source for source in catalog_sources}
    for source in explicit_sources:
        sources_by_name[source.name] = source
    return list(sources_by_name.values())
```

- [ ] **Step 4: Run catalog query tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_project_catalog.py tests/test_cli_query.py -q
```

Expected: PASS.

- [ ] **Step 5: Run all CLI tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_project_catalog.py tests/test_cli_query.py tests/test_cli_inspect_sample.py -q
```

Expected: PASS.

- [ ] **Step 6: Run type check**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: PASS.

- [ ] **Step 7: Commit Task 6**

```bash
git add src/csvql/cli.py tests/test_cli_project_catalog.py tests/test_cli_query.py
git commit -m "feat: query project catalog tables"
```

## Task 7: Documentation Updates

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Update README status and examples**

In `README.md`, under `Implemented now`, add:

```markdown
- `.csvql.yml` project catalog
- `csvql init`, `csvql add`, and `csvql tables`
- catalog-backed `csvql query "SELECT ..."`
```

Under `Planned later`, remove `.csvql.yml` project config so the list starts with:

```markdown
- `run` and `export`
```

Add this section after `Inspect And Sample Examples`:

````markdown
## Project Catalog Examples

Create a project catalog:

```bash
uv run csvql init
```

Register a CSV table:

```bash
uv run csvql add orders examples/sales/data/orders.csv
```

Query a registered table without repeating `--table`:

```bash
uv run csvql query "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status"
```

List registered tables:

```bash
uv run csvql tables
uv run csvql tables --output json
```

For one-off work, explicit `--table` mappings override catalog aliases for the current command.
````

- [ ] **Step 2: Update architecture docs**

In `docs/ARCHITECTURE.md`, add a module boundary after `source.py`:

```markdown
`project_config.py`
: Discover, load, validate, and save `.csvql.yml`; convert registered catalog tables into query table sources.
```

Under current design choices, add:

```markdown
- Project discovery walks upward from the current directory until `.csvql.yml` is found.
- Catalog paths resolve relative to the project root.
- Explicit `--table` mappings override catalog aliases for one command invocation.
```

- [ ] **Step 3: Update roadmap**

In `docs/ROADMAP.md`, mark v0.3 as implemented:

```markdown
## v0.3.0 - Project Catalog

Implemented:

- `.csvql.yml` project catalog
- `csvql init`
- `csvql add`
- `csvql tables`
- upward project root discovery
- relative path resolution from the project root
- catalog-backed `csvql query`
- explicit `--table` override behavior
```

- [ ] **Step 4: Run docs scans**

Run:

```bash
rg -n "safe mode is implemented|sandbox-safe|production-safe|large-file-proven|schema <table>|preview <table>" README.md docs
```

Expected: no matches.

- [ ] **Step 5: Commit Task 7**

```bash
git add README.md docs/ARCHITECTURE.md docs/ROADMAP.md
git commit -m "docs: document project catalog workflow"
```

## Task 8: Full Verification Gate

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run formatting check**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
```

Expected: PASS.

- [ ] **Step 2: Run lint**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
```

Expected: PASS.

- [ ] **Step 3: Run type check**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: PASS.

- [ ] **Step 4: Run tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest
```

Expected: PASS.

- [ ] **Step 5: Run diff hygiene checks**

Run:

```bash
git diff --check
rg -n "TB[D]|TO[D]O|placeholde[r]|FIXM[E]|XX[X]" src tests README.md docs
rg -n "[ \t]+$" src tests README.md docs
```

Expected:

- `git diff --check`: PASS with no output.
- red-flag scan: no matches.
- trailing whitespace scan: no matches.

- [ ] **Step 6: Run CLI smoke checks**

Run these from a temporary directory inside the repo or `/private/tmp`:

```bash
tmp_dir="/private/tmp/csvql-catalog-smoke-$(date +%s)"
mkdir "$tmp_dir"
cp examples/sales/data/orders.csv "$tmp_dir/orders.csv"
cd "$tmp_dir"
UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/.codex/worktrees/ea7e/csvql csvql init
UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/.codex/worktrees/ea7e/csvql csvql add orders orders.csv
UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/.codex/worktrees/ea7e/csvql csvql tables --output json
UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/.codex/worktrees/ea7e/csvql csvql query --output json "SELECT COUNT(*) AS order_count FROM orders"
```

Expected:

- `csvql init` creates `.csvql.yml`.
- `csvql add` registers `orders`.
- `csvql tables --output json` includes `orders`.
- catalog-backed query returns `order_count` equal to `4`.

- [ ] **Step 7: Commit verification polish only if files changed**

If the verification steps require doc, source, test, or formatting changes, commit them:

```bash
git add README.md docs src tests pyproject.toml uv.lock
git commit -m "chore: polish project catalog verification"
```

If no files changed, do not create an empty commit.

## Self-Review Against Spec

Spec coverage:

- `.csvql.yml`: Tasks 2, 3, 5, 7.
- `PyYAML`: Task 1.
- `safe_load` / `safe_dump`: Task 2.
- `init [--force]`: Tasks 2 and 5.
- `add <name> <path> [--replace]`: Tasks 3 and 5.
- `tables --output table|json`: Tasks 3, 4, and 5.
- catalog-backed `query`: Task 6.
- explicit `--table` override behavior: Task 6.
- upward discovery: Tasks 2 and 6.
- project-root path resolution: Tasks 2, 3, and 6.
- typed config errors: Tasks 1, 2, 3, 5, and 6.
- docs without unsafe claims: Task 7.
- full gate: Task 8.

No planned task implements registered-table `inspect` / `sample`, `run`, `export`, profiling, data quality checks, reader options, type overrides, safe mode, cache, or Python API.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-26-project-catalog.md`. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.

2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
