# CLI Reference

`csvql` is the LocalQL command-line interface. Commands write readable tables
by default and support JSON where noted. For a guided first use, start with
[Getting started](getting-started.md).

## Contents

- [Query local sources](#query-local-sources)
- [Source provider options](#source-provider-options)
- [Project catalogs](#project-catalogs)
- [Run saved SQL](#run-saved-sql)
- [Result-size behavior](#result-size-behavior)
- [Save and reuse results](#save-and-reuse-results)
- [Inspect, sample, and profile](#inspect-sample-and-profile)
- [Data-quality checks](#data-quality-checks)
- [Project health](#project-health)
- [Python API](#python-api)

## Query local sources

Query a recognized local file directly. The file name becomes the table name:

```bash
csvql query data/orders.csv "SELECT * FROM orders LIMIT 10"
csvql query data/orders.parquet "SELECT COUNT(*) FROM orders"
csvql query data/events.ndjson "SELECT * FROM events LIMIT 10"
```

The recognized extensions are `.csv`, `.parquet`/`.parq`, `.json`,
`.ndjson`/`.jsonl`, and `.xlsx`. Use `--type` for an explicit single-source
override or an extensionless source:

```bash
csvql query data/order_facts "SELECT COUNT(*) FROM order_facts" \
  --type parquet \
  --option partitioning=hive
```

For multiple provider-neutral sources, repeat `--source`, and associate types
and options by alias:

```bash
csvql query \
  --source customers=data/customers.parquet \
  --source events=data/events.ndjson \
  --source-type events=ndjson \
  --source-option events.sample_size=10000 \
  "SELECT c.segment, COUNT(*) AS event_count
   FROM customers AS c
   JOIN events AS e USING (customer_id)
   GROUP BY c.segment"
```

Every `--source-type NAME=TYPE` and `--source-option NAME.KEY=VALUE` must name
exactly one `--source`. `--table NAME=PATH` remains the explicit-CSV
compatibility syntax and may be repeated for CSV joins:

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

Selection is deterministic: explicit type, then recognized extension. For an
extensionless file or directory, LocalQL may perform bounded, read-only
identification to report candidates, but it never selects one heuristically.
Choose a type explicitly to continue.

Add `--output json` when another program will consume the result. See the
[JSON output reference](json-contracts.md) for the response shapes.

## Source provider options

Provider options are source intent, not query-engine settings. The provider
validates them before binding a relational source. Defaults shown here are
applied during source resolution; version 2 catalogs and the terminal menu save
only the options you explicitly enter.

| Provider | Option | Accepted value | Default | Effect |
| --- | --- | --- | --- | --- |
| CSV | — | No provider options | — | CSV dialect detection remains automatic. |
| Parquet | `partitioning` | `none` or `hive` | `none` | Enables explicit Hive partition interpretation for a file or explicitly typed directory dataset. |
| Parquet | `union_by_name` | Boolean | `false` | Aligns columns by name across dataset members. When false, member schemas must match. |
| JSON and NDJSON | `sample_size` | Positive integer | `20480` | Bounds schema-inference rows when no explicit schema is supplied. |
| JSON and NDJSON | `maximum_depth` | Positive integer | `10` | Bounds nested schema inference when no explicit schema is supplied. |
| JSON and NDJSON | `schema` | Object mapping column names to scalar types | — | Replaces schema inference with an explicit column schema. |
| JSON and NDJSON | `record_path` | Fixed lookup path beginning with `$` | — | Selects an array of object records and requires `schema`. |
| Excel | `sheet` | Exact, non-empty worksheet name | First worksheet in workbook order | Selects one worksheet. |
| Excel | `range` | Finite A1 rectangle such as `A1:F500` | Worksheet dimension | Selects a bounded rectangle; supply it explicitly when the workbook has no usable dimension. |
| Excel | `header` | Boolean | `true` | Treats the first selected row as column names. |
| Excel | `stop_at_empty` | Boolean | `false` | Stops reading at the first empty row when enabled. |
| Excel | `type_mode` | `text` or `infer` | `text` | Keeps cells as text by default; `infer` asks DuckDB to infer column types. |

JSON `schema` values use a bounded scalar grammar: Boolean; signed and unsigned
integer types; `REAL`/`FLOAT`; `DOUBLE`; `VARCHAR`/`TEXT`; `DATE`; `TIME`;
`TIMESTAMP`; `TIMESTAMPTZ`; `UUID`; `JSON`; and `DECIMAL(p,s)` with precision
up to 38. Column names must be simple identifiers. A `record_path` may contain
only fixed key lookups and non-negative array indexes, such as `$.events[0]`.
It must select an array, requires `schema`, and cannot be combined with
explicit `sample_size` or `maximum_depth` inference options.

Use the same option contract on every entry surface:

- single-source CLI commands and `csvql add`: repeat `--option KEY=VALUE`
- multi-source CLI commands: repeat `--source-option NAME.KEY=VALUE`
- terminal menu: enter space-separated `key=value` tokens in Add source
- version 2 catalog: use native YAML values under `source.options`
- Python API: pass native values in `SourceDefinition(..., options={...})`

CLI and terminal-menu booleans are lowercase `true` or `false`. Numeric values
are parsed as numbers, while JSON objects and arrays are parsed as JSON. Quote a
JSON object so the shell preserves it:

```bash
csvql sample data/events.json \
  --type json \
  --option 'schema={"event_id":"BIGINT","event_type":"VARCHAR"}' \
  --limit 10
```

Excel additionally requires the DuckDB `excel` extension to be explicitly
provisioned before LocalQL starts. Follow
[Provision Excel support](getting-started.md#provision-excel-support); LocalQL
never installs an extension while resolving, querying, or exporting.

## Project catalogs

Initialize a project once, then add its sources:

```bash
csvql init
csvql add customers data/customers.csv
csvql add orders data/orders.parquet --type parquet
csvql add events data/events.ndjson --type ndjson --option sample_size=10000
csvql tables
```

From that project directory, query the saved aliases without repeating file
paths:

```bash
csvql query "SELECT COUNT(*) AS order_count FROM orders"
```

New catalogs use the normalized version 2 `source.type`, `source.locator`, and
optional `source.options` shape. Existing version 1 catalogs remain strict,
CSV-only compatibility inputs; no implicit migration occurs.

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

## Result-size behavior

Interactive table output from `csvql query` and `csvql run` retains up to
1,000 rows by default and no more than a 16 MiB encoded preview payload. Use
`--limit N` to choose a different row bound. The bound applies only to table
output, and LocalQL reports when more rows exist beyond the retained preview.

Query/run JSON output remains complete and does not accept `--limit`. The
project-backed Python query API also remains complete. These compatibility
surfaces still materialize every returned row, so use them deliberately for
large results.

`csvql export` streams its result to the requested file, so exports remain
complete and do not inherit the interactive table preview bound. Binary
Parquet and Excel output is available through file export, not query/run
`--output`.

## Save and reuse results

Export saved SQL to a file you choose:

```bash
csvql export queries/revenue_health.sql \
  --format parquet \
  --out exports/revenue_health.parquet
```

LocalQL refuses to overwrite an existing output unless you add `--force`.
The export contains the complete query result even when the same SQL would
produce a bounded interactive table preview.

Choose the result contract that fits the next consumer:

| Format | Contract and intended use |
| --- | --- |
| `csv` | Header plus rows for broad interchange. String cells that begin like spreadsheet formulas are neutralized. |
| `json` | The LocalQL result envelope: `columns`, `rows`, `row_count`, and `elapsed_ms`. Use it for LocalQL automation contracts. |
| `ndjson` | One JSON object per row with no envelope. Use it as a stream or a directly queryable NDJSON source. Non-JSON-native values are serialized as strings. |
| `parquet` | Typed columnar output. Use it for re-querying, cross-format pipelines, and preserving DuckDB logical types. |
| `excel` | An `.xlsx` workbook with a header row. It requires the provisioned DuckDB `excel` extension and follows the extension's spreadsheet conversions; use Parquet when exact logical-type fidelity matters. |
| `markdown` | A complete escaped Markdown table for documentation. |
| `text` | A complete terminal-style table for human-readable files. |

The format is explicit and does not depend on the output suffix:

```bash
csvql export queries/revenue_health.sql --format ndjson --out exports/revenue.ndjson
csvql export queries/revenue_health.sql --format parquet --out exports/revenue.parquet
csvql export queries/revenue_health.sql --format excel --out exports/revenue.xlsx
```

Excel output uses the same explicit provisioning requirement as Excel input.
LocalQL checks and loads an already-installed extension but never downloads or
installs it during export.

CSV, NDJSON, and Parquet exports can be added to the catalog or supplied as
intentional sources. The legacy `--table` syntax is CSV-only; use normalized
source intent for the other formats:

```bash
csvql add revenue_health_result exports/revenue_health.csv
csvql add revenue_health_parquet exports/revenue_health.parquet --type parquet
csvql query "SELECT * FROM revenue_health_result LIMIT 10"
```

The terminal menu can also save its active result to
`.csvql/results/{alias}.csv`. See [Save a result as a source](tui-guide.md#save-a-result-as-a-source).

For measured end-to-end evidence across all five source providers and the
NDJSON, Parquet, and Excel outputs, see the
[LocalQL v1.2.0 benchmark snapshot](benchmarks.md).

## Inspect, sample, and profile

Inspect a file or catalog alias to see its columns and source metadata. CSV
inspection also reports its detected dialect. Add `--exact` only when you want
a full scan for an exact row count:

```bash
csvql inspect data/orders.csv
csvql inspect data/orders.parquet --type parquet
csvql inspect orders --exact --output json
```

Sample a file or catalog alias without writing a query. `inspect`, `sample`,
and `profile` all accept repeatable `--option KEY=VALUE` values:

```bash
csvql sample data/orders.csv --limit 10
csvql sample data/events.json --type json --option 'record_path=$.events' --limit 10
```

Profile a source or catalog alias:

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

output_path = session.export(
    "queries/revenue_health.sql",
    "exports/revenue_health.parquet",
    format="parquet",
)
print(output_path)
```

The API uses the same project catalog as the CLI. For an intentional one-off
source, pass the same provider options with `SourceDefinition`:

```python
from csvql import CSVQLSession, SourceDefinition

session = CSVQLSession.from_config(".")
result = session.query(
    "SELECT COUNT(*) AS order_count FROM orders",
    sources=(
        SourceDefinition(
            "orders",
            "data/orders.parquet",
            source_type="parquet",
            options={"partitioning": "none", "union_by_name": False},
        ),
    ),
)

print(result.rows)
```

The API is intentionally small; use DuckDB directly when you need a broader
Python API.
