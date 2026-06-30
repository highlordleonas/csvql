# JSON Contracts

## Scope And Guarantees

This document records the current `v0.8` JSON output for CSVQL's automation-oriented command surfaces:

- `csvql query --output json`
- `csvql run --output json`
- `csvql inspect --output json`
- `csvql profile --output json`
- `csvql check --output json`
- `csvql export --format json`

Runtime truth wins. The `Current v0.8 Contract` sections below describe the JSON exactly as the CLI emits it today. The `Ideal v1 Normalized Contract` section is future-facing design guidance only; it is not the current runtime envelope.

Not covered here:

- `csvql sample --output json`
- `csvql tables --output json`
- benchmark artifact JSON
- Python API result objects

## Stable vs Volatile Fields

- `elapsed_ms` is part of the current query-shaped runtime output, but its exact numeric value is volatile.
- `source.resolved_path`, `source.modified_at`, and `source.fingerprint.modified_at` are machine-local values and are redacted in the examples below.
- `source.size_bytes` reflects the specific input file used in each example and can vary if the input changes.
- Field names, nesting, omission behavior, and scalar types are the stable part of the contract.

## Current v0.8 Contract

### Shared Query-Shaped Results

These three surfaces currently share the same JSON family:

- `csvql query --output json`
- `csvql run --output json`
- `csvql export --format json`

Common fields:

- `columns`: ordered list of output column names
- `rows`: record-oriented rows keyed by column name
- `row_count`: number of returned rows
- `elapsed_ms`: rounded wall-clock execution time in milliseconds

Example `query` payload captured from `/private/tmp/csvql-json-contracts/query.json`:

```json
{
  "columns": [
    "order_count"
  ],
  "elapsed_ms": 3.099,
  "row_count": 1,
  "rows": [
    {
      "order_count": 2
    }
  ]
}
```

Example `run` payload captured from `/private/tmp/csvql-json-contracts/run.json`:

```json
{
  "columns": [
    "order_count"
  ],
  "elapsed_ms": 0.833,
  "row_count": 1,
  "rows": [
    {
      "order_count": 2
    }
  ]
}
```

Example `export --format json` payload captured from `/private/tmp/csvql-json-contracts/export.json`:

```json
{
  "columns": [
    "order_count"
  ],
  "elapsed_ms": 0.837,
  "row_count": 1,
  "rows": [
    {
      "order_count": 2
    }
  ]
}
```

### inspect --output json

Current top-level fields:

- `source`
- `dialect`
- `columns`
- `row_count`
- `warnings`

`inspect.row_count` is structured metadata, not a plain integer.

Example captured from `/private/tmp/csvql-json-contracts/inspect.json`:

```json
{
  "columns": [
    {
      "duckdb_type": "VARCHAR",
      "name": "order_id"
    },
    {
      "duckdb_type": "VARCHAR",
      "name": "status"
    },
    {
      "duckdb_type": "DOUBLE",
      "name": "total_amount"
    }
  ],
  "dialect": {
    "delimiter": ",",
    "encoding": "utf-8",
    "escape": null,
    "header": true,
    "quote": "\""
  },
  "row_count": {
    "exact": false,
    "mode": "not_counted",
    "value": null
  },
  "source": {
    "display_path": "data/orders.csv",
    "fingerprint": {
      "modified_at": "<modified-at>",
      "size_bytes": 64,
      "version": 1
    },
    "modified_at": "<modified-at>",
    "resolved_path": "<tmp>/csvql-json-contracts-fixture/data/orders.csv",
    "size_bytes": 64
  },
  "warnings": []
}
```

### profile --output json

Current top-level fields:

- `source`
- `row_count`
- `column_count`
- `duplicate_row_count`
- `columns`
- `warnings`

`profile.row_count` is an integer, not the structured object used by `inspect`.

Example captured from `/private/tmp/csvql-json-contracts/profile.json`:

```json
{
  "column_count": 3,
  "columns": [
    {
      "distinct_count": 2,
      "duckdb_type": "VARCHAR",
      "max": "ORD-2",
      "min": "ORD-1",
      "name": "order_id",
      "non_null_count": 2,
      "null_count": 0,
      "null_percentage": 0.0
    },
    {
      "distinct_count": 2,
      "duckdb_type": "VARCHAR",
      "max": "pending",
      "min": "paid",
      "name": "status",
      "non_null_count": 2,
      "null_count": 0,
      "null_percentage": 0.0
    },
    {
      "distinct_count": 2,
      "duckdb_type": "DOUBLE",
      "max": 20.0,
      "min": 10.0,
      "name": "total_amount",
      "non_null_count": 2,
      "null_count": 0,
      "null_percentage": 0.0
    }
  ],
  "duplicate_row_count": 0,
  "row_count": 2,
  "source": {
    "display_path": "data/orders.csv",
    "fingerprint": {
      "modified_at": "<modified-at>",
      "size_bytes": 64,
      "version": 1
    },
    "modified_at": "<modified-at>",
    "resolved_path": "<tmp>/csvql-json-contracts-fixture/data/orders.csv",
    "size_bytes": 64
  },
  "warnings": []
}
```

### check --output json

Current top-level fields:

- `status`
- `check_count`
- `passed_count`
- `failed_count`
- `checks`
- `warnings`

Passing example captured from `/private/tmp/csvql-json-contracts/check-passing.json`:

```json
{
  "check_count": 1,
  "checks": [
    {
      "column": "order_id",
      "failed_count": 0,
      "name": "order_id_required",
      "status": "passed",
      "table": "orders",
      "type": "not_null"
    }
  ],
  "failed_count": 0,
  "passed_count": 1,
  "status": "passed",
  "warnings": []
}
```

Failure example captured from `/private/tmp/csvql-json-contracts/check-failure.json`:

```json
{
  "check_count": 1,
  "checks": [
    {
      "column": "order_id",
      "failed_count": 2,
      "failures": [
        {
          "row": {
            "order_id": null,
            "status": "unknown",
            "total_amount": 10.0
          },
          "row_number": 2,
          "value": null
        }
      ],
      "name": "order_id_required",
      "status": "failed",
      "table": "orders",
      "type": "not_null"
    }
  ],
  "failed_count": 1,
  "passed_count": 0,
  "status": "failed",
  "warnings": []
}
```

`check.failures` is conditional and omitted unless failure samples are requested and present.

## Cross-Command Rules In v0.8

- `query`, `run`, and `export --format json` currently share one query-shaped family.
- `inspect`, `profile`, and `check` always include `warnings`, even when empty.
- `inspect.row_count` is structured metadata, but `profile.row_count` is an integer.
- `check.failures` is conditional and omitted unless `--show-failures` is requested and failures are present.
- Current source metadata can include absolute paths, timestamps, and file fingerprints that vary per machine and run.

## Ideal v1 Normalized Contract

Recommended future envelope:

```json
{
  "schema_version": 1,
  "command": "profile",
  "data": {
    "row_count": 2,
    "column_count": 3,
    "duplicate_row_count": 0,
    "columns": []
  },
  "warnings": [],
  "meta": {
    "source": {
      "display_path": "data/orders.csv"
    },
    "elapsed_ms": 3.099
  }
}
```

Recommended rules:

- `data` contains the semantic result the caller actually wants.
- `warnings` is always present and always a list.
- `meta` contains volatile operational or provenance details.
- Query-shaped results converge under one shared table-result family.
- `inspect` and `profile` stop diverging about where count and source metadata live.

## Delta From Current v0.8 To Ideal v1

### query, run, and export --format json

Current:

- top-level `columns`, `rows`, `row_count`, `elapsed_ms`

Ideal v1:

- move `columns`, `rows`, and `row_count` under `data`
- move `elapsed_ms` under `meta`
- add `schema_version` and `command`

### inspect

Current:

- top-level `source`, `dialect`, `columns`, `row_count`, `warnings`

Ideal v1:

- move `dialect`, `columns`, and `row_count` under `data`
- move machine-local source provenance under `meta`

### profile

Current:

- top-level `source`, `row_count`, `column_count`, `duplicate_row_count`, `columns`, `warnings`

Ideal v1:

- move result metrics under `data`
- move source provenance under `meta`
- converge count and source placement with `inspect`

### check

Current:

- top-level run verdict and counts
- conditional `checks[*].failures`

Ideal v1:

- move verdict and counts under `data`
- keep `warnings` top-level
- keep sampled failures command-specific inside `data.checks[*]`
