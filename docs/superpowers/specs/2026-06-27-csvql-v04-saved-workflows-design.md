# CSVQL v0.4 Saved Workflows Design

## Purpose

CSVQL v0.4 turns the v0.3 project catalog into a repeatable local workflow. Users should be able to register CSV tables once, save SQL in files, inspect or sample registered tables by alias, and export query results to common local formats.

This slice keeps CSVQL local-first and CLI-focused. It does not add query parameters, templating, profiling, data quality checks, caching, safe mode, cloud sources, or production-readiness claims.

## Product Decision

Implement v0.4 as one coherent "saved workflows" release with three staged capabilities:

1. `csvql run <sql-file>` for saved SQL files.
2. catalog-backed `csvql inspect <alias>` and `csvql sample <alias>`.
3. `csvql export <sql-file> --format csv|json|markdown --out <path>`.

These features belong together because they share the same user workflow: register local CSVs, save useful SQL, inspect inputs, and persist outputs.

Implementation should still happen in small commits. The release is one product slice; the work should be executed as separate vertical tasks.

## Command Contract

### `csvql run <sql-file> [--table name=path ...] [--output table|json]`

Runs SQL read from a local `.sql` file.

Examples:

```bash
uv run csvql run queries/revenue_by_month.sql
uv run csvql run queries/revenue_by_month.sql --output json
uv run csvql run queries/revenue_by_month.sql --table orders=data/orders.csv
```

Rules:

- Resolve `<sql-file>` from the invocation current working directory.
- Refuse missing files, directories, unreadable files, and empty SQL files with a typed SQL-file error.
- Use catalog tables by default when no explicit `--table` mappings are provided.
- Preserve the v0.3 explicit mapping behavior when `--table` is provided:
  - register explicit tables first;
  - explicit aliases override same-name catalog aliases;
  - lazily load catalog aliases only when DuckDB reports a missing table;
  - do not parse raw SQL text to guess table names.
- Output behavior matches `csvql query`: Rich table by default and deterministic JSON with `--output json`.
- User-authored SQL remains trusted local SQL.

### `csvql inspect <path-or-alias>`

Extends `inspect` so it can read either a direct CSV path or a catalog alias.

Examples:

```bash
uv run csvql inspect examples/sales/data/orders.csv
uv run csvql inspect orders
uv run csvql inspect orders --exact --output json
```

Resolution rules:

- Path-looking inputs are treated as paths. Path-looking means the value contains a path separator, starts with `.`, starts with `~`, or ends with `.csv`.
- Simple alias-looking inputs are resolved from the nearest `.csvql.yml` first.
- If a simple alias is not found in the catalog, fall back to the existing path behavior so the CLI still returns the current missing-file error for ordinary path mistakes.
- Users can force path behavior for an ambiguous simple name with `./name`.
- `--exact` and `--output` behavior stays unchanged.

### `csvql sample <path-or-alias> [--limit N] [--output table|json]`

Extends `sample` with the same path-or-alias resolution as `inspect`.

Examples:

```bash
uv run csvql sample examples/sales/data/orders.csv --limit 5
uv run csvql sample orders --limit 5 --output json
```

Rules:

- Use the same source-resolution helper as `inspect`.
- Keep `--limit` validation unchanged.
- Keep table and JSON output unchanged.

### `csvql export <sql-file> --format csv|json|markdown --out <path> [--table name=path ...] [--force]`

Runs SQL from a file and writes the result to a local output file.

Examples:

```bash
uv run csvql export queries/revenue_by_month.sql --format csv --out out/revenue.csv
uv run csvql export queries/revenue_by_month.sql --format json --out out/revenue.json
uv run csvql export queries/revenue_by_month.sql --format markdown --out out/revenue.md
```

Rules:

- `export` takes SQL files only in v0.4. Inline export is deferred.
- Resolve `<sql-file>` from the invocation current working directory.
- Resolve `--out` from the invocation current working directory.
- Refuse to overwrite an existing output file unless `--force` is passed.
- Do not create missing parent directories in v0.4. Fail clearly if the output directory does not exist.
- Use the same table-source behavior as `run`.
- Write UTF-8 text files.
- CSV export includes a header row and uses Python's `csv` module for quoting.
- JSON export uses the same deterministic query result payload as `--output json`.
- Markdown export writes a simple pipe table:
  - include a header row;
  - include an alignment separator row;
  - escape pipe characters in cells;
  - replace carriage returns and line feeds in cells with `<br>`.
- Empty result sets still write headers where column metadata is available.

## Architecture

### `src/csvql/sql_file.py`

Responsibilities:

- Resolve SQL file paths from the invocation current working directory.
- Read SQL text as UTF-8.
- Reject missing files, directories, unreadable files, and empty SQL text.
- Return a small value object containing the display path, resolved path, and SQL text.

### `src/csvql/query_workflow.py`

Responsibilities:

- Build query requests for inline SQL, SQL files, explicit mappings, and catalog-backed queries.
- Own shared table-source resolution for `query`, `run`, and `export`.
- Preserve the v0.3 lazy catalog fallback behavior for explicit mappings.
- Keep `cli.py` thin by moving orchestration that is not Typer-specific out of command bodies.

### `src/csvql/source_resolver.py`

Responsibilities:

- Resolve `inspect` and `sample` arguments as direct CSV paths or project catalog aliases.
- Keep the path-looking versus alias-looking rule in one place.
- Return the existing `CSVSource` value used by `inspection.py`.

### `src/csvql/export.py`

Responsibilities:

- Define `ExportFormat` values: `csv`, `json`, and `markdown`.
- Validate output file behavior, including parent directory existence and overwrite protection.
- Serialize `QueryResult` values to CSV, JSON, or Markdown.
- Write UTF-8 output files.

### `src/csvql/cli.py`

Responsibilities:

- Add `run` and `export` commands.
- Update `inspect` and `sample` to use the shared path-or-alias resolver.
- Keep Typer command bodies thin.
- Convert typed errors to the existing CLI error output.

### `src/csvql/exceptions.py`

Add two typed errors:

```python
class SQLFileError(CSVQLError):
    """Raised when a saved SQL file cannot be used."""

    exit_code = 9


class ExportError(CSVQLError):
    """Raised when an export output path or format cannot be used."""

    exit_code = 10
```

## Error Handling

Expected user-facing failures:

- Missing SQL file:
  - error: SQL file not found
  - suggestion: check the path or run from the directory that contains the SQL file
- Empty SQL file:
  - error: SQL file is empty
  - suggestion: add a SQL statement before running it
- `run` or `export` without catalog and without explicit tables:
  - reuse the v0.3 project-config error
  - suggestion: run `csvql init` and `csvql add`, or pass `--table`
- `inspect orders` when `orders` is not a catalog alias and not a file:
  - preserve the current missing-file style error
- Export output exists without `--force`:
  - error: output file already exists
  - suggestion: pass `--force` or choose a different output path
- Export parent directory missing:
  - error: output directory does not exist
  - suggestion: create the directory or choose an existing output directory

No normal CLI error should expose a stack trace.

## Non-Goals

v0.4 does not include:

- inline SQL export
- query parameters
- SQL templating
- named saved queries in `.csvql.yml`
- reader options
- type overrides
- parquet export
- profiling
- data quality checks
- safe mode
- sandboxing
- cache or materialization
- Python API
- cloud or remote sources
- concurrent write protection for `.csvql.yml`

## Testing Strategy

Use focused unit tests for new helpers and CLI integration tests for workflows.

Unit tests:

- SQL file loading succeeds for a non-empty UTF-8 file.
- SQL file loading rejects missing files.
- SQL file loading rejects directories.
- SQL file loading rejects empty or whitespace-only files.
- Path-or-alias source resolution treats path-looking inputs as paths.
- Path-or-alias source resolution resolves simple aliases from the catalog.
- Path-or-alias source resolution falls back to path behavior when a simple alias is not registered.
- Export validation refuses overwrite without `--force`.
- Export validation allows overwrite with `--force`.
- Export validation rejects missing parent directories.
- CSV export includes headers and quoted values.
- JSON export matches current query JSON structure.
- Markdown export escapes pipe characters and line breaks.

CLI tests:

- `csvql run queries/file.sql` uses catalog tables.
- `csvql run queries/file.sql --output json` returns deterministic JSON.
- `csvql run queries/file.sql --table orders=path.csv` works without a catalog.
- `csvql run` preserves explicit override semantics from v0.3.
- `csvql run` rejects missing SQL files.
- `csvql run` rejects empty SQL files.
- `csvql inspect orders` resolves a catalog alias.
- `csvql inspect ./orders.csv` remains path-based.
- `csvql sample orders --limit 5` resolves a catalog alias.
- `csvql export queries/file.sql --format csv --out result.csv` writes CSV.
- `csvql export queries/file.sql --format json --out result.json` writes JSON.
- `csvql export queries/file.sql --format markdown --out result.md` writes Markdown.
- `csvql export` refuses overwrite without `--force`.
- `csvql export --force` overwrites an existing output file.

Verification commands:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
git diff --check
```

Smoke checks:

```bash
uv run csvql init
uv run csvql add orders examples/sales/data/orders.csv
uv run csvql run examples/sales/queries/revenue_by_month.sql --output json
uv run csvql inspect orders --output json
uv run csvql sample orders --limit 2 --output json
uv run csvql export examples/sales/queries/revenue_by_month.sql --format csv --out /tmp/csvql-revenue.csv
uv run csvql export examples/sales/queries/revenue_by_month.sql --format json --out /tmp/csvql-revenue.json
uv run csvql export examples/sales/queries/revenue_by_month.sql --format markdown --out /tmp/csvql-revenue.md
```

## Acceptance Criteria

- `csvql run <sql-file>` executes saved SQL against catalog tables.
- `csvql run <sql-file> --table name=path` works without a catalog.
- `csvql run` preserves explicit table override behavior.
- `csvql inspect <alias>` and `csvql sample <alias>` work for registered catalog tables.
- Direct path behavior for `inspect` and `sample` still works.
- `csvql export` writes CSV, JSON, and Markdown outputs.
- `csvql export` refuses overwrite unless `--force` is passed.
- Missing SQL files, empty SQL files, export path conflicts, and missing export directories produce typed CLI errors.
- Existing `query`, `inspect`, `sample`, and project catalog tests continue to pass.
- Docs describe saved workflows without sandbox, production, untrusted-SQL, or large-file performance claims.

## Execution Boundary

Implementation should start from the current v0.3 project catalog branch after it is accepted as the base for v0.4.

Do not implement this in the dirty `/Users/richarddemke/.codex/worktrees/63fd/csvql` worktree. Do not mix this work with old inspect/sample plans or unrelated governance edits.
