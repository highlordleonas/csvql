# Architecture

CSVQL wraps DuckDB with a small CLI workflow. The project should stay useful without pretending to be a custom database, orchestration tool, or SQL sandbox.

## v0.1 Flow

```text
CLI arguments
  -> table mapping parser
  -> validated table aliases and resolved CSV paths
  -> in-memory DuckDB engine
  -> CSV views
  -> user-authored SQL
  -> table or JSON output
```

## Boundaries

`cli.py`
: Typer command definitions and process-exit behavior. Keep this thin.

`table_mapping.py`
: Parse `name=path`, validate table aliases, resolve CSV paths, and support single-file alias derivation.

`engine.py`
: Own DuckDB connection lifecycle, CSV registration, SQL execution, and DuckDB error conversion.

`output.py`
: Convert `QueryResult` into human-readable table output or automation-friendly JSON.

`models.py`
: Small typed value objects shared across services.

`exceptions.py`
: CLI-friendly failures with stable exit codes.

## Current Design Choices

- DuckDB runs in memory for v0.1.
- CSV files are registered as views using DuckDB's CSV reader.
- Table aliases must match `^[A-Za-z_][A-Za-z0-9_]*$`.
- User SQL is passed through to DuckDB and treated as trusted local input.
- `--output` controls stdout formatting for query results.

## Deferred Decisions

- `.csvql.yml` schema and project discovery.
- Whether persistent DuckDB cache is worth adding.
- Whether named parameters should be supported before v1.
- Whether safe mode belongs in v1 or post-v1.
- How export should share execution paths with stdout output.
