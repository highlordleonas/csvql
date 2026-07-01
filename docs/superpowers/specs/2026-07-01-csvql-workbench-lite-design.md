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
- `Ctrl+Enter` and `F4` run the whole editor contents.
- `F4` is the reliable fallback because some terminals do not emit
  `Ctrl+Enter` reliably.
- Successful query results render in a navigable Textual `DataTable`, not as
  static formatted text.
- The status area shows row count and elapsed time after a successful query.
- Failed queries keep the user in the workbench, clear stale successful result
  state where appropriate, and show the error message and suggestion.
- Query history records successful and failed query attempts for the current
  session.
- The history view can reopen a prior query in the SQL editor.
- The history view can rerun a prior query without requiring a restart.
- `Ctrl+N` clears the editor for a new query while keeping history and the last
  result view visible.
- The user can run several queries back to back without losing the editor,
  source context, or navigation state.

The first slice may keep one SQL editor buffer if multiple buffers would make
the implementation fragile. The product requirement is a reliable repeated
query loop, not named buffers or tabs.

## Query Execution Semantics

The first Workbench Lite slice runs the whole SQL editor contents.

The run action should be labeled **Run Editor** or equivalent in help, footer,
and status text. It should not be labeled in a way that implies IDE-style
current-statement or selected-SQL execution.

When the user invokes Run Editor with `Ctrl+Enter` or `F4`, the TUI should:

- read the complete editor text
- trim leading and trailing whitespace for empty-query detection
- pass the editor text through the existing CSVQL query workflow
- register all currently loaded session sources before execution
- display the `QueryResult` returned by the existing workflow

The first slice should not implement selected-SQL execution or current-statement
execution. If the editor has a selection, the run action still runs the whole
editor. This is deliberate: robust statement-boundary behavior should be
designed with editor semantics and DuckDB behavior instead of guessed as part
of the initial workbench loop.

Multiple SQL statements are passed through to the existing DuckDB-backed query
execution behavior. The TUI displays the final `QueryResult` returned by CSVQL.
It should not add its own transaction wrapper, SQL parser, statement splitter,
or safety layer.

If an earlier statement fails, the run fails. The worker should return a typed
error, history should record an error item, stale last-result state should be
cleared, export should be disabled, and the result panel/status should show the
error message and suggestion where available.

If the final statement completes successfully but does not produce a tabular
result, such as DDL, DML, `COPY`, or `CREATE TABLE`, the run is still a
successful history item with a `no_result` outcome. Prior last-result state
should be cleared, export should be disabled, and the result panel/status
should show a clear message such as "Statement completed; no tabular result to
display." It should not leave a previous query result visible as if it belonged
to the no-result statement.

`no_result` is a TUI-local worker/result outcome wrapper. It does not change
the public `QueryResult` model, existing CLI behavior, existing JSON/table
contracts, or the `CSVQLSession` API unless a separate design explicitly
approves that change.

Follow-up editor-quality work should add explicit actions for:

- run selected SQL
- run current statement
- run whole editor

Those actions should have distinct labels and tests so users never have to
guess which SQL was executed.

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
| History              | Run/status: F4/Ctrl+Enter Run Editor     |
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

The Workbench keymap should reconcile the current MVP function-key actions with
the new pane-oriented layout. The first Workbench slice should prefer
focus-aware commands over global single-letter actions so normal typing in the
SQL editor remains safe.

Recommended global bindings:

| Intent | Current MVP binding | Workbench first-slice binding |
| --- | --- | --- |
| Run editor | `F4`, `Ctrl+Enter` | `F4`, `Ctrl+Enter` |
| New query | `F10`, `Ctrl+N` | `F10`, `Ctrl+N` |
| Export last result | `F7` | `F7` |
| Quit | `F9`, hidden `q` | `F9`, hidden `q` |
| Focus SQL editor | `Ctrl+Down` | `F2`, `Ctrl+Down`, non-editor `Tab` cycle |
| Focus results | none | `F5`, non-editor `Tab` cycle |
| Focus sources | `Ctrl+Up` | `F6`, `Ctrl+Up`, non-editor `Tab` cycle |
| Focus history | none | `F8`, non-editor `Tab` cycle |
| Help/keybindings | none | `F1` globally, `?` outside SQL editor |

Recommended focus-specific source actions:

| Intent | Current MVP binding | Workbench first-slice binding |
| --- | --- | --- |
| Inspect source | `F1` | `i` while sources are focused |
| Sample source | `F2` | `s` while sources are focused |
| Profile source | `F3` | `p` while sources are focused |
| Add source | `F5` | `a` while sources are focused |
| Remove source | `F6` | `d` while sources are focused |
| Save sources | `F8` | `w` while sources are focused |

Recommended focus-specific history actions:

| Intent | Workbench first-slice binding |
| --- | --- |
| Reopen selected query in editor | `Enter` |
| Rerun selected query | `r` |

Other required navigation behavior:

- `Tab` and `Shift+Tab` may cycle panes only when the SQL editor is not
  focused.
- While the SQL editor is focused, `Tab` is reserved for editor text input or
  indentation behavior. If indentation is not implemented in the first slice,
  the app still must not steal `Tab` for pane cycling from the focused editor.
- `Esc` closes modals, search, or help and returns to the previous pane.
- Arrow keys move within the focused pane.
- `F10` may toggle fullscreen only if it does not conflict with the accepted
  `F10`/`Ctrl+N` new-query behavior; otherwise fullscreen should be deferred.

The footer should show the useful active bindings for the current context. It
should not require the user to remember invisible modes.

The TUI should never trap the user in the result view. After running SQL, the
user must be able to immediately edit/run another query, navigate results, or
return to sources/history with predictable keys.

## Text Entry Safety

Printable keys must be safe while the SQL editor is focused.

While the SQL editor is focused, printable characters must type into SQL, not
trigger app actions. This includes `?`, `q`, `i`, `s`, `p`, `a`, `d`, `w`, and
`r`.

Source and history letter actions apply only when their panes are focused. The
hidden `q` quit binding must not fire while SQL text entry owns focus. If bare
`?` cannot be made safe in the SQL editor, help must use only a non-printable
binding such as `F1` while the editor is focused.

## Results Grid

Results should use a Textual `DataTable` or focused result-grid widget.

Required behavior:

- columns are visible as table headers
- rows are keyboard navigable
- horizontal scrolling is supported for wide result sets
- large values do not break the whole layout
- empty result sets show a clear empty-state message
- result metadata includes row count and elapsed time
- export uses the existing explicit export workflow and last-result state
- the grid displays at most 1,000 rows by default
- the grid labels capped output clearly, such as "showing first 1,000 of
  12,345 returned rows"
- cell display text is truncated for layout, with a first-slice target of 120
  visible characters per cell
- truncation affects only the grid display, not the stored query result

The first implementation should treat the row cap as a display cap, not a new
query-execution guarantee. CSVQL's existing `QueryResult` may still hold the
full query result in memory. Users should use SQL `LIMIT` for large exploratory
queries until streaming or preview-limited execution is deliberately designed.
Any row-count label refers only to rows present in the stored `QueryResult`; it
must not imply a source-table count, table scan, or knowledge of rows that were
not returned by the query workflow.

The first slice should not cap visible columns by silently dropping them.
Instead, the result grid should support horizontal scrolling for columns that do
not fit in the terminal. This is a usability requirement for ordinary wide
results, not a claim that CSVQL handles arbitrary wide CSVs well.

Export should write the stored last `QueryResult`, not the truncated grid
display. In the first slice, that means export writes the full result returned
by the existing query workflow. If a future implementation changes query
execution to fetch only a preview, the export contract must be revisited and
documented before shipping.

CSVQL must not claim large-file, large-result, streaming, or memory-safe TUI
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

Rerunning a history item uses the current session sources. History stores SQL
and run metadata, not a snapshot of the original source state. If aliases are
missing, removed, or changed since the original run, normal current-session
query errors apply.

History should not write files by default. Persisted query history or saved SQL
files belong to a later query-persistence slice.

History privacy rules:

- no query history persistence by default
- no history file writes
- no logs containing SQL or query-history records
- no telemetry
- history clears when the TUI process exits
- SQL and error text may include local paths, private identifiers, or sensitive
  business terms, so help text and docs should describe history as local
  in-memory session state only

## Help And Discovery

The workbench needs a help surface.

Required behavior:

- `F1` opens a keybindings/help screen from any pane and is the primary global
  help key.
- `?` opens help only when a non-editor pane is focused and remains documented
  as a fallback because some terminals intercept function keys.
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

Query execution must use a Textual worker in the first Workbench Lite slice so
the interface does not freeze while DuckDB runs.

Required behavior:

- entering a running state updates the status bar
- the run action should not launch overlapping query workers
- each run gets a monotonically increasing sequence id
- workers return typed success, no-result, or error outcomes
- UI mutation happens on the Textual app/UI thread
- worker success updates result state, result grid, status, and history
- worker failure updates error state, status, and history
- stale worker outcomes must be ignored if a newer run sequence has superseded
  them
- cancellation may be deferred if DuckDB cancellation is not already supported
  cleanly
- quitting during an active query worker is allowed
- quitting during an active query exits the app, persists no history, and writes
  no files unless an explicit export or save action already completed
- no cancellation guarantee is claimed for active DuckDB work in the first slice

Inspect, profile, and export workers may be sequenced after query workers unless
the implementation touches those paths heavily. If they remain synchronous, the
implementation plan must record that as a known UX risk.

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

Recommended internal state contracts:

`TUIFocusPane`
: enum or `Literal` for `sources`, `editor`, `results`, `history`, and modal or
  help states where needed. The app should use this instead of scattered string
  checks.

`TUIQueryHistoryItem`
: immutable record for one query attempt. Recommended fields: `sequence`,
  `sql`, `status`, `row_count`, `elapsed_ms`, `error_message`, and
  `created_at` or monotonic session timestamp. It is session-local only.

`TUIResultViewState`
: state for the visible result grid. Recommended fields: `columns`,
  `display_rows`, `total_row_count`, `preview_row_cap`, `cell_char_cap`,
  `is_truncated`, and `source_result_id` or sequence link back to the stored
  last result.

`TUIQueryRunState`
: state for active execution. Recommended fields: `is_running`, active worker
  id or handle, started timestamp, and SQL sequence. This prevents overlapping
  runs and stale worker results from updating the wrong view.

These contracts should keep `tui_app.py` from becoming state soup. The app may
own composition and event dispatch, but durable behavior should sit in typed
state helpers that can be tested without running the full Textual app.

The TUI should consume typed result/error objects. It should not scrape CLI
stdout.

## Skill Activation Contract

Before implementation, read `AGENTS.md`, this spec, current TUI source/tests,
and the relevant skill files.

If this spec conflicts with `AGENTS.md` or higher-priority repo instructions,
those instructions win unless the user explicitly approves a spec revision.

Required skills by change type:

- Python modules, Textual app code, typing, packaging, or tests:
  `python-codebase-standards`
- SQL execution, DuckDB behavior, table aliasing, CSV path handling, or
  trusted/untrusted SQL boundaries:
  `python-codebase-standards` and `security-best-practices`
- TUI UX, keybindings, help text, README, roadmap, or user-facing errors:
  `documentation` or `readme`
- Test strategy, Textual app tests, regression coverage, or manual proof:
  `testing-strategy` or `qa-test-planner`
- Long-running queries, result-size behavior, workers, or performance claims:
  `performance-engineering`
- Implementation planning is mandatory before implementation and must use:
  `superpowers:writing-plans`
- Implementation work:
  `superpowers:test-driven-development`
- Debugging broken TUI behavior:
  `superpowers:systematic-debugging`
- Completion claim:
  `superpowers:verification-before-completion`

If a required skill is unavailable, stop and state the missing skill unless the
user explicitly approves a fallback.

## Testing Strategy

The implementation plan should include focused tests before broad app changes.

Required proof points:

- run keys work from the SQL editor: `Ctrl+Enter` and `F4`
- run keys execute the whole editor text, not a hidden selected/current
  statement mode
- run labels/help say "Run Editor" or equivalent
- `Ctrl+N` clears the editor while leaving history and last result view visible
- printable SQL text keys do not trigger app actions while the editor is
  focused
- `Tab` does not cycle panes while the editor is focused
- repeated queries work without restarting the TUI
- successful results populate a `DataTable`
- final no-result statements clear stale results, disable export, and record a
  successful no-result history item
- earlier statement failures record an error, clear stale results, and disable
  export
- empty result sets show a clear state
- result display caps rows and truncates wide cells without mutating the stored
  result
- result row-count labels refer to returned rows, not total source rows
- wide result columns remain reachable through horizontal scrolling
- query failures record history and do not leave stale successful result state
- history records success and failure metadata
- history can reopen a prior query
- history can rerun a prior query
- history reruns use current session sources and surface normal errors when
  aliases have changed
- pane focus shortcuts move to editor, results, sources, and history
- help opens and closes with predictable focus restoration
- query workers use sequence ids and ignore stale outcomes
- quitting during an active query exits without persisting history or creating
  implicit files
- export still uses explicit last-result behavior
- `csvql menu --help` remains accurate
- plain `csvql` behavior remains unchanged
- README and in-TUI help document the accepted Workbench keymap

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
- `csvql menu --help` documents startup arguments and does not regress.
- Plain `csvql` still shows the existing root help behavior.
- The editor, sources, results, and history are reachable by documented keys.
- README and TUI help agree on the Workbench keymap.
- The user can run multiple SQL queries in one session without restarting.
- `Ctrl+N` clears the editor for a new query without hiding history or the last
  result view.
- Run commands execute the whole editor text in the first slice.
- Run commands are visibly labeled as whole-editor execution.
- Printable keys type into SQL while the editor is focused.
- Final no-result statements and earlier statement failures have deterministic
  history, result-state, export, panel, and status behavior.
- Query workers cannot update the UI with stale superseded results.
- Results are navigable as a table.
- Result display is capped and wide cells are truncated without changing export
  data.
- Wide result columns remain reachable through horizontal scrolling.
- Query history is visible and useful in the current session.
- Query history remains in memory only, clears on quit, and is not logged or
  persisted by default.
- History reruns use current session sources, not source snapshots.
- Quitting during active query work does not create implicit history, save, or
  export files.
- Errors are visible, recoverable, and do not masquerade as empty success.
- No implicit `.csvql.yml`, query-history, cache, or export file writes occur.
- Existing non-TUI CLI commands and the public Python API remain unchanged.
- Focused and full local verification passes.
