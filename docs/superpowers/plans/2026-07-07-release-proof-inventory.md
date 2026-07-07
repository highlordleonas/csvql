# Release Proof Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run and record a current same-`HEAD` LocalQL release-proof inventory without changing runtime behavior or making release eligibility claims.

**Architecture:** This is an evidence-execution lane, not a code-change lane. It creates one ignored inventory directory under `output/`, captures command output and status files, records authority-review notes, and writes a final `RESULT.md` classification while keeping tracked Git status clean.

**Tech Stack:** Shell commands, repo-local `uv`, pytest/Ruff/mypy, release-readiness and benchmark scripts, Markdown evidence files under ignored `output/`.

## Global Constraints

- LocalQL is the installable distribution name.
- Runtime/user-facing surfaces stay `csvql` CLI, `csvql` import package, `.csvql.yml`, and `csvql menu`.
- Use repo-local `uv`; do not install global dependencies.
- Use `UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql` for `uv` commands in this environment.
- Do not claim sandbox safety, safe untrusted SQL, security isolation, production readiness, release-candidate eligibility, `v1-stable`, or broad large-file proof.
- Do not tag, publish to PyPI, create a GitHub release, upload artifacts, push, configure remotes, change versions, or create release artifacts.
- Do not add a web app, cloud connectors, NLP execution, dataframe-first API, plugin system, hidden cache/materialization, or broader platform scope.
- Do not change runtime behavior, keybindings, help text, footer labels, SQL execution semantics, DuckDB behavior, package metadata, schemas, migrations, validation SQL, or database contracts.
- Do not run manual TUI terminal matrix work, screenshots, GUI terminal evidence, or outside-observer coordination in this lane.
- Treat generated files under `output/release-proof-inventory-*` as ignored local proof artifacts; do not commit them unless a separate tracked-artifact decision is made.
- Classify the result as `v1-hardening` or `blocked` unless every documented release-readiness prerequisite is satisfied on the same `HEAD`.

---

## Scope Check

This plan is one proof-inventory slice. It intentionally does not repair docs, change code, collect manual GUI evidence, or pursue release eligibility. If the inventory finds blockers, those become a later design/plan.

## File Structure

Every execution task uses this computed run directory:

```bash
run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"
```

- Create ignored directory: `$run_dir/`
  - One local proof root for this execution, tied to the execution-time `HEAD`.
- Create ignored directory: `$run_dir/commands/`
  - Captured stdout/stderr and exit-status files for each proof command.
- Create ignored directory: `$run_dir/release-readiness/`
  - Work directory for `scripts/verify_release_readiness.py`.
- Create ignored directory: `$run_dir/package-audit/`
  - Reserved for package-audit notes if needed.
- Create ignored directory: `$run_dir/benchmarks/`
  - Work directory for benchmark artifacts.
- Create ignored file: `$run_dir/claim-scan.txt`
  - Raw unsupported-claim scan output.
- Create ignored file: `$run_dir/authority-review.md`
  - Human-readable classification of authority-doc agreement and obvious stale claims.
- Create ignored file: `$run_dir/RESULT.md`
  - Final proof inventory summary and conservative classification.
- Do not modify tracked source, docs, tests, package metadata, or release labels during execution.
- Do not create a Git commit during execution. The deliverable is ignored local evidence plus a final status report.

---

### Task 1: Prepare Inventory Root And Capture Baseline Truth

**Files:**
- Create ignored: `$run_dir/`
- Create ignored: `$run_dir/commands/`

**Interfaces:**
- Consumes: Git repo at current `main` `HEAD`.
- Produces: `commands/00-*.txt` and `commands/00-*.status` files used by `RESULT.md`.

- [ ] **Step 1: Confirm tracked status is clean before proof starts**

Run:

```bash
git status --short --branch
```

Expected: output starts with `## main` and has no tracked file changes.

- [ ] **Step 2: Create the ignored inventory directories**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; mkdir -p "$run_dir/commands" "$run_dir/release-readiness" "$run_dir/package-audit" "$run_dir/benchmarks"; printf "%s\n" "$run_dir" > "$run_dir/RUN_DIR.txt"'
```

Expected: command exits `0` and creates one run directory named from the current short `HEAD`.

- [ ] **Step 3: Capture physical repo path**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; pwd -P > "$run_dir/commands/00-pwd.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/00-pwd.status"'
```

Expected: `00-pwd.status` contains `0`.

- [ ] **Step 4: Capture Git status**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; git status --short --branch > "$run_dir/commands/00-git-status.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/00-git-status.status"'
```

Expected: `00-git-status.status` contains `0`, and `00-git-status.txt` starts with `## main`.

- [ ] **Step 5: Capture current commit**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; git log -1 --oneline > "$run_dir/commands/00-git-log-head.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/00-git-log-head.status"'
```

Expected: `00-git-log-head.status` contains `0`, and the recorded commit matches the current `HEAD`.

- [ ] **Step 6: Capture remote state**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; git remote -v > "$run_dir/commands/00-git-remote.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/00-git-remote.status"'
```

Expected: `00-git-remote.status` contains `0`. Empty `00-git-remote.txt` means no remote is configured.

- [ ] **Step 7: Capture tags pointing at HEAD**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; git tag --points-at HEAD > "$run_dir/commands/00-git-tags-at-head.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/00-git-tags-at-head.status"'
```

Expected: `00-git-tags-at-head.status` contains `0`. Empty `00-git-tags-at-head.txt` means no tag points at `HEAD`.

- [ ] **Step 8: Verify ignored artifacts do not dirty tracked status**

Run:

```bash
git status --short --branch
```

Expected: output starts with `## main` and has no tracked file changes. Ignored `output/` artifacts should not appear.

---

### Task 2: Run Full Local Automated Gate

**Files:**
- Create ignored: `$run_dir/commands/10-*.txt`
- Create ignored: `$run_dir/commands/10-*.status`

**Interfaces:**
- Consumes: inventory root from Task 1.
- Produces: automated gate command outputs used by `RESULT.md`.

- [ ] **Step 1: Run Ruff format check**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff format --check . > "$run_dir/commands/10-ruff-format-check.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/10-ruff-format-check.status"'
```

Expected: `10-ruff-format-check.status` contains `0`.

- [ ] **Step 2: Run Ruff lint check**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check . > "$run_dir/commands/10-ruff-check.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/10-ruff-check.status"'
```

Expected: `10-ruff-check.status` contains `0`.

- [ ] **Step 3: Run mypy over `src`**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras mypy src > "$run_dir/commands/10-mypy-src.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/10-mypy-src.status"'
```

Expected: `10-mypy-src.status` contains `0`.

- [ ] **Step 4: Run full pytest**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest > "$run_dir/commands/10-pytest.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/10-pytest.status"'
```

Expected: `10-pytest.status` contains `0`.

- [ ] **Step 5: Record failures without stopping the inventory**

If any `10-*.status` file contains a nonzero value, do not claim the local gate passed. Continue to independent proof tasks where safe and classify the final inventory as `blocked` if the failure prevents a useful current-state inventory.

---

### Task 3: Run Release-Readiness Proof And Package Audit

**Files:**
- Create ignored: `$run_dir/commands/20-*.txt`
- Create ignored: `$run_dir/commands/20-*.status`
- Create ignored: `$run_dir/release-readiness/**`

**Interfaces:**
- Consumes: full local gate outputs from Task 2.
- Produces: release-readiness summary, built local artifacts, and package audit output.

- [ ] **Step 1: Run release-readiness proof into the inventory directory**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run python scripts/verify_release_readiness.py --work-dir "$run_dir/release-readiness" > "$run_dir/commands/20-release-readiness.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/20-release-readiness.status"'
```

Expected: `20-release-readiness.status` contains `0`. If this fails with a network, cache, or environment issue, record the failure exactly; rerun only after applying the permissions/escalation rules for the current environment.

- [ ] **Step 2: Run package-content audit against release-readiness dist artifacts**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run python scripts/audit_package_contents.py "$run_dir/release-readiness/dist" > "$run_dir/commands/20-package-audit.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/20-package-audit.status"'
```

Expected: `20-package-audit.status` contains `0`.

- [ ] **Step 3: Verify expected release-readiness artifacts exist**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; find "$run_dir/release-readiness/dist" -maxdepth 1 -type f | sort > "$run_dir/commands/20-release-dist-files.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/20-release-dist-files.status"'
```

Expected: `20-release-dist-files.status` contains `0`, and `20-release-dist-files.txt` lists a `localql-1.0.0` wheel and sdist if release-readiness passed.

---

### Task 4: Run Benchmark Proof And Unsupported-Claim Scan

**Files:**
- Create ignored: `$run_dir/benchmarks/**`
- Create ignored: `$run_dir/commands/30-*.txt`
- Create ignored: `$run_dir/commands/30-*.status`
- Create ignored: `$run_dir/claim-scan.txt`

**Interfaces:**
- Consumes: inventory root from Task 1.
- Produces: benchmark artifact paths and unsupported-claim raw scan output.

- [ ] **Step 1: Run benchmark proof**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run python scripts/benchmark_csvql.py --output-root "$run_dir/benchmarks" > "$run_dir/commands/30-benchmark.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/30-benchmark.status"'
```

Expected: `30-benchmark.status` contains `0`, and `30-benchmark.txt` lists `benchmark.json` plus `benchmark-summary.md` paths under the inventory directory.

- [ ] **Step 2: Run unsupported-claim scan**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; rg -n "v1-ready|v1 ready|production-safe|production ready|production-readiness|production readiness|sandbox-safe|sandbox safety|sandbox|large-file-proven|large file proven|large-file performance|large file performance" README.md CHANGELOG.md docs/development.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/benchmarking.md docs/failure-gallery.md docs/v1-manual-qa.md docs/tui-qol-qa.md docs/release-readiness.md docs/release-notes/v1.md > "$run_dir/claim-scan.txt" 2>&1; printf "%s\n" "$?" > "$run_dir/commands/30-claim-scan.status"'
```

Expected: `30-claim-scan.status` may contain `0` if guardrail/non-claim matches are found, or `1` if no matches are found. Neither status is automatically a failure. The matches must be classified in Task 5.

- [ ] **Step 3: Copy claim scan into command log index**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; cp "$run_dir/claim-scan.txt" "$run_dir/commands/30-claim-scan.txt"; printf "%s\n" "$?" > "$run_dir/commands/30-claim-scan-copy.status"'
```

Expected: `30-claim-scan-copy.status` contains `0`.

---

### Task 5: Review Authority Docs And Write Inventory Result

**Files:**
- Create ignored: `$run_dir/authority-review.md`
- Create ignored: `$run_dir/RESULT.md`

**Interfaces:**
- Consumes: command outputs and status files from Tasks 1 through 4.
- Produces: final human-readable proof inventory and conservative classification.

- [ ] **Step 1: Inspect command status files**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; for file in "$run_dir"/commands/*.status; do printf "%s: " "$file"; cat "$file"; done > "$run_dir/commands/status-index.txt"'
```

Expected: `status-index.txt` lists one status value per command.

- [ ] **Step 2: Review authority docs for agreement**

Read these files and classify any stale status language, unsupported release claims, or contradictions:

```text
README.md
CHANGELOG.md
docs/development.md
docs/PRODUCT_DIRECTION.md
docs/ROADMAP.md
docs/ARCHITECTURE.md
docs/json-contracts.md
docs/benchmarking.md
docs/failure-gallery.md
docs/v1-manual-qa.md
docs/tui-qol-qa.md
docs/release-readiness.md
docs/release-notes/v1.md
```

Expected: produce concrete notes for `authority-review.md`. Do not edit tracked docs in this lane.

- [ ] **Step 3: Write `authority-review.md`**

Use `apply_patch` to create the actual run's `$run_dir/authority-review.md` with these sections:

```markdown
# Authority Review

## Reviewed Files

## Agreement Summary

## Unsupported-Claim Scan Classification

## Stale Or Conflicting Language

## Manual-Proof Gaps

## TUI QoL Terminal-Matrix Gaps

## Follow-Up Candidates
```

Expected: every section contains concrete findings from this run. If there are no findings for a section, write `None found in this inventory.` for that section.

- [ ] **Step 4: Write `RESULT.md`**

Use `apply_patch` to create the actual run's `$run_dir/RESULT.md` with these sections:

```markdown
# Release Proof Inventory Result

## Repo Truth

## Automated Gate Outcomes

## Release-Readiness And Package Audit

## Benchmark Proof

## Unsupported-Claim Scan

## Authority-Doc Agreement

## Manual QA Status

## TUI QoL Terminal Matrix Status

## Final Classification

## Blockers

## Artifact Paths
```

Expected:

- `Repo Truth` names branch, commit, remote state, and tags-at-HEAD state.
- `Automated Gate Outcomes` reports pass/fail/not-run for Ruff format, Ruff check, mypy, and pytest.
- `Release-Readiness And Package Audit` reports pass/fail/not-run and paths.
- `Benchmark Proof` records benchmark JSON and Markdown summary paths if the benchmark passed.
- `Unsupported-Claim Scan` summarizes whether matches are guardrails/non-claims or blockers.
- `Authority-Doc Agreement` summarizes the review.
- `Manual QA Status` states that manual v1 QA is not run in this lane unless same-`HEAD` evidence is cited.
- `TUI QoL Terminal Matrix Status` states that the full terminal matrix is not run in this lane unless same-`HEAD` evidence is cited.
- `Final Classification` is `v1-hardening` or `blocked` unless all documented release-candidate eligibility prerequisites are satisfied.
- `Blockers` lists every missing or failed proof item.
- `Artifact Paths` lists command logs, release-readiness output, package audit output, benchmark output, `claim-scan.txt`, and `authority-review.md`.

- [ ] **Step 5: Verify result files exist**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; test -f "$run_dir/RESULT.md"; printf "%s\n" "$?" > "$run_dir/commands/40-result-exists.status"; test -f "$run_dir/authority-review.md"; printf "%s\n" "$?" > "$run_dir/commands/40-authority-review-exists.status"'
```

Expected: both `40-result-exists.status` and `40-authority-review-exists.status` contain `0`.

---

### Task 6: Final Verification And Handoff

**Files:**
- Verify ignored: `$run_dir/RESULT.md`
- Verify ignored: `$run_dir/authority-review.md`
- Verify ignored: `$run_dir/commands/status-index.txt`

**Interfaces:**
- Consumes: completed inventory artifacts from Task 5.
- Produces: final operator summary. No commit is expected.

- [ ] **Step 1: Verify tracked Git status remains clean**

Run:

```bash
git status --short --branch
```

Expected: output starts with `## main` and has no tracked file changes. Ignored `output/` artifacts should not appear.

- [ ] **Step 2: Verify generated evidence files**

Run:

```bash
/bin/zsh -c 'run_dir="output/release-proof-inventory-20260707-$(git rev-parse --short HEAD)"; find "$run_dir" -maxdepth 2 -type f | sort'
```

Expected: output includes `RESULT.md`, `authority-review.md`, `claim-scan.txt`, `commands/status-index.txt`, command output files, and command status files.

- [ ] **Step 3: Verify no release action occurred**

Run:

```bash
git tag --points-at HEAD
```

Expected: no output unless a tag already existed before the lane. Do not create a tag.

Run:

```bash
git remote -v
```

Expected: record current remote state. Do not configure a remote or push.

- [ ] **Step 4: Final handoff**

Report:

- inventory directory path
- final classification from `RESULT.md`
- automated proof pass/fail summary
- manual v1 QA status
- TUI QoL terminal matrix status
- blockers
- commands that failed or were not run
- statement that no tracked files changed during execution
- statement that no tag, push, upload, release, version change, or publish action occurred

Expected final wording must not claim `release-candidate eligible`, `release-candidate`, or `v1-stable` unless the `RESULT.md` proves every documented prerequisite passed on the same `HEAD`.
