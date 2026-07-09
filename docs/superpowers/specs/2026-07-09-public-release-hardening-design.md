# Public Release Hardening Design

## Objective

Move LocalQL from a local release-candidate eligibility assessment to a
public-release-ready state without tagging, publishing, uploading artifacts,
changing the version, or claiming `v1-stable` before explicit approval.

## Current Context

Current `main` is clean at commit `9d08aec`, with current-HEAD proof recorded in
ignored local evidence under `output/release-proof-20260709-9d08aec/RESULT.md`.
GitHub Actions CI run `29030775921` passed for the same commit across Ubuntu
Python 3.11, 3.12, 3.13, and 3.14, plus macOS Python 3.12 and Windows Python
3.12. Local release-readiness, package audit, benchmark proof, unsupported-claim
scan, mypy, Ruff, and full pytest passed for that state.

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

The first release target is `refs/tags/v1.0.0`. The workflow should fail before
building or publishing if it is not running on that exact tag. This prevents an
operator from accidentally publishing from `main` or from a different tag.

The publish job should continue to run the existing release-quality checks:

- `uv sync --all-extras --frozen`
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run --all-extras mypy src`
- `uv run --all-extras pytest`
- `uv build --sdist --wheel --out-dir dist`
- `uv run python scripts/audit_package_contents.py dist`

Preferred supply-chain posture is to pin third-party GitHub Actions by commit
SHA. If action pinning is deferred, that exception must be explicit and should
not be hidden behind a release-ready claim.

### Release Invariant Tests

Tests should guard the release posture so future edits do not reintroduce stale
or unsafe release state. The release docs/open-source launch tests should cover:

- package/public README does not contain local proof packet paths or
  "no PyPI upload" style pre-publish wording in the PyPI-facing section
- package metadata has expected `project.urls`
- publish workflow remains `workflow_dispatch` only
- publish workflow uses `id-token: write`
- publish workflow declares `environment: pypi`
- publish workflow includes a tag guard for `refs/tags/v1.0.0`
- publish workflow does not require or reference a long-lived PyPI API token

## Security Review Design

Security review must happen before repo visibility changes or release actions.
The review has two complementary scopes.

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

- inspect the locked dependency set for known vulnerability signals
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
- require a reviewer/manual approval for the `pypi` environment when available
- configure branch protection or rulesets for `main` when public visibility
  enables those controls
- configure PyPI Trusted Publisher for:
  - owner/repo: `highlordleonas/csvql`
  - workflow: `.github/workflows/publish.yml`
  - environment: `pypi`
  - project: `localql`

No PyPI API token should be added to repository secrets unless trusted
publishing is proven impossible and the user separately approves the fallback.

## Final Release Sequence

The release sequence after implementation and security cleanup is:

1. Run full local gate on public-release-ready `main`.
2. Run release-readiness proof, package audit, benchmark proof, unsupported-claim
   scan, and package long-description scan.
3. Push cleanup commits and wait for same-HEAD CI on `main`.
4. Ask for explicit approval to make the repository public.
5. Configure GitHub environment/protection settings and PyPI trusted publisher.
6. Rerun or refresh public-repo proof after governance changes.
7. Ask for explicit approval to create tag `v1.0.0`.
8. Wait for CI on the tag.
9. Ask for explicit approval to create the GitHub release.
10. Ask for explicit approval to run the PyPI publish workflow.
11. Verify PyPI page, metadata, and clean-environment install from PyPI.
12. Record post-release proof.
13. Only after successful publication proof, update public wording to published
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
- GitHub Actions CI on the exact pushed cleanup commit

## Risks And Mitigations

- **PyPI name race:** `localql` is unclaimed at design time, but a pending trusted
  publisher does not reserve the name. Mitigation: keep cleanup tight and do not
  delay unnecessarily once publication approval is granted.
- **Self-referential proof churn:** public docs should not require a same-commit
  local proof path for their own status update. Mitigation: keep public docs
  evergreen and record local proof under ignored `output/` packets.
- **Trusted SQL misunderstanding:** users may infer sandboxing from local query
  tooling. Mitigation: preserve explicit trusted-SQL/no-sandbox wording in
  README, SECURITY, release notes, and product docs.
- **GitHub control availability:** branch/ruleset controls were unavailable while
  the repo was private on the current plan. Mitigation: configure them after the
  repository becomes public and record any unavailable control explicitly before
  approving publish.
- **Supply-chain drift:** unpinned Actions or broad workflow dispatch could
  publish unintended code. Mitigation: tag guard the publish workflow and prefer
  SHA-pinned actions.
