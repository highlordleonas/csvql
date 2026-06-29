# Architecture

CSVQL wraps DuckDB with a small CLI workflow. The project should stay useful without pretending to be a custom database, orchestration tool, or SQL sandbox.

## Current Flow

```text
CLI arguments
  -> path/sql-file/input parser
  -> explicit table mapping parser or project catalog discovery
  -> validated table aliases and resolved CSV paths
  -> in-memory DuckDB engine
  -> query/inspect/sample/profile/check/export output
```

## Boundaries

`cli.py`
: Typer command definitions and process-exit behavior. Keep this thin.

`table_mapping.py`
: Parse `name=path`, validate table aliases, resolve CSV paths, and support single-file alias derivation.

`sql_file.py`
: Resolve and read saved SQL files, rejecting missing, directory, unreadable, and empty SQL inputs.

`project_config.py`
: Discover `.csvql.yml`, load and validate the project catalog, parse configured data-quality checks, resolve catalog table paths, and build queryable table sources for catalog-backed commands.

`query_workflow.py`
: Shared query request construction and execution for inline query, saved SQL run, and export workflows.

`source.py`
: Resolve local CSV paths and capture file metadata used by inspect, sample, and catalog workflows.

`source_resolver.py`
: Resolve inspect/sample inputs as direct CSV paths or project catalog aliases.

`inspection.py`
: Use DuckDB and bounded file reads to infer columns, dialect metadata, row-count status, and sample rows.

`profiling.py`
: Use DuckDB full-scan aggregate queries to calculate deterministic profile metrics for direct CSV paths and project catalog aliases. Generated aggregate SQL is CSVQL-controlled and quotes DuckDB-discovered column identifiers.

`quality.py`
: Own typed configured-check and check-result value objects.

`checks.py`
: Run CSVQL-controlled DuckDB validation queries for configured project catalog checks. The check path uses generated SQL only, quotes identifiers, and resolves CSV files through the project catalog.

`engine.py`
: Own DuckDB connection lifecycle, CSV registration, SQL execution, and DuckDB error conversion.

`export.py`
: Validate export output paths and serialize query results to CSV, JSON, or Markdown.

`output.py`
: Convert query, inspect, sample, project catalog, profile, and check results into human-readable table output or automation-friendly JSON.

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
- `profile` intentionally performs a full scan and shares source resolution with `inspect` and `sample`.
- `profile` does not run user-authored SQL; it builds CSVQL-controlled aggregate SQL from DuckDB-discovered columns.
- `check` reads configured checks from `.csvql.yml`; v0.6 does not support ad hoc CLI check definitions.
- `check` uses full-file DuckDB validation queries and exits `11` when checks fail.
- `check` does not run user-authored SQL; it builds CSVQL-controlled validation SQL from validated config and DuckDB-registered CSV views.
- `--show-failures` adds capped sampled failing rows or values for failed checks.
- `--output` controls stdout formatting for query results.

## Deferred Decisions

- Whether persistent DuckDB cache is worth adding.
- Whether named parameters should be supported before v1.
- Whether safe mode belongs later; it requires a separate ADR, threat model, implementation plan, and tests.
- How export should share execution paths with stdout output.
