# TUI Adversarial Follow-Up Design

## Status

Approved design for a phased follow-up to the TUI QoL adversarial review.
This document specifies product behavior, implementation boundaries, acceptance
tests, and verification gates. Implementation planning and code changes are
separate follow-up work.

## Context

LocalQL is the installable distribution name. The runtime contract remains the
`csvql` CLI, the `csvql` Python import package, `.csvql.yml` project config,
and the `csvql menu` TUI command.

The TUI QoL branch already repaired the major Run Buffer, source layout, active
result, and footer issues. A later adversarial review found additional
correctness, responsiveness, durability, and policy gaps. Those gaps should be
handled as a phased repair program before treating manual TUI QA as meaningful
release evidence.

This work stays local-first and terminal-first. User-authored SQL remains trusted
local DuckDB SQL. The design must not imply sandbox safety, safe untrusted SQL,
production readiness, broad large-file proof, a web app, cloud connectors, NLP
execution, a dataframe-first API, plugins, hidden cache/materialization, or
broader platform scope.

This design also does not authorize version changes, tags, publishing, artifact
uploads, remotes, release labels, `v1-stable`, or release-candidate proof work.

## Goals

- Fix confirmed TUI correctness issues before manual QA.
- Keep visible result ownership aligned with export and save behavior.
- Make potentially slow source, export, and save operations responsive and
  cancellable.
- Make buffer result selection discoverable without making it global.
- Make file writes safer under failure and cancellation.
- Preserve local power-user path behavior while warning about privacy-sensitive
  persisted paths.
- Preserve full-result export and save semantics while reducing memory pressure
  for large tabular results.
- Make CSV path ingestion happen only from explicit paste or drop events.
- Define acceptance tests for every phase.

## Non-Goals

- No release-candidate eligibility gate, manual terminal matrix execution, tag,
  publish, version, upload, remote, or release status change.
- No compact responsive layout or one-pane narrow mode in this follow-up.
- No user-facing configuration surface for large-result spill thresholds yet.
- No hard rejection of external absolute paths or symlink-resolved external
  paths.
- No claim that local DuckDB SQL execution is isolated from trusted user input.

## Phase Model

The repair program has three phases.

- `P0 Correctness Gate`: fixes behavior that can silently mutate or retarget
  user work. P0 blocks manual TUI QA.
- `P1 Responsiveness And Discoverability`: workerizes slow TUI actions,
  supports cancellation, and makes buffer selection and small terminal limits
  visible.
- `P2 Durability, Result Storage, And Path Policy`: adds atomic writes,
  temp-backed result storage, path warnings, and paste/drop-only CSV ingestion.

Each phase should be independently planned, implemented, reviewed, and verified.
P1 and P2 must not be folded into P0 unless a P0 repair needs a very small
supporting helper.

## Architecture Overview

The implementation should keep the current TUI structure but make three
responsibility boundaries explicit.

`Action gate`
: Decides whether a key binding or action is allowed in the current focus,
  modal, and worker state. This belongs close to `check_action()` and should be
  backed by focused tests.

`Result store`
: Owns active, history, and buffer tabular result storage. It should let the UI
  render bounded previews while export and save operations can still access the
  full active result. Small results may remain in memory. Large results spill to
  session temp artifacts.

`File write service`
: Owns atomic export, derived CSV, and `.csvql.yml` writes. It should use a temp
  sibling file in the target directory, close it, then replace the final path.
  It should also support cancellation cleanup before final replacement.

The UI remains the orchestrator: it prompts, starts workers, updates status,
refreshes panes, and handles cancellation. Domain-style helpers should own
path/result/write rules so behavior can be tested without a full TUI run.

## P0 Correctness Gate

P0 fixes behaviors that can silently mutate state behind a modal or retarget the
active result from the wrong pane.

### Modal Action Fencing

When `_PromptInputScreen` or `_ConfirmationScreen` is active, global app actions
must not affect the underlying app. Modal-local keys still work.

Blocked while a prompt or confirmation is active:

- new query or clear editor
- focus changes
- run actions
- source actions
- history actions
- result navigation
- export and save-as-source
- quit-from-non-editor unless the active modal explicitly owns it

The main enforcement point should be `check_action()`, with defensive action
guards on high-impact actions where practical. Help modal behavior can keep its
existing one-screen-at-a-time protection.

Acceptance tests:

- Open the F7 export prompt, press `F10`, and verify the SQL editor is unchanged.
- Open the F7 export prompt, press source/history/result actions, and verify no
  underlying state changes.
- Open remove-source confirmation, press `F10` and source/history/result
  actions, and verify no underlying state changes.
- Confirming or cancelling the modal still performs only the modal-specific
  action.

### Buffer Result Navigation Scope

`[` and `]` select previous or next buffer result only when Results is focused.
They must not silently retarget the active/exportable result from Sources,
History, or the SQL editor.

Acceptance tests:

- After a multi-result Run Buffer, pressing `[` or `]` in Results changes the
  selected buffer result and active result.
- Pressing `[` or `]` in Sources, History, or SQL leaves the active result
  unchanged.
- Help/footer/docs describe `[` and `]` as Results-pane actions, not global
  actions.

### Export Confirmation Does Not Clear Results

F7 export completion should confirm through status text or a non-destructive
message that does not clear the visible result table and does not replace the
active result view.

Acceptance tests:

- Export a visible result and verify the result grid still contains the same
  rows afterward.
- Verify status names the exported path.
- Verify active result metadata remains the exported result.

### Confirmed Catalog Save

Sources `w` writes `.csvql.yml` only after confirmation. The prompt should name
the count and target path, for example:

`Save N source paths to .csvql.yml? Press y to save or n to cancel.`

Cancel means no file write. Confirm uses the existing project catalog save
behavior, later upgraded to atomic writes in P2.

Acceptance tests:

- Press `w` in Sources and verify a confirmation screen appears before any file
  is written.
- Cancel and verify no `.csvql.yml` is created or modified.
- Confirm and verify sources are written.
- Error paths still surface project catalog errors without hiding state.

### Active-Result Docs And Help

Docs/help must consistently use active-result language. Avoid stale wording such
as "last successful tabular result" when export/save actually use the selected
active result, including recalled History results and selected buffer results.

Help and prompt text must include `.markdown` as an accepted F7 suffix.

Acceptance tests:

- README, TUI guide, release notes, and help text mention active-result behavior.
- Stale "last successful tabular result" wording is absent where it conflicts
  with active-result behavior.
- Help and prompt text include `.markdown`.

## P1 Responsiveness And Discoverability

P1 turns "feels frozen" and "hidden target" issues into explicit contracts.

### Cancellable Workers

The following actions run in background workers:

- source inspect `i`
- source sample `s`
- source profile `p`
- source columns `c`
- export `F7`
- save active result as source `Ctrl+S`, `Alt+S`, or `F11`

While one of these workers is active, the TUI shows a busy status naming the
operation and target. Duplicate starts for the same operation should be ignored
or reported with a status message.

`Esc` cancels the active source/export/save worker when no modal owns `Esc`.
Cancellation is best-effort:

- If no final state has been committed, state remains unchanged.
- Any temp output owned by the cancelled operation is removed.
- Status reports the cancellation.
- If the operation already completed and committed state, completion wins and
  status says the operation completed.

Acceptance tests:

- Source intelligence actions start workers and show busy state.
- Export and save-as-source start workers and keep navigation responsive.
- Duplicate starts while a worker is active do not launch competing workers.
- `Esc` cancels an in-flight worker where cancellation is still possible.
- Cancelled export/save leaves no final file and does not alter active
  result/source state.
- Completion after a late cancel is reported as completion, not partial cancel.

### Buffer Result Discoverability

When a Run Buffer has multiple successful tabular outputs, the Results pane
shows that multiple outputs exist, which output is selected, and how to move
between them using `[` and `]`. The selected buffer output remains the active
result for export and save.

Acceptance tests:

- Multi-result buffer output shows a selector label such as `Result 1 of N`.
- Selecting another output updates the active result label.
- Footer/help/docs expose `[` and `]` only for Results focus.

### Minimum Terminal Size

The TUI declares a minimum usable terminal size and warns below it instead of
trying to build a compact mode in this follow-up.

Minimum usable size: 100 columns by 30 rows. Recommended comfortable size:
120 columns by 36 rows.

Below the minimum, the TUI should show an in-app warning such as:

`Terminal too small for full workbench; use at least 100x30.`

Acceptance tests:

- Simulated layout below 100x30 emits the warning.
- Simulated layout at or above 100x30 does not emit the warning.
- Docs name the minimum and recommended sizes.

## P2 Durability, Result Storage, And Path Policy

P2 makes the result and file-write model safer under larger outputs and
filesystem failure.

### Atomic User-Visible Writes

All user-visible writes in this follow-up use atomic write semantics:

- F7 exports
- derived CSV saves
- `.csvql.yml` catalog saves

The write contract:

1. Resolve the final output path according to existing rules.
2. Create a temp sibling file in the target directory.
3. Write the complete content.
4. Flush and close the temp file.
5. Replace the final path.
6. Remove temp output on failure or cancellation before replacement.

Existing overwrite semantics stay unchanged unless the current API already
rejects overwrite.

Acceptance tests:

- Export, derived CSV save, and catalog save replace final files only after the
  complete write succeeds.
- Simulated write failure leaves the previous final file intact.
- Cancellation before replacement leaves no partial final file.
- Temp files are cleaned up on failure and cancellation.

### Temp-Backed Result Store

Small tabular results may remain in memory. Large tabular results spill to a
session-owned temp artifact while preserving full-result export/save/history
semantics.

Automatic spill threshold:

- spill when row count is greater than 10,000, or
- spill when estimated cell count is greater than 250,000.

The threshold is internal for this follow-up. Do not add user config yet.

The Results grid still renders a bounded preview. Export, save-as-source, and
History recall use the result store to access the full active result. Temp
artifacts are cleaned up on normal TUI exit. Crash leftovers are best-effort
cleanup candidates, not durable user artifacts.

Acceptance tests:

- Results below threshold remain in memory.
- Results above row threshold spill to temp storage.
- Results above cell threshold spill to temp storage.
- Export/save from spilled results writes the full result, not only the preview.
- History recall from spilled results shows preview without losing full output.
- Normal TUI exit cleans up session temp artifacts.
- Preview labels make clear when the grid is showing a bounded preview.

### Warn-But-Allow Path Policy

External absolute paths and symlink-resolved paths outside the start directory
remain valid. This preserves local power-user workflows.

When saving `.csvql.yml`, the TUI warns if the catalog will persist external
paths. The warning should be clear that sharing the catalog may reveal
machine-specific local filesystem locations. The warning does not block the
save after confirmation.

Acceptance tests:

- Catalog save with only project-relative paths does not show an external path
  warning.
- Catalog save with an external absolute path shows a warning and still allows
  confirmation.
- Catalog save with a symlink resolving outside the start directory shows a
  warning and still allows confirmation.
- Docs describe catalog path privacy.

### Paste/Drop-Only CSV Path Ingestion

SQL-editor CSV path ingestion happens only from explicit paste or drop events.
Ordinary editor text changes do not trigger source ingestion.

Paste/drop still consumes the payload only when the entire pasted payload is one
or more standalone `.csv` paths. CSV-looking paths inside SQL strings, comments,
or expressions remain SQL text.

Acceptance tests:

- Pasting one standalone `.csv` path into the editor adds a session source.
- Pasting multiple standalone `.csv` paths adds session sources.
- Pasting SQL containing `.csv` inside strings, comments, or expressions leaves
  the text in the editor.
- Typing or programmatically changing editor text to a `.csv` path does not add
  a source until a paste/drop event occurs.

### History Preview Performance

History movement should not rebuild large previews on every row movement. The
TUI should reuse stored preview metadata or cached preview rows when available.

Repeated F4 runs may continue using fresh DuckDB sessions. That behavior is
intentional for statement runs. Run Buffer remains the shared-session path for a
semicolon-delimited batch.

Acceptance tests:

- Moving across History rows reuses stored preview state for large results.
- Recalled History preview does not trigger repeated full result materialization.
- Docs distinguish F4 fresh-session statement runs from shared-session Run
  Buffer runs.

## Data Flow

### Query Result Flow

1. Query worker returns a tabular result.
2. Result store decides memory versus temp spill using the automatic threshold.
3. Result store records full-result access plus bounded preview metadata.
4. TUI updates the active result label and Results grid preview.
5. Export/save/history recall use the result store reference, not a separate
   ad hoc copy of rows.

### Export And Save Flow

1. User requests export or save-as-source.
2. TUI prompts for path or alias.
3. Worker starts and status names the operation and target.
4. Worker reads full active result through result store.
5. File write service writes atomically through a temp sibling file.
6. Worker completion updates status and any source state.
7. Cancellation before final replacement cleans up temp output and leaves state
   unchanged.

### Catalog Save Flow

1. User presses `w` in Sources.
2. TUI builds a confirmation message naming source count and `.csvql.yml`.
3. If persisted paths include external absolute or symlink-resolved external
   paths, confirmation includes the privacy warning.
4. Confirm starts the catalog save path.
5. P2 implementation writes the catalog atomically.

## Error Handling

- Modal cancellation returns focus to the prior pane where practical.
- Worker errors surface as status/error messages without replacing active
  results or clearing visible output.
- Export/save/catalog failures preserve previous final files.
- Cancellation is best-effort and must report whether cancellation or completion
  won.
- Temp cleanup failures should be reported only when user-visible output is at
  risk; otherwise they can be best-effort diagnostics in tests/log-free state.
- External path warnings must avoid exposing unrelated path details beyond the
  source paths the user already supplied.

## Testing Strategy

Automated coverage should be phase-specific.

P0 tests:

- TUI action/focus tests for modal fencing.
- TUI tests for Results-only buffer navigation.
- Export tests confirming visible result table preservation.
- Workflow tests for confirmed catalog saves.
- Docs tests for active-result and `.markdown` wording.

P1 tests:

- Worker state tests for source intelligence, export, and save-as-source.
- Cancellation tests for worker lifecycle and temp cleanup.
- Duplicate worker start tests.
- Buffer selector discoverability tests.
- Minimum terminal size warning tests.

P2 tests:

- Unit tests for atomic write helpers.
- Export/catalog/derived-source tests for failure and cancellation behavior.
- Result-store tests for memory versus temp spill thresholds.
- TUI workflow tests for spilled-result export/save/history recall.
- Path warning tests for external absolute paths and symlink-resolved paths.
- Paste/drop ingestion tests that distinguish paste events from ordinary editor
  changes.

Docs tests should cover README, TUI guide, release notes, help text, and manual
QA wording when behavior changes affect public instructions.

## Verification Gates

Use repo-local `uv` commands. In this environment, set
`UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql`.

Expected verification sequence for implementation phases:

1. Focused tests for the changed phase.
2. `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff format --check .`
3. `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check .`
4. `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras mypy src`
5. Full `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest` when the phase touches shared TUI, result, export, or catalog behavior.
6. `git diff --check`.

Completion gates:

- P0 is complete only when the five adversarial correctness findings are fixed
  and regression-tested.
- P1 is complete only when long-running TUI actions are cancellable workers and
  discoverability docs are aligned.
- P2 is complete only when atomic writes, temp-backed results, path warnings,
  and paste/drop-only ingestion have tests.

None of these gates change version, publish state, release label, tag state,
remote state, or `v1-stable` status.

## Manual QA Impact

This design updates what manual TUI QA should eventually check, but it does not
execute manual QA or release-candidate proof.

Manual QA should not restart until P0 is complete. Later matrix updates should
cover:

- modal action fencing
- confirmed source catalog saves
- Results-only buffer navigation
- cancellable source/export/save workers
- minimum terminal size warning
- atomic write failure behavior where manually practical
- large-result preview versus full export/save behavior
- external path warnings
- paste/drop-only CSV path ingestion

## Implementation Boundaries

Keep edits scoped to TUI behavior, result/export/catalog helpers, docs, and
tests needed for the phased repair. Do not add dependencies or change lockfiles
unless a later implementation plan proves it is necessary and receives separate
approval.

Do not broaden user-facing claims. In particular, do not describe temp-backed
results as a hidden cache or automatic materialization feature. They are an
internal session storage detail used to preserve full-result behavior while
reducing memory pressure.
