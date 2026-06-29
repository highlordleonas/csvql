# CSVQL v0.6 Data Quality Checks Design

Status: design approved in conversation; written spec review required before implementation planning.

Date: 2026-06-29

## Purpose

CSVQL v0.6 adds repeatable local data-quality checks for registered CSV project tables.

The goal is to let users define checks in `.csvql.yml`, run them with `csvql check`, and get deterministic table or JSON output that works locally and in CI.

This slice keeps CSVQL aligned with its north star: a local-first CLI around DuckDB for understanding, querying, profiling, and validating CSV files. DuckDB owns SQL execution. CSVQL owns project workflow, table aliasing, check configuration, deterministic output, exit behavior, docs, and tests.

## Product Contract

v0.6 adds:

```bash
csvql check
csvql check orders
csvql check --output json
csvql check orders --output json --show-failures --failure-limit 5
```

Command behavior:

- `csvql check` runs all configured checks for all registered project tables.
- `csvql check orders` runs only checks nested under the `orders` table.
- `--output table|json` controls output format and defaults to `table`.
- `--show-failures` includes sampled failing values or rows.
- `--failure-limit N` caps sampled failures per failed check and defaults to `5`.
- v0.6 does not support ad hoc CLI check definitions.
- v0.6 does not support filtering by individual check name.

Exit behavior:

- `0`: command ran and all checks passed.
- `0`: command ran and zero checks were configured.
- `11`: command ran and one or more checks failed.
- Existing error codes remain for missing files, invalid config, unreadable CSVs, and DuckDB execution failures.

Zero configured checks are not an error. The result should clearly report that zero checks ran and include a warning.

## Check Set

v0.6 implements the full roadmap check set:

- `not_null`
- `unique`
- `accepted_values`
- `min`
- `max`
- `row_count_between`
- `foreign_key`

## Configuration Contract

Checks are nested under each table in `.csvql.yml`:

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

      - name: status_allowed
        type: accepted_values
        column: status
        values: ["paid", "pending", "refunded"]

      - name: total_amount_nonnegative
        type: min
        column: total_amount
        value: 0

      - name: total_amount_reasonable
        type: max
        column: total_amount
        value: 100000

      - name: row_count_sane
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
      - name: customer_id_unique
        type: unique
        column: customer_id
```

Validation rules:

- `checks` is optional per table.
- each check must have `name` and `type`.
- check names must be unique within a table.
- check names do not need to be globally unique.
- unknown check types are config errors.
- missing required fields are config errors.
- extra unknown fields are config errors.
- `not_null`, `unique`, `accepted_values`, `min`, `max`, and `foreign_key` require `column`.
- `accepted_values` requires non-empty `values`.
- `min` and `max` require `value`.
- `row_count_between` requires at least one of `min` or `max`.
- if `row_count_between` has both `min` and `max`, `min <= max`.
- `foreign_key` requires `references.table` and `references.column`.
- `foreign_key` referenced table must exist in `.csvql.yml`.
- `foreign_key` is single-column only in v0.6.

## Check Semantics

All checks run against DuckDB-read CSV relations using CSVQL-controlled SQL. `csvql check` does not run user-authored SQL.

Null semantics:

- `not_null` fails null values.
- `unique` ignores nulls.
- `accepted_values` ignores nulls.
- `min` ignores nulls.
- `max` ignores nulls.
- `foreign_key` ignores nulls.
- Required-ness is always expressed with `not_null`.

Individual check behavior:

- `not_null`: failed count is rows where the configured column is null.
- `unique`: failed count uses excess-row semantics for non-null duplicate values. Three identical non-null values contribute `2`.
- `accepted_values`: failed count is non-null rows where the column value is not in configured values.
- `min`: failed count is non-null rows where the column value is less than `value`.
- `max`: failed count is non-null rows where the column value is greater than `value`.
- `row_count_between`: failed if table row count is below `min` or above `max`.
- `foreign_key`: failed count is child rows where the non-null child value has no match in the referenced parent column.

`min` and `max` use DuckDB-inferred comparison semantics. If DuckDB reads a column as `DATE`, the configured value must be comparable as a DuckDB date. If DuckDB cannot compare the column and configured value, that is a config or execution error, not a failed data-quality check.

For `row_count_between`, failed count should be `0` when the row count is within bounds. If the row count is outside a configured bound, failed count should be the delta outside the nearest violated bound.

## Output Contract

Default JSON output excludes failure samples:

```json
{
  "status": "failed",
  "check_count": 3,
  "passed_count": 2,
  "failed_count": 1,
  "checks": [
    {
      "name": "status_allowed",
      "table": "orders",
      "type": "accepted_values",
      "column": "status",
      "status": "failed",
      "failed_count": 2
    }
  ],
  "warnings": []
}
```

Top-level `check_count`, `passed_count`, and `failed_count` count configured checks, not rows. Per-check `failed_count` counts rows or row-count delta for that individual check.

With `--show-failures`, failed checks include capped samples:

```json
{
  "name": "status_allowed",
  "table": "orders",
  "type": "accepted_values",
  "column": "status",
  "status": "failed",
  "failed_count": 2,
  "failures": [
    {"row_number": 7, "value": "cancelled"},
    {"row_number": 12, "value": "unknown"}
  ]
}
```

Foreign-key failure samples identify child rows and child values:

```json
{
  "name": "customer_exists",
  "table": "orders",
  "type": "foreign_key",
  "column": "customer_id",
  "status": "failed",
  "failed_count": 1,
  "failures": [
    {"row_number": 8, "columns": {"customer_id": "CUST-999"}}
  ]
}
```

Table output should be concise by default: one row per check with `table`, `check`, `type`, `status`, and `failed_count`.

When `--show-failures` is passed, table output should print a short capped failure section below the summary.

Zero-check JSON output should look like:

```json
{
  "status": "passed",
  "check_count": 0,
  "passed_count": 0,
  "failed_count": 0,
  "checks": [],
  "warnings": ["No data quality checks are configured."]
}
```

## Architecture

The implementation should follow existing CSVQL boundaries:

- `cli.py`: thin Typer boundary for `check [table]`, `--output`, `--show-failures`, and `--failure-limit`.
- `project_config.py`: parse and validate nested table check configuration.
- `quality.py`: typed check config and result value objects.
- `checks.py`: DuckDB-backed check execution service and CSVQL-controlled aggregate SQL.
- `output.py`: table and JSON renderers for check results.
- `exceptions.py`: add a dedicated data-quality failure exception with exit code `11`.

The check service should:

- load project table paths through existing project catalog resolution.
- run checks in memory with DuckDB.
- load referenced parent tables for `foreign_key`.
- quote generated table/view names and column identifiers safely.
- parameterize configured values where DuckDB supports it.
- avoid user-authored SQL.

If SQL identifier quoting becomes shared with profiling, extract a small internal helper rather than duplicating logic broadly.

## Error Model

Data-quality failures are not command errors. They mean the command ran successfully and found data that violates configured checks.

These are data-quality failures and should produce exit code `11`:

- one or more configured checks fail.

These are command or configuration errors and should use existing error categories where possible:

- no `.csvql.yml` exists.
- selected table does not exist in the project catalog.
- a configured CSV path is missing.
- check config has unknown fields, missing fields, invalid values, or unknown check type.
- a configured column does not exist in the CSV.
- a `foreign_key` reference table or reference column is invalid.
- DuckDB cannot compare configured `min` or `max` values with the inferred column type.
- DuckDB cannot read or execute the generated check query.

## Testing Requirements

Config parsing tests:

- valid nested checks.
- optional checks.
- duplicate check names within a table.
- unknown check types.
- missing required fields.
- unknown extra fields.
- invalid `row_count_between` bounds.
- missing or invalid `foreign_key` references.

Service tests:

- pass and fail cases for every check type.
- null semantics for every applicable check.
- duplicate excess-row semantics for `unique`.
- row-count lower and upper bound failures.
- `min` and `max` using DuckDB-inferred comparison behavior.
- single-column `foreign_key` pass and fail cases.
- `foreign_key` ignores null child values.
- failure sampling with cap.
- odd column names that require identifier quoting.

CLI tests:

- `csvql check`.
- `csvql check orders`.
- table output.
- JSON output.
- `--show-failures`.
- `--failure-limit`.
- exit `0` when checks pass.
- exit `11` when checks fail.
- zero checks warning and exit `0`.
- invalid config error.
- missing selected table error.

Docs:

- README examples for configuring and running checks.
- `docs/ROADMAP.md` v0.6 implemented status after code lands.
- `docs/ARCHITECTURE.md` check boundary and no-user-authored-SQL behavior.

## Implementation Shape

Implement v0.6 in two coherent vertical commits:

1. Config/model/output/CLI plus:
   - `not_null`
   - `unique`
   - `accepted_values`
   - `row_count_between`

2. Range and relational checks plus failure samples:
   - `min`
   - `max`
   - `foreign_key`
   - `--show-failures`
   - `--failure-limit`
   - docs and final verification

## Non-Goals

v0.6 does not include:

- ad hoc CLI check definitions.
- filtering by individual check name.
- composite foreign keys.
- warning-only checks.
- severity levels.
- scoring.
- dashboards.
- automatic running of checks before `query`, `run`, or `export`.
- persistent cache or materialization.
- sandbox, untrusted SQL, production-safety, timeout, benchmark, or large-file performance claims.

## Verification Target

Final verification should include:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest
git diff --check
```

Manual CLI smokes should cover:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql check --output json
UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql check orders --output json --show-failures --failure-limit 2
```
