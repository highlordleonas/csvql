# CSVQL v1 Proof Refresh And Gap Closure Design

Status: design approved in conversation; written spec review required before
implementation planning.

Date: 2026-06-30

## Purpose

This spec defines the next post-v0.7/v0.8 hardening slice toward v1.

The previous authority-alignment slice made the repo docs agree that CSVQL is
still in `v1-hardening`, not yet `release-candidate` or `v1-stable`. This slice
tests that claim against the repo's real proof workflows.

The job is to run and inspect the existing local evidence paths, fix only direct
proof blockers, and update tracked docs only where the fresh proof changes what
the repo can honestly say.

This slice strengthens the CSVQL wedge:

- local-first CSV workflows through DuckDB
- deterministic CLI and JSON behavior where CSVQL owns the contract
- release evidence that is local, repeatable, and bounded
- honest performance language based on actual benchmark artifacts
- no new product surface before v1 stability

## Product Contract

This is a proof-refresh and release-candidate assessment slice.

It may run existing proof workflows and update documentation. It may make narrow
code or test fixes only when the proof workflow itself is broken or when a
runtime defect directly prevents honest release-readiness evaluation.

It must not silently change public behavior, normalize JSON contracts, redesign
exit codes, widen the config schema, bump versions, publish packages, create
tags, or add release automation.

If implementation discovers that CSVQL is not eligible for
`release-candidate`, the correct result is a clear gap list, not a forced
release claim.

## Scope Boundary

Included:

- baseline repo truth: branch, `HEAD`, status, and intended write set
- full local gate through the repo-defined `uv run` commands
- release-readiness proof through `scripts/verify_release_readiness.py`
- benchmark proof through `scripts/benchmark_csvql.py`
- focused inspection of generated release-readiness and benchmark artifacts
- stale or unsupported claim scans across authority docs
- documentation updates when fresh proof changes current truth
- narrow proof-workflow fixes when a script fails for a repo-owned reason
- final release-candidate eligibility assessment

Excluded:

- PyPI publish
- Git tags or GitHub releases
- version bump
- changelog expansion beyond what is needed to record release-candidate gaps
- broad release automation
- new CLI commands
- JSON envelope migration
- exit-code redesign
- config schema changes
- safe mode or sandbox behavior
- hidden cache or materialization
- web, cloud, notebook, dataframe-first, AI, or plugin scope
- committing generated benchmark or build outputs by default

## Current Proof Surfaces

The implementation should use the current repo surfaces rather than inventing a
new workflow:

- `docs/release-readiness.md`: label rules and release-proof checklist
- `docs/benchmarking.md`: benchmark matrix and claims boundary
- `scripts/verify_release_readiness.py`: release-readiness entry point
- `src/csvql/release_readiness.py`: version, build, wheel install, and smoke
  behavior
- `scripts/benchmark_csvql.py`: benchmark entry point
- `src/csvql/benchmark_runner.py`: approved benchmark suite
- `src/csvql/benchmarking.py`: benchmark artifact and Markdown renderer
- `docs/PRODUCT_DIRECTION.md`: scope guardrails and DuckDB/security posture
- `docs/ROADMAP.md`: remaining pre-v1 work
- `AGENTS.md`: repo-local v1-stable definition and proof language

Generated output under `output/` is ignored by git. The implementation should
inspect those outputs and summarize the relevant evidence in the handoff or
tracked docs. It should not commit generated `output/benchmarks`,
`output/release-readiness`, wheels, sdists, virtualenvs, or scratch transcripts
unless a separate tracked-artifact decision is made.

## Proof Workflow

The implementation plan should run the proof in this order.

### 1. Baseline State

Capture:

- `pwd`
- `git status --short --branch`
- `git show --stat --oneline HEAD`
- intended write set before edits

If the tree is dirty, classify each dirty file before running proof. Preserve
user work and stage only intentional changes.

### 2. Full Local Gate

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest
```

These commands prove static formatting, lint, typing, and test health for the
current repo state. They do not prove release packaging or benchmark behavior.

### 3. Release-Readiness Proof

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

The proof must show:

- `pyproject.toml`, `src/csvql/__init__.py`, and `csvql --version` agree
- source distribution and wheel build successfully
- isolated wheel install succeeds
- installed `csvql --version` runs
- installed `csvql inspect <smoke_csv> --output json` runs

If it fails, diagnose the exact failing step. Fix only repo-owned proof blockers
inside the current release-readiness path.

### 4. Benchmark Proof

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Inspect the printed artifact and summary paths. Confirm the artifact records:

- CSVQL version
- DuckDB version
- Python version
- platform
- generation timestamp
- dataset tiers
- measured benchmark cases
- local-evidence-only notes

Benchmark success supports only `benchmark-backed` language for the recorded
datasets. It does not prove large-file performance, production readiness, or
general runtime guarantees.

### 5. Claim Audit

Search authority docs for stale or unsupported language:

- `v1-ready`
- `release-candidate`
- `v1-stable`
- `production-safe`
- `production readiness`
- `sandbox-safe`
- `sandbox`
- `large-file-proven`
- `large-file performance`
- `safe mode`

Allowed hits include historical roadmap sections, negative guardrails, and
explicit label rules. Unsupported positive claims must be removed or rewritten.

### 6. Gap Assessment

Compare fresh proof against `docs/release-readiness.md` and `AGENTS.md`.

The final assessment should say one of:

- still `v1-hardening`, with specific remaining blockers
- eligible for `release-candidate`, with proof commands and artifact paths
- blocked, with the exact command, failing step, and owner boundary

Do not claim `v1-stable` in this slice unless every repo-defined `v1-stable`
condition is already satisfied and the user explicitly approves final release
action. That is unlikely because contract stabilization and release-note work
remain listed pre-v1 concerns.

## File Boundary

Expected tracked files:

- `docs/superpowers/specs/2026-06-30-csvql-v1-proof-refresh-gap-closure-design.md`
- `docs/superpowers/plans/2026-06-30-csvql-v1-proof-refresh-gap-closure.md`
- `docs/release-readiness.md`, only if proof results require clearer status or
  gap language
- `docs/ROADMAP.md`, only if remaining pre-v1 status changes
- `docs/benchmarking.md`, only if benchmark proof exposes stale or incomplete
  benchmark instructions
- `README.md`, only if user-facing release/readiness language becomes stale
- source or tests only for narrow proof-workflow fixes discovered by the proof

Expected ignored outputs:

- `output/benchmarks/**`
- `output/release-readiness/**`
- build outputs under the release-readiness work directory
- temporary smoke virtualenvs

If implementation needs to modify files outside this boundary, it must stop and
state why the boundary is no longer sufficient.

## Implementation Shape

The implementation plan should be evidence-first and reversible.

Recommended task order:

1. capture baseline repo truth and planned write set
2. run full local gate
3. run release-readiness proof
4. run benchmark proof
5. inspect generated proof artifacts and record evidence
6. run claim-audit searches
7. update docs only if proof changes current truth
8. rerun affected checks after any edit
9. classify final status and commit only intended tracked files

If a proof command fails before any edits, prefer diagnosing that failure before
changing docs. Documentation should describe the observed state, not mask it.

## Verification Target

The executable plan must include these checks:

```bash
git diff --check
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

If a command cannot run because of sandboxing or network restrictions, the
implementation must report the command, the observed failure, whether escalation
was requested, and what remains unverified.

## Risks And Controls

Risk: benchmark output is treated as a broad performance claim.

Control:

- keep benchmark language scoped to recorded datasets
- preserve local-evidence-only notes
- reject large-file or production-readiness claims without separate proof

Risk: release-readiness success is mistaken for `v1-stable`.

Control:

- compare proof against every `release-candidate` and `v1-stable` condition
- keep unresolved contract, changelog, or release-action gaps explicit

Risk: proof scripts fail because of environment or dependency access.

Control:

- capture the exact failing command and stderr
- request escalation only for necessary network or sandbox failures
- distinguish environment failure from product failure

Risk: generated outputs pollute the commit.

Control:

- rely on `.gitignore` for `output/`
- inspect `git status --short` before staging
- stage only tracked source/docs/plan/spec changes

Risk: the slice turns into new release automation.

Control:

- use existing scripts
- do not add publish, tag, upload, or release commands
- defer broader workflow work to a separate approved spec

## Success Criteria

This slice is successful when:

- the full local gate has fresh pass/fail evidence
- release-readiness proof has fresh pass/fail evidence
- benchmark proof has fresh pass/fail evidence
- generated proof artifacts were inspected enough to support the final status
- unsupported readiness, sandbox, production, or large-file claims are absent
  or explicitly negative/historical
- tracked docs reflect the observed proof state
- generated outputs are not accidentally committed
- the final handoff states whether CSVQL remains `v1-hardening`, is eligible
  for `release-candidate`, or is blocked

It is not successful if it claims v1 stability from partial proof, hides a
failed command, commits generated artifacts by accident, or expands CSVQL beyond
the approved local-first v1 hardening lane.
