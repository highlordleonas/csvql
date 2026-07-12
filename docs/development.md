# Development

This page is for contributors working from a source checkout. For normal use,
install LocalQL and run `csvql` as shown in [Getting started](getting-started.md).

## Local setup

```bash
uv sync --all-extras --frozen
uv run --frozen csvql --help
```

## Checks

Run the local quality gate in the existing project environment without
dependency reconciliation:

```bash
make ci
```

Before handoff or opening a pull request, reproduce the environment and run the
same checks from a frozen sync:

```bash
make ci-fresh
```

The individual checks use `uv run --frozen --no-sync`; `make ci` therefore
never reconciles project dependencies. `make ci-fresh` completes `make sync`
before invoking `make ci`, including when Make runs with parallel jobs.

If uv reports a missing file inside its package cache, clean only the named
broken package from the cache and repeat the frozen sync. For example:

```bash
uv cache clean hatchling
uv sync --all-extras --frozen
```

## Package changes

When changing package metadata or distribution contents, build and inspect the
packages locally:

```bash
uv build --sdist --wheel --out-dir output/package-audit/dist
uv run --frozen python scripts/audit_package_contents.py output/package-audit/dist
```

The source distribution includes public product and contributor documentation,
including the roadmap and public v2 design. It excludes repository agent
instructions, governance audit reports, internal plans or proof packets, and
local output. The package-content audit enforces those exclusions.

## SQL safety

LocalQL executes trusted local DuckDB SQL. It is not a sandbox and is not safe
for untrusted SQL.
