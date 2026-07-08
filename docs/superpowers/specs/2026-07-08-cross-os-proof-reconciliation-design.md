# Cross-OS Proof Reconciliation Design

## Status

Approved design pending implementation planning.

This design records the next release-proof follow-up after the automated
cross-OS proof lane. It is a tracked reconciliation and CI-correctness design,
not a release action.

## Context

Live repo truth at design time:

- branch: `main`
- tracked status: clean and tracking `origin/main`
- `HEAD`: `d8ec3df test: stabilize tui pane context proof`
- `origin`: `https://github.com/highlordleonas/csvql.git`
- no tag points at `HEAD`
- no repo-local `AGENTS.md` or `AGENTS.override.md` was found in the checked
  repo scope

LocalQL is the installable distribution name. The runtime contract remains the
`csvql` CLI, `csvql` Python import package, `.csvql.yml` project config, and
`csvql menu` TUI command.

The prior automated proof thread produced two important facts:

- `b118a2c359505430b208803ee5b99de1070ebbf9` did not become the passing
  Windows proof candidate and remains superseded or blocked for that lane.
- `d8ec3df938af6d6424efd7f7582c0940b565f1a9` passed GitHub Actions run
  `28965686605` across macOS, Ubuntu, and native Windows runner jobs, including
  the `windows-latest` job with `uv 0.11.28`, Python `3.12.13`,
  `csvql --version` reporting `1.0.0`, and pytest reporting `598 passed`.

The existing local proof packet under ignored `output/` has already been
updated to preserve that distinction, but ignored output artifacts are not
tracked release authority. The tracked docs and guard tests need a narrow
reconciliation pass so future agents do not read stale or over-broad proof
status.

The same CI run also exposed one proof-integrity issue: the matrix row labeled
`python-version: "3.11"` installed Python 3.11, but `uv run python --version`
reported Python `3.12.3`. That means the row label and actual `uv` execution
interpreter disagreed. This is not a runtime product defect, but it makes the
Python 3.11 CI evidence ambiguous.

## Goals

- Record tracked release-proof truth that `b118a2c` was superseded and
  `d8ec3df` is the passing automated cross-OS proof candidate.
- Keep the rescoped proof boundary clear: Windows and Linux screenshots or
  manual terminal media are not required for the current automated lane.
- Preserve the manual-proof limitation: automated proof does not prove Windows
  Terminal or Linux desktop-terminal UX details.
- Fix CI so each matrix row uses the requested Python version for `uv sync` and
  `uv run`, including a real Python 3.11 row.
- Add or update guard tests so the tracked docs and workflow cannot silently
  drift back into misleading proof status.
- Keep all release boundaries intact: no tag, no publish, no GitHub release, no
  release artifact upload, no package version change, and no `v1-stable` claim.

## Non-Goals

- No code behavior changes to the CLI, Python package, or TUI.
- No new feature work.
- No manual Windows Terminal proof.
- No manual Linux desktop-terminal proof.
- No screenshot or media collection.
- No publication, tagging, release creation, artifact upload, remote migration,
  or version bump.
- No claim that the project is `release-candidate`, published, production
  ready, sandbox safe, safe for untrusted SQL, or `v1-stable`.

## Scope

Tracked files expected to change in the implementation plan:

- `docs/tui-qol-qa.md`
- `docs/release-readiness.md`
- `docs/release-notes/v1.md`
- `docs/v1-manual-qa.md`, only if needed to keep manual QA wording consistent
- `tests/test_v1_polish_docs.py`
- `.github/workflows/ci.yml`

Ignored proof artifacts under `output/` may be cited but should not become the
primary tracked authority. If the implementation records a tracked proof
summary, it should cite the GitHub Actions run id, commit SHA, and local output
packet path without committing logs.

## Design

### Tracked Proof Reconciliation

The tracked docs should make the current state plain:

- The older `b118a2c` automated packet is superseded and should not be treated
  as the passing Windows candidate.
- The passing automated cross-OS proof candidate is
  `d8ec3df938af6d6424efd7f7582c0940b565f1a9`.
- GitHub Actions run `28965686605` is the cited same-`HEAD` automated proof run.
- The run passed macOS, Ubuntu, and native Windows automated jobs.
- The proof is automated support proof only. It does not replace manual
  Windows Terminal or Linux desktop terminal UX evidence if a later lane wants
  to claim OS-level terminal behavior.

The docs should continue to say that Windows and Linux screenshots or manual
terminal media are not required for the current rescoped automated lane. They
should also continue to prevent broader release or safety claims.

### CI Python-Version Correctness

The workflow should ensure `uv` uses the matrix Python version for the project
environment and all `uv run` commands.

Preferred implementation direction:

- keep the current matrix rows for Ubuntu 3.11, Ubuntu 3.12, macOS 3.12, and
  Windows 3.12
- keep `uv python install ${{ matrix.python-version }}`
- force the matrix interpreter for `uv sync` and `uv run` by using
  `UV_PYTHON: ${{ matrix.python-version }}` at the job or step level, or by
  passing `--python ${{ matrix.python-version }}` explicitly to `uv sync` and
  `uv run`
- keep the baseline command `uv run python --version` as the proof line for the
  actual interpreter
- do not add a tracked `.python-version` file unless a separate design approves
  a repo-wide Python pin

The implementation plan should choose one exact workflow style and guard it
with tests. The acceptance condition is not "the workflow label says 3.11"; it
is "the CI log for the 3.11 row reports Python 3.11 from `uv run python
--version`."

### Guard Tests

`tests/test_v1_polish_docs.py` should protect both halves of this design:

- release-proof docs must cite `d8ec3df`, GitHub Actions run `28965686605`, and
  the fact that `b118a2c` was superseded or blocked for Windows proof
- release-proof docs must keep the no-screenshot rescope and automated-only
  limitation visible
- `.github/workflows/ci.yml` must contain a Python 3.11 matrix row
- `.github/workflows/ci.yml` must force the `uv` project/run environment to the
  matrix Python version through `UV_PYTHON` or explicit `--python`
- baseline truth must still include `uv run python --version` and
  `uv run --all-extras csvql --version`

The tests should not require exact whitespace or a specific YAML emitter. They
should assert the semantic guardrails that prevent another misleading CI proof.

## Error Handling And Failure States

If the CI workflow cannot make Python 3.11 run under `uv` on the Ubuntu runner,
the result should be classified as blocked for Python 3.11 proof and the docs
must not claim Python 3.11 execution proof.

If the next CI run passes for macOS, Linux, and Windows but a nonessential
GitHub runner warning appears, the warning should be recorded only if it affects
the proof contract. Node deprecation warnings from upstream actions are not a
product defect unless they break the workflow.

If docs and output packets disagree, tracked docs should preserve the stricter
truth: cite only same-`HEAD` passing evidence and explicitly mark older evidence
as historical or superseded.

## Verification

The implementation plan should verify, at minimum:

- focused docs guard tests in `tests/test_v1_polish_docs.py`
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run --all-extras mypy src`
- `uv run --all-extras pytest`
- a GitHub Actions run after pushing, with the Ubuntu 3.11 job log showing
  Python 3.11 from `uv run python --version`

Local `uv` commands may use `UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql`
when the default cache path is not writable in the current environment.

## Acceptance Criteria

- Tracked docs and tests state that `d8ec3df` supersedes the blocked `b118a2c`
  automated proof packet.
- Tracked docs cite GitHub Actions run `28965686605` as prior passing
  cross-OS automated proof without claiming release publication or `v1-stable`.
- Tracked docs preserve that Windows and Linux screenshots are not required for
  this lane, while automated proof does not prove manual terminal UX.
- CI workflow forces `uv` to use each matrix Python version.
- A fresh CI run proves the Python 3.11 row actually runs Python 3.11.
- No release artifact, tag, GitHub release, version bump, publish, or
  `v1-stable` claim is created.

## Next Step

After this spec is reviewed and approved, use `superpowers:writing-plans` to
create a task-by-task implementation plan. The plan should cover tracked docs,
guard tests, CI workflow cleanup, local verification, push approval, GitHub
Actions evidence collection, and final proof-state reporting.
