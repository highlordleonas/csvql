# CSVQL V1 Polish Program Design

Status: design approved in conversation; written spec review required before
implementation planning.

Date: 2026-07-02

## Purpose

This spec defines a final v1 polish program for CSVQL's existing local-first
CSV workflow.

The goal is to make CSVQL feel trustworthy and immediately useful for a new
local CSV user: install it, query a file, open the optional TUI, iterate on SQL,
save a useful derived result, understand what happened, and leave with
confidence that the tool is honest about its limits.

This is a polish and proof lane, not a product-expansion lane. It should improve
the experience around the product that already exists rather than turn CSVQL
into a broader data platform.

## Chosen Direction

The approved direction is **V1 Polish Program with implementation lane**.

The program covers six ordered passes:

1. first-user delight
2. TUI ergonomics
3. derived-source mental model
4. manual release matrix
5. docs claim scan
6. release trust proof

The implementation lane that follows this spec should be scoped to polish and
proof only. It may touch docs, tests, TUI help/status/key affordances,
release-readiness proof output, manual QA documentation, and small behavior
fixes discovered during proof. It must not add new platform scope.

## Product Boundary

CSVQL remains a local-first Python CLI and package for querying local CSV files
through DuckDB.

In scope:

- first-user onboarding and README flow
- CLI-only reusable-result documentation
- TUI key/help/status polish
- derived-source clarity
- manual QA and release matrix
- unsupported-claim scans
- release-readiness proof alignment
- focused tests or docs-proof checks for changed behavior

Out of scope:

- pandas or Polars dependencies
- Parquet reads or writes
- hidden cache or automatic materialization
- safe mode or sandbox behavior
- production-readiness claims
- web app, dashboard, notebook, AI, or plugin surface
- telemetry or product analytics instrumentation
- public Python API expansion
- broad project catalog schema redesign

User-authored SQL remains trusted local SQL. CSVQL does not restrict DuckDB
capabilities or sandbox filesystem access.

## Six Passes

### 1. First-User Delight

Make the first ten minutes obvious:

- install or run commands through `uv`
- one-file query
- project catalog query
- optional TUI launch
- first successful query
- first export or derived source

The README should guide a user to value, not merely enumerate command surfaces.
The first path should be short, copyable, and consistent with the actual CLI.

### 2. TUI Ergonomics

Treat Mac terminal and function-key variance as real.

The TUI should prioritize reliable bindings, visible footer/help text, clear
status messages, and manual proof for key flows. This lane should not add major
editor features unless they remove friction from an already implemented
workflow.

The TUI remains optional. A user who does not want a terminal UI must still have
a clear CLI-only path.

### 3. Derived-Source Mental Model

Original CSV sources and derived query-result sources must be distinguishable
wherever the user can see or reason about them.

The user should understand:

- TUI-derived result sources are explicit CSV files under
  `.csvql/results/{alias}.csv`.
- The TUI can show those sources with `kind=derived` during the current session.
- The saved CSV file remains on disk.
- The alias is session-local unless sources are explicitly saved.
- Current `.csvql.yml` catalog persistence stores a CSV path and does not
  preserve rich source-kind metadata.

### 4. Manual Release Matrix

Define a compact, repeatable human QA checklist for real workflows:

- CLI single-file query
- CLI project catalog query
- CLI export and reuse as a CSV source
- TUI launch
- TUI repeated query
- TUI derived save and query
- bad SQL
- SQL that completes with no tabular result
- export overwrite refusal and `--force`
- missing file behavior
- quit behavior
- Mac keybinding paths

The matrix should be small enough to actually run before release decisions.

### 5. Docs Claim Scan

Scan authority docs and user-facing docs for unsupported claims.

The following claims block the release-polish gate unless they are explicitly
scoped as non-claims or future work:

- sandbox safety
- safe execution of untrusted SQL
- production readiness
- security isolation
- broad large-file performance
- hidden cache or automatic materialization
- externally shipped `v1-stable` status

Docs should continue using precise labels such as `v1-hardening`, local release
state, `release-candidate eligible`, `release-candidate`, and `v1-stable`.

### 6. Release Trust Proof

Finish with hard proof:

- format check
- lint
- typecheck
- full pytest
- release-readiness proof
- benchmark evidence or explicit same-HEAD benchmark citation
- manual matrix result
- unsupported-claim scan
- diff review
- final status boundary confirmation

Until those gates pass on the final intended HEAD, docs should not claim
`v1-stable`.

## CLI-Only Reusable Result Path

The CLI already supports the practical reusable-result workflow. The polish
program should make it explicit so the TUI does not become the only documented
path.

Example:

```bash
uv run csvql export queries/top_orders.sql \
  --format csv \
  --out .csvql/results/top_orders.csv

uv run csvql add top_orders .csvql/results/top_orders.csv

uv run csvql query "SELECT * FROM top_orders"
```

Users can also reuse an exported result without catalog persistence:

```bash
uv run csvql query \
  --table top_orders=.csvql/results/top_orders.csv \
  "SELECT * FROM top_orders"
```

This path should be documented as normal CSV reuse. It is not a typed
derived-source catalog feature because the current catalog schema stores table
paths, not source-kind metadata.

## TUI-Assisted Reusable Result Path

The TUI path remains:

1. open `csvql menu`
2. run SQL
3. save the last successful tabular result as a derived source
4. see the saved alias in Sources with `kind=derived`
5. query or join the alias in the same TUI session
6. optionally save sources to persist the alias path in `.csvql.yml`

If the alias is persisted to `.csvql.yml`, a later catalog reload treats it as a
normal CSV table path unless a future catalog metadata design changes that
contract.

Both CLI and TUI paths write local files only after an explicit user action.
There is no hidden cache, automatic materialization, or dataframe runtime.

## Architecture And File Boundaries

Runtime execution remains:

- Typer CLI boundary in `cli.py`
- DuckDB execution in engine and workflow layers
- optional Textual TUI over existing CSVQL workflows
- derived sources as explicit CSV files under `.csvql/results/{alias}.csv`

Expected implementation file zones:

- `README.md`
- `CHANGELOG.md`
- `docs/release-notes/v1.md`
- `docs/release-readiness.md`
- `docs/ROADMAP.md`
- `docs/PRODUCT_DIRECTION.md`
- `docs/ARCHITECTURE.md`
- `src/csvql/tui_help.py`
- `src/csvql/tui_app.py`
- `src/csvql/release_readiness.py`
- `scripts/verify_release_readiness.py`
- focused tests such as `tests/test_tui_app.py` and
  `tests/test_release_readiness.py`
- a manual QA checklist doc, either as a new file or a clearly bounded section
  in `docs/release-readiness.md`

Files that should not be touched unless a proof-blocking bug is found:

- `src/csvql/cli.py`
- `src/csvql/engine.py`
- `src/csvql/session.py`
- `pyproject.toml`
- `uv.lock`
- project catalog schema code
- public Python API contracts

Implementation must preserve the current dirty tree and must not commit
`.superpowers/` unless Richard separately approves a tracked-artifact decision.

## Error Handling Polish

Failure cases are part of the product experience.

Expected polish:

- CLI docs show export overwrite behavior and mention `--force`.
- TUI save-result errors remain specific:
  - no prior result
  - no tabular result
  - invalid alias
  - duplicate alias
  - existing file
- Docs clarify that catalog persistence of a derived result is explicit and
  stores a CSV path, not rich source metadata.
- Missing-file, bad SQL, and no-result SQL behavior appear in the manual matrix.

## Verification Target

Focused checks should cover any changed behavior.

Full local gate:

```bash
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

Release proof:

```bash
uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

The final implementation plan should also include a stale-claim scan across the
authority docs and a final `git status --short --branch` snapshot.

## Release Status Rules

This program may produce release-candidate evidence. It does not publish a
release.

Do not tag, publish to PyPI, create a GitHub release, upload artifacts, or claim
externally published `v1-stable` in this lane.

Use `v1-hardening` or local release state wording until final gates pass on the
intended release HEAD and Richard explicitly approves any later release action.

## Follow-On Implementation Lane

After Richard reviews and approves this written spec, invoke the
`superpowers:writing-plans` skill and create a task-by-task implementation plan.

The implementation plan should:

1. audit the current dirty tree and preserve unrelated work
2. identify the smallest docs/TUI/proof edits that satisfy the six passes
3. add or update focused tests before behavior edits where behavior changes are
   needed
4. write or update the manual release matrix
5. run focused checks, full local gates, release-readiness proof, and manual
   proof
6. finish with a status and diff review

No implementation work should begin before that plan exists and is approved.
