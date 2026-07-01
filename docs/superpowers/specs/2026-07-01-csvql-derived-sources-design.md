# CSVQL Derived Sources Design

Status: design approved in conversation; written spec review required before
implementation planning.

Date: 2026-07-01

## Purpose

This spec defines a focused follow-up to Workbench Lite: saving the last query
result as a derived source that can be queried and joined later.

The feature is meant to support exploratory local SQL workflows:

1. Load one or more CSV sources.
2. Run a query that produces a useful intermediate result.
3. Save that result under a table alias.
4. Query or join that alias in later SQL.

This is an explicit user action. It is not a hidden cache, automatic
materialization layer, dataframe framework, or new execution engine.

## Chosen Direction

The approved direction is **Derived Sources v1**.

Derived Sources v1 writes a successful tabular query result to a project-local
CSV file under `.csvql/results/`, then registers that file as a normal queryable
source in the current TUI session.

The saved alias appears in the existing Sources pane alongside original CSV
sources, but the pane must distinguish original file sources from derived query
results.

Example Sources pane shape:

```text
alias          kind      path
orders         csv       data/orders.csv
order_names    derived   .csvql/results/order_names.csv
```

The first slice uses CSV because CSVQL already owns CSV source resolution,
registration, export formatting, docs, and tests. Parquet, pandas, Polars, and
DuckDB scratch-database workflows remain later candidates.

## Product Boundary

Derived Sources v1 remains local-first CSVQL:

- DuckDB continues to own SQL execution.
- User-authored SQL remains trusted local SQL.
- Derived sources are written only after explicit user action.
- The stored artifact is a CSV file in `.csvql/results/`.
- The current TUI session registers the derived source immediately.
- Existing query, inspect, sample, profile, export, project catalog, and Python
  API contracts remain unchanged unless a later implementation plan explicitly
  touches them.

This design does not add:

- hidden cache or automatic materialization
- pandas or Polars dependencies
- Parquet source support
- a persistent DuckDB database
- a dataframe-first Python API
- safe-mode or sandbox behavior
- production-readiness or large-result guarantees
- catalog schema changes
- telemetry or query-history persistence

## User Workflow

Required first-slice workflow:

1. The user runs SQL in the TUI.
2. The query succeeds with a tabular `QueryResult`.
3. The user invokes **Save Result As Source**.
4. CSVQL prompts for an alias.
5. CSVQL validates the alias using the existing table-alias rules.
6. CSVQL writes `.csvql/results/<alias>.csv`.
7. CSVQL registers the written file as a source with kind `derived`.
8. The Sources pane refreshes and shows the derived source.
9. The user can reference the alias in later SQL.

Example:

```sql
SELECT id, name
FROM orders;
```

After saving as `order_names`, the user can run:

```sql
SELECT o.id, o.name, p.total
FROM order_names o
JOIN payments p USING (id);
```

The first slice should not require the user to choose a path every time. The
default location is project-local `.csvql/results/`.

## Project-Local Result Directory

Derived Sources v1 uses `.csvql/results/` as the default result directory.

Project-local root resolution:

- If the TUI started inside an existing `.csvql.yml` project, use that project
  root.
- If there is no project catalog, use the TUI `start_dir` as the local root.

CSVQL may create `.csvql/` and `.csvql/results/` when the user explicitly saves
a result. It must not create those directories on TUI startup or after ordinary
queries.

The stored path should be displayed relative to the local root when practical,
for example `.csvql/results/order_names.csv`. Internal execution should use a
resolved path.

## Source Model

The TUI source model needs to distinguish two concepts:

- where a source came from in the session, such as startup argument, catalog, or
  session action
- what kind of source it is, such as original CSV file or derived result

Recommended first-slice fields:

```python
SourceOrigin = Literal["argument", "catalog", "session"]
SourceKind = Literal["csv", "derived"]
```

Existing CSV inputs use kind `csv`.

Saved result sources use:

- `origin="session"`
- `kind="derived"`
- `path=<resolved .csvql/results/<alias>.csv path>`

The Sources pane should show alias, kind, path, and origin if space allows.
`kind` is the user-facing distinction that prevents derived query results from
looking identical to original files.

## Save Semantics

Save Result As Source should be available only when the current session has an
exportable tabular last result.

It must refuse:

- no prior successful tabular query
- final statement produced no tabular result
- last visible output came from inspect, sample, profile, or an error
- invalid alias
- alias already loaded in the current session
- output path already exists, unless explicit replacement is added in the same
  slice with a clear confirmation flow

Recommended v1 behavior is to refuse overwrites first. Replacement can be a
follow-up if the confirmation UI is awkward in Textual.

When save succeeds:

- write the CSV using the full stored last `QueryResult`, not the truncated
  result-grid display
- add the derived source to the current session
- select or highlight the derived source in the Sources pane
- keep the last result visible
- update status with the alias and path

Empty but tabular query results are valid. The output CSV should still include
headers.

## Query Semantics

Derived sources are registered through the same query path as other TUI
sources. The query workflow should not scrape CLI output or create a second SQL
execution path.

The first implementation may continue using the current short-lived
`CSVQLEngine` per query, as long as every current session source is registered
before execution. Because derived sources are CSV files on disk, later queries
can join them without a persistent in-memory connection.

This avoids pandas, Polars, and persistent DuckDB database lifecycle decisions
in the first slice.

## Catalog Behavior

Derived sources are session-visible immediately after save.

Saving them into `.csvql.yml` is not automatic. If the user later invokes the
existing Save Sources action, derived source paths may be persisted as ordinary
CSV table paths because the project catalog currently does not store source
kind metadata.

This is acceptable for the first slice if docs and help are explicit:

- immediate registration is session state
- durable file write happens at `.csvql/results/<alias>.csv`
- catalog persistence remains an explicit Save Sources action
- catalog reload may not preserve the `derived` kind unless a future catalog
  metadata design adds that contract

Do not change the catalog schema in this slice.

## UI And Keybindings

The TUI needs one new visible command:

- **Save Result As Source**

Recommended binding:

- `F11` if available and reliable in Textual terminals
- otherwise a source/result-specific letter binding that is inactive while the
  SQL editor is focused

The binding must be documented in the help modal and README if implemented.
Printable-key safety remains mandatory: letter actions must not fire while the
SQL editor is focused.

The prompt should ask for an alias, not a file path. The path is deterministic:
`.csvql/results/<alias>.csv`.

## Error Handling

Errors should use existing `CSVQLError` style with clear suggestions.

Expected messages:

- "Run a query before saving a result as a source."
- "The last statement did not produce a tabular result."
- "Source alias '<alias>' is already loaded in the TUI session."
- "Derived result already exists at <path>."
- "Failed to write derived source to <path>."

Failures must not register a partial source. If writing fails after creating
the directory, leave the directory in place but do not add a source entry.

## Documentation

README and TUI help should describe the workflow in plain terms:

- derived result sources are explicit
- result artifacts are written under `.csvql/results/`
- they can be queried and joined by alias
- they are CSV-backed in this slice
- they are not hidden cache
- SQL remains trusted local DuckDB SQL

Docs must not claim type preservation, Parquet performance, streaming, memory
safety, sandboxing, or production suitability.

## Internal Architecture

Recommended responsibilities:

`src/csvql/tui_state.py`
: Add source kind metadata and any last-result flags needed to know whether the
  result is eligible for derived-source saving.

`src/csvql/tui_workflows.py`
: Add a pure workflow helper that validates alias/path, writes the CSV artifact,
  and returns a `TUISource` for the derived result.

`src/csvql/tui_app.py`
: Own the prompt, binding, UI status updates, and Sources pane refresh.

`src/csvql/export.py`
: Reuse existing CSV result formatting where possible. Do not add a second CSV
  serialization path unless the existing export helper cannot satisfy empty
  result headers or deterministic newline behavior.

Possible new focused module:

- `src/csvql/tui_derived_sources.py` if the workflow logic would otherwise make
  `tui_workflows.py` too broad.

## Testing Strategy

Required tests:

- source kind defaults to `csv` for existing sources
- saving a tabular last result writes `.csvql/results/<alias>.csv`
- saved CSV includes headers and all stored rows
- saved result source is added to session state with kind `derived`
- Sources pane shows derived kind distinctly
- later queries can join a derived source with an original CSV source
- save refuses when no last query result exists
- save refuses after a no-result statement
- save refuses after error or non-query output clears exportable last result
- save refuses duplicate aliases
- save refuses existing output files unless replacement is explicitly designed
- save does not create `.csvql/results/` before the explicit action
- printable-key safety is preserved for any new keybinding
- README and help text agree on the command and storage location

Recommended verification:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py tests/test_tui_workflows.py tests/test_tui_app.py -q
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src
```

Manual proof should include launching `csvql menu`, running a query, saving the
last result as a derived source, confirming `.csvql/results/<alias>.csv` exists,
and running a later join against the derived alias.

## Acceptance Criteria

Derived Sources v1 is acceptable when:

- saving is explicit and never automatic
- the default write location is `.csvql/results/`
- derived aliases appear in the existing Sources pane
- derived sources are visually distinguishable from original CSV files
- saved aliases are immediately queryable in later TUI SQL
- saved aliases can join with original sources
- overwrites and duplicate aliases fail deterministically
- no pandas, Polars, Parquet, DuckDB scratch DB, or catalog schema expansion is
  introduced
- no hidden cache, sandbox, production-readiness, or large-result claims are
  added

## Explicitly Deferred

- Parquet-backed derived sources
- pandas or Polars dataframe helpers
- persistent DuckDB scratch databases
- configurable result directory
- overwrite confirmation and replacement, if not included in the first
  implementation
- catalog schema metadata for source kind
- saved-query plus derived-source lineage tracking
- source freshness or fingerprint history for derived results

## Open Implementation Decisions

These should be resolved in the implementation plan:

- exact keybinding for Save Result As Source
- whether overwrite replacement is included or deferred
- whether the Sources pane shows both `kind` and `origin` in the first layout
- whether `.csvql/results/` should be added to `.gitignore` in this slice
- whether manual proof should use a temporary project to avoid leaving local
  result artifacts in the repo
