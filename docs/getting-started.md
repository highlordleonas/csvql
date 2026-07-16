# Getting Started

This guide uses the installed `csvql` command. LocalQL is the package name;
`csvql` is the command, Python import package, and `.csvql.yml` configuration
namespace.

## Install LocalQL

Install the core CLI in the Python environment you use for local analysis:

```console
python -m pip install localql
csvql --version
```

If `csvql` is not found after installation, see
[Troubleshooting](troubleshooting.md#csvql-command-not-found).

## Query a CSV

Put a CSV in your working directory. For example, create `orders.csv` with a
header row and a few rows of data, then run:

```console
csvql query orders.csv "SELECT * FROM orders LIMIT 5"
```

The file stem becomes the table name: `orders.csv` is available as `orders`.
The command prints a result table. Use `--output json` when a script needs a
structured result.

![Terminal screenshot of a LocalQL query over a CSV file](assets/localql-terminal-query.svg)

## Use a project catalog

For repeated work in a directory, initialize a catalog and register a friendly
table name:

```console
csvql init
csvql add orders data/orders.csv
csvql tables
csvql query "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status"
```

LocalQL stores the catalog in `.csvql.yml`. The catalog records table names and
CSV paths; it does not upload data or run queries automatically.

## Run saved SQL and export results

Keep a repeatable query in a file, then run or export it explicitly:

```console
csvql run queries/orders_by_status.sql --output json
csvql export queries/orders_by_status.sql --format csv --out orders_by_status.csv
```

Use `--force` only when you intend to replace an existing export.

## Use the optional terminal menu

After your first core query, install the optional terminal-menu extra when you
want an interactive source list, SQL editor, results, and history:

```console
python -m pip install "localql[tui]"
csvql menu orders.csv
```

The menu lets you add sources, write SQL, inspect results, and export a result
without changing the core CLI workflow. See the
[Terminal menu guide](tui-guide.md) for keys and source actions.

![Terminal screenshot of the LocalQL TUI workbench with sources, SQL, history, and results](assets/localql-tui-workbench.svg)

## Compatibility and SQL safety

LocalQL supports Python 3.11 through 3.14 on macOS, Linux, and Windows.

User-authored SQL is trusted local DuckDB SQL. LocalQL does not sandbox DuckDB
or restrict filesystem access, so run only SQL you trust.

## Next steps

- Use the [CLI reference](cli-reference.md) for command options and JSON output.
- Use [Troubleshooting](troubleshooting.md) when a command or project does not work as expected.
- Read the [FAQ](faq.md) for package naming, compatibility, and TUI questions.
- Visit [Support](../SUPPORT.md) for bugs, documentation issues, and focused feature requests.
