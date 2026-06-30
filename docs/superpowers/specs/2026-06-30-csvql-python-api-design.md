# CSVQL Small Python API Design

Date: 2026-06-30

## Purpose

This spec defines the small Python API slice inside CSVQL v0.8 portfolio polish.

The goal is to expose a thin, stable library surface over the same trusted local
project workflows that the CLI already proves:

- project-config-backed SQL execution
- saved SQL execution
- profiling
- configured checks

This slice should strengthen the CSVQL wedge as a local-first automation tool
without turning CSVQL into a Python data framework.

## Approved Direction

The Python API should be:

- project-config-only for v1
- centered on `CSVQLSession.from_config(...)`
- thin over existing internals
- based on short-lived execution per method
- aligned with the existing `CSVQLError` hierarchy
- small enough to be documented and stabilized without inventing a second
  runtime model

The API should not introduce a dataframe layer, notebook-oriented helpers,
plugins, async execution, query builders, ad hoc direct-path session modes, or a
second execution engine.

## Public API Surface

The approved public entrypoint is one session type exposed from the package:

- `CSVQLSession.from_config(start_dir: str | Path = ".") -> CSVQLSession`
- `session.query(sql: str) -> QueryResult`
- `session.run_file(path: str | Path) -> QueryResult`
- `session.profile(table: str) -> ProfileResult`
- `session.check(table: str | None = None, show_failures: bool = False, failure_limit: int = 5) -> CheckRunResult`

Return types should reuse the existing typed result objects already used by the
CLI-backed services:

- `QueryResult`
- `ProfileResult`
- `CheckRunResult`

This slice does not add:

- `inspect()` or `sample()` methods
- config mutation helpers such as `init`, `add`, or `tables`
- export helpers
- JSON formatter helpers
- custom API-only result wrappers unless an existing result type proves
  insufficient during implementation

## Session Boundary

`CSVQLSession` stores resolved project context, not a live DuckDB connection.

That means:

- `from_config(...)` discovers and loads the nearest `.csvql.yml` exactly like
  the CLI project-backed flows
- the session keeps the resolved `ProjectContext`
- each public method performs short-lived work against that stored context
- there is no `close()` requirement in this slice because the session does not
  own a long-lived engine

This avoids stale table-registration state, file-change invalidation rules, and
a second behavior model that diverges from the CLI.

## Runtime Semantics

### `from_config(start_dir=".")`

- discovers the nearest project rooted at `start_dir`
- stores the resolved `ProjectContext`
- raises the existing project/config errors if discovery or config loading
  fails

### `query(sql)`

- runs SQL against the session's configured project tables
- does not support ad hoc `--table` style mappings
- uses the same trusted local SQL posture as the CLI

### `run_file(path)`

- resolves the SQL file relative to the stored project root, not the caller's
  current working directory
- uses the same saved-SQL loading rules as the CLI
- runs against the session's configured project tables

### `profile(table)`

- accepts only a configured table alias from the stored project context
- resolves that table through existing project config helpers
- returns the existing `ProfileResult`

### `check(table=None, show_failures=False, failure_limit=5)`

- mirrors the existing configured-check workflow
- returns `CheckRunResult`
- does not raise a special API exception just because checks failed
- uses result status as the contract for pass/fail checks

## Error Contract

The Python API should reuse the current `CSVQLError` family directly.

That means:

- missing or invalid project config keeps raising existing config exceptions
- invalid SQL keeps raising the current query execution exception
- missing or unreadable saved SQL keeps raising the current SQL file exception
- invalid or missing configured table aliases keep raising current project or
  inspection/config exceptions as appropriate

This slice should not introduce a second API-only exception hierarchy unless the
existing exceptions prove unusable during implementation. The default assumption
is that one error contract is better than two overlapping ones.

## Internal Architecture And File Boundaries

The implementation should add one thin public wrapper module:

- `src/csvql/api.py`

Responsibilities of `api.py`:

- define `CSVQLSession`
- own no CLI formatting
- own no exit-code behavior
- orchestrate existing internal services from a library-facing boundary

Supporting modules should remain the execution authority:

- `project_config.py` for project discovery and loading
- `query_workflow.py` for catalog-backed query execution
- `sql_file.py` for saved SQL loading
- `profiling.py` for full-scan profiling
- `checks.py` for configured checks
- `engine.py` for short-lived DuckDB execution

Likely thin extractions are acceptable if needed:

- a context-based query helper that runs catalog-backed SQL from an existing
  `ProjectContext` instead of rediscovering config from `cwd`
- a small project-table lookup helper for API-side alias resolution

These extractions should stay narrow and should improve reuse rather than create
an alternate workflow stack.

## Testing Strategy

Add one focused API test module, likely `tests/test_api.py`.

Required proof points:

- `CSVQLSession.from_config()` discovers and stores the expected project
- `query()` returns `QueryResult` from configured project tables
- `run_file()` resolves SQL file paths relative to the stored project root
- `profile()` returns `ProfileResult` for a configured table alias
- `check()` returns `CheckRunResult` for both passing and failing check cases
- existing `CSVQLError` subclasses propagate unchanged for:
  - missing config
  - bad SQL
  - missing SQL file
  - invalid table alias

This slice should rely on focused library tests first. It should not require
new CLI behavior changes to prove the API.

## Documentation Impact

Required docs updates:

- `README.md`: add one short Python API usage example
- `docs/ARCHITECTURE.md`: document `api.py` as a thin wrapper over existing
  services

This slice does not include:

- failure-gallery documentation
- notebook examples
- separate JSON contract docs for API results

## Explicit Non-Goals

This design explicitly excludes:

- direct-path or ad hoc non-project sessions
- persistent session-level DuckDB connections
- `inspect()` and `sample()` methods in this slice
- config mutation helpers
- export helpers
- API-specific JSON helpers
- dataframe, notebook, async, plugin, or cloud-facing behavior
- any second execution engine

## Success Criteria

- The API remains project-config-only and small.
- Public methods reuse CLI-tested internals rather than duplicating them.
- The library surface returns existing typed results where possible.
- The existing `CSVQLError` family remains the error contract.
- The behavior is deterministic relative to stored project context rather than
  ambient `cwd`.
- The implementation can be documented and tested without widening product
  scope.
