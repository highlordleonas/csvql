# Release Readiness

LocalQL is the installable distribution name for the `csvql` CLI, Python import
package, and project config contract. This document defines the local proof path
for `release-candidate` and `v1-stable` labels. It does not publish packages,
create tags, upload artifacts, or claim a release by itself.

Release-note surfaces:

- [Changelog](../CHANGELOG.md)
- [v1 release notes](release-notes/v1.md)

For this lane, the release package means these tracked docs exist and agree:

- `CHANGELOG.md`
- `docs/release-notes/v1.md`
- this local candidate workflow in `docs/release-readiness.md`
- README and roadmap discoverability updates

## Current Candidate Assessment

Current release work is public release hardening for the `1.0.0` package
surface. Same-`HEAD` local proof, security proof, package proof, governance
proof, and CI proof must be refreshed on the final committed release target
before tag, publish, GitHub release, or `v1-stable` claims.

Historical local assessments are context only. Any tracked change after local
gates, package audit, release-readiness proof, security scans, governance proof,
CI proof, or package proof invalidates same-`HEAD` release proof until the proof
loop is rerun on the new clean committed `HEAD`.

## Release-Readiness Script

Run:

```bash
uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

On success, the script prints a proof summary with version agreement, built
wheel path, query smoke output, inspect smoke output, TUI extra import output,
and menu help output.

## Package Content Audit

Before external release approval, build the wheel and sdist and inspect their
contents:

```bash
uv build --sdist --wheel --out-dir output/package-audit/dist
uv run python scripts/audit_package_contents.py output/package-audit/dist
```

The audit rejects ignored local artifacts and internal planning material. It is
part of the launch-readiness gate, not a PyPI upload.

This workflow verifies:

- `pyproject.toml` declares the `localql` distribution name
- `pyproject.toml`, `src/csvql/__init__.py`, and `csvql --version` agree on the
  version
- `uv build --sdist --wheel` succeeds
- built wheel and sdist artifact names use the `localql` distribution
- an isolated wheel install can run `csvql --version`
- the installed wheel can run a tiny `query` command
- the installed wheel can run a tiny `inspect` command
- the installed wheel can install the optional `tui` extra, import the
  Textual-backed TUI app, and show `csvql menu --help`

## Full Local Gate

Before any `release-candidate` or `v1-stable` claim, run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

## Manual QA Gates

Run the manual QA gates before classifying a final candidate:

- [Manual v1 QA matrix](v1-manual-qa.md)
- [TUI QoL QA gate](tui-qol-qa.md)

The matrix covers CLI-only reuse, optional TUI flows, derived-source save and
query, bad SQL, TUI DDL metadata results, export overwrite behavior, missing
files, quit behavior, and Mac keybinding paths.

Run the TUI QoL QA gate for rescoped terminal/TUI evidence and state-clarity
checks. The approved TUI release-proof target now requires same-`HEAD`
automated support proof on macOS, native Windows, and Linux. Windows and Linux
screenshots or manual terminal media are no longer required for this release
lane. VS Code integrated terminal, iTerm2, and tmux/SSH are out of scope for
this release lane.

The final proof result also requires same-`HEAD` automated Python-version
support proof for Python 3.11 through Python 3.14 on Ubuntu, plus same-`HEAD`
three-OS automated support proof for macOS, native Windows, and Linux. The
three-OS proof uses Python 3.12 on each target OS family. Required automated
proof commands include `uv sync --all-extras --frozen`,
`uv run ruff format --check .`, `uv run ruff check .`,
`uv run --all-extras mypy src`, and `uv run --all-extras pytest`.

Each source-checkout proof transcript must record `pwd -P`,
`git status --short --branch`, `git log -1 --oneline`, `git remote -v`,
`git tag --points-at HEAD`, `uv --version`, `uv run python --version`, and
`uv run --all-extras csvql --version`. Plain `csvql --version` is not sufficient for source-checkout proof.

Historical proof records are context, not current same-`HEAD` proof. The prior
passing automated run `28965686605` at `d8ec3df` superseded the blocked
`b118a2c` packet, but it is historical prior proof context only and not final
proof for later implementation commits. For a new implementation `HEAD`, record
the fresh GitHub Actions run id and implementation commit SHA in the ignored
proof packet `RESULT.md` and final execution response before claiming current
same-`HEAD` automated proof. Tracked docs define this proof contract and must
not require a self-referential run id for their own commit unless a separate
two-SHA proof recording model is approved. The automated proof does not prove
manual terminal UX.

A local `pass` result from this lane is evidence only. Changing any release label, release status, public status, tag, or published artifact still requires
separate explicit approval.

## Benchmark Proof

Refresh or explicitly cite local benchmark evidence before making performance
claims:

```bash
uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Benchmark artifacts are local evidence only. They do not prove large-file
performance beyond the recorded datasets.

## Local Candidate Workflow

Run candidate evaluation from a clean worktree on `main`.

1. Capture baseline truth:

   ```bash
   pwd -P
   git status --short --branch
   git log -1 --oneline
   git remote -v
   git tag --points-at HEAD
   uv --version
   uv run python --version
   uv run --all-extras csvql --version
   ```

2. Confirm authority docs agree with implemented runtime behavior:

   - `README.md`
   - `CHANGELOG.md`
   - `docs/development.md`
   - `docs/PRODUCT_DIRECTION.md`
   - `docs/ROADMAP.md`
   - `docs/ARCHITECTURE.md`
   - `docs/json-contracts.md`
   - `docs/benchmarking.md`
   - `docs/failure-gallery.md`
   - `docs/v1-manual-qa.md`
   - `docs/tui-qol-qa.md`
   - `docs/release-readiness.md`
   - `docs/release-notes/v1.md`

3. Run the full local gate.
4. Run release-readiness proof.
5. Run the manual v1 QA matrix and record the date, commit SHA, terminal app,
   passed items, and blockers.
6. Confirm `docs/tui-qol-qa.md` defines the approved cross-OS automated TUI
   proof gate. Run the TUI QoL QA gate and record the TUI QoL run id, required
   automated proof outputs, any cited manual terminal context, passed items,
   blockers, source access method, commit verification command, baseline
   transcripts, observer labels, and deviations.
7. Record automated Python-version support proof for Python 3.11 through Python
   3.14 on Ubuntu, plus three-OS automated support proof for macOS, native
   Windows, and Linux on the same candidate `HEAD`.
8. Run benchmark proof or explicitly cite a current local benchmark artifact.
   A current local benchmark artifact must come from the same candidate-state
   `HEAD`; record both `output/benchmarks/<run-id>/benchmark.json` and
   `output/benchmarks/<run-id>/benchmark-summary.md`. Rerunning
   `uv run python scripts/benchmark_csvql.py --output-root output/benchmarks`
   during final candidate evaluation is preferred.
9. Scan for unsupported current claims:

   ```bash
   rg -n "v1-ready|v1 ready|production-safe|production ready|production-readiness|production readiness|sandbox-safe|sandbox safety|sandbox|large-file-proven|large file proven|large-file performance|large file performance" README.md CHANGELOG.md docs/development.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/benchmarking.md docs/failure-gallery.md docs/v1-manual-qa.md docs/tui-qol-qa.md docs/release-readiness.md docs/release-notes/v1.md
   ```

   Matches are expected for guardrails and other non-claims, but each match must
   be classified. A current claim that CSVQL is v1-ready, production-safe,
   production-ready, sandbox-safe or sandboxed, or large-file-proven blocks
   candidate eligibility.

10. Classify the result:

   - `v1-hardening`: release package exists but proof is stale, incomplete, not
     run, or blocked by remaining work.
   - `release-candidate eligible`: release package exists, full local gate
     passes, release-readiness proof passes, benchmark proof is refreshed or a
     same-HEAD local benchmark artifact is cited with benchmark JSON and
     Markdown summary paths, authority docs agree, the TUI QoL QA gate records
     the required automated proof outputs and any cited manual terminal
     context, same-`HEAD` Python 3.11 through Python 3.14 support proof passes,
     same-`HEAD` three-OS automated support proof passes on macOS, native
     Windows, and Linux with baseline transcripts, source access method, commit
     verification command, and no failed or missing required checks, and
     unsupported claims are absent.
   - `blocked`: a named proof, contract, docs, environment, dependency, or
     tooling blocker prevents honest candidate classification.

11. Stop before publishing, tagging, uploading artifacts, creating a GitHub
   release, or changing the package version.

## Label Rules

Use `v1-hardening` only while final candidate proof is stale, incomplete,
unreviewed, or blocked.

Use `release-candidate eligible` only as an assessment result after:

- README, development docs, changelog, release notes, roadmap, product
  direction, architecture, JSON contracts, benchmarking, failure gallery, and
  release readiness agree with the runtime surface
- current JSON shapes, exit codes, config schema, DuckDB dependency floor, and
  Python API surface are documented and test-backed
- the release-readiness script passes on the candidate state
- Python 3.11 through Python 3.14 support proof passes for the same candidate
  `HEAD`
- benchmark proof is refreshed or a same-HEAD local benchmark artifact is cited
  with benchmark JSON and Markdown summary paths
- the full local gate passes
- the TUI QoL QA gate records the required automated proof outputs and any
  cited manual terminal context with a recorded run id, baseline transcripts,
  source access method, commit verification command, and no failed or missing
  required checks
- three-OS automated support proof passes on macOS, native Windows, and Linux
  for the same candidate `HEAD`
- baseline transcripts and automated support proof are same-`HEAD` evidence for
  the candidate state being classified
- changelog and release-note material exists for the implemented surfaces
- docs make no unsupported sandbox, security-isolation, production-readiness,
  or large-file performance claims

Use `release-candidate` as a status label only after candidate eligibility is
proven and the user explicitly approves changing the label. LocalQL candidate
proof must remain current on the exact candidate state before external release
actions.

Use `v1-stable` only after the release-candidate proof remains valid, this
document's label rules and `docs/development.md` release boundary are satisfied,
and the final release action is explicitly approved.

## Generated Artifact Policy

Proof workflows write local evidence under ignored output directories:

- `output/release-readiness/**`
- `output/benchmarks/**`

Generated wheels, sdists, benchmark JSON, benchmark Markdown summaries, virtual
environments, and scratch transcripts are local evidence only. Do not commit
them unless a separate tracked-artifact decision is made.

## No-Publish Boundary

The commands in this document are local verification commands. They do not
publish to PyPI, push Git tags, create GitHub releases, upload artifacts, bump
the version, or mutate external systems.
