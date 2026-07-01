# JSON Contracts

## Scope And Guarantees

This document records the current `v1` JSON output contract for CSVQL's
automation-oriented command surfaces:

- `csvql query --output json`
- `csvql run --output json`
- `csvql inspect --output json`
- `csvql sample --output json`
- `csvql profile --output json`
- `csvql check --output json`
- `csvql doctor --output json`
- `csvql tables --output json`
- `csvql export --format json`

Runtime truth wins. The `Current v0.8 Contract` sections below describe the
JSON exactly as the CLI emits it today. The `Possible Post-v1 Normalized
Contract` section is future-facing design guidance only; it is not the current
runtime envelope.

V1 decision: the current v0.8 JSON shapes are the stable v1 runtime contract. A
normalized envelope is not implemented in the current runtime and must not be
described as current behavior.

Not covered here:

- benchmark artifact JSON
- Python API result objects

## Stable vs Volatile Fields

- `elapsed_ms` is part of the current query-shaped runtime output, but its exact numeric value is volatile.
- `source.resolved_path`, `source.modified_at`, and `source.fingerprint.modified_at` are machine-local values and are redacted in the examples below.
- `source.size_bytes` reflects the specific input file used in each example and can vary if the input changes.
- Field presence, top-level nesting, and omission behavior are the stable part of the contract.
- Individual row values and some nested values remain data-dependent, and non-JSON-native values may be stringified by the serializer.

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

### sample --output json

Current top-level fields:

- `source`
- `limit`
- `columns`
- `rows`
- `warnings`

`sample.rows` is record-oriented JSON keyed by column name. `limit` is the
requested maximum row count, not a guarantee that the source contains that many
rows.

Example shape:

```json
{
  "columns": [
    "order_id",
    "status"
  ],
  "limit": 1,
  "rows": [
    {
      "order_id": "ORD-1",
      "status": "paid"
    }
  ],
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
When it is present, it is a sampled subset of the total failures for that check, capped by `--failure-limit`. In the example above, `failed_count` is `2`, but only one sampled failure object is returned because the capture used `--failure-limit 1`.
Failure sample objects also vary by check type. The not-null example above includes `row_number`, `row`, and `value`, but other checks can emit different fields. For example, `unique` and `row_count_between` checks can include `observed` plus `min` and `max` bounds, and `foreign_key` can add `reference_table` and `reference_column`.

### doctor --output json

Current top-level fields:

- `status`
- `probe_count`
- `passed_count`
- `warning_count`
- `failed_count`
- `project`
- `probes`

`doctor` exits `0` for `passed` and `warning` results. It exits `12` when
concrete project-health failures are found.

`project` is always present. Its `config_path` and `project_root` fields are
machine-local absolute paths when a project catalog is found, and `null` when
project discovery only emits a warning.

Each `probes` entry always includes:

- `name`
- `scope`
- `status`
- `message`

Probe entries can also include conditional context fields such as `table`,
`check`, `path`, `resolved_path`, `column`, `reference_table`, and
`reference_column`.

### tables --output json

Current top-level fields:

- `config_path`
- `project_root`
- `tables`

Each `tables` entry includes:

- `name`
- `path`
- `resolved_path`

`config_path`, `project_root`, and `resolved_path` are machine-local absolute
paths.

## Cross-Command Rules In v0.8

- `query`, `run`, and `export --format json` currently share one query-shaped family.
- `inspect`, `profile`, and `check` always include `warnings`, even when empty.
- `sample`, `inspect`, `profile`, `check`, and `doctor` include `warnings` or warning counts in their current shape.
- `inspect.row_count` is structured metadata, but `profile.row_count` is an integer.
- `check.failures` is conditional and omitted unless `--show-failures` is requested and failures are present.
- When `check.failures` is present, it is a sampled, `--failure-limit`-capped subset rather than a complete enumeration of every failure.
- `tables` exposes machine-local absolute paths because it is a project catalog listing.
- `doctor` has a status-bearing JSON shape separate from `check`.
- Current source metadata can include absolute paths, timestamps, and file fingerprints that vary per machine and run.

## Possible Post-v1 Normalized Contract

Illustrative future envelope:

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

If a post-v1 compatibility break adopts normalization, it should use these
rules:

- `data` contains the semantic result the caller actually wants.
- `warnings` is always present and always a list.
- `meta` contains volatile operational or provenance details.
- Query-shaped results converge under one shared table-result family.
- `inspect` and `profile` stop diverging about where count and source metadata live.

## Potential Migration Delta From Current v0.8

### query, run, and export --format json

Current:

- top-level `columns`, `rows`, `row_count`, `elapsed_ms`

Possible future shape:

- move `columns`, `rows`, and `row_count` under `data`
- move `elapsed_ms` under `meta`
- add `schema_version` and `command`

### inspect

Current:

- top-level `source`, `dialect`, `columns`, `row_count`, `warnings`

Possible future shape:

- move `dialect`, `columns`, and `row_count` under `data`
- move machine-local source provenance under `meta`

### profile

Current:

- top-level `source`, `row_count`, `column_count`, `duplicate_row_count`, `columns`, `warnings`

Possible future shape:

- move result metrics under `data`
- move source provenance under `meta`
- converge count and source placement with `inspect`

### check

Current:

- top-level run verdict and counts
- conditional `checks[*].failures`

Possible future shape:

- move verdict and counts under `data`
- keep `warnings` top-level
- keep sampled failures command-specific inside `data.checks[*]`
