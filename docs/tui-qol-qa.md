# TUI QoL QA Gate

Status: blocking release-proof gate for `csvql menu` deterministic behavior and
cross-OS automated support.

This gate is local release evidence only. It does not publish, tag, upload,
push, bump version, or claim `v1-stable`.

Any failed required item blocks `release-candidate eligible`.

If required automated support proof is untested, failed, stale, or missing
same-`HEAD` identity, the candidate status remains `not eligible yet`.
Windows and Linux screenshots or manual terminal media are not required for
this rescoped lane.

## Approved Cross-OS Automated Release-Proof Scope

The approved release-proof target now uses same-`HEAD` automated support proof
on macOS, native Windows, and Linux. Windows and Linux manual terminal
screenshots are no longer required for this lane. This is a rescoped
release-proof lane, not a claim that the project is already release-candidate
eligible.

This proof shows that the source checkout, CLI, Python package, optional
Textual-backed TUI code, and deterministic test-covered behavior pass on those
OS families. It does not prove OS-level Windows or Linux terminal UX details
such as function-key delivery, Alt-key delivery, native picker focus, or visual
terminal rendering. A separate approved manual terminal proof lane is required
before making those OS-level UX claims.

Historical local evidence remains useful context:

- macOS Terminal local TUI QoL evidence has been recorded under
  `output/tui-qol-qa/20260707-0a946cc-three-os-tui/macos-terminal/`.
- VS Code integrated terminal is out of scope for this release lane after the
  2026-07-07 keybinding spike showed default macOS Option-key behavior did not
  reliably reach the TUI.
- iTerm2 and tmux/SSH are out of scope for this release lane.
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
  final TUI proof result can pass; screenshots are not required for those OS rows.

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

## Manual Terminal Evidence

A manual terminal run is optional context for this rescoped lane unless a later
approved plan makes a specific manual row required. The retained manual terminal
context for the current lane is macOS Terminal:

| Terminal path | Required evidence directory |
| --- | --- |
| macOS Terminal | `output/tui-qol-qa/<run-id>/macos-terminal/` |

Optional Windows or Linux manual terminal evidence may be recorded under
`output/tui-qol-qa/<run-id>/windows-terminal/` or
`output/tui-qol-qa/<run-id>/linux-terminal/`, but those media paths are not
required for `release-candidate eligible` in this lane.

Native Windows automated proof must use a native Windows environment and native
Windows Python/`uv` setup. A Windows Terminal tab running WSL counts as
Linux/WSL context, not native Windows proof, unless a separate design review
explicitly approves a different classification before proof execution.

Any manual terminal proof that is cited should use default terminal settings. A
non-default setting is allowed only when explicitly approved before the run and
recorded as a deviation in the result packet.

## Out-of-Scope Rows

These rows do not block this release-proof lane:

- VS Code integrated terminal
- iTerm2
- tmux/SSH

Out of scope does not mean unsupported forever. It means those terminal hosts
must not be used to claim pass or fail status for the macOS, Windows, and Linux
target.

## Required Setup

Run from the repository root unless a step says otherwise.

Use the same candidate commit for every cited manual terminal context and every
automated support proof source. Each cited manual row and automated platform
proof must include a
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

## Required Automated Support Proof

The final proof result cannot be `pass` without same-`HEAD` automated support
proof for macOS, native Windows, and Linux. This is the required Windows and
Linux proof for the rescoped lane.

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

For implementation changes after a cited proof run, record the fresh GitHub
Actions run id and implementation commit SHA in the ignored proof packet
`RESULT.md` and final execution response. Tracked docs must not require a
self-referential run id for their own commit; doing so creates proof churn
unless a separate two-SHA proof recording model is approved.

Automated support proof outputs should use a clearly mapped naming convention:

- `commands/automated-macos.*`
- `commands/automated-windows.*`
- `commands/automated-linux.*`

An equivalent naming scheme is acceptable only if `RESULT.md` maps each file to
the OS family, runner, command set, and proof status.

## Manual Behavior Matrix

Use this matrix for any manual terminal evidence that is cited. Windows and
Linux manual runs are optional context for this lane; automated proof is the
required Windows and Linux gate.

| ID | Flow | Pass condition |
| --- | --- | --- |
| QOL-01 | Launch empty | Workbench opens, SQL editor is focused, and the status explains no sources are loaded. |
| QOL-02 | Launch with one CSV | Source appears with expected alias, kind, path, and origin. |
| QOL-03 | Launch from a project catalog | Catalog sources appear without extra prompt work. |
| QOL-04 | Add a source with `F3` or `Ctrl+O` | Native picker works where available; otherwise the documented picker fallback prompt appears and accepts a CSV path. |
| QOL-05 | Add a source through the Add Source prompt | `name=path` adds the expected session source and selects it predictably. |
| QOL-06 | Add source by pasted standalone path | Pasted standalone `.csv` path text into the SQL editor adds session sources. Typing a path as ordinary editor text leaves it as SQL/editor text. If a terminal delivers a file drop as pasted path text, the same pasted-path behavior applies there too. CSV paths inside SQL strings, comments, or expressions remain SQL text. |
| QOL-07 | Run selected SQL | Only the selected SQL runs and History records one attempt. |
| QOL-08 | Run the current statement | `F4` and `Ctrl+R` run the statement around the cursor, not unrelated editor text. |
| QOL-09 | Run Buffer with `F12` or `Ctrl+B` | Statements run in order in one DuckDB session, each statement is recorded as a separate History row, temp tables or DDL can feed later statements, and execution stops on the first failure. |
| QOL-10 | Select multi-result output from Run Buffer | Successful tabular Run Buffer results support multi-result selection, and the selected result becomes the active result. |
| QOL-11 | Rerun History rows | Rerun appends a new sequence and selects the new query row. |
| QOL-12 | Export active result | Export writes the active result, including a recalled History result or selected buffer result. |
| QOL-13 | Save active result as a derived source | Derived CSV is written under `.csvql/results/`, added as a session source, and queryable. |
| QOL-14 | Save a derived source from a recalled History result | Derived CSV uses the recalled result, not the most recently executed result. |
| QOL-15 | Open and close help repeatedly from every pane | Help does not stack; one `Esc` closes one help modal and returns to a predictable pane. |
| QOL-16 | Try every documented key from every pane | Each key acts, types text, or is intentionally unavailable according to the active pane. |
| QOL-17 | Resize the terminal while using each pane | Core panes remain understandable and no traceback appears. |
| QOL-18 | Run invalid SQL | Error is visible, History records the failure, and prior result state is not misleading. |
| QOL-19 | Run SQL against a missing source or missing file path | Error is visible with guidance and no traceback appears. |
| QOL-20 | Run DDL or no-result SQL | TUI displays DuckDB metadata results when present, or a clear no-tabular-result state when no result exists. |
| QOL-21 | Run batch SQL where a middle statement fails | Earlier statements are recorded, the failing statement is recorded, later statements do not run, and state is clear. |

## State-Clarity Questions

For each flow, the tester must be able to answer:

- Which pane is active?
- What will this key or action do in the current pane?
- Which source, query, History row, result, export, or derived-source target is affected?
- Did the action run, get rejected, or require fallback?
- Is the next expected action clear?

The flow fails if the TUI crashes, hangs, stacks duplicate modals, loses focus in
an unclear way, exports or saves the wrong result, reruns when it should only
recall, silently ignores an important documented action without a clear fallback,
or leaves the tester unable to identify the active state or action target.

Before export or save-source actions are accepted, the footer, pane title,
result selector, or status line must identify the active result.

## Evidence Rules

Each cited manual terminal run must record:

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
- media artifact paths, when media is collected
- deviations, skipped steps, and failures

Outside-observer manual evidence must also include the observer label, observer
timestamp and timezone, setup transcript, source or evidence transfer method,
and per-flow notes for every TUI QoL matrix item.

Local media evidence is required only for manual terminal rows that are cited as
manual proof. Screenshots or recordings live under ignored proof paths:

```text
output/tui-qol-qa/<run-id>/<terminal-id>/
```

The media files are local proof artifacts. Do not commit them. Windows and
Linux screenshots are optional context in this rescoped lane and are not
required for pass status.

## Classification Rules

- `pass`: all three automated support rows pass, the evidence is same-`HEAD`,
  and the required baseline transcripts, source access method, commit
  verification command, and command outputs are complete. Any cited required
  manual terminal context must not have failed required flows.
- `fail`: a required automated command runs and fails, or a cited required
  manual flow runs and fails.
- `blocked`: required evidence is missing, stale, untrusted, lacks approved
  source access, lacks commit identity, or same-`HEAD` evidence cannot be
  proven.

## Result Summary Template

```markdown
# TUI QoL QA Result

- Run id:
- Candidate commit SHA:
- Final status: pass | fail | blocked
- A local `pass` result from this lane is evidence only; release-candidate eligibility requires separate same-`HEAD` proof agreement:
- Local proof result only; release label changes require separate explicit approval:
- No tag, publish, release artifact upload, version change, remote configuration, or release action occurred:

## Baseline Truth

| Evidence item | Source access method | Commit verification command | Transcript path | Status |
| --- | --- | --- | --- | --- |
| macOS Terminal manual context, if cited |  |  |  |  |
| Automated macOS |  |  | commands/automated-macos.* |  |
| Automated Windows |  |  | commands/automated-windows.* |  |
| Automated Linux |  |  | commands/automated-linux.* |  |

## Automated Support Proof

| OS | Runner | Python | uv | Install command | Command set | Output path | Status | Deviations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| macOS |  |  |  | `uv sync --all-extras --frozen` | Ruff format, Ruff check, mypy, pytest | commands/automated-macos.* |  |  |
| Windows |  |  |  | `uv sync --all-extras --frozen` | Ruff format, Ruff check, mypy, pytest | commands/automated-windows.* |  |  |
| Linux |  |  |  | `uv sync --all-extras --frozen` | Ruff format, Ruff check, mypy, pytest | commands/automated-linux.* |  |  |

## Manual Terminal Context

| Terminal | OS | Shell | Settings | Viewports | Evidence source | Media path | Status | Blockers |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| macOS Terminal |  |  | default |  | local | output/tui-qol-qa/<run-id>/macos-terminal/ |  |  |

## Flow Matrix

| Flow | macOS Terminal manual context | Notes |
| --- | --- | --- |
| QOL-01 |  |  |
| QOL-02 |  |  |
| QOL-03 |  |  |
| QOL-04 |  |  |
| QOL-05 |  |  |
| QOL-06 |  |  |
| QOL-07 |  |  |
| QOL-08 |  |  |
| QOL-09 |  |  |
| QOL-10 |  |  |
| QOL-11 |  |  |
| QOL-12 |  |  |
| QOL-13 |  |  |
| QOL-14 |  |  |
| QOL-15 |  |  |
| QOL-16 |  |  |
| QOL-17 |  |  |
| QOL-18 |  |  |
| QOL-19 |  |  |
| QOL-20 |  |  |
| QOL-21 |  |  |

## Out-of-Scope Rows

VS Code integrated terminal, iTerm2, tmux/SSH, and Windows/Linux manual
terminal screenshots were out of scope for this rescoped release-proof lane.
```

## Automation Boundary

Automated tests should cover deterministic TUI behavior in pytest/Textual.
Manual QA remains required before making OS-level terminal UX claims such as
function-key interception, Alt-key differences, tmux passthrough, SSH quirks,
visual rendering in a specific terminal, and native file picker behavior.
