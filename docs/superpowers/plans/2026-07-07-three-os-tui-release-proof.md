# Three-OS TUI Release Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align LocalQL release-proof authority docs, guard tests, and automated support gates with the approved macOS, Windows, and Linux TUI proof design.

**Architecture:** Keep runtime behavior unchanged. Treat tracked docs and guard tests as the authority implementation, and use CI workflow expansion only to collect automated support proof across target OS families. Manual terminal proof remains a separate proof-execution phase that writes ignored evidence under `output/`.

**Tech Stack:** Markdown docs, pytest docs guards, GitHub Actions, `uv`, Ruff, mypy, pytest, Textual TUI manual evidence.

## Global Constraints

- LocalQL is the installable distribution name.
- Runtime contract remains: CLI command `csvql`, Python import package `csvql`, config `.csvql.yml`, TUI command `csvql menu`.
- Local-first Python CLI/package for querying local CSV files through DuckDB.
- Use `uv`; do not install global dependencies.
- Treat user-authored SQL as trusted local DuckDB SQL.
- Do not claim sandbox safety, safe untrusted SQL, security isolation, production readiness, or broad large-file proof.
- Do not add a web app, cloud connectors, NLP execution, dataframe-first API, plugin system, hidden cache/materialization, or broader platform scope.
- Do not tag, publish to PyPI, create GitHub release, upload release artifacts, change version, push, configure remote, or claim `v1-stable`.
- Required release-proof terminal rows are macOS Terminal, Windows Terminal, and one normal Linux desktop terminal.
- VS Code integrated terminal, iTerm2, and tmux/SSH are out of scope for this release lane.
- Windows Terminal proof must use a native Windows environment and native Windows Python/`uv` setup; WSL counts as Linux/WSL evidence, not Windows evidence.
- Linux proof must use a real desktop terminal emulator, not an IDE terminal, CI pseudo-terminal, browser shell, SSH-only session, or terminal multiplexer.
- Three-OS automated support proof requires macOS, native Windows, and Linux runs on Python 3.12 with `uv sync --all-extras --frozen`, Ruff format check, Ruff lint, mypy over `src`, full pytest, baseline truth, `uv --version`, `uv run python --version`, and `uv run --all-extras csvql --version`.
- Release-readiness proof, package-content audit, benchmark proof, and unsupported-claim scans remain same-`HEAD` release-readiness evidence; they do not need to run on all three OS families for this lane unless a later approved plan broadens them.
- A local `pass` result from this lane is evidence only. Changing any release label, release status, public status, tag, or published artifact requires separate explicit approval.
- Before editing user-facing docs, use `documentation`.
- Before editing `tests/**/*.py`, `.github/workflows/**`, package metadata, typing, CLI/TUI behavior, or dependency surfaces, use `python-codebase-standards`.
- If terminal evidence, CI evidence, or TUI timing contradicts assumptions, stop and use `superpowers:systematic-debugging`.
- Before claiming implementation or proof-execution completion, use `superpowers:verification-before-completion` or `verification-before-completion`.

---

## File Structure

- Modify `tests/test_v1_polish_docs.py`: add docs/workflow guards for approved three-OS scope, automated support proof, source-checkout version commands, and out-of-scope terminal rows.
- Modify `docs/tui-qol-qa.md`: make it the primary TUI proof authority for the three required terminal rows, automated support proof metadata, source access, baseline transcripts, observer evidence, and result packet shape.
- Modify `docs/v1-manual-qa.md`: keep manual v1 QA linked to the new three-OS TUI gate without duplicating the full TUI matrix.
- Modify `docs/release-readiness.md`: align release-readiness workflow and label rules with three-OS TUI terminal proof plus same-`HEAD` automated support proof.
- Modify `docs/release-notes/v1.md`: align candidate proof checklist and final decision template with the approved three-OS scope.
- Modify `.github/workflows/ci.yml`: add macOS and Windows Python 3.12 automated support jobs while preserving existing Ubuntu Python 3.11 and Python 3.12 coverage.
- Use ignored `output/tui-qol-qa/<run-id>/` only during proof execution after separate proof-run approval.

## Task 1: Guard And Update The TUI QoL Authority Doc

**Files:**
- Modify: `tests/test_v1_polish_docs.py`
- Modify: `docs/tui-qol-qa.md`

**Interfaces:**
- Consumes: `read_doc(path: str) -> str` and `normalized_markdown_text(text: str) -> str` from `tests/test_v1_polish_docs.py`.
- Produces: A tracked TUI QoL authority doc that later tasks can cite for required terminal rows, automated support proof, baseline transcripts, observer evidence, and result packet structure.

- [ ] **Step 1: Activate required skills**

Use `documentation` before editing `docs/tui-qol-qa.md`.

Use `python-codebase-standards` before editing `tests/test_v1_polish_docs.py`.

- [ ] **Step 2: Add the failing TUI QoL scope guard**

Append this test after `test_tui_qol_docs_record_scope_closeout_without_release_eligibility` in `tests/test_v1_polish_docs.py`:

```python
def test_tui_qol_gate_uses_approved_three_os_release_scope() -> None:
    matrix = read_doc("docs/tui-qol-qa.md")
    normalized_matrix = normalized_markdown_text(matrix)

    assert "## Approved Three-OS Release-Proof Scope" in matrix
    assert (
        "macOS Terminal, Windows Terminal, and one normal Linux desktop terminal"
        in normalized_matrix
    )
    assert "## Out-of-Scope Rows" in matrix
    required_scope = matrix.split("## Out-of-Scope Rows", 1)[0]
    assert "| macOS Terminal | `output/tui-qol-qa/<run-id>/macos-terminal/` |" in required_scope
    assert (
        "| Windows Terminal | `output/tui-qol-qa/<run-id>/windows-terminal/` |"
        in required_scope
    )
    assert (
        "| GNOME Terminal or equivalent normal Linux desktop terminal | "
        "`output/tui-qol-qa/<run-id>/linux-terminal/` |"
    ) in required_scope
    for old_required_row in (
        "| iTerm2 |",
        "| VS Code terminal |",
        "| tmux/SSH |",
    ):
        assert old_required_row not in required_scope
    for out_of_scope in (
        "VS Code integrated terminal",
        "iTerm2",
        "tmux/SSH",
    ):
        assert out_of_scope in matrix
    assert "native Windows environment and native Windows Python/`uv` setup" in matrix
    assert "A Windows Terminal tab running WSL counts as Linux/WSL evidence" in matrix
    assert "real desktop terminal emulator" in matrix
    assert "default terminal settings" in matrix
```

- [ ] **Step 3: Add the failing automated proof and transcript guard**

Append this test after the test from Step 2:

```python
def test_tui_qol_gate_defines_automated_support_and_result_packet() -> None:
    matrix = read_doc("docs/tui-qol-qa.md")

    for required_text in (
        "## Required Automated Support Proof",
        "one run on macOS, one run on native Windows, and one run on Linux",
        "Python 3.12 on each OS",
        "uv sync --all-extras --frozen",
        "uv run ruff format --check .",
        "uv run ruff check .",
        "uv run --all-extras mypy src",
        "uv run --all-extras pytest",
        "uv --version",
        "uv run python --version",
        "uv run --all-extras csvql --version",
        "Plain `csvql --version` is not sufficient for source-checkout proof",
        "commands/automated-macos.*",
        "commands/automated-windows.*",
        "commands/automated-linux.*",
        "source access method",
        "commit verification command",
        "observer timestamp",
        "local or observer-provided",
        "A local `pass` result from this lane is evidence only",
    ):
        assert required_text in matrix
```

- [ ] **Step 4: Run the focused tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_v1_polish_docs.py::test_tui_qol_gate_uses_approved_three_os_release_scope \
  tests/test_v1_polish_docs.py::test_tui_qol_gate_defines_automated_support_and_result_packet \
  -q
```

Expected: FAIL because `docs/tui-qol-qa.md` still describes the older broad terminal matrix and does not yet contain the approved three-OS proof contract.

- [ ] **Step 5: Replace the stale closeout and required-terminal wording**

In `docs/tui-qol-qa.md`, replace the current `## Current Closeout Status` section through the end of the current `## Required Terminals` section with this text:

```markdown
## Approved Three-OS Release-Proof Scope

The approved release-proof target covers macOS Terminal, Windows Terminal, and
one normal Linux desktop terminal. This is a new release-proof lane, not a claim
that the project is already release-candidate eligible.

Historical local evidence remains useful context:

- macOS Terminal previously passed local TUI QoL evidence under
  `output/tui-qol-qa/20260706-c604a46/macos-terminal/`.
- VS Code integrated terminal is out of scope for this release lane after the
  2026-07-07 keybinding spike showed default macOS Option-key behavior did not
  reliably reach the TUI.
- iTerm2 and tmux/SSH are out of scope for this release lane.
- Linux terminal and Windows Terminal still require same-`HEAD` evidence before
  the final TUI proof result can pass.

This approved scope does not make the project `release-candidate eligible`.

## Scope

This gate covers the existing optional terminal TUI:

- `csvql menu`
- local CSV sources
- trusted local DuckDB SQL
- Sources, SQL editor, Results, History, Help, and prompt modals
- explicit export and explicit derived result sources
- documented keybindings and fallbacks
- terminal resize and terminal-specific key behavior

It does not add a web UI, cloud workflow, plugin system, NLP execution path, or
broader product platform scope. It does not claim sandbox safety, safe untrusted
SQL execution, production readiness, or broad large-file proof.

## Required Terminals

A complete TUI QoL run used for this release-proof lane must cover:

| Terminal path | Required evidence directory |
| --- | --- |
| macOS Terminal | `output/tui-qol-qa/<run-id>/macos-terminal/` |
| Windows Terminal | `output/tui-qol-qa/<run-id>/windows-terminal/` |
| GNOME Terminal or equivalent normal Linux desktop terminal | `output/tui-qol-qa/<run-id>/linux-terminal/` |

The Windows Terminal row must use a native Windows environment and native
Windows Python/`uv` setup. A Windows Terminal tab running WSL counts as
Linux/WSL evidence, not Windows evidence, unless a separate design review
explicitly approves a different classification before proof execution.

The Linux row must use a real desktop terminal emulator, not an IDE-integrated
terminal, CI pseudo-terminal, browser shell, SSH-only session, or terminal
multiplexer. GNOME Terminal is preferred. Konsole, Xfce Terminal, xterm, or
another normal locally displayed Linux desktop terminal is acceptable only if
the evidence names the terminal and version.

Terminal proof should use default terminal settings. A non-default setting is
allowed only when explicitly approved before the run and recorded as a
deviation in the result packet.

## Out-of-Scope Rows

These rows do not block this release-proof lane:

- VS Code integrated terminal
- iTerm2
- tmux/SSH

Out of scope does not mean unsupported forever. It means those terminal hosts
must not be used to claim pass or fail status for the macOS, Windows, and Linux
target.
```

- [ ] **Step 6: Replace the required setup section**

In `docs/tui-qol-qa.md`, replace the current `## Required Setup` section with this text:

````markdown
## Required Setup

Run from the repository root unless a step says otherwise.

Use the same candidate commit for every terminal and automated support proof
source. Each manual platform row and automated platform proof must include a
transcript path or embedded transcript that records:

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

Expected:

- working tree state is recorded before the run
- commit SHA is recorded in the result summary
- version prints `1.0.0`
- empty `git remote -v` or `git tag --points-at HEAD` output is recorded
  explicitly rather than omitted

Plain `csvql --version` is not sufficient for source-checkout proof because the
console script may not be on `PATH`. It is allowed only for installed-wheel
proof, and the result packet must record the wheel source, install command, and
why installed-wheel proof was used.
````

- [ ] **Step 7: Add the automated support proof section**

Insert this section after `## Required Setup`:

```markdown
## Required Automated Support Proof

The final proof result cannot be `pass` without same-`HEAD` automated support
proof for macOS, native Windows, and Linux.

Minimum automated support proof:

- one run on macOS, one run on native Windows, and one run on Linux
- Python 3.12 on each OS
- dependency setup through `uv sync --all-extras --frozen`
- exact dependency install command, output path, and exit status recorded
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run --all-extras mypy src`
- `uv run --all-extras pytest`
- baseline truth transcript, including `uv --version`,
  `uv run python --version`, and `uv run --all-extras csvql --version`

Any dependency install command other than `uv sync --all-extras --frozen` is a
deviation. The result packet must record the exact command, reason, environment
constraint, and why the output is still comparable.

Release-readiness proof, package-content audit, benchmark proof, and
unsupported-claim scans remain required same-`HEAD` release-readiness evidence,
but they do not need to run on all three OS families for this lane unless a
later approved plan explicitly broadens them.

Automated support proof outputs should use a clearly mapped naming convention:

- `commands/automated-macos.*`
- `commands/automated-windows.*`
- `commands/automated-linux.*`

An equivalent naming scheme is acceptable only if `RESULT.md` maps each file to
the OS family, runner, command set, and proof status.
```

- [ ] **Step 8: Replace the evidence rules section**

Replace `## Evidence Rules` in `docs/tui-qol-qa.md` with this text:

````markdown
## Evidence Rules

Each terminal run must record:

- date
- candidate commit SHA
- tester or outside observer
- evidence source: local or observer-provided
- source access method
- commit verification command
- OS name and version
- terminal name and version
- shell name and version
- whether terminal settings are default or non-default
- relevant locale or encoding settings if they affect rendering or keyboard
  behavior
- Python and `uv` setup path
- viewport size range tested
- pass/fail for each flow
- blocker notes
- media artifact paths
- deviations, skipped steps, and failures

Outside-observer evidence must also include the observer label, observer
timestamp and timezone, setup transcript, source or evidence transfer method,
and per-flow notes for every TUI QoL matrix item.

Local media evidence is required for every terminal run, not only failures.
Screenshots or recordings live under ignored proof paths:

```text
output/tui-qol-qa/<run-id>/<terminal-id>/
```

The media files are local proof artifacts. Do not commit them.
````

- [ ] **Step 9: Replace the result summary template**

Replace `## Result Summary Template` in `docs/tui-qol-qa.md` with this text:

````markdown
## Result Summary Template

```markdown
# TUI QoL QA Result

- Run id:
- Candidate commit SHA:
- Final status: pass | fail | blocked
- Local proof result only; release label changes require separate explicit approval:
- No tag, publish, release artifact upload, version change, remote configuration, or release action occurred:

## Baseline Truth

| Evidence item | Source access method | Commit verification command | Transcript path | Status |
| --- | --- | --- | --- | --- |
| macOS Terminal |  |  |  |  |
| Windows Terminal |  |  |  |  |
| Linux terminal |  |  |  |  |
| Automated macOS |  |  | commands/automated-macos.* |  |
| Automated Windows |  |  | commands/automated-windows.* |  |
| Automated Linux |  |  | commands/automated-linux.* |  |

## Automated Support Proof

| OS | Runner | Python | uv | Install command | Command set | Output path | Status | Deviations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| macOS |  |  |  | `uv sync --all-extras --frozen` | Ruff format, Ruff check, mypy, pytest | commands/automated-macos.* |  |  |
| Windows |  |  |  | `uv sync --all-extras --frozen` | Ruff format, Ruff check, mypy, pytest | commands/automated-windows.* |  |  |
| Linux |  |  |  | `uv sync --all-extras --frozen` | Ruff format, Ruff check, mypy, pytest | commands/automated-linux.* |  |  |

## Manual Terminal Rows

| Terminal | OS | Shell | Settings | Viewports | Evidence source | Media path | Status | Blockers |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| macOS Terminal |  |  | default |  | local | output/tui-qol-qa/<run-id>/macos-terminal/ |  |  |
| Windows Terminal |  |  | default |  | local or observer-provided | output/tui-qol-qa/<run-id>/windows-terminal/ |  |  |
| Linux terminal |  |  | default |  | local or observer-provided | output/tui-qol-qa/<run-id>/linux-terminal/ |  |  |

## Flow Matrix

| Flow | macOS Terminal | Windows Terminal | Linux terminal | Notes |
| --- | --- | --- | --- | --- |
| QOL-01 |  |  |  |  |
| QOL-02 |  |  |  |  |
| QOL-03 |  |  |  |  |
| QOL-04 |  |  |  |  |
| QOL-05 |  |  |  |  |
| QOL-06 |  |  |  |  |
| QOL-07 |  |  |  |  |
| QOL-08 |  |  |  |  |
| QOL-09 |  |  |  |  |
| QOL-10 |  |  |  |  |
| QOL-11 |  |  |  |  |
| QOL-12 |  |  |  |  |
| QOL-13 |  |  |  |  |
| QOL-14 |  |  |  |  |
| QOL-15 |  |  |  |  |
| QOL-16 |  |  |  |  |
| QOL-17 |  |  |  |  |
| QOL-18 |  |  |  |  |
| QOL-19 |  |  |  |  |
| QOL-20 |  |  |  |  |
| QOL-21 |  |  |  |  |

## Out-of-Scope Rows

VS Code integrated terminal, iTerm2, and tmux/SSH were out of scope for this release-proof lane.
```
````

- [ ] **Step 10: Run the focused tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_v1_polish_docs.py::test_tui_qol_gate_uses_approved_three_os_release_scope \
  tests/test_v1_polish_docs.py::test_tui_qol_gate_defines_automated_support_and_result_packet \
  -q
```

Expected: PASS.

- [ ] **Step 11: Commit Task 1**

Run:

```bash
git add docs/tui-qol-qa.md tests/test_v1_polish_docs.py
git commit -m "docs: define three-os TUI proof gate"
```

Expected: commit succeeds.

## Task 2: Align Release Authority Docs With The Three-OS Gate

**Files:**
- Modify: `tests/test_v1_polish_docs.py`
- Modify: `docs/v1-manual-qa.md`
- Modify: `docs/release-readiness.md`
- Modify: `docs/release-notes/v1.md`

**Interfaces:**
- Consumes: The three-OS TUI gate wording from Task 1.
- Produces: Release docs that no longer require the older six-row TUI matrix and that keep local proof results separate from release label changes.

- [ ] **Step 1: Activate required skills**

Use `documentation` before editing the release docs.

Use `python-codebase-standards` before editing `tests/test_v1_polish_docs.py`.

- [ ] **Step 2: Add the failing release authority guard**

Append this test after `test_release_docs_keep_tui_qol_closeout_out_of_candidate_eligibility`:

```python
def test_release_docs_require_approved_three_os_tui_proof_gate() -> None:
    manual_qa = read_doc("docs/v1-manual-qa.md")
    readiness = read_doc("docs/release-readiness.md")
    release_notes = read_doc("docs/release-notes/v1.md")
    combined = "\n".join([manual_qa, readiness, release_notes])

    assert "macOS Terminal, Windows Terminal, and one normal Linux desktop terminal" in combined
    assert "three-OS automated support proof" in combined
    assert "uv sync --all-extras --frozen" in combined
    assert "uv run --all-extras csvql --version" in combined
    assert "Plain `csvql --version` is not sufficient for source-checkout proof" in combined
    assert "A local `pass` result from this lane is evidence only" in combined
    assert "changing any release label" in combined
    assert "VS Code integrated terminal, iTerm2, and tmux/SSH are out of scope" in combined
    for stale_required_row in (
        "the older six-row matrix",
        "iTerm2 | `output/tui-qol-qa/<run-id>/iterm2/`",
        "VS Code terminal | `output/tui-qol-qa/<run-id>/vscode-terminal/`",
        "tmux/SSH | `output/tui-qol-qa/<run-id>/tmux-ssh/`",
    ):
        assert stale_required_row not in combined
```

- [ ] **Step 3: Run the focused test and verify it fails**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_v1_polish_docs.py::test_release_docs_require_approved_three_os_tui_proof_gate \
  -q
```

Expected: FAIL because release docs still describe the older full terminal matrix and do not carry the approved automated support proof requirements.

- [ ] **Step 4: Update `docs/v1-manual-qa.md`**

Replace the paragraph after the TUI QoL QA link with this text:

```markdown
For terminal usability coverage, also run the [TUI QoL QA gate](tui-qol-qa.md).
The TUI QoL QA gate is blocking for `release-candidate eligible`.
The approved TUI release-proof target covers macOS Terminal, Windows Terminal,
and one normal Linux desktop terminal, plus same-`HEAD` three-OS automated
support proof. VS Code integrated terminal, iTerm2, and tmux/SSH are out of
scope for this release lane.
```

Replace the setup command with:

````markdown
```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras csvql --version
```
````

- [ ] **Step 5: Update `docs/release-readiness.md`**

In `## Manual QA Gates`, replace the paragraph beginning `Run the TUI QoL QA gate` through the scope-closeout paragraph with this text:

```markdown
Run the TUI QoL QA gate for required terminal coverage, media evidence, and
state-clarity checks. The approved TUI release-proof target covers macOS
Terminal, Windows Terminal, and one normal Linux desktop terminal. VS Code
integrated terminal, iTerm2, and tmux/SSH are out of scope for this release
lane.

The final TUI proof result also requires same-`HEAD` three-OS automated support
proof for macOS, native Windows, and Linux. Minimum automated support proof uses
Python 3.12, `uv sync --all-extras --frozen`, `uv run ruff format --check .`,
`uv run ruff check .`, `uv run --all-extras mypy src`, and
`uv run --all-extras pytest` on each target OS family.

Each source-checkout proof transcript must record `pwd -P`,
`git status --short --branch`, `git log -1 --oneline`, `git remote -v`,
`git tag --points-at HEAD`, `uv --version`, `uv run python --version`, and
`uv run --all-extras csvql --version`. Plain `csvql --version` is not
sufficient for source-checkout proof.

A local `pass` result from this lane is evidence only. Changing any release
label, release status, public status, tag, or published artifact still requires
separate explicit approval.
```

In `## Local Candidate Workflow`, replace steps 5 and 6 with:

```markdown
5. Run the manual v1 QA matrix and record the date, commit SHA, terminal app,
   passed items, and blockers.
6. Confirm `docs/tui-qol-qa.md` defines the approved three-OS TUI proof gate.
   Run the TUI QoL QA gate and record the TUI QoL run id, required terminal
   coverage, media artifact paths, passed items, blockers, source access
   method, commit verification command, baseline transcripts, observer labels,
   and deviations.
7. Record three-OS automated support proof for macOS, native Windows, and
   Linux on the same candidate `HEAD`.
8. Run benchmark proof or explicitly cite a current local benchmark artifact.
   A current local benchmark artifact must come from the same candidate-state
   `HEAD`; record both `output/benchmarks/<run-id>/benchmark.json` and
   `output/benchmarks/<run-id>/benchmark-summary.md`. Rerunning
   `uv run python scripts/benchmark_csvql.py --output-root output/benchmarks`
   during final candidate evaluation is preferred.
9. Scan for unsupported current claims:
```

Adjust the following numbered steps in that section so the unsupported-claim scan remains one step and classification remains the next step.

In `## Label Rules`, replace this bullet:

```markdown
- the TUI QoL QA gate passes on every required terminal with a recorded run id
  and media artifact paths
```

with:

```markdown
- the TUI QoL QA gate passes on macOS Terminal, Windows Terminal, and one normal
  Linux desktop terminal with a recorded run id, media artifact paths, baseline
  transcripts, source access method, commit verification command, and no
  failed, untested, or missing-media items
- three-OS automated support proof passes on macOS, native Windows, and Linux
  for the same candidate `HEAD`
```

- [ ] **Step 6: Update `docs/release-notes/v1.md`**

In `## Candidate Proof Checklist`, replace the TUI QoL gate paragraph with this text:

```markdown
Run the TUI QoL QA gate and record the TUI QoL run id, required terminal
coverage, media artifact paths, source access method, commit verification
command, baseline transcripts, passed items, and blockers. The approved TUI
release-proof target covers macOS Terminal, Windows Terminal, and one normal
Linux desktop terminal. VS Code integrated terminal, iTerm2, and tmux/SSH are
out of scope for this release lane.

Record same-`HEAD` three-OS automated support proof for macOS, native Windows,
and Linux. Minimum automated support proof uses Python 3.12,
`uv sync --all-extras --frozen`, `uv run ruff format --check .`,
`uv run ruff check .`, `uv run --all-extras mypy src`, and
`uv run --all-extras pytest` on each target OS family. Each source-checkout
proof transcript must include `uv --version`, `uv run python --version`, and
`uv run --all-extras csvql --version`. Plain `csvql --version` is not
sufficient for source-checkout proof.

A local `pass` result from this lane is evidence only. Changing any release
label, release status, public status, tag, or published artifact still requires
separate explicit approval.
```

In the `release-candidate eligible` checklist, replace the TUI bullet with:

```markdown
- the TUI QoL QA gate passes on macOS Terminal, Windows Terminal, and one normal
  Linux desktop terminal with a recorded run id, media artifact paths, baseline
  transcripts, source access method, commit verification command, and no
  failed, untested, or missing-media items
- three-OS automated support proof passes on macOS, native Windows, and Linux
  for the same candidate `HEAD`
```

- [ ] **Step 7: Run the focused release docs test and verify it passes**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_v1_polish_docs.py::test_release_docs_require_approved_three_os_tui_proof_gate \
  -q
```

Expected: PASS.

- [ ] **Step 8: Run related existing docs guards**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_v1_polish_docs.py::test_release_docs_keep_tui_qol_closeout_out_of_candidate_eligibility \
  tests/test_v1_polish_docs.py::test_manual_qa_matrix_links_tui_qol_gate \
  tests/test_v1_polish_docs.py::test_release_readiness_links_manual_qa_matrix \
  tests/test_v1_polish_docs.py::test_release_notes_require_manual_qa_and_tui_qol_gates \
  -q
```

Expected: PASS. If an existing assertion still expects the old macOS-only closeout wording, update that assertion to require the new three-OS proof wording shown in Steps 4 through 6, then rerun the same command.

- [ ] **Step 9: Commit Task 2**

Run:

```bash
git add docs/v1-manual-qa.md docs/release-readiness.md docs/release-notes/v1.md tests/test_v1_polish_docs.py
git commit -m "docs: align release proof with three-os TUI gate"
```

Expected: commit succeeds.

## Task 3: Expand CI To Produce Three-OS Automated Support Proof

**Files:**
- Modify: `tests/test_v1_polish_docs.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: The automated support proof requirements from Tasks 1 and 2.
- Produces: A GitHub Actions workflow that can produce cited macOS, native Windows, and Linux automated support output after separate push/run approval.

- [ ] **Step 1: Activate required skills**

Use `python-codebase-standards` before editing `tests/test_v1_polish_docs.py` and `.github/workflows/ci.yml`.

Inspect `.github/workflows/ci.yml` before editing it.

- [ ] **Step 2: Add the failing CI workflow guard**

Append this test after `test_release_docs_require_approved_three_os_tui_proof_gate`:

```python
def test_ci_workflow_collects_three_os_automated_support_gate() -> None:
    ci = read_doc(".github/workflows/ci.yml")

    for required_text in (
        "ubuntu-latest",
        "macos-latest",
        "windows-latest",
        'python-version: "3.12"',
        "uv sync --all-extras --frozen",
        "pwd -P",
        "git status --short --branch",
        "git log -1 --oneline",
        "git remote -v",
        "git tag --points-at HEAD",
        "uv --version",
        "uv run python --version",
        "uv run --all-extras csvql --version",
        "uv run ruff format --check .",
        "uv run ruff check .",
        "uv run --all-extras mypy src",
        "uv run --all-extras pytest",
        "shell: bash",
    ):
        assert required_text in ci
```

- [ ] **Step 3: Run the focused test and verify it fails**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_v1_polish_docs.py::test_ci_workflow_collects_three_os_automated_support_gate \
  -q
```

Expected: FAIL because `.github/workflows/ci.yml` currently runs Ubuntu only.

- [ ] **Step 4: Replace `.github/workflows/ci.yml`**

Replace the full workflow file with:

```yaml
name: ci

on:
  pull_request:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ${{ matrix.os }}
    defaults:
      run:
        shell: bash
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-latest
            python-version: "3.11"
          - os: ubuntu-latest
            python-version: "3.12"
          - os: macos-latest
            python-version: "3.12"
          - os: windows-latest
            python-version: "3.12"
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Set up Python
        run: uv python install ${{ matrix.python-version }}
      - name: Install dependencies
        run: uv sync --all-extras --frozen
      - name: Baseline truth
        run: |
          pwd -P
          git status --short --branch
          git log -1 --oneline
          git remote -v
          git tag --points-at HEAD
          uv --version
          uv run python --version
          uv run --all-extras csvql --version
      - name: Check formatting
        run: uv run ruff format --check .
      - name: Lint
        run: uv run ruff check .
      - name: Type check
        run: uv run --all-extras mypy src
      - name: Test
        run: uv run --all-extras pytest
```

- [ ] **Step 5: Run the focused CI workflow guard and verify it passes**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_v1_polish_docs.py::test_ci_workflow_collects_three_os_automated_support_gate \
  -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add .github/workflows/ci.yml tests/test_v1_polish_docs.py
git commit -m "ci: add three-os automated support gate"
```

Expected: commit succeeds. Do not push. Hosted CI output cannot be claimed until a later explicitly approved push or workflow run produces cited job output.

## Task 4: Verify Tracked Authority Implementation

**Files:**
- Verify: `docs/tui-qol-qa.md`
- Verify: `docs/v1-manual-qa.md`
- Verify: `docs/release-readiness.md`
- Verify: `docs/release-notes/v1.md`
- Verify: `.github/workflows/ci.yml`
- Verify: `tests/test_v1_polish_docs.py`

**Interfaces:**
- Consumes: Tracked implementation from Tasks 1 through 3.
- Produces: Local proof that tracked authority docs, guard tests, and CI workflow syntax text agree before proof execution starts.

- [ ] **Step 1: Run focused docs guards**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py -q
```

Expected: PASS.

- [ ] **Step 2: Run lint and type checks**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras mypy src
```

Expected: all commands PASS.

- [ ] **Step 3: Run full pytest**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest
```

Expected: PASS.

- [ ] **Step 4: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code `0`.

- [ ] **Step 5: Inspect tracked diff**

Run:

```bash
git diff --stat
git diff -- docs/tui-qol-qa.md docs/v1-manual-qa.md docs/release-readiness.md docs/release-notes/v1.md tests/test_v1_polish_docs.py .github/workflows/ci.yml
```

Expected: diff is limited to the approved authority docs, docs guards, and CI workflow.

- [ ] **Step 6: Commit Task 4 verification note if tracked files changed during fixes**

If Step 5 required a tracked correction, run:

```bash
git add docs/tui-qol-qa.md docs/v1-manual-qa.md docs/release-readiness.md docs/release-notes/v1.md tests/test_v1_polish_docs.py .github/workflows/ci.yml
git commit -m "test: guard three-os TUI release proof docs"
```

Expected: commit succeeds when there are staged corrections. If no corrections were made in Task 4, skip this commit step and leave the Task 1 through Task 3 commits as the tracked implementation.

## Task 5: Prepare The Proof-Execution Packet After Separate Approval

**Files:**
- Create ignored evidence root after approval: `output/tui-qol-qa/<run-id>/`
- Create ignored evidence file after approval: `output/tui-qol-qa/<run-id>/RESULT.md`
- Create ignored command outputs after approval: `output/tui-qol-qa/<run-id>/commands/`
- Create ignored media directories after approval: `output/tui-qol-qa/<run-id>/macos-terminal/`
- Create ignored media directories after approval: `output/tui-qol-qa/<run-id>/windows-terminal/`
- Create ignored media directories after approval: `output/tui-qol-qa/<run-id>/linux-terminal/`

**Interfaces:**
- Consumes: Approved and committed tracked authority implementation from Tasks 1 through 4.
- Produces: Ignored local evidence packet that can honestly classify the TUI proof as `pass`, `fail`, or `blocked`.

- [ ] **Step 1: Stop for proof-execution approval**

Ask the user for explicit approval before running terminal proof, coordinating outside observers, pushing for hosted CI, or collecting Windows/Linux evidence.

Required approval statement:

```text
Approve proof execution for the approved three-OS TUI release-proof lane.
```

Expected: if approval is not granted, stop here and report that implementation is ready but proof execution is not started.

- [ ] **Step 2: Create the ignored proof root**

After approval, run:

```bash
run_id="20260707-$(git rev-parse --short HEAD)-three-os-tui"
mkdir -p "output/tui-qol-qa/$run_id/commands"
mkdir -p "output/tui-qol-qa/$run_id/macos-terminal"
mkdir -p "output/tui-qol-qa/$run_id/windows-terminal"
mkdir -p "output/tui-qol-qa/$run_id/linux-terminal"
printf '%s\n' "$run_id"
```

Expected: prints the run id and creates ignored directories.

- [ ] **Step 3: Capture local baseline truth**

Run:

```bash
run_id="20260707-$(git rev-parse --short HEAD)-three-os-tui"
{
  pwd -P
  git status --short --branch
  git log -1 --oneline
  git remote -v
  git tag --points-at HEAD
  env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv --version
  env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run python --version
  env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras csvql --version
} > "output/tui-qol-qa/$run_id/commands/local-baseline.txt" 2>&1
```

Expected: command exits `0`; `local-baseline.txt` records repo truth and version identity.

- [ ] **Step 4: Create `RESULT.md` skeleton**

Create `output/tui-qol-qa/$run_id/RESULT.md` with this exact structure:

```markdown
# TUI QoL QA Result

- Run id:
- Candidate commit SHA:
- Final status: blocked
- Local proof result only; release label changes require separate explicit approval: yes
- No tag, publish, release artifact upload, version change, remote configuration, or release action occurred: yes

## Baseline Truth

| Evidence item | Source access method | Commit verification command | Transcript path | Status |
| --- | --- | --- | --- | --- |
| macOS Terminal | local checkout | `git log -1 --oneline` | commands/local-baseline.txt | blocked |
| Windows Terminal |  |  |  | blocked |
| Linux terminal |  |  |  | blocked |
| Automated macOS |  |  | commands/automated-macos.txt | blocked |
| Automated Windows |  |  | commands/automated-windows.txt | blocked |
| Automated Linux |  |  | commands/automated-linux.txt | blocked |

## Automated Support Proof

| OS | Runner | Python | uv | Install command | Command set | Output path | Status | Deviations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| macOS |  |  |  | `uv sync --all-extras --frozen` | Ruff format, Ruff check, mypy, pytest | commands/automated-macos.txt | blocked |  |
| Windows |  |  |  | `uv sync --all-extras --frozen` | Ruff format, Ruff check, mypy, pytest | commands/automated-windows.txt | blocked |  |
| Linux |  |  |  | `uv sync --all-extras --frozen` | Ruff format, Ruff check, mypy, pytest | commands/automated-linux.txt | blocked |  |

## Manual Terminal Rows

| Terminal | OS | Shell | Settings | Viewports | Evidence source | Media path | Status | Blockers |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| macOS Terminal |  |  | default |  | local | macos-terminal/ | blocked | not run |
| Windows Terminal |  |  | default |  | local or observer-provided | windows-terminal/ | blocked | not run |
| Linux terminal |  |  | default |  | local or observer-provided | linux-terminal/ | blocked | not run |

## Flow Matrix

| Flow | macOS Terminal | Windows Terminal | Linux terminal | Notes |
| --- | --- | --- | --- | --- |
| QOL-01 |  |  |  |  |
| QOL-02 |  |  |  |  |
| QOL-03 |  |  |  |  |
| QOL-04 |  |  |  |  |
| QOL-05 |  |  |  |  |
| QOL-06 |  |  |  |  |
| QOL-07 |  |  |  |  |
| QOL-08 |  |  |  |  |
| QOL-09 |  |  |  |  |
| QOL-10 |  |  |  |  |
| QOL-11 |  |  |  |  |
| QOL-12 |  |  |  |  |
| QOL-13 |  |  |  |  |
| QOL-14 |  |  |  |  |
| QOL-15 |  |  |  |  |
| QOL-16 |  |  |  |  |
| QOL-17 |  |  |  |  |
| QOL-18 |  |  |  |  |
| QOL-19 |  |  |  |  |
| QOL-20 |  |  |  |  |
| QOL-21 |  |  |  |  |

## Out-of-Scope Rows

VS Code integrated terminal, iTerm2, and tmux/SSH were out of scope for this release-proof lane.

## Blockers

- Windows Terminal evidence missing.
- Linux terminal evidence missing.
- Three-OS automated support proof missing.
```

Expected: initial `RESULT.md` is explicitly `blocked` until proof is collected.

- [ ] **Step 5: Run macOS automated support proof locally**

Run:

```bash
run_id="20260707-$(git rev-parse --short HEAD)-three-os-tui"
{
  pwd -P
  git status --short --branch
  git log -1 --oneline
  git remote -v
  git tag --points-at HEAD
  env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv --version
  env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv sync --all-extras --frozen
  env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run python --version
  env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras csvql --version
  env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff format --check .
  env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check .
  env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras mypy src
  env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest
} > "output/tui-qol-qa/$run_id/commands/automated-macos.txt" 2>&1
```

Expected: exit code `0` for a macOS automated support pass. If any command fails, classify the automated macOS row as `fail` and stop for debugging before changing the proof gate.

- [ ] **Step 6: Collect Windows and Linux automated support proof**

Use one of these approved evidence sources:

```text
1. Hosted CI job output from the three-OS workflow after separate push or workflow-run approval.
2. User-provided native Windows and Linux environments.
3. Outside-observer transcripts from approved source access paths.
```

Required command set for each OS:

```bash
pwd -P
git status --short --branch
git log -1 --oneline
git remote -v
git tag --points-at HEAD
uv --version
uv sync --all-extras --frozen
uv run python --version
uv run --all-extras csvql --version
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

Expected: write or cite outputs as `commands/automated-windows.*` and `commands/automated-linux.*`. If a required command runs and fails, classify that OS automated proof row as `fail`. If source access or output trust is missing, classify it as `blocked`.

- [ ] **Step 7: Run or collect manual terminal evidence**

For each required row, run every QOL flow in `docs/tui-qol-qa.md`:

```text
macOS Terminal -> output/tui-qol-qa/<run-id>/macos-terminal/
Windows Terminal -> output/tui-qol-qa/<run-id>/windows-terminal/
Linux desktop terminal -> output/tui-qol-qa/<run-id>/linux-terminal/
```

Expected:

```text
pass = row runs every required flow with media evidence on the candidate HEAD
fail = row runs and a required flow fails
blocked = row is missing, untested, lacks media, lacks commit identity, or cannot be trusted as same-HEAD evidence
```

Windows Terminal must use native Windows Python/`uv`; a WSL tab cannot fill the Windows row.

- [ ] **Step 8: Finalize `RESULT.md` classification**

Update `RESULT.md` using these rules:

```text
pass = all three manual terminal rows pass, all three automated support rows pass, and all evidence is same-HEAD
fail = a required manual flow fails or a required automated command fails
blocked = required evidence is missing, stale, untrusted, or source access is not approved
```

Expected: result is honest and does not change release status. If the result is `pass`, report it as local proof evidence only and ask for separate approval before any release label/status action.

- [ ] **Step 9: Verify ignored proof artifacts**

Run:

```bash
run_id="20260707-$(git rev-parse --short HEAD)-three-os-tui"
test -f "output/tui-qol-qa/$run_id/RESULT.md"
git status --short --branch
git tag --points-at HEAD
git remote -v
```

Expected: `RESULT.md` exists; tracked status does not include ignored `output/` artifacts; no tag, remote configuration, push, publish, release artifact upload, version change, or release action occurred.

## Final Self-Review Checklist

- [ ] Spec coverage: Tasks 1 through 3 implement tracked authority docs, docs guards, and CI workflow support; Task 5 covers proof-execution packet rules.
- [ ] Terminal scope: docs name only macOS Terminal, Windows Terminal, and one normal Linux desktop terminal as release-blocking rows.
- [ ] Out-of-scope rows: VS Code integrated terminal, iTerm2, and tmux/SSH are explicitly out of scope for this lane.
- [ ] Automated support proof: docs and CI require macOS, native Windows, and Linux automated support proof with Python 3.12 and `uv sync --all-extras --frozen`.
- [ ] Baseline transcripts: docs require `pwd -P`, Git truth commands, `uv --version`, `uv run python --version`, and `uv run --all-extras csvql --version`.
- [ ] Source-checkout version proof: plain `csvql --version` is allowed only for installed-wheel proof.
- [ ] Release boundaries: docs say a local `pass` result is evidence only and release label/status changes require separate explicit approval.
- [ ] Verification: focused docs tests, Ruff format check, Ruff lint, mypy, full pytest, and `git diff --check` are included before completion.
