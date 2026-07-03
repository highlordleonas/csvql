# Changelog

All notable CSVQL changes are summarized here.

LocalQL package metadata is prepared for `v1.0.0`. The `v1.0.0` section records
implemented `csvql` surfaces for the local release candidate; it is not a
publication, tag, PyPI upload, GitHub release, artifact upload, or `v1-stable`
claim.

## v1.0.0 - 2026-07-01

Status: LocalQL distribution alias accepted; full candidate proof refreshed at
`fea95f5 release: adopt localql distribution alias`.

### Added

- DuckDB-backed local CSV query workflow through `csvql query`.
- Explicit table mappings with `--table name=path`.
- Single-file shortcut query mode.
- Project catalogs through `.csvql.yml`, `csvql init`, `csvql add`, and
  `csvql tables`.
- Catalog-backed query, inspect, sample, profile, check, run, and export
  workflows.
- Saved SQL execution through `csvql run`.
- Explicit exports through `csvql export` with CSV, JSON, and Markdown formats.
- CSV inspection through `csvql inspect`.
- Bounded data samples through `csvql sample`.
- CSV profiling through `csvql profile`.
- Configured data-quality checks through `csvql check`.
- Project health checks through `csvql doctor`.
- Optional Textual-powered `csvql menu` terminal workbench through the `tui`
  extra.
- TUI startup from `.csvql.yml`, one CSV path, or repeated `--table` mappings.
- TUI source manager, SQL editor, results grid, session-local query history,
  help view, source actions, explicit export action, and explicit project
  catalog save action.
- TUI derived result sources: `Ctrl+S`, `Alt+S`, or `F11` saves the last successful tabular
  result to `.csvql/results/{alias}.csv` and adds it to the current Sources pane
  with kind `derived`; the alias is session-local unless sources are explicitly
  saved to `.csvql.yml`.
- Table and JSON output modes for automation-oriented commands.
- Stable v1 JSON contract documentation for current runtime shapes.
- Common failure gallery for deterministic CLI behavior and exit-code examples.
- Polished SaaS revenue example project with reproducible data and saved SQL.
- Repo-local benchmark workflow with JSON and Markdown artifacts.
- Repo-local release-readiness proof for version, build, wheel install, and
  smoke behavior.
- Small project-backed Python API through `CSVQLSession`.
- `localql` distribution name while keeping the `csvql` command, import package,
  and `.csvql.yml` project config contract.

### Stable v1 Contract Decisions

- Current v0.8 JSON output shapes are the stable v1 runtime contract.
- Current exit-code behavior is the stable v1 CLI failure contract.
- `.csvql.yml` remains strict `version: 1` without a migration framework.
- The Python API remains project-backed and intentionally small.
- DuckDB remains the only SQL execution engine.
- DuckDB dependency support is constrained to `duckdb>=1.5.0,<2`.

### Known Boundaries

- CSVQL treats user-authored SQL as trusted local SQL.
- CSVQL does not sandbox DuckDB or restrict filesystem access.
- CSVQL does not claim production readiness.
- CSVQL does not claim broad large-file performance beyond recorded benchmark
  artifacts.
- TUI query history is session-local and not persisted by CSVQL.
- Derived result sources are explicit user-created CSV files, not hidden cache or
  automatic materialization.
- CSVQL does not include a web app, cloud connector platform, dashboard,
  notebook framework, natural-language SQL engine, dataframe-first API, plugin
  system, safe mode, hidden cache, or automatic materialization.

### Release Proof

Release-candidate eligibility is proven locally by running the release workflow
on the current candidate state:

- full local gate through Ruff, mypy, and pytest
- release-readiness proof through `scripts/verify_release_readiness.py`
- benchmark proof through `scripts/benchmark_csvql.py`
- unsupported-claim scan with matches classified as guardrails, non-claims, or
  conditional label rules
- generated proof artifacts remained ignored under `output/`
