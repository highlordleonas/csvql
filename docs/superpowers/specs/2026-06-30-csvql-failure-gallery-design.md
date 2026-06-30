# CSVQL v0.8/v1 Failure Gallery Design

Status: design approved in conversation; written spec review required before
implementation planning.

Date: 2026-06-30

## Purpose

This spec defines the failure-gallery slice in the current post-v0.7/v0.8
hardening lane toward v1.

The goal is to make CSVQL easier to evaluate and troubleshoot by documenting
common deterministic failure cases across the existing CLI and small Python API.
The gallery should show what fails, why it fails, the current exit code or
exception behavior, and the smallest useful correction.

This slice strengthens the CSVQL wedge:

- stable local workflow
- deterministic errors
- honest trusted-local-SQL posture
- user-facing proof that failures are deliberate rather than incidental
- v1 documentation readiness without widening product scope

## Product Contract

The failure gallery is documentation and test-hardening work. It does not add a
new command, change an exit code, normalize JSON, or redesign the error model.

The gallery documents current runtime behavior for common failures. Runtime
truth wins. If live CLI output differs from existing docs or assumptions, the
implementation plan should document the mismatch and either:

1. update the docs to match current intentional behavior, or
2. stop and call out a separate behavior-fix decision when the runtime behavior
   appears wrong.

Behavior changes should not be hidden inside this docs slice.

## Scope Boundary

Included:

- create `docs/failure-gallery.md`
- link the gallery from `README.md`
- mark the roadmap failure-gallery item implemented after the gallery exists
- capture real CLI output during implementation and normalize volatile paths in
  the docs
- map every documented failure family to existing or new focused tests
- add or strengthen tests only where a documented failure has weak or missing
  coverage

Excluded:

- new public CLI commands
- command behavior changes
- exit-code redesign
- JSON contract normalization
- machine-generated gallery scripts
- checked-in generated output artifacts
- full formal error taxonomy
- Python API-specific exception hierarchy changes
- safe-mode or sandbox claims

## Recommended Approach

Use a docs-first failure gallery with proof tests.

This is preferable to a generated gallery script because the immediate missing
artifact is user-facing documentation, not tooling. A script could reduce drift
later, but it would add ceremony before the gallery shape is proven.

This is also preferable to a formal error taxonomy first because the repo
already has concrete errors, tests, and exit codes. The v1 hardening need is to
make those failures understandable and visibly tested without inventing a larger
compatibility framework.

## Gallery Entry Shape

Each entry in `docs/failure-gallery.md` should use one repeatable structure:

- scenario: what the user did wrong or what project state is broken
- command: one minimal command that triggers the failure
- expected exit code: current CLI behavior
- expected message shape: stable prefix or key phrase, with volatile paths
  normalized in prose
- why it fails: short explanation tied to CSVQL's boundary
- how to fix: one concrete correction
- covered by: existing or new test file that proves the documented behavior

The gallery should be practical. It should not require users to understand
internal exception classes before fixing a command.

## Failure Families

The first gallery should cover these failure families.

### Missing CSV Path

Cover at least one direct-path failure and one project-catalog or table-mapping
failure.

Expected proof points:

- missing file exit code remains `4`
- message clearly identifies the missing CSV path or project table context
- fix points the user to the correct path, `csvql tables`, or project catalog
  entry

### Bad Table Mapping Or Alias

Cover common bad `--table` usage:

- mapping without `=`
- empty CSV path
- unsafe alias such as a hyphenated or digit-leading alias when provided
  directly

Expected proof points:

- table mapping failures use the existing table-mapping error path
- message includes a usable `--table name=path` suggestion where current runtime
  provides one
- the gallery distinguishes generated safe aliases in single-file mode from
  user-provided invalid aliases

### Query Failure

Cover a DuckDB query failure such as:

- missing table
- missing column
- invalid SQL syntax

Expected proof points:

- query execution keeps the current query error behavior
- docs state that user-authored SQL is trusted local SQL and passed through to
  DuckDB
- fix points to checking table aliases, column names, and SQL syntax

### Missing Or Invalid Project Catalog

Cover project workflow failures:

- no `.csvql.yml` for commands that require a project
- malformed YAML or invalid config shape
- invalid configured table or check definition

Expected proof points:

- project-config failures keep the current project-config exit code path
- `csvql doctor` is documented separately because no catalog is a warning for
  doctor but an error for project-required commands
- fix points to `csvql init`, `csvql add`, or correcting the config

### Missing Or Unusable SQL File

Cover saved-SQL workflow failures:

- missing SQL file for `csvql run`
- missing SQL file for `csvql export`
- empty or unreadable SQL file if already covered by existing tests

Expected proof points:

- SQL file failures keep the current saved-SQL exit code path
- fix points to creating a non-empty SQL file and running from the intended
  project directory

### Export Overwrite Protection

Cover an existing export output path without `--force`.

Expected proof points:

- overwrite protection keeps the current export error path
- docs explain that CSVQL will not clobber an existing output unless explicitly
  requested
- fix points to choosing a new output path or adding `--force`

### Data-Quality Check Failure

Cover a configured check failure.

Expected proof points:

- `csvql check` exits `11` when configured checks execute successfully but find
  data-quality failures
- docs distinguish data-quality failure from runtime failure
- docs mention `--show-failures` as a way to inspect capped sampled failures

### Doctor Project-Health Failure And Warning

Cover both doctor outcomes:

- warning with exit `0`, such as no project catalog found
- concrete project-health failure with exit `12`, such as malformed config,
  missing configured CSV, unreadable CSV, or configured check column missing

Expected proof points:

- docs explain that doctor warnings are not command failures
- docs explain that doctor failure is project-health failure, not check
  execution
- docs point users to the flat probe list in JSON output for automation

### Python API Error Propagation

Include a short section for the small Python API.

Expected proof points:

- API methods raise existing `CSVQLError` subclasses instead of process exit
  codes
- `session.check(...)` returns `CheckRunResult` for check failures rather than
  raising just because checks failed
- docs should not duplicate every CLI failure as API examples

## Documentation Style

The gallery should be concise and repair-oriented.

Recommended sections:

1. scope and safety model
2. CLI exit-code quick reference for documented cases
3. failure examples grouped by workflow
4. Python API notes
5. test/proof note explaining that examples are backed by focused tests

Command snippets should use `uv run csvql ...` to match repo-local development
docs. When examples require a project directory, use the polished
`examples/saas_revenue` project when possible. Use tiny temporary fixtures in
implementation only when an example would be clearer than mutating the shipped
example project.

Docs may normalize volatile values:

- absolute paths
- temp directory names
- timestamps
- exact DuckDB wording when only a stable CSVQL prefix is intended

Docs must not normalize contract-relevant fields:

- exit code
- command name
- option name
- stable error prefix
- stable recommendation or suggestion wording when current runtime provides one

## File Boundary

Expected implementation files:

- create `docs/failure-gallery.md`
- modify `README.md` to link the gallery
- modify `docs/ROADMAP.md` to move the failure-gallery item from remaining to
  implemented
- modify focused tests only where coverage is missing or too weak for a
  documented scenario

Likely test files to inspect before adding new tests:

- `tests/test_cli_query.py`
- `tests/test_table_mapping.py`
- `tests/test_cli_project_catalog.py`
- `tests/test_cli_run_export.py`
- `tests/test_cli_check.py`
- `tests/test_cli_doctor.py`
- `tests/test_api.py`
- `tests/test_sql_file.py`
- `tests/test_export.py`

No intended runtime-source changes:

- `src/csvql/*.py`
- `.csvql.yml` schema
- command semantics
- output formatting logic

If implementation uncovers a genuine runtime bug, stop and make that a separate
implementation decision instead of folding behavior repair into the gallery.

## Testing Strategy

Every documented failure family should map to a test.

Preferred test assertions:

- process exit code for CLI behavior
- stable error-message substrings
- stable JSON fields for doctor and check examples where JSON output is used
- existing exception class for API behavior
- result status for API `check(...)` behavior

Avoid:

- full terminal output snapshots with box drawing or path noise
- exact DuckDB internal error strings except where current CSVQL intentionally
  exposes them as part of the message
- checking absolute temp paths
- adding broad golden fixtures just for documentation

The implementation plan should start with a coverage map: scenario, current
test coverage, gap, and proposed test action.

## Verification Target

Required checks for the implementation plan:

- capture real CLI output for every documented CLI scenario
- normalize volatile values in docs without changing contract-relevant fields
- `git diff --check`
- focused tests for newly covered or strengthened scenarios
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run mypy src`
- `uv run pytest`

If full gates cannot run, the handoff must say which command was skipped or
failed and what remains unverified.

## Risks And Controls

Risk: the gallery becomes a second, contradictory error contract.

Control:

- runtime truth wins
- document current behavior
- avoid redesigning exit codes or messages inside this slice

Risk: docs drift because examples are hand-written.

Control:

- require real CLI output capture during implementation
- map every documented family to tests
- prefer stable substrings over brittle snapshots

Risk: the slice turns into behavior repair.

Control:

- no intended runtime-source changes
- stop and call out runtime bugs separately

Risk: the gallery scares users with too much detail.

Control:

- lead each entry with repair guidance
- group examples by workflow
- keep Python API notes short and conceptual

## Success Criteria

This slice is successful when:

- `docs/failure-gallery.md` exists and is linked from README
- the roadmap no longer lists the failure gallery as missing
- each documented failure family has current CLI output and a coverage mapping
- common user mistakes have clear fix guidance
- data-quality failures, project-health failures, runtime errors, and API
  exceptions are clearly distinguished
- no new product surface or error-model redesign is introduced
- the standard repo gate passes before implementation is called complete

It is not successful if it uses documentation as cover for unreviewed behavior
changes, or if it creates a broad compatibility framework before v1 needs one.
