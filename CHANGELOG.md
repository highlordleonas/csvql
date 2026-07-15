# Changelog

This changelog lists the changes in each LocalQL release.

## [1.0.2] - 2026-07-15

### Changed

- Hardened the optional terminal workbench's large-result storage with secure
  operating-system temporary workspaces, atomic spill completion,
  conservative abandoned-workspace recovery, bounded previews, and sanitized
  cleanup or storage-failure reporting.
- Added portable control-key fallbacks for terminal workbench actions where
  terminals or operating systems intercept function keys.
- Sharpened installed-user documentation across pip and uv-tool paths.
- Validated separate core and optional TUI installation paths.
- Confirmed the v1 CSV CLI, Python, catalog, JSON, exit-code, and export
  contracts are unchanged.

TUI spill storage reduces duplicate retained result memory after handling, but
query execution still fully materializes Python results and is not streaming or
execution-memory bounded.

## [1.0.1] - 2026-07-10

### Fixed

- README links and images now open correctly when the package description is
  displayed on PyPI.

### Changed

- Reorganized the public documentation around installation, common workflows,
  command and JSON references, troubleshooting, and contributor guidance.

## [1.0.0] - 2026-07-01

### Added

- DuckDB-backed local CSV queries through `csvql query`.
- Project catalogs with `.csvql.yml`, `csvql init`, `csvql add`, and `csvql tables`.
- Saved SQL execution, explicit exports, inspection, sampling, profiling,
  configured data-quality checks, and project health checks.
- An optional Textual terminal menu with sources, SQL editing, results, history,
  explicit exports, and saved result sources.
- JSON output for supported automation-oriented commands.
- A small project-backed Python API through `CSVQLSession`.
- A reproducible SaaS revenue example project.

### Notes

- The installable package is named `localql`; the command, Python package, and
  project configuration remain `csvql` and `.csvql.yml`.
- LocalQL runs trusted local DuckDB SQL. It does not sandbox DuckDB or restrict
  filesystem access.
- LocalQL 1.0.0 focuses on local CSV work. It does not include cloud connectors, web
  dashboards, notebooks, natural-language SQL, or a plugin platform.
