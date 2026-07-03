# LocalQL Open-Source Launch Readiness Design

Status: design approved in conversation; written spec review required before
implementation planning.

Date: 2026-07-03

## Purpose

This spec defines the public launch-readiness pass for LocalQL, the installable
distribution that preserves the `csvql` CLI command, Python import package, and
`.csvql.yml` project configuration contract.

The goal is to make the public repository and package look like a polished,
trustworthy open-source CLI project: clear install path, clean examples, normal
community files, accurate security posture, package metadata, GitHub templates,
and no internal planning or proof artifacts on the public branch.

This is an open-source launch hygiene lane. It does not publish to PyPI, create
a GitHub release, tag the repository, upload artifacts, or claim `v1-stable`.

## Chosen Direction

The approved direction is **Polished Public Launch Pass**.

The launch pass should be designed as one coherent implementation plan with
separate reviewable commits or work packets:

1. public repository surface cleanup
2. open-source trust files
3. package and GitHub metadata
4. README, FAQ, and development-doc polish
5. GitHub issue and pull request templates
6. trusted publishing preparation
7. package-content and proof verification

The implementation should make the repository feel intentional to new users,
outside contributors, GitHub, and PyPI without expanding the product beyond the
existing local CSV plus DuckDB CLI/TUI workflow.

## Design References

This design is informed by standard public project expectations:

- GitHub Open Source Guide: root-level license, README, contributing guide, and
  code of conduct help users understand and participate in a project.
- GitHub security policy documentation: `SECURITY.md` should tell users how to
  report vulnerabilities and what versions or surfaces are supported.
- PyPA packaging guidance: project metadata should include accurate license,
  classifiers, keywords, readme, and project URLs.
- PyPI Trusted Publishers: GitHub Actions can publish using short-lived trusted
  tokens instead of long-lived PyPI API tokens.

## Product Boundary

LocalQL remains a local-first Python CLI distribution for querying local CSV
files through DuckDB.

The public launch pass may improve documentation, metadata, issue templates,
package audit checks, and release-readiness evidence. It must not add:

- web app or hosted dashboard surfaces
- cloud connectors
- notebook framework
- NLP execution
- dataframe-first API
- plugin system
- hidden cache or automatic materialization
- safe mode or sandbox claims
- broad large-file performance claims without proof
- production-readiness claims

User-authored SQL remains trusted local DuckDB SQL. LocalQL does not restrict
DuckDB capabilities, sandbox filesystem access, or make untrusted SQL safe.

## Public Repository Surface

The public branch should read like a polished CLI project, not an internal build
log.

Remove internal/operator-facing material from the public branch with a normal
commit:

- `AGENTS.md`
- `docs/superpowers/**`
- `docs/CODEX_CAPABILITY_REVIEW.md`
- raw proof packet material such as
  `docs/release-candidate-proof-2026-07-02.md`, unless it is rewritten into a
  concise reader-facing readiness summary

Do not rewrite Git history for this cleanup. A normal commit is sufficient
because the cleanup is about public polish, not secret removal.

Keep and polish user/developer-facing material:

- `README.md`
- `CHANGELOG.md`
- `docs/getting-started.md`
- `docs/troubleshooting.md`
- `docs/tui-guide.md`
- `docs/failure-gallery.md`
- `docs/json-contracts.md`
- `docs/release-readiness.md`
- `docs/release-notes/v1.md`
- `docs/benchmarking.md`
- `docs/ARCHITECTURE.md`
- `docs/PRODUCT_DIRECTION.md`
- `docs/ROADMAP.md`
- examples and screenshots

The principle is simple: public docs should answer "Can I trust and use this?"
Internal docs that primarily answer "How did this get built?" should not shape
the first public impression.

## Open-Source Trust Files

Add normal root-level community and trust files:

- `LICENSE`: MIT, matching the current project license declaration.
- `CONTRIBUTING.md`: short contributor front door.
- `CODE_OF_CONDUCT.md`: root-level public conduct policy.
- `SECURITY.md`: vulnerability reporting policy.
- `SUPPORT.md`: simple support expectations.

`CONTRIBUTING.md` should present the project as solo-maintained:

- issues are welcome
- PRs are welcome but accepted selectively
- roadmap remains maintainer-owned
- no support SLA or fast-response promise
- contributions must respect LocalQL's local-first CSV/DuckDB/CLI boundary

`SECURITY.md` should prefer GitHub private vulnerability reporting. It should
tell users not to file public issues with sensitive vulnerability details.

The security policy must be explicit that LocalQL treats user-authored SQL as
trusted local DuckDB SQL. Vulnerability reports are in scope for LocalQL package
behavior, dependency issues, disclosure mistakes, or misleading security claims,
not for making arbitrary untrusted SQL safe.

## Development Documentation

Remove `AGENTS.md` from the public branch, but preserve the useful public
developer guidance in normal docs.

Add `docs/development.md` for deeper maintainer and contributor details:

- `uv` setup and local command execution
- standard local gates
- LocalQL distribution versus `csvql` runtime contract
- trusted local SQL boundary
- release-readiness gates
- package build and content audit expectations
- no-tag, no-publish, no-GitHub-release rule until separate explicit approval

`CONTRIBUTING.md` should stay concise and link to `docs/development.md` for
details.

## FAQ And README UX

Add `docs/faq.md` to answer the questions that are likely to confuse a new
user:

- Why install `localql` but run `csvql`?
- Is SQL sandboxed?
- Can SQL read local files?
- Why not rename the command to `localql`?
- Why use this instead of DuckDB directly?
- Does it support Parquet, cloud sources, NLP, or web dashboards?
- Where are TUI exports and derived result sources written?
- What is stable in v1.0.0?

The README remains the landing page. It should keep leading with installed-user
commands:

```bash
pip install "localql[tui]"
csvql query ...
csvql menu
```

Source checkout and contributor sections may use `uv run ...`. Public
onboarding examples should not make normal users type `uv run` before every
product command.

README links should make the project easy to navigate:

- Getting started
- FAQ
- Troubleshooting
- TUI guide
- Examples
- Changelog and release notes
- Contributing
- Security
- Development

The LocalQL versus `csvql` explanation should be direct: LocalQL is the
installable distribution name; `csvql` remains the CLI command, Python import
package, and config prefix.

## Package And GitHub Metadata

Update package metadata so PyPI has a complete public presentation:

- add `[project.urls]` for Homepage, Repository, Issues, Changelog, and
  Documentation once final GitHub URLs are known
- align license metadata with the new root `LICENSE`
- add or confirm appropriate classifiers for MIT license, OS independence,
  supported Python versions, console environment, and intended audiences
- keep keywords focused on local CSV, DuckDB, SQL, CLI, and local analytics

Do not claim typed-package support through metadata unless the package includes
the required marker file and public typing contract.

Add GitHub templates:

- bug report issue template
- feature request issue template
- documentation issue template
- pull request template

README badges can be added after the public repository and PyPI URLs are final:

- CI
- PyPI version
- Python versions
- license

## Trusted Publishing Preparation

Prepare for PyPI Trusted Publishing through GitHub Actions, but do not perform a
release action in this lane.

The desired publishing posture is:

- no long-lived PyPI API token committed, printed, or required in local docs
- GitHub Actions trusted publisher configuration described or scaffolded
- release workflow requires deliberate release intent, not an incidental push
- final PyPI upload remains a separate explicitly approved action

If a workflow file is added, it should be conservative: manual or tag-based
entrypoint, clear environment name if used, and no automatic publish from normal
branch pushes.

## Package And Repository Hygiene

The implementation should verify that ignored local junk does not become public
or packaged:

- `.DS_Store`
- caches such as `.pytest_cache`, `.mypy_cache`, and `.ruff_cache`
- `.venv`
- `.csvql/`
- `output/`
- `keys.log`
- `csvql_project_pack/`
- `csvql_project_pack.zip`

The wheel should contain only the intended runtime package plus metadata. The
sdist should not include ignored local artifacts or internal build-state files.

Do not run broad deletion commands without explicit approval. If local ignored
files should be cleaned, treat that as a separate explicit cleanup action.

## Verification Target

The launch pass should end with evidence, not publication.

Minimum verification:

```bash
git diff --check
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

Release/package verification:

- build wheel and sdist
- inspect wheel contents
- inspect sdist contents
- run metadata validation if the tool is available in the environment
- run the repo release-readiness script on the final state
- smoke the installed wheel
- smoke the TUI extra

Claim scans should confirm public docs do not claim:

- sandbox safety
- safe execution of untrusted SQL
- production readiness
- security isolation
- broad large-file proof
- hidden cache or automatic materialization
- externally shipped `v1-stable` status

Public command scans should confirm installed-user docs show `csvql ...` and
reserve `uv run ...` for source-checkout or development instructions.

## Hard Release Boundary

This launch-readiness pass must not:

- create a tag
- publish to PyPI
- create a GitHub release
- upload release artifacts
- change the package version
- claim `v1-stable`
- rewrite Git history

Any actual external release action requires separate explicit approval after the
final proof gate passes on the intended release commit.

## Risks And Mitigations

Risk: removing internal docs loses useful project discipline.

Mitigation: preserve useful public rules in `CONTRIBUTING.md` and
`docs/development.md`; remove only Codex/operator-specific material from the
public branch.

Risk: package metadata links are not known yet.

Mitigation: use final GitHub URLs once the public repository location is known;
do not invent placeholder links in committed metadata.

Risk: trusted publishing scaffolding accidentally creates a release path that
runs too broadly.

Mitigation: use explicit manual or tag-based release triggers and keep publish
execution out of normal push workflows.

Risk: public docs overstate security or release maturity.

Mitigation: keep `SECURITY.md`, FAQ, README status, and release-readiness docs
aligned on trusted local SQL and no `v1-stable` claim before explicit release
approval.

## Implementation Handoff

After this spec is reviewed and approved, the next step is a
`superpowers:writing-plans` implementation plan. That plan should convert this
design into a sequenced checklist with file-level edits, verification commands,
and commit boundaries.
