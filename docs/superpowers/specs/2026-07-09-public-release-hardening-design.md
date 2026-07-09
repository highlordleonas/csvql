# Public Release Hardening Design

## Objective

Move LocalQL from a local release-candidate eligibility assessment to a
public-release-ready state without tagging, publishing, uploading artifacts,
changing the version, or claiming `v1-stable` before explicit approval.

## Current Context

The release-candidate assessment target before this public-release-hardening
design was commit `9d08aec`, with current-HEAD proof recorded in ignored local
evidence under `output/release-proof-20260709-9d08aec/RESULT.md`. GitHub Actions
CI run `29030775921` passed for the same commit across Ubuntu Python 3.11, 3.12,
3.13, and 3.14, plus macOS Python 3.12 and Windows Python 3.12. Local
release-readiness, package audit, benchmark proof, unsupported-claim scan, mypy,
Ruff, and full pytest passed for that state.

The design/spec commits after `9d08aec` do not by themselves refresh release
proof or make the repository release-ready.

The hostile pre-release review found that the runtime/package candidate is
strong, but the publication posture still needs cleanup:

- `README.md` and related public docs still contain pre-publish status wording
  that would become stale or false after a PyPI upload.
- `pyproject.toml` has no `project.urls`, so package metadata does not yet point
  users at the canonical source, issues, changelog, or release notes.
- `.github/workflows/publish.yml` is manual-only and uses OIDC permissions, but
  it is not yet tag-gated or pinned tightly enough for first public release.
- The GitHub repository is currently private, has no `pypi` environment, and
  private-repo branch protection/ruleset inspection is blocked on the current
  account plan.
- PyPI currently returns no project JSON for `localql`, so the package name
  appears unclaimed at the time this design was written.

## Approved Repository Model

Use `highlordleonas/csvql` as the canonical public source repository for the
`localql` distribution. Do not create a separate public release mirror.

This model keeps the PyPI package, GitHub release, issue tracker, docs, source
history, security policy, and CI evidence tied to one repository. It avoids
mirror drift and avoids a confusing split where PyPI trusted publishing points
at a repository that is not the actual development source.

The repository should remain private until release-hardening cleanup, security
review, package verification, and public-readiness checks pass. Making the repo
public is a separate explicit approval gate and is not part of the design or
implementation commits.

## Skill Activation Contract

The implementation plan and implementation work must activate the relevant
skills before touching matching surfaces. Skill activation means reading the
skill entrypoint and following required referenced guidance before edits, scan
claims, or review conclusions.

- Python package, CLI, API, tests, `pyproject.toml`, `uv.lock`, subprocess,
  file/path, SQL, deserialization, or dependency changes must load
  `$python-codebase-standards`.
- Security best-practices review or secure-by-default implementation guidance
  must load `$security-best-practices`. If no framework-specific Python
  reference applies, the agent must state that and use general guidance plus
  repository evidence.
- Git-backed release-hardening security review must load
  `$codex-security:security-diff-scan` and run the required phase order:
  `$codex-security:threat-model`, `$codex-security:finding-discovery`,
  `$codex-security:validation`, `$codex-security:attack-path-analysis`, then
  final reporting.
- Repository-wide Codex Security review must load
  `$codex-security:security-scan` and run that skill's required repository or
  scoped-path workflow. A security best-practices pass is not a substitute for
  this scan.
- A deep or exhaustive Codex Security repository scan must load
  `$codex-security:deep-security-scan` only when that deeper scan is requested.
  This release-hardening intake explicitly requested deep-scan coverage, so the
  implementation plan must preflight delegated-worker and deep-scan capability.
  If available, deep scan is required before public release. If unavailable,
  ordinary repository scan may be used as fallback only with an explicit
  user-approved waiver that records missing coverage and release impact.
- Candidate findings must not be accepted, suppressed, or deferred without
  validation and attack-path receipts, or an explicit proof gap and release
  impact.
- If a required skill is unavailable or cannot be applied cleanly, stop before
  implementing or claiming proof, state the missing capability, and ask for the
  next decision.

## Alternatives Considered

### Public Canonical Current Repo

The current repo becomes public after cleanup. PyPI trusted publishing points at
`highlordleonas/csvql`, and GitHub release/source links point at the same code
that was tested.

This is the recommended approach because it gives the strongest provenance with
the least release-process complexity.

### Separate Public Release Mirror

A public repository would receive release snapshots while development remains
private.

This preserves privacy longer, but creates release drift risk, source-link
ambiguity, and extra promotion workflow complexity. It is not warranted because
the repo does not need to stay private long term.

### Minimal Publish From Private Repo

Only the PyPI README blocker would be fixed before publishing from the private
repository.

This is fastest, but too weak for the first public release. Public users could
not inspect source, and branch-protection/ruleset controls are unavailable or
unverified while the repository remains private on the current account plan.

## Release-Hardening Design

### Public Package Metadata

PyPI-facing package metadata must read correctly both before and after the first
publish. `README.md` should describe LocalQL as a local-first CSV workflow and
should avoid local proof packet paths, internal status labels, or wording such
as "this does not create a PyPI upload" in the package long description.

Tracked release docs may preserve proof procedure and release boundaries, but
they must distinguish local assessment evidence from public release state. Local
ignored proof paths under `output/` may be referenced only as local evidence,
not as required public proof for users.

`pyproject.toml` should add `project.urls` after the public repository model is
accepted:

- Repository: `https://github.com/highlordleonas/csvql`
- Issues: `https://github.com/highlordleonas/csvql/issues`
- Changelog: `https://github.com/highlordleonas/csvql/blob/main/CHANGELOG.md`
- Release notes:
  `https://github.com/highlordleonas/csvql/blob/main/docs/release-notes/v1.md`

### Publish Workflow

`.github/workflows/publish.yml` should stay manual-only and use PyPI trusted
publishing through OIDC. It should publish only from the intended release tag,
not from an arbitrary manual dispatch ref.

The workflow must split artifact preparation from OIDC publishing. Do not grant
`id-token: write` at workflow scope. A no-OIDC `build-and-verify` job should run
dependency sync, format/lint/type/test checks, build wheel and sdist, audit
package contents, verify artifact version/tag identity, run installed-wheel
smoke, and record artifact hashes. A minimal `publish` job should depend on
`build-and-verify`, use `environment: pypi`, grant `id-token: write` only at the
job level, download the already-built artifacts, verify expected hashes and
metadata, then invoke `pypa/gh-action-pypi-publish`.

The OIDC publish job must not run `uv sync`, project tests, source builds, or
project code such as `csvql query`. It may perform only artifact, hash, and
metadata verification needed to publish the exact artifacts produced by the
no-OIDC build job. Leaving project-code execution in the OIDC publish job
requires an explicit user-accepted release risk before tag or publish approval.

The first release target is `refs/tags/v1.0.0`. The workflow should fail before
building or publishing if it is not running on that exact tag. This prevents an
operator from accidentally publishing from `main` or from a different tag.

The release must have non-publishing tag proof before PyPI approval. Either
`.github/workflows/ci.yml` must run for the `v1.0.0` tag, or a separate
non-publishing tag preflight workflow/job must validate `refs/tags/v1.0.0`.
The manual publish workflow is not a substitute for that pre-publish tag proof.

The no-OIDC `build-and-verify` job should continue to run the existing
release-quality checks:

- `uv sync --all-extras --frozen`
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run --all-extras mypy src`
- `uv run --all-extras pytest`
- `uv build --sdist --wheel --out-dir dist`
- `uv run python scripts/audit_package_contents.py dist`

Before any PyPI upload step, the workflow must prove artifact identity, hashes,
and runtime smoke:

- the tag is `v1.0.0`
- built wheel and sdist metadata version is `1.0.0`
- wheel and sdist SHA256 hashes are recorded before upload
- the built wheel installs by file path into a fresh virtual environment
- installed-wheel smoke runs from a temporary directory outside the source
  checkout
- installed-wheel smoke uses no `PYTHONPATH=src`, no editable install, and no
  repo-local import path
- installed-wheel smoke includes `csvql --version` and `csvql query`

After upload, verify that PyPI file hashes match the pre-upload wheel and sdist
hashes. PyPI trusted-publishing attestations must not be disabled. Capture an
attestation receipt or record an explicit user-accepted exception if
attestations cannot be captured or verified.

All external `uses:` actions, including GitHub-owned actions, must be pinned by
commit SHA before first release unless an exception is explicit, documented, and
accepted by the user before tag or publish approval. A release-ready claim is
not allowed while action pinning is deferred without that recorded exception.

TestPyPI may be used as an optional rehearsal before the final timed
public/PyPI window, but it is not mandatory and does not replace the final real
PyPI name check, trusted-publisher setup, publish, or verification gates.

### Release Invariant Tests

Tests should guard the release posture so future edits do not reintroduce stale
or unsafe release state. The release docs/open-source launch tests should cover:

- package/public README does not contain local proof packet paths or
  "no PyPI upload" style pre-publish wording in the PyPI-facing section
- stale-positive assertions for old release proof identifiers, such as
  `a0f3146`, `29029191091`, and
  `output/release-proof-20260709-a0f3146/RESULT.md`, are replaced with
  stale-negative guards where those identifiers would leak into PyPI-facing
  README or package metadata
- package metadata has expected `project.urls`
- publish workflow remains `workflow_dispatch` only
- publish workflow does not grant workflow-level `id-token: write`
- publish workflow has a no-OIDC `build-and-verify` job for sync, checks,
  build, package audit, artifact identity, installed-wheel smoke, and artifact
  hash recording
- publish workflow has a minimal `publish` job with `environment: pypi` and
  job-level `id-token: write`
- publish job downloads already-built artifacts and does not run `uv sync`,
  project tests, source builds, or project code beyond artifact/hash/metadata
  verification needed to publish
- publish workflow declares `environment: pypi`
- publish workflow includes a tag guard for `refs/tags/v1.0.0`
- publish workflow proves built artifact version `1.0.0` matches tag `v1.0.0`
- publish workflow records pre-upload SHA256 hashes and verifies PyPI file
  hashes after upload
- publish workflow keeps trusted-publishing attestations enabled unless an
  explicit user-accepted exception is recorded
- publish workflow runs installed-wheel smoke from outside the source checkout,
  including `csvql query`, before the PyPI upload step
- publish workflow does not require or reference a long-lived PyPI API token

## Security Review Design

Security review must happen before repo visibility changes or release actions.
The review has five complementary scopes.

### Diff Security Scan

Run a Codex Security diff scan over the release-hardening range:

```text
74b193ec49c9..HEAD
```

This scan focuses on the code and workflow changes introduced by the release
hardening package, including:

- Python support and lockfile changes
- release-readiness installed-wheel smoke
- package audit workflow
- native macOS picker subprocess path
- TUI result spill boundary
- docs/status guard changes
- GitHub Actions workflow changes

Any discovered candidate must go through validation and attack-path analysis.
Confirmed or plausible findings must be fixed with focused regression tests or
explicitly deferred with the proof gap and release impact stated.

### Repository-Wide Codex Security Scan

Run a real Codex Security repository-wide scan before public release. This is a
separate lane from the general security best-practices pass and must produce the
normal Codex Security scan artifacts, including phase outputs, worklist or
coverage closure, candidate ledgers, validation receipts, attack-path receipts
where applicable, and final generated report.

If the repository-wide scan cannot be run, stop before public visibility, tag,
or publish actions and ask for an explicit user-approved waiver. The waiver must
state the missing capability, the coverage not obtained, and the release impact.

### Deep Codex Security Scan

Because this release-hardening lane explicitly requested
`$codex-security:deep-security-scan`, the implementation plan must run the
deep-scan capability preflight before deciding scan coverage. If delegated
workers and deep-scan capabilities are available, run the deep scan before public
release and preserve its generated artifacts. If they are unavailable, record
the preflight result and use the ordinary repository-wide scan as fallback only
after explicit user-approved waiver of the missing deep-scan coverage.

A successful deep scan may satisfy the repository-wide Codex Security scan lane
only when its final report explicitly records repository-wide scope and confirms
that the repository-wide scan requirements were covered. Otherwise, run the
ordinary repository-wide scan separately or record an explicit user-approved
coverage waiver.

### Repository Security Best-Practices Pass

Run a repository-wide security best-practices pass over shipped and release
surfaces:

- CLI entrypoints and user-controlled path/SQL handling
- Python API boundary
- YAML project config parsing
- DuckDB trusted-SQL boundary and public documentation
- subprocess use, especially the native picker
- pickle spill boundary in the TUI result store
- package metadata and built wheel/sdist contents
- GitHub Actions CI and publish workflows
- security, support, and contribution docs
- dependency and lockfile vulnerability posture

The review should treat user SQL and local CSV paths as trusted local workflow
inputs unless repository evidence says otherwise. It should not invent a
sandbox claim. Real issues should be validated and fixed before publication.

### Dependency And Supply-Chain Checks

Before public release, run a dependency and package-supply-chain pass:

- audit the locked or resolved dependency set with `pip-audit`, OSV/GitHub
  Advisory review, or an equivalent documented method
- record the exact dependency-audit command output or advisory-review receipt
- if vulnerability-audit tooling or network access is unavailable, record the
  tool/network proof gap and require explicit user acceptance before release
  claims
- confirm `localql` wheel and sdist exclude ignored output, caches, private
  proof packets, `.venv`, `dist`, and `.csvql`
- confirm the built long description renders without stale pre-publish wording
- confirm GitHub Actions publish path does not depend on repository secrets for
  PyPI upload

## GitHub And PyPI Governance

GitHub repository visibility should change only after local cleanup and security
proof pass.

After the repository becomes public, configure these controls before publishing:

- create or verify GitHub environment `pypi`
- require reviewer/manual approval for the `pypi` environment where GitHub
  allows it; if reviewer or prevent-self-review controls are unavailable,
  capture exact evidence and require user acceptance before tag or publish
- restrict the `pypi` environment to the intended release tag `v1.0.0` where
  GitHub allows selected deployment tags; if unavailable, capture exact evidence
  and require user acceptance before tag or publish
- configure branch protection or rulesets for `main` where GitHub allows it; if
  unavailable, capture exact evidence and require user acceptance before tag or
  publish
- enable GitHub private vulnerability reporting where GitHub allows it; if it
  cannot be enabled, record the public issue fallback as an explicit
  user-accepted release risk
- configure PyPI Trusted Publisher for:
  - owner/repo: `highlordleonas/csvql`
  - workflow: `.github/workflows/publish.yml`
  - environment: `pypi`
  - project: `localql`

No PyPI API token should be added to repository secrets unless trusted
publishing is proven impossible and the user separately approves the fallback.

### Governance Proof Artifact Contract

Before proceeding past governance setup, record a redacted governance proof
artifact under:

```text
output/release-governance-<YYYYMMDD>-<short-head>/
```

The artifact must include `RESULT.md` plus a `commands/` directory containing
redacted `*.json`, `*.txt`, screenshots, or manual receipts that capture:

- GitHub environment `pypi` exists.
- Required reviewers, prevent-self-review, and tag deployment policy status are
  captured, including the selected `v1.0.0` deployment tag restriction where
  available, or exact unavailable-control proof is recorded.
- Branch protection or ruleset status for `main` is captured, or exact
  unavailable-control proof is recorded.
- Private vulnerability reporting is enabled, or the intentionally accepted
  fallback reporting path is recorded.
- PyPI Trusted Publisher settings are captured for owner/repo
  `highlordleonas/csvql`, workflow `.github/workflows/publish.yml`,
  environment `pypi`, and project `localql`.
- Repository secrets and variables are inspected for absence of a PyPI API token
  without printing secret values.
- Any unavailable governance control has explicit user acceptance before tag or
  publish actions.

Do not print secret values in proof output, diffs, prompts, or final reports.
These proof artifacts remain ignored and uncommitted unless separately approved.

## Scan And Proof Target Contract

Every security scan and release proof artifact must record:

- physical `pwd -P`
- branch
- base SHA
- head SHA
- clean or dirty working-tree status
- scan or proof scope

Release proof claims require a clean committed `HEAD`. If a scan or proof is run
on an uncommitted dirty tree, label it exploratory only and do not use it to
support public-release, tag, publish, or release-ready claims.

Scans or proof captured before the final cleanup commit are advisory only.
Required release scans and release proof must run after the cleanup commit on a
clean committed target.

Any tracked change after local gates, package audit, release-readiness proof,
security scans, governance proof, CI proof, or package proof invalidates
same-`HEAD` release proof. After such a change, restart the proof loop on the new
clean committed `HEAD` before making release-candidate eligibility, public
release, tag, or publish claims.

## Final Release Sequence

The release sequence after implementation and security cleanup is:

1. Run focused local checks on the implementation diff as advisory pre-commit
   feedback.
2. Commit the approved cleanup changes and confirm the target `HEAD` is clean.
3. Run full local gate on the clean committed target.
4. Run release-readiness proof, package audit, benchmark proof, unsupported-claim
   scan, and package long-description scan on that committed target.
5. Run the required Codex Security diff scan, deep-scan preflight and deep scan
   when available, repository-wide scan or approved fallback, then the security
   best-practices pass on that committed target.
6. Push cleanup commits and wait for same-HEAD CI on `main`.
7. Re-check the PyPI `localql` project immediately before asking to make the
   repository public; if the name is no longer available, stop before changing
   visibility and reassess.
8. If PyPI and GitHub allow a pending Trusted Publisher before public visibility,
   configure or verify it before making the repository public; otherwise record
   why that was not possible and the residual name-race risk.
9. Before asking to make the repository public, confirm the operator is ready to
   continue through governance setup, tag approval, tag CI, PyPI publish
   approval, PyPI publish, and PyPI verification in one bounded release session.
10. Ask for explicit approval to make the repository public.
11. Configure GitHub environment/protection settings and PyPI trusted publisher.
12. Record and review the governance proof artifact.
13. Rerun or refresh public-repo proof after governance changes.
14. Continue only under the bounded release session from public visibility and
    governance setup through tag and PyPI publish. If the sequence must pause
    after public visibility but before PyPI publish, stop and require explicit
    user acceptance of the residual PyPI name-race risk before continuing.
15. Re-check the PyPI `localql` project immediately before tag approval; if the
   name is no longer available, stop before tagging and reassess.
16. Before tag approval, decide the signed-tag posture. Use a signed annotated
    tag if signing identity and tooling are ready. If signing is not ready,
    record an explicit user-accepted signing exception because the repository
    has no existing signing policy.
17. Ask for explicit approval to create annotated tag `v1.0.0` at the clean
    committed `HEAD` used for local, security, package, governance, and CI
    proof.
18. Ask for explicit approval to push tag `v1.0.0`.
19. Verify that the pushed remote tag object exists and is annotated.
20. Verify that the peeled remote tag commit, such as
    `refs/tags/v1.0.0^{}`, resolves to the exact clean committed `HEAD` used
    for local, security, package, governance, and CI proof.
21. Wait for non-publishing CI or tag preflight on `refs/tags/v1.0.0`. If the
    current CI workflow still has no tag trigger and no separate tag preflight
    exists, stop before PyPI approval.
22. If pushed-tag proof or tag CI/preflight fails, stop before PyPI publish and
    GitHub release. Require an explicit user decision before deleting the
    unpublished tag, abandoning `v1.0.0` and cutting a new version, or accepting
    a documented exception. Any tracked fix after pushed-tag proof failure
    invalidates the old proof loop and requires proof to restart on the new
    clean committed `HEAD`.
23. Re-check the PyPI `localql` project immediately before publish approval; if
    the name is no longer available, stop before publishing and reassess.
24. Ask for explicit approval to run the PyPI publish workflow.
25. Verify PyPI page, metadata, and fresh-environment install from PyPI,
    preferably with `--no-cache-dir`, then run `csvql --version` and a minimal
    `csvql query` against a temporary CSV.
26. If publish or post-PyPI verification fails, stop before GitHub release and
    before public stable wording. Inspect and record PyPI project, version, and
    file state. Do not blindly rerun the publish workflow. If no public files
    exist, rerun only against the same tag and artifacts, or restart proof if
    tracked changes are needed. If any `localql 1.0.0` artifact is public,
    require an explicit user decision before yanking, accepting with documented
    risk, cutting a new version, or creating a matching GitHub release. Any
    tracked fix after publish failure invalidates same-`HEAD` proof and
    restarts proof on the new clean committed `HEAD`.
27. Ask for explicit approval to create the GitHub release.
28. Record post-release proof.
29. Only after successful publication proof, update public wording to published
    `v1.0.0` or `v1-stable` if that wording is still desired.

## Out Of Scope Until Separate Approval

The implementation plan generated from this design must not:

- make the GitHub repository public
- create or push a release tag
- create a GitHub release
- run the PyPI publish workflow
- upload release artifacts
- bump or change the package version
- claim `v1-stable`
- add a PyPI API token secret
- delete ignored local proof artifacts or caches

## Verification Targets

The implementation must refresh proof after any tracked cleanup commit:

- `git diff --check`
- `git diff --cached --check` before any commit
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff format --check .`
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check .`
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras mypy src`
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest -q`
- release-readiness proof into a commit-specific ignored output directory
- package build and audit into a commit-specific ignored output directory
- benchmark proof into `output/benchmarks`
- unsupported-claim scan across public docs
- package long-description scan against the built wheel and sdist
- Codex Security diff-scan report for the release-hardening range
- Codex Security repository-wide scan report, or an explicit user-approved
  waiver with release impact
- Codex Security deep-scan preflight result and deep-scan report, or an explicit
  user-approved waiver with missing coverage and release impact
- explicit statement whether deep scan satisfied the repository-wide scan lane,
  or whether both scans were run independently
- security best-practices report or notes scoped to release surfaces
- dependency vulnerability audit output, advisory-review receipt, or explicit
  user-approved proof-gap waiver
- governance proof artifact for GitHub environment/protection, PyPI trusted
  publisher, private vulnerability reporting, and PyPI-token absence
- GitHub Actions CI on the exact pushed cleanup commit
- signed-tag posture receipt, including signed tag proof or an explicit
  user-accepted signing exception
- pushed `v1.0.0` tag proof showing the remote tag object exists and is
  annotated
- peeled remote tag commit proof showing `refs/tags/v1.0.0^{}` resolves to the
  same clean committed `HEAD` used for local, security, package, governance, and
  CI proof
- non-publishing CI or tag preflight proof on `refs/tags/v1.0.0`
- pushed-tag failure decision receipt if tag object proof, peeled commit proof,
  or tag CI/preflight fails
- publish-workflow artifact identity proof that built wheel and sdist version
  `1.0.0` matches tag `v1.0.0`
- publish-workflow installed-wheel smoke proof from a temporary directory
  outside the source checkout, with no `PYTHONPATH=src`, no editable install,
  and `csvql query` before PyPI upload
- post-PyPI fresh-environment install proof for `localql==1.0.0` from PyPI,
  preferably with `--no-cache-dir`, followed by `csvql --version` and a minimal
  `csvql query` against a temporary CSV
- no-OIDC `build-and-verify` job proof showing release-quality checks, build,
  package audit, artifact identity, installed-wheel smoke, and pre-upload
  SHA256 hashes
- minimal OIDC `publish` job proof showing job-level `id-token: write`,
  `environment: pypi`, downloaded artifacts, expected hash/metadata
  verification, and no project-code execution beyond artifact verification
- PyPI file hash proof showing published wheel and sdist hashes match the
  pre-upload artifacts
- trusted-publishing attestation receipt, or an explicit user-accepted
  attestation exception
- PyPI publish failure state and user-decision receipt if publish or post-PyPI
  verification fails

## Risks And Mitigations

- **PyPI name race:** `localql` is unclaimed at design time, but a pending trusted
  publisher does not reserve the name. Mitigation: treat the final tag/publish
  work as a timed release sequence, re-check name availability immediately
  before public visibility, tag approval, and publish approval, configure a
  pending Trusted Publisher before public visibility when feasible, publish
  successfully before creating a GitHub release, and stop if the name is claimed.
- **Self-referential proof churn:** public docs should not require a same-commit
  local proof path for their own status update. Mitigation: keep public docs
  evergreen and record local proof under ignored `output/` packets.
- **Trusted SQL misunderstanding:** users may infer sandboxing from local query
  tooling. Mitigation: preserve explicit trusted-SQL/no-sandbox wording in
  README, SECURITY, release notes, and product docs.
- **GitHub control availability:** branch/ruleset controls were unavailable while
  the repo was private on the current plan. Mitigation: configure or inspect
  them after the repository becomes public, record exact unavailable-control
  evidence, and require user acceptance before tag or publish.
- **Supply-chain drift:** unpinned Actions or broad workflow dispatch could
  publish unintended code. Mitigation: tag guard the publish workflow and
  require SHA-pinned third-party Actions or a documented user-accepted exception
  before tag or publish.
