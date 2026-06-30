# CSVQL v0.8 Doctor Command Design

Status: design approved in conversation; written spec review required before
implementation planning.

Date: 2026-06-29

## Purpose

This spec defines the `csvql doctor` slice inside v0.8 portfolio polish.

The goal is to make CSVQL easier to evaluate as a believable local workflow
tool by adding one focused project-health command that answers a plain question:

> Can this local CSVQL project be discovered, loaded, and minimally trusted to
> run?

This slice should strengthen the CSVQL wedge:

- local-first project readiness
- deterministic automation output
- honest project-health proof without broad new product scope
- better portfolio demonstration for repeatable CLI workflows

## Subproject Boundary

This spec covers only `csvql doctor`.

Explicitly out of scope for this slice:

- saved SQL execution inside doctor
- configured check execution inside doctor
- auto-fix behavior
- arbitrary path or `--config` targeting
- strict mode, deep mode, or repair mode
- new `.csvql.yml` schema features
- common failure gallery writing
- Python API work
- benchmark or release-hardening work

Those are separate v0.8, v0.7, or later-roadmap concerns and should not be
bundled into this slice.

## Product Contract

This slice adds one new end-user command:

- `csvql doctor [--output table|json]`

The command is a focused project-health surface for local CSVQL projects. It is
not a generalized validator framework and not a replacement for:

- `csvql check` for configured data-quality execution
- `csvql run` for saved SQL execution
- `csvql inspect` or `csvql profile` for data exploration

The command should stay small, boring, and honest:

- it discovers the nearest `.csvql.yml`
- validates that the project can be loaded
- proves configured tables can be read through DuckDB
- statically audits configured checks against discovered schema
- emits deterministic table or JSON output

It does not claim sandboxing, safe execution of untrusted SQL, production
readiness, or full business-logic validation.

## Command Contract

The first public shape should be:

- `csvql doctor`
- `csvql doctor --output table`
- `csvql doctor --output json`

This first slice should not add:

- positional arguments
- `--config`
- arbitrary directory targeting
- verbosity flags
- strict-vs-lenient mode switches

The command should be discovery-friendly:

- if no `.csvql.yml` is found by upward discovery from the current working
  directory, the command returns a warning result instead of a hard command
  error
- if a project exists but is incomplete, the command should prefer explicit
  warning or failure probes over opaque exception-only behavior

The command should remain local and deterministic:

- no user-authored SQL
- no external services
- no project mutation
- no hidden repair steps

## Run Status Model

`csvql doctor` should introduce a tri-state run status:

- `passed`
- `warning`
- `failed`

Meaning:

- `passed`: the discovered project is healthy for the narrow readiness contract
  in this spec
- `warning`: no concrete breakage was found, but the project is absent or
  incomplete in a way that should be surfaced clearly
- `failed`: concrete project-health failures were found

Examples:

- no `.csvql.yml` found -> `warning`
- discovered project with zero configured tables -> `warning`
- malformed `.csvql.yml` -> `failed`
- missing configured CSV -> `failed`
- unreadable or invalid CSV for a configured table -> `failed`
- configured check column that does not exist in the discovered schema ->
  `failed`

## Probe Model

`doctor` should be built around a flat ordered list of probes rather than prose
messages or reused data-quality results.

Recommended typed result objects:

- `DoctorProbeResult`
- `DoctorRunResult`

These should live in a dedicated doctor-oriented module or in
`src/csvql/doctor.py`, not in `quality.py`.

Probe fields should include:

- `name`
- `scope`
- `status`
- `message`
- optional scope metadata:
  - `table`
  - `check`
  - `path`
  - `resolved_path`
  - `column`
  - `reference_table`
  - `reference_column`

Recommended stable probe names:

- `project_discovery`
- `config_load`
- `catalog_tables_present`
- `table_readiness`
- `check_schema_resolution`

Probe `name` should stay from a small closed vocabulary. Automation should key
off `name`, `scope`, `status`, and explicit metadata, not parse the free-text
`message`.

Recommended scopes:

- `project`
- `table`
- `check`

`DoctorRunResult` should derive:

- `status`
- `probe_count`
- `passed_count`
- `warning_count`
- `failed_count`

This keeps the contract simple and avoids inventing a full framework.

## Workflow And Component Boundaries

Keep `cli.py` thin and move project-health orchestration into a dedicated
workflow module.

Recommended file responsibilities:

`src/csvql/cli.py`
: add the `doctor` command, call the doctor workflow, render output, and exit
  with the dedicated doctor failure code when the returned run status is
  `failed`

`src/csvql/doctor.py`
: own project discovery handling, probe orchestration, DuckDB readiness checks,
  and static configured-check schema auditing

`src/csvql/output.py`
: add table and JSON formatters for doctor results

`src/csvql/exceptions.py`
: add a dedicated doctor failure exit-code holder if needed for a named exit
  code such as `12`

Reuse existing repo authority instead of recreating logic:

- project discovery and loading from `project_config.py`
- CSV path resolution from `project_config.py`
- DuckDB connection patterns already used by `checks.py` and `profiling.py`
- configured-check column-resolution semantics already established in
  `checks.py`

Do not widen this slice into a shared validation platform.

## Probe Flow

The workflow should run probes in deterministic order and stop only where later
probes would be derivative noise.

### 1. Project Discovery

Start from `Path.cwd()` and perform the same upward project discovery already
used elsewhere in the repo.

Outcomes:

- config found -> `project_discovery` probe `passed`
- no config found -> `project_discovery` probe `warning`, overall run status
  `warning`, and stop

If no config is found, the JSON result should still be well-formed and should
set project paths to `null`.

### 2. Config Load

If a config path is discovered, load and validate it through the existing
project-config path.

Outcomes:

- valid config -> `config_load` probe `passed`
- malformed YAML, unsupported version, invalid alias, invalid check structure,
  unsupported keys, or similar config defects -> `config_load` probe `failed`
  and stop

These are expected doctor findings, not unexpected command crashes.

### 3. Catalog Tables Present

After config load, check whether the project has any configured tables.

Outcomes:

- one or more tables configured -> `catalog_tables_present` probe `passed`
- zero tables configured -> `catalog_tables_present` probe `warning`, overall
  run status `warning`, and stop

This keeps `doctor` useful for a newly initialized but not yet populated
project.

### 4. Table Readiness

For each configured table, in deterministic order by `(table.name.lower(),
table.name)`:

1. resolve the configured path through existing catalog-path logic
2. register the CSV with DuckDB using CSVQL-controlled behavior only
3. run a minimal controlled read such as `SELECT * FROM <view> LIMIT 1`

This should prove actual readability, not only path existence or metadata
binding.

Important rule:

- if the one-row query succeeds but returns zero rows, the probe still `passes`
  because the table is readable even if it is currently empty

Expected failures:

- missing resolved CSV path
- unreadable file
- invalid CSV that DuckDB cannot read
- other controlled DuckDB read failures during readiness proof

Each failure should produce one `table_readiness` probe with `scope=table`
rather than cascading into many secondary failures.

### 5. Static Check-Schema Audit

After table readiness succeeds and column names are known, statically audit
configured checks without executing them.

For each configured check whose required tables passed readiness:

- validate the configured child column against the discovered source table
  columns when the check type requires a column
- validate foreign-key reference target columns against the discovered reference
  table columns
- reuse the same column-resolution semantics as `csvql check`, including
  surrounding-whitespace handling, so doctor does not invent a second schema
  contract

Recommended implementation note:

- if the current `checks.py` helper is too private to reuse cleanly, extract a
  shared column-resolution helper during implementation instead of duplicating
  the logic

Important rule:

- do not execute configured checks, count failing rows, or run business-logic
  validation queries

Noise-control rule:

- if a table readiness probe already failed, omit downstream check-schema probes
  that depend on that broken table instead of generating derivative failures

This keeps the report focused on root causes.

## JSON Contract

`csvql doctor --output json` should emit a stable flat contract meant for real
automation.

Recommended top-level shape:

- `status`
- `probe_count`
- `passed_count`
- `warning_count`
- `failed_count`
- `project`
  - `config_path`
  - `project_root`
- `probes`

Recommended semantics:

- `status` is one of `passed`, `warning`, or `failed`
- `project.config_path` is the absolute path to the discovered `.csvql.yml`, or
  `null` when no project is found
- `project.project_root` is the absolute discovered project root, or `null`
  when no project is found
- `probes` is the ordered source of truth for detailed findings

Recommended probe shape:

- `name`
- `scope`
- `status`
- `message`
- optional metadata fields only when relevant:
  - `table`
  - `check`
  - `path`
  - `resolved_path`
  - `column`
  - `reference_table`
  - `reference_column`

Recommended example shape:

```json
{
  "status": "warning",
  "probe_count": 1,
  "passed_count": 0,
  "warning_count": 1,
  "failed_count": 0,
  "project": {
    "config_path": null,
    "project_root": null
  },
  "probes": [
    {
      "name": "project_discovery",
      "scope": "project",
      "status": "warning",
      "message": "No .csvql.yml project catalog found."
    }
  ]
}
```

Deliberate contract choice:

- do not add a separate top-level `warnings` list

Warning and failure detail should live in the probe list so there is only one
detailed finding channel.

## Table Output

Table output should stay plain and readable.

Recommended structure:

1. summary lines
   - `Status: warning`
   - `Probes: 7 | Passed: 5 | Warnings: 1 | Failed: 1`
2. one flat Rich table with columns such as:
   - `scope`
   - `name`
   - `status`
   - `target`
   - `message`

Recommended target rendering:

- project probes: blank or `.csvql.yml`
- table probes: table alias
- check probes: `table.check_name`

Do not add nested sections, stack traces, or verbose report rendering in this
first slice.

## Exit-Code Contract

Recommended exit behavior:

- `passed` -> exit `0`
- `warning` -> exit `0`
- `failed` -> exit `12`

Why `12`:

- the repo already uses dedicated exit codes for specific command outcomes
- `11` already means data-quality check failures
- `12` cleanly reserves doctor-detected project-health failure

Expected project-health findings should be converted into doctor probes and a
doctor run result rather than leaking out as command-terminating
`ProjectConfigError`, `FileMissingError`, or `CSVInspectionError` exceptions.

Unexpected internal failures should still follow existing exception-handling
behavior and should not be hidden behind a fake doctor result.

## Command, JSON, Exit-Code, Config, Docs, And Test Impact

Command impact:

- adds `csvql doctor`
- does not change existing command semantics

JSON impact:

- adds one new automation-oriented JSON surface for doctor
- does not change existing `query`, `run`, `inspect`, `profile`, `check`, or
  `export` JSON

Exit-code impact:

- adds one dedicated non-zero exit code for doctor failure, recommended `12`
- preserves existing exit-code behavior for other commands

Config impact:

- no `.csvql.yml` schema expansion
- no new project metadata keys

Docs impact:

- yes
- README should document the new command briefly
- architecture docs should record the new workflow boundary
- later failure-gallery docs can reuse real doctor examples

Test impact:

- yes
- add focused unit and CLI tests rather than large snapshots

## Implementation File Boundary

Expected implementation files:

- modify `src/csvql/cli.py`
- create `src/csvql/doctor.py`
- modify `src/csvql/output.py`
- modify `src/csvql/exceptions.py`
- modify `docs/ARCHITECTURE.md`
- modify `README.md`
- add focused tests, likely including:
  - `tests/test_cli_doctor.py`
  - `tests/test_output.py`
  - a focused doctor workflow test file if direct unit coverage is useful

The implementation should avoid unrelated refactors outside these boundaries
unless a tiny helper extraction is required to preserve existing check-column
resolution semantics.

## Testing Strategy

Add focused tests for the public contract and the core workflow rules.

Recommended CLI coverage:

- no catalog found -> JSON/table warning, exit `0`
- valid project with readable tables -> passed, exit `0`
- empty but valid project catalog -> warning, exit `0`
- malformed config -> failed, exit `12`
- missing configured CSV -> failed, exit `12`
- invalid or unreadable CSV -> failed, exit `12`
- configured check column missing from discovered schema -> failed, exit `12`
- foreign-key target column missing from discovered schema -> failed, exit `12`
- zero-row readable CSV still passes table readiness

Recommended unit coverage:

- doctor result model derives counts and top-level status correctly
- probe ordering is deterministic
- JSON serialization shape is stable
- table formatter includes summary counts and probe rows
- downstream check-schema probes are omitted when prerequisite table readiness
  already failed

Avoid large golden snapshots with volatile local-path or timing noise.

## Risks And Guardrails

Risk: `doctor` drifts into executing business logic.

Guardrail:

- no saved SQL
- no configured-check execution
- no full row counts
- no profile metrics
- one controlled row-read proof only

Risk: doctor duplicates `csvql check` column-resolution semantics and creates a
second contract.

Guardrail:

- reuse or extract the same schema-resolution helper used by check execution

Risk: doctor output becomes too clever or too verbose.

Guardrail:

- fixed tri-state run status
- flat ordered probe list
- small closed vocabulary of probe names
- flat table output only

Risk: one broken table creates noisy cascades of redundant failures.

Guardrail:

- report root-cause table-readiness failure first
- omit derivative check-schema probes that depend on broken readiness inputs

## North-Star Fit

This command stays aligned with CSVQL's approved v1 direction.

It helps prove:

- local-first project workflow
- deterministic automation output
- boring but useful CLI product quality

It does not move CSVQL toward rejected scope such as:

- web UI
- cloud connectors
- AI or natural-language SQL
- sandbox claims
- a broad validation platform
- a second execution engine

That makes `csvql doctor` a portfolio-polish feature, not a product-category
expansion.
