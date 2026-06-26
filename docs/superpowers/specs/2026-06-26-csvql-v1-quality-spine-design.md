# CSVQL v1 Quality Spine Design

Status: design approved in conversation; written spec review required before implementation planning.

Date: 2026-06-26

## Purpose

CSVQL should become a local-first CSV intelligence CLI: point it at a dump, understand the shape quickly, query it with SQL, and promote useful analysis into repeatable project workflows without forcing users into Excel cleanup or a warehouse.

The v1 design target is the **Quality Spine**: a small, coherent path from ad hoc inspection to repeatable local analytics.

The active implementation target remains the repo's v0.1 surface until that surface is stable. This spec records the v1 direction so v0.1 and later slices build toward the same shape without expanding scope prematurely.

## Non-Goals

These are explicitly not v1 unless later evidence and explicit scope approval change the decision:

- Web server or app UI
- Cloud connectors
- Multi-tenant, auth, or security platform features
- NLP query execution engine
- Rust performance project or compression layer
- Full lineage graphs
- Dashboards and alerting
- Hidden automatic cache or materialization

Narrow variants can still be considered when scoped correctly:

- HTML or Markdown reports as export artifacts, not a dashboard product
- Explicit user-controlled materialization or refresh commands, not hidden state
- Minimal provenance metadata, not a full lineage graph
- Local security hygiene, not a sandbox claim
- A source abstraction that can later support non-CSV sources, not cloud connectors in v1
- Optional metadata-only suggestions, not executing generated SQL

## Product Shape

CSVQL should support two related workflows.

Ad hoc workflow:

- Inspect an unknown CSV before querying it.
- Sample rows without opening a spreadsheet.
- Query one file or several table mappings using DuckDB SQL.
- Get useful table, JSON, Markdown, or exported output.
- Fail loudly when paths, aliases, CSV parsing, or SQL execution are invalid.

Repeatable workflow:

- Initialize a local CSVQL project.
- Register known CSV tables in a project catalog.
- List registered tables and their basic metadata.
- Run saved SQL files against the catalog.
- Profile data shape and quality.
- Run deterministic data checks with stable output and exit codes.

## v1 Command Surface

The v1 command family is:

- `csvql query`: execute ad hoc SQL against one or more CSV files.
- `csvql inspect`: infer and display CSV shape, columns, dialect clues, row count when practical, and source fingerprint.
- `csvql sample`: display a bounded row sample with selected columns and output modes.
- `csvql run`: execute a saved SQL file against project tables.
- `csvql export`: write query results to explicit output files and formats.
- `csvql init`: create local project configuration.
- `csvql add`: register a CSV table in the project catalog.
- `csvql tables`: list project tables and metadata.
- `csvql profile`: calculate deterministic data profiling results.
- `csvql check`: run configured data quality checks and return a check-specific non-zero exit on failure.

The first implementation slice after this spec should not attempt all of v1. It should focus on the Inspect-First Ad Hoc Workflow: source handling, `inspect`, `sample`, output modes, messy fixtures, and docs.

## Architecture

The core flow should remain small and explicit:

```text
CLI
  -> request parsing and validation
  -> source resolution
  -> CSV inspection and registration
  -> DuckDB execution
  -> result, profile, or check models
  -> output renderers
```

DuckDB owns SQL execution. CSVQL owns local workflow, source resolution, table aliasing, output rendering, deterministic errors, docs, and tests.

Recommended module boundaries:

- `cli.py`: thin Typer boundary, command wiring, exit behavior.
- `table_mapping.py`: v0.1 table mapping parser and alias validation.
- `source.py`: path resolution, `CSVSource`, `RegisteredTable`, and `SourceFingerprint`.
- `inspection.py`: schema, dialect, sample, and lightweight metadata inspection.
- `engine.py`: DuckDB connection lifecycle, CSV registration, SQL execution, and DuckDB error conversion.
- `output.py` or `renderers.py`: table, JSON, Markdown, and export rendering.
- `models.py`: typed request/result/profile/check value objects.
- `exceptions.py`: CLI-friendly failures with stable exit codes.

Do not introduce a global singleton, background daemon, server process, or persistent state that is not explicitly user-controlled.

## Source Model

The source layer should separate local file concerns from SQL execution:

- `CSVSource`: resolved path, display path, file metadata, optional reader options.
- `RegisteredTable`: validated alias plus source and registration settings.
- `SourceFingerprint`: stable enough metadata for repeatable docs and cache decisions later, such as path, size, modified timestamp, and optionally content hash when explicitly requested.

Generated identifiers must be validated or quoted before reaching DuckDB. User-authored SQL remains trusted local SQL unless safe mode is explicitly designed, implemented, and tested.

## Error Model

CSVQL should use typed errors with clear CLI messages and stable exit codes. Required categories:

- Invalid command arguments
- Missing or unreadable file
- Invalid table alias or table mapping
- CSV parse or dialect failure
- Query execution failure
- Invalid project configuration
- Data check failure

`csvql check` should reserve exit code `3` for failed checks, distinct from command/runtime errors.

Errors should be concise for humans and structured in JSON mode where relevant. No command should silently fall back to sample data or ignore unreadable sources.

## Security Model

CSVQL is a local developer tool for trusted local SQL.

Security hygiene required for v1:

- Validate file paths and table aliases before execution.
- Quote or validate generated identifiers.
- Use parameter binding for values when CSVQL supplies values.
- Use safe YAML loading for project configuration.
- Do not log secrets or raw environment dumps.
- Do not auto-install or auto-load DuckDB extensions.
- Do not invoke shell commands from SQL helper features.
- Do not claim sandboxing, safe execution of untrusted SQL, or production isolation.

Optional AI or NLP features, if ever explored, must be metadata-only and non-executing in v1. They may suggest SQL text, but CSVQL must not silently execute generated SQL.

## Testing Strategy

The evidence bar should rise with each slice. v1 stability requires:

- Unit tests for parsing, validation, source resolution, error conversion, and renderers.
- Real DuckDB integration tests for query behavior.
- CLI integration tests for exit codes, stdout, stderr, table output, and JSON output.
- Messy CSV fixtures for delimiter, quote, null, header, encoding, and type-inference edge cases.
- JSON contract tests where output is intended for automation.
- Focused Markdown/export tests once those formats exist.
- No hidden state in tests unless the test explicitly covers user-controlled materialization.

Golden files are acceptable for stable JSON or Markdown artifacts. Avoid brittle snapshots for rich terminal table formatting unless the format is explicitly part of the contract.

## Benchmark and Performance Evidence

Performance claims require benchmark evidence. Do not claim large-file performance from design docs or happy-path fixtures.

A later benchmark harness should measure a small matrix:

- `count(*)`
- Filtered aggregate
- Join
- Window or date-trunc query

Minimum recorded fields:

- CSV sizes and row counts
- DuckDB version
- threads and relevant memory settings
- cold and warm median
- p95
- output row count
- benchmark command and environment notes

The first benchmark artifact can be JSON plus a Markdown summary. Dashboards and alerting are out of scope.

## Implementation Slices

### Slice 1: Inspect-First Ad Hoc Workflow

Goal: make CSVQL useful the moment someone receives an unknown CSV.

Likely work:

- Add `CSVSource`, `RegisteredTable`, and source fingerprint basics.
- Add `csvql inspect`.
- Add `csvql sample`.
- Expand output modes only where the command contract needs them.
- Add messy CSV fixtures.
- Document examples and failure behavior.

Evidence:

- Unit tests for source and inspection behavior.
- CLI tests for `inspect` and `sample`.
- Error-path tests for missing files, invalid aliases, and parse failures.
- README and architecture updates.

### Slice 2: Project Catalog and Saved SQL

Goal: promote repeated work from one-off commands into local project workflows.

Likely work:

- Define `.csvql.yml` schema.
- Add `init`, `add`, and `tables`.
- Add `run` for saved SQL files.
- Keep path resolution predictable and project-local.

Evidence:

- Config loader tests.
- Project discovery tests.
- CLI tests for catalog commands and saved SQL execution.
- Docs for project layout and examples.

### Slice 3: Export, Profile, and Check

Goal: make outputs shareable and quality checks automatable.

Likely work:

- Add `export` using the same execution path as stdout query output.
- Add `profile` with deterministic metrics.
- Add `check` with configured checks and stable exit code.
- Add JSON contracts for profiles and checks.

Evidence:

- Renderer/export tests.
- Profile fixture tests.
- Check pass/fail tests with exit code assertions.
- Docs for CI usage.

### Slice 4: Evidence and Polish

Goal: harden release readiness without widening product scope.

Likely work:

- Benchmark harness and first report.
- Changelog and release workflow.
- Final docs pass.
- Focused review and security gate.

Evidence:

- Published benchmark artifact.
- Full local gate.
- Review notes and fixed findings.
- Release-candidate checklist.

## Lessons From The Older Analytics Project

Useful to bring forward:

- Small DuckDB engine/query/result boundaries.
- Local CSV detection for encoding, dialect, schema, and row count.
- Dataset-to-view registration pattern.
- Behavior-first tests that exercise real DuckDB.
- Fixture generation and benchmark result artifacts.

Avoid carrying forward:

- Enterprise platform scope.
- Web/API/server/cloud/multi-tenant/security/compliance shape.
- Silent sample-data fallbacks.
- Raw f-string SQL generation for identifiers or values.
- Global singleton state.
- `sys.path` hacks.
- Docs and tests drifting from implemented behavior.
- Rust, compression, or cache work before benchmark evidence exists.

## Capability Contract

The repo authority for ongoing Codex work is in `AGENTS.md`. The important operating rule is that capability selection should serve CSVQL's local Python CLI, DuckDB, CSV inspection, tests, docs, and evidence bar. `docs/CODEX_CAPABILITY_REVIEW.md` guides skill and agent selection, but it does not expand product scope by itself.

## Proof Language

Use precise readiness labels:

- `docs-ready`
- `local-cli-proof-ready`
- `test-backed`
- `benchmark-backed`
- `release-candidate`
- `v0.1-stable`

Do not claim `production-safe`, `sandbox-safe`, `large-file-proven`, `portfolio-grade`, or `v1-ready` from docs, fixtures, or one happy-path query.

## Open Decisions For The Implementation Plan

These should be decided in the next Superpowers writing-plan step after user review of this spec:

- Exact first-slice file list and ordering.
- Whether `inspect` row counts should be exact by default or bounded/optional for large files.
- Whether Markdown output belongs in Slice 1 or waits for export.
- Exact JSON schema for `inspect` and `sample`.
