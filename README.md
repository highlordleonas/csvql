# LocalQL

[![CI](https://github.com/highlordleonas/csvql/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/highlordleonas/csvql/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/localql.svg)](https://pypi.org/project/localql/)
[![Python](https://img.shields.io/pypi/pyversions/localql.svg)](https://pypi.org/project/localql/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/highlordleonas/csvql/blob/main/LICENSE)

LocalQL is a lightweight DuckDB-powered tool for querying local CSV files with
SQL. It installs the `csvql` command and provides named tables, saved SQL,
readable output, exports, and an optional terminal menu.

![LocalQL: Query local CSVs with SQL](https://raw.githubusercontent.com/highlordleonas/csvql/main/docs/assets/localql-social-preview.jpg)

## Contents

- [Quickstart](#quickstart)
- [Core workflows](#core-workflows)
- [Terminal menu](#terminal-menu)
- [Safety](#safety)
- [Documentation](#documentation)

## Quickstart

Install LocalQL:

```bash
pip install localql
```

The query below uses the example data in this repository. From another
directory, replace the path with one of your own CSV files.

Query the example CSV:

```bash
csvql query examples/saas_revenue/data/revenue_movements.csv \
  "SELECT movement_type, SUM(mrr_delta) AS net_mrr_change
   FROM revenue_movements
   GROUP BY movement_type
   ORDER BY movement_type"
```

![Terminal screenshot of a LocalQL query over the SaaS revenue example](https://raw.githubusercontent.com/highlordleonas/csvql/main/docs/assets/localql-terminal-query.svg)

For a complete copy-and-paste walkthrough, see
[Getting started](https://github.com/highlordleonas/csvql/blob/main/docs/getting-started.md).

## Core workflows

| When you want to… | Start here |
| --- | --- |
| Query a CSV or join named tables | [CLI reference](https://github.com/highlordleonas/csvql/blob/main/docs/cli-reference.md#query-csv-files) |
| Reuse a project catalog and saved SQL | [Project catalogs](https://github.com/highlordleonas/csvql/blob/main/docs/cli-reference.md#project-catalogs) |
| Inspect, sample, or profile a source | [Inspect, sample, and profile](https://github.com/highlordleonas/csvql/blob/main/docs/cli-reference.md#inspect-sample-and-profile) |
| Export a result or reuse it as a CSV source | [Save and reuse results](https://github.com/highlordleonas/csvql/blob/main/docs/cli-reference.md#save-and-reuse-results) |
| Check configured data-quality rules | [Data-quality checks](https://github.com/highlordleonas/csvql/blob/main/docs/cli-reference.md#data-quality-checks) |

CSVQL does not implement a SQL engine. DuckDB executes SQL; CSVQL manages the
local workflow around table aliases, project configuration, output, and exports.

## Terminal menu

The optional `csvql menu` workbench provides sources, a SQL editor, results,
history, and explicit export actions in the terminal:

```bash
pip install "localql[tui]"
csvql menu
csvql menu /path/to/orders.csv
```

![Terminal screenshot of the LocalQL TUI workbench with sources, SQL, history, and results](https://raw.githubusercontent.com/highlordleonas/csvql/main/docs/assets/localql-tui-workbench.svg)

The terminal menu is optional; all core commands also work without it. See the
[Terminal menu guide](https://github.com/highlordleonas/csvql/blob/main/docs/tui-guide.md)
for keys, source actions, history, and result handling.

## Safety

LocalQL treats user-authored SQL as trusted local DuckDB SQL. It does not
sandbox DuckDB or restrict filesystem access. Run only SQL you trust.

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
