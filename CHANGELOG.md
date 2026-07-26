# Changelog

This page records user-visible changes in each LocalQL release. For a guided
overview of the v1 feature set, see the [v1 release notes](docs/release-notes/v1.md).

## [1.1.1] - 2026-07-25

LocalQL 1.1.1 carries the complete v1.1 feature set forward from the
validation-only `v1.1.0` tag. Version 1.1.0 was not published to PyPI or as a
GitHub Release. Product behavior is unchanged from that qualified tree; 1.1.1
finalizes the public release metadata and strengthens release-state auditing.

### Added

- CSV access now runs through private `SourceSpec` and `SourceAdapter`
  contracts, establishing a CSV-first source boundary without creating a
  public plugin API.
- Public-release audits now require a dated current-version changelog entry and
  neutral release notes before release artifacts are built.

### Changed

- Interactive `csvql query` and `csvql run` table output now retains a bounded
  preview of 1,000 rows by default. Query/run JSON output and Python API results
  remain complete.
- CLI exports and terminal-menu export/save actions use complete results rather
  than inheriting the interactive preview bound.
- The terminal menu preserves complete results under one 1 GiB session
  capacity with no automatic eviction. Existing preserved results remain
  available when capacity is exhausted; a new result then reports a
  preview-only state.

### Fixed

- The terminal menu now supports source-free DuckDB SQL and keeps active-result
  and History actions attached to the result the user selected.

## [1.1.0] - 2026-07-25

Version 1.1.0 was used as a validation-only tag and was not published to PyPI
or as a GitHub Release. Its qualified product behavior is released as 1.1.1.

## [1.0.5] - 2026-07-21

### Changed

- Package and release verification now checks the wheel and source distribution
  as one exact release bundle before publication.
- Version-reporting surfaces now report 1.0.5. Query behavior, supported
  formats, and the SQL safety boundary remain unchanged.

## [1.0.4] - 2026-07-15

### Changed

- No changes to the LocalQL command-line interface or Python API.

## [1.0.3] - 2026-07-15

### Fixed

- The changelog and v1 release notes now describe the current LocalQL release.

### Changed

- The optional `csvql menu` handles restored and unavailable results more
  reliably.

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
