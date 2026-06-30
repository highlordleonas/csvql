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

Use `v1-stable` only after the release-candidate proof remains valid, the
repo-defined `v1-stable` conditions in `AGENTS.md` are satisfied, and the final
release action is explicitly approved.

## No-Publish Boundary

The commands in this document are local verification commands. They do not
publish to PyPI, push Git tags, create GitHub releases, upload artifacts, or
mutate external systems.
