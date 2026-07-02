# CSVQL Release Candidate Proof Packet - 2026-07-02

## Verdict

Verdict: blocked

CSVQL is not `release-candidate eligible` from this proof packet because the
manual v1 QA matrix expects `CREATE TABLE scratch AS SELECT 1 AS value;` to
produce no tabular result, while the current TUI runtime returns a tabular
DuckDB `Count` result. The strict clean-worktree condition also needs a cleanup
or tracked-artifact decision before a final candidate proof.

## Follow-Up Fix Status

After this proof packet, a narrow fix lane corrected the manual QA matrix to
match the current DuckDB/TUI behavior:

- `docs/v1-manual-qa.md` now uses
  `CREATE OR REPLACE TABLE scratch AS SELECT 1 AS value;` and expects DuckDB's
  returned `Count` metadata as a tabular result.
- `docs/release-readiness.md` describes this as TUI DDL metadata-result
  coverage instead of no-result SQL coverage.
- `tests/test_v1_polish_docs.py` and `tests/test_tui_workflows.py` now assert
  the corrected documentation and runtime behavior.

Focused verification passed:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest tests/test_v1_polish_docs.py tests/test_tui_workflows.py -q
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run ruff format --check tests/test_v1_polish_docs.py tests/test_tui_workflows.py
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run ruff check tests/test_v1_polish_docs.py tests/test_tui_workflows.py
git diff --check
```

This resolves the manual QA mismatch in the working tree. It does not reclassify
this packet as `release-candidate eligible`; a final proof still needs an
artifact-posture decision and a fresh proof rerun from the resulting candidate
state.

## Baseline

- Date: 2026-07-02
- Branch: `main`
- HEAD: `21c4baf fix: reset tui run status on rejected runs`
- Repo path: `/Users/richarddemke/LGCY Dropbox/Richard Demke/Mac/Documents/csvql`
- Shell: `/bin/zsh`
- Terminal app: Codex desktop PTY for live TUI launch/quit; Textual
  `run_test()` harness for deterministic TUI behavior proof
- Tracked files: clean at proof start
- Untracked local state at proof start:
  - `.local/`
  - `.superpowers/`
  - `docs/superpowers/plans/2026-07-02-csvql-editor-quality-v2.md`
  - `docs/superpowers/plans/2026-07-02-csvql-release-candidate-proof-packet.md`
- Additional untracked state after proof-note creation:
  - `docs/release-candidate-proof-2026-07-02.md`

Ignored proof output policy was confirmed in `.gitignore` for `output/`,
`dist/`, `build/`, and `.venv/`.

## Automated Proof

- `git diff --check`
  - Exit code: `0`
  - Result: no output
- `env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .`
  - Exit code: `0`
  - Result: `72 files already formatted`
- `env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .`
  - Exit code: `0`
  - Result: `All checks passed!`
- `env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src`
  - Exit code: `0`
  - Result: `Success: no issues found in 32 source files`
- `env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest`
  - Exit code: `0`
  - Result: `457 passed in 31.09s`

Release-readiness recovery notes:

- First release-readiness attempt with `/private/tmp/uv-cache` failed because a
  cached PyYAML wheel metadata file was missing from the local `uv` cache.
- Fresh-cache retry without escalation failed because the sandbox could not
  resolve `https://pypi.org/simple/hatchling/`.
- The same local proof command passed after escalation with
  `UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof`.

Release-readiness command:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

Result:

- Exit code: `0`
- Summary: `Release readiness proof passed.`
- Versions: `pyproject=1.0.0`, `package=1.0.0`, `cli=1.0.0`
- TUI extra import: `tui-extra-ok`
- Menu help smoke: passed

Benchmark command:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Result:

- Exit code: `0`
- Benchmark JSON and Markdown summary were generated for the current HEAD.
- Artifact inspection passed: schema version `1`, CSVQL/DuckDB/Python/platform
  metadata present, datasets `fixture`, `synthetic_medium`, and
  `synthetic_large`, 18 benchmark cases, and local-evidence-only note present.

## Release-Readiness Artifacts

- Wheel: `output/release-readiness/dist/csvql-1.0.0-py3-none-any.whl`
- Sdist: `output/release-readiness/dist/csvql-1.0.0.tar.gz`
- Smoke CSV: `output/release-readiness/smoke/orders.csv`
- Smoke venv: `output/release-readiness/smoke-venv/`

These are ignored local evidence artifacts and were not staged.

## Benchmark Artifacts

- Benchmark JSON: `output/benchmarks/20260702T201221Z/benchmark.json`
- Benchmark summary: `output/benchmarks/20260702T201221Z/benchmark-summary.md`

These are ignored local evidence artifacts and were not staged.

## Manual QA

- Setup/version check: passed
  - `csvql --version` printed `1.0.0`
- CLI single-file query: passed
  - `movement_count = 11`
- CLI project catalog query: passed
  - `customer_count = 5`
- CLI export and reuse as CSV source: passed
  - `revenue_health.csv` was written under `examples/saas_revenue/.csvql/results/`
  - follow-up query returned `result_rows = 4`
- Bad SQL behavior: passed
  - Exit code `1`
  - Error began `DuckDB query failed`
  - Guidance suggested checking table names, column names, and SQL syntax
- Missing file behavior: passed
  - Exit code `4`
  - Error reported `CSV file not found: missing.csv`
- Export overwrite refusal and force: passed
  - first export succeeded
  - second export exited `10` with overwrite guidance
  - forced export succeeded
- TUI launch: passed
  - Live PTY launched `csvql menu examples/saas_revenue/data/revenue_movements.csv`
  - Source alias `revenue_movements` loaded
- TUI repeated query: passed through Textual app harness
  - `movement_count = 11`
  - grouped movement query returned 5 movement-type rows
  - history recorded 2 attempts
- TUI derived save and query: passed through Textual app harness
  - `Ctrl+S` saved alias `movement_counts`
  - derived CSV was written under a temporary proof root
  - `SELECT * FROM movement_counts;` returned 5 rows
- TUI no-result SQL: failed the documented manual QA expectation
  - SQL: `CREATE TABLE scratch AS SELECT 1 AS value;`
  - Expected by `docs/v1-manual-qa.md`: prior results cleared and no tabular result reported
  - Actual runtime: `QueryResult(columns=('Count',), rows=((1,), ...))`
  - Actual status: `1 returned row(s) in 0.7 ms.`
- TUI Editor Quality v2 run modes: passed through Textual app harness
  - `F4` on the current second statement returned `proof_count = 11`
  - `F12` on the whole editor surfaced the deliberate `missing_table` error
- TUI Source Intelligence v1 actions: passed through Textual app harness
  - `c` loaded `revenue_movements: 6 columns loaded.`
  - `l` inserted `"revenue_movements"`
  - `x` inserted:

    ```sql
    SELECT *
    FROM "revenue_movements"
    LIMIT 10;
    ```

- TUI quit path: passed
  - Live PTY exited cleanly after standalone `F9`

## Unsupported-Claim Scan

Command:

```bash
rg -n "v1-ready|v1 ready|production-safe|production ready|production-readiness|production readiness|sandbox-safe|sandbox safety|sandbox|large-file-proven|large file proven|large-file performance|large file performance|v1-stable|release-candidate" AGENTS.md README.md CHANGELOG.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/benchmarking.md docs/failure-gallery.md docs/release-readiness.md docs/release-notes/v1.md
```

Result:

- Exit code: `0`
- Blocker-classified unsupported claims: none
- Matches classified as guardrails, label rules, or workflow instructions

Read-only subagent scan agreed that no blocker-classified unsupported claims
were present. It flagged the untracked worktree state and proof-backed status
language as risks to disclose in this packet.

## Generated Artifact Policy

Generated proof evidence remained local:

- `output/release-readiness/**`
- `output/benchmarks/**`
- `examples/saas_revenue/.csvql/results/revenue_health.csv`
- `examples/saas_revenue/output/revenue-health.csv`
- temporary Textual harness proof roots under `/private/tmp/csvql-tui-proof-*`

`git status --ignored --short` showed generated output as ignored. None of the
generated output artifacts were staged.

## Risks And Caveats

- Terminal key handling varies. `F4` remains the reliable run fallback for query
  execution.
- The live PTY proved TUI launch and `F9` quit, but did not reliably focus text
  entry into Textual's `TextArea`. Textual's `run_test()` harness was used for
  behavior proof of TUI actions.
- Synthetic PTY key bursts can race. Standalone key actions and Textual pilot
  actions are the proof authority here.
- SQL is trusted local DuckDB SQL. CSVQL does not sandbox DuckDB or make
  untrusted SQL safe.
- Benchmark proof is local evidence only and does not prove broad large-file
  performance.
- Release-readiness proof required network escalation after a local `uv` cache
  issue and sandboxed dependency-resolution failure.
- The worktree was tracked-clean but not fully clean because local untracked
  orchestration and plan files were present.

## Blockers

1. Manual QA no-result SQL mismatch.

   `docs/v1-manual-qa.md` expects `CREATE TABLE scratch AS SELECT 1 AS value;`
   to complete with no tabular result. Current runtime returns a tabular DuckDB
   `Count` result. This is a runtime/docs contract mismatch and blocks honest
   release-candidate eligibility. This was resolved in the follow-up working
   tree by documenting and testing the DDL metadata-result behavior.

2. Strict clean-worktree condition not met.

   The tracked tree was clean, but untracked `.local/`, `.superpowers/`, and
   generated Superpowers plan files were present before proof. After this note
   was written, `docs/release-candidate-proof-2026-07-02.md` was also untracked.
   Before final candidate proof, decide whether these should be cleaned,
   ignored, or tracked by explicit artifact decision.

## Next Task

Resolve the untracked artifact posture and rerun this proof packet from the
resulting candidate HEAD. Do not classify CSVQL as `release-candidate eligible`
until the fresh proof passes from that candidate state.
