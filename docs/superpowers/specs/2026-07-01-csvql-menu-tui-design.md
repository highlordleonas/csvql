# CSVQL Menu TUI Design

Status: design approved in conversation; written spec review required before
implementation planning.

Date: 2026-07-01

## Purpose

This spec defines a small interactive terminal UI for CSVQL.

The goal is to make the existing local workflow easier to use from a terminal:

- choose and manage CSV sources
- inspect columns
- sample rows
- profile data
- run trusted SQL across one or more CSV aliases
- export results only when explicitly requested

This is an additive frontend over CSVQL's existing services. It should not
change the existing CLI command contracts or the public Python API contract.

## Approved Direction

The approved direction is a richer terminal UI using Textual, centered on a
source manager.

The TUI should support:

- `csvql menu`
- `csvql menu /path/file.csv`
- `csvql menu --table customers=customers.csv --table orders=orders.csv`

The TUI should be session-backed by default:

- sources added inside the TUI live in memory for the current session
- no `.csvql.yml` write happens unless the user chooses a save action
- no export file write happens unless the user chooses an export action

This direction intentionally avoids a single-file-only design. Multiple sources
and joins are first-class because CSVQL's core workflow already supports
aliases and repeated table mappings.

## Product Boundary

This slice adds one interactive terminal frontend:

- `csvql menu`

It does not add:

- a web app
- a dashboard product
- safe-mode or sandbox behavior
- AI or natural-language SQL generation
- data editing
- hidden persistence
- hidden cache or materialization
- a second execution engine
- a replacement for existing CLI commands
- a change to the public `CSVQLSession` API

DuckDB continues to own SQL execution. CSVQL continues to own source
resolution, aliasing, output formatting, deterministic errors, docs, and tests.

## Command Contract

### `csvql menu`

Starts the TUI.

If the current working directory is inside a CSVQL project, the TUI should load
sources from the nearest `.csvql.yml` into the session. Loading project sources
does not imply mutation.

If no project catalog is found, the TUI starts with an empty source list and
offers an add-source flow.

### `csvql menu /path/file.csv`

Starts the TUI with one source preloaded.

The source alias should follow the same alias derivation and validation rules
used by existing single-file query behavior where practical. If the derived
alias is invalid or conflicts with another loaded alias, the TUI should ask for
an explicit alias rather than silently guessing.

### `csvql menu --table name=path`

Starts the TUI with one or more explicit source mappings.

The mappings should reuse existing table-mapping parsing and validation rules.
Duplicate aliases should fail clearly or force the user to resolve the conflict
before the session starts.

### Existing Root Behavior

Plain `csvql` should keep showing help. This slice should not change
`no_args_is_help=True` behavior in the existing Typer root app.

## TUI Model

The main screen is a source manager.

Recommended source table columns:

- alias
- display path
- status
- row-count status when known
- column count when known

Core actions:

- add CSV source
- remove session source
- inspect selected source
- sample selected source
- profile selected source
- run SQL against all loaded sources
- export last query result
- save session sources to project catalog
- quit

The TUI should make source aliases visible because aliases are the contract SQL
uses for joins.

## SQL Flow

The query screen should run trusted local SQL against all loaded session
sources.

Example:

```sql
SELECT *
FROM customers c
JOIN orders o USING (customer_id)
LIMIT 20;
```

The TUI should not attempt to parse, rewrite, or make user-authored SQL safe.
It should register the current session sources with DuckDB and run the SQL
through existing CSVQL query execution behavior.

Query output should be previewed in the TUI using the existing typed
`QueryResult` model. Export remains an explicit follow-up action.

## Persistence Rules

The default session is in-memory.

Actions that may write files must be explicit:

- `Save sources to project catalog` may create or update `.csvql.yml`
- `Export last result` may write a CSV, JSON, or Markdown output file

The TUI should show the target path before writing. Existing overwrite
protection and explicit force behavior should be reused for exports.

The first implementation may defer project-catalog save if needed, but the
design contract remains: no implicit project mutation.

## Python API Impact

The TUI should not change the public Python API contract.

The existing API remains:

- project-backed
- centered on `CSVQLSession.from_config(...)`
- thin over existing services
- suitable for scripts that load `.csvql.yml` and run repeatable workflows

The TUI may need its own internal session state object for in-memory sources.
That object should not be exported from `csvql.__init__` as public API in this
slice.

If future users need scriptable in-memory sources without `.csvql.yml`, that
should be designed separately as a deliberate public API, not added casually to
`CSVQLSession`.

## Dependency And Packaging Strategy

Textual should be treated as a TUI-specific dependency.

Recommended packaging shape:

- core install keeps existing CLI and Python API dependencies small
- `csvql[tui]` installs Textual support
- local development can continue using `uv sync --all-extras`

If `csvql menu` is invoked without Textual installed, the command should fail
with a clear message that tells the user to install the TUI extra. It should not
break `csvql query`, `csvql inspect`, `CSVQLSession`, or other core workflows.

## Internal Architecture

Keep `cli.py` thin.

Recommended file responsibilities:

`src/csvql/cli.py`
: add the `menu` command, parse startup arguments, and delegate to the TUI
  entrypoint.

`src/csvql/tui_app.py`
: own the Textual app shell, screen composition, navigation, and action
  dispatch.

`src/csvql/tui_state.py`
: own in-memory source state, selected source, last result, and explicit dirty
  state for session changes.

`src/csvql/tui_workflows.py`
: adapt existing CSVQL services for TUI actions such as inspect, sample,
  profile, query, export, and project-catalog loading.

Existing modules remain the behavior authority:

- `source_resolver.py` and table-mapping helpers for path and alias handling
- `inspection.py` for inspect and sample
- `profiling.py` for profile
- `query_workflow.py` and `engine.py` for SQL execution
- `export.py` for export formatting and overwrite behavior
- `project_config.py` for catalog loading and explicit save behavior
- `output.py` for table and JSON formatting where reused outside Textual

The TUI should consume typed result objects. It should not scrape CLI stdout.

## Error Handling

Errors should be shown inside the TUI as actionable messages, but they should
come from existing `CSVQLError` behavior where possible.

Expected examples:

- missing CSV path
- invalid alias
- duplicate alias
- DuckDB query failure
- missing project catalog
- export output already exists

The TUI should not hide failures or convert them into successful empty output.

## Testing Strategy

The implementation plan should include focused tests before broad TUI behavior.

Required proof points:

- `csvql menu --help` exposes the command without changing root help behavior
- startup argument parsing supports empty, single-path, and repeated
  `--table name=path` shapes
- session state stores multiple sources and rejects duplicate aliases
- inspect, sample, profile, and query workflows call existing services and
  return typed results
- query workflow supports joins across two loaded aliases
- export is explicit and preserves overwrite protection
- core Python API tests continue to pass unchanged
- core CLI commands continue to pass unchanged

If Textual supports practical app-level testing in the chosen version, add a
small smoke test for app startup and source-list rendering. Do not make the
entire feature depend on fragile terminal snapshot tests.

## Documentation Impact

Required docs updates during implementation:

- `README.md`: add a short TUI usage section
- `docs/ROADMAP.md`: record the TUI as post-v1 interactive workflow work if it
  lands after the local v1 release state
- optional failure-gallery entry only if the implementation creates a new
  deterministic user-facing failure mode

Docs must continue to state that CSVQL is for trusted local SQL and does not
make untrusted SQL safe.

## Success Criteria

- `csvql menu` is additive and does not change existing command behavior.
- Sources are session-only by default.
- Multiple CSV joins work through aliases.
- Explicit save/export actions are the only file-writing TUI actions.
- `CSVQLSession` remains project-backed and unchanged.
- Core install and Python scripting remain usable without the TUI dependency.
- The TUI reuses existing services instead of duplicating command logic.
- The implementation is covered by focused tests and the full local gate.

## Open Implementation Notes

The implementation plan should decide exact Textual widget choices, keyboard
bindings, and app layout. Those are implementation details as long as the source
manager, query flow, explicit persistence, and Python API boundary in this spec
remain intact.
