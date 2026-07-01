# CSVQL v1 Release Workflow Design

Status: design approved in conversation; written spec review required before
implementation planning.

Date: 2026-06-30

## Purpose

This spec defines the next v1-hardening slice for CSVQL: a local-only release
workflow and release-note package.

CSVQL has already implemented the core local workflow: query, inspect, sample,
profile, project catalogs, saved SQL, export, configured checks, doctor, JSON
contract documentation, failure-gallery documentation, benchmark and
release-readiness scripts, a polished example project, and a small
project-backed Python API.

The remaining pre-candidate gap is release discipline. The repo needs durable
release notes, a changelog surface, and an exact local workflow that explains
how to decide whether the current state is still `v1-hardening`, is
`release-candidate eligible`, or is blocked.

This slice strengthens the CSVQL wedge:

- repeatable local CSV projects
- deterministic CLI, JSON, and Python API contracts
- evidence-backed release readiness
- honest local proof language
- clear separation between release eligibility and release publication

## Approved Direction

Use the release-package approach:

- add a root `CHANGELOG.md` as the durable public change-history surface
- add `docs/release-notes/v1.md` as the detailed v1 release-note and candidate
  checklist surface
- update `docs/release-readiness.md` so the exact local candidate workflow is
  explicit
- add small README or roadmap links only if needed for discoverability and
  consistency
- keep the current status label as `v1-hardening` until the final candidate
  proof actually passes
- stop before publish, tag, GitHub release, PyPI upload, version bump, or any
  external mutation

The release-readiness script and benchmark script remain proof tools. Passing
them is evidence for candidate eligibility, not a release action.

## Scope Boundary

Included:

- `CHANGELOG.md`
- `docs/release-notes/v1.md`
- local release workflow updates in `docs/release-readiness.md`
- small link updates in README or roadmap if needed
- claim scans for false `release-candidate`, `v1-stable`, sandbox,
  production-readiness, or large-file performance language
- docs-only verification for the release package

Excluded:

- PyPI publishing
- Git tags
- GitHub releases
- version bump
- package upload or artifact upload
- new release automation
- new CLI commands
- new scripts or Make targets
- JSON contract changes
- exit-code redesign
- config schema changes
- Python API changes
- safe mode or sandbox behavior
- cache or materialization
- web, cloud, notebook, dataframe-first, AI, or plugin scope
- claiming `release-candidate` or `v1-stable` before fresh proof

## Release Workflow Shape

The workflow should be documented as a local sequence, not a new automation
layer.

Candidate evaluation starts from clean `main` and uses current repo authority:

- `AGENTS.md`
- `README.md`
- `docs/PRODUCT_DIRECTION.md`
- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/json-contracts.md`
- `docs/release-readiness.md`
- `CHANGELOG.md`
- `docs/release-notes/v1.md`
- source and tests as implementation truth

The documented candidate flow should be:

1. Confirm clean `main`, current `HEAD`, and intended write set.
2. Confirm authority docs agree on implemented surfaces, stable contracts, and
   remaining release boundaries.
3. Run the full local gate:

   ```bash
   uv run ruff format --check .
   uv run ruff check .
   uv run mypy src
   uv run pytest
   ```

4. Run release-readiness proof:

   ```bash
   uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
   ```

5. Run benchmark proof:

   ```bash
   uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
   ```

6. Run an unsupported-claim scan for false current-status, sandbox,
   production-readiness, and large-file claims.
7. Classify the result:
   - `v1-hardening`: release package exists but proof is stale, incomplete, or
     blocked by remaining work.
   - `release-candidate eligible`: release package exists, full local gate
     passes, release-readiness proof passes, benchmark proof is refreshed or a
     current local artifact is cited, authority docs agree, and unsupported
     claims are absent.
   - `blocked`: a named proof, contract, docs, or environment blocker prevents
     honest candidate classification.
8. Stop before publish, tag, upload, GitHub release, or PyPI release.

Any publication or tagging step requires a separate explicit approval and should
not be executed by this release-package slice.

## Content Contracts

### CHANGELOG.md

The changelog should be concise and public-facing. It should summarize v1 by
capability area rather than by internal implementation task.

It should cover:

- query workflow
- inspect, sample, profile, and check
- project catalogs and saved SQL
- export
- doctor
- JSON contracts
- Python API
- benchmark and release-readiness proof
- known boundaries

It should avoid marketing claims and unsupported readiness language. It should
not say v1 has been released until an explicit release action is approved and
performed.

### docs/release-notes/v1.md

The v1 release notes should be more operational than the changelog.

They should include:

- current status: `v1-hardening` until final candidate proof passes
- implemented surfaces
- stable contracts: CLI, config schema, JSON outputs, exit codes, Python API,
  and DuckDB dependency floor
- proof checklist and exact commands
- generated artifact policy for ignored `output/` proof artifacts
- unsupported claims and boundaries
- publish/tag boundary
- final candidate decision template

The decision template should support these outcomes:

- `release-candidate eligible`
- `v1-hardening`
- `blocked`

### docs/release-readiness.md

Release readiness remains the authority for local gates and label rules.

It should link to the changelog and v1 release notes, then define the exact
candidate workflow. It should continue to state that local proof does not
publish packages, create tags, upload artifacts, create GitHub releases, or
mutate external systems.

## Verification

For the release-package implementation slice, verification should be docs-first:

```bash
git diff --check
rg -n "v1-ready|production-safe|sandbox-safe|large-file-proven|large-file performance" AGENTS.md README.md docs CHANGELOG.md
```

The plan may add a second claim scan for contextual terms such as
`release-candidate` and `v1-stable`, but legitimate label-rule mentions are
allowed when they are explicitly conditional.

Full Python tests are not required for a docs-only release-package edit unless
the implementation changes executable examples, scripts, source, tests, or
packaging metadata.

For the later final candidate check, verification should include:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

The final candidate check should also rerun unsupported-claim scans and inspect
generated proof artifact paths without committing generated `output/` files.

## Risks And Mitigations

Risk: release docs accidentally imply that v1 has already shipped.

Mitigation: keep the current status as `v1-hardening` and distinguish
`release-candidate eligible` from `v1-stable` and from an actual release action.

Risk: changelog reads like marketing instead of authority.

Mitigation: keep it factual, capability-based, and tied to implemented runtime
surfaces.

Risk: release notes overclaim safety or performance.

Mitigation: include explicit non-claims: no sandbox safety, no production
readiness, and no broad large-file performance claim beyond recorded benchmark
artifacts.

Risk: publish or tag steps sneak into the current slice.

Mitigation: document publication as a later approval boundary and do not execute
or automate it here.

Risk: generated release proof artifacts get committed.

Mitigation: keep `output/release-readiness/**`, `output/benchmarks/**`, wheels,
sdists, and scratch transcripts ignored unless a separate tracked-artifact
decision is made.

Risk: candidate proof needs network access for dependency resolution.

Mitigation: if `uv` build, lock, or proof commands fail from sandboxed network
or DNS limits, rerun through the active approval/escalation flow and report that
environment dependency plainly.

## Success Criteria

The implementation plan should be considered successful when:

- `CHANGELOG.md` exists and summarizes implemented v1 surfaces without
  unsupported release claims
- `docs/release-notes/v1.md` exists and contains the operational v1 release-note
  package
- `docs/release-readiness.md` defines the exact local candidate workflow and
  links the release-note surfaces
- any README or roadmap updates are small and only improve discoverability or
  consistency
- generated proof artifacts remain ignored
- unsupported current-status, sandbox, production-readiness, and broad
  large-file claims are absent
- final handoff keeps the status as `v1-hardening` unless a later final
  candidate proof proves eligibility

## Open Decisions

No product-scope decisions remain open for this design.

The only later decision is whether to approve a separate final release action
after candidate eligibility is proven. That later decision may include version
bump, tag, GitHub release, or PyPI publish steps, but those are out of scope for
this slice.
