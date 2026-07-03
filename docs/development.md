# Development

This page is for contributors and maintainers working from a source checkout.
For normal usage, install LocalQL and run the `csvql` command.

## Naming Contract

LocalQL is the installable distribution name. The CLI command remains `csvql`,
the Python import package remains `csvql`, and the project configuration file
remains `.csvql.yml`.

## Local Setup

```bash
uv sync --all-extras
uv run csvql --help
```

## Local Gates

```bash
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

## SQL Trust Boundary

LocalQL treats user-authored SQL as trusted local DuckDB SQL. It does not
sandbox DuckDB, restrict DuckDB filesystem access, or make untrusted SQL safe.
Do not document or implement safe-mode behavior without a dedicated design,
tests, and explicit maintainer approval.

## Package Audit

Before external release approval, build and inspect the package artifacts:

```bash
uv build --sdist --wheel --out-dir output/package-audit/dist
uv run python scripts/audit_package_contents.py output/package-audit/dist
```

The audit should reject `.DS_Store`, caches, virtual environments, `.csvql/`,
`output/`, `keys.log`, `csvql_project_pack/`, `csvql_project_pack.zip`, and
internal planning material.

## Release Readiness

Run the repo-local release-readiness proof on the final intended release state:

```bash
uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness-localql-public
```

This proof builds the package, installs the built wheel, smokes the installed
`csvql` command, and verifies the optional TUI extra import.

## Release Boundary

Do not create a tag, publish to PyPI, create a GitHub release, upload artifacts,
change the package version, or claim `v1-stable` without separate explicit
approval after final proof passes.
