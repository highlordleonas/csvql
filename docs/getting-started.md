# Getting Started

This walkthrough uses the local SaaS revenue example to show the core CSVQL
workflow: query one CSV, use a project catalog, run saved SQL, and export a
result. DuckDB executes SQL; CSVQL owns table aliases, project configuration,
output formatting, and predictable local error handling.

## Install

Install the package with the optional terminal menu:

```bash
pip install "localql[tui]"
```

From a source checkout, use the repo-local toolchain instead:

```bash
uv sync --all-extras
uv run csvql --help
```

The installable distribution is `localql`. The command, Python import package,
and project config file remain `csvql` and `.csvql.yml`.

## Query One CSV

Run this from the repository root:

```bash
uv run csvql query examples/saas_revenue/data/revenue_movements.csv \
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
uv run csvql tables
```

Query a registered table without passing file paths:

```bash
uv run csvql query "SELECT COUNT(*) AS customer_count FROM customers"
```

Add or replace a table in your own project with:

```bash
uv run csvql add customers data/customers.csv --replace
```

The project path also supports joined SQL and configured checks:

![Terminal screenshot of a SaaS project query and passing configured checks](assets/localql-terminal-project.svg)

## Run Saved SQL

Keep repeatable analysis in SQL files:

```bash
uv run csvql run queries/revenue_health.sql --output json
```

The SaaS example returns one row per month with starting MRR, new MRR,
expansion, contraction, churn, reactivation, ending MRR, ending ARR, and net
revenue retention.

## Export Results

Write the saved analysis to a local file:

```bash
uv run csvql export queries/revenue_health.sql \
  --format markdown \
  --out output/revenue-health.md \
  --force
```

Exports are explicit. CSVQL does not write hidden cache or automatic
materialized state.

## Reuse A Result As A CSV Source

You can turn a result into another CSV source:

```bash
mkdir -p .csvql/results
uv run csvql export queries/revenue_health.sql \
  --format csv \
  --out .csvql/results/revenue_health.csv \
  --force

uv run csvql query \
  --table revenue_health_result=.csvql/results/revenue_health.csv \
  "SELECT COUNT(*) AS result_rows FROM revenue_health_result"
```

This is normal CSV reuse. The project catalog stores table paths; it does not
store typed derived-source metadata.

## Open The Terminal Menu

The optional TUI is useful when you want to iterate locally without leaving the
terminal:

```bash
uv run --all-extras csvql menu data/revenue_movements.csv
```

![Terminal screenshot of the TUI workbench after running the SaaS revenue movement query](assets/localql-tui-workbench.svg)

Use `F4` or `Ctrl+Enter` to run SQL, `F6` for sources, `F5` for results, `F8`
for history, and `F9` to quit. See [Terminal menu guide](tui-guide.md) for the
full workflow.

## Safety Boundary

CSVQL is for trusted local SQL. DuckDB executes the SQL and can access local
files according to DuckDB behavior. Do not run untrusted SQL files or pasted SQL
inside CSVQL.
