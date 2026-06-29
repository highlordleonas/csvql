# CSVQL v0.5 Profiling Implementation Plan

## Goal

Implement `csvql profile <csv-path-or-catalog-alias>` with full-scan DuckDB profiling, table and JSON output, direct path and case-insensitive project catalog alias support, focused tests, and docs.

## Constraints

- Work only in `/Users/richarddemke/.codex/worktrees/4d42/csvql`.
- Do not touch `/Users/richarddemke/.codex/worktrees/63fd/csvql`.
- Current checkout is detached at `48b2714`; do not commit unless moved to a real branch with explicit approval.
- Use `uv` for local execution.
- Do not add dependencies or lockfile churn.
- Do not claim sandbox safety, untrusted SQL safety, production readiness, large-file performance, benchmark-backed speed, timeout guarantees, cache/materialization, or v1 readiness.

## Tasks

1. Add model tests and dataclasses.
   - Modify `tests/test_models.py` and `src/csvql/models.py`.
   - Add `ColumnProfile.as_dict()` and `ProfileResult.as_dict()`.

2. Add DuckDB profiling service.
   - Create `tests/test_profiling.py` and `src/csvql/profiling.py`.
   - Test row and column counts, null metrics, distinct excluding nulls, duplicate excess rows, string min/max, numeric/date min/max, empty data rows, quoted odd column names, and missing-file-after-resolution failure wrapping.
   - Use DuckDB `read_csv(..., auto_detect=True, header=True)` and controlled aggregate queries.
   - Quote generated identifiers safely.

3. Add output renderers.
   - Modify `tests/test_output.py` and `src/csvql/output.py`.
   - Add `format_profile_result_json()` and `format_profile_result_table()`.

4. Wire CLI.
   - Create `tests/test_cli_profile.py` and modify `src/csvql/cli.py`.
   - Test direct path JSON/table output, catalog alias JSON, case-insensitive alias, and missing-file behavior.

5. Update docs.
   - Update `README.md` profile examples.
   - Update `docs/ROADMAP.md` v0.5 implemented status once code is complete.
   - Update `docs/ARCHITECTURE.md` profiling boundary and full-scan behavior.

6. Final verification.
   - `UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .`
   - `UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .`
   - `UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src`
   - `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest`
   - `git diff --check`
   - `UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql profile examples/sales/data/orders.csv --output json`
   - from `examples/sales`: `UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql profile orders --output json`

