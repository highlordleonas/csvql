# CSVQL Release Candidate Proof Packet - 2026-07-02

## Verdict

Verdict: `release-candidate eligible`

CSVQL is `release-candidate eligible` as a local assessment for proof target
commit `538f024 docs: plan release candidate proof refresh`.

This is not a release action. It does not publish packages, create tags, upload
artifacts, create a GitHub release, change the package version, change the
repository status label to `release-candidate`, claim `v1-stable`, or make
unsupported production, sandbox, security-isolation, or broad large-file
performance claims.

## Baseline

- Date: 2026-07-02, America/Denver
- Branch: `main`
- Proof target HEAD: `538f024 docs: plan release candidate proof refresh`
- Repo path:
  `/Users/richarddemke/LGCY Dropbox/Richard Demke/Mac/Documents/csvql`
- Invocation path:
  `/Users/richarddemke/Documents/csvql`
- Shell: `/bin/zsh`
- Tracked status before proof: clean
  - `git status --short --branch` printed only `## main`
- Artifact ignore rules confirmed in `.gitignore`:
  - `.venv/`
  - `dist/`
  - `build/`
  - `.local/`
  - `.superpowers/`
  - `.csvql/`
  - `output/`

## Artifact Posture

Artifact posture for this proof:

- `docs/release-candidate-proof-2026-07-02.md` is the tracked proof note.
- `docs/superpowers/specs/2026-07-02-csvql-release-candidate-proof-refresh-design.md`
  is tracked planning history.
- `docs/superpowers/plans/2026-07-02-csvql-release-candidate-proof-refresh.md`
  is tracked planning history.
- `.local/` is ignored generated local orchestration or telemetry state.
- `.superpowers/` is ignored generated Superpowers local state.
- `.csvql/` is ignored generated local CSVQL state.
- `output/` is ignored generated proof evidence.
- Generated release, benchmark, CLI, and TUI proof artifacts remain ignored
  local evidence unless Richard separately approves a tracked-artifact
  decision.

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
  - Result: `460 passed in 34.58s`

All automated proof commands ran at proof target HEAD `538f024`.

## Release-Readiness Proof

Command:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

First sandboxed attempt:

- Exit code: `1`
- Result: failed while resolving build-system requirement `hatchling`
- Cause: sandbox DNS/network access unavailable for `https://pypi.org/simple/hatchling/`

Result after explicit network escalation:

- Exit code: `0`
- Summary: `Release readiness proof passed.`
- Versions: `pyproject=1.0.0`, `package=1.0.0`, `cli=1.0.0`
- Wheel:
  `output/release-readiness/dist/csvql-1.0.0-py3-none-any.whl`
- Sdist:
  `output/release-readiness/dist/csvql-1.0.0.tar.gz`
- Installed-wheel inspect smoke output: passed
- TUI extra import: `tui-extra-ok`
- Menu help smoke output: passed

Artifact inspection command:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python -c "from pathlib import Path; root = Path('output/release-readiness'); wheels = sorted((root / 'dist').glob('csvql-*.whl')); sdists = sorted((root / 'dist').glob('csvql-*.tar.gz')); python_path = root / 'smoke-venv' / 'bin' / 'python'; csvql_path = root / 'smoke-venv' / 'bin' / 'csvql'; assert wheels, 'missing built wheel'; assert sdists, 'missing built sdist'; assert python_path.exists(), 'missing smoke venv python'; assert csvql_path.exists(), 'missing installed csvql script'; print('release artifacts ok'); print(wheels[-1]); print(sdists[-1])"
```

Artifact inspection result:

- Exit code: `0`
- Result: `release artifacts ok`
- Wheel path:
  `output/release-readiness/dist/csvql-1.0.0-py3-none-any.whl`
- Sdist path:
  `output/release-readiness/dist/csvql-1.0.0.tar.gz`

## Benchmark Proof

Command:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Result:

- Exit code: `0`
- Benchmark JSON:
  `output/benchmarks/20260703T001804Z/benchmark.json`
- Benchmark summary:
  `output/benchmarks/20260703T001804Z/benchmark-summary.md`

Artifact inspection command:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python -c "from pathlib import Path; import json; root = Path('output/benchmarks'); runs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime); assert runs, 'no benchmark run directories'; run = runs[-1]; artifact = run / 'benchmark.json'; summary = run / 'benchmark-summary.md'; payload = json.loads(artifact.read_text(encoding='utf-8')); assert payload['metadata']['schema_version'] == 1; assert payload['metadata']['csvql_version']; assert payload['metadata']['duckdb_version']; assert payload['metadata']['python_version']; assert payload['metadata']['platform']; assert payload['metadata']['generated_at']; assert {d['dataset_id'] for d in payload['datasets']} == {'fixture', 'synthetic_medium', 'synthetic_large'}; assert len(payload['cases']) == 18; assert summary.exists(); assert 'Local benchmark evidence only.' in payload['notes']; print('benchmark artifacts ok'); print(artifact); print(summary)"
```

Artifact inspection result:

- Exit code: `0`
- Result: `benchmark artifacts ok`
- Benchmark JSON:
  `output/benchmarks/20260703T001804Z/benchmark.json`
- Benchmark summary:
  `output/benchmarks/20260703T001804Z/benchmark-summary.md`

These benchmark artifacts were generated during the current proof run at
candidate-state HEAD `538f024`. They are local evidence only and do not prove
broad large-file performance beyond the recorded benchmark datasets.

## Manual QA

Manual proof environment:

- Date: 2026-07-02, America/Denver
- Commit: `538f024 docs: plan release candidate proof refresh`
- Shell: `/bin/zsh`
- Live TUI terminal: Codex managed PTY
- Synthetic TUI key bursts: avoided for live proof; standalone `F9` was used
  for quit

CLI manual QA:

- Setup/version check: passed
  - `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run csvql --version`
  - Exit code: `0`
  - Result: `1.0.0`
- CLI single-file query: passed
  - Query returned `movement_count = 11`
- CLI project catalog query: passed
  - Query returned `customer_count = 5`
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
  - proof path: `examples/saas_revenue/output/revenue-health-proof-current.csv`
  - first forced export succeeded
  - unforced export exited `10` with overwrite guidance
  - final forced export succeeded

TUI deterministic QA:

- Focused TUI proof tests: passed
  - Command:
    `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest tests/test_tui_app.py::test_run_shortcuts_preserve_previous_result_after_empty_sql tests/test_tui_app.py::test_run_shortcuts_preserve_previous_result_after_missing_sources tests/test_tui_app.py::test_schedule_failure_preserves_previous_result_and_resets_ready tests/test_tui_app.py::test_already_running_rejection_preserves_previous_result tests/test_tui_app.py::test_run_shortcut_runs_selected_sql_when_editor_has_selection tests/test_tui_app.py::test_run_all_shortcut_runs_whole_editor_when_current_statement_is_not_enough tests/test_tui_app.py::test_history_rerun_records_rerun_mode_and_status_message tests/test_tui_app.py::test_history_rerun_uses_current_session_sources tests/test_tui_app.py::test_source_columns_loads_displays_and_disables_export tests/test_tui_app.py::test_insert_source_alias_appends_rendered_alias_and_preserves_result tests/test_tui_app.py::test_insert_starter_select_appends_rendered_select_and_preserves_result tests/test_tui_workflows.py::test_run_query_for_tui_treats_duckdb_ddl_metadata_as_result -q`
  - Exit code: `0`
  - Result: `14 passed in 8.24s`
- Full TUI app test file: passed
  - Command:
    `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest tests/test_tui_app.py -q`
  - Exit code: `0`
  - Result: `62 passed in 30.88s`

TUI behaviors covered by deterministic proof:

- repeated query and history behavior
- derived result save/query coverage through the full TUI app suite
- DDL metadata result behavior
- Editor Quality v2 selected/current statement execution
- Editor Quality v2 whole-editor run path
- history rerun using current session sources
- Source Intelligence v1 source column loading
- Source Intelligence v1 alias insertion
- Source Intelligence v1 starter-query insertion
- rejected-run recovery preserving the previous successful result when no query
  ran
- no-source, empty-SQL, already-running, and scheduling-failure rejected-run
  recovery paths
- README/help keymap documentation for current editor/source/history behavior

Live TUI smoke:

- Launch: passed
  - Command:
    `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras csvql menu examples/saas_revenue/data/revenue_movements.csv`
  - PTY output showed `1 source loaded.`
  - Exit code after quit: `0`
- Quit path: passed
  - standalone `F9` sequence exited cleanly without traceback

Proof-process note:

- A first shell wrapper for bad-SQL and missing-file exit capture used `status`,
  which is a read-only variable in zsh. The wrapper failed before printing its
  exit line. The product checks were rerun with `proof_status`; those reruns
  captured the expected exit codes.

## Unsupported-Claim Scan

Command:

```bash
rg -n "v1-ready|v1 ready|production-safe|production ready|production-readiness|production readiness|sandbox-safe|sandbox safety|sandbox|large-file-proven|large file proven|large-file performance|large file performance|v1-stable|release-candidate" AGENTS.md README.md CHANGELOG.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/benchmarking.md docs/failure-gallery.md docs/release-readiness.md docs/release-notes/v1.md
```

Result:

- Exit code: `0`
- Blocker-classified unsupported claims: none
- Matches were classified as:
  - guardrails
  - label rules
  - workflow instructions
  - explicit non-claims

Authority docs reviewed or scanned:

- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/PRODUCT_DIRECTION.md`
- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/json-contracts.md`
- `docs/benchmarking.md`
- `docs/failure-gallery.md`
- `docs/release-readiness.md`
- `docs/release-notes/v1.md`

The authority docs agree with the observed local runtime surface and do not
claim publishing, production safety, sandbox safety, `v1-stable`, or broad
large-file proof.

## Generated Artifact Policy

Generated proof evidence remained local and ignored:

- `output/release-readiness/**`
- `output/benchmarks/**`
- `examples/saas_revenue/.csvql/results/revenue_health.csv`
- `examples/saas_revenue/output/revenue-health-proof-current.csv`
- temporary Textual/TUI proof roots under `/private/tmp`

None of these generated artifacts are intended to be staged or committed.

## Risks And Caveats

- `release-candidate eligible` is an assessment label only. It is not a publish,
  tag, GitHub release, PyPI upload, status-label change, or `v1-stable` action.
- Release-readiness required network escalation after sandbox DNS failure while
  resolving build requirements.
- Terminal key handling varies. `F4` remains the reliable run fallback for query
  execution.
- The live PTY proof covered TUI launch and `F9` quit. Deterministic Textual
  tests are the proof authority for detailed editor, history, source
  intelligence, result-save, DDL metadata, and rejected-run recovery behavior.
- Synthetic TUI key bursts can race; this proof avoided them for live TUI proof.
- SQL is trusted local DuckDB SQL. CSVQL does not sandbox DuckDB or make
  untrusted SQL safe.
- Benchmark proof is local evidence only and does not prove broad large-file
  performance.
- Generated proof outputs are local evidence only and remain ignored.

## Blockers

None found in this proof packet.

## Next Task

Richard can review this refreshed proof packet and decide whether to treat the
repository as `release-candidate` status. Do not publish, tag, upload artifacts,
create a GitHub release, change the package version, or claim `v1-stable`
without separate explicit approval.
