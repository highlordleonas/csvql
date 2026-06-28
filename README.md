# CSVQL

CSVQL is a lightweight DuckDB-powered CLI for querying local CSV files like SQL tables.

```bash
csvql query \
  --table customers=examples/sales/data/customers.csv \
  --table orders=examples/sales/data/orders.csv \
  "SELECT
      c.email,
      COUNT(o.order_id) AS orders,
      SUM(o.total_amount) AS lifetime_value
   FROM customers c
   JOIN orders o USING (customer_id)
   GROUP BY c.email
   ORDER BY lifetime_value DESC"
```

CSVQL does not implement a SQL engine. DuckDB executes SQL; CSVQL owns the local workflow around table aliases, readable output, validation, and project catalog configuration.

## Status

This repository has the v0.1 query workflow, the first inspect/sample vertical, the v0.3 project catalog workflow, and the v0.4 saved-workflow surfaces implemented for local CLI use.

Implemented now:

- `csvql query --table name=path "SELECT ..."`
- `.csvql.yml` project catalog discovery
- `csvql init`
- `csvql add`
- `csvql tables`
- catalog-backed `csvql query "SELECT ... FROM alias"`
- `csvql inspect data/orders.csv --output json`
- `csvql sample data/orders.csv --limit 10`
- `csvql run queries/file.sql`
- `csvql export queries/file.sql --format csv|json|markdown --out path`
- catalog-backed `csvql inspect alias`
- catalog-backed `csvql sample alias`
- repeated `--table` mappings for joins
- single-file shortcut mode
- table and JSON stdout output
- DuckDB in-memory execution
- focused tests, Ruff, mypy, and GitHub Actions scaffolding

Planned later:

- profiling and data quality checks
- benchmarks and release workflow

## Install For Development

```bash
uv sync --all-extras
```

Run the CLI from the repo:

```bash
uv run csvql --help
```

## Query Examples

Query one CSV with the single-file shortcut. The table name is derived from the file stem, so `orders.csv` becomes `orders`.

```bash
uv run csvql query examples/sales/data/orders.csv \
  "SELECT status, COUNT(*) AS order_count
   FROM orders
   GROUP BY status
   ORDER BY status"
```

Query multiple CSV files:

```bash
uv run csvql query \
  --table customers=examples/sales/data/customers.csv \
  --table orders=examples/sales/data/orders.csv \
  "SELECT
      c.customer_id,
      c.email,
      COUNT(o.order_id) AS order_count,
      SUM(o.total_amount) AS revenue
   FROM customers c
   JOIN orders o USING (customer_id)
   GROUP BY c.customer_id, c.email
   ORDER BY revenue DESC"
```

Return JSON for automation:

```bash
uv run csvql query \
  --table orders=examples/sales/data/orders.csv \
  --output json \
  "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status"
```

## Project Catalog Examples

Initialize a local project catalog:

```bash
uv run csvql init
```

Register a table once:

```bash
uv run csvql add orders examples/sales/data/orders.csv
```

List registered tables as JSON:

```bash
uv run csvql tables --output json
```

Query a registered table by alias:

```bash
uv run csvql query "SELECT COUNT(*) AS order_count FROM orders"
```

For one invocation, explicit `--table` mappings still work and override catalog aliases with the same name.

```bash
uv run csvql query \
  --table orders=examples/sales/data/orders.csv \
  "SELECT COUNT(*) AS order_count FROM orders"
```

## Saved Workflow Examples

Run SQL from a file using catalog aliases:

```bash
cd examples/sales
uv run csvql run queries/revenue_by_month.sql --output json
```

Inspect and sample registered catalog aliases:

```bash
uv run csvql inspect orders --output json
uv run csvql sample orders --limit 5 --output json
```

Export SQL-file results:

```bash
mkdir -p out

uv run csvql export queries/revenue_by_month.sql \
  --format csv \
  --out out/revenue.csv

uv run csvql export queries/revenue_by_month.sql \
  --format json \
  --out out/revenue.json

uv run csvql export queries/revenue_by_month.sql \
  --format markdown \
  --out out/revenue.md
```

`csvql export` refuses to overwrite an existing output file unless `--force` is passed. The output directory must already exist.

## Inspect And Sample Examples

Inspect a CSV without running user-authored SQL:

```bash
uv run csvql inspect examples/sales/data/orders.csv --output json
```

Calculate an exact row count when you explicitly want a full scan:

```bash
uv run csvql inspect examples/sales/data/orders.csv --exact --output json
```

Sample rows from a CSV:

```bash
uv run csvql sample examples/sales/data/orders.csv --limit 5
```

## Development Checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

Or run the combined local gate:

```bash
make ci
```

## Security Model

CSVQL is currently a local developer tool for trusted SQL. DuckDB executes the SQL, and CSVQL does not restrict DuckDB capabilities or filesystem access. Do not run untrusted SQL files or input.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Codex capability review](docs/CODEX_CAPABILITY_REVIEW.md)
- [v1 Quality Spine design](docs/superpowers/specs/2026-06-26-csvql-v1-quality-spine-design.md)
