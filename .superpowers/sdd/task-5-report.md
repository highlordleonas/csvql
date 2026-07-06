# Task 5 Report: P2 Atomic Text Write Primitive

## Status

Completed.

## What Changed

- Added `src/csvql/atomic_write.py` with:
  - `OperationCancelled`
  - `OperationToken`
  - `write_text_atomic(path, content, *, encoding="utf-8", newline=None, token=None)`
- Switched export file writes in `src/csvql/export.py` to the atomic helper.
- Switched derived-result CSV writes in `src/csvql/tui_workflows.py` to the atomic helper and preserved the existing pre-write existence guard.
- Switched `.csvql.yml` saves in `src/csvql/project_config.py` to the atomic helper.
- Added `tests/test_atomic_write.py` for successful atomic writes and cancellation cleanup.

## Behavior Notes

- `OperationCancelled` is allowed to propagate so later cancellation work can handle it directly.
- The derived-result CSV path keeps the existing duplicate-file rejection behavior.
- CSV newline handling for derived-result writes remains `newline=""` so existing CSV output stays byte-for-byte stable.

## Verification

- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_atomic_write.py tests/test_export.py tests/test_tui_workflows.py -q`
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_project_config.py -q`
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check src/csvql/atomic_write.py src/csvql/export.py src/csvql/project_config.py src/csvql/tui_workflows.py tests/test_atomic_write.py`

## Concerns

- No remaining known issues in the touched scope.
- The helper is intentionally local and dependency-free, with no lockfile or package changes.

## Review Fix

- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_atomic_write.py tests/test_export.py tests/test_tui_workflows.py tests/test_project_config.py -q` -> `120 passed`
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check src/csvql/atomic_write.py src/csvql/export.py src/csvql/project_config.py src/csvql/tui_workflows.py tests/test_atomic_write.py tests/test_export.py tests/test_tui_workflows.py tests/test_project_config.py` -> passed
- `git diff --check` -> passed
