# Contributing

LocalQL is a solo-maintained local-first CLI project. Issues are welcome.
Pull requests are reviewed selectively, and the roadmap remains maintainer-owned.

## Good First Contributions

- clear bug reports with a small CSV example
- documentation fixes
- examples that use local CSV files
- focused tests for existing behavior
- small CLI/TUI usability fixes that preserve current contracts

## Project Boundaries

LocalQL packages the `csvql` command for local CSV analysis with DuckDB.
The installable distribution is `localql`; the CLI command, Python import
package, and config file remain `csvql`, `csvql`, and `.csvql.yml`.

In-scope contributions stay within local CSV files, DuckDB SQL, CLI/TUI
workflow, explicit exports, project catalogs, tests, and public documentation.

Out-of-scope contributions include web apps, hosted dashboards, cloud
connectors, notebook frameworks, NLP execution, dataframe-first APIs, plugin
systems, hidden caches, automatic materialization, safe-mode claims, sandbox
claims, production-readiness claims, and broad large-file claims without proof.

## Local Setup

```bash
uv sync --all-extras
uv run csvql --help
```

## Checks

Run the standard local gate before opening a pull request:

```bash
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

For package metadata or distribution-content changes, also follow the package
checks in [Development](docs/development.md).

## Git Workflow

Use branch names that describe the work type and scope:

- `feat/<short-scope>` for user-visible capability
- `fix/<short-scope>` for bug fixes
- `docs/<short-scope>` for documentation-only changes
- `test/<short-scope>` for test-only coverage changes
- `chore/<short-scope>` for maintenance
- `refactor/<short-scope>` for behavior-preserving code structure changes
- `release/<short-scope>` for packaging or release work
- `hotfix/<short-scope>` for urgent narrow fixes

Use conventional commit-style subjects, such as `docs: update terminal menu
guide` or `fix: restore recalled TUI result export`. Keep each commit focused
on one behavior or documentation change.

## Pull Requests

Keep pull requests focused. Include tests or docs updates when behavior changes.
Do not mix unrelated cleanup into a feature or bug fix.

## Conduct And Security

Follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report sensitive
vulnerabilities through the path in [Security](SECURITY.md), not public issues.
