# LocalQL

[![CI](https://github.com/highlordleonas/csvql/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/highlordleonas/csvql/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/localql.svg)](https://pypi.org/project/localql/)
[![Python](https://img.shields.io/pypi/pyversions/localql.svg)](https://pypi.org/project/localql/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/highlordleonas/csvql/blob/main/LICENSE)

LocalQL is a lightweight DuckDB-powered tool for querying local CSV files with
SQL. It installs the `csvql` command and provides named tables, saved SQL,
readable output, exports, and an optional terminal menu.

![LocalQL: Query local CSVs with SQL](https://raw.githubusercontent.com/highlordleonas/csvql/main/docs/assets/localql-social-preview.jpg)

## Choose your workflow

| You want to… | Start with |
| --- | --- |
| Query, inspect, profile, check, or export local CSV data | The `csvql` CLI |
| Explore sources and results interactively in a terminal | The optional `csvql menu` workbench |
| Embed project-backed queries in Python | `CSVQLSession` |
| Produce stable automation output | `--output json` and the JSON contract |

DuckDB executes your SQL; LocalQL manages the local workflow around CSV table
aliases, project configuration, output, and exports.

## Installation

Install the core command into your selected Python environment and confirm the
installed version:

```console
python -m pip install localql
csvql --version
```

For the optional terminal workbench, or for an isolated application
environment, use one of these alternatives:

```console
python -m pip install "localql[tui]"
uv tool install localql
uv tool install "localql[tui]"
```

`uv` must already be installed before you use `uv tool`. `pip` installs into
the selected Python environment; `uv tool` creates an isolated application
environment.

Whichever installer you use, its executable directory must be on `PATH`: the
selected Python environment's scripts directory for `pip`, or the uv tool
executable directory for `uv tool`. If `csvql --version` is not found:

- For `pip`, `python -m pip show localql` confirms the selected environment and
  `python -c "import sysconfig; print(sysconfig.get_path('scripts'))"` prints its
  scripts directory. Activate that environment or add the printed directory to
  `PATH`.
- For `uv tool`, `uv tool dir --bin` prints the executable directory and
  `uv tool update-shell` adds it to `PATH`. Open a new shell afterward.

See [Troubleshooting](https://github.com/highlordleonas/csvql/blob/main/docs/troubleshooting.md)
for more installation diagnostics.

## 60-second quickstart

Create a small CSV in your current directory, then query it with the installed
`csvql` command. These two lines work in Bash-compatible shells and PowerShell:

```console
python -c "from pathlib import Path; Path('orders.csv').write_text('order_id,status\nORD-1,paid\nORD-2,pending\nORD-3,paid\n', encoding='utf-8')"
csvql query orders.csv "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status ORDER BY status" --output json
```

The result reports two `paid` source rows, one `pending` source row, and two
grouped result rows. Timing fields may vary and are not part of this expected
result.

For a complete walkthrough of projects, saved SQL, exports, and result reuse,
see [Getting started](https://github.com/highlordleonas/csvql/blob/main/docs/getting-started.md).

## Terminal workbench

The optional `csvql menu` workbench provides sources, a SQL editor, results,
history, and explicit export actions in the terminal:

```console
csvql menu
csvql menu /path/to/orders.csv
```

![Terminal screenshot of the LocalQL TUI workbench with sources, SQL, history, and results](https://raw.githubusercontent.com/highlordleonas/csvql/main/docs/assets/localql-tui-workbench.svg)

The terminal workbench is optional; all core commands work without it. See the
[Terminal menu guide](https://github.com/highlordleonas/csvql/blob/main/docs/tui-guide.md)
for keys, source actions, history, and result handling.

## Compatibility and safety

LocalQL supports Python 3.11 through 3.14. The v1 CLI, Python, project catalog,
JSON, exit-code, and export contracts remain compatible in 1.0.2.

LocalQL treats user-authored SQL as trusted local DuckDB SQL. It does not
sandbox DuckDB or restrict filesystem access. Run only SQL you trust.

## What's new in 1.0.2

- The optional terminal workbench now uses secure temporary workspaces, atomic
  spill completion, conservative recovery, bounded previews, and sanitized
  storage or cleanup reporting for large results.
- Portable control-key fallbacks cover terminal workbench actions when a
  terminal or operating system intercepts function keys.

See the [v1 release notes](https://github.com/highlordleonas/csvql/blob/main/docs/release-notes/v1.md)
and [changelog](https://github.com/highlordleonas/csvql/blob/main/CHANGELOG.md)
for details.

## Documentation

### Use LocalQL

- [Getting started](https://github.com/highlordleonas/csvql/blob/main/docs/getting-started.md)
- [CLI reference](https://github.com/highlordleonas/csvql/blob/main/docs/cli-reference.md)
- [Terminal menu guide](https://github.com/highlordleonas/csvql/blob/main/docs/tui-guide.md)
- [Troubleshooting](https://github.com/highlordleonas/csvql/blob/main/docs/troubleshooting.md)
- [FAQ](https://github.com/highlordleonas/csvql/blob/main/docs/faq.md)
- [SaaS revenue example](https://github.com/highlordleonas/csvql/blob/main/examples/saas_revenue/README.md)

### Reference

- [JSON output reference](https://github.com/highlordleonas/csvql/blob/main/docs/json-contracts.md)
- [Architecture](https://github.com/highlordleonas/csvql/blob/main/docs/ARCHITECTURE.md)
- [v1 release notes](https://github.com/highlordleonas/csvql/blob/main/docs/release-notes/v1.md)
- [Changelog](https://github.com/highlordleonas/csvql/blob/main/CHANGELOG.md)

### Project and support

- [Roadmap](https://github.com/highlordleonas/csvql/blob/main/docs/ROADMAP.md)
- [Contributing](https://github.com/highlordleonas/csvql/blob/main/CONTRIBUTING.md)
- [Security](https://github.com/highlordleonas/csvql/blob/main/SECURITY.md)
- [Support](https://github.com/highlordleonas/csvql/blob/main/SUPPORT.md)
- [Code of Conduct](https://github.com/highlordleonas/csvql/blob/main/CODE_OF_CONDUCT.md)
