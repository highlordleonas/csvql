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

Stable gate:

- CLI behavior documented in `README.md`
- missing-file, bad-mapping, invalid-alias, and query-failure tests
- JSON and table output tests
- Ruff format, Ruff lint, mypy, and pytest passing through `uv run`
- no unsupported sandbox, security-isolation, production-readiness, or large-file performance claims

## v0.2.0 - Inspect And Sample

Implemented:

- source model for resolved local CSV files
- `csvql inspect <path>`
- bounded/default row-count status; exact row count only with `--exact`
- `csvql sample <path>`
- table and JSON output for `inspect` and `sample`
- messy CSV fixtures and error-path tests
- README and architecture updates

## v0.3.0 - Project Catalog

Implemented:

- `.csvql.yml` models and loader
- `csvql init`
- `csvql add`
- `csvql tables`
- project root discovery
- relative path resolution for catalog-backed tables
- catalog-backed `csvql query "SELECT ... FROM alias"`
- explicit `--table` mappings override catalog aliases for one invocation

## v0.4.0 - Saved Workflows

Implemented:

- `csvql run queries/file.sql`
- registered-table support for `csvql inspect`
- registered-table support for `csvql sample`
- `csvql export queries/file.sql --format csv|json|markdown --out path`
- overwrite protection for export outputs with explicit `--force`

## v0.5.0 - Profiling

Implemented:

- row and column counts
- null counts and percentages
- distinct counts excluding nulls
- numeric, date, and string min and max
- duplicate row count using excess-row semantics
- direct path and catalog alias support for `csvql profile`
- table and JSON profile output

## v0.6.0 - Data Quality Checks

Implemented:

- configured checks in `.csvql.yml`
- `csvql check [table]`
- `not_null`, `unique`, `accepted_values`, `min`, `max`, `row_count_between`, `foreign_key`
- non-zero exit code `11` on data-quality failures
- table and JSON output for check results
- sampled failing rows or values with `--show-failures`

## v0.7.0 - Benchmark And Release Hardening

- benchmark harness and JSON artifact
- Markdown benchmark summary
- release workflow
- changelog
- polished examples with reproducible data and commands

## Post-v1 - Python API

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
- polished examples with reproducible data and commands
