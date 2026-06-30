# CSVQL v1 Authority Alignment And Release Readiness Design

Status: design approved in conversation; written spec review required before
implementation planning.

Date: 2026-06-30

## Purpose

This spec defines the next post-v0.7/v0.8 hardening slice toward v1.

CSVQL now has the main local workflow implemented: direct CSV querying,
project catalogs, saved SQL, export, inspect, sample, profile, check, doctor,
JSON contracts, benchmark and release-readiness scripts, example-project docs,
failure-gallery docs, and the small `CSVQLSession` Python API.

The next job is not to widen the product. The next job is to make the repo's
authority surfaces agree on what exists, what remains before v1, and what proof
is required before claiming `release-candidate` or `v1-stable`.

This slice strengthens the CSVQL wedge:

- local-first CSV querying through DuckDB
- deterministic CLI and JSON behavior where the repo already owns it
- honest documentation of trusted local SQL and non-sandboxed execution
- release proof that is explicit and repeatable
- product scope discipline before v1

## Product Contract

This is docs and authority-alignment work. It does not change runtime behavior.

Runtime truth wins over docs, plans, and generated notes. If implementation
finds a contradiction between docs and the current CLI or Python API, the
implementation should either:

1. update docs to match current intentional runtime behavior, or
2. stop and call out a separate behavior-fix decision when runtime behavior
   appears wrong.

Behavior changes, JSON shape changes, config schema changes, exit-code redesign,
and release automation should not be hidden inside this slice.

## Scope Boundary

Included:

- reconcile `AGENTS.md` as the repo-local Codex operating authority
- reconcile `README.md` as the user-facing current-status and workflow surface
- reconcile `docs/PRODUCT_DIRECTION.md` as the product strategy and scope guard
- reconcile `docs/ROADMAP.md` as the implemented, remaining, and future-work map
- reconcile `docs/ARCHITECTURE.md` as the current runtime architecture summary
- reconcile `docs/json-contracts.md` as the current JSON-contract authority
- reconcile `docs/release-readiness.md` as the release-candidate and v1-stable
  proof checklist
- preserve the already completed failure-gallery work as implemented
- keep any existing dirty authority edits only where they are correct and within
  this approved slice
- add no more release machinery than the current lane needs

Excluded:

- runtime source changes
- new CLI commands
- JSON output normalization
- exit-code changes
- config schema changes
- version bump
- dependency or lockfile changes
- publishing automation
- changelog expansion beyond a minimal release-note stub, unless implementation
  proves the stub is needed to keep release-readiness honest
- safe mode or sandbox behavior
- hidden cache or materialization
- web app, cloud connector, notebook, dataframe-first, AI, or plugin platform
- broad Codex hooks, agents, generated contract framework, or new authority
  surfaces

## Authority Model

The implementation should align the repo authorities in this order:

1. `AGENTS.md`: operating lane and hard boundaries for Codex work.
2. `README.md`: user-facing current status and everyday workflow.
3. `docs/PRODUCT_DIRECTION.md`: product strategy, north star, and scope
   guardrails.
4. `docs/ROADMAP.md`: what is implemented, what remains before v1, and what is
   future work.
5. `docs/ARCHITECTURE.md`: current runtime shape and design boundaries.
6. `docs/json-contracts.md`: current JSON truth plus explicit unresolved v1
   contract decisions.
7. `docs/release-readiness.md`: proof path for release-candidate and v1-stable
   labels.

These files should not repeat the same prose. Each authority has a job:

- `AGENTS.md` governs how Codex should work in this repo.
- `README.md` explains what a user can do now.
- `docs/PRODUCT_DIRECTION.md` explains why v1 hardening should not widen scope.
- `docs/ROADMAP.md` distinguishes implemented, remaining, and future work.
- `docs/ARCHITECTURE.md` explains how the CLI and package fit together today.
- `docs/json-contracts.md` prevents accidental contract drift.
- `docs/release-readiness.md` defines the proof checklist.

## Required Corrections

The implementation should make these corrections where the current docs are
stale or ambiguous.

### Current Lane

Replace stale language that presents v0.1 or v0.7 as the current lane.

The current lane is post-v0.7/v0.8 hardening toward v1. The docs should state
that the core local workflow is implemented and that remaining work is
authority alignment, release-readiness proof, contract-stabilization decisions,
benchmark proof refresh, changelog or release-note discipline, and final full
gate verification.

### Failure Gallery

Failure-gallery work is complete in the current repo state. The authority docs
should treat it as implemented, not as a missing pre-v1 item.

### JSON Contracts

`docs/json-contracts.md` should clearly separate current runtime truth from
future normalized-contract ideas.

The current v0.8 JSON shapes are the active runtime contract unless a separate,
explicit compatibility decision changes them. A normalized v1 envelope may
remain documented as a possible future direction, but it must not read as
implemented behavior or as work included in this slice.

### Release Readiness

`docs/release-readiness.md` should no longer read as a v0.7-only proof note.

It should describe the real v1 hardening proof path:

- version consistency check
- build and isolated wheel install through the existing release-readiness script
- full local gate through `uv run`
- benchmark proof or a documented local benchmark artifact
- docs and roadmap alignment
- explicit no-publish boundary unless a separate release command is approved
- label rules for `v1-hardening`, `release-candidate`, and `v1-stable`

### Safety And Performance Claims

Docs must not claim sandbox safety, security isolation, production readiness, or
large-file performance beyond proof.

The docs should continue to state that user-authored SQL is trusted local SQL
executed by DuckDB and that CSVQL does not restrict DuckDB's filesystem
capabilities unless a separate safe-mode feature is designed, implemented, and
tested.

## File Boundary

Expected implementation files:

- `AGENTS.md`
- `README.md`
- `docs/PRODUCT_DIRECTION.md`
- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/json-contracts.md`
- `docs/release-readiness.md`

Expected planning artifacts:

- `docs/superpowers/specs/2026-06-30-csvql-v1-authority-release-readiness-design.md`
- `docs/superpowers/plans/2026-06-30-csvql-v1-authority-release-readiness.md`

No intended runtime-source files:

- `src/csvql/*.py`
- tests, unless implementation discovers a specific docs assertion that needs a
  lightweight proof test
- `pyproject.toml`
- `uv.lock`
- example data
- benchmark output artifacts

If implementation discovers a runtime bug or a missing test that materially
blocks honest docs, stop and make that a separate decision instead of widening
this slice silently.

## Implementation Shape

The implementation plan should be docs-first and reviewable in small batches.

Recommended task order:

1. audit authority docs for stale lane language and unsupported claims
2. reconcile existing dirty authority edits in `AGENTS.md`, `README.md`,
   `docs/PRODUCT_DIRECTION.md`, and `docs/ROADMAP.md`
3. update `docs/ARCHITECTURE.md` to remove stale v0.1 wording and align current
   runtime boundaries
4. update `docs/json-contracts.md` to make current v0.8 shapes the active truth
   and normalized v1 ideas explicitly future-facing
5. update `docs/release-readiness.md` into a v1 hardening proof checklist
6. run docs-focused stale-claim searches and diff review
7. run the relevant verification gate
8. stage and commit only intended changes

The plan should preserve user work. The working tree already contains dirty
authority-doc edits, so implementation must review and stage intentionally
rather than assuming every dirty line belongs in the commit.

## Verification Target

Required checks for the implementation plan:

- `git diff --check`
- targeted stale-language searches for:
  - `v0.1`
  - `v0.7`
  - `v1-ready`
  - `sandbox`
  - `production`
  - `large-file`
- focused review of every changed authority doc

Run the full local gate when implementation reaches the final authority
alignment state:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest
```

If any full-gate command cannot run, the handoff must say which command was
skipped or failed and what remains unverified.

## Risks And Controls

Risk: the docs overclaim v1 readiness.

Control:

- use `v1-hardening` for the current lane
- reserve `release-candidate` for a state with refreshed release proof
- reserve `v1-stable` for the documented full proof state

Risk: future JSON ideas are mistaken for current runtime behavior.

Control:

- label current v0.8 JSON shapes as runtime truth
- label normalized v1 contract shape as a separate decision, not this slice

Risk: implementation accidentally commits unrelated dirty work.

Control:

- inspect `git status --short --branch`
- review diffs file by file
- stage only the intended docs and Superpowers artifacts

Risk: release-readiness turns into ceremony instead of proof.

Control:

- update the checklist and current commands only
- do not add new automation unless a repeated failure proves the need

Risk: `AGENTS.md` becomes stale or too broad as repo authority.

Control:

- keep it focused on operating lane, boundaries, tools, and proof labels
- keep product explanation in the product and roadmap docs

## Success Criteria

This slice is successful when:

- the authority docs agree that CSVQL is in post-v0.7/v0.8 hardening toward v1
- stale v0.1 or v0.7 current-lane wording is removed or clearly historical
- failure-gallery work is listed as implemented
- remaining pre-v1 work is explicit and narrow
- release-readiness docs define what proof is required before
  `release-candidate` and `v1-stable`
- JSON-contract docs distinguish current runtime truth from future normalized
  ideas
- docs preserve the trusted-local-SQL and non-sandboxed security posture
- docs make no unsupported production, sandbox, or large-file claims
- no runtime behavior changes are introduced
- verification results are reported plainly

It is not successful if it turns v1 hardening into a new product surface,
commits unrelated dirty work, or uses release language to claim proof that has
not been refreshed.
