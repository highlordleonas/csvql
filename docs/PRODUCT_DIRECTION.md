# Product Direction

Status: advisory steering artifact

Date: 2026-06-26

Source: reconciles three external research passes and local adversarial review. This
document does not override `AGENTS.md`, the current release lane, accepted ADRs, or
tests. It exists to keep future implementation work pointed at the defensible
product wedge and away from attractive but crowded scope.

## Reconciled Verdict

CSVQL is worth building only as a narrow local-first workflow tool, not as a
generic "SQL on CSV" wrapper.

The defensible product is:

> A repeatable DuckDB-powered CLI for local CSV projects: inspect files, map
> them to stable table aliases, run trusted SQL, emit deterministic automation
> output, and later promote repeatable work into project configuration, exports,
> and checks.

The weak product is:

> A friendlier DuckDB CLI for querying CSV files.

DuckDB, qsv, sqlite-utils, csvkit, Miller, xan, VisiData, pandas, Polars,
Frictionless, Great Expectations, Soda, and dbt already cover much of the broad
CSV/query/profile/check space. CSVQL should not compete on command breadth,
interactive exploration, enterprise data quality, notebooks, dashboards, cloud
connectors, or natural-language SQL.

## Current Lane

The active implementation target remains `v0.1`: query local CSV files through
DuckDB with table aliases, JSON/table output, typed boundaries, clear CLI
errors, and focused tests.

Do not use this document to pull later features into `v0.1`.

`v0.1` should become stable by proving:

- missing-file, bad-mapping, invalid-alias, and query-failure behavior
- JSON and Rich table output behavior
- README examples and security language
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run mypy src`
- `uv run pytest`

Before calling `v0.1` stable, decide whether current query JSON should gain a
minimal `schema_version` or remain intentionally unversioned until the
inspect/sample contract. Do not let this decision expand into a full JSON
framework.

## Near-Term Direction

After `v0.1` is stable, the next useful vertical is Inspect and Sample.

That slice should include:

- a resolved CSV source model
- cheap default source fingerprint fields, such as version, size, and modified
  timestamp
- explicit opt-in for content hashing because it reads the file
- `csvql inspect <path>`
- `csvql sample <path>`
- DuckDB-backed dialect and column inference
- bounded/default row-count status, with exact row count only by explicit flag
- table and JSON output
- typed sniff/parse/source errors
- focused messy CSV fixtures
- docs that preserve the trusted-SQL boundary

That slice must not include:

- `.csvql.yml`
- project catalog commands
- saved SQL execution
- export commands
- profiling
- data quality checks
- cache or materialization
- safe mode
- Markdown/report output
- Python API

## Later Direction

After Inspect and Sample, the strongest order remains:

1. Project catalog and saved SQL: `.csvql.yml`, table registration, project root
   discovery, `csvql run`.
2. Export: explicit user-requested CSV, JSON, Markdown, or Parquet artifacts.
3. Profiling: lightweight deterministic summaries only after inspect/sample and
   catalog behavior are stable.
4. Checks: SQL/configured checks with stable JSON and exit codes; avoid building
   a Great Expectations, Soda, Frictionless, or dbt clone.
5. Benchmark and release hardening: only publish performance or large-file
   claims after reproducible benchmark evidence exists.
6. Portfolio polish and a small Python API: make the repository easy to
   understand, demo, and evaluate without changing the product category.

The small Python API is now part of the v1 target, but only as a thin library
boundary over the same internals that power the CLI. It should expose project
configuration, trusted SQL execution, saved SQL files, profiling, and checks
without introducing dataframe integrations, notebook helpers, plugins, async
execution, a query builder, cloud access, or a second execution engine.

Portfolio polish should demonstrate product maturity rather than add broad new
features. Favor a polished example project, stable JSON contract documentation,
common failure examples, and a focused project-health command over UI, cloud, AI,
or framework scope.

## Non-Negotiable Guardrails

- DuckDB owns SQL execution. CSVQL owns local workflow, source resolution, table
  aliasing, output rendering, deterministic errors, docs, and tests.
- Keep `cli.py` thin.
- Keep DuckDB connection and query execution in `engine.py`.
- Keep generated identifier validation outside user-authored SQL.
- Treat user SQL and future project config as trusted local code.
- Do not claim sandboxing, safe execution of untrusted SQL, production
  isolation, or large-file performance without proof.
- Do not implement safe mode without a separate ADR, threat model,
  implementation plan, and tests.
- Do not implement hidden automatic cache or materialization. Later cache work
  must be explicit user-controlled behavior.
- Keep public positioning CSV-focused until the repo actually supports broader
  local data files.
- Keep the v1 Python API small and boring. It should wrap CSVQL's existing
  tested services, not create a separate Python data framework.

## DuckDB Version And Security Posture

DuckDB remains the sole engine for the foreseeable future.

Future `inspect` work is likely to use DuckDB CSV sniffing. A past DuckDB
`sniff_csv` vulnerability was fixed after affected `1.0.0` releases. The
current lockfile resolves DuckDB `1.5.4`, but `pyproject.toml` currently allows
`duckdb>=1.0.0`. Before shipping sniff-based inspect behavior, raise or document
the minimum supported DuckDB version so vulnerable versions are not accepted.

This does not make CSVQL a sandbox. DuckDB SQL can read and write files and may
access external resources depending on settings and extensions. CSVQL is a local
automation tool for trusted projects.

## Contract Discipline

Stable automation output is part of the wedge, but contract work must be
proportional.

Use stable JSON contracts for command outputs intended for scripts or CI. Avoid
golden snapshots that include volatile values such as elapsed time unless those
fields are normalized or explicitly excluded.

Every implementation plan that changes a command should state:

- command behavior changed
- JSON fields changed
- exit codes changed
- docs changed
- tests proving the changed contract

Do not import exit-code taxonomies from research notes blindly. Current source
and tests are implementation truth until a deliberate compatibility decision
replaces them.

## Codex Steering

The reconciled Codex-ops research is correct about the moat: CSVQL should be
boring, deterministic, and contract-aware. It is wrong when it asks the repo to
grow hooks, custom agents, local skills, broad verification scripts, or a full
JSON-contract framework before the current lane is stable.

Future Codex sessions should use this order:

1. Stabilize the active `v0.1` query lane.
2. State command, JSON, exit-code, docs, and test impact before implementation.
3. Use one accountable implementer, with bounded read-only review when useful.
4. Add deterministic scripts, hooks, repo-local skills, or custom agents only
   after repeated failures show that existing repo authority is insufficient.

## Scope Drift Rejection List

Reject or defer these unless the user explicitly opens a new product strategy:

- "dbt-lite" public positioning
- broad CSV command suites
- custom transform DSLs
- custom check DSLs
- safe mode or sandbox claims
- cloud connectors
- web UI or dashboard
- notebook integration
- AI or natural-language SQL execution
- second execution engine
- hidden cache/materialization
- performance claims without benchmark artifacts
- dataframe-first Python API design
- plugin systems or async session APIs before real usage demands them

## Implementation Steering Checklist

Every future implementation plan should include a short direction check:

- Target lane: `v0.1`, `v0.2`, later roadmap, or explicit new scope.
- Wedge strengthened: repeatability, source identity, deterministic output,
  stable errors, or local trusted workflow.
- Scope rejected: specific tempting items not included in this slice.
- Contracts touched: commands, JSON fields, exit codes, config schema.
- Verification target: exact `uv run ...` checks or focused CLI commands.

If a change does not strengthen the wedge or stabilize the current lane, it is
probably docs-only, backlog, or out of scope.

## Research Still Needed

Do not do more generic market research. Validate the narrow wedge:

- Would target users choose CSVQL over DuckDB CLI plus Makefile?
- Do they value stable JSON output enough to adopt a new tool?
- Do they create project config and saved SQL, or only inspect once?
- Is cheap metadata fingerprinting enough, or do users need opt-in content hash?
- Is a minimal SQL-based check model enough, or do they immediately demand a
  larger data quality framework?

Evidence that should weaken or stop the product:

- users only want one-off CSV inspection
- users prefer DuckDB CLI, qsv, sqlite-utils, notebooks, or Excel
- users ask primarily for GUI, cloud, AI, or broad wrangling commands
- users do not rerun projects or care about stable contracts

Evidence that should strengthen the product:

- users commit project config and SQL files
- users run JSON output in scripts or CI
- users ask for source drift and fingerprint history
- users compare CSVQL favorably against DuckDB CLI plus Makefile
