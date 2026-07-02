# CSVQL Editor Quality V2 Design

## Status

Design approved in conversation on 2026-07-02. Written spec review is required
before implementation planning.

Repo state at the design-writing baseline:

- Branch: `main`
- Pre-spec HEAD: `46b9ec5`
- Latest committed lane: Source Intelligence v1
- Tracked tree: dirty with uncommitted Editor Quality v2 draft work
- Untracked generated state: `.superpowers/`

The uncommitted Editor Quality work is useful draft evidence, but this spec is
the authority for the next implementation plan. The implementation plan must
review and reconcile that draft rather than assume it is already accepted.

## Goal

Make the optional TUI SQL editor safer to iterate in by running the SQL the user
means to run and by making repeated query runs easy to understand.

## Lane Position

Richard approved the v1 polish order as:

1. Source Intelligence v1.
2. Editor Quality v2.
3. Release Candidate Proof Packet.

Source Intelligence v1 is committed. This spec covers the remaining Editor
Quality v2 work. The Release Candidate Proof Packet waits until Editor Quality
v2 is implemented, verified, reviewed, and either committed or explicitly
stopped.

## Product Boundary

CSVQL remains a local-first Python CLI and package for querying local CSV files
through DuckDB. Editor Quality v2 improves the optional Textual TUI only.

User-authored SQL remains trusted local DuckDB SQL. This work must not claim or
add safe mode, sandboxing, security isolation, production readiness, hidden
cache, broad materialization, dataframe runtime, cloud connectors, web UI,
notebooks, AI, plugins, or large-file performance proof.

## Scope

Included:

- Run selected SQL from the editor when a non-empty selection exists.
- Otherwise run the current semicolon-delimited statement around the cursor.
- Preserve a whole-editor run path for users who want the previous behavior.
- Make status and history text distinguish run modes clearly.
- Keep history reopen and rerun behavior focused and predictable.
- Update in-app help and README keymap text.
- Add focused automated tests for editor SQL selection, run modes, status,
  history, rerun behavior, docs/help text, and common SQL delimiter edge cases.
- Run a manual TUI proof for selected/current statement, whole-editor run, and
  history rerun ergonomics.

Excluded:

- CLI command changes.
- Python API changes.
- DuckDB engine changes.
- Project catalog schema changes.
- Persisted query history.
- Cursor-exact source insertion changes.
- SQL formatter.
- SQL autocomplete.
- SQL parser replacement.
- Syntax highlighting.
- Line numbers.
- Multi-cursor editing.
- Any product scope outside the optional TUI.

Line numbers and syntax highlighting are intentionally deferred. They are
editor-visual features, not required to close the run/repeat ambiguity that
blocks this lane.

## User Experience

The TUI should expose three query-run paths:

1. `F4` / `Ctrl+Enter`: **Run SQL**.
   - If the editor has selected text after trimming whitespace, run that SQL.
   - If there is no selected SQL, run the current statement around the cursor.
2. `F12`: **Run All**.
   - Run the whole editor buffer after trimming whitespace.
3. History pane `r`: **Rerun**.
   - Rerun the selected history item's stored SQL against the current session
     sources.

History pane `Enter` remains **Open query**. It loads the selected history SQL
into the editor and focuses the editor, but it does not run SQL by itself.

The visible language should avoid ambiguity:

- Running selected/current SQL should say `Running SQL query N...`.
- Running the full editor should say `Running editor query N...`.
- Rerunning a history item should say `Rerunning query N as query M...`.
- Successful, no-result, and error statuses should still report the actual
  outcome and preserve existing result/export behavior.

The footer and help text should make `F4` the reliable run fallback because
terminal handling for `Ctrl+Enter` varies. `F12` should be documented as the
whole-editor run path.

## Current Statement Contract

The current statement selector should be small and deterministic. It is not a
full SQL parser.

Required behavior:

- Split statements on semicolons that are not inside:
  - single-quoted string literals;
  - double-quoted identifiers;
  - line comments;
  - block comments.
- Return the trimmed statement containing the cursor.
- If the cursor is on whitespace after a semicolon, fall back to the nearest
  previous non-empty statement.
- If no non-empty current statement exists, return an empty string so existing
  empty-SQL handling can show `Enter SQL before running a query.`

Out of scope:

- Dialect-complete SQL parsing.
- Dollar-quoted strings.
- Nested block comments.
- Semantic validation before DuckDB execution.

This contract keeps the feature useful for normal TUI iteration while avoiding
a broad parser dependency or false correctness claim.

## History And Repeatability Contract

Query history remains session-local and in-memory only.

Each recorded query attempt should retain the SQL that was actually submitted
to DuckDB. Add a small TUI-local run mode field rather than inferring from SQL
text.

Allowed run modes:

- `sql`: selected/current statement via `F4` or `Ctrl+Enter`.
- `editor`: whole-editor run via `F12`.
- `rerun`: rerun from the history pane.

The history table should stay compact and add one visible `run` column. The
columns should be `seq`, `run`, `status`, `rows`, and `sql`.

Rerun behavior:

- `r` only works when the History pane is focused.
- Rerun uses the selected history item's stored SQL, not the current editor
  buffer.
- Rerun may load that SQL into the editor as a convenience, but the run source
  must be the stored history SQL.
- Rerun records a new history item with the new sequence and outcome.
- Rerun uses current session sources, matching existing TUI behavior.

## Architecture

Keep the existing TUI boundaries:

- `src/csvql/tui_editor.py` owns editor SQL selection helpers.
- `src/csvql/tui_state.py` owns session-local query history and run state.
- `src/csvql/tui_app.py` owns Textual bindings, focus gating, visible status,
  history table rendering, and worker scheduling.
- `src/csvql/tui_help.py` owns in-app help text.
- `README.md` owns user-facing keymap documentation.

Expected implementation shape:

- Add or keep a focused editor helper:

  ```python
  def selected_or_current_sql(
      text: str,
      *,
      cursor_location: tuple[int, int],
      selected_text: str,
  ) -> str:
      """Return selected SQL, or the current semicolon-delimited statement."""
  ```

- Keep query execution in existing TUI workflow and engine layers.
- Keep `cli.py` untouched.
- Do not persist new editor or history metadata to disk.
- Keep changes local to TUI state/app/help/editor helpers, tests, and README.

Add a `TUIQueryRunMode` literal type and a `run_mode` field to
`TUIQueryHistoryItem`. The field should default to `sql` so existing direct
test construction remains simple. Do not introduce a broad event system or
history persistence model.

## Error Handling

Use existing TUI error display through `CSVQLError`.

Required behavior:

- Empty selected/current SQL and empty whole-editor SQL both surface:
  `Enter SQL before running a query.`
- No loaded sources still surfaces:
  `No sources loaded.`
- A query already in progress still surfaces:
  `Query already running.`
- DuckDB execution errors remain normal query errors and are recorded in
  history.

Changing the run mode must not change trusted-local-SQL posture. CSVQL should
not pre-screen SQL for safety or restrict DuckDB capabilities in this lane.

## Tests

Focused tests should cover:

- Selected SQL wins over current statement.
- Current statement is selected by cursor position.
- Semicolons inside single quotes do not split statements.
- Semicolons inside double-quoted identifiers do not split statements.
- Semicolons inside line comments and block comments do not split statements.
- Cursor after a trailing semicolon uses the previous non-empty statement.
- `F4` runs selected/current SQL and can skip an earlier failing statement.
- `F12` runs the whole editor buffer and preserves prior whole-editor behavior.
- History `Enter` reopens without running.
- History `r` reruns the stored history SQL, not whatever is currently in the
  editor.
- Status or history text distinguishes `Run SQL`, `Run All`, and rerun.
- Help and README document the keymap accurately.

The relevant automated gate should include at least:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_editor.py tests/test_tui_state.py tests/test_tui_workflows.py tests/test_tui_results.py tests/test_tui_app.py tests/test_cli_menu.py -q
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest
git diff --check
```

## Manual TUI Proof

Before calling Editor Quality v2 complete, run a local TUI proof against a
small checked-in example CSV.

Required proof:

1. Launch `csvql menu` with a sample CSV.
2. Put two statements in the editor where the first statement would fail and
   the second statement succeeds.
3. Place the cursor in the second statement and press `F4`.
4. Confirm only the current statement runs successfully.
5. Press `F12`.
6. Confirm the whole editor runs and surfaces the expected first-statement
   failure.
7. Reopen a history item with `Enter`.
8. Rerun a history item with `r`.
9. Confirm status/history language makes run source clear.

Proof notes should mention terminal caveats plainly: `F4` is the reliable run
fallback, `Ctrl+Enter` and function keys can vary by terminal, and synthetic
PTY key bursts can race compared with ordinary standalone key use.

## Completion Criteria

Editor Quality v2 is complete when:

- The selected/current statement and whole-editor run paths are implemented.
- One narrow repeated-query ergonomics slice is implemented.
- Help and README match runtime behavior.
- Focus gating keeps printable history/source actions out of the SQL editor.
- Automated gates pass.
- Manual TUI proof passes with caveats recorded.
- A code-review pass finds no blocking issues.
- `.superpowers/` remains untracked unless Richard explicitly approves tracking
  generated Superpowers state.

After completion, the next lane is the Release Candidate Proof Packet. That
packet should not add product scope. It should run the manual QA matrix,
refresh benchmark proof or cite same-HEAD benchmark artifacts where valid, and
produce a release-candidate eligibility note while keeping status language
conservative until proof passes on the final intended HEAD.
