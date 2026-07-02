# CSVQL TUI Error Recovery Polish Design

## Status

Design approved in conversation on 2026-07-02. Written spec review is required
before implementation planning.

Repo state at the design-writing baseline:

- Branch: `main`
- Pre-spec HEAD: `7c4c296 docs: record release candidate proof`
- Tracked tree: clean
- Current release posture: `release-candidate eligible` as a local assessment,
  not a release, tag, publish, upload, or `v1-stable` action

## Goal

Make the optional TUI recover predictably from rejected query-run actions by
preserving the previous successful result when no query actually ran.

## Lane Position

This is a narrow product-polish slice after Source Intelligence v1, Editor
Quality v2, and release-candidate eligibility proof. It intentionally pauses
release promotion while tightening one real TUI workflow risk.

After this slice is implemented, verified, reviewed, and either committed or
explicitly stopped, Richard can decide whether to return to release-candidate
status work.

## Product Boundary

CSVQL remains a local-first Python CLI and package for querying local CSV files
through DuckDB. This work improves only the optional Textual TUI.

User-authored SQL remains trusted local DuckDB SQL. This work must not claim or
add safe mode, sandboxing, security isolation, production readiness, hidden
cache, broad materialization, dataframe runtime, cloud connectors, web UI,
notebooks, AI, plugins, or large-file performance proof.

## Problem

The TUI currently treats some rejected run actions like destructive outcomes.
For example, pressing run with empty SQL can clear the previous successful
result before any query is submitted to DuckDB.

That is poor recovery behavior. A harmless user mistake should not remove a
useful result, export/save eligibility, or the visible result grid. Actual query
outcomes should still replace or clear result state according to what happened.

## Scope

Included:

- Preserve the previous successful result when a run action is rejected before a
  query starts.
- Make rejected-run status text say that no query ran and that the previous
  result remains available when one exists.
- Keep rejected runs out of query history.
- Keep `run-status` returning to `Ready.` after rejected runs.
- Add focused Textual app tests for rejected-run recovery behavior.

Excluded:

- CLI command changes.
- Python API changes.
- DuckDB engine changes.
- Project catalog schema changes.
- Persisted query history.
- New TUI panes, modals, or layout changes.
- Cancellation support.
- Retry buttons.
- SQL parsing or validation changes.
- Error-recovery suggestions based on DuckDB error content.
- New manual proof, benchmark, release-readiness, or release status work.

## Recovery Contract

The TUI should distinguish rejected runs from completed runs.

Rejected runs happen before DuckDB execution begins:

- Empty SQL.
- No sources loaded.
- Query already running.
- Unable to schedule a query run.

For rejected runs:

- Do not clear `state.last_result`.
- Do not clear `state.result_view`.
- Do not clear the visible results grid.
- Do not change `state.last_result_status`.
- Do not add a query-history item.
- Reset `#run-status` to `Ready.`.
- Show the rejection reason.
- If a previous result exists, include `Previous result is still available.` in
  the status and result-message surfaces.

Completed runs have reached the query outcome path:

- Success replaces the previous result.
- No-result clears export/save eligibility and records a `no_result` history
  item.
- DuckDB/user SQL errors clear export/save eligibility and record an `error`
  history item.
- Unexpected worker failures clear export/save eligibility and record an
  `error` history item.

This keeps stale-result risk low. A result remains exportable only when no new
query actually ran.

## User Experience

When a rejected run happens and a previous result exists, the user should see:

```text
Error: Enter SQL before running a query.
Suggestion: Type SQL in the editor and try again. Previous result is still available.
```

Equivalent wording should apply to missing sources, already-running query, and
scheduling failure. The exact rejection reason should remain specific.

When no previous result exists, existing rejection messages can stay concise:

```text
Error: Enter SQL before running a query.
Suggestion: Type SQL in the editor and try again.
```

The result table should remain visually stable after a rejected run when a
previous result exists. The result-message panel should also retain or restate
that the previous result remains available instead of implying an empty or
failed result.

## Architecture

Keep existing boundaries:

- `src/csvql/tui_app.py` owns Textual actions, status surfaces, visible result
  grid behavior, and worker scheduling.
- `src/csvql/tui_state.py` owns query-result, history, and active-run state.
- `tests/test_tui_app.py` owns Textual app behavior tests.

Expected implementation shape:

- Add a small helper inside `CSVQLMenuApp`, named
  `_show_rejected_run(error: CSVQLError) -> None` or an equivalent local name
  with the same responsibility.

- The helper should:
  - reset `#run-status` to `Ready.`;
  - preserve result state and the result grid;
  - append `Previous result is still available.` to the suggestion when
    `self.state.last_result is not None`;
  - update both the top status and results-message surfaces through existing
    status/error display paths or a small local variant;
  - focus the SQL editor after rejection when that matches current run behavior.

- Use the helper for:
  - empty SQL in `_start_query_run`;
  - no sources loaded in `_start_query_run`;
  - query already running in `_schedule_editor_query`;
  - query already running from `begin_query_run`;
  - unable to schedule query run.

- Do not use the helper for:
  - `TUIQueryOutcome.error`;
  - `TUIQueryOutcome.no_result`;
  - worker failure.

No change is expected in `src/csvql/tui_state.py` unless implementation reveals
that a small state helper is needed. The preferred implementation keeps the
state model unchanged and adjusts only TUI app behavior.

## Testing

Add or update focused tests in `tests/test_tui_app.py`.

Acceptance tests should prove:

- Pressing run on empty SQL preserves the previous successful result, visible
  results grid, result-message surface, export/save eligibility, and history.
- Pressing run with no sources loaded preserves the previous successful result
  when one exists.
- Pressing run while another query is already running preserves the previous
  successful result.
- A scheduling failure preserves the previous successful result.
- Rejected runs do not add query-history rows.
- `#run-status` is `Ready.` after each rejected run.
- Status or result-message text includes `Previous result is still available.`
  when a previous result exists.
- Existing completed-run behavior remains unchanged for:
  - no-result outcomes;
  - DuckDB/query errors;
  - unexpected worker failures.

Focused verification after implementation:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest tests/test_tui_app.py -q
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run ruff format --check src/csvql/tui_app.py tests/test_tui_app.py
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run ruff check src/csvql/tui_app.py tests/test_tui_app.py
```

Run the full test suite if implementation changes shared TUI state behavior,
history recording, result rendering helpers, or anything outside
`src/csvql/tui_app.py` and `tests/test_tui_app.py`.

## Documentation

No README or in-app help change is required unless implementation introduces
new user-facing commands or materially changes documented key behavior.

If the final wording is useful enough to document, keep it to one short README
sentence under the TUI section. Do not change release status docs or proof notes
as part of this polish slice.

## Risks

- Preserving a previous result after the wrong kind of failure could make stale
  export/save behavior confusing. The recovery contract avoids this by
  preserving only rejected runs where no query started.
- `tui_app.py` is a dense coordination file. Keep the helper local and small;
  do not refactor broad TUI structure in this slice.
- Terminal key handling varies. Textual `run_test()` should be the proof
  authority for this state behavior.
- This slice will make the previous release-candidate proof stale. After the
  implementation lands, rerun at least focused TUI tests. Rerun the full
  candidate proof only if Richard wants to reassert release-candidate
  eligibility after this polish.

## Direction Check

- Target lane: post-proof TUI polish before optional release promotion.
- Wedge strengthened: trustworthy local TUI iteration and deterministic result
  recovery.
- Scope rejected: release promotion, publishing, tags, safe mode, sandboxing,
  persistence, engine changes, CLI changes, and broad UI redesign.
- Contracts touched: TUI rejected-run result-preservation behavior and visible
  status wording.
- Verification target: focused Textual app tests plus Ruff checks, with broader
  tests only if the implementation touches shared state or rendering behavior.
