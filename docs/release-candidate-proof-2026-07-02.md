# CSVQL Release Candidate Proof Packet - 2026-07-02

## Verdict

Verdict: `release-candidate eligible`

CSVQL is `release-candidate eligible` as a local assessment for proof target
commit `8ede1ef test: align tui ddl metadata proof`.

This is not a release action. It does not publish packages, create tags, upload
artifacts, create a GitHub release, change the package version, claim
`v1-stable`, or make unsupported production, sandbox, security-isolation, or
large-file performance claims.

## Baseline

- Date: 2026-07-02
- Branch: `main`
- Proof target HEAD: `8ede1ef test: align tui ddl metadata proof`
- Repo path:
  `/Users/richarddemke/LGCY Dropbox/Richard Demke/Mac/Documents/csvql`
- Shell: `/bin/zsh`
- Tracked status before proof: clean
  - `git status --short --branch` printed only `## main`
- Ignored local state remained ignored:
  - `.local/`
  - `.superpowers/`
  - `.csvql/`
  - `output/`
  - generated caches and local proof outputs

## Artifact Posture

Artifact posture was resolved before this proof:

- `.local/` is ignored generated telemetry/local orchestration state.
- `.superpowers/` is ignored generated Superpowers local state.
- `docs/release-candidate-proof-2026-07-02.md` is the tracked proof note.
- `docs/superpowers/plans/2026-07-02-csvql-editor-quality-v2.md` is tracked
  planning history under the existing `docs/superpowers/plans/` convention.
- `docs/superpowers/plans/2026-07-02-csvql-release-candidate-proof-packet.md`
  is tracked planning history under the same convention.
- Generated release and benchmark artifacts remain ignored local evidence.

## Automated Proof

- `git diff --check`
  - Exit code: `0`
  - Result: no whitespace errors
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run ruff format --check .`
  - Exit code: `0`
  - Result: `72 files already formatted`
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run ruff check .`
  - Exit code: `0`
  - Result: `All checks passed!`
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras mypy src`
  - Exit code: `0`
  - Result: `Success: no issues found in 32 source files`
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest`
  - Exit code: `0`
  - Result: `458 passed in 34.77s`

## Release-Readiness Proof

Command:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

Result after network escalation:

- Exit code: `0`
- Summary: `Release readiness proof passed.`
- Versions: `pyproject=1.0.0`, `package=1.0.0`, `cli=1.0.0`
- Wheel:
  `output/release-readiness/dist/csvql-1.0.0-py3-none-any.whl`
- Sdist:
  `output/release-readiness/dist/csvql-1.0.0.tar.gz`
- Inspect smoke output: passed
- TUI extra import: `tui-extra-ok`
- Menu help smoke output: passed

The first sandboxed attempt failed while resolving `hatchling` from PyPI because
DNS/network access was unavailable in the sandbox. The same command passed after
explicit network escalation.

## Benchmark Proof

Command:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Result:

- Exit code: `0`
- Benchmark JSON:
  `output/benchmarks/20260702T204101Z/benchmark.json`
- Benchmark summary:
  `output/benchmarks/20260702T204101Z/benchmark-summary.md`

Benchmark artifacts are local evidence only. They do not prove broad large-file
performance beyond the recorded benchmark datasets.

## Manual QA

- Setup/version check: passed
  - `csvql --version` printed `1.0.0`
- CLI single-file query: passed
  - `movement_count = 11`
- CLI project catalog query: passed
  - `customer_count = 5`
- CLI export and reuse as CSV source: passed
  - export wrote `.csvql/results/revenue_health.csv`
  - follow-up query returned `result_rows = 4`
- Bad SQL behavior: passed
  - exit code `1`
  - error began `DuckDB query failed`
  - suggestion advised checking table names, column names, and SQL syntax
- Missing file behavior: passed
  - exit code `4`
  - error reported `CSV file not found: missing.csv`
- Export overwrite refusal and force: passed
  - fresh proof path: `output/revenue-health-proof-8ede1ef.csv`
  - first export succeeded
  - second export exited `10` with overwrite guidance
  - forced export succeeded
- TUI launch: passed
  - live PTY launched `csvql menu examples/saas_revenue/data/revenue_movements.csv`
  - status showed `1 source loaded.`
- TUI repeated query: passed through Textual app harness against the example CSV
  - `movement_count = 11`
  - grouped movement query returned 5 movement-type rows
  - history recorded 2 attempts after the two runs
- TUI derived save and query: passed through Textual app harness
  - `Ctrl+S` saved alias `movement_counts`
  - derived CSV was written under `.csvql/results/movement_counts.csv`
  - `SELECT * FROM movement_counts;` returned 5 rows
- TUI DDL metadata result: passed through Textual app harness
  - SQL: `CREATE OR REPLACE TABLE scratch AS SELECT 1 AS value;`
  - result columns: `Count`
  - result rows: `[[1]]`
- Quit path: passed
  - live PTY exited cleanly after standalone `F9`
- Mac keybinding path: passed by deterministic app harness and docs alignment
  - `Ctrl+S` saved result as a source
  - README/manual docs do not rely on `F11` as the only save path

## Unsupported-Claim Scan

Command:

```bash
rg -n "v1-ready|v1 ready|production-safe|production ready|production-readiness|production readiness|sandbox-safe|sandbox safety|sandbox|large-file-proven|large file proven|large-file performance|large file performance|v1-stable|release-candidate" AGENTS.md README.md CHANGELOG.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/benchmarking.md docs/failure-gallery.md docs/release-readiness.md docs/release-notes/v1.md
```

Result:

- Exit code: `0`
- Blocker-classified unsupported claims: none
- Matches were classified as guardrails, label rules, workflow instructions, or
  explicit non-claims.

## Generated Artifact Policy

Generated proof evidence remained local and ignored:

- `output/release-readiness/**`
- `output/benchmarks/**`
- `.csvql/results/movement_counts.csv`
- `examples/saas_revenue/.csvql/results/revenue_health.csv`
- `examples/saas_revenue/output/revenue-health.csv`
- `examples/saas_revenue/output/revenue-health-proof-8ede1ef.csv`
- temporary Textual harness roots under `/private/tmp/csvql-tui-proof-*`

None of these generated artifacts were staged.

## Risks And Caveats

- `release-candidate eligible` is an assessment label only. It is not a publish,
  tag, GitHub release, PyPI upload, or `v1-stable` action.
- Release-readiness required network escalation after sandbox DNS failure while
  resolving build requirements.
- Terminal key handling varies. `F4` remains the reliable run fallback for query
  execution.
- The live PTY proof covered TUI launch and `F9` quit. Textual `run_test()` was
  used as the deterministic proof authority for editor, history, save, and DDL
  behavior.
- SQL is trusted local DuckDB SQL. CSVQL does not sandbox DuckDB or make
  untrusted SQL safe.
- Benchmark proof is local evidence only and does not prove broad large-file
  performance.

## Blockers

None found in this proof packet.

## Next Task

Richard can review this proof packet and decide whether to treat the repository
as `release-candidate` status. Do not publish, tag, upload artifacts, or claim
`v1-stable` without separate explicit approval.
