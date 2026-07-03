# LocalQL Open-Source Launch Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare LocalQL for a polished public open-source launch without publishing, tagging, uploading artifacts, changing versions, or claiming `v1-stable`.

**Architecture:** This is a docs, metadata, repository-hygiene, and verification pass. It removes internal operator material from the public branch, adds standard open-source trust files, preserves useful development rules in reader-facing docs, adds GitHub templates and cautious trusted-publishing scaffolding, and verifies public/package contents with tests plus package-audit proof.

**Tech Stack:** Python 3.11+, `uv`, Hatchling, PyPI/PyPA metadata, GitHub Actions, Pytest, Ruff, mypy, Markdown, YAML.

---

## Scope And Release Boundary

This plan must not:

- publish to PyPI
- create a GitHub release
- create or push a tag
- upload release artifacts
- change the package version
- rewrite Git history
- claim `v1-stable`
- delete ignored local junk with broad cleanup commands

The current repo has no configured Git remote. Do not invent public repository
URLs. Add URL metadata and README badges only after Richard provides the final
public GitHub URL during execution.

## File Structure

Create:

- `LICENSE`: MIT license text for the public repo and package metadata.
- `CONTRIBUTING.md`: concise contributor front door for a solo-maintained project.
- `CODE_OF_CONDUCT.md`: root conduct policy.
- `SECURITY.md`: private vulnerability reporting and trusted-local-SQL boundary.
- `SUPPORT.md`: support expectations and issue-routing guidance.
- `docs/development.md`: public developer and maintainer reference replacing useful non-Codex portions of `AGENTS.md`.
- `docs/faq.md`: public answers for LocalQL versus `csvql`, SQL trust boundary, non-goals, and TUI result paths.
- `.github/ISSUE_TEMPLATE/bug_report.yml`: structured bug issue template.
- `.github/ISSUE_TEMPLATE/feature_request.yml`: structured feature issue template.
- `.github/ISSUE_TEMPLATE/docs_issue.yml`: structured docs issue template.
- `.github/pull_request_template.md`: PR checklist.
- `.github/workflows/publish.yml`: manual PyPI Trusted Publishing workflow scaffold.
- `scripts/audit_package_contents.py`: package artifact content audit for wheel and sdist.
- `tests/test_open_source_launch_docs.py`: public repo launch-surface regression tests.
- `tests/test_package_audit.py`: unit tests for the package audit helper.

Modify:

- `README.md`: links to public trust/development docs, FAQ, issue paths, and URL/badge updates if public URL is known.
- `pyproject.toml`: license metadata, classifiers, keywords, and project URLs only if public URL is provided.
- `docs/release-readiness.md`: include package-content audit and trusted publishing boundary.
- `docs/release-notes/v1.md`: keep release language aligned with launch-readiness and no external release action.
- `tests/test_v1_polish_docs.py`: extend existing public-doc command and claim guards if the new FAQ/development docs should be covered.

Remove from the public branch:

- `AGENTS.md`
- `docs/superpowers/**`
- `docs/CODEX_CAPABILITY_REVIEW.md`
- `docs/release-candidate-proof-2026-07-02.md`

Do not remove the ignored local files under `.venv/`, `.pytest_cache/`,
`.mypy_cache/`, `.ruff_cache/`, `.csvql/`, `output/`, `keys.log`,
`csvql_project_pack/`, or `csvql_project_pack.zip` unless Richard separately
approves a local cleanup command.

---

### Task 1: Add Launch-Surface Regression Tests

**Files:**

- Create: `tests/test_open_source_launch_docs.py`
- Modify: `tests/test_v1_polish_docs.py`

- [ ] **Step 1: Create failing tests for the public launch surface**

Create `tests/test_open_source_launch_docs.py` with this content:

```python
from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_open_source_trust_files_exist() -> None:
    for path in (
        "LICENSE",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "SUPPORT.md",
        "docs/development.md",
        "docs/faq.md",
    ):
        assert (REPO_ROOT / path).is_file(), path


def test_internal_operator_material_is_not_on_public_branch() -> None:
    for path in (
        "AGENTS.md",
        "docs/superpowers",
        "docs/CODEX_CAPABILITY_REVIEW.md",
        "docs/release-candidate-proof-2026-07-02.md",
    ):
        assert not (REPO_ROOT / path).exists(), path


def test_readme_links_public_launch_docs() -> None:
    readme = read_text("README.md")

    for expected in (
        "[FAQ](docs/faq.md)",
        "[Contributing](CONTRIBUTING.md)",
        "[Security](SECURITY.md)",
        "[Development](docs/development.md)",
        "[Support](SUPPORT.md)",
    ):
        assert expected in readme


def test_security_and_faq_state_trusted_local_sql_boundary() -> None:
    combined = "\n".join([read_text("SECURITY.md"), read_text("docs/faq.md")])

    assert "trusted local DuckDB SQL" in combined
    assert "does not sandbox DuckDB" in combined
    assert "Do not report sensitive vulnerabilities in public issues" in combined


def test_contributing_sets_solo_maintainer_posture() -> None:
    contributing = read_text("CONTRIBUTING.md")

    assert "solo-maintained" in contributing
    assert "Issues are welcome" in contributing
    assert "Pull requests are reviewed selectively" in contributing
    assert "roadmap remains maintainer-owned" in contributing


def test_github_templates_exist() -> None:
    for path in (
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/ISSUE_TEMPLATE/docs_issue.yml",
        ".github/pull_request_template.md",
        ".github/workflows/publish.yml",
    ):
        assert (REPO_ROOT / path).is_file(), path


def test_pyproject_public_metadata_is_consistent() -> None:
    payload = tomllib.loads(read_text("pyproject.toml"))
    project = payload["project"]

    assert project["name"] == "localql"
    assert project["license"] == "MIT"
    assert "LICENSE" in payload["project"]["license-files"]
    assert "License :: OSI Approved :: MIT License" in project["classifiers"]
    assert "Operating System :: OS Independent" in project["classifiers"]
    assert "csv" in project["keywords"]
    assert "duckdb" in project["keywords"]
    assert "local-analytics" in project["keywords"]


def test_publish_workflow_is_manual_only() -> None:
    workflow = read_text(".github/workflows/publish.yml")

    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert "pull_request:" not in workflow
    assert "pypa/gh-action-pypi-publish" in workflow
    assert "environment: pypi" in workflow
```

- [ ] **Step 2: Extend the public-doc wording guard**

Append this test to `tests/test_v1_polish_docs.py`:

```python
def test_public_launch_docs_state_security_and_release_boundaries() -> None:
    public_docs = "\n".join(
        [
            read_doc("README.md"),
            read_doc("docs/getting-started.md"),
            read_doc("docs/troubleshooting.md"),
            read_doc("docs/tui-guide.md"),
            read_doc("docs/faq.md"),
            read_doc("docs/development.md"),
            read_doc("SECURITY.md"),
            read_doc("CONTRIBUTING.md"),
        ]
    )

    required_boundaries = (
        "does not sandbox DuckDB",
        "trusted local DuckDB SQL",
        "Do not create a tag",
        "publish to PyPI",
        "create a GitHub release",
        "explicit exports",
    )
    for boundary in required_boundaries:
        assert boundary in public_docs
```

- [ ] **Step 3: Run the failing launch-doc tests**

Run:

```bash
uv run pytest tests/test_open_source_launch_docs.py tests/test_v1_polish_docs.py -q
```

Expected result: fails because the launch files, GitHub templates, FAQ, development doc, and metadata updates do not exist yet.

- [ ] **Step 4: Keep the failing tests in the working tree**

Do not commit this task. The launch-surface tests are intentionally red until
the public files, metadata, templates, and internal-doc removals are complete.
They will be committed with the task that turns the launch-surface suite green.

Run:

```bash
git status --short
```

Expected result: `tests/test_open_source_launch_docs.py` is untracked and
`tests/test_v1_polish_docs.py` is modified.

---

### Task 2: Add Open-Source Trust Files

**Files:**

- Create: `LICENSE`
- Create: `CONTRIBUTING.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `SECURITY.md`
- Create: `SUPPORT.md`
- Test: `tests/test_open_source_launch_docs.py`

- [ ] **Step 1: Add the MIT license**

Create `LICENSE` with this text:

```text
MIT License

Copyright (c) 2026 Richard Demke

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Add the contributor guide**

Create `CONTRIBUTING.md` with this structure and required wording:

```markdown
# Contributing

LocalQL is a solo-maintained local-first CLI project. Issues are welcome.
Pull requests are reviewed selectively, and the roadmap remains
maintainer-owned.

## Good First Contributions

- clear bug reports with a small CSV example
- documentation fixes
- examples that use local CSV files
- focused tests for existing behavior
- small CLI/TUI usability fixes that preserve current contracts

## Project Boundaries

LocalQL packages the `csvql` command for local CSV analysis with DuckDB.
The installable distribution is `localql`; the CLI command, Python import
package, and config file remain `csvql`, `csvql`, and `.csvql.yml`.

In-scope contributions stay within local CSV files, DuckDB SQL, CLI/TUI
workflow, explicit exports, project catalogs, tests, and public documentation.

Out-of-scope contributions include web apps, hosted dashboards, cloud
connectors, notebook frameworks, NLP execution, dataframe-first APIs, plugin
systems, hidden caches, automatic materialization, safe-mode claims, sandbox
claims, production-readiness claims, and broad large-file claims without proof.

## Local Setup

```bash
uv sync --all-extras
uv run csvql --help
```

## Checks

Run the standard local gate before opening a pull request:

```bash
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

For package or release-readiness changes, also run the package and
release-readiness checks described in [Development](docs/development.md).

## Pull Requests

Keep pull requests focused. Include tests or docs updates when behavior changes.
Do not mix unrelated cleanup into a feature or bug fix.

## Conduct And Security

Follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report sensitive
vulnerabilities through the path in [Security](SECURITY.md), not public issues.
```

- [ ] **Step 3: Add the code of conduct**

Create `CODE_OF_CONDUCT.md` with this content:

```markdown
# Code of Conduct

## Expected Behavior

Contributors and maintainers are expected to be respectful, direct, and
constructive. Healthy disagreement is welcome when it is focused on the work.

## Unacceptable Behavior

Harassment, personal attacks, discriminatory language, threats, spam, and
deliberate disruption are not acceptable in project spaces.

## Scope

This code of conduct applies to project issues, pull requests, discussions,
documentation, and other public collaboration spaces connected to LocalQL.

## Enforcement

The maintainer may edit, hide, or remove comments; close issues or pull
requests; block participants; or take other reasonable moderation actions to
keep the project usable.

## Reporting

Report conduct concerns to the maintainer through a private GitHub channel when
one is available. Do not include private personal information in public issues.
```

- [ ] **Step 4: Add the security policy**

Create `SECURITY.md` with this content:

```markdown
# Security Policy

## Reporting A Vulnerability

Use GitHub private vulnerability reporting for sensitive security reports when
it is enabled for the public repository.

Do not report sensitive vulnerabilities in public issues. Public issues are
fine for normal bugs, documentation problems, and non-sensitive behavior
questions.

## Supported Versions

Before the first public release, only the current `main` branch is reviewed for
security reports. After the first public release, the current published release
line is the supported line unless release notes say otherwise.

## Security Boundary

LocalQL treats user-authored SQL as trusted local DuckDB SQL. It does not
sandbox DuckDB, restrict DuckDB filesystem access, or make untrusted SQL safe.

Security reports are useful when they concern LocalQL package behavior,
dependency vulnerabilities, accidental disclosure, misleading security claims,
or behavior that contradicts documented local-only expectations.
```

- [ ] **Step 5: Add the support policy**

Create `SUPPORT.md` with this content:

```markdown
# Support

LocalQL is a solo-maintained open-source project.

Use GitHub issues for reproducible bugs, documentation problems, and focused
feature requests. Include the command you ran, a small CSV example when
possible, your Python version, your operating system, and the full error output.

There is no support SLA. The maintainer may close issues that are outside the
project scope or that cannot be reproduced with local files.

For sensitive vulnerability reports, use the path in [Security](SECURITY.md)
instead of a public issue.
```

- [ ] **Step 6: Run the trust-file tests**

Run:

```bash
uv run pytest tests/test_open_source_launch_docs.py::test_open_source_trust_files_exist tests/test_open_source_launch_docs.py::test_contributing_sets_solo_maintainer_posture tests/test_open_source_launch_docs.py::test_security_and_faq_state_trusted_local_sql_boundary -q
```

Expected result: trust-file existence and contributor posture assertions pass; FAQ-related assertions still fail until `docs/faq.md` exists.

- [ ] **Step 7: Commit the trust files**

Run:

```bash
git add LICENSE CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md SUPPORT.md
git commit -m "docs: add open-source trust files"
```

---

### Task 3: Add Development And FAQ Docs

**Files:**

- Create: `docs/development.md`
- Create: `docs/faq.md`
- Modify: `docs/release-readiness.md`
- Modify: `docs/release-notes/v1.md`
- Test: `tests/test_open_source_launch_docs.py`
- Test: `tests/test_v1_polish_docs.py`

- [ ] **Step 1: Create the development reference**

Create `docs/development.md` with these sections and required content:

```markdown
# Development

This page is for contributors and maintainers working from a source checkout.
For normal usage, install LocalQL and run the `csvql` command.

## Naming Contract

LocalQL is the installable distribution name. The CLI command remains `csvql`,
the Python import package remains `csvql`, and the project configuration file
remains `.csvql.yml`.

## Local Setup

```bash
uv sync --all-extras
uv run csvql --help
```

## Local Gates

```bash
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

## SQL Trust Boundary

LocalQL treats user-authored SQL as trusted local DuckDB SQL. It does not
sandbox DuckDB, restrict DuckDB filesystem access, or make untrusted SQL safe.
Do not document or implement safe-mode behavior without a dedicated design,
tests, and explicit maintainer approval.

## Package Audit

Before external release approval, build and inspect the package artifacts:

```bash
uv build --sdist --wheel --out-dir output/package-audit/dist
uv run python scripts/audit_package_contents.py output/package-audit/dist
```

The audit should reject `.DS_Store`, caches, virtual environments, `.csvql/`,
`output/`, `keys.log`, `csvql_project_pack/`, `csvql_project_pack.zip`, and
internal planning material.

## Release Readiness

Run the repo-local release-readiness proof on the final intended release state:

```bash
uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness-localql-public
```

This proof builds the package, installs the built wheel, smokes the installed
`csvql` command, and verifies the optional TUI extra import.

## Release Boundary

Do not create a tag, publish to PyPI, create a GitHub release, upload artifacts,
change the package version, or claim `v1-stable` without separate explicit
approval after final proof passes.
```

- [ ] **Step 2: Create the FAQ**

Create `docs/faq.md` with these sections and required answers:

```markdown
# FAQ

## Why do I install `localql` but run `csvql`?

`localql` is the installable distribution name. The command remains `csvql`
because the tool is still the CSV query workflow users type in the terminal.
The Python import package also remains `csvql`, and project config remains
`.csvql.yml`.

## Is SQL sandboxed?

No. LocalQL treats user-authored SQL as trusted local DuckDB SQL. It does not
sandbox DuckDB, restrict DuckDB filesystem access, or make untrusted SQL safe.

## Can SQL read local files?

DuckDB SQL can access local files according to DuckDB behavior and your local
environment. Only run SQL you trust.

## Why use this instead of DuckDB directly?

DuckDB owns SQL execution. LocalQL adds a local workflow around CSV table
aliases, project catalogs, saved SQL files, readable terminal output, explicit
exports, data-quality checks, troubleshooting commands, and the optional TUI.

## Does LocalQL support Parquet, cloud sources, NLP, or web dashboards?

Not in v1.0.0. The v1 scope is local CSV files, DuckDB SQL, CLI workflow,
project catalogs, explicit exports, and the optional terminal menu.

## Where do TUI result sources go?

When you explicitly save a successful tabular result in the TUI, LocalQL writes
`.csvql/results/{alias}.csv` and adds that alias to the current TUI session.
The file remains on disk. The alias becomes durable across sessions only if you
explicitly save sources to `.csvql.yml`.

## What is stable in v1.0.0?

The v1.0.0 target covers the documented CLI commands, project catalog workflow,
saved SQL execution, explicit exports, JSON/table output contracts where
documented, local release-readiness proof, and the optional TUI entrypoint.
External publication requires a separate release approval.
```

- [ ] **Step 3: Update release-readiness docs**

In `docs/release-readiness.md`, add a package audit subsection with this text:

```markdown
## Package Content Audit

Before external release approval, build the wheel and sdist and inspect their
contents:

```bash
uv build --sdist --wheel --out-dir output/package-audit/dist
uv run python scripts/audit_package_contents.py output/package-audit/dist
```

The audit rejects ignored local artifacts and internal planning material. It is
part of the launch-readiness gate, not a PyPI upload.
```

- [ ] **Step 4: Update v1 release notes with public launch boundary**

In `docs/release-notes/v1.md`, add a short note near the status/release boundary:

```markdown
Public launch hygiene adds standard open-source trust files, public development
docs, FAQ coverage, GitHub templates, and package-content audit checks. This
does not create a tag, publish to PyPI, create a GitHub release, upload
artifacts, or claim `v1-stable`.
```

- [ ] **Step 5: Run focused docs tests**

Run:

```bash
uv run pytest tests/test_open_source_launch_docs.py tests/test_v1_polish_docs.py -q
```

Expected result: trust files, FAQ, development docs, security boundary, and claim-scan tests pass except checks that depend on GitHub templates, metadata, or removed internal docs.

- [ ] **Step 6: Commit public docs**

Run:

```bash
git add docs/development.md docs/faq.md docs/release-readiness.md docs/release-notes/v1.md
git commit -m "docs: add public FAQ and development guide"
```

---

### Task 4: Remove Internal Public-Branch Material

**Files:**

- Delete: `AGENTS.md`
- Delete: `docs/superpowers/**`
- Delete: `docs/CODEX_CAPABILITY_REVIEW.md`
- Delete: `docs/release-candidate-proof-2026-07-02.md`
- Test: `tests/test_open_source_launch_docs.py`

- [ ] **Step 1: Copy this plan outside the repo before deleting `docs/superpowers`**

Run:

```bash
cp docs/superpowers/plans/2026-07-03-localql-open-source-launch-readiness.md /private/tmp/localql-open-source-launch-readiness-plan.md
```

Expected result: `/private/tmp/localql-open-source-launch-readiness-plan.md`
exists. Use that copy for the remaining tasks after `docs/superpowers` is
removed from the public branch.

- [ ] **Step 2: Remove internal tracked files**

Run:

```bash
git rm AGENTS.md
git rm -r docs/superpowers
git rm docs/CODEX_CAPABILITY_REVIEW.md
git rm docs/release-candidate-proof-2026-07-02.md
```

- [ ] **Step 3: Confirm no tracked internal paths remain**

Run:

```bash
git ls-files AGENTS.md docs/superpowers docs/CODEX_CAPABILITY_REVIEW.md docs/release-candidate-proof-2026-07-02.md
```

Expected output: no output.

- [ ] **Step 4: Run the internal-material guard**

Run:

```bash
uv run pytest tests/test_open_source_launch_docs.py::test_internal_operator_material_is_not_on_public_branch -q
```

Expected result: pass.

- [ ] **Step 5: Commit internal-material removal**

Run:

```bash
git add -u AGENTS.md docs/superpowers docs/CODEX_CAPABILITY_REVIEW.md docs/release-candidate-proof-2026-07-02.md
git commit -m "docs: remove internal launch artifacts from public branch"
```

---

### Task 5: Update Package Metadata And README Navigation

**Files:**

- Modify: `pyproject.toml`
- Modify: `README.md`
- Test: `tests/test_open_source_launch_docs.py`
- Test: `tests/test_v1_polish_docs.py`

- [ ] **Step 1: Check for the public repository URL**

Run:

```bash
git remote get-url origin
```

Current expected result in this repo: command exits nonzero because no remote is configured.

If Richard provides a final public GitHub URL before this task executes, add
`[project.urls]` and README badges with that exact URL. If no URL is provided,
do not add URL metadata or badges in this task; record in the final handoff
that URL/badge metadata remains gated on the public repository URL.

- [ ] **Step 2: Update license metadata and classifiers**

In `pyproject.toml`, change the project metadata to this shape while preserving the existing version, dependencies, optional dependencies, scripts, and tool sections:

```toml
[project]
name = "localql"
version = "1.0.0"
description = "LocalQL packages csvql, a DuckDB-powered CLI for querying local CSV files like SQL tables."
readme = "README.md"
requires-python = ">=3.11,<3.14"
license = "MIT"
license-files = ["LICENSE"]
authors = [{ name = "Richard Demke" }]
keywords = ["csv", "duckdb", "sql", "cli", "local-analytics", "data-engineering"]
classifiers = [
    "Environment :: Console",
    "Intended Audience :: Developers",
    "Intended Audience :: Science/Research",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Database",
    "Topic :: Utilities",
]
```

If the public repository URL is known, add `[project.urls]` immediately after
the classifiers block. Use the exact public GitHub URL for Homepage and
Repository, append `/issues` for Issues, append `/blob/main/CHANGELOG.md` for
Changelog, and append `#readme` for Documentation. If the URL is not known,
omit `[project.urls]`.

- [ ] **Step 3: Update README navigation**

In `README.md`, add a concise navigation section after the Quickstart command-mode bullets:

```markdown
## Project Links

- [Getting started](docs/getting-started.md)
- [FAQ](docs/faq.md)
- [Troubleshooting](docs/troubleshooting.md)
- [TUI guide](docs/tui-guide.md)
- [Examples](examples/saas_revenue/README.md)
- [Changelog](CHANGELOG.md)
- [Release notes](docs/release-notes/v1.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Support](SUPPORT.md)
- [Development](docs/development.md)
```

If the public GitHub URL and PyPI project page are known, add badges below `# LocalQL` for CI, PyPI version, Python versions, and license. Do not add badges with guessed URLs.

- [ ] **Step 4: Run metadata and README tests**

Run:

```bash
uv run pytest tests/test_open_source_launch_docs.py::test_pyproject_public_metadata_is_consistent tests/test_open_source_launch_docs.py::test_readme_links_public_launch_docs -q
```

Expected result: pass.

- [ ] **Step 5: Run the existing public command split guard**

Run:

```bash
uv run pytest tests/test_v1_polish_docs.py::test_public_onboarding_uses_installed_cli_command -q
```

Expected result: pass. README public examples still use installed `csvql ...` commands; source-checkout sections still use `uv run ...`.

- [ ] **Step 6: Commit metadata and README navigation**

Run:

```bash
git add pyproject.toml README.md
git commit -m "docs: polish public package metadata and navigation"
```

---

### Task 6: Add GitHub Templates And Manual Publish Workflow

**Files:**

- Create: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Create: `.github/ISSUE_TEMPLATE/feature_request.yml`
- Create: `.github/ISSUE_TEMPLATE/docs_issue.yml`
- Create: `.github/pull_request_template.md`
- Create: `.github/workflows/publish.yml`
- Test: `tests/test_open_source_launch_docs.py`

- [ ] **Step 1: Add the bug report template**

Create `.github/ISSUE_TEMPLATE/bug_report.yml`:

```yaml
name: Bug report
description: Report a reproducible LocalQL problem
title: "[Bug]: "
labels: ["bug"]
body:
  - type: markdown
    attributes:
      value: "Thanks for helping improve LocalQL. Please include a small local CSV example when possible."
  - type: textarea
    id: command
    attributes:
      label: Command
      description: Paste the exact command you ran.
      render: shell
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: Expected behavior
    validations:
      required: true
  - type: textarea
    id: actual
    attributes:
      label: Actual behavior
      description: Include the full error output.
      render: text
    validations:
      required: true
  - type: input
    id: version
    attributes:
      label: LocalQL version
      description: Run `csvql --version`.
    validations:
      required: true
  - type: input
    id: python
    attributes:
      label: Python version
      description: Run `python --version`.
    validations:
      required: false
  - type: input
    id: os
    attributes:
      label: Operating system
    validations:
      required: true
```

- [ ] **Step 2: Add the feature request template**

Create `.github/ISSUE_TEMPLATE/feature_request.yml`:

```yaml
name: Feature request
description: Suggest a focused LocalQL improvement
title: "[Feature]: "
labels: ["enhancement"]
body:
  - type: markdown
    attributes:
      value: "LocalQL is local-first: CSV files, DuckDB SQL, CLI/TUI workflow, explicit exports, and project catalogs."
  - type: textarea
    id: problem
    attributes:
      label: Problem
      description: What local CSV workflow problem would this solve?
    validations:
      required: true
  - type: textarea
    id: proposal
    attributes:
      label: Proposed behavior
    validations:
      required: true
  - type: checkboxes
    id: scope
    attributes:
      label: Scope check
      options:
        - label: This stays within local CSV, DuckDB SQL, CLI/TUI workflow, explicit exports, or project catalogs.
          required: true
        - label: This does not require a web app, cloud connector, NLP execution, hidden cache, or sandbox-safe SQL claim.
          required: true
```

- [ ] **Step 3: Add the docs issue template**

Create `.github/ISSUE_TEMPLATE/docs_issue.yml`:

```yaml
name: Documentation issue
description: Report confusing, stale, or missing docs
title: "[Docs]: "
labels: ["documentation"]
body:
  - type: input
    id: page
    attributes:
      label: Page or section
      description: Link or name the page.
    validations:
      required: true
  - type: textarea
    id: issue
    attributes:
      label: What is confusing or missing?
    validations:
      required: true
  - type: textarea
    id: suggestion
    attributes:
      label: Suggested wording
      description: Optional exact replacement text.
    validations:
      required: false
```

- [ ] **Step 4: Add the PR template**

Create `.github/pull_request_template.md`:

```markdown
## Summary

## Scope Check

- [ ] This change stays within LocalQL's local CSV, DuckDB, CLI/TUI, explicit export, project catalog, docs, or test scope.
- [ ] This change does not add web app, cloud connector, NLP execution, hidden cache, sandbox-safe SQL, or production-readiness claims.
- [ ] Public examples use installed `csvql ...` commands unless the section is specifically for source-checkout development.

## Verification

- [ ] `uv run ruff format --check .`
- [ ] `uv run ruff check .`
- [ ] `uv run --all-extras mypy src`
- [ ] `uv run --all-extras pytest`

## Notes
```

- [ ] **Step 5: Add the manual trusted-publishing workflow scaffold**

Create `.github/workflows/publish.yml`:

```yaml
name: publish

on:
  workflow_dispatch:

permissions:
  contents: read
  id-token: write

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Set up Python
        run: uv python install 3.12
      - name: Install dependencies
        run: uv sync --all-extras --frozen
      - name: Check formatting
        run: uv run ruff format --check .
      - name: Lint
        run: uv run ruff check .
      - name: Type check
        run: uv run --all-extras mypy src
      - name: Test
        run: uv run --all-extras pytest
      - name: Build
        run: uv build --sdist --wheel --out-dir dist
      - name: Audit package contents
        run: uv run python scripts/audit_package_contents.py dist
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 6: Run the public launch-surface tests**

Run:

```bash
uv run pytest tests/test_open_source_launch_docs.py tests/test_v1_polish_docs.py -q
```

Expected result: pass.

- [ ] **Step 7: Commit GitHub templates and launch-surface tests**

Run:

```bash
git add .github/ISSUE_TEMPLATE/bug_report.yml .github/ISSUE_TEMPLATE/feature_request.yml .github/ISSUE_TEMPLATE/docs_issue.yml .github/pull_request_template.md .github/workflows/publish.yml tests/test_open_source_launch_docs.py tests/test_v1_polish_docs.py
git commit -m "ci: prepare open-source issue templates and publishing workflow"
```

---

### Task 7: Add Package Content Audit Helper

**Files:**

- Create: `scripts/audit_package_contents.py`
- Create: `tests/test_package_audit.py`
- Modify: `.github/workflows/publish.yml`
- Modify: `docs/development.md`
- Modify: `docs/release-readiness.md`

- [ ] **Step 1: Add tests for package content audit**

Create `tests/test_package_audit.py`:

```python
from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

from scripts.audit_package_contents import audit_archives, find_archives, forbidden_entries


def write_wheel(path: Path, names: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, "")


def write_sdist(path: Path, names: list[str]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name in names:
            file_path = path.parent / name.replace("/", "_")
            file_path.write_text("", encoding="utf-8")
            archive.add(file_path, arcname=name)


def test_forbidden_entries_detects_internal_and_ignored_paths() -> None:
    names = [
        "localql-1.0.0/README.md",
        "localql-1.0.0/docs/superpowers/specs/design.md",
        "localql-1.0.0/.DS_Store",
        "localql-1.0.0/output/proof.json",
        "localql-1.0.0/csvql_project_pack.zip",
    ]

    assert forbidden_entries(names) == [
        "localql-1.0.0/docs/superpowers/specs/design.md",
        "localql-1.0.0/.DS_Store",
        "localql-1.0.0/output/proof.json",
        "localql-1.0.0/csvql_project_pack.zip",
    ]


def test_find_archives_requires_wheel_and_sdist(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.0-py3-none-any.whl"
    sdist = tmp_path / "localql-1.0.0.tar.gz"
    wheel.write_text("", encoding="utf-8")
    sdist.write_text("", encoding="utf-8")

    assert find_archives(tmp_path) == ([wheel], [sdist])


def test_audit_archives_accepts_clean_package(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.0-py3-none-any.whl"
    sdist = tmp_path / "localql-1.0.0.tar.gz"
    write_wheel(wheel, ["csvql/__init__.py", "localql-1.0.0.dist-info/METADATA"])
    write_sdist(sdist, ["localql-1.0.0/README.md", "localql-1.0.0/src/csvql/__init__.py"])

    audit_archives([wheel], [sdist])


def test_audit_archives_rejects_forbidden_package_entries(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.0-py3-none-any.whl"
    sdist = tmp_path / "localql-1.0.0.tar.gz"
    write_wheel(wheel, ["csvql/__init__.py", ".DS_Store"])
    write_sdist(sdist, ["localql-1.0.0/README.md"])

    try:
        audit_archives([wheel], [sdist])
    except SystemExit as exc:
        assert "Forbidden package entries" in str(exc)
    else:
        raise AssertionError("Expected SystemExit for forbidden package entry")
```

- [ ] **Step 2: Run the failing package audit tests**

Run:

```bash
uv run pytest tests/test_package_audit.py -q
```

Expected result: fails because `scripts/audit_package_contents.py` does not exist yet.

- [ ] **Step 3: Implement the package content audit helper**

Create `scripts/audit_package_contents.py`:

```python
"""Audit built wheel and sdist contents for public release hygiene."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path

FORBIDDEN_NAMES = {
    ".DS_Store",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    ".csvql",
    "output",
    "keys.log",
    "csvql_project_pack",
    "csvql_project_pack.zip",
    "AGENTS.md",
}

FORBIDDEN_PATH_PARTS = {
    "docs/superpowers",
    "docs/CODEX_CAPABILITY_REVIEW.md",
    "docs/release-candidate-proof-2026-07-02.md",
}


def archive_names_from_wheel(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return sorted(archive.namelist())


def archive_names_from_sdist(path: Path) -> list[str]:
    with tarfile.open(path) as archive:
        return sorted(archive.getnames())


def forbidden_entries(names: list[str]) -> list[str]:
    blocked: list[str] = []
    for name in names:
        normalized = name.strip("/")
        parts = normalized.split("/")
        if any(part in FORBIDDEN_NAMES for part in parts):
            blocked.append(name)
            continue
        if any(forbidden in normalized for forbidden in FORBIDDEN_PATH_PARTS):
            blocked.append(name)
    return blocked


def find_archives(dist_dir: Path) -> tuple[list[Path], list[Path]]:
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if not wheels:
        raise SystemExit(f"No wheel found in {dist_dir}")
    if not sdists:
        raise SystemExit(f"No sdist found in {dist_dir}")
    return wheels, sdists


def audit_archives(wheels: list[Path], sdists: list[Path]) -> None:
    failures: list[str] = []
    for wheel in wheels:
        names = archive_names_from_wheel(wheel)
        if not any(name.startswith("csvql/") for name in names):
            failures.append(f"{wheel}: missing csvql package files")
        for entry in forbidden_entries(names):
            failures.append(f"{wheel}: {entry}")
    for sdist in sdists:
        names = archive_names_from_sdist(sdist)
        for entry in forbidden_entries(names):
            failures.append(f"{sdist}: {entry}")
    if failures:
        rendered = "\n".join(failures)
        raise SystemExit(f"Forbidden package entries found:\n{rendered}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    args = parser.parse_args()

    wheels, sdists = find_archives(args.dist_dir)
    audit_archives(wheels, sdists)
    print(
        "Package content audit passed: "
        f"{len(wheels)} wheel(s), {len(sdists)} sdist(s)."
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run package audit tests**

Run:

```bash
uv run pytest tests/test_package_audit.py -q
```

Expected result: pass.

- [ ] **Step 5: Commit package audit helper**

Run:

```bash
git add scripts/audit_package_contents.py tests/test_package_audit.py docs/development.md docs/release-readiness.md .github/workflows/publish.yml
git commit -m "test: add package content audit"
```

---

### Task 8: Run Focused Launch Verification

**Files:**

- Check: all launch docs, tests, metadata, templates, and internal-removal paths

- [ ] **Step 1: Run focused launch tests**

Run:

```bash
uv run pytest tests/test_open_source_launch_docs.py tests/test_package_audit.py tests/test_v1_polish_docs.py -q
```

Expected result: all selected tests pass.

- [ ] **Step 2: Run format/lint checks on changed files**

Run:

```bash
uv run ruff format --check tests/test_open_source_launch_docs.py tests/test_package_audit.py scripts/audit_package_contents.py
uv run ruff check tests/test_open_source_launch_docs.py tests/test_package_audit.py scripts/audit_package_contents.py
```

Expected result: both commands pass.

- [ ] **Step 3: Run Markdown/public wording scans**

Run:

```bash
rg -n "v1-stable|production-ready|sandbox-safe|safe for untrusted SQL|security isolation|large-file proven|hidden cache|automatic materialization" README.md docs CONTRIBUTING.md SECURITY.md SUPPORT.md CODE_OF_CONDUCT.md
```

Expected result: any matches are explicit non-claims, guardrails, or release-boundary language. A sentence claiming the project is sandbox-safe, production-ready, large-file-proven, or externally stable blocks completion.

- [ ] **Step 4: Confirm internal docs are absent from tracked files**

Run:

```bash
git ls-files | rg '^(AGENTS.md|docs/superpowers/|docs/CODEX_CAPABILITY_REVIEW.md|docs/release-candidate-proof-2026-07-02.md)$'
```

Expected result: command exits with no matches.

- [ ] **Step 5: Confirm ignored local junk is not tracked**

Run:

```bash
git ls-files | rg '(^|/)(\.DS_Store|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.venv|keys\.log|csvql_project_pack\.zip)$|^output/|^\.csvql/|^csvql_project_pack/'
```

Expected result: no tracked junk artifacts.

- [ ] **Step 6: Commit any fixes from focused verification**

If Steps 1-5 required fixes, commit them:

```bash
git add README.md pyproject.toml docs tests scripts .github CONTRIBUTING.md SECURITY.md SUPPORT.md CODE_OF_CONDUCT.md LICENSE
git commit -m "chore: finish launch-readiness focused verification"
```

If Steps 1-5 passed without changes, do not create an empty commit.

---

### Task 9: Build, Audit, And Run Release-Readiness Proof

**Files:**

- Check: built artifacts under ignored `output/`
- Check: final repo status

- [ ] **Step 1: Build wheel and sdist into ignored output**

Run:

```bash
uv build --sdist --wheel --out-dir output/package-audit/dist
```

Expected result: `output/package-audit/dist/localql-1.0.0-py3-none-any.whl` and `output/package-audit/dist/localql-1.0.0.tar.gz` exist.

- [ ] **Step 2: Audit package contents**

Run:

```bash
uv run python scripts/audit_package_contents.py output/package-audit/dist
```

Expected result:

```text
Package content audit passed: 1 wheel(s), 1 sdist(s).
```

- [ ] **Step 3: Run release-readiness proof**

Run:

```bash
uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness-localql-public
```

Expected result includes:

```text
Release readiness proof passed.
Distribution: localql
Versions: pyproject=1.0.0, package=1.0.0, cli=1.0.0
TUI extra import: tui-extra-ok
```

- [ ] **Step 4: Run full local gate**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

Expected result: all commands pass.

- [ ] **Step 5: Run final diff and status checks**

Run:

```bash
git diff --check
git status --short --branch
git log -1 --oneline
```

Expected result: `git diff --check` has no output. `git status --short --branch` shows only the branch line unless verification generated ignored files under `output/`.

- [ ] **Step 6: Final launch-readiness handoff**

Report:

- commits created
- files added, modified, and removed
- focused tests and full gates run
- package audit result
- release-readiness proof result
- whether public URL/badge metadata was added or left gated on the public GitHub URL
- confirmation that no tag, PyPI upload, GitHub release, artifact upload, version change, history rewrite, or `v1-stable` claim happened

Do not publish or tag.

---

## Self-Review Checklist

Spec coverage:

- Public repository surface cleanup is covered by Task 4 and Task 8.
- Open-source trust files are covered by Task 2.
- Package metadata and GitHub metadata are covered by Task 5 and Task 6.
- README, FAQ, and development docs are covered by Task 3 and Task 5.
- Trusted Publishing preparation is covered by Task 6.
- Package-content and proof verification are covered by Task 7, Task 8, and Task 9.
- The hard release boundary is stated in the scope section and final handoff.

Execution notes:

- The plan intentionally avoids guessed public URLs because no Git remote is configured.
- The plan uses a normal commit to remove internal material and does not rewrite history.
- The plan does not include broad cleanup of ignored local files.
