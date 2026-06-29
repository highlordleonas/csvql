# CSVQL v0.6 Data Quality Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `csvql check` so CSVQL can run configured data-quality checks from `.csvql.yml`, report deterministic table or JSON results, include sampled failing rows or values on request, and exit non-zero when checks fail.

**Architecture:** Extend the existing project catalog schema to allow per-table `checks` while keeping config parsing strict. Add `quality.py` for typed check config/result objects, `checks.py` for DuckDB-controlled full-file validation queries, renderer functions in `output.py`, and a thin Typer command in `cli.py`. Keep user-authored SQL out of the check path; generated SQL is CSVQL-controlled and must quote table and column identifiers safely.

**Tech Stack:** Python 3.12, Typer, DuckDB, PyYAML, Rich, pytest, Ruff, mypy, uv.

---

## Scope And Constraints

- Implement these check types: `not_null`, `unique`, `accepted_values`, `min`, `max`, `row_count_between`, and single-column `foreign_key`.
- Configure checks only in `.csvql.yml`; do not add ad hoc CLI check definitions.
- Add `csvql check [TABLE] --output table|json --show-failures --failure-limit N`.
- Default `--output` remains `table`.
- Default `--failure-limit` is `5`; require `N >= 1`.
- Exit `0` when all configured checks pass or no checks are configured.
- Exit `11` when one or more checks fail.
- Preserve existing exit codes for missing files, invalid config, and DuckDB execution errors.
- Treat null child values as passing `foreign_key`; pair with `not_null` when required.
- Treat nulls as passing for `unique`, `accepted_values`, `min`, `max`, and `foreign_key`.
- Count `unique` failures with excess-row semantics: three equal non-null values contribute `2`.
- Count `row_count_between` failures as `0` in range, or the delta outside the nearest violated bound.
- Include sampled failures only with `--show-failures`.
- Do not claim sandbox safety, untrusted SQL safety, production readiness, large-file performance, timeout guarantees, cache/materialization, benchmark-backed speed, or v1 readiness.

## File Map

- Modify `src/csvql/exceptions.py`: add `DataQualityCheckFailure` with exit code `11`.
- Create `src/csvql/sql_utils.py`: shared `quote_identifier(identifier: str) -> str`.
- Modify `src/csvql/profiling.py`: import and use `quote_identifier`.
- Create `src/csvql/quality.py`: typed check specs, result objects, parsing helpers, and JSON serialization.
- Modify `src/csvql/project_config.py`: allow `checks` under each table, parse check specs, preserve save output for existing `csvql add` behavior.
- Create `src/csvql/checks.py`: DuckDB-backed check execution service.
- Modify `src/csvql/output.py`: add `format_check_result_json()` and `format_check_result_table()`.
- Modify `src/csvql/cli.py`: add thin `check` command and imports.
- Modify `README.md`: add check examples and move data-quality checks from planned to implemented.
- Modify `docs/ROADMAP.md`: mark v0.6 implemented details.
- Modify `docs/ARCHITECTURE.md`: document the check path, full-scan behavior, config-only surface, and trusted-local SQL boundary.
- Test `tests/test_sql_utils.py`: identifier quoting.
- Test `tests/test_quality.py`: typed result serialization and failure samples.
- Modify `tests/test_project_config.py`: config parsing and validation for checks.
- Test `tests/test_checks.py`: DuckDB validation semantics.
- Modify `tests/test_output.py`: check output renderers.
- Test `tests/test_cli_check.py`: CLI behavior, exit codes, catalog path resolution, table filter, JSON/table output, and failure samples.

## Check Config Contract

Use this schema in tests and docs:

```yaml
version: 1
tables:
  orders:
    path: data/orders.csv
    checks:
      - name: order_id_required
        type: not_null
        column: order_id
      - name: order_id_unique
        type: unique
        column: order_id
      - name: status_known
        type: accepted_values
        column: status
        values: [paid, pending, cancelled]
      - name: total_non_negative
        type: min
        column: total_amount
        value: 0
      - name: total_under_manual_review_limit
        type: max
        column: total_amount
        value: 10000
      - name: order_count_expected
        type: row_count_between
        min: 1
        max: 100000
      - name: customer_exists
        type: foreign_key
        column: customer_id
        references:
          table: customers
          column: customer_id
  customers:
    path: data/customers.csv
    checks:
      - name: customer_id_required
        type: not_null
        column: customer_id
```

Expected JSON shape:

```json
{
  "status": "failed",
  "check_count": 2,
  "passed_count": 1,
  "failed_count": 1,
  "checks": [
    {
      "name": "order_id_required",
      "table": "orders",
      "type": "not_null",
      "column": "order_id",
      "status": "failed",
      "failed_count": 1
    }
  ],
  "warnings": []
}
```

With `--show-failures`, failed checks include:

```json
{
  "failures": [
    {
      "row_number": 3,
      "value": null,
      "row": {
        "order_id": null,
        "customer_id": "CUST-2",
        "status": "paid"
      }
    }
  ]
}
```

For aggregate checks where a row sample is not meaningful, use a compact sample object:

```json
{
  "failures": [
    {
      "observed": 0,
      "min": 1,
      "max": 100000
    }
  ]
}
```

## Task 1: Shared SQL Identifier Quoting

**Files:**
- Create: `src/csvql/sql_utils.py`
- Modify: `src/csvql/profiling.py`
- Create: `tests/test_sql_utils.py`
- Test: `tests/test_profiling.py`

- [ ] **Step 1: Add failing tests for shared identifier quoting**

Create `tests/test_sql_utils.py`:

```python
from csvql.sql_utils import quote_identifier


def test_quote_identifier_wraps_and_escapes_duckdb_identifier() -> None:
    assert quote_identifier("order id") == '"order id"'
    assert quote_identifier("total-amount") == '"total-amount"'
    assert quote_identifier("select") == '"select"'
    assert quote_identifier('weird"name') == '"weird""name"'
```

- [ ] **Step 2: Run the focused failing test**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_sql_utils.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'csvql.sql_utils'`.

- [ ] **Step 3: Add `sql_utils.py`**

Create `src/csvql/sql_utils.py`:

```python
"""Small SQL-generation helpers for CSVQL-controlled DuckDB queries."""


def quote_identifier(identifier: str) -> str:
    """Return a DuckDB identifier quoted for generated CSVQL SQL."""

    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'
```

- [ ] **Step 4: Replace profiling's private quote helper**

In `src/csvql/profiling.py`, import the helper and replace each `_quote_identifier(...)` call:

```python
from csvql.sql_utils import quote_identifier
```

Then update generated SQL sites to use `quote_identifier(PROFILE_VIEW_NAME)` and `quote_identifier(column_name)`. Remove the private `_quote_identifier()` function at the bottom of the file.

- [ ] **Step 5: Verify focused tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_sql_utils.py tests/test_profiling.py -v`

Expected: PASS.

- [ ] **Step 6: Commit shared SQL helper**

```bash
git add src/csvql/sql_utils.py src/csvql/profiling.py tests/test_sql_utils.py
git commit -m "refactor: share DuckDB identifier quoting"
```

## Task 2: Quality Models And Serialization

**Files:**
- Create: `src/csvql/quality.py`
- Create: `tests/test_quality.py`

- [ ] **Step 1: Add failing serialization tests**

Create `tests/test_quality.py`:

```python
from csvql.quality import (
    CheckFailureSample,
    CheckResult,
    CheckRunResult,
    ConfiguredCheck,
    ForeignKeyReference,
)


def test_configured_check_as_dict_includes_reference_when_present() -> None:
    check = ConfiguredCheck(
        name="customer_exists",
        table="orders",
        type="foreign_key",
        column="customer_id",
        values=(),
        value=None,
        min_value=None,
        max_value=None,
        references=ForeignKeyReference(table="customers", column="customer_id"),
    )

    assert check.as_dict() == {
        "name": "customer_exists",
        "table": "orders",
        "type": "foreign_key",
        "column": "customer_id",
        "references": {"table": "customers", "column": "customer_id"},
    }


def test_check_run_result_as_dict_omits_failures_when_not_requested() -> None:
    result = CheckRunResult(
        status="failed",
        checks=(
            CheckResult(
                name="order_id_required",
                table="orders",
                type="not_null",
                column="order_id",
                status="failed",
                failed_count=1,
                failures=(
                    CheckFailureSample(
                        row_number=2,
                        value=None,
                        row={"order_id": None, "status": "paid"},
                    ),
                ),
            ),
        ),
        warnings=(),
    )

    assert result.as_dict(include_failures=False) == {
        "status": "failed",
        "check_count": 1,
        "passed_count": 0,
        "failed_count": 1,
        "checks": [
            {
                "name": "order_id_required",
                "table": "orders",
                "type": "not_null",
                "column": "order_id",
                "status": "failed",
                "failed_count": 1,
            }
        ],
        "warnings": [],
    }


def test_check_run_result_as_dict_includes_failures_when_requested() -> None:
    result = CheckRunResult(
        status="failed",
        checks=(
            CheckResult(
                name="order_id_required",
                table="orders",
                type="not_null",
                column="order_id",
                status="failed",
                failed_count=1,
                failures=(
                    CheckFailureSample(
                        row_number=2,
                        value=None,
                        row={"order_id": None, "status": "paid"},
                    ),
                ),
            ),
        ),
        warnings=(),
    )

    check_payload = result.as_dict(include_failures=True)["checks"][0]

    assert check_payload["failures"] == [
        {
            "row_number": 2,
            "value": None,
            "row": {"order_id": None, "status": "paid"},
        }
    ]
```

- [ ] **Step 2: Run the focused failing tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_quality.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'csvql.quality'`.

- [ ] **Step 3: Add typed quality dataclasses**

Create `src/csvql/quality.py`:

```python
"""Typed data-quality check configuration and results."""

from dataclasses import dataclass
from typing import Literal

CheckType = Literal[
    "not_null",
    "unique",
    "accepted_values",
    "min",
    "max",
    "row_count_between",
    "foreign_key",
]
CheckStatus = Literal["passed", "failed"]
RunStatus = Literal["passed", "failed"]


@dataclass(frozen=True, slots=True)
class ForeignKeyReference:
    """Single-column foreign-key target from project config."""

    table: str
    column: str

    def as_dict(self) -> dict[str, str]:
        return {
            "table": self.table,
            "column": self.column,
        }


@dataclass(frozen=True, slots=True)
class ConfiguredCheck:
    """Validated data-quality check from `.csvql.yml`."""

    name: str
    table: str
    type: CheckType
    column: str | None
    values: tuple[object, ...]
    value: object | None
    min_value: object | None
    max_value: object | None
    references: ForeignKeyReference | None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "table": self.table,
            "type": self.type,
        }
        if self.column is not None:
            payload["column"] = self.column
        if self.values:
            payload["values"] = list(self.values)
        if self.value is not None:
            payload["value"] = self.value
        if self.min_value is not None:
            payload["min"] = self.min_value
        if self.max_value is not None:
            payload["max"] = self.max_value
        if self.references is not None:
            payload["references"] = self.references.as_dict()
        return payload


@dataclass(frozen=True, slots=True)
class CheckFailureSample:
    """One sampled failure for verbose check output."""

    row_number: int | None = None
    value: object | None = None
    row: dict[str, object] | None = None
    observed: object | None = None
    expected: object | None = None
    min_value: object | None = None
    max_value: object | None = None
    reference_table: str | None = None
    reference_column: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.row_number is not None:
            payload["row_number"] = self.row_number
        if self.value is not None or self.row is not None:
            payload["value"] = self.value
        if self.row is not None:
            payload["row"] = self.row
        if self.observed is not None:
            payload["observed"] = self.observed
        if self.expected is not None:
            payload["expected"] = self.expected
        if self.min_value is not None:
            payload["min"] = self.min_value
        if self.max_value is not None:
            payload["max"] = self.max_value
        if self.reference_table is not None:
            payload["reference_table"] = self.reference_table
        if self.reference_column is not None:
            payload["reference_column"] = self.reference_column
        return payload


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Result for one configured data-quality check."""

    name: str
    table: str
    type: CheckType
    column: str | None
    status: CheckStatus
    failed_count: int
    failures: tuple[CheckFailureSample, ...] = ()

    def as_dict(self, *, include_failures: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "table": self.table,
            "type": self.type,
            "status": self.status,
            "failed_count": self.failed_count,
        }
        if self.column is not None:
            payload["column"] = self.column
        if include_failures and self.failures:
            payload["failures"] = [failure.as_dict() for failure in self.failures]
        return payload


@dataclass(frozen=True, slots=True)
class CheckRunResult:
    """Aggregate result for a `csvql check` invocation."""

    status: RunStatus
    checks: tuple[CheckResult, ...]
    warnings: tuple[str, ...]

    @property
    def check_count(self) -> int:
        return len(self.checks)

    @property
    def failed_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "failed")

    @property
    def passed_count(self) -> int:
        return self.check_count - self.failed_count

    def as_dict(self, *, include_failures: bool) -> dict[str, object]:
        return {
            "status": self.status,
            "check_count": self.check_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "checks": [
                check.as_dict(include_failures=include_failures)
                for check in self.checks
            ],
            "warnings": list(self.warnings),
        }
```

- [ ] **Step 4: Verify focused tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_quality.py -v`

Expected: PASS.

- [ ] **Step 5: Commit quality model foundation**

```bash
git add src/csvql/quality.py tests/test_quality.py
git commit -m "feat: add data quality result models"
```

## Task 3: Project Config Check Parsing

**Files:**
- Modify: `src/csvql/project_config.py`
- Modify: `tests/test_project_config.py`

- [ ] **Step 1: Add failing config parser tests**

Append to `tests/test_project_config.py`:

```python
def test_load_project_accepts_table_checks(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        """
version: 1
tables:
  orders:
    path: data/orders.csv
    checks:
      - name: order_id_required
        type: not_null
        column: order_id
      - name: status_known
        type: accepted_values
        column: status
        values: [paid, pending]
      - name: expected_rows
        type: row_count_between
        min: 1
        max: 10
      - name: customer_exists
        type: foreign_key
        column: customer_id
        references:
          table: customers
          column: customer_id
  customers:
    path: data/customers.csv
""",
        encoding="utf-8",
    )

    context = load_project(tmp_path)

    orders = context.config.tables[0]
    assert orders.name == "orders"
    assert [check.name for check in orders.checks] == [
        "order_id_required",
        "status_known",
        "expected_rows",
        "customer_exists",
    ]
    assert orders.checks[1].values == ("paid", "pending")
    assert orders.checks[2].min_value == 1
    assert orders.checks[2].max_value == 10
    assert orders.checks[3].references is not None
    assert orders.checks[3].references.table == "customers"


@pytest.mark.parametrize(
    "check_yaml",
    [
        "checks: {}\n",
        "checks:\n  - type: not_null\n    column: order_id\n",
        "checks:\n  - name: bad\n    column: order_id\n",
        "checks:\n  - name: bad name\n    type: not_null\n    column: order_id\n",
        "checks:\n  - name: bad\n    type: not_null\n",
        "checks:\n  - name: bad\n    type: accepted_values\n    column: status\n    values: []\n",
        "checks:\n  - name: bad\n    type: row_count_between\n",
        "checks:\n  - name: bad\n    type: row_count_between\n    min: 10\n    max: 1\n",
        "checks:\n  - name: bad\n    type: foreign_key\n    column: customer_id\n",
        "checks:\n  - name: bad\n    type: foreign_key\n    column: customer_id\n    references: {table: customers}\n",
    ],
)
def test_load_project_rejects_invalid_table_checks(
    tmp_path: Path,
    check_yaml: str,
) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n    "
        + check_yaml.replace("\n", "\n    "),
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


def test_save_project_preserves_checks_when_replacing_unrelated_table(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    orders_path = project_root / "orders.csv"
    customers_path = project_root / "customers.csv"
    project_root.mkdir()
    orders_path.write_text("order_id\nORD-1\n", encoding="utf-8")
    customers_path.write_text("customer_id\nCUST-1\n", encoding="utf-8")
    config_path = project_root / CONFIG_FILENAME
    config_path.write_text(
        """
version: 1
tables:
  orders:
    path: orders.csv
    checks:
      - name: order_id_required
        type: not_null
        column: order_id
  customers:
    path: customers.csv
""",
        encoding="utf-8",
    )
    context = load_project(project_root)

    updated_context = add_project_table(
        context,
        "customers",
        "customers.csv",
        replace=True,
        invocation_dir=project_root,
    )

    orders = next(table for table in updated_context.config.tables if table.name == "orders")
    assert [check.name for check in orders.checks] == ["order_id_required"]
```

- [ ] **Step 2: Run focused failing tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_project_config.py -v`

Expected: FAIL because `ProjectTable` has no `checks` field and `checks` is rejected as unsupported metadata.

- [ ] **Step 3: Extend `ProjectTable` and payload saving**

In `src/csvql/project_config.py`, add:

```python
from csvql.quality import ConfiguredCheck, ForeignKeyReference
```

Update `ProjectTable`:

```python
@dataclass(frozen=True, slots=True)
class ProjectTable:
    """A project catalog table entry."""

    name: str
    path: str
    checks: tuple[ConfiguredCheck, ...] = ()
```

Update `_project_config_payload()` so checks are emitted only when present:

```python
    tables_payload: dict[str, dict[str, object]] = {}
    for table in sorted(config.tables, key=lambda table: table.name):
        table_payload: dict[str, object] = {"path": table.path}
        if table.checks:
            table_payload["checks"] = [_check_config_payload(check) for check in table.checks]
        tables_payload[table.name] = table_payload
```

Add this helper:

```python
def _check_config_payload(check: ConfiguredCheck) -> dict[str, object]:
    payload = check.as_dict()
    payload.pop("table", None)
    return payload
```

- [ ] **Step 4: Parse and validate checks**

In `_parse_project_table_entry()`, change:

```python
    allowed_keys = {"path", "checks"}
```

After validating `raw_path`, parse checks:

```python
    raw_checks = raw_table.get("checks", [])
    checks = _parse_table_checks(name, raw_checks, config_path=config_path)

    return ProjectTable(name=name, path=raw_path, checks=checks)
```

Add these helpers below `_parse_project_table_entry()`:

```python
def _parse_table_checks(
    table_name: str,
    raw_checks: object,
    *,
    config_path: Path,
) -> tuple[ConfiguredCheck, ...]:
    if raw_checks is None:
        return ()
    if not isinstance(raw_checks, list):
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' checks in {config_path} must be a list.",
            suggestion="Use checks: [] or a list of check mappings.",
        )

    return tuple(
        _parse_table_check(table_name, raw_check, config_path=config_path)
        for raw_check in raw_checks
    )


def _parse_table_check(
    table_name: str,
    raw_check: object,
    *,
    config_path: Path,
) -> ConfiguredCheck:
    if not isinstance(raw_check, dict):
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' checks in {config_path} must be mappings.",
            suggestion="Use check entries with name and type fields.",
        )
    raw_name = raw_check.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' has a check without a valid name.",
            suggestion="Set a non-empty check name using letters, numbers, and underscores.",
        )
    try:
        check_name = validate_table_alias(raw_name)
    except TableMappingError as exc:
        raise ProjectConfigError(
            f"Invalid check name '{raw_name}' for table '{table_name}' in {config_path}.",
            suggestion="Use letters, numbers, and underscores; start with a letter or underscore.",
        ) from exc

    raw_type = raw_check.get("type")
    if not isinstance(raw_type, str):
        raise ProjectConfigError(
            f"Project catalog check '{check_name}' in {config_path} must have a string type.",
            suggestion="Use one of: not_null, unique, accepted_values, min, max, row_count_between, foreign_key.",
        )
    check_type = raw_type
    if check_type not in {
        "not_null",
        "unique",
        "accepted_values",
        "min",
        "max",
        "row_count_between",
        "foreign_key",
    }:
        raise ProjectConfigError(
            f"Unsupported check type '{raw_type}' for check '{check_name}' in {config_path}.",
            suggestion="Use one of: not_null, unique, accepted_values, min, max, row_count_between, foreign_key.",
        )

    column = _parse_optional_column(raw_check, table_name, check_name, check_type, config_path)
    values = _parse_values(raw_check, table_name, check_name, check_type, config_path)
    value = _parse_scalar_value(raw_check, table_name, check_name, check_type, config_path)
    min_value, max_value = _parse_row_count_bounds(
        raw_check,
        table_name,
        check_name,
        check_type,
        config_path,
    )
    references = _parse_foreign_key_reference(
        raw_check,
        table_name,
        check_name,
        check_type,
        config_path,
    )

    return ConfiguredCheck(
        name=check_name,
        table=table_name,
        type=check_type,  # type: ignore[arg-type]
        column=column,
        values=values,
        value=value,
        min_value=min_value,
        max_value=max_value,
        references=references,
    )
```

Add focused helper functions for column, values, scalar value, row-count bounds, and FK reference. Required rules:

```python
COLUMN_CHECK_TYPES = {"not_null", "unique", "accepted_values", "min", "max", "foreign_key"}


def _parse_optional_column(
    raw_check: dict[object, object],
    table_name: str,
    check_name: str,
    check_type: str,
    config_path: Path,
) -> str | None:
    raw_column = raw_check.get("column")
    if check_type in COLUMN_CHECK_TYPES:
        if not isinstance(raw_column, str) or not raw_column.strip():
            raise ProjectConfigError(
                f"Check '{check_name}' on table '{table_name}' in {config_path} requires a column.",
                suggestion="Set column to the CSV header name to validate.",
            )
        return raw_column
    if raw_column is not None:
        raise ProjectConfigError(
            f"Check '{check_name}' on table '{table_name}' in {config_path} must not set column.",
            suggestion="Remove column from row_count_between checks.",
        )
    return None
```

The other helpers must enforce:

- `accepted_values` requires non-empty `values` list.
- `min` and `max` require `value`.
- `row_count_between` accepts `min`, `max`, or both; at least one is required.
- `row_count_between` integer bounds must be non-negative.
- `row_count_between` with both bounds must have `min <= max`.
- `foreign_key` requires `references.table` and `references.column` strings.
- Checks reject unsupported keys with a message naming the check.

- [ ] **Step 5: Preserve checks when adding or replacing tables**

In `add_project_table()`, when replacing an existing table, preserve existing checks unless the function grows an explicit check-editing surface:

```python
    existing_checks: tuple[ConfiguredCheck, ...] = ()
    if existing_index is not None:
        existing_checks = tables[existing_index].checks
    updated_table = ProjectTable(name=table_name, path=stored_path, checks=existing_checks)
```

Keep newly added tables with `checks=()`.

- [ ] **Step 6: Verify focused config tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_project_config.py -v`

Expected: PASS.

- [ ] **Step 7: Commit config parsing**

```bash
git add src/csvql/project_config.py tests/test_project_config.py
git commit -m "feat: parse configured data quality checks"
```

## Task 4: DuckDB Check Execution Core

**Files:**
- Create: `src/csvql/checks.py`
- Create: `tests/test_checks.py`

- [ ] **Step 1: Add failing execution tests for core checks**

Create `tests/test_checks.py`:

```python
from pathlib import Path

import pytest

from csvql.checks import run_configured_checks
from csvql.exceptions import CSVInspectionError, ProjectConfigError
from csvql.project_config import (
    CONFIG_FILENAME,
    ProjectConfig,
    ProjectContext,
    ProjectTable,
)
from csvql.quality import ConfiguredCheck, ForeignKeyReference


def _context(project_root: Path, tables: tuple[ProjectTable, ...]) -> ProjectContext:
    return ProjectContext(
        project_root=project_root.resolve(),
        config_path=(project_root / CONFIG_FILENAME).resolve(),
        config=ProjectConfig(version=1, tables=tables),
    )


def _check(
    name: str,
    table: str,
    type_value: str,
    *,
    column: str | None = None,
    values: tuple[object, ...] = (),
    value: object | None = None,
    min_value: object | None = None,
    max_value: object | None = None,
    references: ForeignKeyReference | None = None,
) -> ConfiguredCheck:
    return ConfiguredCheck(
        name=name,
        table=table,
        type=type_value,  # type: ignore[arg-type]
        column=column,
        values=values,
        value=value,
        min_value=min_value,
        max_value=max_value,
        references=references,
    )


def test_run_configured_checks_returns_warning_for_zero_checks(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(tmp_path, (ProjectTable("orders", "orders.csv"),))

    result = run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    assert result.status == "passed"
    assert result.check_count == 0
    assert result.warnings == ("No data quality checks configured.",)


def test_run_configured_checks_validates_not_null_unique_values_and_row_count(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text(
        "order_id,status,total_amount\n"
        "ORD-1,paid,10\n"
        "ORD-2,unknown,20\n"
        "ORD-2,,30\n"
        ",paid,40\n",
        encoding="utf-8",
    )
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check("order_id_required", "orders", "not_null", column="order_id"),
                    _check("order_id_unique", "orders", "unique", column="order_id"),
                    _check(
                        "status_known",
                        "orders",
                        "accepted_values",
                        column="status",
                        values=("paid", "pending"),
                    ),
                    _check(
                        "expected_rows",
                        "orders",
                        "row_count_between",
                        min_value=5,
                        max_value=10,
                    ),
                ),
            ),
        ),
    )

    result = run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    failures = {check.name: check.failed_count for check in result.checks}
    assert result.status == "failed"
    assert failures == {
        "order_id_required": 1,
        "order_id_unique": 1,
        "status_known": 1,
        "expected_rows": 1,
    }


def test_run_configured_checks_validates_min_max_and_ignores_nulls(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text(
        "order_id,total_amount\nORD-1,-1\nORD-2,100\nORD-3,\n",
        encoding="utf-8",
    )
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check("total_non_negative", "orders", "min", column="total_amount", value=0),
                    _check("total_under_limit", "orders", "max", column="total_amount", value=50),
                ),
            ),
        ),
    )

    result = run_configured_checks(context, table_name="orders", show_failures=False, failure_limit=5)

    assert [(check.name, check.failed_count) for check in result.checks] == [
        ("total_non_negative", 1),
        ("total_under_limit", 1),
    ]


def test_run_configured_checks_validates_foreign_key_and_ignores_null_child(
    tmp_path: Path,
) -> None:
    (tmp_path / "orders.csv").write_text(
        "order_id,customer_id\nORD-1,CUST-1\nORD-2,CUST-MISSING\nORD-3,\n",
        encoding="utf-8",
    )
    (tmp_path / "customers.csv").write_text("customer_id\nCUST-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "customer_exists",
                        "orders",
                        "foreign_key",
                        column="customer_id",
                        references=ForeignKeyReference("customers", "customer_id"),
                    ),
                ),
            ),
            ProjectTable("customers", "customers.csv"),
        ),
    )

    result = run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    assert result.checks[0].failed_count == 1


def test_run_configured_checks_includes_capped_failure_samples(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text(
        "order_id,status\n,paid\n,unknown\nORD-1,unknown\n",
        encoding="utf-8",
    )
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(_check("order_id_required", "orders", "not_null", column="order_id"),),
            ),
        ),
    )

    result = run_configured_checks(context, table_name=None, show_failures=True, failure_limit=1)

    assert result.checks[0].failed_count == 2
    assert len(result.checks[0].failures) == 1
    assert result.checks[0].failures[0].row_number == 1
    assert result.checks[0].failures[0].row == {"order_id": None, "status": "paid"}


def test_run_configured_checks_rejects_unknown_table_filter(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(tmp_path, (ProjectTable("orders", "orders.csv"),))

    with pytest.raises(ProjectConfigError):
        run_configured_checks(context, table_name="missing", show_failures=False, failure_limit=5)


def test_run_configured_checks_wraps_missing_file_after_catalog_resolution(
    tmp_path: Path,
) -> None:
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "missing.csv",
                checks=(_check("order_id_required", "orders", "not_null", column="order_id"),),
            ),
        ),
    )

    with pytest.raises(CSVInspectionError) as exc_info:
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    assert "Failed to run data quality checks for project catalog table 'orders'" in str(exc_info.value)
```

- [ ] **Step 2: Run the focused failing tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_checks.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'csvql.checks'`.

- [ ] **Step 3: Implement `checks.py` service skeleton**

Create `src/csvql/checks.py`:

```python
"""DuckDB-backed data-quality check execution."""

from collections.abc import Iterable

import duckdb

from csvql.exceptions import CSVInspectionError, ProjectConfigError
from csvql.project_config import ProjectContext, ProjectTable, resolve_catalog_path
from csvql.quality import CheckFailureSample, CheckResult, CheckRunResult, ConfiguredCheck
from csvql.sql_utils import quote_identifier

CHECK_VIEW_PREFIX = "__csvql_check_"


def run_configured_checks(
    context: ProjectContext,
    *,
    table_name: str | None,
    show_failures: bool,
    failure_limit: int,
) -> CheckRunResult:
    """Run configured data-quality checks from a project catalog."""

    selected_tables = _select_tables(context, table_name)
    checks = tuple(check for table in selected_tables for check in table.checks)
    if not checks:
        warning = (
            f"No data quality checks configured for table '{table_name}'."
            if table_name is not None
            else "No data quality checks configured."
        )
        return CheckRunResult(status="passed", checks=(), warnings=(warning,))

    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = duckdb.connect(database=":memory:")
        _register_tables(connection, context, _required_tables(context, selected_tables))
        results = tuple(
            _run_check(connection, check, show_failures=show_failures, failure_limit=failure_limit)
            for check in checks
        )
    except CSVInspectionError:
        raise
    except duckdb.Error as exc:
        raise CSVInspectionError(
            "Failed to run data quality checks.",
            suggestion="Check that configured columns exist and values compare cleanly with DuckDB-inferred CSV types.",
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    status = "failed" if any(result.status == "failed" for result in results) else "passed"
    return CheckRunResult(status=status, checks=results, warnings=())
```

- [ ] **Step 4: Implement table selection and registration**

Add:

```python
def _select_tables(
    context: ProjectContext,
    table_name: str | None,
) -> tuple[ProjectTable, ...]:
    tables = tuple(sorted(context.config.tables, key=lambda table: table.name))
    if table_name is None:
        return tables
    match = next((table for table in tables if table.name.lower() == table_name.lower()), None)
    if match is None:
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' was not found in {context.config_path}.",
            suggestion="Run csvql tables to list configured table aliases.",
        )
    return (match,)


def _required_tables(
    context: ProjectContext,
    selected_tables: tuple[ProjectTable, ...],
) -> tuple[ProjectTable, ...]:
    required_names = {table.name.lower() for table in selected_tables}
    for table in selected_tables:
        for check in table.checks:
            if check.references is not None:
                required_names.add(check.references.table.lower())
    required_tables: list[ProjectTable] = []
    for required_name in sorted(required_names):
        table = next(
            (candidate for candidate in context.config.tables if candidate.name.lower() == required_name),
            None,
        )
        if table is None:
            raise ProjectConfigError(
                f"Referenced project catalog table '{required_name}' was not found in {context.config_path}.",
                suggestion="Add the referenced table to .csvql.yml before running csvql check.",
            )
        required_tables.append(table)
    return tuple(required_tables)


def _register_tables(
    connection: duckdb.DuckDBPyConnection,
    context: ProjectContext,
    tables: Iterable[ProjectTable],
) -> None:
    for table in tables:
        try:
            resolved_path = resolve_catalog_path(table, context)
            relation = connection.read_csv(str(resolved_path), auto_detect=True, header=True)
            relation.create_view(_view_name(table.name), replace=True)
        except (OSError, duckdb.Error) as exc:
            raise CSVInspectionError(
                f"Failed to run data quality checks for project catalog table '{table.name}'.",
                suggestion="Check that the configured CSV file exists and is readable.",
            ) from exc


def _view_name(table_name: str) -> str:
    return f"{CHECK_VIEW_PREFIX}{table_name.lower()}"
```

- [ ] **Step 5: Implement check dispatch and counts**

Add:

```python
def _run_check(
    connection: duckdb.DuckDBPyConnection,
    check: ConfiguredCheck,
    *,
    show_failures: bool,
    failure_limit: int,
) -> CheckResult:
    failed_count = _failed_count(connection, check)
    failures = (
        _failure_samples(connection, check, limit=failure_limit)
        if show_failures and failed_count > 0
        else ()
    )
    return CheckResult(
        name=check.name,
        table=check.table,
        type=check.type,
        column=check.column,
        status="failed" if failed_count else "passed",
        failed_count=failed_count,
        failures=failures,
    )


def _failed_count(connection: duckdb.DuckDBPyConnection, check: ConfiguredCheck) -> int:
    if check.type == "not_null":
        return _fetch_scalar_int(connection, _not_null_count_sql(check))
    if check.type == "unique":
        return _fetch_scalar_int(connection, _unique_count_sql(check))
    if check.type == "accepted_values":
        return _fetch_scalar_int(connection, _accepted_values_count_sql(check))
    if check.type == "min":
        return _fetch_scalar_int(connection, _min_count_sql(check))
    if check.type == "max":
        return _fetch_scalar_int(connection, _max_count_sql(check))
    if check.type == "row_count_between":
        return _row_count_between_failure_count(connection, check)
    if check.type == "foreign_key":
        return _fetch_scalar_int(connection, _foreign_key_count_sql(check))
    raise AssertionError(f"Unhandled check type: {check.type}")
```

- [ ] **Step 6: Implement generated SQL helpers**

Use `quote_identifier()` for every view and column name. Use DuckDB parameters for configured scalar/list values.

Required predicates:

```python
def _not_null_count_sql(check: ConfiguredCheck) -> str:
    return (
        f"SELECT count(*) FROM {quote_identifier(_view_name(check.table))} "
        f"WHERE {quote_identifier(check.column or '')} IS NULL"
    )
```

For checks with configured values, prefer parameterized execution helpers:

```python
def _fetch_scalar_int(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: tuple[object, ...] = (),
) -> int:
    row = connection.execute(query, parameters).fetchone()
    if row is None:
        return 0
    return int(row[0] or 0)
```

Implement counts with these semantics:

- `unique`: group by column where column is not null, sum `count(*) - 1` for duplicate groups.
- `accepted_values`: `column IS NOT NULL AND column NOT IN (?, ?, ...)`.
- `min`: `column IS NOT NULL AND column < ?`.
- `max`: `column IS NOT NULL AND column > ?`.
- `row_count_between`: fetch `count(*)`, return `min - row_count`, `row_count - max`, or `0`.
- `foreign_key`: left anti join child to parent where child column is not null.

- [ ] **Step 7: Implement failure sample queries**

Implement `_failure_samples()` so:

- row-level checks return `CheckFailureSample(row_number=<1-based row_number()>, value=<bad value>, row=<full row dict>)`.
- `unique` samples duplicate non-null values with an `observed` count.
- `row_count_between` returns one aggregate sample with observed row count and bounds.
- `foreign_key` samples child rows whose non-null key is absent from parent.

Use a wrapper query for row-level samples:

```sql
SELECT *
FROM (
  SELECT row_number() OVER () AS __csvql_row_number, *
  FROM "view_name"
)
WHERE <failure predicate>
LIMIT ?
```

Build row dictionaries from `cursor.description` and row tuples, excluding `__csvql_row_number` from the nested `row`.

- [ ] **Step 8: Verify focused check tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_checks.py -v`

Expected: PASS.

- [ ] **Step 9: Commit check execution core**

```bash
git add src/csvql/checks.py tests/test_checks.py
git commit -m "feat: run configured data quality checks"
```

## Task 5: Output Renderers

**Files:**
- Modify: `src/csvql/output.py`
- Modify: `tests/test_output.py`

- [ ] **Step 1: Add failing output tests**

Append to `tests/test_output.py`:

```python
from csvql.quality import CheckFailureSample, CheckResult, CheckRunResult
from csvql.output import format_check_result_json, format_check_result_table


def test_format_check_result_json_is_deterministic_without_failures() -> None:
    result = CheckRunResult(
        status="failed",
        checks=(
            CheckResult(
                name="order_id_required",
                table="orders",
                type="not_null",
                column="order_id",
                status="failed",
                failed_count=1,
                failures=(CheckFailureSample(row_number=2, value=None, row={"order_id": None}),),
            ),
        ),
        warnings=(),
    )

    payload = json.loads(format_check_result_json(result, include_failures=False))

    assert payload["status"] == "failed"
    assert payload["check_count"] == 1
    assert "failures" not in payload["checks"][0]


def test_format_check_result_json_includes_failures_when_requested() -> None:
    result = CheckRunResult(
        status="failed",
        checks=(
            CheckResult(
                name="order_id_required",
                table="orders",
                type="not_null",
                column="order_id",
                status="failed",
                failed_count=1,
                failures=(CheckFailureSample(row_number=2, value=None, row={"order_id": None}),),
            ),
        ),
        warnings=(),
    )

    payload = json.loads(format_check_result_json(result, include_failures=True))

    assert payload["checks"][0]["failures"] == [
        {"row_number": 2, "value": None, "row": {"order_id": None}}
    ]


def test_format_check_result_table_contains_status_counts_and_failures() -> None:
    result = CheckRunResult(
        status="failed",
        checks=(
            CheckResult(
                name="order_id_required",
                table="orders",
                type="not_null",
                column="order_id",
                status="failed",
                failed_count=1,
                failures=(CheckFailureSample(row_number=2, value=None, row={"order_id": None}),),
            ),
        ),
        warnings=("No data quality checks configured for table 'customers'.",),
    )

    output = format_check_result_table(result, include_failures=True)

    assert "Status: failed" in output
    assert "Checks: 1" in output
    assert "order_id_required" in output
    assert "Failures:" in output
    assert "row_number=2" in output
    assert "Warnings:" in output
```

- [ ] **Step 2: Run focused failing output tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_output.py -v`

Expected: FAIL because the check renderers are not defined.

- [ ] **Step 3: Add JSON renderer**

In `src/csvql/output.py`, import:

```python
from csvql.quality import CheckRunResult
```

Add:

```python
def format_check_result_json(
    result: CheckRunResult,
    *,
    include_failures: bool,
) -> str:
    """Format a data-quality check result as deterministic JSON."""

    return json.dumps(
        result.as_dict(include_failures=include_failures),
        default=str,
        indent=2,
        sort_keys=True,
    )
```

- [ ] **Step 4: Add table renderer**

Add:

```python
def format_check_result_table(
    result: CheckRunResult,
    *,
    include_failures: bool,
) -> str:
    """Format a data-quality check result as Rich table text."""

    console = Console(color_system=None, force_terminal=False, record=True, width=140)
    console.print(f"Status: {result.status}")
    console.print(
        f"Checks: {result.check_count} | Passed: {result.passed_count} | Failed: {result.failed_count}"
    )

    table = Table(show_header=True)
    table.add_column("table")
    table.add_column("check")
    table.add_column("type")
    table.add_column("column")
    table.add_column("status")
    table.add_column("failed")
    for check in result.checks:
        table.add_row(
            check.table,
            check.name,
            check.type,
            check.column or "",
            check.status,
            str(check.failed_count),
        )
    console.print(table)

    if include_failures:
        _print_check_failures(console, result)
    if result.warnings:
        console.print("Warnings:")
        for warning in result.warnings:
            console.print(f"- {warning}")
    return console.export_text(clear=True)
```

Add:

```python
def _print_check_failures(console: Console, result: CheckRunResult) -> None:
    failure_lines: list[str] = []
    for check in result.checks:
        for failure in check.failures:
            details = ", ".join(
                f"{key}={_format_cell(value)}"
                for key, value in failure.as_dict().items()
            )
            failure_lines.append(f"{check.table}.{check.name}: {details}")
    if failure_lines:
        console.print("Failures:")
        for line in failure_lines:
            console.print(f"- {line}")
```

- [ ] **Step 5: Verify output tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_output.py -v`

Expected: PASS.

- [ ] **Step 6: Commit renderers**

```bash
git add src/csvql/output.py tests/test_output.py
git commit -m "feat: render data quality check results"
```

## Task 6: CLI Command And Exit Codes

**Files:**
- Modify: `src/csvql/exceptions.py`
- Modify: `src/csvql/cli.py`
- Create: `tests/test_cli_check.py`

- [ ] **Step 1: Add failing CLI tests**

Create `tests/test_cli_check.py`:

```python
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql.cli import app
from csvql.project_config import CONFIG_FILENAME

runner = CliRunner()


def _write_project(tmp_path: Path, config_body: str) -> None:
    (tmp_path / CONFIG_FILENAME).write_text(config_body, encoding="utf-8")


def test_check_returns_zero_for_passing_checks_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "orders.csv").write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    _write_project(
        tmp_path,
        """
version: 1
tables:
  orders:
    path: orders.csv
    checks:
      - name: order_id_required
        type: not_null
        column: order_id
""",
    )

    result = runner.invoke(app, ["check", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "passed"
    assert payload["check_count"] == 1
    assert payload["failed_count"] == 0


def test_check_returns_exit_11_for_failed_checks_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "orders.csv").write_text("order_id,status\n,paid\n", encoding="utf-8")
    _write_project(
        tmp_path,
        """
version: 1
tables:
  orders:
    path: orders.csv
    checks:
      - name: order_id_required
        type: not_null
        column: order_id
""",
    )

    result = runner.invoke(app, ["check"])

    assert result.exit_code == 11
    assert "Status: failed" in result.output
    assert "order_id_required" in result.output


def test_check_table_filter_matches_case_insensitively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "orders.csv").write_text("order_id\nORD-1\n", encoding="utf-8")
    _write_project(
        tmp_path,
        """
version: 1
tables:
  Orders:
    path: orders.csv
    checks:
      - name: order_id_required
        type: not_null
        column: order_id
""",
    )

    result = runner.invoke(app, ["check", "orders", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["checks"][0]["table"] == "Orders"


def test_check_show_failures_includes_sampled_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "orders.csv").write_text("order_id,status\n,paid\n,paid\n", encoding="utf-8")
    _write_project(
        tmp_path,
        """
version: 1
tables:
  orders:
    path: orders.csv
    checks:
      - name: order_id_required
        type: not_null
        column: order_id
""",
    )

    result = runner.invoke(
        app,
        ["check", "--output", "json", "--show-failures", "--failure-limit", "1"],
    )

    assert result.exit_code == 11
    payload = json.loads(result.output)
    assert len(payload["checks"][0]["failures"]) == 1
    assert payload["checks"][0]["failures"][0]["row"] == {
        "order_id": None,
        "status": "paid",
    }


def test_check_missing_catalog_uses_project_config_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check"])

    assert result.exit_code == 8
    assert "No .csvql.yml project catalog found" in result.output


def test_check_missing_file_uses_existing_file_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_project(
        tmp_path,
        """
version: 1
tables:
  orders:
    path: missing.csv
    checks:
      - name: order_id_required
        type: not_null
        column: order_id
""",
    )

    result = runner.invoke(app, ["check"])

    assert result.exit_code == 7
    assert "Failed to run data quality checks for project catalog table 'orders'" in result.output
```

- [ ] **Step 2: Run focused failing CLI tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_check.py -v`

Expected: FAIL because `csvql check` is not registered.

- [ ] **Step 3: Add data-quality failure exception**

In `src/csvql/exceptions.py`, add:

```python
class DataQualityCheckFailure(CSVQLError):
    """Raised when configured data-quality checks fail."""

    exit_code = 11
```

- [ ] **Step 4: Wire thin CLI command**

In `src/csvql/cli.py`, import:

```python
from csvql.checks import run_configured_checks
from csvql.exceptions import CSVQLError, DataQualityCheckFailure
from csvql.output import (
    OutputFormat,
    format_check_result_json,
    format_check_result_table,
    ...
)
```

Add command near `profile`:

```python
@app.command()
def check(
    table_name: Annotated[
        str | None,
        typer.Argument(help="Optional project catalog table alias to check."),
    ] = None,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="Data-quality check output format.",
        ),
    ] = OutputFormat.table,
    show_failures: Annotated[
        bool,
        typer.Option(
            "--show-failures",
            help="Include sampled failing rows or values in output.",
        ),
    ] = False,
    failure_limit: Annotated[
        int,
        typer.Option(
            "--failure-limit",
            min=1,
            help="Maximum sampled failures per failed check.",
        ),
    ] = 5,
) -> None:
    """Run configured data-quality checks from the project catalog."""

    try:
        context = load_project()
        result = run_configured_checks(
            context,
            table_name=table_name,
            show_failures=show_failures,
            failure_limit=failure_limit,
        )
        if output is OutputFormat.json:
            typer.echo(format_check_result_json(result, include_failures=show_failures))
        else:
            typer.echo(format_check_result_table(result, include_failures=show_failures), nl=False)
        if result.status == "failed":
            raise DataQualityCheckFailure("Configured data-quality checks failed.")
    except CSVQLError as exc:
        _exit_with_error(exc)
```

If this prints the rendered output and then also prints `Error: Configured data-quality checks failed.`, replace the raised exception with `raise typer.Exit(DataQualityCheckFailure.exit_code)` after output. Keep `DataQualityCheckFailure` for stable exit-code ownership and tests.

- [ ] **Step 5: Verify CLI tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_check.py -v`

Expected: PASS.

- [ ] **Step 6: Run focused integration tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_quality.py tests/test_project_config.py tests/test_checks.py tests/test_output.py tests/test_cli_check.py -v`

Expected: PASS.

- [ ] **Step 7: Commit CLI wiring**

```bash
git add src/csvql/exceptions.py src/csvql/cli.py tests/test_cli_check.py
git commit -m "feat: add data quality check command"
```

## Task 7: Documentation Updates

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Update README status and implemented list**

In `README.md`, change the status paragraph to include v0.6:

```markdown
This repository has the v0.1 query workflow, the first inspect/sample vertical, the v0.3 project catalog workflow, the v0.4 saved-workflow surfaces, the v0.5 profiling surface, and the v0.6 data-quality check surface implemented for local CLI use.
```

Add implemented bullets:

```markdown
- configured data-quality checks in `.csvql.yml`
- `csvql check [table] --output json`
- sampled failure output with `csvql check --show-failures`
```

Move `data quality checks` out of `Planned later`.

- [ ] **Step 2: Add README check examples**

Add a new `## Data Quality Check Examples` section after Profile Examples:

````markdown
## Data Quality Check Examples

Configure checks in `.csvql.yml`:

```yaml
version: 1
tables:
  orders:
    path: data/orders.csv
    checks:
      - name: order_id_required
        type: not_null
        column: order_id
      - name: order_id_unique
        type: unique
        column: order_id
      - name: status_known
        type: accepted_values
        column: status
        values: [paid, pending, cancelled]
      - name: customer_exists
        type: foreign_key
        column: customer_id
        references:
          table: customers
          column: customer_id
  customers:
    path: data/customers.csv
```

Run all configured checks:

```bash
uv run csvql check
```

Run checks for one registered table and return JSON:

```bash
uv run csvql check orders --output json
```

Include capped failure samples:

```bash
uv run csvql check orders --output json --show-failures --failure-limit 5
```

`csvql check` exits `0` when checks pass or no checks are configured. It exits `11` when configured checks run successfully and find data-quality failures. Missing catalogs, missing files, invalid config, and DuckDB execution errors use the existing CLI error path.
````

- [ ] **Step 3: Update roadmap v0.6**

In `docs/ROADMAP.md`, replace the v0.6 bullets with:

```markdown
Implemented:

- configured checks in `.csvql.yml`
- `csvql check [table]`
- `not_null`, `unique`, `accepted_values`, `min`, `max`, `row_count_between`, `foreign_key`
- non-zero exit code `11` on data-quality failures
- table and JSON output for check results
- sampled failing rows or values with `--show-failures`
```

- [ ] **Step 4: Update architecture**

In `docs/ARCHITECTURE.md`, update the flow:

```text
  -> query/inspect/sample/profile/check/export output
```

Add boundaries:

```markdown
`quality.py`
: Own typed configured-check and check-result value objects.

`checks.py`
: Run CSVQL-controlled DuckDB validation queries for configured project catalog checks. The check path uses generated SQL only, quotes identifiers, and resolves CSV files through the project catalog.
```

Update `project_config.py` boundary:

```markdown
: Discover `.csvql.yml`, load and validate the project catalog, parse configured data-quality checks, resolve catalog table paths, and build queryable table sources for catalog-backed commands.
```

Update `output.py` boundary:

```markdown
: Convert query, inspect, sample, project catalog, profile, and check results into human-readable table output or automation-friendly JSON.
```

Add design choices:

```markdown
- `check` reads configured checks from `.csvql.yml`; v0.6 does not support ad hoc CLI check definitions.
- `check` uses full-file DuckDB validation queries and exits `11` when checks fail.
- `check` does not run user-authored SQL; it builds CSVQL-controlled validation SQL from validated config and DuckDB-registered CSV views.
- `--show-failures` adds capped sampled failing rows or values for failed checks.
```

- [ ] **Step 5: Verify docs claim scan**

Run: `rg -n "sandbox|safe mode|untrusted|production|large-file|large file|benchmark|timeout|cache|materialization|v1-ready|production-safe|sandbox-safe|large-file-proven" README.md docs/ROADMAP.md docs/ARCHITECTURE.md`

Expected: Only existing security model and deferred safe-mode language remain; no new unsupported claim is introduced.

- [ ] **Step 6: Commit docs**

```bash
git add README.md docs/ROADMAP.md docs/ARCHITECTURE.md
git commit -m "docs: document data quality checks"
```

## Task 8: Full Verification And Local CLI Smoke

**Files:**
- No planned source edits unless verification exposes defects.

- [ ] **Step 1: Run format check**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .`

Expected: PASS.

- [ ] **Step 2: Run lint**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .`

Expected: PASS.

- [ ] **Step 3: Run type check**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src`

Expected: PASS.

- [ ] **Step 4: Run full tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest`

Expected: PASS.

- [ ] **Step 5: Run diff whitespace check**

Run: `git diff --check`

Expected: no output and exit code `0`.

- [ ] **Step 6: Add example check config for smoke only**

Use a temporary copy of `examples/sales` outside the repo so the smoke does not alter tracked examples:

```bash
cp -R examples/sales /private/tmp/csvql-v06-sales-smoke
```

Edit `/private/tmp/csvql-v06-sales-smoke/.csvql.yml` to include:

```yaml
version: 1
tables:
  customers:
    path: data/customers.csv
    checks:
      - name: customer_id_required
        type: not_null
        column: customer_id
      - name: customer_id_unique
        type: unique
        column: customer_id
  orders:
    path: data/orders.csv
    checks:
      - name: order_id_required
        type: not_null
        column: order_id
      - name: customer_exists
        type: foreign_key
        column: customer_id
        references:
          table: customers
          column: customer_id
```

- [ ] **Step 7: Run passing smoke**

Run from `/private/tmp/csvql-v06-sales-smoke`:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/.codex/worktrees/4d42/csvql csvql check --output json
```

Expected: exit `0`, JSON `status` is `"passed"`.

- [ ] **Step 8: Run failure-sample smoke**

Append a failing row to `/private/tmp/csvql-v06-sales-smoke/data/orders.csv`:

```text
ORD-BAD,CUST-MISSING,2026-01-01,paid,12.34
```

Run from `/private/tmp/csvql-v06-sales-smoke`:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/.codex/worktrees/4d42/csvql csvql check orders --output json --show-failures --failure-limit 1
```

Expected: exit `11`, JSON `status` is `"failed"`, and `customer_exists` includes one sampled failure.

- [ ] **Step 9: Inspect final diff**

Run: `git status --short --branch`

Run: `git diff --stat HEAD~6..HEAD`

Run: `git log --oneline -8`

Expected: branch is `codex/v06-data-quality`; commits are focused; no unrelated files changed.

- [ ] **Step 10: Final handoff labels**

Use only earned labels:

- `test-backed` if the full test suite passed.
- `local-cli-proof-ready` if both smoke commands passed.

Do not claim:

- `benchmark-backed`
- `large-file-proven`
- `production-safe`
- `sandbox-safe`
- `v1-ready`

## Self-Review

- Spec coverage: covered config-only checks, all seven check types, table filter, JSON/table output, exit code `11`, zero-check success warning, sampled failures, FK null semantics, unique excess-row semantics, null-ignore semantics, DuckDB-controlled SQL, identifier quoting, docs, and final verification.
- No-stub scan: all sections contain concrete implementation steps. Any conditional branch in the CLI task names the exact fallback code path if Typer output includes an unwanted error line.
- Type consistency: `ConfiguredCheck`, `ForeignKeyReference`, `CheckFailureSample`, `CheckResult`, and `CheckRunResult` are defined before use. Renderer and CLI signatures consistently use `include_failures`, `show_failures`, and `failure_limit`.
- Risk check: the highest implementation risk is DuckDB failure-sample SQL for odd headers and parameterized list checks. Task 4 requires generated-SQL tests and reuses shared identifier quoting before CLI wiring.
