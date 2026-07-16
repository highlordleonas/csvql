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
