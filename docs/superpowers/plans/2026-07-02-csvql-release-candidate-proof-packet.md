# CSVQL Release Candidate Proof Packet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a proof-only release-candidate eligibility packet for the current CSVQL `main` state and record the result in one tracked dated proof note.

**Architecture:** This plan uses existing repo-local proof surfaces: full `uv` gates, release-readiness script, benchmark script, manual v1 QA matrix, and authority-claim scans. It does not change product behavior or repair docs during execution; any contradiction becomes a blocker or follow-up recorded in the proof note. Generated `output/` artifacts remain ignored local evidence, while the final human-readable proof note is the tracked artifact.

**Tech Stack:** Python, `uv`, Ruff, mypy, pytest, DuckDB, Textual TUI extra, git, Markdown.

---

## File Structure

Create during proof execution:

- `docs/release-candidate-proof-2026-07-02.md`: dated proof packet note with exact commit, command results, artifact paths, manual QA result, claim-scan classification, verdict, blockers, risks, and next task.

Read during proof execution:

- `AGENTS.md`: repo-local v1 hardening contract, proof language, and no-claim boundaries.
- `README.md`: user-facing behavior and release-readiness links.
- `CHANGELOG.md`: release package surface and known boundaries.
- `docs/release-readiness.md`: candidate workflow and label rules.
- `docs/release-notes/v1.md`: candidate proof checklist and release package contents.
- `docs/v1-manual-qa.md`: manual CLI and TUI QA matrix.
- `docs/benchmarking.md`: benchmark scope and claims boundary.
- `docs/PRODUCT_DIRECTION.md`: scope guardrails and v1 hardening lane.
- `docs/ROADMAP.md`: remaining before v1 publication.
- `docs/ARCHITECTURE.md`: runtime boundaries and deferred decisions.
- `docs/json-contracts.md`: JSON contract authority.
- `docs/failure-gallery.md`: deterministic CLI failure behavior.
- `scripts/verify_release_readiness.py`: release-readiness proof entry point.
- `scripts/benchmark_csvql.py`: benchmark proof entry point.
- `src/csvql/release_readiness.py`: release-readiness implementation.
- `src/csvql/benchmark_runner.py`: benchmark matrix implementation.
- `src/csvql/benchmarking.py`: benchmark artifact model and summary renderer.

Generated local evidence, not committed:

- `output/release-readiness/**`
- `output/benchmarks/**`
- wheels, sdists, smoke virtualenvs, benchmark JSON, benchmark Markdown summaries, and scratch transcripts under ignored `output/`.

Do not modify in this proof-only lane:

- Runtime source files.
- User-facing product docs, except the new dated proof note.
- `.superpowers/`.
- Existing untracked `docs/superpowers/plans/2026-07-02-csvql-editor-quality-v2.md` unless Richard separately approves a tracked-artifact decision.

## Direction Check

- Target lane: release-candidate eligibility proof for post-v0.9 hardening toward v1.
- Wedge strengthened: deterministic local workflow, documented release discipline, proof-backed status labels.
- Scope rejected: new features, docs repairs, version bump, publishing, tags, GitHub release, PyPI upload, safe mode, sandboxing, production-readiness claims, hidden cache/materialization, web/cloud/notebook/dataframe/AI/plugin scope.
- Contracts touched: none, unless proof exposes a blocker that Richard moves into a separate fix lane.
- Verification target: current-HEAD repo truth, full local gate, release-readiness proof, benchmark proof, manual QA matrix, unsupported-claim scan, final git status, and one tracked proof note.

---

### Task 1: Baseline Repo Truth And Authority Re-Ground

**Files:**

- Read: `AGENTS.md`
- Read: `docs/release-readiness.md`
- Read: `docs/release-notes/v1.md`
- Read: `.gitignore`

- [ ] **Step 1: Confirm current directory**

Run:

```bash
pwd
```

Expected: prints `/Users/richarddemke/Documents/csvql` or the resolved Dropbox-backed path for the same workspace.

- [ ] **Step 2: Confirm branch and dirty state**

Run:

```bash
git status --short --branch
```

Expected: starts with `## main`. Tracked files must be clean before proof begins. Existing untracked `.superpowers/` and `docs/superpowers/plans/2026-07-02-csvql-editor-quality-v2.md` may remain untracked and must not be committed in this lane.

- [ ] **Step 3: Confirm current HEAD**

Run:

```bash
git log -1 --oneline
```

Expected: record the exact commit. At plan-writing time the expected commit is `21c4baf fix: reset tui run status on rejected runs`; if HEAD has advanced, record the new commit and continue only if it is intentional.

- [ ] **Step 4: Confirm proof outputs are ignored**

Run:

```bash
rg -n "^output/$|^dist/$|^build/$|^\\.venv/" .gitignore
```

Expected: output includes ignore rules for `output/`, `dist/`, `build/`, and `.venv/`.

- [ ] **Step 5: Re-read release authority before running commands**

Run:

```bash
sed -n '1,240p' docs/release-readiness.md
```

Expected: documents the local candidate workflow, full local gate, release-readiness proof, benchmark proof, manual QA matrix, unsupported-claim scan, and no-publish boundary.

- [ ] **Step 6: Classify baseline result**

Record `baseline: passed` only if the current branch, HEAD, dirty state, ignored artifact policy, and release-readiness workflow are known before running proof commands.

If tracked files are dirty, stop and classify each tracked change before running proof.

---

### Task 2: Full Local Gate

**Files:**

- Test: `src/`
- Test: `tests/`
- Read: `pyproject.toml`

- [ ] **Step 1: Check patch whitespace before proof**

Run:

```bash
git diff --check
```

Expected: exits `0` with no output.

- [ ] **Step 2: Run Ruff format check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
```

Expected: exits `0` and reports files already formatted.

- [ ] **Step 3: Run Ruff lint**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
```

Expected: exits `0` and prints `All checks passed!`.

- [ ] **Step 4: Run mypy with all extras**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src
```

Expected: exits `0` and prints `Success: no issues found`.

- [ ] **Step 5: Run the full test suite with all extras**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest
```

Expected: exits `0` with all tests passing.

- [ ] **Step 6: Classify local gate**

Record `full local gate: passed` only if all five checks pass at the same HEAD.

If a command fails because of sandbox or dependency access, rerun the same command with escalation according to the active permissions instructions.

If a command fails because of repo behavior, stop and record the failure as a release-candidate blocker. Do not patch source or docs in this lane.

---

### Task 3: Release-Readiness Proof

**Files:**

- Read: `scripts/verify_release_readiness.py`
- Read: `src/csvql/release_readiness.py`
- Generated, ignored: `output/release-readiness/**`

- [ ] **Step 1: Run release-readiness proof**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

Expected: exits `0` and prints a proof summary covering version agreement, built wheel path, installed-wheel version smoke, installed-wheel inspect smoke, TUI extra import smoke, and `csvql menu --help` smoke.

- [ ] **Step 2: Inspect release-readiness artifacts**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python -c "from pathlib import Path; root = Path('output/release-readiness'); wheels = sorted((root / 'dist').glob('csvql-*.whl')); sdists = sorted((root / 'dist').glob('csvql-*.tar.gz')); python_path = root / 'smoke-venv' / 'bin' / 'python'; csvql_path = root / 'smoke-venv' / 'bin' / 'csvql'; assert wheels, 'missing built wheel'; assert sdists, 'missing built sdist'; assert python_path.exists(), 'missing smoke venv python'; assert csvql_path.exists(), 'missing installed csvql script'; print('release artifacts ok'); print(wheels[-1]); print(sdists[-1])"
```

Expected: exits `0`, prints `release artifacts ok`, then prints the latest wheel and sdist paths under `output/release-readiness/dist/`.

- [ ] **Step 3: Classify release-readiness proof**

Record `release-readiness proof: passed` only if both commands pass and the artifact paths are captured.

If this proof fails because package build, install, version agreement, TUI import, or menu help smoke fails, stop and record the failure as a release-candidate blocker. Do not patch source or docs in this lane.

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
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Expected: exits `0` and prints two paths: `benchmark.json` and `benchmark-summary.md` under the same new run directory in `output/benchmarks/`.

- [ ] **Step 2: Inspect latest benchmark artifact**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python -c "from pathlib import Path; import json; root = Path('output/benchmarks'); runs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime); assert runs, 'no benchmark run directories'; run = runs[-1]; artifact = run / 'benchmark.json'; summary = run / 'benchmark-summary.md'; payload = json.loads(artifact.read_text(encoding='utf-8')); assert payload['metadata']['schema_version'] == 1; assert payload['metadata']['csvql_version']; assert payload['metadata']['duckdb_version']; assert payload['metadata']['python_version']; assert payload['metadata']['platform']; assert payload['metadata']['generated_at']; assert {d['dataset_id'] for d in payload['datasets']} == {'fixture', 'synthetic_medium', 'synthetic_large'}; assert len(payload['cases']) == 18; assert summary.exists(); assert 'Local benchmark evidence only.' in payload['notes']; print('benchmark artifacts ok'); print(artifact); print(summary)"
```

Expected: exits `0`, prints `benchmark artifacts ok`, then prints the latest benchmark JSON and Markdown summary paths.

- [ ] **Step 3: Classify benchmark proof**

Record `benchmark proof: passed` only if both commands pass and artifact paths are captured from the current HEAD.

If the benchmark fails, stop and record the failing case or artifact assertion as a release-candidate blocker. Do not patch benchmark code or docs in this lane.

---

### Task 5: Manual V1 QA Matrix At Current HEAD

**Files:**

- Read: `docs/v1-manual-qa.md`
- Exercise: `examples/saas_revenue/data/revenue_movements.csv`
- Exercise: `examples/saas_revenue/.csvql/results/**`
- Generated, ignored or example output: local QA outputs created by documented commands.

- [ ] **Step 1: Record the manual proof environment**

Record:

- date: `2026-07-02`
- commit: output of `git log -1 --oneline`
- terminal app or PTY used for TUI proof
- shell: output of `echo $SHELL`
- OS context if relevant to Mac keybindings

- [ ] **Step 2: Run documented version setup**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql --version
```

Expected: prints `1.0.0`.

- [ ] **Step 3: Run documented CLI single-file query**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query examples/saas_revenue/data/revenue_movements.csv "SELECT COUNT(*) AS movement_count FROM revenue_movements"
```

Expected: table output contains `movement_count`.

- [ ] **Step 4: Run documented CLI project catalog query**

Run from `examples/saas_revenue`:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query "SELECT COUNT(*) AS customer_count FROM customers"
```

Expected: table output contains `customer_count`.

- [ ] **Step 5: Run documented export and reusable CSV source proof**

Run from `examples/saas_revenue`:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql export queries/revenue_health.sql --format csv --out .csvql/results/revenue_health.csv --force
```

Expected: exits `0`.

Run from `examples/saas_revenue`:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query --table revenue_health_result=.csvql/results/revenue_health.csv "SELECT COUNT(*) AS result_rows FROM revenue_health_result"
```

Expected: table output contains `result_rows`.

- [ ] **Step 6: Run documented bad SQL proof**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query --table revenue_movements=examples/saas_revenue/data/revenue_movements.csv "SELECT missing_column FROM revenue_movements"
```

Expected: exits `1`, prints an error beginning `DuckDB query failed`, and suggests checking table names, column names, and SQL syntax.

- [ ] **Step 7: Run documented missing-file proof**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query missing.csv "SELECT 1"
```

Expected: exits `4` and reports that the CSV file was not found.

- [ ] **Step 8: Run documented export overwrite refusal and force proof**

Run from `examples/saas_revenue`:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql export queries/revenue_health.sql --format csv --out output/revenue-health.csv
```

Expected: exits `0`.

Run from `examples/saas_revenue`:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql export queries/revenue_health.sql --format csv --out output/revenue-health.csv
```

Expected: exits `10` with overwrite guidance.

Run from `examples/saas_revenue`:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql export queries/revenue_health.sql --format csv --out output/revenue-health.csv --force
```

Expected: exits `0`.

- [ ] **Step 9: Launch the TUI**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras csvql menu examples/saas_revenue/data/revenue_movements.csv
```

Expected: workbench opens with a loaded `revenue_movements` source alias.

- [ ] **Step 10: Prove TUI repeated query and history behavior**

In the TUI SQL editor, run with `F4`:

```sql
SELECT COUNT(*) AS movement_count FROM revenue_movements;
```

Expected: result grid shows `movement_count`.

Then run with `F4`:

```sql
SELECT movement_type, COUNT(*) AS rows
FROM revenue_movements
GROUP BY movement_type;
```

Expected: result grid shows grouped rows, history records both attempts, and the editor remains usable.

- [ ] **Step 11: Prove TUI no-result SQL behavior**

In the TUI SQL editor, run with `F4`:

```sql
CREATE TABLE scratch AS SELECT 1 AS value;
```

Expected: prior tabular results are cleared and the TUI reports that the statement completed with no tabular result to display.

- [ ] **Step 12: Prove TUI derived save and query behavior**

In the TUI, save the last successful tabular result with `Ctrl+S`, use alias `movement_counts`, then run:

```sql
SELECT * FROM movement_counts;
```

Expected: `.csvql/results/movement_counts.csv` is written under the current local root, Sources shows `movement_counts` with kind `derived`, and the query returns rows from the saved result.

- [ ] **Step 13: Prove current Editor Quality v2 run modes remain usable**

In the TUI SQL editor, place the cursor inside the second statement and press `F4`:

```sql
SELECT * FROM missing_table;

SELECT COUNT(*) AS proof_count FROM revenue_movements;
```

Expected: only the current statement runs, result grid shows `proof_count`, and the first bad statement is not executed.

Then press `F12`.

Expected: whole-editor execution attempts both statements and reports the deliberate `missing_table` error.

- [ ] **Step 14: Prove current Source Intelligence v1 actions remain usable**

In the TUI Sources pane, select `revenue_movements`, then press `c`.

Expected: source columns load and the status reports the number of loaded columns.

Press `l`.

Expected: the SQL editor receives the quoted selected-source alias.

Press `x`.

Expected: the SQL editor receives a starter query for the selected source.

- [ ] **Step 15: Prove quit path**

In the TUI, press `F9`.

Expected: the app exits cleanly without a traceback.

- [ ] **Step 16: Classify manual QA**

Record `manual QA: passed` only if every documented CLI item and every TUI item above passed at the current HEAD.

If a synthetic key burst races in a PTY, retry the same TUI action as standalone key presses. Record the caveat if standalone key presses work. If standalone keys fail, record the item as a blocker.

---

### Task 6: Unsupported-Claim And Authority Scan

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

Expected: matches exist for guardrails, label rules, non-claims, and candidate workflow language.

- [ ] **Step 2: Classify each match**

Classify each match as one of:

- guardrail: says not to claim sandboxing, production readiness, broad large-file performance, `v1-stable`, or release status without proof
- label rule: defines when a label may be used
- workflow instruction: describes the local candidate proof process
- blocker: currently claims CSVQL is v1-ready, `v1-stable`, production-safe, production-ready, sandbox-safe, sandboxed, large-file-proven, or broadly large-file performant without proof

Expected: no blocker classifications.

- [ ] **Step 3: Compare authority docs to proof results**

Read the sections that define release status and runtime boundaries:

```bash
sed -n '1,220p' docs/release-readiness.md
```

Expected: current label rules match the observed proof result and do not imply publishing, tagging, PyPI upload, production readiness, sandbox safety, or broad large-file proof.

Read release notes status and boundaries:

```bash
sed -n '1,220p' docs/release-notes/v1.md
```

Expected: release notes identify a local release state and candidate proof checklist without claiming external release action.

- [ ] **Step 4: Classify authority scan**

Record `authority scan: passed` only if no blocker classification exists and authority docs agree with observed proof results.

If a blocker classification exists, do not patch it in this lane. Record it in the proof note as an eligibility blocker and recommend a separate docs-fix lane.

---

### Task 7: Write The Tracked Proof Note

**Files:**

- Create: `docs/release-candidate-proof-2026-07-02.md`

- [ ] **Step 1: Create the proof note from observed evidence only**

Create `docs/release-candidate-proof-2026-07-02.md` with these sections in this order:

- `# CSVQL Release Candidate Proof Packet - 2026-07-02`
- `## Verdict`
- `## Baseline`
- `## Automated Proof`
- `## Release-Readiness Artifacts`
- `## Benchmark Artifacts`
- `## Manual QA`
- `## Unsupported-Claim Scan`
- `## Generated Artifact Policy`
- `## Risks And Caveats`
- `## Blockers`
- `## Next Task`

The note must include only observed values from Tasks 1 through 6. Do not leave guessed output, empty sections, or draft markers.

- [ ] **Step 2: Use one exact verdict label**

Write exactly one of these verdict lines under `## Verdict`:

```markdown
Verdict: release-candidate eligible
```

Use this only if baseline, full local gate, release-readiness proof, benchmark proof, manual QA, and authority scan all pass.

```markdown
Verdict: blocked
```

Use this if any required proof command, manual QA item, release artifact inspection, benchmark artifact inspection, or authority scan fails.

```markdown
Verdict: v1-hardening
```

Use this only if proof was intentionally stopped before completion with Richard's approval and the repo remains in the hardening lane.

- [ ] **Step 3: Record command results with enough detail to audit**

For each automated command, record:

- exact command
- exit code
- key success or failure line
- current `HEAD`
- artifact path when the command created one

Expected: a reader can reconstruct which local proof ran without reading chat history.

- [ ] **Step 4: Record manual QA in checklist form**

For each manual QA item, record `passed`, `failed`, or `not run with reason`.

Expected: no item is silently omitted.

- [ ] **Step 5: Record risks without expanding scope**

At minimum, include these risk classifications:

- terminal key handling varies; `F4` is the reliable run fallback
- synthetic PTY key bursts can race; standalone key results are the proof authority
- SQL is trusted local DuckDB SQL, not sandboxed
- benchmark proof is local evidence only, not broad large-file proof
- generated `output/` artifacts are ignored local evidence, not tracked release artifacts

Expected: risks are described as release-proof caveats, not as new product commitments.

- [ ] **Step 6: Scan the proof note for accidental overclaims**

Run:

```bash
rg -n "production-safe|sandbox-safe|large-file-proven|v1-stable|published|PyPI|GitHub release" docs/release-candidate-proof-2026-07-02.md
```

Expected: no match presents a current claim. Matches are allowed only if they appear in caveat or no-publish language.

- [ ] **Step 7: Confirm proof note diff is the only intended tracked content change**

Run:

```bash
git status --short
```

Expected: `docs/release-candidate-proof-2026-07-02.md` appears as a new file. Existing untracked `.superpowers/` and `docs/superpowers/plans/2026-07-02-csvql-editor-quality-v2.md` may still appear. Generated `output/` artifacts must not appear as untracked files if `.gitignore` is correct.

---

### Task 8: Final Hygiene And Handoff

**Files:**

- Read: `docs/release-candidate-proof-2026-07-02.md`
- Optional stage after Richard approval: `docs/release-candidate-proof-2026-07-02.md`

- [ ] **Step 1: Re-run final git status**

Run:

```bash
git status --short --branch
```

Expected: tracked changes are limited to the new proof note unless Richard separately approved adding the plan. `.superpowers/` remains untracked.

- [ ] **Step 2: Decide whether to stage and commit the proof note**

If Richard approved committing the proof note, run:

```bash
git add docs/release-candidate-proof-2026-07-02.md
```

Expected: only the proof note is staged.

Then run:

```bash
git status --short
```

Expected: staged file is `A  docs/release-candidate-proof-2026-07-02.md`; `.superpowers/` and the older untracked Editor Quality v2 plan are not staged.

- [ ] **Step 3: Commit only after staging is verified**

If Richard approved committing and staging is verified, run:

```bash
git commit -m "docs: add release candidate proof packet"
```

Expected: commit succeeds and includes only the proof note.

- [ ] **Step 4: Report final outcome plainly**

Final handoff must include:

- final verdict from the proof note
- current branch and `HEAD`
- full local gate result
- release-readiness result and artifact paths
- benchmark result and artifact paths
- manual QA result
- unsupported-claim scan result
- whether the proof note was committed or left unstaged
- skipped checks, if any
- remaining risks
- next task

Expected: no release publish, tag, PyPI upload, GitHub release, version bump, source change, docs repair, `.superpowers/` commit, or generated artifact commit occurred.

---

## Self-Review

Spec coverage:

- Proof-only scope is covered by Tasks 1 through 8.
- Tracked proof note is covered by Task 7.
- Full local gate, release-readiness proof, benchmark proof, manual QA, and unsupported-claim scan are covered by Tasks 2 through 6.
- No product/docs repair scope is enforced in File Structure, Direction Check, and each blocker classification step.

Placeholder scan:

- This plan contains no unresolved filler sections or deferred-work markers.

Type and command consistency:

- All commands use repo-local `uv` execution.
- TUI proof uses `--all-extras`.
- Generated artifacts stay under ignored `output/` paths.
- The only planned tracked proof output is `docs/release-candidate-proof-2026-07-02.md`.

Residual risk:

- Release-readiness and benchmark commands may need dependency/build access through `uv`; sandbox or network failures must follow the active permissions escalation flow.
- Manual TUI proof depends on terminal key behavior; standalone key actions are more reliable than synthetic key bursts.
- A blocker found by proof is recorded, not fixed, until Richard approves a separate fix lane.
