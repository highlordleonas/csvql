# Changelog

This page records user-visible changes in each LocalQL release. For a guided
overview of the v1 feature set, see the [v1 release notes](docs/release-notes/v1.md).

## [1.2.0] - 2026-07-30

LocalQL 1.2.0 expands the CSV-first foundation into one deterministic local
structured-source workflow. CSV, Parquet, JSON, NDJSON, and Excel sources now
participate through the same CLI, terminal workbench, catalog, and Python API
contracts.

### Added

- Added Parquet files and explicitly typed partitioned Parquet directories,
  JSON documents, NDJSON/JSON Lines records, and Excel `.xlsx` workbooks as
  relational sources alongside CSV.
- Added deterministic source selection: an explicit type wins, a recognized
  file extension selects its provider, and bounded identification reports
  evidence without guessing when a file or directory remains ambiguous.
- Added provider-specific options for Parquet partitioning and schema union,
  bounded JSON/NDJSON inference and explicit schemas or record paths, and Excel
  sheet, range, header, empty-row, and type-conversion behavior.
- Added cross-format joins plus shared inspect, sample, and profile behavior
  across the supported local providers.
- Added normalized version 2 source definitions to project catalogs while
  keeping version 1 catalogs readable. The CLI, terminal workbench, and Python
  `SourceDefinition` API use the same source intent.
- Added complete result export to record-oriented NDJSON, typed Parquet, and
  Excel `.xlsx` across the CLI, Python API, and LocalQL Workbench. Existing CSV,
  JSON-envelope, Markdown, and text exports remain available.
- Added an end-to-end multi-format export benchmark that crosses all five source
  providers with NDJSON, Parquet, and Excel outputs and validates every
  generated artifact outside the timed interval.

### Changed

- Source detection, activation, resolution, and binding now follow one
  registered-provider workflow across entry surfaces. Provider activation stays
  lazy, and LocalQL never installs optional dependencies while starting,
  detecting, querying, or exporting.
- Excel support requires DuckDB's `excel` extension to be provisioned
  explicitly in the same environment before Excel input or output; missing
  availability produces an actionable diagnostic.
- Parquet result export preserves DuckDB logical column types. NDJSON writes one
  record per line, while the existing JSON export retains the LocalQL result
  envelope with columns, row count, and elapsed time.
- The terminal experience is now presented as **LocalQL Workbench**, and CLI
  help distinguishes the CSV-compatible `--table` option from multi-format
  `--source`, `--source-type`, and `--source-option` usage.
- The installable distribution remains `localql`; the `csvql` command, Python
  import package, and `.csvql.yml` project convention remain compatible.
- The provider registration boundary remains internal. LocalQL 1.2.0 does not
  introduce a public plugin SDK, remote connectors, recursive directory
  guessing, or silent dependency installation.

### Fixed

- Terminal-workbench errors now preserve readable multiline diagnostics and
  suggestions while continuing to escape terminal control characters.

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
