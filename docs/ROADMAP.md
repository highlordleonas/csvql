# Roadmap

## v0.1.0 - Query MVP

Goal: prove the core promise with a small working CLI.

- `csvql --help`
- `csvql query --table orders=data/orders.csv "SELECT * FROM orders LIMIT 10"`
- single-file shortcut: `csvql query data/orders.csv "SELECT * FROM orders LIMIT 10"`
- multiple table mappings for joins
- table output
- JSON output
- clear missing-file, bad-mapping, and query errors
- package layout, tests, Ruff, mypy, and CI

## v0.2.0 - Project Catalog

- `.csvql.yml` models and loader
- `csvql init`
- `csvql add`
- `csvql tables`
- project root discovery
- relative path resolution
- CSV reader options and type overrides

## v0.3.0 - SQL Files, Schema, Preview, Export

- `csvql run queries/file.sql`
- positional query parameters
- `csvql schema <table>`
- `csvql preview <table>`
- `csvql export queries/file.sql --format csv|json|markdown|parquet --out path`

## v0.4.0 - Profiling

- row and column counts
- null counts and percentages
- distinct counts
- numeric/date min and max
- duplicate row count
- JSON profile output

## v0.5.0 - Data Quality Checks

- configured checks in `.csvql.yml`
- `not_null`, `unique`, `accepted_values`, `min`, `max`, `row_count_between`, `foreign_key`
- non-zero exit code on failures
- JSON check output for CI

## v0.6.0 - Python API

- `CSVQLSession.from_config(".csvql.yml")`
- `session.query(sql, params=None)`
- `session.run_file(path, params=None)`
- typed result object with export helpers

## v1.0.0 - Stable Release

- stable CLI contract
- stable config schema
- full documentation
- benchmark report
- release workflow
- changelog
- portfolio-grade examples
