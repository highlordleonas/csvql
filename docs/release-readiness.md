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
