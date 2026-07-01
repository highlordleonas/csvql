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

Implemented:

- benchmark harness and JSON artifact
- Markdown benchmark summary
- reproducible synthetic and fixture-sized benchmark inputs
- benchmark documentation that avoids large-file claims beyond the recorded artifact
- version consistency verification
- build smoke for sdist and wheel
- installed-wheel smoke verification
- release-readiness documentation

## v0.8.0 - Portfolio Polish And Python API

Implemented:

- polished example project with reproducible data and commands
- walkthrough documentation for the example project
- stable JSON contract documentation for automation-oriented command outputs
- common failure gallery covering missing files, invalid aliases, invalid config, failed checks, overwrite protection, missing SQL files, and doctor failures
- focused `csvql doctor` command for local project health checks
- `CSVQLSession.from_config(".csvql.yml")`
- `session.tables()`
- `session.query(sql)`
- `session.run_file(path)`
- `session.inspect(table, exact=False)`
- `session.sample(table, limit=10)`
- `session.profile(table)`
- `session.check(table=None)`
- `session.export(sql_file, out, format="json", force=False)`
- small typed result objects that wrap existing CLI-tested internals
- no direct-path session mode, dataframe framework, notebook integration, async API, plugin API, config mutation helpers, or second execution engine

Remaining before v1:

- explicit user approval for release action after the 2026-07-01
  `release-candidate eligible` local proof assessment

## v1.0.0 - Stable Release

- stable CLI contract
- stable config schema
- stable small Python API contract
- full documentation
- refreshed benchmark report or documented local benchmark artifact
- release workflow
- changelog or release notes
- polished examples with reproducible data and commands
- full local gate passing through `uv run`

## Post-v1 - Future Expansion Candidates

- optional explicit cache or materialization with user-controlled state
- additional export formats if real workflows need them
- safe mode only after a separate ADR, threat model, implementation plan, and tests
- broader local file formats only after CSV-first v1 is stable
- richer Python API only after the small v1 API has real usage feedback
