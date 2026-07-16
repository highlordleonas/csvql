# Contributing to LocalQL

Thanks for helping improve LocalQL. Focused bug reports, documentation fixes,
small examples, usability improvements, and tests for documented behavior are
all useful contributions.

## Before you start

Describe the problem and who it affects. Keep a change focused on local CSV
workflows, DuckDB SQL, the `csvql` command, the optional terminal menu, exports,
project catalogs, or documentation. Explain any compatibility impact, including
changes to command output, `.csvql.yml`, saved SQL, or supported Python versions.

Do not include sensitive details in a public issue. Use the reporting route in
[Security](SECURITY.md) for a potential vulnerability.

## Work from a source checkout

LocalQL uses `uv` for its contributor environment. From a source checkout:

```bash
uv sync --all-extras --frozen
uv run --all-extras csvql --help
```

## Validate your change

Run the checks that cover your change before opening a pull request:

```bash
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

Update documentation when behavior, commands, installation, compatibility, or
user-visible output changes. Add a screenshot when it makes a CLI or terminal
menu change easier to understand.

For package metadata or distribution-content work, follow the package checks in
[Development](docs/development.md).

## Pull requests

Use a concise title that describes the user-facing change. In the pull request,
summarize the user impact, scope, compatibility considerations, validation,
documentation updates, and screenshots when relevant. Keep unrelated cleanup in
a separate pull request.

## Community

Follow the [Code of Conduct](CODE_OF_CONDUCT.md). For normal bugs, questions,
and documentation problems, start with [Support](SUPPORT.md).
