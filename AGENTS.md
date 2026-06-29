# CSVQL Project Instructions

## Scope

CSVQL is a Python CLI and package for querying local CSV files through DuckDB. DuckDB owns SQL execution; this repo owns CLI workflow, table aliasing, output formatting, tests, docs, and later project configuration.

## Current Implementation Target

The active implementation target is v0.1:

- `csvql query --table name=path "SELECT ..."`
- single-file shortcut: `csvql query data/orders.csv "SELECT ..."`
- DuckDB in-memory execution
- Rich table output and JSON output
- typed internal boundaries and clear CLI errors
- focused unit and CLI integration tests

Do not implement project config, profiling, data quality checks, exports, shell, doctor, persistent cache, safe mode, or Python API until the v0.1 surface is stable.

`v0.1-stable` means:

- CLI behavior is documented in `README.md`.
- Missing-file, bad-mapping, invalid-alias, and query-failure errors are covered by tests.
- JSON and Rich table output behavior are covered by tests.
- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` pass.
- Docs make no unsupported sandbox, security-isolation, production-readiness, or large-file performance claims.

## Tooling

- Use `uv` for dependency management and command execution.
- Keep dependencies in `pyproject.toml`; keep `uv.lock` intentional once generated.
- Do not install global packages.
- Prefer `uv run` for local checks.

Expected local gates:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

## Architecture Rules

- Keep `cli.py` as a thin Typer boundary.
- Keep DuckDB connection and query execution in `engine.py`.
- Keep parsing and validation of table mappings outside the CLI command body.
- Validate generated table aliases before passing them to DuckDB.
- Resolve CSV paths before execution and fail loudly for missing files.
- Treat user-authored SQL as trusted local SQL unless safe mode is explicitly implemented and tested.
- Do not claim safe sandbox behavior.

## Source Pack

`csvql_project_pack/` and `csvql_project_pack.zip` are input artifacts, not runtime source. Copy useful content into normal repo files before relying on it.

## Skill Activation Contract

Use relevant repo-local, global, plugin, and Superpowers skills intentionally. Select by task, but bias toward the local Python CLI, DuckDB, CSV inspection, testing, documentation, and evidence-backed product-quality stack.

Before code or docs changes, read active repo authority first: this `AGENTS.md`, relevant docs, tests, and existing source patterns.

Default stack for non-trivial CSVQL work:

- `python-codebase-standards`
- `testing-strategy` or `qa-test-planner`
- `verification-before-completion`
- `documentation` or `readme` when docs or user-facing behavior changes

Mandatory skill triggers:

- Python modules, CLI code, packaging, dependencies, typing, or tests: `python-codebase-standards`
- DuckDB execution, SQL behavior, table aliasing, CSV path handling, or user input boundaries: `python-codebase-standards`; add `security-best-practices` for path, SQL, safe-mode, or untrusted-input work
- CLI UX, errors, output formats, examples, README, roadmap, or architecture docs: `documentation`, `readme`
- Inspect, profile, check, or data-quality features: `data-quality`; add `quality-scoring` only when scoring or thresholds are explicit
- Benchmarking, cache, compression, large-file behavior, or Rust-extension discussion: `performance-engineering`, with benchmark evidence before design claims
- Product workflow, repeatable analytics, project catalogs, or saved SQL: `analytics-product`, `data-products`, `requirements-clarity`
- Durable architecture decisions: `architecture-decision-records`
- Review or security gates: `code-review`, `security-best-practices`, `differential-review` when appropriate
- Superpowers: use when explicitly invoked or when the task fits brainstorming, writing-plans, test-driven-development, systematic-debugging, verification-before-completion, or branch finishing
- GitHub, PR, and CI tools: only when requested or needed

If a mandatory skill is unavailable, stop and state the missing skill before proceeding, unless the user explicitly approves a fallback.

Every implementation handoff must list skills used, verification commands run, skipped checks, and remaining risk.

Authority precedence:

- Direct user instruction and current-session boundaries come first.
- Then this `AGENTS.md` and any nested `AGENTS.override.md`.
- Then `README.md`, `docs/PRODUCT_DIRECTION.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, and accepted ADRs.
- Tests and source code are implementation truth.
- `docs/CODEX_CAPABILITY_REVIEW.md` guides capability selection but does not expand product scope by itself.
- `csvql_project_pack/` and `csvql_project_pack.zip` are input artifacts, not runtime or authority source.
- Subagent notes, brainstorming notes, and generated handoffs are evidence only; main-agent synthesis and tracked repo files decide.

Scope guardrails:

- CSVQL is local-first: CSV files, DuckDB, CLI workflow, typed Python boundaries, useful output, repeatable tests.
- `docs/PRODUCT_DIRECTION.md` records the reconciled research verdict and implementation steering checklist; use it as advisory scope guardrail, not as permission to skip the active release lane.
- Do not turn v1 into a web app, cloud connector platform, multi-tenant/auth system, dashboard product, NLP execution engine, or Rust performance project without evidence and explicit scope approval.
- Treat user-authored SQL as trusted local SQL until safe mode is explicitly designed, implemented, and tested.
- CSVQL does not restrict DuckDB capabilities, sandbox filesystem access, or make untrusted SQL safe.
- Do not claim sandboxing, security isolation, production readiness, or large-file performance without proof.
- Add cache/materialization only as explicit user-controlled behavior, not hidden automatic state.
- Use `uv` for all local execution. Do not install global packages.
- Keep changes small, reversible, and backed by focused tests.
- Prefer coherent vertical batches over one-command micro-slices when related behavior can be reviewed and verified together safely.

Codex operating model:

- Treat external research reports, generated plans, subagent notes, and brainstorming notes as advisory evidence only. They do not redefine the active lane or product scope.
- For implementation planning, start with the `docs/PRODUCT_DIRECTION.md` direction gate: target lane, wedge strengthened, scope rejected, contracts touched, and verification target.
- Prefer one accountable implementer for code changes. Use subagents or reviewer roles only for bounded scouting, test drafting, or read-only final review.
- Keep product direction, JSON contract shape, exit-code policy, security posture, and roadmap sequencing in the main agent's synthesis.
- Do not add repo-local `.codex/hooks`, `.codex/agents`, `.agents/skills`, Codex GitHub Actions, or broad verification scripts until a repeated failure is documented and the user explicitly approves that new authority surface.
- Determinism and trustworthy contracts are the moat, but contract machinery must stay proportional to the current lane. Do not build a full JSON-contract, exit-code, hook, or agent framework before `v0.1` is stable.

Readiness and proof language:

- Use precise labels: `docs-ready`, `local-cli-proof-ready`, `test-backed`, `benchmark-backed`, `release-candidate`, `v0.1-stable`.
- Do not claim `production-safe`, `sandbox-safe`, `large-file-proven`, `portfolio-grade`, or `v1-ready` from docs, fixtures, or one happy-path query.
- A feature is not stable until CLI behavior, errors, JSON/table output where relevant, docs, and tests agree.
