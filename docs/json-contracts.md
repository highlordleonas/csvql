# JSON Output Reference

LocalQL can return JSON from commands that produce tabular data or inspect a
project. This reference describes the stable fields and the values that vary by
machine or input. It is intended for scripts and integrations; use the normal
table output when you are working interactively.

## Contents

- [Stable fields and changing values](#stable-fields-and-changing-values)
- [Query, run, and JSON export](#query-run-and-json-export)
- [Inspect and sample](#inspect-and-sample)
- [Profile](#profile)
- [Checks and project health](#checks-and-project-health)
- [Tables](#tables)
- [Shared behavior](#shared-behavior)

## Stable fields and changing values

Field names, nesting, and when fields are omitted are documented behavior in
1.0.0. Some values change with the input file, computer, or run:

- `elapsed_ms` varies by run.
- Source paths, modification timestamps, and file sizes depend on the machine
  and file being inspected.
- Query rows and profile values depend on the source data.
- Values that are not native JSON types are serialized as strings.

Examples use placeholders for values that differ between computers.

## Query, run, and JSON export

These commands share one result shape:

- `csvql query --output json`
- `csvql run --output json`
- `csvql export --format json`

| Field | Meaning |
| --- | --- |
| `columns` | Ordered output-column names. |
| `rows` | Records keyed by column name. |
| `row_count` | Number of returned records. |
| `elapsed_ms` | Rounded elapsed time for the query. |

```json
{
  "columns": ["order_count"],
  "rows": [{"order_count": 2}],
  "row_count": 1,
  "elapsed_ms": 3.099
}
```

## Inspect and sample

`csvql inspect --output json` returns source metadata, detected CSV dialect,
columns, row-count metadata, and warnings.

```json
{
  "source": {
    "display_path": "data/orders.csv",
    "resolved_path": "<absolute-path>",
    "modified_at": "<modified-at>",
    "size_bytes": 64,
    "fingerprint": {
      "version": 1,
      "size_bytes": 64,
      "modified_at": "<modified-at>"
    }
  },
  "dialect": {
    "delimiter": ",",
    "encoding": "utf-8",
    "header": true,
    "quote": "\"",
    "escape": null
  },
  "columns": [{"name": "order_id", "duckdb_type": "VARCHAR"}],
  "row_count": {"mode": "not_counted", "exact": false, "value": null},
  "warnings": []
}
```

`csvql sample --output json` returns `source`, `limit`, `columns`, `rows`, and
`warnings`. `limit` is the requested maximum, not a promise that the source
contains that many rows.

```json
{
  "source": {
    "display_path": "data/orders.csv",
    "resolved_path": "<absolute-path>",
    "modified_at": "<modified-at>",
    "size_bytes": 64,
    "fingerprint": {
      "version": 1,
      "size_bytes": 64,
      "modified_at": "<modified-at>"
    }
  },
  "limit": 1,
  "columns": ["order_id", "status"],
  "rows": [{"order_id": "ORD-1", "status": "paid"}],
  "warnings": []
}
```

## Profile

`csvql profile --output json` returns:

- `source`
- `row_count`
- `column_count`
- `duplicate_row_count`
- `columns`
- `warnings`

Each column reports its name and DuckDB type, null and distinct counts, null
percentage, and observed minimum and maximum values when applicable.

```json
{
  "source": {
    "display_path": "data/orders.csv",
    "resolved_path": "<absolute-path>",
    "modified_at": "<modified-at>",
    "size_bytes": 64,
    "fingerprint": {
      "version": 1,
      "size_bytes": 64,
      "modified_at": "<modified-at>"
    }
  },
  "row_count": 2,
  "column_count": 3,
  "duplicate_row_count": 0,
  "columns": [
    {
      "name": "status",
      "duckdb_type": "VARCHAR",
      "null_count": 0,
      "non_null_count": 2,
      "null_percentage": 0.0,
      "distinct_count": 2,
      "min": "paid",
      "max": "pending"
    }
  ],
  "warnings": []
}
```

## Checks and project health

`csvql check --output json` returns the overall `status`, counts for configured
checks, individual check results, and `warnings`.

```json
{
  "status": "passed",
  "check_count": 1,
  "passed_count": 1,
  "failed_count": 0,
  "checks": [
    {
      "name": "order_id_required",
      "table": "orders",
      "column": "order_id",
      "type": "not_null",
      "status": "passed",
      "failed_count": 0
    }
  ],
  "warnings": []
}
```

`checks[*].failures` is present only when you request failure samples and the
check has failures. It is capped by `--failure-limit`; it is not a complete list
of every failing row.

`csvql doctor --output json` returns an overall `status`, counts for passed,
warning, and failed probes, a `project` object, and `probes`. A probe always
has `name`, `scope`, `status`, and `message`; it can also include context such
as a table, check, path, or column.

## Tables

`csvql tables --output json` returns the discovered catalog location and its
defined tables:

```json
{
  "config_path": "<absolute-path>",
  "project_root": "<absolute-path>",
  "tables": [
    {
      "name": "orders",
      "path": "data/orders.csv",
      "resolved_path": "<absolute-path>"
    }
  ]
}
```

The catalog and resolved-path fields are absolute paths on the computer running
the command.

## Shared behavior

- Query, saved-SQL runs, and JSON exports use the same tabular-result shape.
- `inspect`, `sample`, `profile`, and `check` include `warnings`, even when it
  is empty.
- `inspect.row_count` is structured metadata; `profile.row_count` is an integer.
- `check` and `doctor` have status-bearing result shapes that are separate from
  query results.
