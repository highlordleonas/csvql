# Architecture

CSVQL wraps DuckDB with a small CLI workflow. The project should stay useful without pretending to be a custom database, orchestration tool, or SQL sandbox.

## Current Flow

```text
CLI arguments
  -> query/input parser
  -> explicit table mapping parser
  -> optional project catalog discovery
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

`project_config.py`
: Discover `.csvql.yml`, load and validate the project catalog, resolve catalog table paths, and build queryable table sources for catalog-backed commands.

`source.py`
: Resolve local CSV paths and capture file metadata used by inspect, sample, and catalog workflows.

`inspection.py`
: Use DuckDB and bounded file reads to infer columns, dialect metadata, row-count status, and sample rows.

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
- Project catalog discovery is optional and only used for commands that support `.csvql.yml`.
- Catalog table paths resolve relative to the discovered project root.
- `csvql add` resolves the provided CSV path from the invocation current working directory before storing it in the catalog.
- Explicit `--table` mappings override catalog aliases with the same name for a single query invocation.
- User SQL is passed through to DuckDB and treated as trusted local input.
- CSVQL does not restrict DuckDB capabilities or sandbox filesystem access.
- `inspect` does not run an exact row count by default; `--exact` is the explicit full-scan mode.
- `sample` reads a bounded row count and shares source resolution with `inspect` and `query`.
- `--output` controls stdout formatting for query results.

## Deferred Decisions

- Whether persistent DuckDB cache is worth adding.
- Whether named parameters should be supported before v1.
- Whether safe mode belongs later; it requires a separate ADR, threat model, implementation plan, and tests.
- How export should share execution paths with stdout output.
