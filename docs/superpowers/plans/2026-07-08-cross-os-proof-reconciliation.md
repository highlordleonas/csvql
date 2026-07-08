# Cross-OS Proof Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile tracked release-proof docs, guard tests, and CI so cross-OS automated proof claims stay same-HEAD, auditable, and Python-version-correct.

**Architecture:** Guard tests define the proof contract first, then tracked docs and the GitHub Actions workflow are changed only enough to satisfy those tests. Fresh hosted CI evidence is collected after the implementation commit and recorded in ignored proof output plus the final execution response, not embedded into tracked docs as a self-referential run id.

**Tech Stack:** Python, pytest, PyYAML, Markdown authority docs, GitHub Actions, `uv`, Ruff, mypy.

## Global Constraints

- LocalQL is the installable distribution name.
- Runtime contract remains: CLI command `csvql`, Python import package `csvql`, config `.csvql.yml`, TUI command `csvql menu`.
- Use `uv`; do not install global dependencies.
- Treat user-authored SQL as trusted local DuckDB SQL.
- Do not claim sandbox safety, safe untrusted SQL, security isolation, production readiness, or broad large-file proof.
- Do not add a web app, cloud connectors, NLP execution, dataframe-first API, plugin system, hidden cache/materialization, or broader platform scope.
- Do not tag, publish to PyPI, create GitHub release, upload release artifacts, change version, or claim `v1-stable`.
- Do not push, trigger hosted CI, or collect private GitHub Actions logs until the execution lane receives separate explicit approval for remote actions.
- Windows and Linux screenshots or manual terminal media are not required for the current automated lane.
- Automated proof does not prove Windows Terminal or Linux desktop-terminal UX details.
- Fresh post-change GitHub Actions run id and implementation commit SHA belong in the ignored proof packet `RESULT.md` and final execution response, not in tracked docs as current proof for their own commit.
- Before tracked documentation edits, use the `documentation` skill.
- Before editing `tests/**/*.py`, `.github/workflows/**`, Python tooling, `uv` behavior, package metadata, or CI commands, use the `python-codebase-standards` skill.
- This plan embeds failing-test-first steps for guard tests and CI behavior.
- If CI behavior contradicts assumptions, use `superpowers:systematic-debugging` before making another fix.
- Before claiming completion, use `superpowers:verification-before-completion`.

---

## File Structure

- Modify `tests/test_v1_polish_docs.py` to add a tracked-proof reconciliation guard and replace brittle CI YAML text matching with semantic PyYAML checks.
- Modify `docs/tui-qol-qa.md` to record `b118a2c` as blocked or superseded, `d8ec3df` / run `28965686605` as historical prior proof context, and the ignored-packet/final-response recording model for fresh proof.
- Modify `docs/release-readiness.md` to keep release classification tied to fresh same-HEAD proof and prevent tracked docs from requiring a self-referential CI run id.
- Modify `docs/release-notes/v1.md` to mirror the release-readiness proof wording for the v1 packet.
- Modify `.github/workflows/ci.yml` to force `uv` to use the matrix Python with job-level `UV_PYTHON: ${{ matrix.python-version }}` while keeping `uv python install ${{ matrix.python-version }}`.
- Create ignored proof output only after separately approved remote execution, using `output/tui-qol-qa/$(date +%Y%m%d)-$(git rev-parse --short HEAD)-cross-os-automated/RESULT.md`.

## Task 1: Baseline And Skill Activation

**Files:**
- Read: `docs/superpowers/specs/2026-07-08-cross-os-proof-reconciliation-design.md`
- Read: `docs/tui-qol-qa.md`
- Read: `docs/release-readiness.md`
- Read: `docs/release-notes/v1.md`
- Read: `tests/test_v1_polish_docs.py`
- Read: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: approved design requirements and current repo state.
- Produces: confirmed clean starting point for tracked implementation work.

- [ ] **Step 1: Re-run live repo truth**

Run each command from the repo root:

```bash
pwd -P
git status --short --branch
git log -1 --oneline
git remote -v
git tag --points-at HEAD
find . -maxdepth 4 -name AGENTS.md -o -name AGENTS.override.md
```

Expected:

- `git status --short --branch` shows `main` and only expected local ahead status or tracked edits from this execution lane.
- `git log -1 --oneline` is recorded before edits.
- `git tag --points-at HEAD` is empty unless a future explicit release action created a tag.
- The repo-local AGENTS search prints no files unless a later user-added repo instruction file exists.

- [ ] **Step 2: Activate required skills for the next edits**

Before Task 2, read and apply the `documentation` skill because tracked docs will change.

Before Task 4, read and apply the `python-codebase-standards` skill because tests and CI will change.

- [ ] **Step 3: Confirm PyYAML is already available**

Run:

```bash
rg -n "pyyaml|PyYAML|yaml" pyproject.toml uv.lock tests
```

Expected:

- `pyproject.toml` includes `pyyaml>=6.0.3`.
- Existing tests already import `yaml`, so `tests/test_v1_polish_docs.py` can use `yaml.safe_load` without adding dependencies.

## Task 2: Add Failing Guard For Historical Proof Semantics

**Files:**
- Modify: `docs/superpowers/plans/2026-07-08-cross-os-proof-reconciliation.md`
- Modify: `tests/test_v1_polish_docs.py`
- Test: `tests/test_v1_polish_docs.py`

**Interfaces:**
- Consumes: `read_doc(path: str) -> str` and `normalized_markdown_text(text: str) -> str`.
- Produces: `test_cross_os_proof_docs_record_prior_proof_without_current_head_claim`.

- [ ] **Step 1: Add the failing tracked-proof reconciliation test**

Insert this test after `test_release_docs_require_approved_cross_os_automated_tui_proof_gate`:

```python
def test_cross_os_proof_docs_record_prior_proof_without_current_head_claim() -> None:
    tui_qol = read_doc("docs/tui-qol-qa.md")
    readiness = read_doc("docs/release-readiness.md")
    release_notes = read_doc("docs/release-notes/v1.md")
    combined = "\n".join([tui_qol, readiness, release_notes])
    normalized_combined = normalized_markdown_text(combined)

    for required_text in (
        "b118a2c",
        "blocked `b118a2c`",
        "superseded",
        "d8ec3df",
        "28965686605",
        "historical prior proof context",
        "not final proof for later implementation commits",
        "ignored proof packet `RESULT.md` and final execution response",
        "must not require a self-referential run id",
    ):
        assert required_text in normalized_combined

    assert "Windows and Linux screenshots or manual terminal media are not required" in (
        normalized_combined
    )
    assert "automated proof does not prove manual terminal UX" in normalized_combined
    assert "`v1-stable`" in combined
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_cross_os_proof_docs_record_prior_proof_without_current_head_claim -q
```

Expected: FAIL because the tracked docs do not yet cite `b118a2c`, `d8ec3df`, run `28965686605`, and the self-referential proof rule together.

## Task 3: Update Tracked Docs To Pass Historical Proof Guard

**Files:**
- Modify: `docs/tui-qol-qa.md`
- Modify: `docs/release-readiness.md`
- Modify: `docs/release-notes/v1.md`
- Test: `tests/test_v1_polish_docs.py`

**Interfaces:**
- Consumes: `test_cross_os_proof_docs_record_prior_proof_without_current_head_claim`.
- Produces: tracked docs that state historical proof context without claiming current same-HEAD proof for later commits.

- [ ] **Step 1: Update `docs/tui-qol-qa.md` historical evidence bullets**

In `docs/tui-qol-qa.md`, in the `Historical local evidence remains useful context:` list, keep the existing macOS, VS Code, iTerm2, and tmux/SSH bullets, then replace the current Windows/Linux automated bullet with these bullets:

```markdown
- The blocked `b118a2c` automated packet is superseded and must not be treated
  as the passing Windows candidate.
- Commit `d8ec3df` and GitHub Actions run `28965686605` are historical prior
  proof context for an earlier candidate, not final proof for later
  implementation commits.
- Current automated proof for a new implementation commit must be recorded in
  the ignored proof packet `RESULT.md` and final execution response before
  claiming same-`HEAD` pass.
- Tracked docs define the proof contract and must not require a
  self-referential run id for their own commit unless a separate two-SHA proof
  recording model is approved.
- Windows and Linux require same-`HEAD` automated support proof before the
  final TUI proof result can pass; screenshots are not required for those OS
  rows.
```

- [ ] **Step 2: Update `docs/tui-qol-qa.md` automated proof section**

In `docs/tui-qol-qa.md`, after the paragraph that begins `Release-readiness proof, package-content audit`, add:

```markdown
For implementation changes after a cited proof run, record the fresh GitHub
Actions run id and implementation commit SHA in the ignored proof packet
`RESULT.md` and final execution response. Tracked docs must not require a
self-referential run id for their own commit; doing so creates proof churn
unless a separate two-SHA proof recording model is approved.
```

- [ ] **Step 3: Update `docs/release-readiness.md` TUI proof wording**

In `docs/release-readiness.md`, after the paragraph that ends `Plain \`csvql --version\` is not sufficient for source-checkout proof.`, add:

```markdown
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
```

- [ ] **Step 4: Update `docs/release-notes/v1.md` TUI proof wording**

In `docs/release-notes/v1.md`, after the paragraph that ends `Plain \`csvql --version\` is not sufficient for source-checkout proof.`, add:

```markdown
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
```

- [ ] **Step 5: Run the focused docs guard**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_cross_os_proof_docs_record_prior_proof_without_current_head_claim -q
```

Expected: PASS.

- [ ] **Step 6: Commit the docs proof contract**

Run:

```bash
git add docs/superpowers/plans/2026-07-08-cross-os-proof-reconciliation.md docs/tui-qol-qa.md docs/release-readiness.md docs/release-notes/v1.md tests/test_v1_polish_docs.py
git commit -m "docs: reconcile cross-os proof contract"
```

Expected: commit succeeds. Do not push.

## Task 4: Replace Brittle CI Workflow Guard With Semantic Checks

**Files:**
- Modify: `tests/test_v1_polish_docs.py`
- Test: `tests/test_v1_polish_docs.py`

**Interfaces:**
- Consumes: PyYAML dependency from `pyproject.toml`.
- Produces: semantic `test_ci_workflow_collects_three_os_automated_support_gate`.

- [ ] **Step 1: Add the YAML import**

At the top of `tests/test_v1_polish_docs.py`, change:

```python
from pathlib import Path
```

to:

```python
from pathlib import Path

import yaml
```

- [ ] **Step 2: Replace the brittle CI workflow test**

Replace the whole existing `test_ci_workflow_collects_three_os_automated_support_gate` function with:

```python
def test_ci_workflow_collects_three_os_automated_support_gate() -> None:
    ci = read_doc(".github/workflows/ci.yml")
    workflow = yaml.safe_load(ci)
    test_job = workflow["jobs"]["test"]
    matrix_rows = test_job["strategy"]["matrix"]["include"]
    matrix_pairs = {
        (str(row["os"]), str(row["python-version"])) for row in matrix_rows
    }

    assert {
        ("ubuntu-latest", "3.11"),
        ("ubuntu-latest", "3.12"),
        ("macos-latest", "3.12"),
        ("windows-latest", "3.12"),
    } <= matrix_pairs

    job_env = test_job.get("env", {}) or {}
    steps = test_job["steps"]
    step_runs = "\n".join(
        str(step.get("run", "")) for step in steps if isinstance(step, dict)
    )
    forced_by_env = job_env.get("UV_PYTHON") == "${{ matrix.python-version }}"
    forced_by_run_arg = "--python ${{ matrix.python-version }}" in step_runs

    assert forced_by_env or forced_by_run_arg

    for required_text in (
        "ubuntu-latest",
        "macos-latest",
        "windows-latest",
        "uv python install ${{ matrix.python-version }}",
        "uv sync --all-extras --frozen",
        "pwd -P",
        "git status --short --branch",
        "git log -1 --oneline",
        "git remote -v",
        "git tag --points-at HEAD",
        "uv --version",
        "uv run python --version",
        "uv run --all-extras csvql --version",
        "fetch-depth: 0",
        "uv run ruff format --check .",
        "uv run ruff check .",
        "uv run --all-extras mypy src",
        "uv run --all-extras pytest",
        "shell: bash",
    ):
        assert required_text in ci
```

- [ ] **Step 3: Run the rewritten CI guard to verify it fails**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_ci_workflow_collects_three_os_automated_support_gate -q
```

Expected: FAIL on `assert forced_by_env or forced_by_run_arg` because the workflow has no `UV_PYTHON` job env and no explicit `--python ${{ matrix.python-version }}` arguments yet.

## Task 5: Force The CI Matrix Python For `uv`

**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_v1_polish_docs.py`

**Interfaces:**
- Consumes: semantic CI guard from Task 4.
- Produces: GitHub Actions workflow where `uv sync` and `uv run` use the matrix Python version.

- [ ] **Step 1: Add job-level `UV_PYTHON`**

In `.github/workflows/ci.yml`, under `runs-on: ${{ matrix.os }}` for `jobs.test`, add:

```yaml
    env:
      UV_PYTHON: ${{ matrix.python-version }}
```

The top of the job should read:

```yaml
  test:
    runs-on: ${{ matrix.os }}
    env:
      UV_PYTHON: ${{ matrix.python-version }}
    defaults:
      run:
        shell: bash
```

Keep this existing step unchanged:

```yaml
      - name: Set up Python
        run: uv python install ${{ matrix.python-version }}
```

Keep these baseline proof commands unchanged:

```yaml
          uv run python --version
          uv run --all-extras csvql --version
```

- [ ] **Step 2: Run the focused CI guard**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_ci_workflow_collects_three_os_automated_support_gate -q
```

Expected: PASS.

- [ ] **Step 3: Run the focused docs guard and CI guard together**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_cross_os_proof_docs_record_prior_proof_without_current_head_claim tests/test_v1_polish_docs.py::test_ci_workflow_collects_three_os_automated_support_gate -q
```

Expected: PASS.

- [ ] **Step 4: Commit the CI interpreter fix**

Run:

```bash
git add .github/workflows/ci.yml tests/test_v1_polish_docs.py
git commit -m "ci: force uv matrix python"
```

Expected: commit succeeds. Do not push.

## Task 6: Local Verification Before Remote Proof

**Files:**
- Verify: `.github/workflows/ci.yml`
- Verify: `docs/tui-qol-qa.md`
- Verify: `docs/release-readiness.md`
- Verify: `docs/release-notes/v1.md`
- Verify: `tests/test_v1_polish_docs.py`

**Interfaces:**
- Consumes: commits from Tasks 3 and 5.
- Produces: local evidence that tracked changes are clean before hosted CI.

- [ ] **Step 1: Inspect the tracked diff**

Run:

```bash
git status --short --branch
git diff --check HEAD~2..HEAD
git show --stat --oneline --decorate --no-renames HEAD~1..HEAD
```

Expected:

- Only the planned docs, test, and workflow files changed.
- `git diff --check HEAD~2..HEAD` prints no whitespace errors.

- [ ] **Step 2: Run dependency sync proof**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv sync --all-extras --frozen
```

Expected: exit 0.

- [ ] **Step 3: Run focused proof guard tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py -q
```

Expected: PASS.

- [ ] **Step 4: Run format, lint, type, and full tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff format --check .
UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check .
UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras mypy src
UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest
```

Expected: all commands exit 0.

- [ ] **Step 5: Stop before remote actions**

Run:

```bash
git status --short --branch
git log -1 --oneline
```

Expected:

- Branch is `main`.
- Tracked tree is clean.
- HEAD is the implementation commit that must be proven by hosted CI.
- Stop and ask the user to approve pushing `main` to `origin` and collecting private GitHub Actions logs for this exact HEAD.

## Task 7: Separately Approved Hosted CI Proof Collection

**Files:**
- Create ignored output: `output/tui-qol-qa/$(date +%Y%m%d)-$(git rev-parse --short HEAD)-cross-os-automated/RESULT.md`
- Create ignored output: `output/tui-qol-qa/$(date +%Y%m%d)-$(git rev-parse --short HEAD)-cross-os-automated/commands/github-run-${run_id}.json`
- Create ignored output: `output/tui-qol-qa/$(date +%Y%m%d)-$(git rev-parse --short HEAD)-cross-os-automated/commands/github-run-${run_id}.log`

**Interfaces:**
- Consumes: explicit user approval for remote actions, clean tracked implementation HEAD, `gh` authenticated as `highlordleonas`.
- Produces: ignored proof packet and final response data for fresh same-HEAD automated proof.

- [ ] **Step 1: Confirm remote-action approval and GitHub identity**

Do not run this task until the user explicitly approves pushing and collecting hosted CI evidence.

After approval, run:

```bash
source ~/.zshrc
gh-personal
gh auth status
git config user.name
git config user.email
```

Expected:

- `gh auth status` shows active authentication for `highlordleonas`.
- `git config user.name` prints `highlordleonas`.
- `git config user.email` prints `richarddemke@gmail.com`.

- [ ] **Step 2: Push the implementation HEAD**

Run:

```bash
git status --short --branch
git log -1 --oneline
git push origin main
```

Expected:

- `git status --short --branch` shows a clean tracked tree.
- Push succeeds.
- Do not tag, publish, create a GitHub release, upload release artifacts, or change version.

- [ ] **Step 3: Locate and watch the GitHub Actions run for the pushed HEAD**

Run:

```bash
commit_sha="$(git rev-parse HEAD)"
run_id="$(gh run list --repo highlordleonas/csvql --branch main --commit "$commit_sha" --workflow ci --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$run_id" --repo highlordleonas/csvql --exit-status
```

Expected:

- `run_id` is non-empty.
- `gh run watch` exits 0.

If `gh run watch` exits nonzero, collect the logs in Step 4, mark the proof packet blocked, and use `superpowers:systematic-debugging` before editing again.

- [ ] **Step 4: Save run metadata and logs into ignored output**

Run:

```bash
proof_dir="output/tui-qol-qa/$(date +%Y%m%d)-$(git rev-parse --short HEAD)-cross-os-automated"
mkdir -p "$proof_dir/commands"
gh run view "$run_id" --repo highlordleonas/csvql --json databaseId,headSha,status,conclusion,url,jobs > "$proof_dir/commands/github-run-${run_id}.json"
gh run view "$run_id" --repo highlordleonas/csvql --log > "$proof_dir/commands/github-run-${run_id}.log"
```

Expected:

- Both files exist under the ignored proof directory.
- `headSha` in the JSON equals `git rev-parse HEAD`.

- [ ] **Step 5: Verify the Ubuntu 3.11 proof line**

Run:

```bash
rg -n "ubuntu-latest|3.11|uv run python --version|Python 3.11" "$proof_dir/commands/github-run-${run_id}.log"
```

Expected:

- The log contains the Ubuntu 3.11 job context.
- The log contains `uv run python --version`.
- The same Ubuntu 3.11 job contains `Python 3.11`.

- [ ] **Step 6: Write the ignored `RESULT.md` proof packet**

Run:

```bash
{
  printf '# Cross-OS Automated Proof Result\n\n'
  printf 'Status: pass\n\n'
  printf '- Scope: automated support proof for macOS, Ubuntu/Linux, and native Windows GitHub-hosted runners.\n'
  printf '- Commit SHA: `%s`\n' "$(git rev-parse HEAD)"
  printf '- GitHub Actions run id: `%s`\n' "$run_id"
  printf '- GitHub Actions run URL: `https://github.com/highlordleonas/csvql/actions/runs/%s`\n' "$run_id"
  printf '- Historical prior proof: `d8ec3df` / run `28965686605` remains context only for this implementation commit.\n'
  printf '- Superseded packet: blocked `b118a2c` remains superseded by later passing automated proof.\n'
  printf '- Fresh proof recording model: tracked docs define the requirement; this ignored packet and the final execution response record the current run id and SHA.\n'
  printf '- Python 3.11 integrity check: Ubuntu 3.11 job log includes `uv run python --version` and `Python 3.11`.\n'
  printf '- Boundaries: no tag, publish, GitHub release, version change, release artifact upload, or `v1-stable` claim was made.\n\n'
  printf '## Evidence Files\n\n'
  printf '- `%s/commands/github-run-%s.json`\n' "$proof_dir" "$run_id"
  printf '- `%s/commands/github-run-%s.log`\n' "$proof_dir" "$run_id"
} > "$proof_dir/RESULT.md"
```

Expected:

- `$proof_dir/RESULT.md` exists.
- `git status --short --branch` does not show `output/` because it is ignored.

- [ ] **Step 7: Final proof-state response**

Run:

```bash
git status --short --branch
git log -1 --oneline
git tag --points-at HEAD
```

Expected:

- Tracked tree is clean.
- HEAD matches the implementation commit proven by the GitHub Actions run.
- No tag points at HEAD unless the user separately approved a release tag.

Final response must include:

- implementation commit SHA
- GitHub Actions run id
- proof packet path under `output/tui-qol-qa/`
- Ubuntu 3.11 log result
- explicit statement that `d8ec3df` / run `28965686605` is historical prior proof only
- explicit statement that no tag, publish, GitHub release, release artifact upload, version change, or `v1-stable` claim was made

## Self-Review Checklist

- Spec coverage: Tasks 2 and 3 cover historical proof wording, blocked `b118a2c`, prior `d8ec3df` / run `28965686605`, ignored proof packet reporting, and no self-referential tracked-doc run id. Tasks 4 and 5 cover semantic CI checks and `UV_PYTHON`. Tasks 6 and 7 cover local verification, remote approval, hosted proof, and final reporting.
- Placeholder scan: The plan uses shell variables for runtime values and contains no deferred implementation steps or unspecified error handling.
- Type consistency: New tests use existing `read_doc` and `normalized_markdown_text` helpers and PyYAML's `safe_load`; the workflow key checked by tests is `jobs.test.env.UV_PYTHON`.
- Scope check: No runtime source, package metadata, version file, release tag, publish flow, GitHub release, or artifact upload is part of this plan.
