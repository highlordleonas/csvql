# CSVQL v0.7 Benchmark And Release Hardening Design

Status: design approved in conversation; written spec review required before implementation planning.

Date: 2026-06-29

## Purpose

CSVQL v0.7 strengthens the project as a trustworthy local tool by adding benchmark
evidence, reproducible benchmark inputs, packaging proof, and release-readiness
verification without expanding the end-user runtime feature set.

The release should make CSVQL easier to evaluate honestly:

- benchmark-backed for a bounded set of existing workflows
- reproducible on the user's machine
- buildable as a distributable package
- installable and runnable outside the source tree
- explicit about what is still not proven

This slice should strengthen the CSVQL wedge without changing the product
category. DuckDB still owns SQL execution. CSVQL still owns the local workflow,
table aliasing, project catalog behavior, deterministic output, docs, and tests.

## Product Contract

v0.7 does not add new public end-user CLI commands.

Instead, it adds repo-local hardening workflows around the existing CLI:

- benchmark runner for selected CSVQL commands
- reproducible synthetic benchmark project generation
- machine-readable benchmark artifact
- Markdown benchmark summary generated from the artifact
- package build smoke
- installed-wheel smoke
- version consistency verification
- manual release-readiness checklist

Expected repo-local entrypoints:

```bash
uv run python scripts/benchmark_csvql.py ...
uv run python scripts/render_benchmark_summary.py ...
```

The exact packaging smoke command can be chosen during implementation, but the
proof requirement is fixed: CSVQL must build a wheel and sdist successfully and
the built wheel must run in an isolated environment without depending on the
repo source tree being importable.

## Scope Boundary

v0.7 is a proof-and-hardening release, not a feature release.

Included:

- benchmark harness for a representative subset of existing commands
- deterministic synthetic benchmark projects derived from a fixed seed
- artifact and summary generation
- build/install/version proof
- release-readiness documentation and verification guidance

Excluded:

- new user-facing CLI features such as `csvql doctor`
- Python API work
- config schema changes
- existing command JSON contract changes
- exit-code taxonomy changes
- changelog policy as a required stable repo surface
- publish automation, GitHub release automation, or PyPI workflow
- benchmark claims beyond recorded local evidence
- any sandbox, production, untrusted-SQL, or large-file safety claim

## Contracts Touched

Commands:

- existing user-facing commands should remain behaviorally unchanged
- new benchmark and summary workflows should live in repo-local scripts, not a
  public `csvql benchmark` command

JSON:

- existing command JSON for `query`, `inspect`, `sample`, `run`, `export`,
  `profile`, and `check` must remain unchanged
- v0.7 introduces a new benchmark artifact JSON shape only

Exit codes:

- no new public CLI exit-code contract in v0.7
- benchmark verification should treat command success as a runner concern, not a
  new CLI surface

Config:

- no `.csvql.yml` contract changes

Docs/tests:

- yes, heavily; this release is mostly proof, reproducibility, and verification

## Benchmark Coverage

The benchmark suite should measure representative existing workflows, not every
command equally.

Recommended benchmark cases:

1. `query` against a single CSV with aggregate and group-by output to JSON
2. `run` against a saved SQL file in a catalog-backed project, output to JSON
3. `inspect --output json` in default bounded mode
4. `inspect --exact --output json`
5. `profile --output json`
6. `check --output json` on configured project checks without `--show-failures`

Benchmark exclusions:

- `init`, `add`, and `tables`: verify through tests and smoke usage, not
  benchmark focus
- table-output rendering: keep covered by tests, not benchmark headline
- `export`: keep as build/install/smoke proof and regression coverage, not a
  primary benchmark claim
- `sample`: useful behaviorally, but lower-value for first benchmark evidence
  than full-scan and query workflows

The benchmark cases should target the happy path only. `check` benchmarks should
run against passing checks so the benchmark suite measures runtime behavior
instead of a failure-reporting exit path.

## Benchmark Input Tiers

The current bundled example project is too small to support meaningful
performance claims on its own, so v0.7 must include deterministic synthetic data
generation.

Recommended input tiers:

- `fixture`: current `examples/sales` project exactly as shipped
- `synthetic_medium`: generated sales-like project with approximately 10,000
  customers and 100,000 orders
- `synthetic_large`: generated sales-like project with approximately 50,000
  customers and 500,000 orders

Synthetic benchmark projects should include:

- `data/customers.csv`
- `data/orders.csv`
- `.csvql.yml`
- saved SQL files used by benchmarked `run` cases
- passing configured checks used by the benchmarked `check` case

Generation rules:

- fixed random seed
- deterministic row ordering
- repeatable value distributions
- no dependence on external services or downloaded data
- file contents sufficient to exercise joins, grouping, full scans, and passing
  configured checks

The synthetic projects should look like a scaled version of the existing sales
example, not a disconnected micro-benchmark dataset.

## Benchmark Runner Design

The benchmark runner should be a repo-local Python script, not a public CLI
command.

Runner behavior:

- invoke CSVQL via `sys.executable -m csvql ...` so the benchmark measures CSVQL
  CLI behavior instead of `uv` startup overhead
- generate or refresh synthetic benchmark inputs before measurement
- run one warm-up iteration plus five measured iterations per case
- capture raw wall-clock timing per measured run
- compute summary statistics per case: median, minimum, and maximum
- record command arguments, input tier, dataset characteristics, and outcome
- validate that each command succeeded and emitted structurally valid output

Measurement boundary:

- measure end-to-end CLI wall-clock time
- do not benchmark by importing internal services directly
- do not rely on existing command `elapsed_ms` payloads as the primary timing
  source because not all benchmarked commands emit that field

Artifact metadata should record:

- timestamp
- platform
- Python version
- DuckDB version
- CSVQL version
- warm-up count
- measured iteration count
- benchmark invocation details

## Benchmark Artifact Shape

The benchmark JSON artifact is the source of truth for reported results.

Recommended top-level shape:

```json
{
  "metadata": {},
  "datasets": [],
  "cases": [],
  "notes": []
}
```

`metadata` should include:

- CSVQL version
- DuckDB version
- Python version
- platform information
- benchmark runner version or schema version
- run timestamp
- warm-up and measured iteration policy

`datasets` should describe each input tier:

- dataset id
- seed
- row counts by file
- file sizes
- generation parameters

`cases` should include one entry per benchmark case and input tier combination:

- case id
- human-readable label
- command arguments
- input tier id
- measured run timings
- summary metrics
- command result sanity fields when useful, such as row count or status

`notes` should include explicit caveats:

- results are local evidence from one machine and environment
- results are not universal performance guarantees
- v0.7 does not prove large-file readiness beyond the recorded artifact

## Markdown Summary Design

The Markdown summary should be generated from the benchmark artifact, not hand
maintained separately.

The summary should:

- identify the machine and environment succinctly
- list the benchmark matrix and dataset tiers
- report median/min/max timing per case
- describe relative patterns conservatively
- point readers to the raw JSON artifact as the authoritative record

The summary must not:

- market CSVQL as generally fast
- claim large-file proof beyond the tested datasets
- hide machine-specific limitations
- introduce metrics that are not present in the JSON artifact

Acceptable summary language:

- full-scan commands scale materially with dataset size
- the saved-SQL path tracks the query workflow closely on the synthetic projects
- benchmark evidence in this repo is local and rerunnable

Unacceptable summary language:

- CSVQL is large-file proven
- CSVQL is production ready
- CSVQL is optimized for big data

## Release-Proof Design

v0.7 should prove that CSVQL is buildable, installable, and version-consistent
without pretending the project needs automated publishing yet.

Required proof surfaces:

- version consistency across `pyproject.toml`, `src/csvql/__init__.py`, and
  `csvql --version`
- successful package build for sdist and wheel
- isolated installed-wheel smoke run
- short manual release-readiness checklist

Installed-wheel smoke requirements:

- use an isolated temporary environment
- install the built wheel instead of importing from the repo checkout
- run `csvql --version`
- run one short CLI command such as a tiny `query` or `inspect` against a local
  CSV fixture

The implementation may choose the exact isolated-install command, but the proof
must show that the wheel works without the repo source tree on `PYTHONPATH`.

## Verification Target

The implementation plan for v0.7 should preserve the existing quality gates and
add focused hardening verification.

Base gates:

- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run mypy src`
- `uv run pytest`

New focused checks:

- deterministic synthetic data generation tests
- benchmark case-definition validation tests
- Markdown summary rendering tests
- version-consistency verification
- package build smoke
- isolated installed-wheel smoke
- benchmark runner produces JSON artifact and Markdown summary from the same run

CI posture for v0.7:

- keep the existing quality gates in CI
- do not run the benchmark matrix on every push or pull request
- package build smoke may move into CI later if it stays fast and deterministic

## File And Output Layout

Recommended new tracked files:

- `scripts/benchmark_csvql.py`
- `scripts/render_benchmark_summary.py`
- `tests/test_benchmarking.py`
- `docs/benchmarking.md`
- `docs/release-readiness.md`

Recommended generated output location:

- `output/benchmarks/<run-id>/`

Expected generated outputs per run:

- benchmark artifact JSON
- benchmark summary Markdown
- generated synthetic benchmark project files if they are preserved for
  inspection rather than cleaned up automatically

This default location fits the current repo because `output/` is already
ignored. Repeated local benchmark runs should not create noisy git diffs.

## Artifact Policy

v0.7 should default to untracked local benchmark evidence, not committed
canonical benchmark records.

Policy:

- tracked docs define the benchmark process and interpretation rules
- generated benchmark results live under ignored `output/`
- the repo does not require a checked-in canonical benchmark artifact in v0.7
- benchmark generation remains manual and explicit

This keeps machine-specific results out of routine diffs while preserving a
repeatable workflow.

If the project later wants a curated checked-in benchmark record, that decision
belongs closer to `v1.0.0` when the release narrative and verification
environment are more deliberate.

## Documentation Expectations

`docs/benchmarking.md` should explain:

- benchmark scope and benchmarked cases
- dataset tiers and generation philosophy
- exact rerun commands
- artifact layout
- interpretation rules and forbidden claims

`docs/release-readiness.md` should explain:

- version consistency checks
- build smoke steps
- isolated install/run smoke steps
- when to rerun benchmarks
- what v0.7 does and does not prove

README changes, if any, should stay modest and honest:

- CSVQL now has benchmark and release-hardening workflows
- no broad performance or release-readiness claims beyond the documented proof

## Rejected Alternatives

Rejected for v0.7:

- a public `csvql benchmark` command
- automatic benchmark execution in the main CI path
- checked-in volatile benchmark artifacts by default
- publish automation or release pipeline work
- changelog process as a new required stable surface
- feature work such as `doctor` or Python API bundled into this release

These are either premature ceremony or they widen the release into a partial
`v0.8`/`v1.0` project.

## Direction Check

Target lane:

- `v0.7.0 - Benchmark And Release Hardening`

Wedge strengthened:

- repeatability
- deterministic evidence
- local trusted workflow
- distributable-package proof

Scope rejected:

- new runtime features
- publish automation
- broad release ceremony
- unsupported safety or performance claims

Contracts touched:

- new benchmark artifact JSON only
- docs, scripts, and verification surfaces

Verification target:

- existing repo gates
- focused benchmark and packaging proof

## Success Criteria

v0.7 is successful when:

- benchmark runs are reproducible from tracked docs
- the project can generate meaningful local evidence for selected workflows
- the wheel builds and runs outside the repo checkout
- existing command contracts remain unchanged
- docs describe the proof precisely without exaggeration

v0.7 is not successful if it adds release ceremony without evidence, or if it
uses benchmark work as an excuse to widen product scope.
