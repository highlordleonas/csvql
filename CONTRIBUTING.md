# Contributing

LocalQL is maintained by one person. Issues are welcome, and focused pull
requests are useful when they fit the project described below.

## Good First Contributions

- clear bug reports with a small CSV example
- documentation fixes
- examples that use local CSV files
- focused tests for existing behavior
- small CLI/TUI usability fixes that preserve documented behavior

## What Fits The Project

LocalQL packages the `csvql` command for local CSV analysis with DuckDB.
The installable distribution is `localql`; the CLI command, Python import
package, and config file remain `csvql`, `csvql`, and `.csvql.yml`.

Contributions should focus on local CSV files, DuckDB SQL, the CLI or terminal
menu, exports, project catalogs, tests, and public documentation.

LocalQL is not intended to become a web app, hosted dashboard, cloud connector,
notebook framework, natural-language query tool, dataframe-first API, or plugin
system. Changes should not describe LocalQL as a sandbox, as safe for untrusted
SQL, or as suitable for workloads that have not been tested.

## Local Setup

```bash
uv sync --all-extras
uv run csvql --help
```

## Checks

Run these checks before opening a pull request:

```bash
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

For package metadata or distribution-content changes, also follow the package
checks in [Development](docs/development.md).

## Git Workflow

Use a short branch name that describes the change, such as
`docs/improve-quickstart` or `fix/export-message`.

Use conventional commit-style subjects, such as `docs: update terminal menu
guide` or `fix: restore recalled TUI result export`. Keep each commit focused
on one behavior or documentation change.

## Pull Requests

Keep pull requests focused. Include tests or docs updates when behavior changes.
Do not mix unrelated cleanup into a feature or bug fix.

## Conduct And Security

Follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report sensitive
vulnerabilities through the path in [Security](SECURITY.md), not public issues.
