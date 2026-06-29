# CSVQL v1 Expanded Roadmap Design

Date: 2026-06-29

## Objective

Expand the CSVQL v1 target from a working local CLI into a polished portfolio-ready
local data tool while preserving the product wedge: local CSV projects, DuckDB
execution, repeatable configuration, deterministic outputs, and trusted local
workflows.

## Approved Direction

CSVQL v1 should showcase backend/Python engineering, data workflow judgment, and
developer-tooling discipline. The project should look like a coherent product,
not a collection of unrelated demos.

The v1 roadmap now includes:

- the already implemented CLI surfaces through data-quality checks
- benchmark and release hardening
- portfolio polish and example walkthroughs
- stable JSON contract documentation
- a common failure gallery
- a focused `csvql doctor` project-health command
- a small Python API that wraps existing CLI-tested internals

## Python API Boundary

The Python API belongs in v1 only as a small, stable library surface:

- `CSVQLSession.from_config(".csvql.yml")`
- `session.query(sql)`
- `session.run_file(path)`
- `session.profile(table)`
- `session.check(table=None)`
- small typed result objects for rows, columns, profiles, and checks

The API must not become a dataframe framework, notebook integration layer, async
runtime, plugin system, query builder, cloud connector, or second execution
engine. It should reuse existing project config, query workflow, profiling, and
check services rather than duplicate CLI behavior.

## Portfolio Polish Boundary

Portfolio polish should make the current product easier to evaluate:

- polished example project with realistic local CSVs
- reproducible commands that exercise query, inspect, sample, run, export,
  profile, and check
- JSON contract docs for automation-oriented outputs
- failure gallery for common user mistakes and deterministic errors
- benchmark artifacts and Markdown report with precise proof language
- changelog and release workflow

This work should not add a web UI, cloud connectors, AI/NL SQL, safe-mode claims,
dbt-like transformation graphs, Great Expectations-style suites, hidden cache, or
another execution engine.

## Roadmap Shape

The approved remaining roadmap is:

1. `v0.7.0 - Benchmark And Release Hardening`
2. `v0.8.0 - Portfolio Polish And Python API`
3. `v1.0.0 - Stable Release`
4. post-v1 future expansion only after v1 has real usage feedback

## Success Criteria

- Roadmap and product-direction docs agree on v1 scope.
- Every new feature strengthens repeatability, deterministic output, stable
  errors, local trusted workflow, or portfolio evaluation.
- Claims remain evidence-backed: no sandbox, production, untrusted-SQL, or
  large-file claims without specific proof.
- Implementation plans state command, JSON, exit-code, config, docs, and test
  impact before code changes.
