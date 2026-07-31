# Development

This guide is for contributors working from a LocalQL source checkout. To use
the installed application, follow [Getting started](getting-started.md) and run
the `csvql` command directly.

## Set up the contributor environment

Use the repository's locked dependencies and include the optional terminal-menu
extra:

```bash
uv sync --all-extras --frozen
uv run --all-extras csvql --help
```

## Run checks

Run the relevant checks before opening a pull request:

```bash
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

Use focused tests while iterating, then run the broader suite when a change
crosses command, configuration, packaging, or terminal-menu behavior.

## Benchmark structured exports

Run the end-to-end multi-format export matrix after export, provider, or
dependency-lifecycle changes:

```bash
uv run --locked --no-sync python scripts/benchmark_multiformat_exports.py \
  --rows 100000 \
  --warmup-runs 1 \
  --measured-runs 3
```

The benchmark covers CSV, JSON, NDJSON, Parquet, and Excel inputs crossed with
NDJSON, Parquet, and Excel outputs. Timings include CLI startup, source
resolution, query execution, export writing, and atomic publication. Validation
runs after timing and checks row count and deterministic ID aggregates.

Excel must already be provisioned for the active DuckDB runtime; the benchmark
fails closed and never installs it. Results are local evidence under
`output/benchmarks/multiformat-exports/`, which is ignored by Git. Compare only
runs with the same machine, runtime, row count, warmups, and measured-run count.

## Package changes

When changing package metadata or distribution contents, build and inspect the
artifacts locally:

```bash
uv build --sdist --wheel --out-dir dist
uv run python scripts/audit_package_contents.py dist
```

## Document behavior

Keep installed-user commands in public guides as `csvql ...`. Update the
relevant guide, release notes, troubleshooting entry, and screenshots when a
user-visible workflow changes.

## SQL safety

LocalQL executes trusted local DuckDB SQL. It is not a sandbox and is not safe
for untrusted SQL.
