# Getting Started

Start with the installed LocalQL command from any working directory. This guide
also covers the package lifecycle, then uses the repository's SaaS revenue
project to demonstrate catalogs, saved SQL, exports, and result reuse. DuckDB
executes SQL; LocalQL handles table aliases, project configuration, output
formatting, and predictable local error handling.

## Install and manage LocalQL

The installable distribution is `localql`. The command, Python import package,
and project config file remain `csvql` and `.csvql.yml`.

| Lifecycle | pip environment | isolated uv tool |
| --- | --- | --- |
| Core install | `python -m pip install localql` | `uv tool install localql` |
| TUI install | `python -m pip install "localql[tui]"` | `uv tool install "localql[tui]"` |
| Upgrade core | `python -m pip install --upgrade localql` | `uv tool upgrade localql` |
| Upgrade TUI | `python -m pip install --upgrade "localql[tui]"` | `uv tool upgrade localql` |
| Uninstall | `python -m pip uninstall localql` | `uv tool uninstall localql` |

`pip` installs into the selected Python environment. `uv tool` creates an
isolated application environment, and `uv` must already be installed before
you use it.

An existing uv tool keeps the extras selected when it was installed. To change
between core and TUI mode, uninstall LocalQL and reinstall it with the desired
package expression.

Confirm which installed version your shell resolves:

```console
csvql --version
```

## Develop from a source checkout

From an existing LocalQL source checkout, use the frozen repo environment for
development commands:

```bash
uv sync --all-extras --frozen
uv run --all-extras csvql --help
```

The examples below use the installed `csvql` command from the repository root.
When developing against source instead, run the same commands through the
repo-local environment with `uv run --all-extras`.

## Query One CSV

Run this from the repository root you entered above:

```bash
csvql query examples/saas_revenue/data/revenue_movements.csv \
  "SELECT movement_type, SUM(mrr_delta) AS net_mrr_change
   FROM revenue_movements
   GROUP BY movement_type
   ORDER BY movement_type"
```

The table alias comes from the file stem, so `revenue_movements.csv` becomes
`revenue_movements`.

![Terminal screenshot of a movement-type revenue query](assets/localql-terminal-query.svg)

## Use A Project Catalog

The example project already includes `.csvql.yml` with registered tables:

```bash
cd examples/saas_revenue
csvql tables
```

Query a registered table without passing file paths:

```bash
csvql query "SELECT COUNT(*) AS customer_count FROM customers"
```

Add or replace a table in your own project with:

```bash
csvql add customers data/customers.csv --replace
```

The project path also supports joined SQL and configured checks:

![Terminal screenshot of a SaaS project query and passing configured checks](assets/localql-terminal-project.svg)

## Run Saved SQL

Keep repeatable analysis in SQL files:

```bash
csvql run queries/revenue_health.sql --output json
```

The SaaS example returns one row per month with starting MRR, new MRR,
expansion, contraction, churn, reactivation, ending MRR, ending ARR, and net
revenue retention.

## Export Results

Write the saved analysis to a local file:

```bash
mkdir -p output
csvql export queries/revenue_health.sql \
  --format markdown \
  --out output/revenue-health.md \
  --force
```

LocalQL writes an export only when you run `csvql export` or choose an export
action in the terminal menu. It does not create a hidden result cache.

## Reuse A Result As A CSV Source

You can turn a result into another CSV source:

```bash
mkdir -p .csvql/results
csvql export queries/revenue_health.sql \
  --format csv \
  --out .csvql/results/revenue_health.csv \
  --force

csvql query \
  --table revenue_health_result=.csvql/results/revenue_health.csv \
  "SELECT COUNT(*) AS result_rows FROM revenue_health_result"
```

This is normal CSV reuse. The project catalog stores table names and file paths;
it does not label generated CSVs differently from other CSV files.

## Open The Terminal Menu

The optional TUI is useful when you want to iterate locally without leaving the
terminal:

```bash
csvql menu data/revenue_movements.csv
```

![Terminal screenshot of the TUI workbench after running the SaaS revenue movement query](assets/localql-tui-workbench.svg)

Use `F4` or `Ctrl+R` to run selected SQL or the current statement, `F12` or
`Ctrl+B` to run the full editor buffer, `F3` or `Ctrl+O` to choose CSV files,
`F6` or `Ctrl+Up` for sources, `F5` for results, `F8` for history, and `F9` or
`q` outside text entry to quit. See [Terminal menu guide](tui-guide.md) for the
full workflow.

## SQL Safety

CSVQL is for trusted local SQL. DuckDB executes the SQL and can access local
files according to DuckDB behavior. Do not run untrusted SQL files or pasted SQL
inside CSVQL.
