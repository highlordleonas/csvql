# Release Proof Inventory Design

## Status

Approved design pending written-spec review.

This design creates a proof-inventory lane for the current `main` `HEAD`. It is
an evidence and classification lane, not an eligibility push and not a release
action.

## Context

LocalQL is the installable distribution name. The runtime contract remains the
`csvql` CLI, the `csvql` Python import package, `.csvql.yml` project config,
and the `csvql menu` TUI command.

The current repo state is `v1-hardening`. The release docs already define a
local candidate workflow that requires:

- baseline repo truth
- full local gate
- release-readiness proof
- manual v1 QA matrix
- TUI QoL terminal matrix
- benchmark proof
- unsupported-claim scan
- authority-doc agreement

The recent TUI QoL closeout made the release boundary more honest: macOS
Terminal evidence exists for that lane, but the full TUI QoL terminal matrix is
not complete, and the closeout does not make the project
`release-candidate eligible`.

This proof inventory should refresh what can be verified automatically on the
current `HEAD`, record what remains unverified, and stop with an honest
classification.

## Goals

- Produce a same-`HEAD` local proof inventory for current `main`.
- Run the documented automated release proof commands that are safe for local
  evidence gathering.
- Record artifact paths, command outcomes, and blocker notes under ignored
  `output/`.
- Classify the current state conservatively as `v1-hardening` or `blocked`
  unless every release-readiness requirement is actually satisfied.
- Keep manual v1 QA and TUI QoL matrix gaps explicit instead of treating
  automated proof as enough.
- Preserve all product, runtime, release, and security boundaries.

## Non-Goals

- No release-candidate eligibility push.
- No manual TUI terminal matrix run.
- No screenshots or GUI terminal evidence.
- No outside-observer coordination.
- No runtime behavior changes.
- No docs claim that the project is `release-candidate eligible`,
  `release-candidate`, or `v1-stable`.
- No tag, PyPI upload, GitHub release, artifact upload, version change, push,
  or remote configuration.
- No claims of sandbox safety, safe untrusted SQL, security isolation,
  production readiness, or broad large-file proof.

## Proof Scope

The inventory should run and record:

- baseline repo truth:
  - `pwd -P`
  - `git status --short --branch`
  - `git log -1 --oneline`
  - `git remote -v`
  - `git tag --points-at HEAD`
- full local gate:
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run --all-extras mypy src`
  - `uv run --all-extras pytest`
- release-readiness proof:
  - `uv run python scripts/verify_release_readiness.py --work-dir <inventory-dir>/release-readiness`
- package-content audit if release-readiness produces current dist artifacts,
  or by running the documented package audit commands into the inventory path.
- benchmark proof:
  - `uv run python scripts/benchmark_csvql.py --output-root <inventory-dir>/benchmarks`
- unsupported-claim scan across the authority docs named by
  `docs/release-readiness.md`.
- authority-doc agreement review across the same authority docs.

Use `UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql` for `uv` commands in
this environment.

## Evidence Output

Use one ignored local evidence root:

```text
output/release-proof-inventory-<YYYYMMDD>-<short-head>/
```

Expected contents:

- `RESULT.md`: concise human-readable proof inventory and classification.
- `commands/`: captured command output files, one file per proof command.
- `release-readiness/`: release-readiness work directory.
- `package-audit/`: package audit artifacts if run.
- `benchmarks/`: benchmark JSON and Markdown summary artifacts.
- `claim-scan.txt`: unsupported-claim scan output and classification notes.
- `authority-review.md`: authority-doc agreement notes.

These files are local proof artifacts and should remain ignored. Do not commit
generated proof artifacts unless a separate tracked-artifact decision is made.

## Classification Rules

The inventory result must use one of these labels:

- `v1-hardening`: automated proof is fresh or partly fresh, but manual proof,
  TUI terminal evidence, authority agreement, or other release-readiness
  requirements remain incomplete.
- `blocked`: a named proof, docs, environment, dependency, tooling, or command
  failure prevents a useful current-state inventory.
- `release-candidate eligible`: allowed only if the full local gate,
  release-readiness proof, benchmark proof, authority-doc agreement,
  unsupported-claim scan, manual v1 QA matrix, and TUI QoL terminal matrix all
  pass on the same candidate-state `HEAD`.

The expected outcome for this inventory lane is `v1-hardening` unless already
completed same-`HEAD` manual QA and full TUI terminal evidence can be cited
without rerunning manual work.

## Error Handling

If a proof command fails:

- record the exact command
- record the exit status
- record the short failure reason
- keep any relevant output path
- continue independent read-only scans where safe
- classify as `blocked` if the failure prevents an honest current-state
  inventory

Do not retry blindly. If a failure looks like the known `uv` cache permissions
issue, retry once with `UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql` and
record both attempts if the first attempt was part of the lane.

## Authority Review

The authority-doc review should inspect the docs listed in
`docs/release-readiness.md`:

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

The review should classify obvious inconsistencies, stale status language, and
unsupported claims. It should not rewrite docs in this lane unless a later
implementation plan explicitly adds a docs-repair task.

## Acceptance Criteria

- A local ignored inventory directory is created for the current `HEAD`.
- Every automated proof command attempted by the lane has recorded output.
- `RESULT.md` names the commit, branch, command outcomes, artifact paths,
  manual-proof gaps, TUI terminal-matrix gaps, and final classification.
- The inventory does not claim `release-candidate eligible` unless every
  documented prerequisite is satisfied on the same `HEAD`.
- Generated proof artifacts remain ignored and uncommitted.
- No runtime source, package metadata, version, tag, remote, publish workflow,
  or release label is changed.

## Verification

The implementation plan should verify the design/spec work with:

```bash
git diff --check
```

The execution lane should verify the inventory by checking:

```bash
test -f output/release-proof-inventory-<YYYYMMDD>-<short-head>/RESULT.md
git status --short --branch
```

Tracked status should remain clean after generated `output/` artifacts are
created because `output/` is ignored.

## Risks And Mitigations

- Overclaim risk: mitigate by requiring conservative labels and listing manual
  proof gaps explicitly.
- Stale evidence risk: mitigate by tying all proof artifacts to the current
  `HEAD`.
- Manual-gate gap risk: mitigate by recording manual v1 QA and TUI QoL matrix
  as blockers unless same-`HEAD` evidence exists.
- Artifact confusion risk: mitigate by keeping generated proof under ignored
  `output/` and not treating local artifacts as published release artifacts.
- Scope creep risk: mitigate by forbidding runtime changes, docs repair,
  terminal screenshots, and release actions in this inventory lane.
