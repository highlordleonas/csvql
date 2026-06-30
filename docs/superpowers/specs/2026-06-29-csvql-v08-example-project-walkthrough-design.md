# CSVQL v0.8 Example Project And Walkthrough Design

Status: design approved in conversation; written spec review required before implementation planning.

Date: 2026-06-29

## Purpose

This spec defines the first portfolio-polish slice inside v0.8: replace the
current lightweight sales example with a stronger local analytics project and a
copy/paste walkthrough that proves CSVQL can support a believable automation
workflow.

The goal is not to expand CSVQL's product surface. The goal is to make the
existing surface easier to evaluate by showing a small but real-feeling project
that a hiring manager, teammate, or reviewer could run locally without setup
drama.

This slice should strengthen the CSVQL wedge:

- local-first CSV project workflow
- DuckDB-backed SQL execution through existing CSVQL commands
- deterministic project checks and outputs
- automation-oriented JSON export
- human-readable Markdown export
- reproducible example data

## Subproject Boundary

This spec does not cover all of v0.8.

It covers only the polished example project and walkthrough.

Explicitly out of scope for this slice:

- `csvql doctor`
- the small Python API
- formal JSON contract documentation across all commands
- common failure gallery
- any new CLI command
- any new config schema feature
- any new output format

Those remain valid v0.8 work, but they should be planned separately so this
slice stays focused and executable.

## Product Contract

This slice does not add a new end-user command.

It uses already-implemented CLI behavior only:

- `csvql inspect`
- `csvql profile`
- `csvql check`
- `csvql run`
- `csvql export`

The example project should prove that those commands work together in a coherent
local workflow without changing their public contract.

## User Goal

The target user experience is "real automation user copy/paste."

A user should be able to clone the repo, open the example project, paste a short
sequence of commands, and get:

- project inspection and profiling output
- successful project health checks
- a main revenue-health analysis result
- a JSON artifact that could be passed to another tool or script
- a Markdown sidecar that is easy to read in a PR, note, or local report

The example should read like a small analytics project, not a toy CSV demo.

## Recommended Example Shape

Replace `examples/sales` with a stronger repo-owned example project:

`examples/saas_revenue/`

Recommended contents:

- `examples/saas_revenue/README.md`
- `examples/saas_revenue/.csvql.yml`
- `examples/saas_revenue/data/customers.csv`
- `examples/saas_revenue/data/subscriptions.csv`
- `examples/saas_revenue/data/revenue_movements.csv`
- `examples/saas_revenue/queries/revenue_health.sql`
- at most two supporting SQL files if they make the walkthrough clearer
- `examples/saas_revenue/scripts/regenerate_data.py`
- `examples/saas_revenue/output/` as the documented export target directory

The example directory should be usable on its own. A reader should not need to
hunt through top-level docs to understand what it is, how to run it, or how to
rebuild the data.

## Business Framing And Data Model

The example should model a small B2B SaaS revenue workflow centered on revenue
health rather than generic order totals.

Primary business question:

- what is happening to recurring revenue, churn, expansion, and net retention?

Recommended tables:

1. `customers.csv`
2. `subscriptions.csv`
3. `revenue_movements.csv`

The design intent is:

- `customers` explains who the business serves
- `subscriptions` explains the recurring commercial relationship
- `revenue_movements` explains why MRR changed over time

The data should feel mid-layer and inspectable, not raw event exhaust and not a
fully modeled warehouse mart.

Recommended movement categories:

- `new`
- `expansion`
- `contraction`
- `churn`
- `reactivation`

Implementation can choose exact column names, but the tables should be simple
enough that a user can understand the model by reading the CSV headers and one
saved SQL file.

## Walkthrough Flow

The walkthrough should prioritize the outcome first, then briefly explain the
model behind it.

Recommended command flow:

1. open the example directory
2. inspect one core table
3. profile one core table
4. run project checks
5. run the main saved SQL analysis to JSON in the terminal
6. export the same analysis to `output/revenue-health.json`
7. export the same analysis to `output/revenue-health.md`
8. show the deterministic regeneration command

The main readout should come from one canonical query:

- `queries/revenue_health.sql`

That query should answer the headline business question directly. Supporting SQL
files are allowed only if they make the walkthrough clearer; this should not
become a mini transformation framework.

## Reproducibility Contract

The example should support both instant use and exact regeneration.

Required:

- committed CSV files in the repo for immediate walkthrough use
- one tiny deterministic helper script that regenerates those files exactly

The regeneration workflow should:

- use a fixed seed
- produce deterministic row ordering
- avoid network or external service dependencies
- be easy to run locally with the repo toolchain

The committed CSVs are the primary user experience. The regeneration script is
proof that the example is maintained intentionally rather than hand-edited.

## Config, Checks, And Constraints

The example project's `.csvql.yml` should use only existing config features.

Recommended checks:

- key not-null checks
- key uniqueness checks
- foreign keys from subscriptions and movements back to customers
- accepted movement-type values
- a few cheap business sanity checks such as non-negative recurring revenue
  amounts where appropriate

Do not turn the example into a large assertion suite. The checks should
demonstrate believable project health validation, not replicate a data-quality
platform.

## Command, JSON, Exit-Code, And Config Impact

Command impact:

- no new CLI command
- no renamed command
- no changed command semantics
- the walkthrough uses existing commands only

JSON impact:

- no new JSON contract is introduced by this slice
- the example depends on existing `run`, `inspect`, `profile`, `check`, and
  `export --format json` behavior
- the JSON artifact used in the walkthrough is an example of current automation
  usage, not yet the formal stable JSON contract documentation effort

Exit-code impact:

- no new exit-code behavior
- `csvql check` keeps its current success vs failed-check contract, including
  exit code `11` for configured-check failures
- walkthrough commands should be written so a successful copy/paste path exits
  cleanly on a healthy example project

Config impact:

- no `.csvql.yml` schema expansion
- only new example-project config content

Docs impact:

- yes, substantially
- the example becomes a primary proof surface for portfolio evaluation

Test impact:

- yes, focused end-to-end proof around the example project and walkthrough

## Docs Flow

Keep the docs close to the example.

Recommended structure:

- top-level `README.md`: short entry point that points to the stronger example
- `examples/saas_revenue/README.md`: primary copy/paste walkthrough

The example README should stand on its own and cover:

- what the example models
- the short command sequence
- what each output proves
- where the exported files land, using `output/revenue-health.json` and
  `output/revenue-health.md`
- how to regenerate the data exactly

If an additional top-level docs page is useful, it should point into the example
instead of duplicating the full walkthrough.

## Testing Strategy

Testing should prove the example is real, deterministic, and aligned with the
documented workflow without creating brittle giant snapshots.

Recommended coverage:

- helper-script determinism for regenerated example data
- example config and checks pass on committed data
- main saved query runs successfully
- JSON export smoke for the main walkthrough artifact
- Markdown export smoke for the sidecar artifact
- at least one focused test that the walkthrough's main analysis returns stable,
  representative fields and values

Prefer checking:

- key field names
- output file existence
- row counts or section counts where meaningful
- representative metrics
- deterministic high-signal values

Avoid snapshotting entire large exports unless the payload is intentionally
small.

## Risks And Controls

Main risks:

1. the example still feels toy-sized
2. the example turns into an overbuilt analytics case study
3. the walkthrough depends on undocumented manual setup
4. the example drifts from committed data into hand-maintained fiction

Controls:

- use a believable SaaS revenue-health story, not generic sales totals
- keep one main question and one canonical query
- keep the example runnable from committed CSVs immediately
- include exact deterministic regeneration
- keep all behavior on existing CLI surfaces

## Success Criteria

This slice is successful when:

- `examples/saas_revenue/` reads like a small real local analytics project
- a user can copy/paste the walkthrough and get useful results without editing
  files first
- the example proves inspect, profile, check, run, and export work together
- JSON export is clearly useful for automation-oriented workflows
- Markdown export is clearly useful for human review
- the data can be regenerated exactly from the helper script
- README and example docs point to the same golden path
- no new CLI surface or product-expansion trap is introduced

## What This Proves

If implemented well, this slice proves:

- CSVQL can support a believable local analytics project
- the current CLI surface is composable enough for a small end-to-end workflow
- exported outputs are useful for both automation and human review
- the repo is becoming easier to evaluate as a serious piece of work

It does not prove:

- production BI readiness
- warehouse-scale modeling
- broad domain coverage
- safe execution of untrusted SQL
- large-file performance
- completion of the rest of v0.8
