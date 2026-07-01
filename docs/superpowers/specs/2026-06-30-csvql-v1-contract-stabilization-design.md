# CSVQL v1 Contract Stabilization Design

Status: design approved in conversation; written spec review required before
implementation planning.

Date: 2026-06-30

## Purpose

This spec defines the v1 contract-stabilization slice for CSVQL.

CSVQL is in post-v0.7/v0.8 hardening toward v1. The core local workflow is
implemented: query, inspect, sample, project catalogs, saved SQL, export,
profile, configured checks, doctor, JSON contract documentation, failure
gallery documentation, benchmark and release-readiness scripts, example-project
walkthroughs, and a small `CSVQLSession` Python API.

The next job is to stabilize and document the existing contracts while adding
project-backed Python API parity for the implemented workflow. This should make
v1 honest and useful without turning CSVQL into a broader data platform.

This slice strengthens the CSVQL wedge:

- repeatable local CSV projects
- deterministic CLI and JSON behavior
- stable project catalog behavior
- stable small Python automation surface
- explicit DuckDB support posture
- release-candidate proof that is current, local, and repeatable

## Approved Direction

Use the conservative contract-freeze approach with one bounded API expansion:

- keep current v0.8 JSON shapes stable for v1
- keep current exit-code behavior stable for v1
- keep `.csvql.yml` as strict `version: 1` with no migration framework
- raise the DuckDB dependency floor to `duckdb>=1.5.0,<2`
- expand `CSVQLSession` to cover project-backed `tables`, `inspect`, `sample`,
  and `export`
- preserve the trusted-local-SQL posture
- keep `v1-hardening` as the status label until implementation and proof are
  complete

The normalized JSON envelope currently documented in `docs/json-contracts.md`
remains a possible future direction, not a v1 runtime change.

## Scope Boundary

Included:

- dependency-floor update for DuckDB
- Python API parity methods for the project-backed workflow
- docs updates that state the frozen v1 contracts clearly
- tests for the added API behavior and current contract guarantees touched by
  this slice
- release-readiness proof after implementation

Excluded:

- JSON envelope migration
- exit-code redesign
- `.csvql.yml` schema migration framework
- direct CSV path mode in the Python API
- ad hoc Python API table mappings
- config mutation helpers in the Python API
- dataframe helpers
- async API
- plugin API
- persistent session-level DuckDB connection
- safe mode or sandbox claims
- cache or materialization
- web, cloud, notebook, AI, or dashboard scope
- release-candidate or v1-stable claim before fresh proof

## Stable CLI Contracts

### JSON Output

The current v0.8 JSON shapes remain stable for v1.

Stable surfaces:

- `csvql query --output json`
- `csvql run --output json`
- `csvql export --format json`
- `csvql inspect --output json`
- `csvql sample --output json`
- `csvql profile --output json`
- `csvql check --output json`
- `csvql doctor --output json`
- `csvql tables --output json`

Current shape differences are intentional contract facts for v1. Examples:

- query-shaped results expose top-level `columns`, `rows`, `row_count`, and
  `elapsed_ms`
- `inspect.row_count` is structured metadata
- `profile.row_count` is an integer
- `check.failures` is conditional and sampled
- machine-local source paths, timestamps, and elapsed time remain volatile
  values

Implementation should update docs and tests to make these shapes explicit, not
normalize them.

### Exit Codes

The current exit-code map remains stable for v1:

- `0`: success, including doctor warnings and zero configured checks
- `1`: general CSVQL error and DuckDB query execution failure
- `4`: missing CSV file
- `6`: invalid table mapping or table alias
- `7`: inspect or sample failure
- `8`: project catalog discovery, parsing, or validation failure
- `9`: saved SQL file failure
- `10`: export path or export format failure
- `11`: configured data-quality checks ran and found failures
- `12`: doctor found concrete project-health failures

The implementation should document this map in the appropriate user-facing
surface and keep focused tests aligned with runtime behavior.

### Project Config Schema

The v1 `.csvql.yml` schema remains strict `version: 1`.

Supported top-level keys:

- `version`
- `tables`

Supported table keys:

- `path`
- `checks`

There is no v1 migration framework, no alternate config filename, and no new
project schema feature in this slice.

## DuckDB Support Contract

DuckDB remains CSVQL's only SQL engine.

The dependency should move from `duckdb>=1.0.0` to:

```toml
"duckdb>=1.5.0,<2"
```

Rationale:

- current product direction identifies the old `>=1.0.0` range as too broad
- the lockfile currently resolves DuckDB 1.5.x
- v1 should not accept old engine versions that the docs already treat as
  questionable
- a minor-family floor avoids pinning v1 to one patch release
- `<2` avoids silently accepting a future major DuckDB compatibility break

This does not make CSVQL sandboxed or safe for untrusted SQL. DuckDB SQL remains
trusted local input and may access local resources depending on DuckDB features
and settings.

## Python API Contract

The v1 Python API should provide project-backed parity for the core repeatable
workflow. It should not become a dataframe framework or a second execution
model.

Public API:

```python
from csvql import CSVQLSession

session = CSVQLSession.from_config(".")

session.tables()
session.query("SELECT COUNT(*) AS row_count FROM orders")
session.run_file("queries/report.sql")
session.inspect("orders", exact=False)
session.sample("orders", limit=10)
session.profile("orders")
session.check(table=None, show_failures=False, failure_limit=5)
session.export(
    "queries/report.sql",
    "output/report.json",
    format="json",
    force=False,
)
```

Required signatures:

- `CSVQLSession.from_config(start_dir: str | Path = ".") -> CSVQLSession`
- `session.tables() -> ProjectTablesResult`
- `session.query(sql: str) -> QueryResult`
- `session.run_file(path: str | Path) -> QueryResult`
- `session.inspect(table: str, *, exact: bool = False) -> InspectResult`
- `session.sample(table: str, *, limit: int = 10) -> SampleResult`
- `session.profile(table: str) -> ProfileResult`
- `session.check(table: str | None = None, *, show_failures: bool = False, failure_limit: int = 5) -> CheckRunResult`
- `session.export(sql_file: str | Path, out: str | Path, *, format: ExportFormat | str, force: bool = False) -> Path`

### API Semantics

`from_config()`
: discovers and stores the nearest project context.

`tables()`
: returns the existing project table listing as `ProjectTablesResult`.

`query()`
: runs trusted SQL against the stored project catalog tables.

`run_file()`
: resolves the SQL file relative to the stored project root, then runs it
  against the stored project catalog tables.

`inspect()`
: accepts a configured table alias only, resolves it through the stored project
  context, and returns `InspectResult`.

`sample()`
: accepts a configured table alias only, enforces the existing positive limit
  rule, and returns `SampleResult`.

`profile()`
: accepts a configured table alias only and returns `ProfileResult`.

`check()`
: runs configured project checks and returns `CheckRunResult`. Failed checks do
  not raise an exception; result status is the pass/fail contract.

`export()`
: resolves the SQL file and output path relative to the stored project root,
  runs the saved SQL against the stored project catalog tables, writes UTF-8
  text in `csv`, `json`, or `markdown` format, preserves overwrite protection
  with `force=False`, and returns the resolved output `Path`.

### API Error Contract

The Python API reuses existing `CSVQLError` subclasses directly.

Expected examples:

- missing project config raises `ProjectConfigError`
- invalid project config raises `ProjectConfigError`
- missing CSV paths raise `FileMissingError`
- bad SQL raises `QueryExecutionError`
- missing or empty SQL files raise `SQLFileError`
- inspect/sample failures raise `CSVInspectionError`
- invalid export output raises `ExportError`
- failed configured checks return `CheckRunResult` instead of raising

No API-only exception hierarchy is added in this slice.

## Architecture

`CSVQLSession` remains a thin project-backed wrapper in `src/csvql/api.py`.

It stores `ProjectContext`, not a persistent DuckDB connection. Each method
delegates to existing services and performs short-lived work:

- `project_config.py` for project discovery, loading, table listing, and table
  path resolution
- `engine.py` and `query_workflow.py` for SQL execution
- `sql_file.py` for saved SQL loading
- `inspection.py` for inspect and sample
- `profiling.py` for profile
- `checks.py` for configured checks
- `export.py` for export path validation, serialization, and writes

The implementation may add a small private helper in `api.py` to resolve a
catalog alias to `CSVSource`, because `inspect`, `sample`, and `profile` should
share that behavior.

The implementation should not move CLI formatting or process-exit behavior into
the API.

## Documentation Impact

Required docs updates:

- `README.md`: update Python API example and v1 hardening status if needed
- `docs/ARCHITECTURE.md`: document the expanded `api.py` boundary
- `docs/PRODUCT_DIRECTION.md`: keep the contract freeze and local workflow
  scope aligned
- `docs/ROADMAP.md`: list contract stabilization and expanded project-backed
  API parity as the remaining v1 slice until implemented
- `docs/json-contracts.md`: state that current v0.8 JSON shapes are stable for
  v1 and normalized envelope remains future-facing
- `docs/release-readiness.md`: keep label rules and proof commands aligned

Docs must not claim:

- sandbox safety
- production readiness
- large-file performance beyond local benchmark artifacts
- release-candidate
- v1-stable

## Testing Strategy

Add or extend focused tests for:

- `CSVQLSession.tables()` returns `ProjectTablesResult`
- `CSVQLSession.inspect()` returns `InspectResult` for a catalog alias
- `CSVQLSession.inspect(exact=True)` returns exact row-count metadata
- `CSVQLSession.sample()` returns `SampleResult` for a catalog alias
- `CSVQLSession.sample(limit=0)` preserves the existing failure behavior
- `CSVQLSession.export()` writes CSV
- `CSVQLSession.export()` writes JSON matching query-shaped output
- `CSVQLSession.export()` writes Markdown
- `CSVQLSession.export()` refuses overwrite without `force=True`
- `CSVQLSession.export(..., force=True)` overwrites intentionally
- invalid aliases or missing project paths propagate existing `CSVQLError`
  subclasses
- the package root exposes the documented API types needed for import examples

Also keep existing CLI JSON and exit-code tests green. Runtime CLI behavior
should not change in this slice.

## Implementation File Boundary

Likely source files:

- `pyproject.toml`
- `uv.lock` if dependency resolution changes it
- `src/csvql/api.py`
- `src/csvql/__init__.py`

Likely test files:

- `tests/test_api.py`
- focused existing tests only if imports or contract assertions need adjustment

Likely docs:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/PRODUCT_DIRECTION.md`
- `docs/ROADMAP.md`
- `docs/json-contracts.md`
- `docs/release-readiness.md`

Generated proof output under `output/` should stay ignored.

## Verification Target

Implementation should run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

If the dependency-floor change requires resolver or build access and the sandbox
blocks dependency work, the implementation should rerun the necessary command
with explicit escalation rather than weakening the dependency decision.

## Success Criteria

- current JSON shapes are explicitly stable for v1
- current exit codes are explicitly stable for v1
- current project config schema is explicitly stable for v1
- DuckDB support posture is enforced through packaging, not only prose
- the Python API covers the core project-backed workflow
- added API methods reuse existing service behavior
- CLI behavior is unchanged
- docs do not widen the product or claim unsupported safety/performance labels
- release-readiness proof is fresh after implementation

## Open Risks

- `duckdb>=1.5.0,<2` may update `uv.lock`; that is acceptable only if the
  resolver proof is explicit and the diff is reviewed.
- `export()` adds filesystem writes to the Python API. The design contains that
  risk by requiring project-root-relative output resolution, existing overwrite
  protection, and return of the resolved output path.
- Expanding the API increases v1 support burden. The design contains that risk
  by excluding direct-path mode, config mutation, dataframes, async, and plugins.
