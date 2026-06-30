# CSVQL Doctor Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `csvql doctor` as a focused project-health command that discovers a local CSVQL project, reports warning/failure/pass status in table or JSON form, proves configured tables are readable through DuckDB, and statically audits configured checks against discovered schema.

**Architecture:** Keep `cli.py` thin and put doctor-specific orchestration and result objects in a dedicated `src/csvql/doctor.py` module. Reuse existing project discovery, config loading, path resolution, DuckDB CSV registration, and check-column resolution semantics, while adding doctor-specific output formatters, CLI tests, workflow tests, and concise docs.

**Tech Stack:** Python 3.12, Typer, DuckDB, Rich, pytest, `uv`, existing CSVQL config/loading helpers, existing CLI/test patterns.

---

## Preconditions

- Start from the approved spec at `docs/superpowers/specs/2026-06-29-csvql-doctor-design.md`.
- Start from a clean worktree on branch `codex/v07-benchmark-release-hardening-ecb3`.
- Confirm the current baseline before editing:

```bash
git status --short --branch
git rev-parse --short HEAD
```

Expected:

- clean working tree
- `HEAD` at `0efcf0d` or a descendant that still contains the approved doctor design

- Sync the environment before touching code:

```bash
uv sync --all-extras --frozen
```

- Confirm the repo gate is green before implementation:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

Expected: PASS for all commands.

## Scope And Constraints

- Add exactly one new public command:
  - `csvql doctor`
  - `csvql doctor --output table`
  - `csvql doctor --output json`
- Treat missing `.csvql.yml` as a doctor warning, not a hard CLI error.
- Use tri-state doctor status:
  - `passed`
  - `warning`
  - `failed`
- Exit behavior:
  - `passed` -> `0`
  - `warning` -> `0`
  - `failed` -> `12`
- Reuse existing config and column-resolution semantics.
- Do not add:
  - `--config`
  - positional args
  - strict/deep/repair mode
  - saved SQL execution inside doctor
  - configured check execution inside doctor
  - project mutation or auto-fix behavior

## Command, JSON, Exit-Code, Docs, And Test Impact

Command impact:

- adds `csvql doctor`
- does not change existing command semantics

JSON impact:

- adds one new automation-oriented JSON contract for doctor
- does not change current JSON shapes for `query`, `run`, `inspect`, `sample`, `profile`, `check`, `tables`, or `export`

Exit-code impact:

- adds one dedicated non-zero exit code for doctor failures: `12`
- preserves existing `check` failure exit code `11`

Docs impact:

- update `README.md` with one command bullet and one short usage section
- update `docs/ARCHITECTURE.md` with the new `doctor.py` boundary and current design choices

Test impact:

- add dedicated unit tests for doctor result objects/workflow
- add dedicated CLI tests for doctor command behavior
- extend output tests for doctor JSON/table renderers

## File Structure

- Create: `src/csvql/doctor.py`
- Modify: `src/csvql/cli.py`
- Modify: `src/csvql/output.py`
- Modify: `src/csvql/exceptions.py`
- Modify: `src/csvql/checks.py`
- Create: `tests/test_doctor.py`
- Create: `tests/test_cli_doctor.py`
- Modify: `tests/test_output.py`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`

`src/csvql/doctor.py`
: owns doctor result types, project-health workflow, table-readiness probes, and static check-schema audit

`src/csvql/cli.py`
: adds the `doctor` Typer command and doctor-specific exit behavior

`src/csvql/output.py`
: adds doctor JSON and table renderers

`src/csvql/exceptions.py`
: reserves exit code `12` for doctor-detected project-health failures

`src/csvql/checks.py`
: exposes a tiny public helper so doctor reuses the same configured-column resolution semantics as `csvql check`

`tests/test_doctor.py`
: unit/workflow tests for doctor result counting, JSON shape, and derivative-probe suppression

`tests/test_cli_doctor.py`
: end-to-end CLI behavior tests for warning/pass/fail paths

`tests/test_output.py`
: formatter-level doctor JSON/table tests

`README.md`
: user-facing command documentation

`docs/ARCHITECTURE.md`
: repo-level architecture boundary update

## Task 1: Add Doctor Result Objects And Output Formatters

**Files:**
- Create: `src/csvql/doctor.py`
- Create: `tests/test_doctor.py`
- Modify: `src/csvql/output.py`
- Modify: `tests/test_output.py`

- [ ] **Step 1: Write the failing doctor result-model test**

Create `tests/test_doctor.py` with this first unit test:

```python
import json

from csvql.doctor import DoctorProbeResult, DoctorRunResult


def test_doctor_run_result_derives_warning_counts_and_json_shape() -> None:
    result = DoctorRunResult(
        project_root=None,
        config_path=None,
        probes=(
            DoctorProbeResult(
                name="project_discovery",
                scope="project",
                status="warning",
                message="No .csvql.yml project catalog found.",
            ),
        ),
    )

    assert result.status == "warning"
    assert result.probe_count == 1
    assert result.passed_count == 0
    assert result.warning_count == 1
    assert result.failed_count == 0
    assert result.as_dict() == {
        "status": "warning",
        "probe_count": 1,
        "passed_count": 0,
        "warning_count": 1,
        "failed_count": 0,
        "project": {
            "config_path": None,
            "project_root": None,
        },
        "probes": [
            {
                "name": "project_discovery",
                "scope": "project",
                "status": "warning",
                "message": "No .csvql.yml project catalog found.",
            }
        ],
    }
```

- [ ] **Step 2: Run the new doctor result-model test to verify it fails**

Run:

```bash
uv run pytest tests/test_doctor.py::test_doctor_run_result_derives_warning_counts_and_json_shape -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'csvql.doctor'`.

- [ ] **Step 3: Add failing doctor formatter tests**

In `tests/test_output.py`, add imports and these new tests:

```python
from csvql.doctor import DoctorProbeResult, DoctorRunResult
from csvql.output import (
    format_check_result_json,
    format_check_result_table,
    format_doctor_result_json,
    format_doctor_result_table,
    format_inspect_result_json,
    format_inspect_result_table,
    format_json_result,
    format_profile_result_json,
    format_profile_result_table,
    format_project_tables_json,
    format_project_tables_table,
    format_sample_result_json,
    format_sample_result_table,
)


def _doctor_warning_result() -> DoctorRunResult:
    return DoctorRunResult(
        project_root=None,
        config_path=None,
        probes=(
            DoctorProbeResult(
                name="project_discovery",
                scope="project",
                status="warning",
                message="No .csvql.yml project catalog found.",
            ),
        ),
    )


def test_format_doctor_result_json_is_deterministic() -> None:
    payload = json.loads(format_doctor_result_json(_doctor_warning_result()))

    assert payload == {
        "status": "warning",
        "probe_count": 1,
        "passed_count": 0,
        "warning_count": 1,
        "failed_count": 0,
        "project": {
            "config_path": None,
            "project_root": None,
        },
        "probes": [
            {
                "name": "project_discovery",
                "scope": "project",
                "status": "warning",
                "message": "No .csvql.yml project catalog found.",
            }
        ],
    }


def test_format_doctor_result_table_contains_summary_and_probe_row() -> None:
    output = format_doctor_result_table(_doctor_warning_result())

    assert "Status: warning" in output
    assert "Probes: 1 | Passed: 0 | Warnings: 1 | Failed: 0" in output
    assert "project_discovery" in output
    assert "No .csvql.yml project catalog found." in output
```

- [ ] **Step 4: Run the new formatter tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_output.py::test_format_doctor_result_json_is_deterministic \
  tests/test_output.py::test_format_doctor_result_table_contains_summary_and_probe_row \
  -q
```

Expected: FAIL with missing `csvql.doctor` import and missing formatter functions.

- [ ] **Step 5: Implement the doctor result objects in `src/csvql/doctor.py`**

Create `src/csvql/doctor.py` with this initial content:

```python
"""Project-health result objects and workflow for `csvql doctor`."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DoctorScope = Literal["project", "table", "check"]
DoctorStatus = Literal["passed", "warning", "failed"]


@dataclass(frozen=True, slots=True)
class DoctorProbeResult:
    """One project-health finding emitted by `csvql doctor`."""

    name: str
    scope: DoctorScope
    status: DoctorStatus
    message: str
    table: str | None = None
    check: str | None = None
    path: Path | None = None
    resolved_path: Path | None = None
    column: str | None = None
    reference_table: str | None = None
    reference_column: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "scope": self.scope,
            "status": self.status,
            "message": self.message,
        }
        if self.table is not None:
            payload["table"] = self.table
        if self.check is not None:
            payload["check"] = self.check
        if self.path is not None:
            payload["path"] = str(self.path)
        if self.resolved_path is not None:
            payload["resolved_path"] = str(self.resolved_path)
        if self.column is not None:
            payload["column"] = self.column
        if self.reference_table is not None:
            payload["reference_table"] = self.reference_table
        if self.reference_column is not None:
            payload["reference_column"] = self.reference_column
        return payload


@dataclass(frozen=True, slots=True)
class DoctorRunResult:
    """Aggregate result for a `csvql doctor` invocation."""

    project_root: Path | None
    config_path: Path | None
    probes: tuple[DoctorProbeResult, ...]

    @property
    def status(self) -> DoctorStatus:
        if any(probe.status == "failed" for probe in self.probes):
            return "failed"
        if any(probe.status == "warning" for probe in self.probes):
            return "warning"
        return "passed"

    @property
    def probe_count(self) -> int:
        return len(self.probes)

    @property
    def passed_count(self) -> int:
        return sum(1 for probe in self.probes if probe.status == "passed")

    @property
    def warning_count(self) -> int:
        return sum(1 for probe in self.probes if probe.status == "warning")

    @property
    def failed_count(self) -> int:
        return sum(1 for probe in self.probes if probe.status == "failed")

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "probe_count": self.probe_count,
            "passed_count": self.passed_count,
            "warning_count": self.warning_count,
            "failed_count": self.failed_count,
            "project": {
                "config_path": str(self.config_path) if self.config_path is not None else None,
                "project_root": str(self.project_root) if self.project_root is not None else None,
            },
            "probes": [probe.as_dict() for probe in self.probes],
        }
```

- [ ] **Step 6: Add doctor JSON/table formatters to `src/csvql/output.py`**

In `src/csvql/output.py`, add the new import and formatter functions:

```python
from csvql.doctor import DoctorProbeResult, DoctorRunResult


def format_doctor_result_json(result: DoctorRunResult) -> str:
    """Format a doctor result as deterministic JSON."""

    return json.dumps(result.as_dict(), indent=2, sort_keys=True)


def format_doctor_result_table(result: DoctorRunResult) -> str:
    """Format a doctor result as Rich table text."""

    console = Console(color_system=None, force_terminal=False, record=True, width=140)
    console.print(f"Status: {result.status}")
    console.print(
        "Probes: "
        f"{result.probe_count} | Passed: {result.passed_count} | "
        f"Warnings: {result.warning_count} | Failed: {result.failed_count}"
    )

    table = Table(show_header=True)
    table.add_column("scope")
    table.add_column("name")
    table.add_column("status")
    table.add_column("target")
    table.add_column("message")
    for probe in result.probes:
        table.add_row(
            probe.scope,
            probe.name,
            probe.status,
            _format_doctor_target(probe),
            probe.message,
        )
    console.print(table)
    return console.export_text(clear=True)


def _format_doctor_target(probe: DoctorProbeResult) -> str:
    if probe.scope == "table":
        return probe.table or ""
    if probe.scope == "check":
        return f"{probe.table}.{probe.check}".strip(".")
    return str(probe.path or ".csvql.yml")
```

- [ ] **Step 7: Run the focused doctor unit and formatter tests**

Run:

```bash
uv run pytest tests/test_doctor.py tests/test_output.py -q
```

Expected: PASS for the new doctor unit/formatter tests.

- [ ] **Step 8: Commit the result-object and formatter slice**

```bash
git add src/csvql/doctor.py tests/test_doctor.py src/csvql/output.py tests/test_output.py
git commit -m "feat: add doctor result and output types"
```

## Task 2: Add The Doctor CLI And Table-Readiness Workflow

**Files:**
- Create: `tests/test_cli_doctor.py`
- Modify: `src/csvql/doctor.py`
- Modify: `src/csvql/cli.py`
- Modify: `src/csvql/exceptions.py`

- [ ] **Step 1: Write failing CLI tests for discovery, config load, and table readiness**

Create `tests/test_cli_doctor.py` with these initial CLI tests:

```python
import json
from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from csvql.cli import app
from csvql.project_config import CONFIG_FILENAME

runner = CliRunner()


def _write_project_config(tmp_path: Path, text: str) -> None:
    (tmp_path / CONFIG_FILENAME).write_text(dedent(text).lstrip(), encoding="utf-8")


def test_doctor_without_catalog_returns_warning_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "warning"
    assert payload["project"] == {"config_path": None, "project_root": None}
    assert payload["warning_count"] == 1
    assert payload["failed_count"] == 0
    assert payload["probes"][0]["name"] == "project_discovery"
    assert payload["probes"][0]["status"] == "warning"


def test_doctor_invalid_yaml_returns_failed_json_and_exit_12(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text("version: [\n", encoding="utf-8")

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 12, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    assert payload["probes"][0]["name"] == "project_discovery"
    assert payload["probes"][1]["name"] == "config_load"
    assert payload["probes"][1]["status"] == "failed"
    assert "Invalid YAML" in payload["probes"][1]["message"]


def test_doctor_empty_project_catalog_returns_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables: {}
        """,
    )

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "warning"
    assert payload["probes"][-1]["name"] == "catalog_tables_present"
    assert payload["probes"][-1]["status"] == "warning"


def test_doctor_valid_project_returns_passed_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "order_id,status\nORD-1,paid\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
        """,
    )

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "passed"
    assert payload["failed_count"] == 0
    assert payload["warning_count"] == 0
    assert any(
        probe["name"] == "table_readiness"
        and probe["status"] == "passed"
        and probe["table"] == "orders"
        for probe in payload["probes"]
    )


def test_doctor_header_only_csv_still_passes_table_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "order_id,status\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
        """,
    )

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "passed"
    assert any(
        probe["name"] == "table_readiness"
        and probe["status"] == "passed"
        and probe["table"] == "orders"
        for probe in payload["probes"]
    )


def test_doctor_missing_csv_returns_failed_probe_and_exit_12(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
        """,
    )

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 12, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    assert any(
        probe["name"] == "table_readiness"
        and probe["status"] == "failed"
        and probe["table"] == "orders"
        for probe in payload["probes"]
    )
```

- [ ] **Step 2: Run the new doctor CLI tests to verify they fail**

Run:

```bash
uv run pytest tests/test_cli_doctor.py -q
```

Expected: FAIL with `No such command 'doctor'`.

- [ ] **Step 3: Reserve exit code `12` in `src/csvql/exceptions.py`**

Add this class to `src/csvql/exceptions.py` after `DataQualityCheckFailure`:

```python
class DoctorFailure(CSVQLError):
    """Raised when `csvql doctor` finds project-health failures."""

    exit_code = 12
```

- [ ] **Step 4: Implement discovery, config-load, and table-readiness workflow in `src/csvql/doctor.py`**

Extend `src/csvql/doctor.py` with the actual doctor workflow:

```python
import duckdb

from csvql.exceptions import FileMissingError, ProjectConfigError
from csvql.project_config import ProjectContext, ProjectTable, discover_project, load_project, resolve_catalog_path
from csvql.sql_utils import quote_identifier

DOCTOR_VIEW_PREFIX = "__csvql_doctor_"


def run_doctor(start_dir: Path | None = None) -> DoctorRunResult:
    """Run project-health probes for the nearest CSVQL project."""

    try:
        project_root, config_path = discover_project(start_dir)
    except ProjectConfigError as exc:
        return DoctorRunResult(
            project_root=None,
            config_path=None,
            probes=(
                DoctorProbeResult(
                    name="project_discovery",
                    scope="project",
                    status="warning",
                    message=exc.message,
                ),
            ),
        )

    probes: list[DoctorProbeResult] = [
        DoctorProbeResult(
            name="project_discovery",
            scope="project",
            status="passed",
            message="Discovered project catalog.",
            path=config_path,
            resolved_path=config_path,
        )
    ]

    try:
        context = load_project(start_dir)
    except ProjectConfigError as exc:
        probes.append(
            DoctorProbeResult(
                name="config_load",
                scope="project",
                status="failed",
                message=exc.message,
                path=config_path,
                resolved_path=config_path,
            )
        )
        return DoctorRunResult(
            project_root=project_root,
            config_path=config_path,
            probes=tuple(probes),
        )

    probes.append(
        DoctorProbeResult(
            name="config_load",
            scope="project",
            status="passed",
            message="Loaded project catalog.",
            path=context.config_path,
            resolved_path=context.config_path,
        )
    )

    tables = tuple(sorted(context.config.tables, key=lambda table: (table.name.lower(), table.name)))
    if not tables:
        probes.append(
            DoctorProbeResult(
                name="catalog_tables_present",
                scope="project",
                status="warning",
                message="Project catalog has no configured tables.",
                path=context.config_path,
                resolved_path=context.config_path,
            )
        )
        return DoctorRunResult(
            project_root=context.project_root,
            config_path=context.config_path,
            probes=tuple(probes),
        )

    probes.append(
        DoctorProbeResult(
            name="catalog_tables_present",
            scope="project",
            status="passed",
            message=f"Project catalog has {len(tables)} configured table(s).",
            path=context.config_path,
            resolved_path=context.config_path,
        )
    )

    table_probes, _ = _run_table_readiness_probes(context, tables)
    probes.extend(table_probes)
    return DoctorRunResult(
        project_root=context.project_root,
        config_path=context.config_path,
        probes=tuple(probes),
    )


def _run_table_readiness_probes(
    context: ProjectContext,
    tables: tuple[ProjectTable, ...],
) -> tuple[tuple[DoctorProbeResult, ...], dict[str, tuple[str, ...]]]:
    probes: list[DoctorProbeResult] = []
    column_names_by_table: dict[str, tuple[str, ...]] = {}
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = duckdb.connect(database=":memory:")
        for table in tables:
            try:
                resolved_path = resolve_catalog_path(table, context)
                relation = connection.read_csv(
                    str(resolved_path),
                    auto_detect=True,
                    header=True,
                )
                relation.create_view(_doctor_view_name(table.name), replace=True)
                connection.execute(
                    f"SELECT * FROM {quote_identifier(_doctor_view_name(table.name))} LIMIT 1"
                ).fetchall()
            except (FileMissingError, OSError, duckdb.Error) as exc:
                probes.append(
                    DoctorProbeResult(
                        name="table_readiness",
                        scope="table",
                        status="failed",
                        message=str(exc),
                        table=table.name,
                    )
                )
                continue

            column_names_by_table[table.name.lower()] = tuple(str(column) for column in relation.columns)
            probes.append(
                DoctorProbeResult(
                    name="table_readiness",
                    scope="table",
                    status="passed",
                    message="Registered and read configured CSV through DuckDB.",
                    table=table.name,
                    path=Path(table.path),
                    resolved_path=resolved_path,
                )
            )
    finally:
        if connection is not None:
            connection.close()

    return tuple(probes), column_names_by_table


def _doctor_view_name(table_name: str) -> str:
    return f"{DOCTOR_VIEW_PREFIX}{table_name.lower()}"
```

- [ ] **Step 5: Wire the doctor command into `src/csvql/cli.py`**

Update the imports and add the command after `check`:

```python
from csvql.doctor import run_doctor
from csvql.exceptions import CSVQLError, DataQualityCheckFailure, DoctorFailure
from csvql.output import (
    OutputFormat,
    format_check_result_json,
    format_check_result_table,
    format_doctor_result_json,
    format_doctor_result_table,
    format_inspect_result_json,
    format_inspect_result_table,
    format_json_result,
    format_profile_result_json,
    format_profile_result_table,
    format_project_tables_json,
    format_project_tables_table,
    format_sample_result_json,
    format_sample_result_table,
    format_table_result,
)


@app.command()
def doctor(
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="Doctor output format.",
        ),
    ] = OutputFormat.table,
) -> None:
    """Check local CSVQL project health without running user-authored SQL."""

    result = run_doctor(start_dir=Path.cwd())
    if output is OutputFormat.json:
        typer.echo(format_doctor_result_json(result))
    else:
        typer.echo(format_doctor_result_table(result), nl=False)
    if result.status == "failed":
        raise typer.Exit(DoctorFailure.exit_code)
```

- [ ] **Step 6: Run the focused doctor CLI tests**

Run:

```bash
uv run pytest tests/test_cli_doctor.py -q
```

Expected: PASS for discovery, config-load, zero-table, readable-table, and missing-file cases.

- [ ] **Step 7: Commit the doctor CLI and table-readiness slice**

```bash
git add src/csvql/doctor.py src/csvql/cli.py src/csvql/exceptions.py tests/test_cli_doctor.py
git commit -m "feat: add doctor command and table readiness"
```

## Task 3: Add Static Check-Schema Audit Without Executing Checks

**Files:**
- Modify: `src/csvql/checks.py`
- Modify: `src/csvql/doctor.py`
- Modify: `tests/test_doctor.py`
- Modify: `tests/test_cli_doctor.py`

- [ ] **Step 1: Write failing tests for schema-audit failures and derivative-probe suppression**

Add these tests.

In `tests/test_doctor.py`, append:

```python
from pathlib import Path
from textwrap import dedent

from csvql.doctor import run_doctor


def test_run_doctor_omits_check_probes_when_table_readiness_failed(tmp_path: Path) -> None:
    (tmp_path / ".csvql.yml").write_text(
        dedent(
            """
            version: 1
            tables:
              orders:
                path: missing.csv
                checks:
                  - name: order_id_required
                    type: not_null
                    column: order_id
            """
        ).lstrip(),
        encoding="utf-8",
    )

    result = run_doctor(start_dir=tmp_path)

    assert result.status == "failed"
    assert [probe.name for probe in result.probes] == [
        "project_discovery",
        "config_load",
        "catalog_tables_present",
        "table_readiness",
    ]
    assert all(probe.scope != "check" for probe in result.probes)
```

In `tests/test_cli_doctor.py`, append:

```python
def test_doctor_fails_when_configured_check_column_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "actual_order_id\nORD-1\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
            checks:
              - name: order_id_required
                type: not_null
                column: order_id
        """,
    )

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 12, result.output
    payload = json.loads(result.output)
    failing_probe = next(probe for probe in payload["probes"] if probe["scope"] == "check")
    assert failing_probe["name"] == "check_schema_resolution"
    assert failing_probe["status"] == "failed"
    assert failing_probe["table"] == "orders"
    assert failing_probe["check"] == "order_id_required"
    assert failing_probe["column"] == "order_id"


def test_doctor_fails_when_foreign_key_reference_column_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "customers.csv").write_text(
        "customer_key\nC-1\n",
        encoding="utf-8",
    )
    (tmp_path / "data" / "subscriptions.csv").write_text(
        "subscription_id,customer_id\nSUB-1,C-1\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          customers:
            path: data/customers.csv
          subscriptions:
            path: data/subscriptions.csv
            checks:
              - name: customer_exists
                type: foreign_key
                column: customer_id
                references:
                  table: customers
                  column: customer_id
        """,
    )

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 12, result.output
    payload = json.loads(result.output)
    failing_probe = next(probe for probe in payload["probes"] if probe["scope"] == "check")
    assert failing_probe["name"] == "check_schema_resolution"
    assert failing_probe["status"] == "failed"
    assert failing_probe["reference_table"] == "customers"
    assert failing_probe["reference_column"] == "customer_id"
```

- [ ] **Step 2: Run the new doctor schema-audit tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_doctor.py::test_run_doctor_omits_check_probes_when_table_readiness_failed \
  tests/test_cli_doctor.py::test_doctor_fails_when_configured_check_column_is_missing \
  tests/test_cli_doctor.py::test_doctor_fails_when_foreign_key_reference_column_is_missing \
  -q
```

Expected: FAIL because doctor does not yet emit any check-scope probes.

- [ ] **Step 3: Expose a tiny public shared column-resolution helper in `src/csvql/checks.py`**

Add this public wrapper above `_resolve_column_name`:

```python
def resolve_configured_column_name(
    table_name: str,
    configured_column: str | None,
    column_names_by_table: dict[str, tuple[str, ...]],
) -> str:
    """Resolve a configured column name using CSVQL's existing check semantics."""

    return _resolve_column_name(table_name, configured_column, column_names_by_table)
```

Keep `_resolve_column_name()` unchanged so the current `check` workflow behavior stays identical.

- [ ] **Step 4: Extend `src/csvql/doctor.py` with static check-schema audit probes**

Update the imports and extend `run_doctor()` to call a new helper after table readiness:

```python
from csvql.checks import resolve_configured_column_name


def run_doctor(start_dir: Path | None = None) -> DoctorRunResult:
    ...
    table_probes, column_names_by_table = _run_table_readiness_probes(context, tables)
    probes.extend(table_probes)
    probes.extend(_run_check_schema_probes(context, column_names_by_table))
    return DoctorRunResult(
        project_root=context.project_root,
        config_path=context.config_path,
        probes=tuple(probes),
    )


def _run_check_schema_probes(
    context: ProjectContext,
    column_names_by_table: dict[str, tuple[str, ...]],
) -> tuple[DoctorProbeResult, ...]:
    probes: list[DoctorProbeResult] = []
    for table in sorted(context.config.tables, key=lambda item: (item.name.lower(), item.name)):
        if table.name.lower() not in column_names_by_table:
            continue
        for check in table.checks:
            reference = check.references
            if reference is not None and reference.table.lower() not in column_names_by_table:
                continue
            try:
                if check.column is not None:
                    resolve_configured_column_name(
                        check.table,
                        check.column,
                        column_names_by_table,
                    )
                if reference is not None:
                    resolve_configured_column_name(
                        reference.table,
                        reference.column,
                        column_names_by_table,
                    )
            except ProjectConfigError as exc:
                probes.append(
                    DoctorProbeResult(
                        name="check_schema_resolution",
                        scope="check",
                        status="failed",
                        message=exc.message,
                        table=check.table,
                        check=check.name,
                        column=check.column,
                        reference_table=reference.table if reference is not None else None,
                        reference_column=reference.column if reference is not None else None,
                    )
                )
                continue

            probes.append(
                DoctorProbeResult(
                    name="check_schema_resolution",
                    scope="check",
                    status="passed",
                    message="Resolved configured check columns against discovered schema.",
                    table=check.table,
                    check=check.name,
                    column=check.column,
                    reference_table=reference.table if reference is not None else None,
                    reference_column=reference.column if reference is not None else None,
                )
            )
    return tuple(probes)
```

- [ ] **Step 5: Run the focused schema-audit tests**

Run:

```bash
uv run pytest tests/test_doctor.py tests/test_cli_doctor.py -q
```

Expected: PASS, including suppression of derivative check probes when a table never passed readiness.

- [ ] **Step 6: Commit the doctor schema-audit slice**

```bash
git add src/csvql/checks.py src/csvql/doctor.py tests/test_doctor.py tests/test_cli_doctor.py
git commit -m "feat: add doctor check schema audit"
```

## Task 4: Document The Command And Run The Full Verification Gate

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Add the new command to the README status list**

In `README.md`, add this bullet under `Implemented now:`:

```markdown
- `csvql doctor --output json`
```

- [ ] **Step 2: Add a short doctor usage section to `README.md`**

Insert this section after the data-quality examples and before benchmark hardening:

````markdown
## Project Health Examples

Run project doctor from a directory with a `.csvql.yml` project catalog:

```bash
uv run csvql doctor
```

Return doctor results as JSON for automation:

```bash
uv run csvql doctor --output json
```

`csvql doctor` exits `0` for `passed` and `warning` results. It exits `12` when the
project catalog exists but CSVQL finds concrete project-health failures such as invalid
config, missing configured CSV files, unreadable CSV inputs, or configured checks that
reference missing columns.
````

- [ ] **Step 3: Update `docs/ARCHITECTURE.md` with the doctor workflow boundary**

Make these edits in `docs/ARCHITECTURE.md`:

```markdown
CLI arguments
  -> path/sql-file/input parser
  -> explicit table mapping parser or project catalog discovery
  -> validated table aliases and resolved CSV paths
  -> in-memory DuckDB engine
  -> query/inspect/sample/profile/check/doctor/export output
```

Add this new boundary entry:

```markdown
`doctor.py`
: Run project-health probes for the nearest `.csvql.yml`, returning tri-state
  pass/warning/fail results for project discovery, config load, table readability,
  and static configured-check schema audit without executing user-authored SQL or
  configured checks.
```

Update the `output.py` description to include doctor:

```markdown
`output.py`
: Convert query, inspect, sample, project catalog, profile, check, and doctor
  results into human-readable table output or automation-friendly JSON.
```

Add these current design choice bullets near the existing `check` bullets:

```markdown
- `doctor` discovers the nearest project catalog and returns a warning result, not a hard CLI error, when no `.csvql.yml` is present.
- `doctor` proves table readiness with CSVQL-controlled DuckDB registration plus a one-row read and treats zero-row readable CSVs as healthy.
- `doctor` statically audits configured check columns against discovered schema without executing configured checks and exits `12` when concrete project-health failures are found.
```

- [ ] **Step 4: Run the focused doctor test suite after the docs update**

Run:

```bash
uv run pytest tests/test_doctor.py tests/test_cli_doctor.py tests/test_output.py -q
```

Expected: PASS.

- [ ] **Step 5: Run the full verification gate**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
git diff --check
git status --short --branch
```

Expected:

- Ruff format: PASS
- Ruff lint: PASS
- mypy: PASS
- pytest: PASS
- `git diff --check`: no output
- `git status --short --branch`: only intended tracked changes before commit, then clean after commit

- [ ] **Step 6: Commit the docs and verification slice**

```bash
git add README.md docs/ARCHITECTURE.md
git commit -m "docs: add doctor command usage"
```

## Final Verification And Handoff

- [ ] **Step 1: Review the full diff before closeout**

Run:

```bash
git show --stat --oneline --decorate HEAD
git diff HEAD~4..HEAD -- src/csvql/doctor.py src/csvql/cli.py src/csvql/output.py src/csvql/exceptions.py src/csvql/checks.py tests/test_doctor.py tests/test_cli_doctor.py tests/test_output.py README.md docs/ARCHITECTURE.md
```

Expected:

- only doctor-related files changed
- no unrelated cleanup
- exit-code contract, JSON shape, probe model, docs, and tests all present

- [ ] **Step 2: Capture the final proof packet**

Record these final results in the implementation handoff:

```text
Branch: codex/v07-benchmark-release-hardening-ecb3
HEAD: <new commit after docs>
Changed files:
- src/csvql/doctor.py
- src/csvql/cli.py
- src/csvql/output.py
- src/csvql/exceptions.py
- src/csvql/checks.py
- tests/test_doctor.py
- tests/test_cli_doctor.py
- tests/test_output.py
- README.md
- docs/ARCHITECTURE.md

Verification:
- uv run ruff format --check .
- uv run ruff check .
- uv run mypy src
- uv run pytest
- git diff --check
```

Expected: all commands PASS.

## Spec Coverage Check

- New command shape: covered by Task 2 CLI wiring and tests.
- Tri-state status model and flat probe list: covered by Task 1 result objects and Task 2/3 CLI tests.
- Missing catalog warning instead of hard CLI error: covered by Task 2.
- Table-readiness proof with one-row read and zero-row success: covered by Task 2.
- Static check-schema audit without check execution: covered by Task 3.
- Exit code `12`: covered by Task 2.
- JSON/table output contract: covered by Task 1 and Task 2/3.
- README and architecture docs: covered by Task 4.

## Placeholder Scan

This plan intentionally avoids:

- `TODO`
- `TBD`
- “implement later”
- unspecified error handling
- unspecified tests
- “similar to Task N”

Every code-touching step includes concrete code, exact files, and exact commands.
