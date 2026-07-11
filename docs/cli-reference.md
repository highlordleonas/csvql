# CLI Reference

`csvql` is the LocalQL command-line interface. Commands write readable tables
by default and support JSON where noted. For a guided first use, start with
[Getting started](getting-started.md).

## Contents

- [Query CSV files](#query-csv-files)
- [Project catalogs](#project-catalogs)
- [Run saved SQL](#run-saved-sql)
- [Save and reuse results](#save-and-reuse-results)
- [Inspect, sample, and profile](#inspect-sample-and-profile)
- [Data-quality checks](#data-quality-checks)
- [Project health](#project-health)
- [Python API](#python-api)

## Query CSV files

Query a CSV directly. The file name becomes the table name:

```bash
csvql query data/orders.csv "SELECT * FROM orders LIMIT 10"
```

Use `--table` to name one or more CSV files explicitly, including joins:

```bash
csvql query \
  --table customers=data/customers.csv \
  --table orders=data/orders.csv \
  "SELECT c.segment, COUNT(*) AS order_count
   FROM customers AS c
   JOIN orders AS o USING (customer_id)
   GROUP BY c.segment
   ORDER BY order_count DESC"
```

Add `--output json` when another program will consume the result. See the
[JSON output reference](json-contracts.md) for the response shapes.

## Project catalogs

Initialize a project once, then add its sources:

```bash
csvql init
csvql add customers data/customers.csv
csvql add orders data/orders.csv
csvql tables
```

From that project directory, query the saved aliases without repeating file
paths:

```bash
csvql query "SELECT COUNT(*) AS order_count FROM orders"
```

LocalQL stores the catalog in `.csvql.yml`. Read [Getting started](getting-started.md#use-a-project-catalog)
for the expected layout and the [FAQ](faq.md) for the distribution-name and
command-name distinction.

## Run saved SQL

Keep repeatable queries in a `.sql` file and run them from the project:

```bash
csvql run queries/revenue_health.sql
csvql run queries/revenue_health.sql --output json
```

The saved SQL uses the aliases defined by the project catalog.

## Save and reuse results

Export saved SQL to a file you choose:

```bash
csvql export queries/revenue_health.sql \
  --format csv \
  --out exports/revenue_health.csv
```

LocalQL refuses to overwrite an existing output unless you add `--force`.

An exported result is an ordinary CSV file. Add it to the catalog or pass it
with `--table` when you want to query it again:

```bash
csvql add revenue_health_result exports/revenue_health.csv
csvql query "SELECT * FROM revenue_health_result LIMIT 10"
```

The terminal menu can also save its active result to
`.csvql/results/{alias}.csv`. See [Save a result as a source](tui-guide.md#save-a-result-as-a-source).

## Inspect, sample, and profile

Inspect a file or catalog alias to see its columns and detected dialect. Add
`--exact` only when you want a full scan for an exact row count:

```bash
csvql inspect data/orders.csv
csvql inspect orders --exact --output json
```

Sample a file or catalog alias without writing a query:

```bash
csvql sample data/orders.csv --limit 10
```

Profile a CSV or catalog alias:

```bash
csvql profile data/orders.csv
csvql profile orders --output json
```

`profile` reports row and column counts, null and distinct counts, values at
the observed bounds, and duplicate-row counts. It reads the source to calculate
those values.

## Data-quality checks

Define checks in `.csvql.yml`, then run all checks or the checks for one table:

```bash
csvql check
csvql check orders
csvql check orders --show-failures
```

`csvql check` exits with status `11` when configured checks fail. Use
`--show-failures` for a bounded sample that helps locate the problem.

## Project health

Check whether the discovered project catalog and configured sources are usable:

```bash
csvql doctor
csvql doctor --output json
```

`doctor` exits with status `12` for concrete project-health failures, such as
invalid configuration, missing sources, or checks that refer to missing columns.

## Python API

LocalQL also provides a small project-backed Python API:

```python
from csvql import CSVQLSession

session = CSVQLSession.from_config(".")
result = session.query("SELECT COUNT(*) AS order_count FROM orders")

print(result.rows)
```

The API uses the same project catalog as the CLI. It is intentionally small;
use DuckDB directly when you need a broader Python API.
