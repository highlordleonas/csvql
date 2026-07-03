# CSVQL Release Candidate Proof Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh the local release-candidate eligibility proof for the current CSVQL `main` candidate state and record the observed result in the tracked dated proof note.

**Architecture:** This is a proof-only lane built on existing repo-local authority: full `uv` gates, the release-readiness script, the benchmark script, manual v1 QA, focused Textual TUI tests, and unsupported-claim scans. It updates only proof documentation unless Richard explicitly approves a separate fix lane for a blocker.

**Tech Stack:** Python, `uv`, Ruff, mypy, pytest, DuckDB, Textual, Typer, git, Markdown.

---

## File Structure

Create or modify during execution:

- Modify: `docs/release-candidate-proof-2026-07-02.md`
  - Replace stale proof-target evidence with observed current-HEAD proof results.
  - Keep the note as a local assessment, not a publish, tag, upload, version
    bump, GitHub release, or `v1-stable` claim.

Read during execution:

- `AGENTS.md`
  - Repo-local v1 hardening contract, proof language, and no-claim boundaries.
- `docs/superpowers/specs/2026-07-02-csvql-release-candidate-proof-refresh-design.md`
  - Approved design for this proof refresh.
- `docs/release-readiness.md`
  - Candidate workflow, full local gate, release-readiness proof, benchmark
    proof, label rules, generated artifact policy.
- `docs/v1-manual-qa.md`
  - Manual v1 QA matrix.
- `docs/release-notes/v1.md`
  - Release package and candidate proof checklist context.
- `docs/benchmarking.md`
  - Benchmark scope and large-file-claim boundary.
- `README.md`, `CHANGELOG.md`, `docs/PRODUCT_DIRECTION.md`,
  `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/json-contracts.md`,
  `docs/failure-gallery.md`
  - Authority and unsupported-claim scan surfaces.
- `scripts/verify_release_readiness.py`
  - Release-readiness proof entry point.
- `scripts/benchmark_csvql.py`
  - Benchmark proof entry point.
- `tests/test_tui_app.py`, `tests/test_tui_workflows.py`
  - Deterministic Textual proof for current TUI behavior.

Generated local evidence, not committed:

- `output/release-readiness/**`
- `output/benchmarks/**`
- `.csvql/results/**`
- `examples/saas_revenue/.csvql/results/**`
- `examples/saas_revenue/output/**`
- temporary TUI proof roots under `/private/tmp`

Do not modify in this lane:

- Runtime source files under `src/`.
- Test files under `tests/`.
- User-facing product docs other than the proof note.
- `.local/`, `.superpowers/`, `.csvql/`, `output/`, `dist/`, `build/`, or
  generated benchmark/release artifacts.

## Direction Check

- Target lane: proof refresh for post-v0.9 hardening toward v1.
- Wedge strengthened: deterministic local CLI/TUI proof, release discipline,
  honest status labels.
- Scope rejected: new features, code repairs, docs repairs outside the proof
  note, version bump, publishing, tags, PyPI upload, GitHub release, safe mode,
  sandboxing, production-readiness claims, hidden cache, web/cloud/notebook/
  dataframe/AI/plugin scope, broad large-file performance claims.
- Contracts touched: none. If proof exposes a contract problem, record it as a
  blocker and stop for a separate fix lane.
- Verification target: current HEAD, full local gate, release-readiness proof,
  benchmark proof, manual/deterministic v1 QA, unsupported-claim scan, final
  git status, and one refreshed proof note.

---

### Task 1: Baseline Repo Truth And Artifact Posture

**Files:**

- Read: `AGENTS.md`
- Read: `docs/superpowers/specs/2026-07-02-csvql-release-candidate-proof-refresh-design.md`
- Read: `docs/release-readiness.md`
- Read: `.gitignore`

- [ ] **Step 1: Confirm current directory**

Run from the repo root:

```bash
pwd
```

Expected: prints the Dropbox-backed CSVQL workspace path or the equivalent
`/Users/richarddemke/Documents/csvql` symlinked path.

- [ ] **Step 2: Confirm branch and tracked-tree state**

Run:

```bash
git status --short --branch
```

Expected: starts with `## main`. Tracked files must be clean before proof
begins. If tracked files are dirty, stop and classify each tracked change before
running proof commands.

- [ ] **Step 3: Confirm current HEAD**

Run:

```bash
git log -1 --oneline
```

Expected: record the exact current commit. Do not assume the old proof target
or the design baseline. This plan file is tracked planning history, so the
execution-time proof target may be a later docs-only HEAD.

- [ ] **Step 4: Confirm ignored artifact policy**

Run:

```bash
rg -n "^\\.local/$|^\\.superpowers/$|^\\.csvql/$|^output/$|^dist/$|^build/$|^\\.venv/" .gitignore
```

Expected: output includes ignore rules for `.local/`, `.superpowers/`,
`.csvql/`, `output/`, `dist/`, `build/`, and `.venv/`.

- [ ] **Step 5: Re-read the approved design and release workflow**

Run:

```bash
sed -n '1,320p' docs/superpowers/specs/2026-07-02-csvql-release-candidate-proof-refresh-design.md
```

Expected: confirms this is proof-only, records no-publish boundaries, and says
failed proof becomes a blocker rather than automatic repair scope.

Run:

```bash
sed -n '1,260p' docs/release-readiness.md
```

Expected: documents the full local gate, release-readiness script, manual v1
QA matrix, benchmark proof, unsupported-claim scan, label rules, generated
artifact policy, and no-publish boundary.

- [ ] **Step 6: Classify baseline**

Record `baseline: passed` only if the directory, branch, HEAD, tracked-tree
state, ignored artifact posture, approved design, and release workflow are all
known before running proof commands.

If tracked files are dirty, record `baseline: blocked` and stop.

---

### Task 2: Full Local Gate

**Files:**

- Test: `src/`
- Test: `tests/`
- Read: `pyproject.toml`

- [ ] **Step 1: Check patch whitespace**

Run:

```bash
git diff --check
```

Expected: exits `0` with no output.

- [ ] **Step 2: Run Ruff format check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run ruff format --check .
```

Expected: exits `0` and reports files already formatted.

- [ ] **Step 3: Run Ruff lint**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run ruff check .
```

Expected: exits `0` and prints `All checks passed!`.

- [ ] **Step 4: Run mypy with all extras**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras mypy src
```

Expected: exits `0` and prints `Success: no issues found`.

- [ ] **Step 5: Run the full test suite with all extras**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest
```

Expected: exits `0` with all tests passing.

- [ ] **Step 6: Classify full local gate**

Record `full local gate: passed` only if all five commands pass at the same
HEAD.

If a command fails because dependency resolution or build access is blocked by
sandbox/network restrictions, rerun the same command with explicit escalation
according to the active permissions instructions and record both attempts.

If a command fails because of repo behavior, stop and record it as a
release-candidate blocker. Do not patch source or docs in this lane.

---

### Task 3: Release-Readiness Proof

**Files:**

- Read: `scripts/verify_release_readiness.py`
- Read: `src/csvql/release_readiness.py`
- Generated, ignored: `output/release-readiness/**`

- [ ] **Step 1: Run release-readiness proof**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

Expected: exits `0` and prints a proof summary covering version agreement, the
built wheel path, installed-wheel version smoke, installed-wheel inspect smoke,
TUI extra import smoke, and `csvql menu --help` smoke.

If the first attempt fails while resolving build requirements because the
sandbox cannot reach package indexes, rerun this same command with explicit
network escalation and record both the sandbox failure and escalated result.

- [ ] **Step 2: Inspect release-readiness artifacts**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python -c "from pathlib import Path; root = Path('output/release-readiness'); wheels = sorted((root / 'dist').glob('csvql-*.whl')); sdists = sorted((root / 'dist').glob('csvql-*.tar.gz')); python_path = root / 'smoke-venv' / 'bin' / 'python'; csvql_path = root / 'smoke-venv' / 'bin' / 'csvql'; assert wheels, 'missing built wheel'; assert sdists, 'missing built sdist'; assert python_path.exists(), 'missing smoke venv python'; assert csvql_path.exists(), 'missing installed csvql script'; print('release artifacts ok'); print(wheels[-1]); print(sdists[-1])"
```

Expected: exits `0`, prints `release artifacts ok`, then prints the latest
wheel and sdist paths under `output/release-readiness/dist/`.

- [ ] **Step 3: Classify release-readiness proof**

Record `release-readiness proof: passed` only if the release-readiness command
and artifact inspection both pass and artifact paths are captured.

If the proof fails because package build, install, version agreement, TUI
import, or menu help smoke fails, stop and record the failure as a
release-candidate blocker. Do not patch source or docs in this lane.

---

### Task 4: Benchmark Proof

**Files:**

- Read: `scripts/benchmark_csvql.py`
- Read: `src/csvql/benchmark_runner.py`
- Read: `src/csvql/benchmarking.py`
- Generated, ignored: `output/benchmarks/**`

- [ ] **Step 1: Run benchmark proof**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Expected: exits `0` and prints two paths: `benchmark.json` and
`benchmark-summary.md` under the same new run directory in
`output/benchmarks/`.

- [ ] **Step 2: Inspect latest benchmark artifact**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python -c "from pathlib import Path; import json; root = Path('output/benchmarks'); runs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime); assert runs, 'no benchmark run directories'; run = runs[-1]; artifact = run / 'benchmark.json'; summary = run / 'benchmark-summary.md'; payload = json.loads(artifact.read_text(encoding='utf-8')); assert payload['metadata']['schema_version'] == 1; assert payload['metadata']['csvql_version']; assert payload['metadata']['duckdb_version']; assert payload['metadata']['python_version']; assert payload['metadata']['platform']; assert payload['metadata']['generated_at']; assert {d['dataset_id'] for d in payload['datasets']} == {'fixture', 'synthetic_medium', 'synthetic_large'}; assert len(payload['cases']) == 18; assert summary.exists(); assert 'Local benchmark evidence only.' in payload['notes']; print('benchmark artifacts ok'); print(artifact); print(summary)"
```

Expected: exits `0`, prints `benchmark artifacts ok`, then prints the latest
benchmark JSON and Markdown summary paths.

- [ ] **Step 3: Classify benchmark proof**

Record `benchmark proof: passed` only if both commands pass and artifact paths
are captured from the current HEAD.

If the benchmark fails, stop and record the failing case or artifact assertion
as a release-candidate blocker. Do not patch benchmark code or docs in this
lane.

---

### Task 5: CLI Manual QA Matrix

**Files:**

- Read: `docs/v1-manual-qa.md`
- Exercise: `examples/saas_revenue/data/revenue_movements.csv`
- Exercise: `examples/saas_revenue/.csvql/results/**`
- Exercise: `examples/saas_revenue/output/**`

- [ ] **Step 1: Record manual proof environment**

Run:

```bash
echo "$SHELL"
```

Expected: prints the shell path. Record date, current HEAD, shell, and that CLI
manual proof ran locally.

- [ ] **Step 2: Check CLI version**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run csvql --version
```

Expected: prints `1.0.0`.

- [ ] **Step 3: Run single-file query proof**

Run from repo root:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run csvql query examples/saas_revenue/data/revenue_movements.csv "SELECT COUNT(*) AS movement_count FROM revenue_movements"
```

Expected: exits `0` and output contains `movement_count`.

- [ ] **Step 4: Run project catalog query proof**

Run from `examples/saas_revenue`:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run csvql query "SELECT COUNT(*) AS customer_count FROM customers"
```

Expected: exits `0` and output contains `customer_count`.

- [ ] **Step 5: Run export and reusable CSV source proof**

Run from `examples/saas_revenue`:

```bash
mkdir -p .csvql/results
```

Expected: exits `0`.

Run from `examples/saas_revenue`:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run csvql export queries/revenue_health.sql --format csv --out .csvql/results/revenue_health.csv --force
```

Expected: exits `0` and writes `.csvql/results/revenue_health.csv`.

Run from `examples/saas_revenue`:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run csvql query --table revenue_health_result=.csvql/results/revenue_health.csv "SELECT COUNT(*) AS result_rows FROM revenue_health_result"
```

Expected: exits `0` and output contains `result_rows`.

- [ ] **Step 6: Run bad SQL proof**

Run from repo root with status capture:

```bash
set +e
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run csvql query --table revenue_movements=examples/saas_revenue/data/revenue_movements.csv "SELECT missing_column FROM revenue_movements"
status=$?
echo "exit:$status"
set -e
```

Expected: prints `exit:1`, an error beginning `DuckDB query failed`, and a
suggestion to check table names, column names, and SQL syntax.

- [ ] **Step 7: Run missing-file proof**

Run from repo root with status capture:

```bash
set +e
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run csvql query missing.csv "SELECT 1"
status=$?
echo "exit:$status"
set -e
```

Expected: prints `exit:4` and reports `CSV file not found: missing.csv`.

- [ ] **Step 8: Run export overwrite refusal and force proof**

Run from `examples/saas_revenue`:

```bash
mkdir -p output
```

Expected: exits `0`.

Run from `examples/saas_revenue`:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run csvql export queries/revenue_health.sql --format csv --out output/revenue-health-proof-current.csv --force
```

Expected: exits `0`.

Run from `examples/saas_revenue` with status capture:

```bash
set +e
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run csvql export queries/revenue_health.sql --format csv --out output/revenue-health-proof-current.csv
status=$?
echo "exit:$status"
set -e
```

Expected: prints `exit:10` with overwrite guidance.

Run from `examples/saas_revenue`:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run csvql export queries/revenue_health.sql --format csv --out output/revenue-health-proof-current.csv --force
```

Expected: exits `0`.

- [ ] **Step 9: Classify CLI manual QA**

Record `CLI manual QA: passed` only if every CLI item passed at the same HEAD.

If any item fails, stop and record it as a release-candidate blocker. Do not
patch source or docs in this lane.

---

### Task 6: Deterministic TUI QA And Live TUI Smoke

**Files:**

- Test: `tests/test_tui_app.py`
- Test: `tests/test_tui_workflows.py`
- Exercise: `examples/saas_revenue/data/revenue_movements.csv`
- Generated, ignored: temporary Textual and TUI proof roots under `/private/tmp`

- [ ] **Step 1: Run focused TUI proof tests for current polish**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest \
  tests/test_tui_app.py::test_run_shortcuts_preserve_previous_result_after_empty_sql \
  tests/test_tui_app.py::test_run_shortcuts_preserve_previous_result_after_missing_sources \
  tests/test_tui_app.py::test_schedule_failure_preserves_previous_result_and_resets_ready \
  tests/test_tui_app.py::test_already_running_rejection_preserves_previous_result \
  tests/test_tui_app.py::test_run_shortcut_runs_selected_sql_when_editor_has_selection \
  tests/test_tui_app.py::test_run_all_shortcut_runs_whole_editor_when_current_statement_is_not_enough \
  tests/test_tui_app.py::test_history_rerun_records_rerun_mode_and_status_message \
  tests/test_tui_app.py::test_history_rerun_uses_current_session_sources \
  tests/test_tui_app.py::test_source_columns_loads_displays_and_disables_export \
  tests/test_tui_app.py::test_insert_source_alias_appends_rendered_alias_and_preserves_result \
  tests/test_tui_app.py::test_insert_starter_select_appends_rendered_select_and_preserves_result \
  tests/test_tui_workflows.py::test_run_query_for_tui_treats_duckdb_ddl_metadata_as_result \
  -q
```

Expected: exits `0` with all listed tests passing.

- [ ] **Step 2: Run the focused TUI app file**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: exits `0` with all `tests/test_tui_app.py` tests passing.

- [ ] **Step 3: Launch live TUI smoke**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras csvql menu examples/saas_revenue/data/revenue_movements.csv
```

Expected: the Textual workbench opens with a loaded `revenue_movements` source
alias and no traceback.

- [ ] **Step 4: Confirm live TUI quit path**

In the live TUI opened in Step 3, press `F9`.

Expected: the app exits cleanly without a traceback.

- [ ] **Step 5: Record TUI proof caveats**

Record:

- deterministic Textual test result;
- live TUI launch and quit result;
- terminal app or PTY used;
- whether standalone keys were used;
- whether synthetic key bursts were avoided.

Expected: TUI QA can be classified as passed if deterministic tests pass and
live launch/quit works. If live launch is not possible in the current terminal
environment, record the reason and keep the overall proof at `v1-hardening` or
`blocked` rather than silently claiming live manual QA passed.

---

### Task 7: Unsupported-Claim And Authority Scan

**Files:**

- Read: `AGENTS.md`
- Read: `README.md`
- Read: `CHANGELOG.md`
- Read: `docs/PRODUCT_DIRECTION.md`
- Read: `docs/ROADMAP.md`
- Read: `docs/ARCHITECTURE.md`
- Read: `docs/json-contracts.md`
- Read: `docs/benchmarking.md`
- Read: `docs/failure-gallery.md`
- Read: `docs/release-readiness.md`
- Read: `docs/release-notes/v1.md`

- [ ] **Step 1: Run unsupported-claim scan**

Run:

```bash
rg -n "v1-ready|v1 ready|production-safe|production ready|production-readiness|production readiness|sandbox-safe|sandbox safety|sandbox|large-file-proven|large file proven|large-file performance|large file performance|v1-stable|release-candidate" AGENTS.md README.md CHANGELOG.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/benchmarking.md docs/failure-gallery.md docs/release-readiness.md docs/release-notes/v1.md
```

Expected: matches may exist for guardrails, label rules, non-claims, and
candidate workflow language.

- [ ] **Step 2: Classify every match**

Classify each match as one of:

- guardrail: says not to claim sandboxing, production readiness, broad
  large-file performance, `v1-stable`, or release status without proof;
- label rule: defines when a label may be used;
- workflow instruction: describes the local candidate proof process;
- explicit non-claim: states what CSVQL does not prove or does not do;
- blocker: currently claims CSVQL is v1-ready, `v1-stable`,
  production-safe, production-ready, sandbox-safe, sandboxed,
  large-file-proven, or broadly large-file performant without proof.

Expected: no blocker classifications.

- [ ] **Step 3: Re-read release note boundary**

Run:

```bash
sed -n '1,240p' docs/release-notes/v1.md
```

Expected: release notes identify local release state and candidate proof
checklist context without claiming publish, tag, upload, GitHub release,
`v1-stable`, production readiness, sandbox safety, or broad large-file proof.

- [ ] **Step 4: Classify authority scan**

Record `authority scan: passed` only if no blocker classification exists and
authority docs agree with observed proof results.

If a blocker classification exists, do not patch it in this lane. Record it in
the proof note as an eligibility blocker and recommend a separate docs-fix lane.

---

### Task 8: Refresh The Tracked Proof Note

**Files:**

- Modify: `docs/release-candidate-proof-2026-07-02.md`

- [ ] **Step 1: Open the stale proof note**

Run:

```bash
sed -n '1,260p' docs/release-candidate-proof-2026-07-02.md
```

Expected: the note still records an older proof target. Use it as structure and
history, not current proof evidence.

- [ ] **Step 2: Rewrite the proof note with observed evidence**

Edit `docs/release-candidate-proof-2026-07-02.md` so it contains these sections
in this order:

```markdown
# CSVQL Release Candidate Proof Packet - 2026-07-02

## Verdict

## Baseline

## Artifact Posture

## Automated Proof

## Release-Readiness Proof

## Benchmark Proof

## Manual QA

## Unsupported-Claim Scan

## Generated Artifact Policy

## Risks And Caveats

## Blockers

## Next Task
```

Expected: every section uses observed command output and artifact paths from
Tasks 1 through 7. The note must not copy stale proof results forward as current
evidence.

- [ ] **Step 3: Choose the exact verdict line**

Use exactly one of these verdict lines:

```markdown
Verdict: `release-candidate eligible`
```

Use this only if baseline, full local gate, release-readiness proof, benchmark
proof, CLI manual QA, deterministic/live TUI QA, and authority scan all pass.

```markdown
Verdict: `blocked`
```

Use this if any required proof command, artifact inspection, manual QA item,
TUI proof item, or claim scan fails.

```markdown
Verdict: `v1-hardening`
```

Use this if Richard intentionally stops the proof before completion, or if live
manual proof cannot be completed and the honest state is incomplete rather than
blocked by runtime behavior.

- [ ] **Step 4: Record command results with audit detail**

For each automated command, record:

- exact command;
- exit code;
- key success or failure line;
- current `HEAD`;
- artifact path when the command created one.

Expected: a reader can reconstruct what local proof ran without reading chat
history.

- [ ] **Step 5: Record manual QA in checklist form**

For each manual QA item, record one status:

- `passed`;
- `failed`;
- `not run with reason`.

Expected: no CLI or TUI item is silently omitted.

- [ ] **Step 6: Record risks without expanding scope**

Include these caveats when applicable:

- `release-candidate eligible` is a local assessment, not a release action;
- terminal key handling varies, and `F4` remains the reliable run fallback;
- synthetic TUI key bursts can race;
- SQL is trusted local DuckDB SQL and not sandboxed;
- benchmark proof is local evidence only, not broad large-file proof;
- generated `output/` artifacts are ignored local evidence, not tracked release
  artifacts;
- release-readiness may require dependency/build network access.

Expected: risks are described as proof caveats, not product commitments.

- [ ] **Step 7: Scan the proof note for accidental overclaims**

Run:

```bash
rg -n "production-safe|sandbox-safe|large-file-proven|v1-stable|published|PyPI|GitHub release" docs/release-candidate-proof-2026-07-02.md
```

Expected: no match presents a current claim. Matches are allowed only in
caveat, no-publish, or no-action language.

- [ ] **Step 8: Inspect the proof note diff**

Run:

```bash
git diff -- docs/release-candidate-proof-2026-07-02.md
```

Expected: diff updates stale target evidence to current observed evidence and
does not add unsupported release, production, sandbox, or broad performance
claims.

---

### Task 9: Final Hygiene, Commit Decision, And Handoff

**Files:**

- Modify or read: `docs/release-candidate-proof-2026-07-02.md`

- [ ] **Step 1: Re-run final whitespace check**

Run:

```bash
git diff --check
```

Expected: exits `0` with no output.

- [ ] **Step 2: Re-run final git status**

Run:

```bash
git status --short --branch
```

Expected: tracked changes are limited to
`docs/release-candidate-proof-2026-07-02.md` unless Richard separately approved
another tracked artifact. Generated `output/`, `.csvql/`, `.local/`, and
`.superpowers/` evidence remains ignored.

- [ ] **Step 3: Stage only the proof note after approval**

If Richard approved committing the refreshed proof note as part of execution,
run:

```bash
git add docs/release-candidate-proof-2026-07-02.md
```

Expected: only the proof note is staged.

- [ ] **Step 4: Verify staged files**

Run:

```bash
git diff --cached --name-status
```

Expected: output includes only:

```text
M	docs/release-candidate-proof-2026-07-02.md
```

- [ ] **Step 5: Commit the proof note after staged verification**

If Richard approved the commit and only the proof note is staged, run:

```bash
git commit -m "docs: refresh release candidate proof"
```

Expected: commit succeeds and includes only the refreshed proof note.

- [ ] **Step 6: Report final outcome plainly**

Final handoff must include:

- final verdict from the proof note;
- current branch and HEAD;
- full local gate result;
- release-readiness result and artifact paths;
- benchmark result and artifact paths;
- CLI manual QA result;
- deterministic/live TUI QA result;
- unsupported-claim scan result;
- whether the proof note was committed or left unstaged;
- skipped checks, if any;
- remaining risks;
- next task.

Expected: no release publish, tag, PyPI upload, GitHub release, version bump,
source change, docs repair outside the proof note, `.superpowers/` commit, or
generated artifact commit occurred.

---

## Self-Review

Spec coverage:

- Baseline truth and artifact posture are covered in Task 1.
- Full local gate is covered in Task 2.
- Release-readiness proof and artifact inspection are covered in Task 3.
- Benchmark proof and artifact inspection are covered in Task 4.
- Manual CLI QA is covered in Task 5.
- Deterministic and live TUI QA are covered in Task 6.
- Unsupported-claim and authority scans are covered in Task 7.
- Proof-note refresh and verdict classification are covered in Task 8.
- Final hygiene, commit decision, and handoff are covered in Task 9.

Placeholder scan:

- This plan contains no unresolved filler sections, deferred repair steps, or
  guessed proof outputs.

Type and command consistency:

- All Python commands use repo-local `uv`.
- TUI tests and app launch use `--all-extras`.
- The UV cache path matches the approved proof-refresh design.
- Generated proof artifacts stay under ignored locations.
- The only planned tracked proof output is
  `docs/release-candidate-proof-2026-07-02.md`.

Residual risk:

- Release-readiness can require network escalation for dependency/build access.
- Live TUI smoke depends on terminal behavior; deterministic Textual tests are
  the stronger proof for detailed editor/source/recovery behavior.
- A blocker discovered during proof is recorded, not repaired, until Richard
  approves a separate fix lane.
