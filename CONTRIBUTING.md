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

Current v1 contributions should focus on local CSV files, DuckDB SQL, the CLI or
terminal menu, exports, project catalogs, tests, and public documentation.
Future structured-source work must name a maintainer-approved direction in
[the roadmap](docs/ROADMAP.md), confirm that the direction has been adopted in
the repository, and still requires a separately approved implementation lane.

LocalQL is not intended to become a web app, hosted dashboard, notebook
framework, natural-language query tool, dataframe-first API, or ungoverned
plugin system. The maintainer-approved future connector direction does not
authorize unsupported sources, remote writes, embedded credentials, or
implementation outside a named roadmap lane. Changes should not describe
LocalQL as a sandbox, as safe for untrusted SQL, or as suitable for workloads
that have not been tested.

## Local Setup

```bash
uv sync --all-extras --frozen
uv run --frozen csvql --help
```

## Checks

Run these checks before opening a pull request:

```bash
make ci
make ci-fresh
```

Use `make ci` while iterating in the existing project environment without
dependency reconciliation. Use `make ci-fresh` before handoff or opening a
pull request.

For package metadata or distribution-content changes, also follow the package
checks in [Development](docs/development.md).

## Git Workflow

Maintainer development branches remain local by default. Maintainers use a
short `feature/*`, `fix/*`, `docs/*`, or `release/*` branch, keep commits
focused, and follow the approval boundaries in [Releasing](docs/releasing.md)
before any public repository or package transition.

External contributors push branches to their own forks and intentionally open
public pull requests against LocalQL. Contributors do not need to install the
maintainer clone's remote settings or local release guardrails; use a short-lived
branch and include the checks and evidence relevant to the change.

Use conventional commit-style subjects, such as `docs: update terminal menu
guide` or `fix: restore recalled TUI result export`. Keep each commit focused
on one behavior or documentation change.

## Pull Requests

Keep pull requests focused. Include tests or docs updates when behavior changes.
Do not mix unrelated cleanup into a feature or bug fix.

## Conduct And Security

Follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report sensitive
vulnerabilities through the path in [Security](SECURITY.md), not public issues.
