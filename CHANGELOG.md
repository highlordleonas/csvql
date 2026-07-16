# Changelog

This page records user-visible changes in each LocalQL release. For a guided
overview of the v1 feature set, see the [v1 release notes](docs/release-notes/v1.md).

## [1.0.1] - 2026-07-10

### Fixed

- README links and screenshots render correctly in the package description on
  PyPI.

### Changed

- Installation, command references, troubleshooting, and contributor guidance
  are easier to navigate.

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

- The installable package is `localql`; the command, Python import package, and
  project configuration remain `csvql` and `.csvql.yml`.
- LocalQL runs trusted local DuckDB SQL. It does not sandbox DuckDB or restrict
  filesystem access.
