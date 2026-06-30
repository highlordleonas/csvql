# CSVQL v1 Proof Refresh And Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a fresh, evidence-backed v1 hardening assessment by running CSVQL's existing local gates, release-readiness proof, benchmark proof, claim audit, and final gap classification.

**Architecture:** This plan is evidence-first and does not add new product surface. It uses the existing repo scripts as proof authorities, treats generated `output/` files as ignored local evidence, updates tracked docs only when fresh proof contradicts current docs, and finishes with an explicit status label: `v1-hardening`, `release-candidate` eligible, or blocked.

**Tech Stack:** Python 3.11+, `uv`, Ruff, mypy, pytest, DuckDB, Typer CLI, git, Markdown docs.

---

## File Structure

Create:

- `docs/superpowers/plans/2026-06-30-csvql-v1-proof-refresh-gap-closure.md`: this executable implementation plan.

Read:

- `docs/superpowers/specs/2026-06-30-csvql-v1-proof-refresh-gap-closure-design.md`: approved design authority.
- `AGENTS.md`: repo-local v1-stable definition, proof language, and execution contract.
- `docs/release-readiness.md`: release proof checklist and label rules.
- `docs/benchmarking.md`: benchmark matrix and claims boundary.
- `docs/ROADMAP.md`: remaining pre-v1 work.
- `docs/PRODUCT_DIRECTION.md`: v1 hardening scope guardrails.
- `README.md`: user-facing current behavior and status.
- `scripts/verify_release_readiness.py`: release-readiness entry point.
- `scripts/benchmark_csvql.py`: benchmark entry point.
- `src/csvql/release_readiness.py`: release-readiness implementation.
- `src/csvql/benchmark_runner.py`: benchmark matrix implementation.
- `src/csvql/benchmarking.py`: benchmark artifact model and summary renderer.

Modify only if fresh proof exposes a contradiction:

- `docs/release-readiness.md`: status, label, or proof-command wording.
- `docs/ROADMAP.md`: remaining pre-v1 status.
- `docs/benchmarking.md`: benchmark instruction or claim-boundary wording.
- `README.md`: user-facing readiness language.
- `src/csvql/release_readiness.py` and `tests/test_release_readiness.py`: only for a release proof workflow defect.
- `src/csvql/benchmark_runner.py`, `src/csvql/benchmarking.py`, `tests/test_benchmark_runner.py`, and `tests/test_benchmarking.py`: only for a benchmark proof workflow defect.

Do not commit:

- `output/benchmarks/**`
- `output/release-readiness/**`
- build artifacts
- wheels
- sdists
- smoke virtualenvs
- scratch transcripts

## Direction Check

- Target lane: v1 hardening.
- Wedge strengthened: repeatable local CLI proof, deterministic output confidence, release evidence discipline.
- Scope rejected: publishing, version bump, JSON envelope migration, exit-code redesign, safe mode, cache/materialization, web/cloud/notebook/dataframe/AI/plugin scope.
- Contracts touched: none by default. If a proof defect forces code or docs changes, list affected command behavior, JSON fields, exit codes, config schema, docs, and tests before editing.
- Verification target: full `uv run` gate, release-readiness script, benchmark script, artifact inspection, claim audit, and final git status.

---

### Task 1: Baseline Repo Truth

**Files:**

- Read: `docs/superpowers/specs/2026-06-30-csvql-v1-proof-refresh-gap-closure-design.md`
- Read: `AGENTS.md`
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

Expected: starts with `## main`. If any tracked file is dirty, classify it before running proof and do not overwrite user work.

- [ ] **Step 3: Confirm current HEAD**

Run:

```bash
git show --stat --oneline HEAD
```

Expected: `2ccb964 docs: add v1 proof refresh design` or a later intentional commit that includes the approved proof-refresh design.

- [ ] **Step 4: Confirm generated proof outputs are ignored**

Run:

```bash
rg -n "^output/$|^dist/$|^build/$|^\\.venv/" .gitignore
```

Expected: output includes `output/`, `dist/`, `build/`, and `.venv/`.

- [ ] **Step 5: Re-read the approved design before execution**

Run:

```bash
sed -n '1,380p' docs/superpowers/specs/2026-06-30-csvql-v1-proof-refresh-gap-closure-design.md
```

Expected: the spec describes proof refresh, release-candidate assessment, no publish/tag/version bump, and no generated output commits.

---

### Task 2: Full Local Gate

**Files:**

- Read: `pyproject.toml`
- Test: `src/`
- Test: `tests/`

- [ ] **Step 1: Check whitespace and patch safety before proof**

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

- [ ] **Step 4: Run mypy**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: exits `0` and prints `Success: no issues found`.

- [ ] **Step 5: Run pytest**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest
```

Expected: exits `0` with all tests passing.

- [ ] **Step 6: Classify local-gate result**

If all commands pass, record `full local gate: passed` for the final handoff.

If a command fails because of dependency or sandbox access, rerun the same command with escalation according to the active permissions instructions.

If a command fails because of repo behavior, stop before release-readiness proof and diagnose the failing command. Do not edit docs to hide a failing gate.

---

### Task 3: Release-Readiness Proof

**Files:**

- Read: `scripts/verify_release_readiness.py`
- Read: `src/csvql/release_readiness.py`
- Generated, ignored: `output/release-readiness/**`

- [ ] **Step 1: Run the release-readiness script**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

Expected: exits `0` and prints JSON for the installed-wheel `inspect` smoke command. The JSON object includes `source`, `dialect`, `columns`, `row_count`, and `warnings`.

- [ ] **Step 2: Inspect release artifacts**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python -c "from pathlib import Path; root = Path('output/release-readiness'); wheels = sorted((root / 'dist').glob('csvql-*.whl')); sdists = sorted((root / 'dist').glob('csvql-*.tar.gz')); python_path = root / 'smoke-venv' / 'bin' / 'python'; csvql_path = root / 'smoke-venv' / 'bin' / 'csvql'; smoke_csv = root / 'smoke' / 'orders.csv'; assert wheels, 'missing built wheel'; assert sdists, 'missing built sdist'; assert python_path.exists(), 'missing smoke venv python'; assert csvql_path.exists(), 'missing installed csvql script'; assert smoke_csv.exists(), 'missing smoke CSV'; print('release artifacts ok'); print(wheels[-1]); print(sdists[-1])"
```

Expected: exits `0`, prints `release artifacts ok`, then prints one wheel path and one sdist path under `output/release-readiness/dist/`.

- [ ] **Step 3: Classify release-readiness result**

If both release-readiness steps pass, record `release-readiness proof: passed` and keep the printed wheel and sdist paths for the final handoff.

If the script fails during `uv build`, `uv venv`, or `uv pip install` with network or sandbox symptoms, rerun the same command with escalation according to the active permissions instructions.

If the script fails because version strings disagree, package build output is missing, wheel install fails from repo packaging, or the installed smoke command fails, diagnose that exact step before running benchmark proof.

---

### Task 4: Benchmark Proof

**Files:**

- Read: `scripts/benchmark_csvql.py`
- Read: `src/csvql/benchmark_runner.py`
- Read: `src/csvql/benchmarking.py`
- Generated, ignored: `output/benchmarks/**`

- [ ] **Step 1: Run the benchmark script**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Expected: exits `0` and prints two paths: the generated `benchmark.json` path and the generated `benchmark-summary.md` path under `output/benchmarks/`.

- [ ] **Step 2: Inspect the latest benchmark artifact**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python -c "from pathlib import Path; import json; root = Path('output/benchmarks'); runs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime); assert runs, 'no benchmark run directories'; run = runs[-1]; artifact = run / 'benchmark.json'; summary = run / 'benchmark-summary.md'; payload = json.loads(artifact.read_text(encoding='utf-8')); assert payload['metadata']['schema_version'] == 1; assert payload['metadata']['csvql_version']; assert payload['metadata']['duckdb_version']; assert payload['metadata']['python_version']; assert payload['metadata']['platform']; assert payload['metadata']['generated_at']; assert {d['dataset_id'] for d in payload['datasets']} == {'fixture', 'synthetic_medium', 'synthetic_large'}; assert len(payload['cases']) == 18; assert summary.exists(); assert 'Local benchmark evidence only.' in payload['notes']; print('benchmark artifacts ok'); print(artifact); print(summary)"
```

Expected: exits `0`, prints `benchmark artifacts ok`, then prints the latest benchmark JSON and Markdown summary paths.

- [ ] **Step 3: Classify benchmark result**

If both benchmark steps pass, record `benchmark proof: passed` and keep the printed artifact and summary paths for the final handoff.

If the benchmark script fails because a CLI command exits non-zero, diagnose the failing benchmark case before changing docs.

If it fails because generated datasets cannot be written under `output/benchmarks`, inspect permissions and `.gitignore` before changing source.

---

### Task 5: Claim Audit

**Files:**

- Read: `AGENTS.md`
- Read: `README.md`
- Read: `docs/PRODUCT_DIRECTION.md`
- Read: `docs/ROADMAP.md`
- Read: `docs/ARCHITECTURE.md`
- Read: `docs/json-contracts.md`
- Read: `docs/release-readiness.md`
- Read: `docs/benchmarking.md`
- Read: `docs/failure-gallery.md`

- [ ] **Step 1: Search for readiness, sandbox, production, and performance claims**

Run:

```bash
rg -n "v1-ready|release-candidate|v1-stable|production-safe|production readiness|sandbox-safe|sandbox|large-file-proven|large-file performance|safe mode" AGENTS.md README.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/release-readiness.md docs/benchmarking.md docs/failure-gallery.md
```

Expected: every hit is one of these allowed categories:

- historical roadmap or design context
- negative guardrail
- explicit label rule
- claims-boundary statement
- current-lane statement that says CSVQL is still `v1-hardening`

- [ ] **Step 2: Search for stale current-lane wording**

Run:

```bash
rg -n "current lane is v0\\.1|current lane is v0\\.7|v0\\.1 current|v0\\.7 current|v1 ready|production safe|sandbox safe|large file proven" AGENTS.md README.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/release-readiness.md docs/benchmarking.md docs/failure-gallery.md
```

Expected: exits `1` with no matches. If it exits `0`, inspect every hit and update the smallest affected doc sentence.

- [ ] **Step 3: Confirm generated outputs are ignored**

Run:

```bash
git status --short --ignored output
```

Expected: generated proof outputs appear only as ignored paths such as `!! output/`, or there is no output if the directory was not created. There must be no `?? output/` or staged generated artifact.

---

### Task 6: Gap Assessment And Documentation Decision

**Files:**

- Read: `docs/release-readiness.md`
- Read: `AGENTS.md`
- Read: `docs/ROADMAP.md`
- Modify: `docs/release-readiness.md`, only if current proof status or label rules are contradicted by observed evidence.
- Modify: `docs/ROADMAP.md`, only if remaining pre-v1 status changes.
- Modify: `docs/benchmarking.md`, only if benchmark instructions or claim boundaries are contradicted by observed evidence.
- Modify: `README.md`, only if user-facing readiness language is contradicted by observed evidence.

- [ ] **Step 1: Compare proof results to release-candidate conditions**

Run:

```bash
sed -n '1,220p' docs/release-readiness.md
```

Expected: release-candidate conditions include authority agreement, passing release-readiness script, refreshed benchmark proof or cited current local artifact, full local gate, changelog or release-note material, and no unsupported sandbox, security-isolation, production-readiness, or large-file performance claims.

- [ ] **Step 2: Compare proof results to repo-defined v1-stable conditions**

Run:

```bash
sed -n '1,80p' AGENTS.md
```

Expected: `v1-stable` requires documented CLI behavior, authority agreement, failure documentation, stable or migrated contracts, fresh benchmark and release-readiness proof, release workflow and changelog or release-note material, full local gate, and no unsupported claims.

- [ ] **Step 3: Decide whether tracked docs need edits**

Use this decision table:

| Observation | Action |
| --- | --- |
| All proof commands pass and docs already describe remaining contract/changelog gaps | Do not edit tracked docs solely to add a timestamp. Report proof paths in the final handoff. |
| A doc claims `release-candidate`, `v1-stable`, sandbox safety, production readiness, or broad large-file performance without proof | Patch only the false sentence and rerun the claim audit. |
| A proof command fails and docs imply that proof is fresh or passing | Patch the affected readiness language to say the proof is blocked, then rerun the claim audit. |
| A proof script defect is found in repo-owned code | Fix the script path with a focused test, rerun the failed proof, then rerun the full local gate. |

- [ ] **Step 4: Classify final status**

Use one status label:

- `v1-hardening`: proof refreshed but pre-v1 contract, changelog, release-note, or final approval gaps remain.
- `release-candidate eligible`: full local gate, release-readiness proof, benchmark proof, claim audit, authority agreement, and changelog or release-note material are all satisfied.
- `blocked`: at least one required proof command cannot pass or cannot be verified.

Expected for the current lane: likely `v1-hardening`, because contract stabilization and release-note work remain listed pre-v1 concerns unless another committed change has already satisfied them.

---

### Task 7: Rerun Checks After Any Tracked Edit

**Files:**

- Modify only as discovered in Task 6.
- Test only as required by the changed file type.

- [ ] **Step 1: Inspect tracked changes**

Run:

```bash
git status --short
```

Expected: either no tracked changes, or only files listed in this plan's file boundary.

- [ ] **Step 2: Check edited files for whitespace issues**

Run:

```bash
git diff --check
```

Expected: exits `0` with no output.

- [ ] **Step 3: Rerun focused checks for docs-only edits**

If only Markdown docs changed, run:

```bash
rg -n "v1-ready|production-safe|sandbox-safe|large-file-proven|large-file performance" AGENTS.md README.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/release-readiness.md docs/benchmarking.md docs/failure-gallery.md
```

Expected: no unsupported positive claims. Historical, negative, or label-rule hits are allowed only when classified in the final handoff.

- [ ] **Step 4: Rerun full checks for source or test edits**

If any `src/` or `tests/` file changed, run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest
```

Expected: every command exits `0`.

- [ ] **Step 5: Rerun the proof command that originally failed**

If Task 3 failed before a source/test fix, rerun:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

Expected: exits `0` and prints installed-wheel inspect JSON.

If Task 4 failed before a source/test fix, rerun:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Expected: exits `0` and prints benchmark JSON and Markdown summary paths.

---

### Task 8: Commit Only Intentional Tracked Changes

**Files:**

- Stage only files listed in this plan's file boundary.
- Do not stage ignored `output/` artifacts.

- [ ] **Step 1: Inspect final status before staging**

Run:

```bash
git status --short
```

Expected: one of these states:

- no tracked changes, when proof passed or failed without requiring tracked edits
- only approved docs, source, or test changes from the file boundary
- the plan file itself when this plan has not yet been committed

- [ ] **Step 2: Stage intentional tracked changes only when changes exist**

If tracked changes exist, run:

```bash
git add docs/superpowers/plans/2026-06-30-csvql-v1-proof-refresh-gap-closure.md docs/release-readiness.md docs/ROADMAP.md docs/benchmarking.md README.md src/csvql/release_readiness.py src/csvql/benchmark_runner.py src/csvql/benchmarking.py tests/test_release_readiness.py tests/test_benchmark_runner.py tests/test_benchmarking.py
```

Expected: stages only existing changed files from the approved file boundary.

- [ ] **Step 3: Review staged diff**

Run:

```bash
git diff --cached --stat
git diff --cached --check
```

Expected: staged stat includes only intended tracked files, and staged diff check exits `0`.

- [ ] **Step 4: Commit when tracked changes exist**

If there are staged changes, run:

```bash
git commit -m "chore: refresh v1 proof status"
```

Expected: commit succeeds. If the only tracked change is this plan file and the user did not approve committing the plan, skip this step and leave the plan uncommitted.

- [ ] **Step 5: Confirm no generated outputs are staged**

Run:

```bash
git status --short --ignored output
```

Expected: no staged `output/` files. Ignored generated proof artifacts may appear as `!! output/`.

---

### Task 9: Final Handoff

**Files:**

- Read: current git status.
- Read: latest proof command outputs from the active session.

- [ ] **Step 1: Capture final repo status**

Run:

```bash
git status --short --branch
```

Expected: clean tracked tree or clearly listed intentional uncommitted plan/docs changes.

- [ ] **Step 2: Capture final HEAD**

Run:

```bash
git show --stat --oneline HEAD
```

Expected: prints the latest committed work. If no implementation commit was needed, `HEAD` may remain the plan/spec commit from before execution.

- [ ] **Step 3: Report proof evidence plainly**

The final handoff must include:

- final status label: `v1-hardening`, `release-candidate eligible`, or `blocked`
- full local gate command results
- release-readiness proof result and artifact paths
- benchmark proof result and artifact paths
- claim-audit result
- tracked files changed
- generated outputs left ignored
- skipped checks and why
- remaining risks or next task

- [ ] **Step 4: State the next task**

If final status is `v1-hardening`, the next task should be one of:

- contract stabilization decision for JSON, exit codes, config schema, Python API, and DuckDB minimum
- release workflow and changelog or release-note material
- targeted fix for the blocking proof command

If final status is `release-candidate eligible`, the next task should be explicit user approval for final release action. Do not publish, tag, or push as part of this plan.

---

## Self-Review Checklist

- Spec coverage: Tasks 1 through 9 cover baseline truth, full local gate, release-readiness proof, benchmark proof, artifact inspection, claim audit, docs decision, reruns after edits, commit hygiene, and final status classification.
- Placeholder scan: the plan contains no open-ended implementation slots.
- Scope check: the plan uses existing scripts and does not add release automation, public behavior changes, or product surface.
- Type and command consistency: every command uses repo-local `uv` execution where required and keeps generated output under ignored `output/`.
- Residual risk: benchmark and release-readiness commands may require dependency access through `uv`; if sandbox or network failures occur, escalation must use the active permissions flow.
