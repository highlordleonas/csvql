# Changelog

This changelog lists the changes in each LocalQL release.

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
