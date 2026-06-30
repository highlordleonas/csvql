# CSVQL v1 Authority Alignment And Release Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align CSVQL's repo authority docs and release-readiness checklist for post-v0.7/v0.8 hardening toward v1 without runtime behavior changes.

**Architecture:** This is a docs-only authority reconciliation. Existing source and tests remain implementation truth; docs are updated to reflect the current runtime, separate current contracts from future decisions, and define the proof path for `release-candidate` and `v1-stable` labels. Verification uses diff review, stale-claim searches, and the standard `uv run` gates.

**Tech Stack:** Markdown documentation, Git diff review, ripgrep, `uv`, Ruff, mypy, pytest, existing CSVQL release-readiness and benchmark scripts as documented proof paths.

---

## Direction Check

- Target lane: post-v0.7/v0.8 hardening toward v1.
- Wedge strengthened: authority alignment, deterministic contracts, honest release-readiness proof, trusted local workflow.
- Scope rejected: runtime behavior changes, new commands, JSON normalization, config schema changes, version bump, dependency changes, release publishing automation, safe mode, cache/materialization, cloud, web, notebook, dataframe-first, AI, or plugin scope.
- Contracts touched: documentation of current CLI surface, JSON contract posture, release-readiness proof labels, security/performance claim boundaries.
- Verification target: exact doc diffs, stale-language search, `git diff --check`, and the standard `uv run` gate.

## Pre-Execution State

At plan-writing time, the working tree already has dirty authority-doc edits:

- `AGENTS.md`
- `README.md`
- `docs/PRODUCT_DIRECTION.md`
- `docs/ROADMAP.md`

Treat those edits as candidate input. Do not revert them. Do not assume every
dirty line is correct. Review and stage intentionally.

## File Structure

- Modify `AGENTS.md`: repo-local operating lane and hard boundaries for Codex.
- Modify `README.md`: user-facing current status and docs links.
- Modify `docs/PRODUCT_DIRECTION.md`: product strategy and v1-hardening scope guard.
- Modify `docs/ROADMAP.md`: implemented, remaining-before-v1, and post-v1 map.
- Modify `docs/ARCHITECTURE.md`: current runtime architecture and deferred decisions.
- Modify `docs/json-contracts.md`: current v0.8 JSON contract authority plus open v1 decision.
- Modify `docs/release-readiness.md`: v1-hardening proof checklist and no-publish boundary.
- Keep `docs/superpowers/specs/2026-06-30-csvql-v1-authority-release-readiness-design.md`: approved design authority.
- Keep this plan at `docs/superpowers/plans/2026-06-30-csvql-v1-authority-release-readiness.md`.
- Do not modify `src/csvql/*.py`, tests, `pyproject.toml`, `uv.lock`, example data, generated benchmark artifacts, or release output artifacts in this slice.

## Task 1: Baseline Authority Audit

**Files:**
- Read: `AGENTS.md`
- Read: `README.md`
- Read: `docs/PRODUCT_DIRECTION.md`
- Read: `docs/ROADMAP.md`
- Read: `docs/ARCHITECTURE.md`
- Read: `docs/json-contracts.md`
- Read: `docs/release-readiness.md`
- Read: `docs/superpowers/specs/2026-06-30-csvql-v1-authority-release-readiness-design.md`

- [ ] **Step 1: Confirm branch and dirty state**

Run:

```bash
git status --short --branch
```

Expected: branch is `main`; dirty files include the four pre-existing authority docs and this plan file if it has not already been committed.

- [ ] **Step 2: Review existing authority-doc dirty diff**

Run:

```bash
git diff -- AGENTS.md README.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md
```

Expected: the diff moves stale v0.1/v0.7 current-lane language toward post-v0.7/v0.8 hardening. Mark any line that still treats failure-gallery documentation as remaining work for correction in Task 2.

- [ ] **Step 3: Search authority docs for stale or risky claims**

Run:

```bash
rg -n "v0\.1|v0\.7|v1-ready|production-safe|sandbox-safe|large-file-proven|large-file performance|large file|safe sandbox|production readiness" AGENTS.md README.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/release-readiness.md
```

Expected: historical roadmap headings and explicit "do not claim" guardrails may appear. No hit should present v0.1 or v0.7 as the current lane, and no hit should claim production, sandbox, or large-file proof.

- [ ] **Step 4: Confirm no runtime work is necessary before editing docs**

Run:

```bash
git diff --stat
```

Expected: only documentation and planning files are dirty. If a runtime file is dirty, stop and ask the main thread whether that runtime change is user work, because runtime changes are outside this slice.

## Task 2: Reconcile Current-Lane Authority Docs

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/PRODUCT_DIRECTION.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Update `AGENTS.md` current lane wording**

In `AGENTS.md`, keep the existing `## Current Release Lane` section, but make the remaining-lane paragraph say this:

```markdown
Current work should harden and reconcile the product for v1, not widen it. The
remaining lane is authority alignment, release workflow and changelog work,
contract stabilization decisions, benchmark and release-readiness proof
refreshes, and final full-gate verification. Failure-gallery documentation is
implemented and should be kept aligned with runtime behavior.
```

Expected: `AGENTS.md` no longer lists failure-gallery documentation as remaining work.

- [ ] **Step 2: Update `README.md` status paragraph**

Replace the current `## Status` opening paragraph with this content:

```markdown
This repository has the core local workflow implemented for local CLI use:
query, inspect/sample, project catalogs, saved SQL, export, profile, configured
checks, doctor, benchmark and release-readiness proof scripts, JSON contract
documentation, the failure gallery, the polished example project, and the small
project-backed Python API. The current lane is v1 hardening: authority
alignment, release workflow and changelog work, contract stabilization,
benchmark and release-readiness proof refresh, and final full-gate proof.
```

Expected: README presents the current product plainly and does not imply failure-gallery documentation is still pending.

- [ ] **Step 3: Update `docs/PRODUCT_DIRECTION.md` current-lane bullets**

In `docs/PRODUCT_DIRECTION.md`, keep the post-v0.7/v0.8 lane, but replace the current work bullets under `Current work should not add broad new product surface...` with:

```markdown
- align `AGENTS.md`, README, roadmap, architecture, product direction, release
  readiness, and JSON-contract docs with the runtime surface
- keep the completed failure gallery aligned with deterministic runtime behavior
- decide whether v1 keeps the current v0.8 JSON shapes for compatibility or
  introduces the documented normalized envelope with migration notes
- refresh benchmark and release-readiness proof before release claims
- add release workflow and changelog material without pretending publishing is
  already automated
- run the full local gate before any `release-candidate` or `v1-stable` claim
```

Expected: product direction treats the failure gallery as complete and points the near-term work at authority/release hardening.

- [ ] **Step 4: Update `docs/PRODUCT_DIRECTION.md` near-term slice list**

In the `Near-Term Direction` section, replace the "That slice should include" list with:

```markdown
- authority repair for stale v0.1-era instructions and docs
- release-readiness checklist work that builds on `docs/release-readiness.md`
- changelog or release-note preparation for the implemented surfaces
- explicit contract decisions for CLI JSON, exit codes, config schema, and the
  small Python API
- a proof refresh using the standard `uv run` gates, release-readiness script,
  and benchmark workflow before benchmark-backed or performance claims
```

Expected: product direction no longer lists the failure gallery as a future near-term deliverable.

- [ ] **Step 5: Update `docs/ROADMAP.md` v0.8 and v1 sections**

Ensure `docs/ROADMAP.md` has:

```markdown
Remaining before v1:

- final documentation pass that keeps README, architecture, JSON contracts,
  release readiness, roadmap, and product direction aligned
- explicit contract-stabilization decision for current JSON shapes, exit-code
  policy, config schema, and the small Python API
- refreshed benchmark and release-readiness proof before release claims
- release workflow and changelog or release-note material
- full local gate passing through `uv run`
```

Also ensure `v1.0.0 - Stable Release` includes:

```markdown
- refreshed benchmark report or documented local benchmark artifact
- release workflow
- changelog or release notes
- full local gate passing through `uv run`
```

Expected: roadmap distinguishes completed v0.8 work, remaining pre-v1 hardening, and v1 stable requirements.

- [ ] **Step 6: Review the current-lane doc diff**

Run:

```bash
git diff -- AGENTS.md README.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md
```

Expected: all changes are authority alignment only. No source, dependency, config, or release-output file is touched.

## Task 3: Reconcile Architecture Doc

**Files:**
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Remove stale v0.1 runtime wording**

In `docs/ARCHITECTURE.md`, replace this bullet:

```markdown
- DuckDB runs in memory for v0.1.
```

with:

```markdown
- DuckDB runs in memory for current CLI and Python API execution.
```

Expected: architecture no longer implies the runtime architecture is still v0.1.

- [ ] **Step 2: Replace stale deferred decisions**

Replace the `## Deferred Decisions` bullet list with:

```markdown
- Whether v1 keeps the current v0.8 JSON shapes as stable or introduces a
  documented migration path.
- Whether persistent DuckDB cache is worth adding after v1 usage evidence.
- Whether named parameters belong in a post-v1 workflow.
- Whether safe mode belongs later; it requires a separate ADR, threat model,
  implementation plan, and tests.
- Whether additional export formats deserve post-v1 scope.
```

Expected: deferred decisions match the current v1-hardening lane and do not imply unfinished v0.1 architecture work.

- [ ] **Step 3: Search architecture for stale current-lane claims**

Run:

```bash
rg -n "v0\.1|v0\.7|before v1|v1-ready|safe sandbox|production readiness|large-file" docs/ARCHITECTURE.md
```

Expected: no hits for stale current-lane claims. If `safe mode` appears, it must remain a deferred decision with the ADR/threat-model/testing boundary.

## Task 4: Reconcile JSON Contract Doc

**Files:**
- Modify: `docs/json-contracts.md`

- [ ] **Step 1: Add an explicit open v1 decision note**

After the opening scope paragraph in `docs/json-contracts.md`, add:

```markdown
Open v1 decision: the current v0.8 JSON shapes remain the active runtime
contract until a separate compatibility decision changes them. A normalized
envelope is not implemented in the current runtime and must not be described as
current behavior.
```

Expected: automation readers can tell what is true today and what is still a decision.

- [ ] **Step 2: Rename the future normalized-contract heading**

Replace:

```markdown
## Ideal v1 Normalized Contract
```

with:

```markdown
## Possible Future Normalized Contract
```

Expected: the heading no longer reads like a committed v1 runtime requirement.

- [ ] **Step 3: Rename the migration delta heading**

Replace:

```markdown
## Delta From Current v0.8 To Ideal v1
```

with:

```markdown
## Potential Migration Delta From Current v0.8
```

Expected: the delta section reads as future migration guidance, not current implementation scope.

- [ ] **Step 4: Search JSON contracts for ambiguous future/current wording**

Run:

```bash
rg -n "Ideal v1|current runtime envelope|not the current runtime|normalized|Open v1 decision|Possible Future" docs/json-contracts.md
```

Expected: there is no `Ideal v1` hit. Future normalized-contract language is explicitly not implemented.

## Task 5: Rewrite Release-Readiness Checklist

**Files:**
- Modify: `docs/release-readiness.md`

- [ ] **Step 1: Replace the full release-readiness doc**

Replace the current contents of `docs/release-readiness.md` with:

````markdown
# Release Readiness

CSVQL is in post-v0.7/v0.8 hardening toward v1. This document defines the
local proof path for `release-candidate` and `v1-stable` labels. It does not
publish packages, create tags, upload artifacts, or claim a release by itself.

## Release-Readiness Script

Run:

```bash
uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

This workflow verifies:

- `pyproject.toml`, `src/csvql/__init__.py`, and `csvql --version` agree
- `uv build --sdist --wheel` succeeds
- an isolated wheel install can run `csvql --version`
- the installed wheel can run a tiny `inspect` command

## Full Local Gate

Before any `release-candidate` or `v1-stable` claim, run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

## Benchmark Proof

Refresh or explicitly cite local benchmark evidence before making performance
claims:

```bash
uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Benchmark artifacts are local evidence only. They do not prove large-file
performance beyond the recorded datasets.

## Label Rules

Use `v1-hardening` for the current lane while authority docs, release notes,
contract decisions, benchmark proof, and final gates are still being reconciled.

Use `release-candidate` only after:

- README, roadmap, product direction, architecture, JSON contracts, and release
  readiness agree with the runtime surface
- the release-readiness script passes on the candidate state
- benchmark proof is refreshed or a current local benchmark artifact is cited
- the full local gate passes
- changelog or release-note material exists for the implemented surfaces
- docs make no unsupported sandbox, security-isolation, production-readiness,
  or large-file performance claims

Use `v1-stable` only after the release-candidate proof remains valid and the
final release action is explicitly approved.

## No-Publish Boundary

The commands in this document are local verification commands. They do not
publish to PyPI, push Git tags, create GitHub releases, upload artifacts, or
mutate external systems.
````

Expected: release readiness now describes the v1 proof path and does not claim fresh proof unless the proof commands are actually run.

- [ ] **Step 2: Confirm release-readiness command names match repo scripts**

Run:

```bash
rg -n "verify_release_readiness|benchmark_csvql|ruff format|ruff check|mypy src|pytest" docs/release-readiness.md scripts pyproject.toml Makefile
```

Expected: `scripts/verify_release_readiness.py` and `scripts/benchmark_csvql.py` exist; the `uv run` gate names match README and `AGENTS.md`.

## Task 6: Verification And Claim Audit

**Files:**
- Read: all modified docs

- [ ] **Step 1: Run whitespace diff check**

Run:

```bash
git diff --check
```

Expected: no output and exit code `0`.

- [ ] **Step 2: Run stale-claim search across authority docs**

Run:

```bash
rg -n "v0\.1|v0\.7|v1-ready|production-safe|sandbox-safe|large-file-proven|large-file performance|safe sandbox|production readiness" AGENTS.md README.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/release-readiness.md
```

Expected allowed hits:

- historical version headings or historical release names in `docs/ROADMAP.md`
- guardrails that say not to claim sandbox, production, or large-file proof
- `v0.7/v0.8` only where naming the current hardening lane

Expected disallowed hits:

- `v1-ready`
- any current-lane statement saying v0.1 or v0.7 is active
- any positive production-safe, sandbox-safe, or large-file-proven claim

- [ ] **Step 3: Run docs link and file existence smoke check**

Run:

```bash
python3 - <<'PY'
from pathlib import Path

required = [
    Path("docs/ARCHITECTURE.md"),
    Path("docs/benchmarking.md"),
    Path("docs/json-contracts.md"),
    Path("docs/failure-gallery.md"),
    Path("docs/PRODUCT_DIRECTION.md"),
    Path("docs/release-readiness.md"),
    Path("docs/ROADMAP.md"),
    Path("docs/CODEX_CAPABILITY_REVIEW.md"),
    Path("docs/superpowers/specs/2026-06-30-csvql-v1-authority-release-readiness-design.md"),
    Path("docs/superpowers/plans/2026-06-30-csvql-v1-authority-release-readiness.md"),
]

missing = [str(path) for path in required if not path.exists()]
if missing:
    raise SystemExit("missing docs: " + ", ".join(missing))
print("all required docs exist")
PY
```

Expected output:

```text
all required docs exist
```

- [ ] **Step 4: Run full local gate**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest
```

Expected:

- Ruff format reports all files formatted.
- Ruff check reports all checks passed.
- mypy reports success for `src`.
- pytest passes.

Do not run the benchmark or release-readiness script in this slice unless the main thread explicitly chooses proof refresh. If either command is run, report the exact command and result, and do not claim `release-candidate` unless all release-candidate label rules are satisfied.

## Task 7: Final Diff Review And Commit

**Files:**
- Stage: `AGENTS.md`
- Stage: `README.md`
- Stage: `docs/PRODUCT_DIRECTION.md`
- Stage: `docs/ROADMAP.md`
- Stage: `docs/ARCHITECTURE.md`
- Stage: `docs/json-contracts.md`
- Stage: `docs/release-readiness.md`
- Stage: `docs/superpowers/plans/2026-06-30-csvql-v1-authority-release-readiness.md`

- [ ] **Step 1: Review final status**

Run:

```bash
git status --short --branch
```

Expected: only the intended authority docs and this plan are dirty. If additional files are dirty, classify them as user work or stop before staging.

- [ ] **Step 2: Review final diff stat**

Run:

```bash
git diff --stat
```

Expected: changes are limited to docs and this plan.

- [ ] **Step 3: Review final docs diff**

Run:

```bash
git diff -- AGENTS.md README.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/release-readiness.md docs/superpowers/plans/2026-06-30-csvql-v1-authority-release-readiness.md
```

Expected: diff matches this plan and contains no runtime source changes.

- [ ] **Step 4: Stage only intended files**

Run:

```bash
git add AGENTS.md README.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/release-readiness.md docs/superpowers/plans/2026-06-30-csvql-v1-authority-release-readiness.md
```

Expected: only the listed files are staged.

- [ ] **Step 5: Review staged diff**

Run:

```bash
git diff --cached --stat
git diff --cached --check
```

Expected: staged diff is docs-only and whitespace check passes.

- [ ] **Step 6: Commit authority alignment**

Run:

```bash
git commit -m "docs: align v1 authority and release readiness"
```

Expected: one commit containing only the intended authority docs and plan.

- [ ] **Step 7: Report final state**

Run:

```bash
git status --short --branch
git show --stat --oneline HEAD
```

Expected: no unintended staged changes remain. The handoff lists skills used, verification commands and results, skipped proof-refresh commands, changed files, and remaining risk.
