# CSVQL v0.5 Profiling Design

## Goal

CSVQL v0.5 adds deterministic full-scan profiling for local CSV sources:

```bash
csvql profile <csv-path-or-catalog-alias>
csvql profile <csv-path-or-catalog-alias> --output json
```

The command supports direct CSV paths and project catalog aliases. Catalog alias resolution is case-insensitive, matching `inspect` and `sample`.

## Scope

Profiling intentionally performs a full scan. There is no bounded default mode and no `--exact` flag.

Supported output formats:

- `table`, the default human-readable Rich table output
- `json`, the stable automation contract

JSON top-level fields:

- `source`
- `row_count`
- `column_count`
- `duplicate_row_count`
- `columns`
- `warnings`

Column fields:

- `name`
- `duckdb_type`
- `non_null_count`
- `null_count`
- `null_percentage`
- `distinct_count`
- `min`
- `max`

Metric rules:

- `distinct_count` excludes nulls.
- `null_percentage` is rounded to three decimals.
- zero data rows report `0.0` for `null_percentage`.
- `duplicate_row_count` uses excess-row semantics: three identical complete rows contribute `2`.
- string `min` and `max` use DuckDB lexicographic ordering.

## Architecture

- Add `src/csvql/profiling.py` for DuckDB full-scan aggregate profiling.
- Add `ColumnProfile` and `ProfileResult` to `src/csvql/models.py`.
- Add profile renderers to `src/csvql/output.py`.
- Wire a thin `profile` command in `src/csvql/cli.py`.
- Reuse `resolve_path_or_catalog_source(...)`.

Profiling must not run user-authored SQL. It should build CSVQL-controlled aggregate SQL from DuckDB-discovered columns and quote identifiers safely for odd CSV headers such as `order id`, `total-amount`, and `select`.

Reuse `CSVInspectionError` for profile execution failures with message text:

```text
Failed to profile CSV file: <display path>
```

## Out Of Scope

This slice does not add safe mode, sandboxing, cache/materialization, benchmarking, timeout guarantees, production-readiness claims, data-quality scoring, or a Python API.

Docs must not claim sandbox safety, untrusted SQL safety, production readiness, large-file performance, benchmark-backed speed, timeout guarantees, cache/materialization, or v1 readiness.

