# Architecture

CSVQL wraps DuckDB with a small command-line workflow. It is not a custom
database, orchestration tool, or SQL sandbox.

## How A Command Runs

```text
CLI arguments
  -> path/sql-file/input parser
  -> explicit table mapping parser or project catalog discovery
  -> validated table aliases and resolved CSV paths
  -> in-memory DuckDB engine
  -> query/inspect/sample/profile/check/doctor/export output

Optional terminal menu flow:
csvql menu startup arguments
  -> lazy Textual dependency boundary
  -> TUI session state from catalog, one CSV path, or --table mappings
  -> existing inspect/sample/profile/query/export services
  -> in-memory history, visible results, explicit exports, and explicit
     project-local derived result CSVs
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
: Shared query request construction and execution for inline query, saved SQL run, and export workflows.

`source.py`
: Resolve local CSV paths and capture file metadata used by inspect, sample, and catalog workflows.

`source_resolver.py`
: Resolve inspect/sample inputs as direct CSV paths or project catalog aliases.

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
: Own DuckDB connection lifecycle, CSV registration, SQL execution, and DuckDB error conversion.

`export.py`
: Validate export output paths and serialize query results to CSV, JSON,
  Markdown, or text.

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
  sources, runs trusted local SQL through `engine.py`, delegates inspect/sample/
  profile/export behavior, saves sources to `.csvql.yml`, and writes explicit
  derived result CSVs under `.csvql/results/`.

`tui_result_store.py`
: Session-local query-result storage. Small results remain in memory; results
  above row or cell thresholds spill to process-owned temporary files so the
  TUI can recall and explicitly export the full result. Normal TUI shutdown
  removes the temporary directory.

`tui_app.py`, `tui_results.py`, `tui_help.py`
: Textual UI composition, keybindings, result display helpers, and in-app help.
  These modules own terminal interaction only; DuckDB execution stays in the
  engine/workflow layers.

## Design Choices

- DuckDB runs in memory for CLI and Python API execution.
- CSV files are registered as views using DuckDB's CSV reader.
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
- `csvql menu` is optional and requires the `tui` package extra; the core CLI
  install does not require Textual.
- The TUI keeps query history in memory for the current terminal session only.
- The TUI writes durable files only on explicit user actions: result export,
  project catalog save, or derived result source save. Large query results can
  also spill automatically to session-owned temporary files that are removed on
  normal shutdown.
- TUI derived result sources are CSV files under project-root or start-directory
  `.csvql/results/{alias}.csv`. They are loaded back into the current TUI
  Sources pane with kind `derived` and can be queried like other local CSV
  sources. The file persists on disk, but the alias is session-local unless the
  user explicitly saves sources to `.csvql.yml`.
- Derived result sources are CSV files created only when the user asks for them;
  they are not a hidden cache.
- When DuckDB returns column metadata for statements such as DDL, CSVQL treats
  the response as a tabular result instead of classifying SQL by statement text.
