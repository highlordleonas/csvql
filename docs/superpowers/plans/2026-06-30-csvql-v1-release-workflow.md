# CSVQL v1 Release Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the local-only v1 release package: a root changelog, detailed v1 release notes, and release-readiness workflow updates that make final candidate evaluation executable without publishing or tagging anything.

**Architecture:** Keep this docs-only. `CHANGELOG.md` becomes the concise public change-history surface, `docs/release-notes/v1.md` becomes the operational release-note and candidate checklist, and `docs/release-readiness.md` remains the local gate and label-rule authority. README and roadmap changes are limited to discoverability and current-lane alignment.

**Tech Stack:** Markdown docs, `rg`, `git diff --check`, existing `uv` release proof commands documented but not run in this implementation slice.

---

## Preconditions

- Start from a clean worktree on `main`.
- Use the committed spec at `docs/superpowers/specs/2026-06-30-csvql-v1-release-workflow-design.md` as the authority for this slice.
- Keep the status label `v1-hardening`.
- Do not claim `release-candidate`, `v1-stable`, production readiness, sandbox safety, or broad large-file proof.
- Do not publish, tag, push, upload artifacts, bump the version, add scripts, or create release automation.
- Do not change Python source, tests, package metadata, JSON contracts, exit codes, config schema, or CLI behavior.

Run before editing:

```bash
git status --short --branch
git log -1 --oneline
sed -n '1,260p' docs/superpowers/specs/2026-06-30-csvql-v1-release-workflow-design.md
```

Expected:

- `git status --short --branch` prints `## main`.
- Latest commit is the approved design spec or a later clean commit containing it.
- The spec confirms the included files are `CHANGELOG.md`, `docs/release-notes/v1.md`, `docs/release-readiness.md`, and small README/roadmap link updates if needed.

## Scope And Constraints

Included:

- Create `CHANGELOG.md`.
- Create `docs/release-notes/v1.md`.
- Update `docs/release-readiness.md`.
- Update README documentation links and release-hardening language.
- Update `docs/ROADMAP.md` so remaining pre-v1 work reflects that the release package exists after this plan is executed.
- Run docs-only verification and claim scans.

Excluded:

- PyPI publishing.
- Git tags.
- GitHub releases.
- Version bump.
- Package upload or artifact upload.
- New release automation.
- New CLI commands.
- New scripts or Make targets.
- JSON contract changes.
- Exit-code redesign.
- Config schema changes.
- Python API changes.
- Safe mode or sandbox behavior.
- Cache or materialization.
- Web, cloud, notebook, dataframe-first, AI, or plugin scope.
- Claiming `release-candidate` or `v1-stable` before fresh final proof.

## Command, JSON, Exit-Code, Config, Docs, And Test Impact

Command impact:

- No CLI commands change.

JSON impact:

- No runtime JSON output changes.

Exit-code impact:

- No exit-code behavior changes.

Config impact:

- No `.csvql.yml` schema changes.

Docs impact:

- Adds changelog and v1 release notes.
- Updates release-readiness workflow and label rules.
- Adds README links to changelog and v1 release notes.
- Updates roadmap remaining-work language after release-note material exists.

Test impact:

- No pytest suite is required for this docs-only slice.
- `git diff --check` and claim scans are required.
- Full local gate, release-readiness proof, and benchmark proof are documented for the later final candidate check, not executed by this plan unless executable examples or source are changed unexpectedly.

## File Structure

- Create: `CHANGELOG.md`
  - Concise public-facing change history for implemented v1 surfaces.
- Create: `docs/release-notes/v1.md`
  - Detailed operational v1 release notes, proof checklist, non-claims, and candidate decision template.
- Modify: `docs/release-readiness.md`
  - Exact local candidate workflow, release-note links, and label rules.
- Modify: `README.md`
  - Release-hardening text and documentation links.
- Modify: `docs/ROADMAP.md`
  - Remaining before v1 once release workflow and release notes exist.

## Task 1: Baseline And Changelog

**Files:**
- Create: `CHANGELOG.md`

- [ ] **Step 1: Confirm baseline repo state**

Run:

```bash
git status --short --branch
git log -1 --oneline
```

Expected:

- `git status --short --branch` prints `## main`.
- Latest commit contains the approved release workflow design spec.

- [ ] **Step 2: Create `CHANGELOG.md`**

Create `CHANGELOG.md` with this complete content:

```markdown
# Changelog

All notable CSVQL changes are summarized here.

CSVQL is currently in `v1-hardening`. The `v1.0.0` section records implemented
surfaces for release preparation; it is not a publication, tag, PyPI upload, or
`v1-stable` claim.

## v1.0.0 - Pending

Status: `v1-hardening`. Final release-candidate proof has not yet been run on
the release-package state.

### Added

- DuckDB-backed local CSV query workflow through `csvql query`.
- Explicit table mappings with `--table name=path`.
- Single-file shortcut query mode.
- Project catalogs through `.csvql.yml`, `csvql init`, `csvql add`, and
  `csvql tables`.
- Catalog-backed query, inspect, sample, profile, check, run, and export
  workflows.
- Saved SQL execution through `csvql run`.
- Explicit exports through `csvql export` with CSV, JSON, and Markdown formats.
- CSV inspection through `csvql inspect`.
- Bounded data samples through `csvql sample`.
- CSV profiling through `csvql profile`.
- Configured data-quality checks through `csvql check`.
- Project health checks through `csvql doctor`.
- Table and JSON output modes for automation-oriented commands.
- Stable v1 JSON contract documentation for current runtime shapes.
- Common failure gallery for deterministic CLI behavior and exit-code examples.
- Polished SaaS revenue example project with reproducible data and saved SQL.
- Repo-local benchmark workflow with JSON and Markdown artifacts.
- Repo-local release-readiness proof for version, build, wheel install, and
  smoke behavior.
- Small project-backed Python API through `CSVQLSession`.

### Stable v1 Contract Decisions

- Current v0.8 JSON output shapes are the stable v1 runtime contract.
- Current exit-code behavior is the stable v1 CLI failure contract.
- `.csvql.yml` remains strict `version: 1` without a migration framework.
- The Python API remains project-backed and intentionally small.
- DuckDB remains the only SQL execution engine.
- DuckDB dependency support is constrained to `duckdb>=1.5.0,<2`.

### Known Boundaries

- CSVQL treats user-authored SQL as trusted local SQL.
- CSVQL does not sandbox DuckDB or restrict filesystem access.
- CSVQL does not claim production readiness.
- CSVQL does not claim broad large-file performance beyond recorded benchmark
  artifacts.
- CSVQL does not include a web app, cloud connector platform, dashboard,
  notebook framework, natural-language SQL engine, dataframe-first API, plugin
  system, safe mode, hidden cache, or automatic materialization.

### Release Proof

Candidate eligibility requires fresh local proof on the candidate state:

- full local gate through Ruff, mypy, and pytest
- release-readiness proof through `scripts/verify_release_readiness.py`
- benchmark proof through `scripts/benchmark_csvql.py`
- unsupported-claim scan
- explicit final classification as `v1-hardening`, `release-candidate eligible`,
  or `blocked`
```

- [ ] **Step 3: Check changelog diff**

Run:

```bash
git diff -- CHANGELOG.md
```

Expected:

- Diff creates only `CHANGELOG.md`.
- The file says `v1-hardening`.
- The file does not say `release-candidate`, `v1-stable`, production ready, sandbox safe, or large-file proven as current facts.

- [ ] **Step 4: Commit changelog**

Run:

```bash
git add CHANGELOG.md
git commit -m "docs: add v1 changelog"
```

Expected:

- Commit succeeds.
- Commit includes only `CHANGELOG.md`.

## Task 2: Add v1 Release Notes

**Files:**
- Create: `docs/release-notes/v1.md`

- [ ] **Step 1: Create release-notes directory**

Run:

```bash
mkdir -p docs/release-notes
```

Expected:

- `docs/release-notes/` exists.
- No tracked files change yet.

- [ ] **Step 2: Create `docs/release-notes/v1.md`**

Create `docs/release-notes/v1.md` with this complete content:

````markdown
# CSVQL v1 Release Notes

Status: `v1-hardening`

Candidate decision: not yet evaluated on the release-package state.

This document is the operational v1 release-note package. It records what v1
contains, what proof is required, what claims are intentionally not made, and
how to classify the final candidate check. It does not publish packages, create
tags, upload artifacts, create a GitHub release, or claim `v1-stable`.

## Implemented Surfaces

CSVQL v1 is the stable local-first CSV workflow already implemented in this
repo:

- `csvql query --table name=path "SELECT ..."`
- single-file shortcut query mode
- `.csvql.yml` project catalogs
- `csvql init`
- `csvql add`
- `csvql tables`
- catalog-backed SQL queries
- `csvql inspect`
- `csvql sample`
- `csvql profile`
- `csvql check`
- `csvql run`
- `csvql export`
- `csvql doctor`
- table and JSON output modes
- deterministic failure behavior documented in the failure gallery
- polished SaaS revenue example project
- benchmark and release-readiness proof scripts
- project-backed Python API through `CSVQLSession`

## Stable Contracts

### CLI Contract

The documented CLI command surface is stable for v1. DuckDB owns SQL execution;
CSVQL owns local workflow, table aliasing, source resolution, output rendering,
deterministic errors, and project configuration.

### Config Contract

`.csvql.yml` remains strict `version: 1`.

Supported top-level keys:

- `version`
- `tables`

Supported table keys:

- `path`
- `checks`

There is no v1 migration framework, alternate config filename, or new config
schema feature in this release package.

### JSON Contract

The current v0.8 JSON output shapes are the stable v1 runtime contract.
`docs/json-contracts.md` is the detailed JSON authority.

Current shape differences are intentional v1 facts. Query-shaped results,
inspection results, profile results, check results, doctor results, table lists,
and benchmark artifacts are not normalized into a shared envelope for v1.

### Exit-Code Contract

The current exit-code behavior is stable for v1:

- `0`: success, including doctor warnings and zero configured checks
- `1`: general CSVQL error and DuckDB query execution failure
- `4`: missing CSV file
- `6`: invalid table mapping or table alias
- `7`: inspect or sample failure
- `8`: project catalog discovery, parsing, or validation failure
- `9`: saved SQL file failure
- `10`: export path or export format failure
- `11`: configured data-quality checks ran and found failures
- `12`: doctor found concrete project-health failures

### Python API Contract

The v1 Python API is small and project-backed:

- `CSVQLSession.from_config(path)`
- `session.tables()`
- `session.query(sql)`
- `session.run_file(path)`
- `session.inspect(table, exact=False)`
- `session.sample(table, limit=10)`
- `session.profile(table)`
- `session.check(table=None)`
- `session.export(sql_file, out, format="json", force=False)`

The Python API does not provide direct-path sessions, ad hoc table mappings,
config mutation helpers, dataframe helpers, async execution, plugin APIs, a
persistent session-level DuckDB connection, or a second execution engine.

### DuckDB Contract

DuckDB remains the sole SQL engine. The package dependency floor is
`duckdb>=1.5.0,<2`.

This does not make CSVQL a sandbox. DuckDB SQL may access files or external
resources depending on settings and extensions. CSVQL is a local automation tool
for trusted projects.

## Candidate Proof Checklist

Run from a clean worktree on `main`.

Capture baseline truth:

```bash
pwd
git status --short --branch
git log -1 --oneline
```

Run the full local gate:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

Run release-readiness proof:

```bash
uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

Run benchmark proof:

```bash
uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Run an unsupported-claim scan across current authority docs:

```bash
rg -n "v1-ready|production-safe|sandbox-safe|large-file-proven|production-ready" AGENTS.md README.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/release-readiness.md docs/release-notes/v1.md CHANGELOG.md
```

Any match must be a guardrail, non-claim, or conditional label rule. A current
claim that CSVQL is v1-ready, production-safe, sandbox-safe, production-ready,
or large-file-proven blocks candidate eligibility.

## Generated Artifact Policy

Release proof writes local evidence under ignored output directories:

- `output/release-readiness/**`
- `output/benchmarks/**`

Generated wheels, sdists, benchmark JSON, benchmark Markdown summaries, virtual
environments, and scratch transcripts remain local evidence unless a separate
tracked-artifact decision is made.

## Unsupported Claims

The v1 release package does not claim:

- sandbox safety
- safe execution of untrusted SQL
- production readiness
- broad large-file performance
- cloud readiness
- multi-tenant isolation
- a web, dashboard, notebook, AI, dataframe, async, plugin, cache, or
  materialization platform

## Publish And Tag Boundary

The proof commands are local verification commands only.

They do not:

- publish to PyPI
- push Git tags
- create GitHub releases
- upload artifacts
- mutate external systems
- change the package version

Any final release action requires separate explicit approval after candidate
eligibility is proven.

## Final Candidate Decision Template

Use one of these outcomes after the final candidate check:

### `release-candidate eligible`

Use only when all of the following are true:

- release package exists
- full local gate passes
- release-readiness proof passes
- benchmark proof is refreshed or a current local benchmark artifact is cited
- authority docs agree with runtime behavior
- unsupported claims are absent
- generated proof artifacts remain ignored

### `v1-hardening`

Use when the release package exists but proof is stale, incomplete, not run, or
blocked by remaining docs or runtime work.

### `blocked`

Use when a named proof, contract, docs, environment, dependency, or tooling
blocker prevents honest candidate classification.

## Current Decision

Current status remains `v1-hardening`.

The next task after this release-note package is the final release-candidate
eligibility check.
````

- [ ] **Step 3: Check release notes diff**

Run:

```bash
git diff -- docs/release-notes/v1.md
```

Expected:

- Diff creates only `docs/release-notes/v1.md`.
- The file keeps current status as `v1-hardening`.
- The file makes publish/tag/upload/version-bump boundaries explicit.

- [ ] **Step 4: Commit release notes**

Run:

```bash
git add docs/release-notes/v1.md
git commit -m "docs: add v1 release notes"
```

Expected:

- Commit succeeds.
- Commit includes only `docs/release-notes/v1.md`.

## Task 3: Update Release Readiness Authority

**Files:**
- Modify: `docs/release-readiness.md`

- [ ] **Step 1: Replace release-readiness document**

Replace `docs/release-readiness.md` with this complete content:

````markdown
# Release Readiness

CSVQL is in post-v0.7/v0.8 hardening toward v1. This document defines the
local proof path for `release-candidate` and `v1-stable` labels. It does not
publish packages, create tags, upload artifacts, or claim a release by itself.

Release-note surfaces:

- [Changelog](../CHANGELOG.md)
- [v1 release notes](release-notes/v1.md)

For this lane, the release package means these tracked docs exist and agree:

- `CHANGELOG.md`
- `docs/release-notes/v1.md`
- this local candidate workflow in `docs/release-readiness.md`
- README and roadmap discoverability updates

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

## Local Candidate Workflow

Run candidate evaluation from a clean worktree on `main`.

1. Capture baseline truth:

   ```bash
   pwd
   git status --short --branch
   git log -1 --oneline
   ```

2. Confirm authority docs agree with implemented runtime behavior:

   - `AGENTS.md`
   - `README.md`
   - `CHANGELOG.md`
   - `docs/PRODUCT_DIRECTION.md`
   - `docs/ROADMAP.md`
   - `docs/ARCHITECTURE.md`
   - `docs/json-contracts.md`
   - `docs/release-readiness.md`
   - `docs/release-notes/v1.md`

3. Run the full local gate.
4. Run release-readiness proof.
5. Run benchmark proof or explicitly cite a current local benchmark artifact.
   A current local benchmark artifact must come from the same candidate-state
   `HEAD`; record both `output/benchmarks/<run-id>/benchmark.json` and
   `output/benchmarks/<run-id>/benchmark-summary.md`. Rerunning
   `uv run python scripts/benchmark_csvql.py --output-root output/benchmarks`
   during final candidate evaluation is preferred.
6. Scan for unsupported current claims:

   ```bash
   rg -n "v1-ready|production-safe|sandbox-safe|large-file-proven|production-ready" AGENTS.md README.md CHANGELOG.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/release-readiness.md docs/release-notes/v1.md
   ```

   Any match must be a guardrail, non-claim, or conditional label rule. A current
   claim that CSVQL is v1-ready, production-safe, sandbox-safe,
   production-ready, or large-file-proven blocks candidate eligibility.

7. Classify the result:

   - `v1-hardening`: release package exists but proof is stale, incomplete, not
     run, or blocked by remaining work.
   - `release-candidate eligible`: release package exists, full local gate
     passes, release-readiness proof passes, benchmark proof is refreshed or a
     same-HEAD local benchmark artifact is cited with benchmark JSON and
     Markdown summary paths, authority docs agree, and unsupported claims are
     absent.
   - `blocked`: a named proof, contract, docs, environment, dependency, or
     tooling blocker prevents honest candidate classification.

8. Stop before publishing, tagging, uploading artifacts, creating a GitHub
   release, or changing the package version.

## Label Rules

Use `v1-hardening` for the current lane until final candidate proof is fresh,
complete, and reviewed.

Use `release-candidate eligible` only as an assessment result after:

- AGENTS.md, README, changelog, release notes, roadmap, product direction,
  architecture, JSON contracts, and release readiness agree with the runtime
  surface
- current JSON shapes, exit codes, config schema, DuckDB dependency floor, and
  Python API surface are documented and test-backed
- the release-readiness script passes on the candidate state
- benchmark proof is refreshed or a same-HEAD local benchmark artifact is cited
  with benchmark JSON and Markdown summary paths
- the full local gate passes
- changelog and release-note material exists for the implemented surfaces
- docs make no unsupported sandbox, security-isolation, production-readiness,
  or large-file performance claims

Use `release-candidate` as a status label only after candidate eligibility is
proven and the user explicitly approves changing the label.

Use `v1-stable` only after the release-candidate proof remains valid, the
repo-defined `v1-stable` conditions in `AGENTS.md` are satisfied, and the final
release action is explicitly approved.

## Generated Artifact Policy

Proof workflows write local evidence under ignored output directories:

- `output/release-readiness/**`
- `output/benchmarks/**`

Generated wheels, sdists, benchmark JSON, benchmark Markdown summaries, virtual
environments, and scratch transcripts are local evidence only. Do not commit
them unless a separate tracked-artifact decision is made.

## No-Publish Boundary

The commands in this document are local verification commands. They do not
publish to PyPI, push Git tags, create GitHub releases, upload artifacts, bump
the version, or mutate external systems.
````

- [ ] **Step 2: Check release-readiness diff**

Run:

```bash
git diff -- docs/release-readiness.md
```

Expected:

- Diff adds release-note links.
- Diff adds the local candidate workflow.
- Diff distinguishes `release-candidate eligible` from a `release-candidate` status label.
- Diff keeps the no-publish boundary.

- [ ] **Step 3: Commit release-readiness update**

Run:

```bash
git add docs/release-readiness.md
git commit -m "docs: define v1 candidate workflow"
```

Expected:

- Commit succeeds.
- Commit includes only `docs/release-readiness.md`.

## Task 4: Update Discoverability Docs

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Update README status paragraph**

In `README.md`, replace this paragraph:

```markdown
project-backed Python API. The current lane is v1 hardening: authority
alignment, release workflow and changelog work, and contract stabilization.
```

With:

```markdown
project-backed Python API. The current lane is v1 hardening: with the v1
release package applied, the remaining gate is final release-candidate
eligibility proof.
```

Expected:

- README still says current lane is v1 hardening.
- README no longer says release workflow and changelog work are unstarted after this plan is implemented.

- [ ] **Step 2: Update README release hardening section**

In `README.md`, replace this section:

```markdown
## Benchmark And Release Hardening

Generate local benchmark evidence:

- `uv run python scripts/benchmark_csvql.py --output-root output/benchmarks`

Verify build and install proof:

- `uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness`

Claims boundary:

- Local benchmark evidence only
- No large-file proof beyond the recorded datasets
- No production-readiness claim
```

With:

```markdown
## Benchmark And Release Hardening

Generate local benchmark evidence:

- `uv run python scripts/benchmark_csvql.py --output-root output/benchmarks`

Verify build and install proof:

- `uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness`

Release workflow and notes:

- [Changelog](CHANGELOG.md)
- [v1 release notes](docs/release-notes/v1.md)
- [Release readiness](docs/release-readiness.md)

Claims boundary:

- Local benchmark evidence only
- No large-file proof beyond the recorded datasets
- No production-readiness claim
- No sandbox-safety claim
- No publish, tag, or upload action without separate explicit approval
```

Expected:

- README points users to the changelog, v1 release notes, and release-readiness docs.
- README does not claim a release has occurred.

- [ ] **Step 3: Update README documentation list**

In `README.md`, replace this list:

```markdown
- [Architecture](docs/ARCHITECTURE.md)
- [Benchmarking](docs/benchmarking.md)
- [JSON contracts](docs/json-contracts.md)
- [Failure gallery](docs/failure-gallery.md)
- [Product direction](docs/PRODUCT_DIRECTION.md)
- [Release readiness](docs/release-readiness.md)
- [Roadmap](docs/ROADMAP.md)
- [Codex capability review](docs/CODEX_CAPABILITY_REVIEW.md)
- [v1 Quality Spine design](docs/superpowers/specs/2026-06-26-csvql-v1-quality-spine-design.md)
```

With:

```markdown
- [Architecture](docs/ARCHITECTURE.md)
- [Benchmarking](docs/benchmarking.md)
- [Changelog](CHANGELOG.md)
- [JSON contracts](docs/json-contracts.md)
- [Failure gallery](docs/failure-gallery.md)
- [Product direction](docs/PRODUCT_DIRECTION.md)
- [Release readiness](docs/release-readiness.md)
- [v1 release notes](docs/release-notes/v1.md)
- [Roadmap](docs/ROADMAP.md)
- [Codex capability review](docs/CODEX_CAPABILITY_REVIEW.md)
- [v1 Quality Spine design](docs/superpowers/specs/2026-06-26-csvql-v1-quality-spine-design.md)
```

Expected:

- README documentation links include `CHANGELOG.md` and `docs/release-notes/v1.md`.

- [ ] **Step 4: Update roadmap remaining-work section**

In `docs/ROADMAP.md`, replace this section:

```markdown
Remaining before v1:

- release workflow and release-note material
- final release-candidate eligibility check after release workflow and release
  notes exist
```

With:

```markdown
Remaining before v1:

- final release-candidate eligibility check after release workflow and release
  notes exist
```

Expected:

- Roadmap no longer lists release workflow and release-note material as remaining once this plan is implemented.
- Roadmap still requires final release-candidate eligibility check.

- [ ] **Step 5: Review README and roadmap diffs**

Run:

```bash
git diff -- README.md docs/ROADMAP.md
```

Expected:

- Diff is limited to release workflow, release-note, and documentation-link language.
- No unrelated README examples or roadmap milestones change.

- [ ] **Step 6: Commit discoverability updates**

Run:

```bash
git add README.md docs/ROADMAP.md
git commit -m "docs: link v1 release package"
```

Expected:

- Commit succeeds.
- Commit includes only `README.md` and `docs/ROADMAP.md`.

## Task 5: Verify Docs Package

**Files:**
- Read: `AGENTS.md`
- Read: `README.md`
- Read: `CHANGELOG.md`
- Read: `docs/PRODUCT_DIRECTION.md`
- Read: `docs/ROADMAP.md`
- Read: `docs/ARCHITECTURE.md`
- Read: `docs/json-contracts.md`
- Read: `docs/release-readiness.md`
- Read: `docs/release-notes/v1.md`

- [ ] **Step 1: Check whitespace and patch hygiene**

Run:

```bash
git diff --check HEAD~4..HEAD
```

Expected:

- No output.
- Exit code `0`.

- [ ] **Step 2: Scan for unsupported hard claims**

Run:

```bash
rg -n "v1-ready|production-safe|sandbox-safe|large-file-proven|production-ready" AGENTS.md README.md CHANGELOG.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/release-readiness.md docs/release-notes/v1.md
```

Expected:

- Any matches are only guardrails, non-claims, or examples of claims CSVQL does not make.
- There is no current claim that CSVQL is v1-ready, production-safe, sandbox-safe, large-file-proven, or production-ready.

- [ ] **Step 3: Scan release status language**

Run:

```bash
rg -n "release-candidate|v1-stable|v1-hardening" AGENTS.md README.md CHANGELOG.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/release-readiness.md docs/release-notes/v1.md
```

Expected:

- Current status references say `v1-hardening`.
- `release-candidate` references are conditional, label rules, or `release-candidate eligible` assessment language.
- `v1-stable` references are conditional rules only.

- [ ] **Step 4: Verify release-note links resolve by path inspection**

Run:

```bash
test -f CHANGELOG.md
test -f docs/release-notes/v1.md
test -f docs/release-readiness.md
```

Expected:

- All commands exit `0`.

- [ ] **Step 5: Inspect final git status**

Run:

```bash
git status --short --branch
git log --oneline -5
```

Expected:

- `git status --short --branch` prints `## main`.
- Recent commits include:
  - `docs: add v1 changelog`
  - `docs: add v1 release notes`
  - `docs: define v1 candidate workflow`
  - `docs: link v1 release package`

## Task 6: Final Handoff

**Files:**
- Read: `CHANGELOG.md`
- Read: `docs/release-notes/v1.md`
- Read: `docs/release-readiness.md`
- Read: `README.md`
- Read: `docs/ROADMAP.md`

- [ ] **Step 1: Prepare final handoff**

Use this handoff structure:

```markdown
Implemented the v1 local release package.

Changed:
- `CHANGELOG.md`: added pending v1 changelog with implemented surfaces and boundaries.
- `docs/release-notes/v1.md`: added operational v1 release notes, proof checklist, artifact policy, non-claims, and decision template.
- `docs/release-readiness.md`: defined the local candidate workflow and label rules.
- `README.md`: linked release package docs and clarified release-hardening boundaries.
- `docs/ROADMAP.md`: narrowed remaining pre-v1 work to final release-candidate eligibility check.

Verification:
- `git diff --check HEAD~4..HEAD`
- unsupported hard-claim scan
- release status language scan
- path checks for release-note docs

Status:
- Still `v1-hardening`.
- Not `release-candidate`.
- Not `v1-stable`.

Next task:
- Run final release-candidate eligibility check: full local gate, release-readiness proof, benchmark proof, claim scan, and final classification.
```

Expected:

- Handoff does not claim `release-candidate` or `v1-stable`.
- Handoff states that final candidate proof is next.

## Plan Self-Review

Spec coverage:

- `CHANGELOG.md`: Task 1.
- `docs/release-notes/v1.md`: Task 2.
- `docs/release-readiness.md`: Task 3.
- README and roadmap discoverability updates: Task 4.
- Claim scans and docs-only verification: Task 5.
- Final status and next task: Task 6.

Placeholder scan:

- The plan contains no placeholder sections.
- The plan contains complete Markdown content for new files and exact replacement text for modified docs.

Scope check:

- The plan is docs-only.
- The plan does not publish, tag, upload, bump versions, add release automation, or change runtime behavior.
- The plan keeps current status as `v1-hardening`.

Residual risk:

- Claim scans include conditional and non-claim language, so the implementer must distinguish guardrails from false current-state claims.
- Full local gate and proof commands are intentionally deferred to the final candidate check unless executable files unexpectedly change.
