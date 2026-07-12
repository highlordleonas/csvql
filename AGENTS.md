# LocalQL Repository Instructions

## Project Contract

LocalQL is the installable distribution for the `csvql` command and Python
package. The released v1 contract is a local CSV workflow backed by DuckDB:
query, inspect, sample, profile, configured checks, explicit exports, project
catalogs, a small Python API, and an optional terminal workbench.

DuckDB executes user-authored SQL. Treat that SQL as trusted local input.
LocalQL is not a sandbox and does not restrict DuckDB filesystem access.

The maintainer-approved future direction is recorded in `docs/ROADMAP.md` and
`docs/v2-point-and-query-design.md`. Treat those documents as product-direction
authority, not implementation authority. They do not authorize implementation,
dependency changes, network access, releases, or external-system writes by
themselves.

## Authority And Structure

- `README.md` is the public entry point.
- `docs/ROADMAP.md` owns phased product direction and milestone status.
- `docs/ARCHITECTURE.md` describes current implemented architecture.
- `docs/json-contracts.md` documents stable v1 JSON output.
- `docs/v2-point-and-query-design.md` records maintainer-approved product
  direction and a proposed v2 architecture, not current implementation truth.
- `src/csvql/` and `tests/` establish current behavior.
- `pyproject.toml`, `uv.lock`, `Makefile`, and `.github/workflows/` establish
  package and validation mechanics.

When these sources disagree, preserve the released contract, use code and tests
for observed behavior, and record unresolved product or architecture decisions
instead of inventing a resolution.

## Tooling And Validation

Use `uv`; do not introduce another package manager or install global tools.
Keep dependency and `uv.lock` changes intentional and task-scoped.

Canonical setup and validation:

```bash
uv sync --all-extras --frozen
make ci
make ci-fresh
```

`make ci` runs Ruff formatting and lint checks, strict mypy, and the full pytest
suite in the existing project environment without dependency reconciliation.
`make ci-fresh` completes a frozen sync before invoking `make ci` and is the
lock-reconciled reproducibility gate for handoff. Use narrower tests during
iteration, then run the appropriate complete gate.

## Change Boundaries

- Keep `cli.py` a thin Typer boundary and DuckDB execution in `engine.py`.
- Validate aliases, paths, catalog content, and connector input at boundaries.
- Preserve stable CLI, Python, catalog, JSON, exit-code, and export contracts or
  provide an explicit compatibility decision and migration path.
- Do not claim sandbox safety, production readiness, connector support, or
  large-data performance without direct evidence.
- Do not add hidden persistent caches or silently install dependencies,
  connectors, or DuckDB extensions.
- Never store credentials or tokens in tracked catalogs, tests, logs, errors,
  screenshots, or documentation examples.
- Remote connectors and v2 source adapters remain proposal-only until a
  separately approved implementation plan exists.

Do not commit, tag, publish, deploy, change release controls, or write to remote
systems unless the user explicitly authorizes that action for the current task.

## Documentation And Handoff

Public installed-user examples use `csvql ...`. Source-checkout development
examples may use `uv run ...`.

For implementation handoff, report files changed, checks run and their results,
skipped checks, compatibility impact, and remaining risks. Keep proposals,
approved work, implemented work, verified work, and released work distinct.
