# Failure Gallery

CSVQL is a local developer tool for trusted SQL over local CSV files. DuckDB
executes user-authored SQL, and CSVQL does not restrict DuckDB capabilities or
filesystem access.

This gallery documents common deterministic failures that CSVQL already
handles. Runtime behavior wins: if a command prints a different exit code or
stable message than this page, treat the runtime as the source to inspect before
changing docs.

Examples use `uv run csvql ...`. Absolute temporary paths are normalized as
`<project-root>` when the path value is not the contract.

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

Typer usage errors, such as an invalid option value, use Typer's own CLI path
and are outside this gallery.

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

How to fix: run from the directory that contains the CSV, pass the correct path,
or add the CSV to a project catalog and query by table alias.

Covered by:
`tests/test_failure_gallery.py::test_gallery_direct_missing_csv_path_returns_exit_4`

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

The suggestion may wrap across terminal lines. The stable contract is the
project-table context and the repair instruction.

Why it fails: CSVQL resolves configured table paths relative to the project root
before registering DuckDB views.

How to fix: restore the CSV file, edit `.csvql.yml`, or run
`uv run csvql add orders <path> --replace`.

Covered by:
`tests/test_failure_gallery.py::test_gallery_project_catalog_missing_csv_path_returns_exit_4`

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

Why it fails: explicit table mappings must bind a DuckDB table alias to a
resolved CSV path before query execution starts.

Covered by:
`tests/test_failure_gallery.py::test_gallery_bad_table_mapping_cli_errors_use_exit_6`

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

Why it fails: CSVQL cannot register a table alias without a concrete local CSV
path.

Covered by:
`tests/test_failure_gallery.py::test_gallery_bad_table_mapping_cli_errors_use_exit_6`

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

The suggestion may wrap before `underscore.` in narrow terminals.

How to fix: use an alias such as `orders_2026`.

Why it fails: user-provided aliases must already be safe SQL identifiers before
CSVQL passes them to DuckDB.

Covered by:
`tests/test_failure_gallery.py::test_gallery_bad_table_mapping_cli_errors_use_exit_6`

Single-file shortcut note: CSVQL derives a safe alias from filenames in shortcut
mode. A file named `2026-orders.csv` is queried as `table_2026_orders`;
user-provided `--table` aliases remain validated exactly as entered.

Covered by:
`tests/test_failure_gallery.py::test_gallery_single_file_shortcut_uses_generated_safe_alias`

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

Why it fails: CSVQL treats user-authored SQL as trusted local SQL and passes it
to DuckDB after registering CSV sources.

How to fix: run `uv run csvql inspect orders.csv`, check the table alias, and
correct the SQL.

Covered by:
`tests/test_failure_gallery.py::test_gallery_duckdb_query_failure_uses_exit_1`

## Project Catalog Failures

### Missing catalog for project-required query mode

Scenario: `csvql query "SELECT ..."` is run without explicit `--table` mappings
and no `.csvql.yml` exists.

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

How to fix: run `uv run csvql init` and `uv run csvql add`, or pass
`--table name=path` for an ad hoc query.

Why it fails: project query mode needs a discovered catalog unless the command
provides explicit table mappings.

Covered by:
`tests/test_failure_gallery.py::test_gallery_missing_project_catalog_uses_exit_8`

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
one probe has name=config_load
that probe has status=failed
that probe message contains "Invalid YAML"
```

How to fix: repair `.csvql.yml` so it has `version: 1` and a mapping under
`tables`.

Why it fails: doctor can discover the catalog file, but it cannot continue
project-health checks until the YAML parses.

Covered by:
`tests/test_failure_gallery.py::test_gallery_invalid_project_catalog_doctor_uses_exit_12`

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

Why it fails: saved-SQL commands load the SQL file before discovering project
tables or running DuckDB.

Covered by:
`tests/test_failure_gallery.py::test_gallery_saved_sql_file_failures_use_exit_9`

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

Why it fails: CSVQL refuses to run an empty saved-SQL file because there is no
statement to execute.

Covered by:
`tests/test_failure_gallery.py::test_gallery_saved_sql_file_failures_use_exit_9`

Scenario: `csvql export` points at a missing SQL file.

Command:

```bash
uv run csvql export queries/missing.sql --format csv --out out.csv
```

Expected exit code: `9`

Expected message shape:

```text
Error: SQL file not found: queries/missing.sql
Suggestion: Check the path or run from the directory that contains the SQL file.
```

How to fix: create the SQL file before exporting, then rerun the export command.

Why it fails: export loads the saved SQL before resolving output content, so a
missing SQL file stops the command before query execution.

Covered by:
`tests/test_failure_gallery.py::test_gallery_saved_sql_file_failures_use_exit_9`

## Export Overwrite Protection

Scenario: the export output path already exists and `--force` was not passed.

Command:

```bash
uv run csvql export query.sql --format csv --out out.csv
```

Expected exit code: `10`

Expected message shape:

```text
Error: Export output already exists: <project-root>/out.csv
Suggestion: Pass --force to overwrite it or choose a different output path.
```

The absolute path may wrap across terminal lines. The stable contract is that
the existing output is named and the command refuses to overwrite it without
`--force`.

Why it fails: CSVQL refuses to clobber an existing export unless the command
explicitly opts in.

How to fix: choose a new output path or pass `--force`.

Covered by:
`tests/test_failure_gallery.py::test_gallery_export_overwrite_protection_uses_exit_10`

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

Why it fails: a data-quality failure means the command ran and found invalid
rows. It is not the same as a runtime failure.

How to fix: inspect sampled failures with `--show-failures`, repair the data or
check definition, then rerun `csvql check`.

Covered by:
`tests/test_failure_gallery.py::test_gallery_data_quality_failure_uses_exit_11_json`

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

Why it is not a failure: doctor can report that no project exists without
failing the process.

How to fix: run `uv run csvql init` if this directory should be a CSVQL project.

Covered by:
`tests/test_failure_gallery.py::test_gallery_doctor_warning_and_failure_statuses`

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

How to fix: restore the CSV, correct `.csvql.yml`, or run
`uv run csvql add orders <path> --replace`.

Covered by:
`tests/test_failure_gallery.py::test_gallery_doctor_warning_and_failure_statuses`

## Python API Notes

The small Python API raises `CSVQLError` subclasses for runtime errors instead
of exiting the process.

### Missing project catalog

Scenario: API code opens a session from a directory without `.csvql.yml`.

Invocation:

```python
CSVQLSession.from_config("missing-project")
```

Expected API behavior: raises `ProjectConfigError`.

Why it fails: project-backed API sessions need the same catalog discovery as
project-backed CLI commands.

How to fix: pass a directory inside a CSVQL project, or create one with
`uv run csvql init` and `uv run csvql add`.

Covered by:
`tests/test_failure_gallery.py::test_gallery_python_api_propagates_errors_but_check_failures_return_result`

### DuckDB query failure

Scenario: API code queries a missing column.

Invocation:

```python
session.query("SELECT missing_column FROM orders")
```

Expected API behavior: raises `QueryExecutionError`.

Why it fails: `session.query(...)` registers project tables and passes trusted
local SQL through to DuckDB.

How to fix: inspect the configured table, then correct the column name, table
alias, or SQL syntax.

Covered by:
`tests/test_failure_gallery.py::test_gallery_python_api_propagates_errors_but_check_failures_return_result`

### Missing saved SQL file

Scenario: API code runs a saved SQL file that does not exist.

Invocation:

```python
session.run_file("queries/missing.sql")
```

Expected API behavior: raises `SQLFileError`.

Why it fails: `session.run_file(...)` resolves saved SQL paths from the project
root before running the query.

How to fix: create the SQL file under the project, or pass the correct
project-relative path.

Covered by:
`tests/test_failure_gallery.py::test_gallery_python_api_propagates_errors_but_check_failures_return_result`

### Data-quality failure result

Scenario: API code runs configured checks and the checks find bad rows.

Invocation:

```python
result = session.check(show_failures=True, failure_limit=1)
```

Expected API behavior: returns `CheckRunResult` with:

```text
status=failed
failed_count=1
checks[0].name=order_id_required
checks[0].failures[0].row_number=2
```

Why it does not raise: a failed check is a successful check run with failed data,
not an API runtime error.

How to fix: inspect the returned failures, repair the data or check definition,
then run `session.check(...)` again.

Covered by:
`tests/test_failure_gallery.py::test_gallery_python_api_propagates_errors_but_check_failures_return_result`

## Proof

This gallery is backed by focused tests in `tests/test_failure_gallery.py` plus
the existing source-specific tests for table mapping, SQL files, export paths,
checks, doctor output, and API behavior.

Before claiming this page is current, run:

```bash
uv run pytest tests/test_failure_gallery.py -q
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```
