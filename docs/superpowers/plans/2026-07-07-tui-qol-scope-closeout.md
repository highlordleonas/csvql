# TUI QoL Scope Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the abandoned VS Code fallback lane by documenting the current TUI QoL evidence honestly and adding docs guards that prevent future terminal or release-status overclaims.

**Architecture:** Keep runtime behavior unchanged and use docs as the authority surface for this closeout. Add focused text guards in `tests/test_v1_polish_docs.py`, then update the TUI QoL and release-readiness docs so macOS Terminal evidence, VS Code limitations, terminal gaps, and release eligibility stay separate.

**Tech Stack:** Markdown docs, pytest docs guards, project-local `uv`.

## Global Constraints

- LocalQL is the installable distribution name.
- Runtime/user-facing surfaces stay `csvql` CLI, `csvql` import package, `.csvql.yml`, and `csvql menu`.
- Use repo-local `uv`; do not install global dependencies.
- Use `UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql` for `uv` commands in this environment.
- Do not claim sandbox safety, safe untrusted SQL, security isolation, production readiness, release-candidate eligibility, `v1-stable`, or broad large-file proof.
- Do not tag, publish to PyPI, create a GitHub release, upload artifacts, push, configure remotes, change versions, or create release artifacts.
- Do not add a web app, cloud connectors, NLP execution, dataframe-first API, plugin system, hidden cache/materialization, or broader platform scope.
- Do not change runtime behavior, keybindings, help text, footer labels, SQL execution semantics, DuckDB behavior, package metadata, schemas, migrations, validation SQL, or database contracts.
- Do not run manual screenshot evidence, launch GUI terminal proof, or inspect ignored `output/` artifacts for this closeout implementation.
- Treat VS Code integrated-terminal compatibility as out of scope unless a new design review explicitly reopens it.
- Before editing user-facing docs during execution, use the `documentation` skill if available.
- Before editing `tests/**/*.py` during execution, use the `python-codebase-standards` skill if available.
- Before claiming completion during execution, use `superpowers:verification-before-completion` or `verification-before-completion`.

---

## Scope Check

This is one docs-and-guard-test slice. It does not need separate subsystem plans because every change supports the same deliverable: honest TUI QoL closeout status without runtime changes.

## File Structure

- Modify `tests/test_v1_polish_docs.py`
  - Add text-guard tests for the closeout status, release-status separation, rejected VS Code fallback promises, and the closed VS Code fallback spec/plan.
  - Keep tests deterministic; do not launch Textual or inspect `output/`.
- Modify `docs/tui-qol-qa.md`
  - Add a `Current Closeout Status` section near the top.
  - Reword the required terminal matrix as the future/full release-eligibility gate, not something the current closeout has already satisfied.
- Modify `docs/v1-manual-qa.md`
  - Clarify that the current TUI QoL scope closeout records macOS Terminal evidence and remaining gaps only.
- Modify `docs/release-readiness.md`
  - Clarify that macOS-only closeout evidence does not satisfy release-candidate eligibility.
- Modify `docs/release-notes/v1.md`
  - Mirror the release-readiness clarification in the candidate proof checklist.
- Do not modify `src/csvql/tui_app.py`, `src/csvql/tui_help.py`, `README.md`, `docs/getting-started.md`, `docs/tui-guide.md`, `docs/troubleshooting.md`, package metadata, or the closed VS Code spec/plan unless a guard test reveals an existing claim that must be corrected.

---

### Task 1: Add Docs Guards For TUI QoL Scope Boundaries

**Files:**
- Modify: `tests/test_v1_polish_docs.py`

**Interfaces:**
- Consumes: Existing `read_doc(path: str) -> str` and `normalized_markdown_text(text: str) -> str` helpers.
- Produces: Four pytest docs guards that later doc edits must satisfy.

- [ ] **Step 1: Insert the closeout status guard**

In `tests/test_v1_polish_docs.py`, add this test immediately after `test_tui_qol_qa_gate_is_blocking_and_records_terminal_evidence`:

```python
def test_tui_qol_docs_record_scope_closeout_without_release_eligibility() -> None:
    matrix = read_doc("docs/tui-qol-qa.md")
    normalized_matrix = normalized_markdown_text(matrix)

    assert "## Current Closeout Status" in matrix
    assert "macOS Terminal is the verified local pass row for this lane." in matrix
    assert "output/tui-qol-qa/20260706-c604a46/macos-terminal/" in matrix
    assert "VS Code integrated terminal is out of scope for this closeout." in matrix
    assert "recorded a keybinding failure" in matrix
    assert "iTerm2 is blocked locally because the app was unavailable." in matrix
    assert "Linux terminal and Windows Terminal were not run locally." in matrix
    assert "tmux/SSH is blocked locally because `tmux` was unavailable." in matrix
    assert (
        "This closeout does not make the project `release-candidate eligible`."
        in matrix
    )
    assert (
        "A future complete TUI QoL run used for release-candidate eligibility must cover:"
        in normalized_matrix
    )
```

- [ ] **Step 2: Insert the release-status separation guard**

Add this test immediately after the closeout status guard:

```python
def test_release_docs_keep_tui_qol_closeout_out_of_candidate_eligibility() -> None:
    manual_qa = read_doc("docs/v1-manual-qa.md")
    readiness = read_doc("docs/release-readiness.md")
    release_notes = read_doc("docs/release-notes/v1.md")

    assert (
        "The current TUI QoL scope closeout records macOS Terminal evidence and "
        "terminal gaps only; it does not satisfy the full TUI QoL terminal matrix."
        in manual_qa
    )

    required_release_wording = (
        "A local TUI QoL scope closeout that records only macOS Terminal evidence "
        "and terminal gaps is not enough for `release-candidate eligible`; the "
        "full required terminal matrix must pass with media evidence."
    )
    assert required_release_wording in readiness
    assert required_release_wording in release_notes
```

- [ ] **Step 3: Insert the rejected VS Code fallback guard**

Add this test after the release-status separation guard:

```python
def test_public_docs_do_not_advertise_rejected_vscode_alt_fallbacks() -> None:
    public_docs = "\n".join(
        [
            read_doc("README.md"),
            read_doc("docs/getting-started.md"),
            read_doc("docs/tui-guide.md"),
            read_doc("docs/troubleshooting.md"),
            read_doc("docs/tui-qol-qa.md"),
            read_doc("docs/v1-manual-qa.md"),
            read_doc("docs/release-readiness.md"),
            read_doc("docs/release-notes/v1.md"),
        ]
    )

    for rejected_claim in (
        "`Alt+H`",
        "`Alt+R`",
        "`Alt+U`",
        "VS Code-friendly",
        "VS Code fallback",
    ):
        assert rejected_claim not in public_docs
```

- [ ] **Step 4: Insert the closed historical lane guard**

Add this test after the rejected VS Code fallback guard:

```python
def test_closed_vscode_fallback_spec_and_plan_remain_non_executable() -> None:
    spec = read_doc(
        "docs/superpowers/specs/2026-07-07-vscode-alt-keybinding-fallback-design.md"
    )
    plan = read_doc(
        "docs/superpowers/plans/2026-07-07-vscode-alt-keybinding-fallback.md"
    )

    assert (
        "Superseded after failed pre-churn reachability evidence and user rescope."
        in spec
    )
    assert (
        "The lane is now closed. Do not implement this VS Code-specific fallback design"
        in spec
    )
    assert "**Closed plan:** Do not execute this plan." in plan
    assert "VS Code integrated-terminal compatibility is now out of scope." in plan
```

- [ ] **Step 5: Run the focused guards and confirm the intended failures**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_tui_qol_docs_record_scope_closeout_without_release_eligibility tests/test_v1_polish_docs.py::test_release_docs_keep_tui_qol_closeout_out_of_candidate_eligibility tests/test_v1_polish_docs.py::test_public_docs_do_not_advertise_rejected_vscode_alt_fallbacks tests/test_v1_polish_docs.py::test_closed_vscode_fallback_spec_and_plan_remain_non_executable -q
```

Expected:

- `test_tui_qol_docs_record_scope_closeout_without_release_eligibility` fails because `docs/tui-qol-qa.md` has no `Current Closeout Status` section yet.
- `test_release_docs_keep_tui_qol_closeout_out_of_candidate_eligibility` fails because release docs do not yet include the new closeout wording.
- The rejected fallback guard passes.
- The closed historical lane guard passes.

Do not commit failing tests by themselves. Continue to Task 2 in the same working tree.

---

### Task 2: Update TUI QoL And Release Docs To Match The Guards

**Files:**
- Modify: `docs/tui-qol-qa.md`
- Modify: `docs/v1-manual-qa.md`
- Modify: `docs/release-readiness.md`
- Modify: `docs/release-notes/v1.md`
- Test: `tests/test_v1_polish_docs.py`

**Interfaces:**
- Consumes: Guard tests from Task 1.
- Produces: Public docs that keep local TUI QoL closeout, full terminal matrix evidence, and release eligibility separate.

- [ ] **Step 1: Add the closeout section to `docs/tui-qol-qa.md`**

Insert this section after the opening status paragraph and before `## Scope`:

```markdown
## Current Closeout Status

The current local TUI QoL closeout is macOS Terminal-focused evidence, not a
full cross-terminal release gate pass.

- macOS Terminal is the verified local pass row for this lane. Local proof
  artifacts live under `output/tui-qol-qa/20260706-c604a46/macos-terminal/`.
- VS Code integrated terminal is out of scope for this closeout. The 2026-07-07
  spike recorded a keybinding failure where default macOS Option-key handling
  inserted text instead of opening TUI Help.
- iTerm2 is blocked locally because the app was unavailable.
- Linux terminal and Windows Terminal were not run locally.
- tmux/SSH is blocked locally because `tmux` was unavailable.

This closeout does not make the project `release-candidate eligible`.
```

- [ ] **Step 2: Reword the required terminal matrix introduction**

In `docs/tui-qol-qa.md`, replace:

```markdown
Every complete TUI QoL run must cover:
```

with:

```markdown
A future complete TUI QoL run used for release-candidate eligibility must cover:
```

Keep the existing terminal table and evidence rules.

- [ ] **Step 3: Add the manual QA clarification**

In `docs/v1-manual-qa.md`, after:

```markdown
The TUI QoL QA gate is blocking for `release-candidate eligible`.
```

add:

```markdown
The current TUI QoL scope closeout records macOS Terminal evidence and terminal
gaps only; it does not satisfy the full TUI QoL terminal matrix.
```

- [ ] **Step 4: Add the release-readiness clarification**

In `docs/release-readiness.md`, after the paragraph ending with:

```markdown
state-clarity checks. Any failed TUI QoL matrix item blocks `release-candidate eligible`.
```

add:

```markdown
A local TUI QoL scope closeout that records only macOS Terminal evidence and
terminal gaps is not enough for `release-candidate eligible`; the full required
terminal matrix must pass with media evidence.
```

- [ ] **Step 5: Add the release-notes clarification**

In `docs/release-notes/v1.md`, after the paragraph ending with:

```markdown
matrix item blocks `release-candidate eligible`. Any untested or missing-media
TUI QoL item also blocks `release-candidate eligible`.
```

add:

```markdown
A local TUI QoL scope closeout that records only macOS Terminal evidence and
terminal gaps is not enough for `release-candidate eligible`; the full required
terminal matrix must pass with media evidence.
```

- [ ] **Step 6: Run the focused guards and confirm they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_tui_qol_docs_record_scope_closeout_without_release_eligibility tests/test_v1_polish_docs.py::test_release_docs_keep_tui_qol_closeout_out_of_candidate_eligibility tests/test_v1_polish_docs.py::test_public_docs_do_not_advertise_rejected_vscode_alt_fallbacks tests/test_v1_polish_docs.py::test_closed_vscode_fallback_spec_and_plan_remain_non_executable -q
```

Expected: all four selected tests pass.

- [ ] **Step 7: Commit the docs and guards**

Run:

```bash
git add docs/tui-qol-qa.md docs/v1-manual-qa.md docs/release-readiness.md docs/release-notes/v1.md tests/test_v1_polish_docs.py
git commit -m "docs: close TUI QoL terminal scope honestly"
```

Expected: commit succeeds and includes only those five files.

---

### Task 3: Verify The Full Docs Guard Surface

**Files:**
- Verify: `tests/test_v1_polish_docs.py`
- Verify: `README.md`
- Verify: `docs/getting-started.md`
- Verify: `docs/tui-guide.md`
- Verify: `docs/troubleshooting.md`
- Verify: `docs/tui-qol-qa.md`
- Verify: `docs/v1-manual-qa.md`
- Verify: `docs/release-readiness.md`
- Verify: `docs/release-notes/v1.md`

**Interfaces:**
- Consumes: Task 2 commit.
- Produces: Final proof that the docs guard file passes and public docs do not advertise the rejected Alt fallback lane.

- [ ] **Step 1: Run the full focused docs test file**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py -q
```

Expected: every test in `tests/test_v1_polish_docs.py` passes.

- [ ] **Step 2: Run the rejected public fallback phrase scan**

Run:

```bash
rg -n "Alt\\+H|Alt\\+R|Alt\\+U|VS Code-friendly|VS Code fallback" README.md docs/getting-started.md docs/tui-guide.md docs/troubleshooting.md docs/tui-qol-qa.md docs/v1-manual-qa.md docs/release-readiness.md docs/release-notes/v1.md
```

Expected: no output. `rg` exits `1` when there are no matches; that exit code is the expected result for this guard scan.

- [ ] **Step 3: Run the whitespace check**

Run:

```bash
git diff --check HEAD~1..HEAD
```

Expected: no output.

- [ ] **Step 4: Inspect the committed file list**

Run:

```bash
git show --stat --oneline --name-only HEAD
```

Expected: the latest implementation commit lists only:

```text
docs/release-notes/v1.md
docs/release-readiness.md
docs/tui-qol-qa.md
docs/v1-manual-qa.md
tests/test_v1_polish_docs.py
```

- [ ] **Step 5: Confirm the working tree**

Run:

```bash
git status --short --branch
```

Expected: clean tracked working tree on `codex/tui-polish-qa`.

If Task 3 requires a correction, make the smallest docs or test edit, rerun the failing check plus `tests/test_v1_polish_docs.py -q`, then commit the correction with:

```bash
git add docs/tui-qol-qa.md docs/v1-manual-qa.md docs/release-readiness.md docs/release-notes/v1.md tests/test_v1_polish_docs.py
git commit -m "test: guard TUI QoL scope closeout claims"
```

Expected for the correction commit: it includes only files needed by the failed verification.
