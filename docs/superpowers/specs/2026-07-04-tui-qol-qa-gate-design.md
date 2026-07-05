# TUI QoL QA Gate Design

## Status

Approved design for a dedicated TUI quality-of-life release gate. This document
specifies the gate only; implementation planning and code changes are separate.

## Context

LocalQL's installable distribution remains `localql`, while the runtime contract
continues to use the `csvql` CLI, Python import package, `.csvql.yml`, and
`csvql menu` TUI command. Recent TUI work fixed source loading, help stacking,
multi-statement execution, and History result recall. The remaining risk is not
core DuckDB execution. It is terminal variance, focus ambiguity, result-target
ambiguity, modal behavior, and small workflow bugs that users discover during
normal terminal use.

The existing `docs/v1-manual-qa.md` is a release checklist. It is useful, but
too compact to serve as a thorough TUI quality-of-life regression gate.

## Goals

- Create a dedicated TUI QoL QA matrix that must pass before any
  `release-candidate eligible` assessment.
- Make the matrix behavior-oriented: each check verifies that the tester can
  understand the active pane, action target, current result, and expected next
  state.
- Cover terminal-specific behavior across macOS, Linux, Windows, VS Code, and
  tmux/SSH paths.
- Require auditable local proof artifacts, including media for every terminal
  run.
- Use the manual matrix as the source of truth for later targeted automated TUI
  regressions.

## Non-Goals

- Do not add a web UI, cloud workflow, plugin system, NLP execution path, or
  broader product platform scope.
- Do not claim sandbox safety, safe untrusted SQL execution, production
  readiness, or broad large-file proof.
- Do not publish, tag, upload artifacts, push, bump version, or change public
  release labels as part of this gate.
- Do not require automation for OS-level terminal behavior that Textual tests
  cannot reliably simulate.

## Authority Surfaces

Add a new committed document:

- `docs/tui-qol-qa.md`

Link it from:

- `docs/v1-manual-qa.md`
- `docs/release-readiness.md`

The release-readiness language should make the gate blocking:

> Any failed TUI QoL matrix item blocks `release-candidate eligible`.

If a terminal or flow is untested, failed, or missing required media, the
candidate status remains `not eligible yet`.

## Required Terminal Coverage

Every TUI QoL run must cover:

- macOS Terminal
- iTerm2
- VS Code terminal
- Linux terminal
- Windows Terminal
- tmux/SSH

If a terminal cannot be tested by the local operator, the result row must name
the outside observer and identify where their media evidence was collected into
the local proof directory.

## Manual Matrix Flows

Each terminal must run the same behavior matrix:

1. Launch empty.
2. Launch with one CSV.
3. Launch from a project catalog.
4. Add a source with `F3`.
5. Add a source through the Add Source prompt.
6. Add a source by pasted path.
7. Run selected SQL.
8. Run the current statement.
9. Run full-buffer multi-statement SQL with `F12`.
10. Recall History results.
11. Rerun History rows.
12. Export a recalled result.
13. Save a derived source from the latest result.
14. Save a derived source from a recalled History result.
15. Open and close help repeatedly from every pane.
16. Try every documented key from every pane.
17. Resize the terminal while using each pane.
18. Run invalid SQL.
19. Run SQL against a missing source or missing file path.
20. Run DDL or no-result SQL.
21. Run batch SQL where a middle statement fails.

## Pass Criteria

For each flow, the tester must be able to answer:

- Which pane is active?
- What will this key or action do in the current pane?
- Which source, query, History row, result, export, or derived-source target is
  affected?
- Did the action run, get rejected, or require fallback?
- Is the next expected action clear?

The flow fails if the TUI crashes, hangs, stacks duplicate modals, loses focus in
an unclear way, exports or saves the wrong result, reruns when it should only
recall, silently ignores an important documented action without a clear fallback,
or leaves the tester unable to identify the active state or action target.

## Evidence Requirements

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

Media evidence is required for every terminal run, not only failures.
Screenshots or recordings live under ignored proof paths:

```text
output/tui-qol-qa/<run-id>/<terminal-id>/
```

Recommended terminal ids:

- `macos-terminal`
- `iterm2`
- `vscode-terminal`
- `linux-terminal`
- `windows-terminal`
- `tmux-ssh`

The media files are local proof artifacts and should not be committed. The
committed QA doc should include a result-recording template and expected folder
shape.

## Result Summary Template

The QA doc should include a compact template:

```markdown
## TUI QoL QA Result

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
```

## Automated Regression Strategy

The manual matrix lands first and defines the behavior contract. Automation
follows as a targeted regression layer for deterministic behavior.

Automation candidates:

- Help does not stack from repeated `F1` or `?`.
- `Esc` closes one modal and restores predictable focus.
- Documented keys either act or are intentionally disabled by pane.
- `F12` creates separate History rows and result snapshots.
- History highlight recalls the selected result without rerunning SQL.
- Rerunning History appends a new sequence and selects it.
- Export/save acts on the currently recalled successful result.
- Invalid SQL, no-result SQL, and batch mid-failure preserve clear state.
- CSV path paste, `F3` fallback, and Add Source prompt produce consistent
  session sources.
- Tiny and wide terminal dimensions keep the core panes usable where Textual can
  simulate the behavior reliably.

Manual-only coverage remains required for OS-level terminal behavior such as
function-key interception, Alt-key emission differences, tmux passthrough, SSH
quirks, and platform-specific file-picker behavior.

## Implementation Sequence

1. Add `docs/tui-qol-qa.md` with the matrix, evidence rules, result template,
   pass/fail criteria, and ignored artifact path convention.
2. Link the new TUI QoL gate from `docs/v1-manual-qa.md`.
3. Update `docs/release-readiness.md` candidate workflow and label rules so the
   TUI QoL gate blocks `release-candidate eligible`.
4. Add or adjust automated tests for deterministic TUI regressions listed above.
5. Run the documented TUI QoL matrix and record a local proof summary before any
   stronger release assessment.

## Open Release Status

Until the new TUI QoL matrix is implemented, run, and passed across all required
terminals with media evidence, the release status remains `not eligible yet`.
