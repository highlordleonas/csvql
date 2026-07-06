# Task 6 Report

## Status

Completed.

## What Changed

- `src/csvql/export.py`
  - Added optional `OperationToken` support to `write_export_file()`.
  - Let `OperationCancelled` propagate unchanged so cancelled writes are not wrapped as generic export failures.

- `src/csvql/tui_workflows.py`
  - Added optional `OperationToken` plumbing to `export_last_result()`.
  - Added optional `OperationToken` plumbing to `save_derived_result_source()`.
  - Threaded cancellation into `_write_derived_result_file()` and preserved `OperationCancelled` there as well.

- `src/csvql/tui_app.py`
  - Workerized F7 export and save-active-result-as-source.
  - Added per-operation cancellation tokens and tracked the active operation worker name to prevent stale worker results from affecting a newer operation.
  - Added `_ExportOutcome` and `_SaveResultSourceOutcome` so worker results are applied only after successful completion.
  - Kept export completion from clearing the visible result grid.
  - Added Esc cancellation for running export/save workers.
  - Preserved `OperationCancelled` as a non-generic cancellation path in worker failure handling.
  - Added a preflight duplicate-alias check for save-as-source so validation failures still surface immediately without starting a worker.

- `tests/test_tui_app.py`
  - Added the Esc cancellation regression for export before final file commit.
  - Updated export/save tests to wait for worker completion before asserting on status or file output.
  - Imported the original export helper for the monkeypatched cancellation test to avoid recursion.

- `tests/test_tui_workflows.py`
  - Updated the monkeypatched derived-result write helper to accept the new token keyword argument.

## Verification

- `git diff --check`
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py -k "export_last_result or save_result_as_source or cancels_running_export" -q`
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_workflows.py -k "save_derived_result_source and not refutes" -q`

## Concerns

- I did not run the full repository test suite, only the focused export/save worker slice plus the touched workflow helper slice.
- The save-as-source duplicate-alias path now preflights in the TUI before the worker starts, which keeps the error immediate but is a small extra validation branch outside the worker commit path.

## Review Fix

- Updated the Task 4 source-action worker callbacks in `src/csvql/tui_app.py` to accept the `OperationToken` argument and ignore it, restoring compatibility with `_start_operation_worker(work(token))`.
- Added a save-as-source cancellation regression in `tests/test_tui_app.py` that cancels before the derived CSV commit and asserts no final file and no new source.
- Verification:
  - `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py -k "source_intelligence_action_uses_operation_worker or source_columns_loads_grid_and_disables_export or escape_cancels_running_source_operation or cancelled_sample_worker_preserves_previous_active_result or source_worker_failure_preserves_csv_error_message_and_suggestion or sample_worker_failure_preserves_csv_error_message_and_suggestion" -q` -> `6 passed, 111 deselected`
  - `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py -k "export_last_result or save_result_as_source or cancels_running_export or cancels_running_save_result" -q` -> `11 passed, 106 deselected`
  - `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_workflows.py -k "save_derived_result_source or export_last_result" -q` -> `14 passed, 31 deselected`
  - `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check src/csvql/tui_app.py src/csvql/tui_workflows.py src/csvql/export.py tests/test_tui_app.py tests/test_tui_workflows.py` -> passed
  - `git diff --check` -> passed
