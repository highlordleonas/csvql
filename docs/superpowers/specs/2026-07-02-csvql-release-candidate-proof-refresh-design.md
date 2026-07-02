# CSVQL Release Candidate Proof Refresh Design

## Status

Design approved in conversation on 2026-07-02. Written spec review is required
before implementation planning.

Repo state at the design-writing baseline:

- Branch: `main`
- Pre-spec HEAD: `e2456b9 fix: preserve tui results on rejected runs`
- Tracked tree: clean
- Existing proof note target:
  `8ede1ef test: align tui ddl metadata proof`
- Current release posture: `v1-hardening` until proof is refreshed at the
  current candidate state

## Goal

Refresh the local release-candidate eligibility proof for the current CSVQL
candidate state and record the result in a tracked proof note.

The target proof commit is current `main` at
`e2456b9 fix: preserve tui results on rejected runs`, unless HEAD advances
before execution. If HEAD advances, the proof must record the new exact commit
and continue only if that change is intentional for the candidate.

## Lane Position

Source Intelligence v1, Editor Quality v2, and the narrow TUI error-recovery
polish are implemented, verified, reviewed, and committed.

The previous release-candidate proof packet is stale because later TUI polish
moved HEAD after the recorded proof target. This lane exists to re-run proof
against the actual candidate state, not to add more product scope.

## Product Boundary

CSVQL remains a local-first Python CLI and package for querying local CSV files
through DuckDB. This proof refresh changes no runtime behavior.

User-authored SQL remains trusted local DuckDB SQL. This work must not claim or
add safe mode, sandboxing, security isolation, production readiness, hidden
cache, broad materialization, dataframe runtime, cloud connectors, web UI,
notebooks, AI, plugins, or broad large-file performance proof.

This proof refresh must not publish packages, create tags, upload artifacts,
create a GitHub release, change the package version, or claim `v1-stable`.

## Problem

The tracked proof note currently says CSVQL is `release-candidate eligible`
based on an older proof target. Since then, TUI behavior changed. The old proof
is useful history, but it is not sufficient evidence for the current candidate
state.

Without a refreshed proof packet, the honest status is still `v1-hardening`.

## Scope

Included:

- Reconfirm repo truth, branch, HEAD, tracked-tree cleanliness, and ignored
  artifact posture.
- Rerun the full local gate.
- Rerun the release-readiness proof.
- Rerun benchmark proof and capture same-HEAD benchmark artifact paths.
- Rerun or deterministically prove the manual v1 QA matrix, including the
  newer TUI editor, source-intelligence, and rejected-run recovery behavior.
- Rerun unsupported-claim scans across authority docs.
- Refresh `docs/release-candidate-proof-2026-07-02.md` with observed current
  evidence only.
- Classify the result as `release-candidate eligible`, `v1-hardening`, or
  `blocked`.

Excluded:

- Product behavior changes.
- Runtime source changes.
- CLI, Python API, DuckDB engine, or project catalog changes.
- Version bump, tag, publish, upload, GitHub release, or `v1-stable` action.
- Hidden materialization, cache, safe-mode, sandbox, production, cloud, web,
  notebook, dataframe, AI, or plugin scope.
- Committing generated proof artifacts under `output/`, `.csvql/`, `.local/`,
  `.superpowers/`, or temporary TUI proof roots.
- Repairing docs or code inside the proof lane if a blocker is found.

## Proof Contract

The proof refresh is a candidate evaluation lane.

It may produce one tracked human-readable proof note:

- `docs/release-candidate-proof-2026-07-02.md`

It may also produce ignored local evidence:

- `output/release-readiness/**`
- `output/benchmarks/**`
- `.csvql/results/**`
- example-project output files
- temporary TUI harness roots under `/private/tmp`

The final proof note must include:

- baseline repo truth;
- exact HEAD and branch;
- automated command results and exit codes;
- release-readiness artifact paths;
- benchmark artifact paths;
- manual QA results;
- unsupported-claim scan classification;
- generated artifact posture;
- blockers, if any;
- risks and caveats;
- next task.

The note must not include guessed results, placeholder text, chat-only claims,
or stale proof copied forward without rerunning or explicitly identifying it as
history.

## Evidence Flow

Proof execution should use the existing release-readiness authority:

- `docs/release-readiness.md`
- `docs/v1-manual-qa.md`
- `scripts/verify_release_readiness.py`
- `scripts/benchmark_csvql.py`
- existing full local gate commands

Required automated gates:

```bash
git diff --check
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras mypy src
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest
```

Required release-readiness command:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

Required benchmark command:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Required unsupported-claim scan:

```bash
rg -n "v1-ready|v1 ready|production-safe|production ready|production-readiness|production readiness|sandbox-safe|sandbox safety|sandbox|large-file-proven|large file proven|large-file performance|large file performance|v1-stable|release-candidate" AGENTS.md README.md CHANGELOG.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/benchmarking.md docs/failure-gallery.md docs/release-readiness.md docs/release-notes/v1.md
```

Matches are acceptable only when classified as guardrails, label rules,
workflow instructions, or explicit non-claims.

## Manual QA Contract

Manual QA must cover the existing matrix in `docs/v1-manual-qa.md` and the
newer TUI work that moved HEAD after the old proof note.

At minimum, record proof for:

- version setup;
- CLI single-file query;
- CLI project catalog query;
- explicit export and reuse as a CSV source;
- bad SQL behavior;
- missing file behavior;
- export overwrite refusal and force;
- TUI launch and quit path;
- repeated query and history behavior;
- derived save and query;
- DDL metadata result behavior;
- Editor Quality v2 selected/current statement and whole-editor run behavior;
- Source Intelligence v1 column loading, alias insertion, and starter-query
  insertion;
- rejected-run recovery preserving previous results when no query ran.

Deterministic Textual app tests may be used for TUI behavior that is hard to
prove reliably through a live PTY. Live PTY proof should still cover launch and
quit when feasible. If synthetic key bursts race, standalone key behavior is the
proof authority and the caveat must be recorded.

## Failure Handling

If a proof command, artifact inspection, manual QA item, or claim scan fails,
the proof lane should stop and record a `blocked` result or an incomplete
`v1-hardening` result.

Do not patch product code or docs inside this proof-refresh lane unless Richard
explicitly approves a separate fix lane. A blocker found by proof is evidence,
not an automatic scope expansion.

If release-readiness fails only because dependency resolution is blocked by the
sandbox or network restrictions, rerun the same command with explicit
escalation according to the active permissions instructions and record both the
initial failure and the escalated result.

## Artifact Policy

Ignored proof evidence must remain ignored unless Richard explicitly approves a
tracked-artifact decision.

Do not commit:

- `.local/`
- `.superpowers/`
- `.csvql/`
- `output/`
- wheels, sdists, benchmark JSON, benchmark summaries, local venvs, or scratch
  TUI transcripts

The only expected tracked output of this lane is the refreshed proof note. The
Superpowers spec and plan files are tracked planning history under the existing
`docs/superpowers/` convention.

## Acceptance Criteria

The lane is complete when one of these outcomes is true:

- `release-candidate eligible`: baseline truth passes, full local gate passes,
  release-readiness proof passes, benchmark proof is same-HEAD and recorded,
  manual QA passes, authority docs agree, unsupported claims are absent, and the
  proof note is refreshed with current evidence.
- `blocked`: at least one proof item fails, and the proof note or handoff names
  the failing command, manual QA item, artifact inspection, or claim scan.
- `v1-hardening`: Richard intentionally stops the proof before completion, and
  the handoff says proof is incomplete rather than candidate-eligible.

In all cases, final reporting must state:

- branch and HEAD;
- proof verdict;
- commands run and results;
- generated artifact paths;
- skipped checks, if any;
- whether the proof note was changed and committed;
- remaining risks;
- next task.

## Risks And Caveats

- `release-candidate eligible` is only a local assessment label. It is not a
  release action.
- Release-readiness may require dependency/build network access.
- Terminal key handling varies. `F4` remains the reliable run fallback.
- Synthetic TUI key bursts can race. Standalone key behavior is stronger proof
  for interactive flows.
- SQL is trusted local DuckDB SQL. CSVQL does not sandbox DuckDB or make
  untrusted SQL safe.
- Benchmark proof is local evidence only and does not prove broad large-file
  performance.
- Generated local artifacts are evidence, not tracked release assets.

## Verification Target

The proof-refresh implementation plan should end with:

```bash
git status --short --branch
```

Expected tracked changes are limited to the refreshed proof note and any
approved Superpowers planning artifacts. Generated proof evidence must remain
ignored.
