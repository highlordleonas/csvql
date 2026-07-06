# Task 4 Report: P1 Source Intelligence Workers And Cancellation State

## Summary

Implemented Task 4 in `csvql` by moving source intelligence actions off the UI thread and adding cancellable operation state for source workers.

## Changed Files

- `src/csvql/tui_state.py`
- `src/csvql/tui_app.py`
- `tests/test_tui_app.py`

## What Changed

- Added `TUIOperationKind` and `TUIOperationRunState` to track the current cancellable non-query operation in session state.
- Routed `inspect_source`, `sample_source`, `profile_source`, and `show_source_columns` through Textual workers instead of running them synchronously on the UI thread.
- Added Esc cancellation for the active source worker with best-effort semantics.
- Preserved existing source-intelligence rendering behavior:
  - inspect still renders the columns table and status text
  - sample still renders the sampled rows in the results grid
  - profile still renders the profile table and status text
  - show columns still caches and renders columns, and still clears the active result first
- Added a worker completion split so source worker results are applied separately from query workers.
- Blocked duplicate source-intelligence starts while a source operation is running.
- Added regression tests for:
  - worker-backed source inspect
  - Esc cancellation of a running source operation
  - existing source-intelligence rendering behavior
  - printable source-intelligence keys still working when focused on sources

## Verification

Ran:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_source_intelligence_action_uses_operation_worker \
  tests/test_tui_app.py::test_escape_cancels_running_source_operation \
  tests/test_tui_app.py::test_inspect_sample_and_profile_selected_source_update_output \
  tests/test_tui_app.py::test_source_intelligence_printable_keys_only_work_when_sources_focused -q
```

Result: `4 passed`

Ran:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras ruff check src/csvql/tui_app.py src/csvql/tui_state.py tests/test_tui_app.py
```

Result: `All checks passed!`

Ran:

```bash
git diff --check
```

Result: clean

## Concerns

- Cancellation is best-effort. If a worker finishes after Esc, its late result is ignored rather than force-stopping the underlying thread.
- No file export/save cancellation was added here; that remains for the later task.
