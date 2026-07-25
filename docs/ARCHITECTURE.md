# Architecture

CSVQL wraps DuckDB with a small command-line workflow. It is not a custom
database, orchestration tool, or SQL sandbox.

## How A Command Runs

```text
CLI arguments
  -> path/sql-file/input parser
  -> explicit table mapping parser or project catalog discovery
  -> private SourceSpec and SourceAdapter resolution
  -> in-memory DuckDB engine
  -> complete ResultStream
  -> bounded interactive output, complete JSON/Python result, or streaming export

Optional terminal menu flow:
csvql menu startup arguments
  -> lazy Textual dependency boundary
  -> TUI session state from catalog, one CSV path, or --table mappings
  -> TUIQueryRunner consumes one ResultStream
  -> bounded preview plus complete TUIResultStore preservation
  -> in-memory history, visible previews, complete explicit exports, and
     complete explicit project-local derived result CSVs
```

## Components

`cli.py`
: Typer command definitions and process-exit behavior. Keep this thin.

`api.py`
: Small public Python wrapper around project-backed table listing, query, saved
  SQL, inspect, sample, profile, configured checks, and export services. It
  stores resolved project context, not a persistent DuckDB connection, and does
  not own CLI formatting or process-exit behavior.

`table_mapping.py`
: Parse `name=path`, validate table aliases, resolve CSV paths, and support single-file alias derivation.

`sql_file.py`
: Resolve and read saved SQL files, rejecting missing, directory, unreadable, and empty SQL inputs.

`project_config.py`
: Discover `.csvql.yml`, load and validate the project catalog, parse configured
  data-quality checks, resolve catalog table paths, and build queryable sources.

`query_workflow.py`
: Shared query request construction plus complete and streaming execution for
  inline query, saved SQL run, and export workflows.

`source.py`
: Own private `SourceSpec`, resolved-source and capability value objects, resolve
  local CSV paths, and capture file metadata used by source workflows.

`source_adapter.py`, `csv_adapter.py`
: Define the private `SourceAdapter` capability/binding boundary and its explicit
  registry, with CSV as the only v1.1 adapter. This is not a public plugin API.

`source_resolver.py`
: Resolve inspect/sample inputs as direct CSV paths or project catalog aliases.

`source_operations.py`
: Run source-neutral inspect, sample, and profile operations over an
  adapter-prepared binding.

`inspection.py`
: Use DuckDB and bounded file reads to infer columns, dialect metadata, row-count status, and sample rows.

`profiling.py`
: Use DuckDB full-scan aggregate queries to calculate profile metrics for direct
  CSV paths and project catalog aliases. CSVQL generates the aggregate SQL and
  quotes column names discovered by DuckDB.

`quality.py`
: Own typed configured-check and check-result value objects.

`checks.py`
: Run generated DuckDB validation queries for checks in the project catalog.
  CSVQL quotes column names and resolves CSV files through the catalog.

`doctor.py`
: Run project-health probes for the nearest `.csvql.yml`, returning tri-state
  pass/warning/fail results for project discovery, config load, table readability,
  and configured check definitions without executing user-authored SQL or the
  checks themselves.

`engine.py`
: Own DuckDB connection lifecycle, source preparation, complete or streaming SQL
  execution, cancellation, and DuckDB error conversion.

`result_stream.py`, `bounded_result.py`
: `ResultStream` owns single-consumer bounded batches from one DuckDB cursor.
  `BoundedQueryResult` and its preview policy cap interactive row and payload
  retention without changing complete Python or JSON results.

`export.py`
: Define export formats and validate output paths.

`streaming_export.py`
: Perform complete streaming export to CSV, JSON, Markdown, or text with atomic
  destination replacement and cleanup.

`output.py`
: Convert query, inspect, sample, project catalog, profile, check, and doctor
  results into human-readable table output or automation-friendly JSON.

`models.py`
: Small typed value objects shared across services.

`exceptions.py`
: CLI-friendly failures with stable exit codes.

`tui_launcher.py`
: Lazy optional dependency boundary for `csvql menu`. It converts missing
  Textual dependency errors into normal CSVQL CLI errors.

`tui_state.py`
: In-memory state for the current terminal menu session: loaded sources,
  selected source, query history, last result status, result preview state, and
  active worker state.

`tui_workflows.py`
: TUI workflow adapter around existing CSVQL services. It loads startup
  sources, delegates inspect/sample/profile behavior, saves sources to
  `.csvql.yml`, and writes explicit derived result CSVs under
  `.csvql/results/`.

`tui_query_runner.py`
: `TUIQueryRunner` executes each statement once, publishes its bounded preview,
  and preserves its complete result when session capacity allows.

`result_codec.py`, `result_spool.py`, `tui_result_store.py`
: Encode typed rows, own private temporary result files, and expose the
  `TUIResultStore`. Complete results share one 1 GiB session capacity with no
  automatic eviction; capacity exhaustion produces a truthful preview-only
  result without removing earlier results.

`tui_app.py`, `tui_results.py`, `tui_help.py`
: Textual UI composition, keybindings, result display helpers, and in-app help.
  These modules own terminal interaction only; DuckDB execution stays in the
  engine/workflow layers.

## Design Choices

- DuckDB runs in memory for CLI and Python API execution.
- CSV files are registered as views through the private CSV `SourceAdapter`
  using DuckDB's CSV reader.
- Table aliases must match `^[A-Za-z_][A-Za-z0-9_]*$`.
- Project catalog discovery is optional and only used for commands that support `.csvql.yml`.
- Catalog table paths resolve relative to the discovered project root.
- `csvql add` resolves the CSV path from the current working directory before
  storing it in the catalog.
- Explicit `--table` mappings override catalog aliases with the same name for a single query invocation.
- User SQL is passed through to DuckDB and treated as trusted local input.
- CSVQL does not restrict DuckDB capabilities or sandbox filesystem access.
- The Python API requires a project catalog and opens a short-lived DuckDB
  connection for each query, saved SQL file, inspection, sample, profile, check,
  or export.
- `inspect` does not run an exact row count by default; `--exact` is the explicit full-scan mode.
- `sample` reads a bounded row count and shares source resolution with `inspect` and `query`.
- `profile` intentionally performs a full scan and shares source resolution with `inspect` and `sample`.
- `profile` does not run user-authored SQL; CSVQL builds its aggregate queries
  from columns discovered by DuckDB.
- `check` reads configured checks from `.csvql.yml`; checks are catalog-backed
  rather than ad hoc CLI definitions.
- `check` uses full-file DuckDB validation queries and exits `11` when checks fail.
- `check` does not run user-authored SQL; CSVQL builds validation queries from
  the catalog and registered CSV views.
- `--show-failures` adds capped sampled failing rows or values for failed checks.
- `doctor` looks for the nearest project catalog and returns a warning, not a
  command error, when no `.csvql.yml` is present.
- `doctor` checks table readability with CSVQL-controlled DuckDB registration
  and a one-row read; readable CSVs with no rows are healthy.
- `doctor` compares configured check columns with the discovered schema without
  running the checks and exits `12` when it finds a project-health problem.
- `--output` controls stdout formatting for query results.
- Interactive `query` and `run` table output keeps at most 1,000 rows and
  16 MiB of encoded preview payload by default. Query/run JSON output and the
  Python API remain complete in v1.1.
- CLI exports consume a `ResultStream` and remain complete.
- `csvql menu` is optional and requires the `tui` package extra; the core CLI
  install does not require Textual.
- The TUI keeps query history in memory for the current terminal session only.
- The TUI shows bounded previews while preserving complete results under one
  1 GiB aggregate session capacity. It uses no automatic eviction.
- The TUI writes files only on explicit user actions: result export, project
  catalog save, or derived result source save.
- TUI derived result sources are CSV files under project-root or start-directory
  `.csvql/results/{alias}.csv`. They are loaded back into the current TUI
  Sources pane with kind `derived` and can be queried like other local CSV
  sources. The file persists on disk, but the alias is session-local unless the
  user explicitly saves sources to `.csvql.yml`.
- Derived result sources are CSV files created only when the user asks for them;
  they are not a hidden cache.
- When DuckDB returns column metadata for statements such as DDL, CSVQL treats
  the response as a tabular result instead of classifying SQL by statement text.
