# Development

This page is for contributors working from a source checkout. For normal use,
install LocalQL and run `csvql` as shown in [Getting started](getting-started.md).

## Local setup

```bash
uv sync --all-extras
uv run csvql --help
```

## Checks

Run the local quality checks before opening a pull request:

```bash
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

## Package changes

When changing package metadata or distribution contents, build and inspect the
packages locally:

```bash
uv build --sdist --wheel --out-dir output/package-audit/dist
uv run python scripts/audit_package_contents.py output/package-audit/dist
```

## SQL safety

LocalQL executes trusted local DuckDB SQL. It is not a sandbox and is not safe
for untrusted SQL.
