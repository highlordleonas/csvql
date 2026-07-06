# TUI QoL QA Gate

Status: blocking manual quality-of-life gate for `csvql menu`.

This gate is local release evidence only. It does not publish, tag, upload,
push, bump version, or claim `v1-stable`.

Any failed item blocks `release-candidate eligible`.

If a terminal or flow is untested, failed, or missing required media evidence,
the candidate status remains `not eligible yet`.

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

Every complete TUI QoL run must cover:

| Terminal path | Required evidence directory |
| --- | --- |
| macOS Terminal | `output/tui-qol-qa/<run-id>/macos-terminal/` |
| iTerm2 | `output/tui-qol-qa/<run-id>/iterm2/` |
| VS Code terminal | `output/tui-qol-qa/<run-id>/vscode-terminal/` |
| Linux terminal | `output/tui-qol-qa/<run-id>/linux-terminal/` |
| Windows Terminal | `output/tui-qol-qa/<run-id>/windows-terminal/` |
| tmux/SSH | `output/tui-qol-qa/<run-id>/tmux-ssh/` |

If a terminal cannot be tested locally, the result row must name the outside
observer and the collected local media path.

## Required Setup

Run from the repository root unless a step says otherwise.

Use the same candidate commit for every terminal:

```bash
pwd -P
git status --short --branch
git log -1 --oneline
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras csvql --version
```

Expected:

- working tree is clean before the run
- commit SHA is recorded in the result summary
- version prints `1.0.0`

## Behavior Matrix

Run every item in every required terminal.

| ID | Flow | Pass condition |
| --- | --- | --- |
| QOL-01 | Launch empty | Workbench opens, SQL editor is focused, and the status explains no sources are loaded. |
| QOL-02 | Launch with one CSV | Source appears with expected alias, kind, path, and origin. |
| QOL-03 | Launch from a project catalog | Catalog sources appear without extra prompt work. |
| QOL-04 | Add a source with `F3` or `Ctrl+O` | Native picker works where available; otherwise the documented picker fallback prompt appears and accepts a CSV path. |
| QOL-05 | Add a source through the Add Source prompt | `name=path` adds the expected session source and selects it predictably. |
| QOL-06 | Add source by pasted standalone path | A pasted standalone CSV path becomes a session source and does not remain as SQL text; CSV paths inside SQL strings, comments, or expressions remain SQL text. |
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

Each terminal run must record:

- date
- commit SHA
- tester
- OS
- terminal name and version
- viewport size range tested
- pass/fail for each flow
- blocker notes
- media artifact paths

Local media evidence is required for every terminal run, not only failures.
Screenshots or recordings live under ignored proof paths:

```text
output/tui-qol-qa/<run-id>/<terminal-id>/
```

The media files are local proof artifacts. Do not commit them.

## Result Summary Template

```markdown
# TUI QoL QA Result

- Run id:
- Commit:
- Overall status: pass | fail | blocked
- Tester:
- Date:

| Terminal | OS | Version | Viewports | Media path | Status | Blockers |
| --- | --- | --- | --- | --- | --- | --- |
| macOS Terminal |  |  |  | output/tui-qol-qa/<run-id>/macos-terminal/ |  |  |
| iTerm2 |  |  |  | output/tui-qol-qa/<run-id>/iterm2/ |  |  |
| VS Code terminal |  |  |  | output/tui-qol-qa/<run-id>/vscode-terminal/ |  |  |
| Linux terminal |  |  |  | output/tui-qol-qa/<run-id>/linux-terminal/ |  |  |
| Windows Terminal |  |  |  | output/tui-qol-qa/<run-id>/windows-terminal/ |  |  |
| tmux/SSH |  |  |  | output/tui-qol-qa/<run-id>/tmux-ssh/ |  |  |

| Flow | macOS Terminal | iTerm2 | VS Code | Linux | Windows | tmux/SSH | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| QOL-01 |  |  |  |  |  |  |  |
| QOL-02 |  |  |  |  |  |  |  |
| QOL-03 |  |  |  |  |  |  |  |
| QOL-04 |  |  |  |  |  |  |  |
| QOL-05 |  |  |  |  |  |  |  |
| QOL-06 |  |  |  |  |  |  |  |
| QOL-07 |  |  |  |  |  |  |  |
| QOL-08 |  |  |  |  |  |  |  |
| QOL-09 |  |  |  |  |  |  |  |
| QOL-10 |  |  |  |  |  |  |  |
| QOL-11 |  |  |  |  |  |  |  |
| QOL-12 |  |  |  |  |  |  |  |
| QOL-13 |  |  |  |  |  |  |  |
| QOL-14 |  |  |  |  |  |  |  |
| QOL-15 |  |  |  |  |  |  |  |
| QOL-16 |  |  |  |  |  |  |  |
| QOL-17 |  |  |  |  |  |  |  |
| QOL-18 |  |  |  |  |  |  |  |
| QOL-19 |  |  |  |  |  |  |  |
| QOL-20 |  |  |  |  |  |  |  |
| QOL-21 |  |  |  |  |  |  |  |
```

## Automation Boundary

Automated tests should cover deterministic TUI behavior in pytest/Textual.
Manual QA remains required for OS-level terminal behavior such as function-key
interception, Alt-key differences, tmux passthrough, SSH quirks, and native file
picker behavior.
