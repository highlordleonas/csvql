# LocalQL

[![CI](https://github.com/highlordleonas/csvql/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/highlordleonas/csvql/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/localql.svg)](https://pypi.org/project/localql/)
[![Python](https://img.shields.io/pypi/pyversions/localql.svg)](https://pypi.org/project/localql/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/highlordleonas/csvql/blob/main/LICENSE)

LocalQL is a DuckDB-powered tool for querying local CSV files with SQL. Install
the `localql` package to use the `csvql` command, organize repeatable work in a
`.csvql.yml` project catalog, export results, and optionally work in a terminal
menu.

![LocalQL: Query local CSVs with SQL](https://raw.githubusercontent.com/highlordleonas/csvql/main/docs/assets/localql-social-preview.jpg)

## Contents

- [Install and first query](#install-and-first-query)
- [Optional terminal menu](#optional-terminal-menu)
- [Compatibility and safety](#compatibility-and-safety)
- [Core workflows](#core-workflows)
- [Get help and stay current](#get-help-and-stay-current)

## Install and first query

Install the core command in your selected Python environment:

```console
python -m pip install localql
csvql --version
```

To try a query, create a small CSV in the directory where you are working:

```console
python -c "from pathlib import Path; Path('orders.csv').write_text('order_id,status\nORD-1,paid\nORD-2,pending\nORD-3,paid\n', encoding='utf-8')"
csvql query orders.csv "SELECT * FROM orders LIMIT 5"
```

The file name becomes the SQL table name, so `orders.csv` is available as
`orders`. A successful command prints a table with the CSV rows. See
[Getting started](https://github.com/highlordleonas/csvql/blob/main/docs/getting-started.md)
for project catalogs, saved SQL, and exports.

![Terminal screenshot of a LocalQL query over a CSV file](https://raw.githubusercontent.com/highlordleonas/csvql/main/docs/assets/localql-terminal-query.svg)

## Optional terminal menu

The core CLI needs only `localql`. Install the optional Textual-based terminal
menu when you want a source list, SQL editor, results, and history in one
terminal application:

```console
python -m pip install "localql[tui]"
csvql menu orders.csv
```

All core commands remain available without the extra. See the
[Terminal menu guide](https://github.com/highlordleonas/csvql/blob/main/docs/tui-guide.md)
for keys and source-management actions.

![Terminal screenshot of the LocalQL TUI workbench with sources, SQL, history, and results](https://raw.githubusercontent.com/highlordleonas/csvql/main/docs/assets/localql-tui-workbench.svg)

## Compatibility and safety

LocalQL supports Python 3.11 through 3.14 on macOS, Linux, and Windows.

LocalQL treats user-authored SQL as trusted local DuckDB SQL. It does not
sandbox DuckDB or restrict filesystem access. Run only SQL you trust.

## Core workflows

| When you want to… | Start here |
| --- | --- |
| Query a CSV or join named tables | [CLI reference](https://github.com/highlordleonas/csvql/blob/main/docs/cli-reference.md#query-csv-files) |
| Reuse a project catalog and saved SQL | [Project catalogs](https://github.com/highlordleonas/csvql/blob/main/docs/cli-reference.md#project-catalogs) |
| Inspect, sample, or profile a source | [Inspect, sample, and profile](https://github.com/highlordleonas/csvql/blob/main/docs/cli-reference.md#inspect-sample-and-profile) |
| Export a result or reuse it as a CSV source | [Save and reuse results](https://github.com/highlordleonas/csvql/blob/main/docs/cli-reference.md#save-and-reuse-results) |
| Check configured data-quality rules | [Data-quality checks](https://github.com/highlordleonas/csvql/blob/main/docs/cli-reference.md#data-quality-checks) |

DuckDB executes SQL; LocalQL manages local CSV table aliases, project
configuration, output, and explicit exports.

## Get help and stay current

- [Getting started](https://github.com/highlordleonas/csvql/blob/main/docs/getting-started.md)
- [CLI reference](https://github.com/highlordleonas/csvql/blob/main/docs/cli-reference.md)
- [Troubleshooting](https://github.com/highlordleonas/csvql/blob/main/docs/troubleshooting.md)
- [FAQ](https://github.com/highlordleonas/csvql/blob/main/docs/faq.md)
- [Support](https://github.com/highlordleonas/csvql/blob/main/SUPPORT.md)
- [Security](https://github.com/highlordleonas/csvql/blob/main/SECURITY.md)
- [Changelog](https://github.com/highlordleonas/csvql/blob/main/CHANGELOG.md)
- [v1 release notes](https://github.com/highlordleonas/csvql/blob/main/docs/release-notes/v1.md)
- [Contributing](https://github.com/highlordleonas/csvql/blob/main/CONTRIBUTING.md)
- [Roadmap](https://github.com/highlordleonas/csvql/blob/main/docs/ROADMAP.md)
