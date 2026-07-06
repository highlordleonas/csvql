# TUI QoL Repair Design

## Status

Approved design for a narrow, release-blocking TUI quality-of-life repair pass.
This document specifies behavior only. Implementation planning and code changes
are separate follow-up work.

## Context

LocalQL's installable distribution remains `localql`, while the runtime contract
continues to use the `csvql` CLI, Python import package, `.csvql.yml`, and
`csvql menu` TUI command.

The TUI QoL gate is already release-blocking. Recent testing and review exposed
remaining usability and correctness issues around `F12`, help/modal stacking,
portable key behavior, History sequencing, result ownership, and pasted CSV path
handling. These issues must be repaired and manually proven before any stronger
`release-candidate eligible` assessment.

## Goals

- Keep the TUI focused on local CSV sources and trusted local DuckDB SQL.
- Make every run action and result target understandable from the visible UI.
- Fix confirmed RC-blocking workflow bugs without broadening product scope.
- Preserve useful power-user behavior where it can be made clear and testable.
- Strengthen automated regressions for deterministic TUI behavior.
- Update the manual TUI QoL matrix so terminal-by-terminal QA checks the repaired
  behavior explicitly.

## Non-Goals

- Do not add a web UI, cloud workflow, plugin system, NLP execution path,
  dataframe-first API, hidden cache, or broader platform behavior.
- Do not claim sandbox safety, safe untrusted SQL execution, production
  readiness, or broad large-file proof.
- Do not publish, tag, upload artifacts, push, bump version, or change public
  release labels as part of this repair pass.
- Do not replace terminal-by-terminal manual QA with automation.

## Run Buffer Contract

Keep `F12`, but rename it everywhere from `Run All` to `Run Buffer`.

`F4` and `Ctrl+R` run selected SQL or the current statement. `F12` runs every
semicolon-delimited statement in the editor buffer.

An `F12` buffer run uses one shared DuckDB session for that batch, so temporary
tables and DDL from earlier statements can feed later statements in the same
buffer. Each statement gets its own History row with run mode `buffer`.
Execution stops at the first failing statement.

The Results pane shows a lightweight selector for successful tabular results
from the latest buffer run. The selected result in that selector is the active
target for `F7 Export` and `Ctrl+S` or `Alt+S` save-as-source. DDL or no-row
statements and failures remain visible in History/status, but they do not create
result tabs.

## Help, Modals, and Portable Keys

Use one visible help entry: `F1 Help`. Remove `? Help` from the footer and
user-facing docs as a documented shortcut. In the SQL editor, `?` types a
literal question mark. Outside the editor, `?` may remain an undocumented
compatibility alias or do nothing, but it is not a primary affordance.

Help must not stack over itself or over prompt modals. Pressing `F1` while help
is already open should leave one help screen open. Pressing `F1` while a prompt
modal is open should not stack help over the prompt. `Esc` closes only the
current modal and returns to the prior pane.

Keep function keys in the footer because they are compact, but provide
documented non-function fallbacks for terminal-hostile environments. The repair
should cover add/open CSV source, rerun in History, quit outside text entry, and
Run Buffer. Help should show both the function key and fallback where available.
The footer should stay short and prioritize common action names.

## Result Ownership and Labels

Track an explicit active result instead of relying on implicit "last result"
behavior.

Query success sets the active result to that query result. History recall sets
the active result to the recalled History result without rerunning. The buffer
result selector changes the active result to the selected buffer tab. Source
preview, inspect, sample, and profile views do not become export or save targets.

The UI should label the active object clearly, using states such as:

- `Active result: query 7`
- `Active result: buffer 3.2`
- `History preview: query 4`
- `Source preview: subscriptions`
- `No active result`

Rename visible actions to match the active-result model:

- `F7 Export active result`
- `Ctrl+S` or `Alt+S Save active result source`

History run labels should be:

- `current` for `F4` and `Ctrl+R`
- `buffer` for `F12`
- `rerun` for History reruns

Rerunning History query 9 should append a new sequence after the current maximum
sequence. If query 10 already exists, the rerun becomes query 11. After rerun,
the TUI selects or focuses the new appended row and reports `Reran query 9 as
query 11`.

## Pasted CSV Path Safety

Pasted CSV paths should become sources only when the editor content is plausibly
a dropped or pasted path, not when a path appears inside real SQL.

If the SQL editor contains only one or more standalone `.csv` paths, consume
those paths as session sources and clear the consumed text. If a `.csv` path
appears inside a SQL string literal, comment, or expression, leave it alone and
run or parse SQL normally.

When path text is ambiguous, prefer not consuming it. Show a clear status hint
that points the user to the file picker or Add Source prompt. The Add Source
prompt remains the explicit fallback and should accept both `alias=/path/file.csv`
and plain `/path/file.csv`.

## Testing and QA

Add or adjust automated tests for deterministic behavior:

- `F12 Run Buffer` uses one shared DuckDB session for the batch.
- Buffer statements create separate History rows with run mode `buffer`.
- Buffer result selection controls the active export/save target.
- Buffer execution stops at the first failing statement.
- `F1` does not stack help over help or over prompt modals.
- `?` types normally in the SQL editor.
- Portable key fallbacks work where Textual can simulate them.
- Pasted path detection does not consume SQL string literals, comments, or
  expressions that contain `.csv` paths.
- History rerun appends after the maximum sequence and selects the new row.
- Active-result export/save targets match query success, History recall, and
  buffer result selection.

Update `docs/tui-qol-qa.md` so manual terminal QA explicitly checks `Run Buffer`,
multi-result selection, fallback keys, active result labels, modal behavior, and
pasted path safety.

After implementation, run focused TUI tests first, then the full repository
gate. The release remains `not eligible yet` until the terminal-by-terminal TUI
QoL matrix passes with required media evidence and the broader authority-doc
agreement proof is complete.
