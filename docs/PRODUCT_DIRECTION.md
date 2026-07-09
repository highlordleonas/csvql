# Product Direction

Status: advisory steering artifact

Date: 2026-06-26
Updated: 2026-07-01

Source: reconciles three external research passes and local adversarial review. This
document does not override `docs/development.md`, `docs/release-readiness.md`,
the current release lane, accepted ADRs, or tests. It exists to keep future
implementation work pointed at the defensible product wedge and away from
attractive but crowded scope.

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

The optional `csvql menu` TUI stays inside the defensible wedge only as a thin
terminal workbench for the same local CSV catalog, trusted SQL, explicit export,
and explicit derived-result-source workflows. It is not a dashboard, notebook,
or broad interactive exploration platform.

## Current Lane

The active implementation lane is LocalQL distribution aliasing for the `csvql`
CLI/import package before v1.0.0 external release action. The repo has already
implemented the core local workflow: query, inspect/sample, project catalogs,
saved SQL, export, profile, configured checks, benchmark and
release-readiness scripts, JSON contract documentation, a polished example
project, `csvql doctor`, a small project-backed Python API, and the optional
Textual-powered `csvql menu` terminal workbench with session-local history,
explicit project catalog save, explicit result export, and explicit derived
result sources under `.csvql/results/{alias}.csv`.

Current work should not add broad new product surface. Pre-release blocker fixes
are in `v1-hardening` while the support and proof contract is refreshed,
including Python 3.13 and Python 3.14 support proof. Every external release
action still requires separate explicit approval:

- keep README, development docs, roadmap, architecture, product direction,
  release readiness, and JSON-contract docs aligned with the runtime surface
- keep the completed failure gallery aligned with deterministic runtime behavior
- keep benchmark and release-readiness proof current before release claims
- avoid pretending publishing is already automated or complete
- rerun the full local gate before any `v1-stable` claim

## Near-Term Direction

The strongest next vertical is v1 release authority and proof hardening, not
more feature expansion.

That slice should include:

- authority repair for stale v0.1-era instructions and docs
- release-readiness checklist work that builds on `docs/release-readiness.md`
- changelog or release-note preparation for the implemented surfaces
- explicit contract decisions for CLI JSON, exit codes, config schema, and the
  small Python API
- authority alignment against the refreshed `uv run` gates, release-readiness
  proof, and benchmark workflow before benchmark-backed or performance claims

That slice must not include:

- additional public CLI commands beyond stabilizing the already documented
  optional `csvql menu` surface
- new config schema features
- runtime JSON normalization without an explicit compatibility decision
- safe mode
- hidden cache or automatic materialization
- dataframe, notebook, async, plugin, cloud, AI, or web scope

## Later Direction

After v1 stabilization, the project should pause for real usage feedback before
expanding. Valid post-v1 candidates remain broader explicit
cache/materialization, additional export formats, broader local file formats, or
a richer Python API, but only after the small v1 surface proves useful. The v1
derived result source action is a narrow explicit CSV artifact workflow, not a
hidden cache layer or dataframe runtime.

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
- Do not implement hidden automatic cache or materialization. The implemented
  TUI derived result source flow is explicit user-controlled CSV artifact
  creation; broader cache/materialization remains later.
- Keep public positioning CSV-focused until the repo actually supports broader
  local data files.
- Keep the v1 Python API small and boring. It should wrap CSVQL's existing
  tested services, not create a separate Python data framework.

## DuckDB Version And Security Posture

DuckDB remains the sole engine for the foreseeable future.

Inspect, profile, check, and doctor now rely on DuckDB CSV handling. A past
DuckDB `sniff_csv` vulnerability was fixed after affected `1.0.0` releases. The
v1 contract-stabilization slice raises the package dependency floor to
`duckdb>=1.5.0,<2`, matching the current DuckDB 1.5.x lockfile family while
avoiding silent acceptance of old 1.0-era engines or a future DuckDB major
version.

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

1. Treat the current runtime as LocalQL with refreshed local candidate proof,
   but no external release action or `v1-stable` claim.
2. State command, JSON, exit-code, config, docs, and test impact before
   implementation.
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

- Target lane: v1 hardening, v1 release, post-v1 backlog, or explicit new scope.
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
