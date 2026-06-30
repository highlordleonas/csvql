# CSVQL Failure Gallery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-facing failure gallery for CSVQL's current deterministic CLI and small Python API failures, linked from README and roadmap, with focused proof tests.

**Architecture:** Runtime behavior remains authoritative. The slice adds one documentation page, one focused proof-test module for gallery-backed failures, and small README/roadmap edits; it does not change `src/csvql/*.py`, command semantics, exit codes, JSON shapes, or the trusted-local-SQL posture.

**Tech Stack:** Python, Typer `CliRunner`, pytest, DuckDB through existing CSVQL paths, `uv` for all commands, Markdown documentation.

---

## Direction Check

- Target lane: post-v0.7/v0.8 hardening toward v1.
- Wedge strengthened: deterministic errors, local trusted workflow, user repair guidance.
- Scope rejected: new CLI commands, exit-code redesign, JSON normalization, safe mode, generated checked-in gallery output.
- Contracts touched: documentation for current commands, current exit codes, current API exception behavior.
- Verification target: focused gallery tests, real CLI capture transcript, docs diff review, full local gates.

## File Map

- Create `tests/test_failure_gallery.py`: focused tests that prove the failure families documented by the gallery at the CLI/API boundary.
- Create `docs/failure-gallery.md`: repair-oriented user documentation with normalized path examples and test coverage pointers.
- Modify `README.md`: add the gallery to the Documentation list.
- Modify `docs/ROADMAP.md`: move the failure-gallery item from "Remaining before v1" into the v0.8 implemented list.
- Do not modify `src/csvql/*.py`, `.csvql.yml` schema behavior, command signatures, exit-code constants, JSON formatting logic, or shipped example data.

## Coverage Map

| Failure family | Current coverage | Planned action |
| --- | --- | --- |
| Direct missing CSV path | Unit and CLI coverage exists across source, inspect, profile, check | Add gallery-level CLI proof for `csvql query missing.csv "SELECT 1"` |
| Project catalog CSV path missing | Unit and doctor/check coverage exists | Add gallery-level query proof for catalog table context |
| Bad table mapping or alias | Unit coverage exists in `tests/test_table_mapping.py` | Add gallery-level CLI proofs for missing `=`, empty path, and invalid alias |
| Generated single-file alias distinction | Unit coverage exists for alias derivation | Add gallery-level success proof for a digit-leading filename using generated alias |
| DuckDB query failure | API coverage exists | Add gallery-level CLI proof for missing column |
| Missing project catalog | CLI coverage exists for query/check/project commands | Add gallery-level CLI proof for project-required query mode |
| Invalid project catalog | Project-config and doctor coverage exists | Add gallery-level doctor JSON proof for invalid YAML |
| Missing or empty SQL file | Unit and CLI coverage exists | Add gallery-level CLI proofs for missing run file, missing export file, and empty run file |
| Export overwrite protection | Unit and CLI coverage exists | Add gallery-level CLI proof for exit `10` without `--force` |
| Data-quality check failure | CLI coverage exists | Add gallery-level JSON proof for exit `11` and sampled failures |
| Doctor warning and failure | CLI coverage exists | Add gallery-level JSON proof for warning exit `0` and failed exit `12` |
| Python API error propagation | API coverage exists | Add gallery-level API proof that exceptions propagate while failed checks return `CheckRunResult` |

### Task 1: Add Gallery Proof Tests

**Files:**
- Create: `tests/test_failure_gallery.py`

- [ ] **Step 1: Create the focused proof test module**

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql.api import CSVQLSession
from csvql.cli import app
from csvql.exceptions import ProjectConfigError, QueryExecutionError, SQLFileError
from csvql.quality import CheckRunResult


runner = CliRunner()


def _write_csv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_gallery_project(
    root: Path,
    *,
    rows: str = "ORD-001,paid\nORD-002,pending\n",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "queries").mkdir(parents=True, exist_ok=True)
    _write_csv(root / "data" / "orders.csv", "order_id,status\n" + rows)
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


def test_gallery_direct_missing_csv_path_returns_exit_4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["query", "missing.csv", "SELECT 1"])

    assert result.exit_code == 4
    assert "Error: CSV file not found: missing.csv" in result.output
    assert (
        "Suggestion: Check the path or run from the directory that contains the CSV file."
        in result.output
    )


def test_gallery_project_catalog_missing_csv_path_returns_exit_4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".csvql.yml").write_text(
        (
            "version: 1\n"
            "tables:\n"
            "  orders:\n"
            "    path: data/missing.csv\n"
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["query", "SELECT COUNT(*) FROM orders"])

    assert result.exit_code == 4
    assert "CSV file not found for project catalog table 'orders': data/missing.csv" in (
        result.output
    )
    assert "Update .csvql.yml, run csvql add orders <path> --replace" in result.output


@pytest.mark.parametrize(
    ("mapping", "expected_message", "expected_suggestion"),
    [
        (
            "orders",
            "Invalid table mapping 'orders'.",
            "Use --table name=path, for example --table orders=data/orders.csv.",
        ),
        (
            "orders=",
            "Missing CSV path for table alias 'orders'.",
            "Use --table name=path, for example --table orders=data/orders.csv.",
        ),
        (
            "1orders=orders.csv",
            "Invalid table alias '1orders'.",
            "Use letters, numbers, and underscores; start with a letter or underscore.",
        ),
    ],
)
def test_gallery_bad_table_mapping_cli_errors_use_exit_6(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mapping: str,
    expected_message: str,
    expected_suggestion: str,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["query", "--table", mapping, "SELECT 1"])

    assert result.exit_code == 6
    assert f"Error: {expected_message}" in result.output
    assert f"Suggestion: {expected_suggestion}" in result.output


def test_gallery_single_file_shortcut_uses_generated_safe_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_csv(tmp_path / "2026-orders.csv", "order_id\nORD-001\n")

    result = runner.invoke(
        app,
        [
            "query",
            "2026-orders.csv",
            "SELECT COUNT(*) AS row_count FROM table_2026_orders",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [{"row_count": 1}]


def test_gallery_duckdb_query_failure_uses_exit_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_csv(tmp_path / "orders.csv", "order_id\nORD-001\n")

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            "orders=orders.csv",
            "SELECT missing_column FROM orders",
        ],
    )

    assert result.exit_code == 1
    assert "Error: DuckDB query failed:" in result.output
    assert "Suggestion: Check table names, column names, and SQL syntax." in result.output


def test_gallery_missing_project_catalog_uses_exit_8(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["query", "SELECT 1"])

    assert result.exit_code == 8
    assert "Error: No .csvql.yml project catalog found." in result.output
    assert "Suggestion: Run project init/add or pass --table mappings explicitly." in (
        result.output
    )


def test_gallery_invalid_project_catalog_doctor_uses_exit_12(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".csvql.yml").write_text("version: [\n", encoding="utf-8")

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 12, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    assert payload["probes"][1]["name"] == "config_load"
    assert payload["probes"][1]["status"] == "failed"
    assert "Invalid YAML" in payload["probes"][1]["message"]


def test_gallery_saved_sql_file_failures_use_exit_9(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "empty.sql").write_text("   \n", encoding="utf-8")

    missing_run = runner.invoke(app, ["run", "queries/missing.sql"])
    empty_run = runner.invoke(app, ["run", "empty.sql"])
    missing_export = runner.invoke(
        app,
        [
            "export",
            "queries/missing.sql",
            "--format",
            "csv",
            "--out",
            "out.csv",
        ],
    )

    assert missing_run.exit_code == 9
    assert "Error: SQL file not found: queries/missing.sql" in missing_run.output
    assert empty_run.exit_code == 9
    assert "Error: SQL file is empty: empty.sql" in empty_run.output
    assert missing_export.exit_code == 9
    assert "Error: SQL file not found: queries/missing.sql" in missing_export.output


def test_gallery_export_overwrite_protection_uses_exit_10(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "query.sql").write_text("SELECT 1 AS one", encoding="utf-8")
    (tmp_path / "out.csv").write_text("existing", encoding="utf-8")

    result = runner.invoke(
        app,
        ["export", "query.sql", "--format", "csv", "--out", "out.csv"],
    )

    assert result.exit_code == 10
    assert "Error: Export output already exists:" in result.output
    assert "Suggestion: Pass --force to overwrite it or choose a different output path." in (
        result.output
    )
    assert (tmp_path / "out.csv").read_text(encoding="utf-8") == "existing"


def test_gallery_data_quality_failure_uses_exit_11_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_gallery_project(tmp_path, rows="ORD-001,paid\n,pending\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["check", "--output", "json", "--show-failures", "--failure-limit", "1"],
    )

    assert result.exit_code == 11, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    assert payload["failed_count"] == 1
    assert payload["checks"][0]["name"] == "order_id_required"
    assert payload["checks"][0]["failures"][0]["row_number"] == 2


def test_gallery_doctor_warning_and_failure_statuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty_project = tmp_path / "empty"
    empty_project.mkdir()
    monkeypatch.chdir(empty_project)

    warning_result = runner.invoke(app, ["doctor", "--output", "json"])

    assert warning_result.exit_code == 0, warning_result.output
    warning_payload = json.loads(warning_result.output)
    assert warning_payload["status"] == "warning"
    assert warning_payload["probes"][0]["name"] == "project_discovery"
    assert warning_payload["probes"][0]["status"] == "warning"

    broken_project = tmp_path / "broken"
    broken_project.mkdir()
    (broken_project / ".csvql.yml").write_text(
        (
            "version: 1\n"
            "tables:\n"
            "  orders:\n"
            "    path: data/missing.csv\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(broken_project)

    failure_result = runner.invoke(app, ["doctor", "--output", "json"])

    assert failure_result.exit_code == 12, failure_result.output
    failure_payload = json.loads(failure_result.output)
    assert failure_payload["status"] == "failed"
    assert any(
        probe["name"] == "table_readiness"
        and probe["status"] == "failed"
        and probe["table"] == "orders"
        for probe in failure_payload["probes"]
    )


def test_gallery_python_api_propagates_errors_but_check_failures_return_result(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_gallery_project(project_root, rows="ORD-001,paid\n,pending\n")

    with pytest.raises(ProjectConfigError):
        CSVQLSession.from_config(tmp_path / "missing-project")

    session = CSVQLSession.from_config(project_root)

    with pytest.raises(QueryExecutionError):
        session.query("SELECT missing_column FROM orders")

    with pytest.raises(SQLFileError):
        session.run_file("queries/missing.sql")

    result = session.check(show_failures=True, failure_limit=1)

    assert isinstance(result, CheckRunResult)
    assert result.status == "failed"
    assert result.failed_count == 1
    assert result.checks[0].name == "order_id_required"
    assert result.checks[0].failures[0].row_number == 2
```

- [ ] **Step 2: Run the new proof tests**

Run:

```bash
uv run pytest tests/test_failure_gallery.py -q
```

Expected: the new module passes. If a test fails because current runtime output differs from the assertion, inspect the failure. If the runtime behavior is intentional, update the test and planned docs to match runtime truth. If the runtime behavior is wrong, stop this docs slice and write a separate behavior-fix decision.

- [ ] **Step 3: Commit the focused tests**

Run:

```bash
git add tests/test_failure_gallery.py
git commit -m "test: cover failure gallery contracts"
```

Expected: one commit containing only `tests/test_failure_gallery.py`.

### Task 2: Capture Real CLI Output For Documentation

**Files:**
- Scratch only: `/tmp/csvql-failure-gallery-captures.md`
- Do not commit the scratch transcript.

- [ ] **Step 1: Generate a scratch transcript from real CLI invocations**

Run:

```bash
uv run python - <<'PY' > /tmp/csvql-failure-gallery-captures.md
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run_case(root: Path, title: str, args: list[str]) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "csvql", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    print(f"## {title}")
    print()
    print("Command:")
    print(f"uv run csvql {' '.join(args)}")
    print()
    print(f"Exit code: {completed.returncode}")
    print()
    print("Stdout:")
    print("```")
    print(completed.stdout.strip())
    print("```")
    print()
    if completed.stderr.strip():
        print("Stderr:")
        print("```")
        print(completed.stderr.strip())
        print("```")
        print()


with tempfile.TemporaryDirectory(prefix="csvql-gallery-") as temp:
    root = Path(temp)

    missing_csv = root / "missing-csv"
    missing_csv.mkdir()
    run_case(missing_csv, "direct missing CSV", ["query", "missing.csv", "SELECT 1"])

    catalog_missing_csv = root / "catalog-missing-csv"
    catalog_missing_csv.mkdir()
    (catalog_missing_csv / ".csvql.yml").write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: data/missing.csv\n",
        encoding="utf-8",
    )
    run_case(
        catalog_missing_csv,
        "project catalog missing CSV",
        ["query", "SELECT COUNT(*) FROM orders"],
    )

    mapping_root = root / "mapping"
    mapping_root.mkdir()
    run_case(mapping_root, "table mapping without equals", ["query", "--table", "orders", "SELECT 1"])
    run_case(mapping_root, "table mapping empty path", ["query", "--table", "orders=", "SELECT 1"])
    run_case(mapping_root, "invalid explicit alias", ["query", "--table", "1orders=orders.csv", "SELECT 1"])

    query_root = root / "query"
    query_root.mkdir()
    (query_root / "orders.csv").write_text("order_id\nORD-001\n", encoding="utf-8")
    run_case(
        query_root,
        "duckdb query failure",
        ["query", "--table", "orders=orders.csv", "SELECT missing_column FROM orders"],
    )

    no_catalog_root = root / "no-catalog"
    no_catalog_root.mkdir()
    run_case(no_catalog_root, "missing project catalog", ["query", "SELECT 1"])

    invalid_config_root = root / "invalid-config"
    invalid_config_root.mkdir()
    (invalid_config_root / ".csvql.yml").write_text("version: [\n", encoding="utf-8")
    run_case(invalid_config_root, "invalid project catalog", ["doctor", "--output", "json"])

    sql_root = root / "sql"
    sql_root.mkdir()
    (sql_root / "empty.sql").write_text("   \n", encoding="utf-8")
    run_case(sql_root, "missing SQL file for run", ["run", "queries/missing.sql"])
    run_case(sql_root, "empty SQL file for run", ["run", "empty.sql"])
    run_case(
        sql_root,
        "missing SQL file for export",
        ["export", "queries/missing.sql", "--format", "csv", "--out", "out.csv"],
    )

    export_root = root / "export"
    export_root.mkdir()
    (export_root / "query.sql").write_text("SELECT 1 AS one", encoding="utf-8")
    (export_root / "out.csv").write_text("existing", encoding="utf-8")
    run_case(
        export_root,
        "export overwrite protection",
        ["export", "query.sql", "--format", "csv", "--out", "out.csv"],
    )

    check_root = root / "check"
    check_root.mkdir()
    (check_root / "data").mkdir()
    (check_root / "data" / "orders.csv").write_text(
        "order_id,status\nORD-001,paid\n,pending\n",
        encoding="utf-8",
    )
    (check_root / ".csvql.yml").write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: data/orders.csv\n"
        "    checks:\n"
        "      - name: order_id_required\n"
        "        type: not_null\n"
        "        column: order_id\n",
        encoding="utf-8",
    )
    run_case(
        check_root,
        "data quality check failure",
        ["check", "--output", "json", "--show-failures", "--failure-limit", "1"],
    )

    doctor_warning_root = root / "doctor-warning"
    doctor_warning_root.mkdir()
    run_case(doctor_warning_root, "doctor warning", ["doctor", "--output", "json"])

    doctor_failure_root = root / "doctor-failure"
    doctor_failure_root.mkdir()
    (doctor_failure_root / ".csvql.yml").write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: data/missing.csv\n",
        encoding="utf-8",
    )
    run_case(doctor_failure_root, "doctor failure", ["doctor", "--output", "json"])

print("## Normalization note")
print()
print("Replace absolute temporary roots with <project-root> before copying examples into docs.")
PY
```

Expected: `/tmp/csvql-failure-gallery-captures.md` contains one section per documented CLI scenario, each with a command, exit code, and captured stdout.

- [ ] **Step 2: Compare the transcript against the proof tests**

Run:

```bash
rg -n "Exit code: (1|4|6|8|9|10|11|12)|DuckDB query failed|CSV file not found|Invalid table mapping|Invalid table alias|No \\.csvql\\.yml|SQL file not found|SQL file is empty|Export output already exists|order_id_required|project_discovery|table_readiness" /tmp/csvql-failure-gallery-captures.md
```

Expected: matches exist for every family in the coverage map. If a command produces a different exit code or stable phrase than `tests/test_failure_gallery.py`, update the test only when source/runtime inspection proves the captured behavior is intentional.

### Task 3: Create The Failure Gallery Documentation

**Files:**
- Create: `docs/failure-gallery.md`

- [ ] **Step 1: Create `docs/failure-gallery.md`**

```markdown
# Failure Gallery

CSVQL is a local developer tool for trusted SQL over local CSV files. DuckDB executes user-authored SQL, and CSVQL does not restrict DuckDB capabilities or filesystem access.

This gallery documents common deterministic failures that CSVQL already handles. Runtime behavior wins: if a command prints a different exit code or stable message than this page, treat the runtime as the source to inspect before changing docs.

Examples use `uv run csvql ...`. Absolute temporary paths are normalized as `<project-root>` when the path value is not the contract.

## CLI Exit-Code Quick Reference

| Exit code | Failure kind | Typical fix |
| --- | --- | --- |
| `1` | DuckDB query execution failure | Check table aliases, column names, and SQL syntax |
| `4` | CSV file missing | Fix the path, run from the intended directory, or update `.csvql.yml` |
| `6` | Bad `--table name=path` mapping | Use a valid table alias and non-empty CSV path |
| `8` | Project catalog discovery or validation failure | Run `csvql init`, run `csvql add`, or correct `.csvql.yml` |
| `9` | Saved SQL file missing, unreadable, or empty | Create a readable non-empty SQL file |
| `10` | Export output already exists | Pick a new output path or pass `--force` |
| `11` | Configured checks ran and found data-quality failures | Inspect failed checks and repair the data or check definition |
| `12` | `csvql doctor` found project-health failures | Correct the project catalog, CSV files, or check schema |

Typer usage errors, such as an invalid option value, use Typer's own CLI path and are outside this gallery.

## Missing CSV Path

### Direct CSV argument

Scenario: the single-file shortcut points at a file that does not exist.

Command:

```bash
uv run csvql query missing.csv "SELECT 1"
```

Expected exit code: `4`

Expected message shape:

```text
Error: CSV file not found: missing.csv
Suggestion: Check the path or run from the directory that contains the CSV file.
```

Why it fails: CSVQL resolves local CSV paths before handing work to DuckDB.

How to fix: run from the directory that contains the CSV, pass the correct path, or add the CSV to a project catalog and query by table alias.

Covered by: `tests/test_failure_gallery.py::test_gallery_direct_missing_csv_path_returns_exit_4`

### Project catalog table path

Scenario: `.csvql.yml` points a registered table at a missing CSV.

Command:

```bash
uv run csvql query "SELECT COUNT(*) FROM orders"
```

Expected exit code: `4`

Expected message shape:

```text
Error: CSV file not found for project catalog table 'orders': data/missing.csv
Suggestion: Update .csvql.yml, run csvql add orders <path> --replace, or restore the CSV file.
```

Why it fails: CSVQL resolves configured table paths relative to the project root before registering DuckDB views.

How to fix: restore the CSV file, edit `.csvql.yml`, or run `uv run csvql add orders <path> --replace`.

Covered by: `tests/test_failure_gallery.py::test_gallery_project_catalog_missing_csv_path_returns_exit_4`

## Bad Table Mapping Or Alias

Scenario: `--table` is provided without `name=path`.

Command:

```bash
uv run csvql query --table orders "SELECT 1"
```

Expected exit code: `6`

Expected message shape:

```text
Error: Invalid table mapping 'orders'.
Suggestion: Use --table name=path, for example --table orders=data/orders.csv.
```

How to fix: pass `--table orders=data/orders.csv`.

Covered by: `tests/test_failure_gallery.py::test_gallery_bad_table_mapping_cli_errors_use_exit_6`

Scenario: `--table` has an alias but no CSV path.

Command:

```bash
uv run csvql query --table orders= "SELECT 1"
```

Expected exit code: `6`

Expected message shape:

```text
Error: Missing CSV path for table alias 'orders'.
Suggestion: Use --table name=path, for example --table orders=data/orders.csv.
```

How to fix: add the path after `=`.

Covered by: `tests/test_failure_gallery.py::test_gallery_bad_table_mapping_cli_errors_use_exit_6`

Scenario: a user-provided alias is not a safe SQL identifier.

Command:

```bash
uv run csvql query --table 1orders=orders.csv "SELECT 1"
```

Expected exit code: `6`

Expected message shape:

```text
Error: Invalid table alias '1orders'.
Suggestion: Use letters, numbers, and underscores; start with a letter or underscore.
```

How to fix: use an alias such as `orders_2026`.

Covered by: `tests/test_failure_gallery.py::test_gallery_bad_table_mapping_cli_errors_use_exit_6`

Single-file shortcut note: CSVQL derives a safe alias from filenames in shortcut mode. A file named `2026-orders.csv` is queried as `table_2026_orders`; user-provided `--table` aliases remain validated exactly as entered.

Covered by: `tests/test_failure_gallery.py::test_gallery_single_file_shortcut_uses_generated_safe_alias`

## DuckDB Query Failure

Scenario: the SQL references a missing column.

Command:

```bash
uv run csvql query --table orders=orders.csv "SELECT missing_column FROM orders"
```

Expected exit code: `1`

Expected message shape:

```text
Error: DuckDB query failed:
Suggestion: Check table names, column names, and SQL syntax.
```

Why it fails: CSVQL treats user-authored SQL as trusted local SQL and passes it to DuckDB after registering CSV sources.

How to fix: run `uv run csvql inspect orders.csv`, check the table alias, and correct the SQL.

Covered by: `tests/test_failure_gallery.py::test_gallery_duckdb_query_failure_uses_exit_1`

## Project Catalog Failures

### Missing catalog for project-required query mode

Scenario: `csvql query "SELECT ..."` is run without explicit `--table` mappings and no `.csvql.yml` exists.

Command:

```bash
uv run csvql query "SELECT 1"
```

Expected exit code: `8`

Expected message shape:

```text
Error: No .csvql.yml project catalog found.
Suggestion: Run project init/add or pass --table mappings explicitly.
```

How to fix: run `uv run csvql init` and `uv run csvql add`, or pass `--table name=path` for an ad hoc query.

Covered by: `tests/test_failure_gallery.py::test_gallery_missing_project_catalog_uses_exit_8`

### Invalid catalog discovered by doctor

Scenario: `.csvql.yml` is present but contains malformed YAML.

Command:

```bash
uv run csvql doctor --output json
```

Expected exit code: `12`

Stable JSON fields:

```text
status=failed
probes[1].name=config_load
probes[1].status=failed
probes[1].message contains "Invalid YAML"
```

How to fix: repair `.csvql.yml` so it has `version: 1` and a mapping under `tables`.

Covered by: `tests/test_failure_gallery.py::test_gallery_invalid_project_catalog_doctor_uses_exit_12`

## Saved SQL File Failures

Scenario: `csvql run` points at a missing SQL file.

Command:

```bash
uv run csvql run queries/missing.sql
```

Expected exit code: `9`

Expected message shape:

```text
Error: SQL file not found: queries/missing.sql
Suggestion: Check the path or run from the directory that contains the SQL file.
```

How to fix: create the SQL file or run from the intended project directory.

Covered by: `tests/test_failure_gallery.py::test_gallery_saved_sql_file_failures_use_exit_9`

Scenario: `csvql run` points at an empty SQL file.

Command:

```bash
uv run csvql run empty.sql
```

Expected exit code: `9`

Expected message shape:

```text
Error: SQL file is empty: empty.sql
Suggestion: Add a SQL statement before running it.
```

How to fix: write one SQL statement in the file.

Covered by: `tests/test_failure_gallery.py::test_gallery_saved_sql_file_failures_use_exit_9`

Scenario: `csvql export` points at a missing SQL file.

Command:

```bash
uv run csvql export queries/missing.sql --format csv --out out.csv
```

Expected exit code: `9`

Expected message shape:

```text
Error: SQL file not found: queries/missing.sql
```

How to fix: create the SQL file before exporting, then rerun the export command.

Covered by: `tests/test_failure_gallery.py::test_gallery_saved_sql_file_failures_use_exit_9`

## Export Overwrite Protection

Scenario: the export output path already exists and `--force` was not passed.

Command:

```bash
uv run csvql export query.sql --format csv --out out.csv
```

Expected exit code: `10`

Expected message shape:

```text
Error: Export output already exists:
Suggestion: Pass --force to overwrite it or choose a different output path.
```

Why it fails: CSVQL refuses to clobber an existing export unless the command explicitly opts in.

How to fix: choose a new output path or pass `--force`.

Covered by: `tests/test_failure_gallery.py::test_gallery_export_overwrite_protection_uses_exit_10`

## Data-Quality Check Failure

Scenario: configured checks execute successfully and find bad data.

Command:

```bash
uv run csvql check --output json --show-failures --failure-limit 1
```

Expected exit code: `11`

Stable JSON fields:

```text
status=failed
failed_count=1
checks[0].name=order_id_required
checks[0].failures[0].row_number=2
```

Why it fails: a data-quality failure means the command ran and found invalid rows. It is not the same as a runtime failure.

How to fix: inspect sampled failures with `--show-failures`, repair the data or check definition, then rerun `csvql check`.

Covered by: `tests/test_failure_gallery.py::test_gallery_data_quality_failure_uses_exit_11_json`

## Doctor Warning And Project-Health Failure

Scenario: no project catalog exists.

Command:

```bash
uv run csvql doctor --output json
```

Expected exit code: `0`

Stable JSON fields:

```text
status=warning
probes[0].name=project_discovery
probes[0].status=warning
```

Why it is not a failure: doctor can report that no project exists without failing the process.

How to fix: run `uv run csvql init` if this directory should be a CSVQL project.

Covered by: `tests/test_failure_gallery.py::test_gallery_doctor_warning_and_failure_statuses`

Scenario: a project catalog exists but references a missing CSV.

Command:

```bash
uv run csvql doctor --output json
```

Expected exit code: `12`

Stable JSON fields:

```text
status=failed
one probe has name=table_readiness
that probe has status=failed
that probe has table=orders
```

Why it fails: doctor found a concrete project-health problem.

How to fix: restore the CSV, correct `.csvql.yml`, or run `uv run csvql add orders <path> --replace`.

Covered by: `tests/test_failure_gallery.py::test_gallery_doctor_warning_and_failure_statuses`

## Python API Notes

The small Python API raises `CSVQLError` subclasses for runtime errors instead of exiting the process.

Documented examples:

- `CSVQLSession.from_config(...)` raises `ProjectConfigError` when no project catalog is found.
- `session.query(...)` raises `QueryExecutionError` when DuckDB rejects the SQL.
- `session.run_file(...)` raises `SQLFileError` when the SQL file is missing or unusable.
- `session.check(...)` returns `CheckRunResult` with `status == "failed"` when configured checks run and find data-quality failures.

Covered by: `tests/test_failure_gallery.py::test_gallery_python_api_propagates_errors_but_check_failures_return_result`

## Proof

This gallery is backed by focused tests in `tests/test_failure_gallery.py` plus the existing source-specific tests for table mapping, SQL files, export paths, checks, doctor output, and API behavior.

Before claiming this page is current, run:

```bash
uv run pytest tests/test_failure_gallery.py -q
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```
```

- [ ] **Step 2: Compare docs against captured transcript**

Run:

```bash
rg -n "Expected exit code:|Expected message shape:|Stable JSON fields:|Covered by:" docs/failure-gallery.md
```

Expected: every gallery entry has an exit code or stable JSON fields plus a `Covered by` line.

- [ ] **Step 3: Commit the gallery page**

Run:

```bash
git add docs/failure-gallery.md
git commit -m "docs: add failure gallery"
```

Expected: one commit containing only `docs/failure-gallery.md`.

### Task 4: Link README Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the failure gallery link to the Documentation list**

Change the Documentation list to include this bullet after JSON contracts:

```markdown
- [Failure gallery](docs/failure-gallery.md)
```

The resulting list should read:

```markdown
## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Benchmarking](docs/benchmarking.md)
- [JSON contracts](docs/json-contracts.md)
- [Failure gallery](docs/failure-gallery.md)
- [Product direction](docs/PRODUCT_DIRECTION.md)
- [Release readiness](docs/release-readiness.md)
- [Roadmap](docs/ROADMAP.md)
- [Codex capability review](docs/CODEX_CAPABILITY_REVIEW.md)
- [v1 Quality Spine design](docs/superpowers/specs/2026-06-26-csvql-v1-quality-spine-design.md)
```

- [ ] **Step 2: Verify the README link target exists**

Run:

```bash
test -f docs/failure-gallery.md
```

Expected: command exits `0`.

### Task 5: Update Roadmap Status

**Files:**
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Move the failure-gallery item into the v0.8 implemented list**

In `docs/ROADMAP.md`, add this bullet in the `v0.8.0 - Portfolio Polish And Python API` Implemented list after the JSON contract documentation bullet:

```markdown
- common failure gallery covering missing files, invalid aliases, invalid config, failed checks, overwrite protection, missing SQL files, and doctor failures
```

Then remove that same bullet from `Remaining before v1`.

The `Remaining before v1` list should become:

```markdown
Remaining before v1:

- final documentation pass that keeps README, architecture, JSON contracts, roadmap, and product direction aligned
```

- [ ] **Step 2: Verify the roadmap names the gallery only once**

Run:

```bash
rg -n "common failure gallery" docs/ROADMAP.md
```

Expected: one match in the v0.8 implemented list.

### Task 6: Run Focused And Full Verification

**Files:**
- Review: `tests/test_failure_gallery.py`
- Review: `docs/failure-gallery.md`
- Review: `README.md`
- Review: `docs/ROADMAP.md`

- [ ] **Step 1: Run focused tests for the gallery**

Run:

```bash
uv run pytest tests/test_failure_gallery.py -q
```

Expected: all tests in `tests/test_failure_gallery.py` pass.

- [ ] **Step 2: Run docs and whitespace checks**

Run:

```bash
git diff --check -- tests/test_failure_gallery.py docs/failure-gallery.md README.md docs/ROADMAP.md
```

Expected: no whitespace errors.

- [ ] **Step 3: Run standard repo gates**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

Expected: all commands pass. If a full gate fails, keep the failure output and diagnose whether it is caused by this slice before changing any file outside the file map.

- [ ] **Step 4: Review the final diff**

Run:

```bash
git diff -- tests/test_failure_gallery.py docs/failure-gallery.md README.md docs/ROADMAP.md
```

Expected:

- `tests/test_failure_gallery.py` contains gallery proof tests only.
- `docs/failure-gallery.md` documents current runtime behavior and repair guidance.
- `README.md` only adds the gallery link.
- `docs/ROADMAP.md` only moves the failure-gallery item from remaining to implemented.
- No source file under `src/csvql/` changed.

### Task 7: Commit Documentation Links And Handoff

**Files:**
- Commit: `README.md`
- Commit: `docs/ROADMAP.md`

- [ ] **Step 1: Commit README and roadmap updates**

Run:

```bash
git add README.md docs/ROADMAP.md
git commit -m "docs: link failure gallery"
```

Expected: one commit containing only README and roadmap status updates.

- [ ] **Step 2: Record final state**

Run:

```bash
git status --short --branch
```

Expected: no uncommitted changes from this slice. If other files were dirty before execution, confirm they are unchanged by this slice.

- [ ] **Step 3: Prepare handoff summary**

Report:

- Files changed: `tests/test_failure_gallery.py`, `docs/failure-gallery.md`, `README.md`, `docs/ROADMAP.md`
- Verification run: focused gallery tests, `git diff --check`, Ruff format check, Ruff lint, mypy, full pytest
- Behavior changes: none
- Remaining v1 work: final documentation alignment pass
