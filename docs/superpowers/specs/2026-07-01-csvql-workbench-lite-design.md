# CSVQL Workbench Lite TUI Design

Status: design approved in conversation; written spec review required before
implementation planning.

Date: 2026-07-01

## Purpose

This spec defines the next CSVQL terminal UI slice after the initial
`csvql menu` implementation.

The current TUI proves that Textual can wrap CSVQL's existing local workflows,
but it still feels like a thin command wrapper. The next slice should make the
menu feel like a small local SQL workbench: a place where a user can load CSV
aliases, write SQL, run several queries in one session, inspect results, and
recover prior SQL without restarting.

This remains an additive TUI over existing CSVQL services. It does not change
the existing CLI command contracts, DuckDB execution posture, or public Python
API.

## Chosen Direction

The approved direction is **Workbench Lite**.

Workbench Lite borrows the useful shape of mature terminal tools without
turning CSVQL into a full database IDE:

- a source/catalog area that keeps loaded aliases visible
- a focused SQL editor
- a run/status bar
- a real results grid
- session query history
- visible help and keybinding discovery

The first Workbench Lite slice should prioritize the query loop. Source catalog
intelligence and editor power features are important follow-up work, but the
core loop must be pleasant first.

## Product Boundary

Workbench Lite is still local-first CSVQL:

- CSV files are the source format for this lane.
- DuckDB continues to own SQL execution.
- User-authored SQL remains trusted local SQL.
- Session state remains in memory unless the user chooses an explicit save or
  export action.
- Existing `inspect`, `sample`, `profile`, `query`, `export`, project catalog,
  and Python API behavior remain the behavior authority.

This design does not add:

- a web app
- a dashboard product
- AI or natural-language SQL generation
- safe-mode or sandbox behavior
- data editing
- hidden persistence
- hidden cache or materialization
- a second SQL execution engine
- a replacement for existing CLI commands
- a change to `CSVQLSession`

## First Slice: Query Loop

The first Workbench Lite implementation should fix the core interactive loop.

Required behavior:

- The SQL editor is the primary working pane.
- `Ctrl+Enter`, `Ctrl+J`, and `F4` run SQL.
- `Ctrl+J` exists because some terminals do not emit `Ctrl+Enter` reliably.
- Successful query results render in a navigable Textual `DataTable`, not as
  static formatted text.
- The status area shows row count and elapsed time after a successful query.
- Failed queries keep the user in the workbench, clear stale successful result
  state where appropriate, and show the error message and suggestion.
- Query history records successful and failed query attempts for the current
  session.
- The history view can reopen a prior query in the SQL editor.
- The history view can rerun a prior query without requiring a restart.
- `Ctrl+N` creates a fresh query working area or clears the current editor,
  whichever is simpler to ship cleanly in the first implementation.
- The user can run several queries back to back without losing the editor,
  source context, or navigation state.

The first slice may keep one SQL editor buffer if multiple buffers would make
the implementation fragile. The product requirement is a reliable repeated
query loop, not tabs for their own sake.

## Layout

The approved layout is a compact workbench:

- left side: sources and history
- right top: SQL editor
- right middle: run/status bar
- right bottom: results grid
- bottom footer: current keybindings and command discovery

Recommended first layout:

```text
+----------------------+------------------------------------------+
| Sources              | SQL Editor                               |
| payloads             | SELECT name, COUNT(*) AS rows            |
|   id                 | FROM payloads                            |
|   name               | GROUP BY name                            |
|   created_at         | LIMIT 20;                                |
|                      +------------------------------------------+
| History              | Run/status: F4/Ctrl+Enter/Ctrl+J Run     |
| 14:22 count payloads | 20 rows | 18 ms | F7 export | ? help     |
| 14:24 sample names   +------------------------------------------+
|                      | Results                                  |
|                      | name       | rows                        |
|                      | enerflo    | 1492                        |
|                      | standard   | 812                         |
+----------------------+------------------------------------------+
```

The first implementation may simplify source details if full column expansion
is not in scope yet. The source area still needs to keep aliases visible
because aliases are the SQL contract for joins.

## Navigation

The TUI should have a clear pane focus model.

Required shortcuts:

- `F2`: focus SQL editor
- `F5`: focus results
- `F6`: focus sources
- `F8`: focus history
- `F10`: toggle fullscreen for the focused pane if practical
- `?`: open help/keybindings
- `Esc`: close modals, search, or help and return to the previous pane
- arrow keys: move within the focused pane

The footer should show the useful active bindings for the current context. It
should not require the user to remember invisible modes.

The TUI should never trap the user in the result view. After running SQL, the
user must be able to immediately edit/run another query, navigate results, or
return to sources/history with predictable keys.

## Results Grid

Results should use a Textual `DataTable` or focused result-grid widget.

Required behavior:

- columns are visible as table headers
- rows are keyboard navigable
- large values do not break the whole layout
- empty result sets show a clear empty-state message
- result metadata includes row count and elapsed time
- export uses the existing explicit export workflow and last-result state

The first implementation should prefer a bounded preview over trying to render
huge result sets in full. CSVQL must not claim large-file or large-result TUI
performance without benchmark evidence.

## Query History

History is session-local in the first slice.

Each history item should include:

- timestamp or sequence number
- SQL text
- status: success or error
- row count when successful
- elapsed time when available
- short error text when failed

Required actions:

- focus history
- select previous/next history item
- reopen selected SQL in the editor
- rerun selected SQL

History should not write files by default. Persisted query history or saved SQL
files belong to a later query-persistence slice.

## Help And Discovery

The workbench needs a help surface.

Required behavior:

- `?` opens a keybindings/help screen.
- Help lists pane focus keys, query execution keys, history actions, source
  actions, result actions, export, save sources, and quit.
- `Esc` exits help and returns focus to the previous pane.
- The footer continues to show the highest-value contextual keys.

Textual's command palette can be used where it fits, but the first slice should
not depend on custom command-provider complexity unless it clearly reduces
implementation risk.

## Error Handling

Workbench errors should be local, visible, and recoverable.

Expected error cases:

- empty SQL
- no sources loaded
- invalid SQL
- unknown table alias
- DuckDB execution failure
- export path already exists
- source path no longer exists

Errors should come from existing `CSVQLError` behavior where possible. The TUI
should show both message and suggestion when available. It should not convert a
failure into an empty successful result.

## Responsiveness

Long-running query, inspect, profile, or export work should move toward Textual
workers so the interface does not freeze.

The first slice may implement workers for query execution immediately if the
implementation remains small. If workers are deferred, the implementation plan
must state that blocking behavior remains a known UX risk.

## Explicitly Sequenced Later

The following work is intentionally deferred from the first query-loop slice,
but it is not rejected:

### Source Catalog Intelligence

- expandable aliases and columns
- inferred type display
- row count and column count refresh
- insert alias into SQL
- insert column into SQL
- source or column context actions
- describe selected source

### Editor Quality

- run selected SQL
- run current statement
- line numbers
- find and go-to-line
- syntax highlighting if dependency cost is acceptable
- SQL formatting

### Query Persistence

- open `.sql` files in the editor
- save editor SQL to `.sql`
- named query buffers
- integration with existing project saved-SQL workflows

### Power User UX

- custom keymaps
- richer command palette
- configurable layout
- saved TUI preferences

These items should come back after the query loop is usable. They should deepen
CSVQL's local workbench experience without widening the product into a full
IDE, web app, or managed data platform.

## Still Out Of Scope

The following remain out of scope unless separately approved with new design
and proof:

- AI SQL generation
- safe-mode or sandbox claims
- untrusted SQL execution guarantees
- data editing
- hidden cache or materialization
- cloud connectors
- notebook framework
- web dashboard
- production-readiness claims

## Internal Architecture

Keep `cli.py` thin.

Recommended responsibilities:

`src/csvql/tui_app.py`
: own Textual composition, pane focus, keybindings, screens, and action
  dispatch. If this file grows too large, split pane widgets into focused
  modules instead of letting one app file absorb all behavior.

`src/csvql/tui_state.py`
: own in-memory session state, selected source, last result, query history,
  active pane, and optional buffer metadata.

`src/csvql/tui_workflows.py`
: continue adapting existing CSVQL services for inspect, sample, profile,
  query, export, and project catalog actions.

Possible new focused modules:

- `src/csvql/tui_history.py` for query-history records and helpers
- `src/csvql/tui_results.py` for result-grid population and formatting
- `src/csvql/tui_help.py` for help screen content

The TUI should consume typed result/error objects. It should not scrape CLI
stdout.

## Testing Strategy

The implementation plan should include focused tests before broad app changes.

Required proof points:

- run keys work from the SQL editor: `Ctrl+Enter`, `Ctrl+J`, and `F4`
- repeated queries work without restarting the TUI
- successful results populate a `DataTable`
- empty result sets show a clear state
- query failures record history and do not leave stale successful result state
- history records success and failure metadata
- history can reopen a prior query
- history can rerun a prior query
- pane focus shortcuts move to editor, results, sources, and history
- help opens and closes with predictable focus restoration
- export still uses explicit last-result behavior

Recommended verification:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src
```

Manual proof should include launching `csvql menu` against a real CSV, running
multiple queries, navigating results, reopening history, and exporting one
result explicitly.

## Acceptance Criteria

Workbench Lite query-loop implementation is acceptable when:

- `csvql menu` still starts with project, path, and repeated `--table` sources.
- The editor, sources, results, and history are reachable by documented keys.
- The user can run multiple SQL queries in one session without restarting.
- Results are navigable as a table.
- Query history is visible and useful in the current session.
- Errors are visible, recoverable, and do not masquerade as empty success.
- No implicit `.csvql.yml`, query-history, cache, or export file writes occur.
- Existing non-TUI CLI commands and the public Python API remain unchanged.
- Focused and full local verification passes.
