# CSVQL v0.8 JSON Contracts Documentation Design

Status: design approved in conversation; written spec review required before implementation planning.

Date: 2026-06-29

## Purpose

This spec defines the JSON contracts documentation slice inside v0.8 portfolio
polish.

The goal is to make CSVQL easier to evaluate as a deterministic local
automation tool by documenting the current JSON outputs for the existing
automation-oriented command surfaces, while also defining the ideal normalized
`v1` contract direction.

This slice should strengthen the CSVQL wedge:

- stable local automation usage
- honest command-output documentation
- explicit current-vs-future contract boundaries
- test-backed contract discipline without pretending current output is already
  normalized

## Deliverable Choice

The agreed v0.8 deliverable is:

- current contract first, ideal `v1` second
- docs only, not JSON Schema
- no breaking runtime changes in this slice

That means this release documents the current JSON exactly as shipped, then adds
an explicit future-facing section that describes the ideal normalized `v1`
contract and the per-command gap between `v0.8` and that target.

## Product Contract

This slice does not add or change a public CLI command.

It documents only the current JSON outputs for these existing surfaces:

- `csvql query --output json`
- `csvql run --output json`
- `csvql inspect --output json`
- `csvql profile --output json`
- `csvql check --output json`
- `csvql export --format json`

The contract doc is user-facing documentation for automation-oriented output. It
is not yet a machine-readable schema, and it is not a compatibility promise for
the ideal `v1` contract shape.

## Scope Boundary

Included:

- one contract document for the agreed automation JSON surfaces
- exact documentation of current runtime JSON behavior
- examples taken from real CLI output with clearly labeled redactions for
  machine-specific values
- explicit notes about stable vs volatile fields
- one future-facing `v1` section describing the ideal normalized contract
- focused test strengthening where current JSON coverage is too thin

Excluded:

- any public CLI behavior change
- any current runtime JSON normalization in code
- `sample` JSON documentation
- `tables` JSON documentation
- benchmark artifact JSON documentation
- machine-readable JSON Schema files
- Python API result-shape documentation
- exit-code redesign
- contract versioning implementation

## Current Contract Documentation Rules

The contract document must follow these rules:

1. Runtime truth wins.
   - The `v0.8` section documents the JSON exactly as the CLI emits it today.
   - The docs must not smooth over inconsistencies by prose alone.

2. Scope is command-output only.
   - Cover only `query`, `run`, `inspect`, `profile`, `check`, and
     `export --format json`.

3. Stable vs volatile fields are labeled explicitly.
   - Fields such as `elapsed_ms` are current output, but volatile and unsafe for
     exact automation assertions.

4. Absence matters.
   - If a field is omitted in runtime output, the doc must say omitted, not
     `null`.
   - Example: `check.failures` appears only when failure samples are requested
     and present.

5. Shared current shapes are described where they already exist.
   - `query`, `run`, and JSON export currently share the same `QueryResult`
     payload family.

6. Current mismatches are documented, not hidden.
   - Example: `inspect.row_count` is structured metadata, while
     `profile.row_count` is an integer.

7. Example redaction is allowed only for presentation noise.
   - Machine-local paths, timestamps, and volatile timing values may be
     redacted or annotated.
   - Field names, nesting, omission behavior, and scalar types must remain
     exact.

8. The ideal `v1` contract is advisory only in this slice.
   - The docs may recommend normalization, but they must not imply that the
     current runtime already exposes that normalized shape.

## Recommended Documentation Structure

Create one primary document:

- `docs/json-contracts.md`

Recommended sections:

1. `Scope and guarantees`
   - what commands are covered
   - what is documented as current truth
   - what is future-facing only

2. `Current v0.8 contract by command`
   - one section per covered command
   - example payload
   - field-by-field notes
   - stable vs volatile field notes

3. `Cross-command rules in v0.8`
   - shared conventions that already exist
   - explicit mismatches that still exist

4. `Ideal v1 normalized contract`
   - one concise proposed future envelope
   - explanation of why it is cleaner

5. `Delta from current v0.8 to ideal v1`
   - per-command migration notes
   - no implementation promised in this slice

## Covered Command Families

The current contract doc should group commands by the shapes they already share.

### Query-Shaped Results

These currently share the same JSON family:

- `query`
- `run`
- `export --format json`

Current shape:

- `columns`
- `rows`
- `row_count`
- `elapsed_ms`

Important notes:

- `rows` is record-oriented JSON keyed by column name
- `row_count` is the number of returned rows, not a source-file row count
- `elapsed_ms` is part of current output but volatile

### Inspect

Current shape includes:

- `source`
- `dialect`
- `columns`
- `row_count`
- `warnings`

Important notes:

- `row_count` is a structured object with `mode`, `value`, and `exact`
- source metadata includes machine-local details such as resolved paths and file
  fingerprints

### Profile

Current shape includes:

- `source`
- `row_count`
- `column_count`
- `duplicate_row_count`
- `columns`
- `warnings`

Important notes:

- `row_count` is an integer here, not structured metadata
- column entries include null, distinct, and min/max metrics

### Check

Current shape includes:

- `status`
- `check_count`
- `passed_count`
- `failed_count`
- `checks`
- `warnings`

Important notes:

- `checks[*].failures` is conditional
- zero-check warnings are part of the contract
- pass/fail semantics are in the payload itself, not only in exit codes

## Ideal v1 Contract Direction

For `v1`, the recommended automation envelope is:

- `schema_version`
- `command`
- `data`
- `warnings`
- `meta`

Recommended rules for the ideal future shape:

- `data` contains the semantic result the caller actually wants
- `warnings` is always present and always a list
- `meta` contains volatile or operational details such as elapsed time, source
  identity, and machine-local provenance
- command-specific verdicts remain inside `data`
- `query`, `run`, and `export --format json` converge on one shared table-result
  family
- `inspect` and `profile` stop disagreeing about where count and source metadata
  live
- absolute paths and machine-local details move out of the core business payload

This slice does not implement that shape. It only documents it and maps the gap
from current `v0.8`.

## File Boundary

Expected implementation files for the later plan:

- Create: `docs/json-contracts.md`
- Modify: `README.md` only if a new documentation link is added
- Modify: focused test files if contract coverage is thin
  - likely `tests/test_output.py`
  - possibly `tests/test_cli_query.py`
  - possibly `tests/test_cli_run_export.py`
  - possibly `tests/test_cli_inspect_sample.py`
  - possibly `tests/test_cli_profile.py`
  - possibly `tests/test_cli_check.py`

No intended changes:

- `src/csvql/*.py`
- command semantics
- output formatting logic

## Verification Requirements

This slice must prove documentation accuracy, not just write prose.

Required verification:

1. Doc-to-runtime checks
   - every documented current-contract example comes from real CLI output
   - machine-local values may be redacted or annotated only where necessary

2. Test-backed structural coverage
   - strengthen or add focused JSON assertions for:
     - query-shaped results
     - inspect
     - profile
     - check with and without failure samples
   - avoid brittle full golden snapshots with volatile fields

3. Standard repo gate
   - `uv run ruff format --check .`
   - `uv run ruff check .`
   - `uv run mypy src`
   - `uv run pytest`

## Risks And Mitigations

### Contract-Freeze Risk

Risk:
- the docs could accidentally bless current awkward shapes forever

Mitigation:
- keep `current v0.8 contract` and `ideal v1 contract` as separate sections

### Volatile-Field Risk

Risk:
- the docs could encourage automation that depends on `elapsed_ms`, absolute
  paths, or timestamps

Mitigation:
- label stable vs volatile fields explicitly
- treat volatile fields as documentation facts, not assertion targets

### Scope-Creep Risk

Risk:
- the slice could sprawl into schemas, `sample`, `tables`, benchmark artifacts,
  or Python API docs

Mitigation:
- keep the covered command list fixed
- reject machine-readable schemas in this slice

### Silent-Drift Risk

Risk:
- docs can go stale if not paired with tests

Mitigation:
- strengthen focused structural JSON tests alongside the docs

## Out Of Scope Follow-On Work

These remain valid later work, but are not part of this design:

- JSON Schema publication
- runtime normalization toward the ideal envelope
- `sample` or `tables` contract docs
- benchmark artifact contract docs
- Python API result object contract docs
- breaking JSON cleanup before `v1`

## Success Criteria

This slice is successful when:

- `docs/json-contracts.md` documents the current JSON truth for the agreed six
  automation surfaces
- the doc clearly separates current `v0.8` behavior from the ideal `v1`
  contract
- tests back the documented structural behavior without relying on volatile
  values
- no public CLI behavior changes are introduced
- the standard repo gate passes
