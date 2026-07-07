# VS Code Alt Keybinding Fallback Design

## Status

Approved design for a narrow TUI keybinding repair. This document specifies the
intended behavior, implementation boundaries, acceptance tests, and verification
path. Implementation planning and code changes are separate follow-up work.

## Context

LocalQL is the installable distribution name. The runtime contract remains the
`csvql` CLI, the `csvql` Python import package, `.csvql.yml` project config,
and the `csvql menu` TUI command.

The current TUI function-key map works in macOS Terminal, but VS Code integrated
terminal evidence shows several keys are intercepted before they reach Textual:
`F1` opens the VS Code command palette, `F5` opens VS Code UI, `F6` does not
focus Sources, and `Ctrl+Up` can be captured by the OS. The SQL editor is the
default focused pane, so fallbacks must work from text entry without inserting
printable characters into SQL.

This design stays within TUI QoL and terminal compatibility. It does not
authorize release-candidate eligibility claims, version changes, tags, remotes,
publishing, artifact uploads, broader platform scope, or new security claims.
User-authored SQL remains trusted local DuckDB SQL.

## Goals

- Preserve all existing function-key bindings for terminals where they work.
- Add discoverable, non-printing fallbacks for VS Code integrated terminal.
- Let users reach Help, Results, and Sources from the SQL editor without typing
  characters into the editor.
- Let users move from the SQL editor to Results with `Alt+R`, then use existing
  `[` and `]` for Results-only buffer-result navigation when they work there.
- Keep modal, focus, and action-gating behavior unchanged.
- Update visible help, footer, and docs so the fallback path is discoverable.
- Add focused automated coverage before refreshing manual terminal evidence.

## Non-Goals

- No replacement of the existing function-key map.
- No user-configurable keymap.
- No command palette redesign.
- No new panes, workflow changes, or release proof scope.
- No claim that Alt keys work in every terminal; terminal-specific behavior
  remains manual QA evidence.

## Keybinding Design

Existing bindings remain primary. Add an Alt fallback layer for the keys blocked
in VS Code integrated terminal:

| Action | Existing binding | New fallback |
| --- | --- | --- |
| Help | `F1` | `Alt+H` |
| Focus Results | `F5` | `Alt+R` |
| Focus Sources | `F6` / `Ctrl+Up` | `Alt+U` |

`Alt+S` is intentionally not used for Sources because it already saves the
active result as a derived source. Plain printable letters are intentionally not
used for these global fallbacks because they would type into the SQL editor.

Buffer-result navigation should stay on the existing Results-only `[` and `]`
bindings unless the reachability gate proves they are insufficient after
`Alt+R` focuses Results. Before adding `Alt+[` or `Alt+]`, prove existing
bracket navigation after `Alt+R` is insufficient. This YAGNI checkpoint prevents
unnecessary keybindings, docs churn, tests, footer/help complexity, and manual
evidence burden.

## Pre-Churn Reachability Gate

Before broad code or docs churn, prove the selected Alt bindings can actually
reach the TUI:

- Automated Textual proof: use the repo's focused TUI test harness to prove
  Textual accepts and dispatches the selected binding names.
- Manual VS Code proof: use the same isolated VS Code profile and default
  settings as the failing evidence to prove VS Code integrated terminal emits
  those keys to the TUI.
- Buffer navigation proof: first test `Alt+R` into Results, then plain `[` and
  `]` in an actual multi-result Results state. Add Alt bracket fallbacks only if
  plain brackets are still unreachable or unreliable after `Alt+R`.

The spike may use the smallest temporary or partial binding needed to observe
Textual and terminal behavior. It must not update README, docs, help text,
footer labels, or other user-facing shortcut promises until the reachability
gate passes.

If any selected Alt binding fails, revert the temporary probe or otherwise leave
no user-facing shortcut/docs/footer churn, then stop implementation and return
to design review before choosing replacement keys.

Temporary probe code must not be committed unless it becomes the final
implementation and passes the normal test path for this lane.

## Implementation Surfaces

`src/csvql/tui_app.py`
: Extend `CSVQLMenuApp.BINDINGS` for the selected actions. The existing action
  methods remain unchanged. `check_action()` continues to enforce modal
  blocking, Results-only buffer navigation, and pane-specific printable source
  and history actions.

`src/csvql/tui_help.py`
: Document the Alt fallback layer in the in-app help text.

User docs
: Update README, getting-started, TUI guide, troubleshooting, and TUI QoL QA
  wording so users see the function keys first and the Alt fallback path as the
  VS Code/terminal compatibility route.

Tests
: Update focused TUI and docs tests for binding behavior, footer/help wording,
  and documentation guards.

## Footer And Help Wording

Footer labels should remain compact. Combined labels are appropriate where the
footer already shows the blocked action:

- `F1/Alt+H` for Help
- `F5/Alt+R` for Results
- `F6/Alt+U` for Sources

Buffer-result fallbacks should be documented in help, docs, and the buffer tab
title text rather than added to the footer, because `[` and `]` are hidden
Results-only actions today and the footer is already space constrained.

Footer order should remain stable by pane. Automated tests should assert exact
footer entries and order for the primary panes, and manual evidence should
include normal-size and terminal-too-small views so compact labels do not crowd
or hide the resize warning.

Because the footer advertises Alt shortcuts globally, manual terminal evidence
must prove the advertised Alt shortcuts in macOS Terminal as well as VS Code
integrated terminal. macOS Terminal evidence should use default Terminal
settings unless this spec explicitly records a different setting. If a terminal
cannot emit an advertised Alt shortcut, return to design review before deciding
whether to remove that shortcut from the footer or choose a replacement.

Docs should describe Alt bindings as fallbacks for terminals that intercept
function keys, not as a replacement keymap.

## Skill Activation Contract

Implementation must not start until the implementation lane loads the required
skills for the files and behavior being touched.

- Before creating the implementation plan, use `superpowers:writing-plans`.
- Before editing README or docs guidance, use `documentation`.
- Before editing `src/csvql/**/*.py`, `tests/**/*.py`, package metadata, typing,
  CLI/TUI behavior, or dependency surfaces, use `python-codebase-standards`.
- If keybinding behavior fails unexpectedly or terminal evidence contradicts
  assumptions, stop and use `superpowers:systematic-debugging` before changing
  approach.
- Before claiming completion, use `superpowers:verification-before-completion`
  or `verification-before-completion`.
- This lane should not touch SQL execution semantics, DuckDB behavior, schemas,
  migrations, validation SQL, or database contracts. If it does, stop and use
  `postgresql-database-standards` before proceeding.

## Error Handling And Gating

The Alt fallbacks call existing actions, so behavior should match the current
function-key and bracket behavior:

- Help remains one modal at a time.
- Results and Sources focus actions remain global except when a prompt or
  confirmation modal blocks app actions.
- `[` and `]` select buffer results only when Results is focused.
- `[` and `]` do nothing from SQL, Sources, or History.
- If the YAGNI checkpoint authorizes `Alt+[` and `Alt+]`, they must follow the
  same Results-only gating as `[` and `]`.
- Prompt and confirmation modals block the Alt fallbacks anywhere the matching
  existing actions are already blocked.
- Minimum modal-negative coverage includes one prompt modal and one confirmation
  modal. Each must block at least one global focus action. Across those tests,
  cover Help, Results or Sources focus, and buffer navigation.
- Operation-running restrictions for export/save/source inspection remain
  unchanged.

## Verification Plan

Focused automated checks:

- Spike implementation gate proving Textual accepts and dispatches the selected
  key names through the repo's focused TUI test harness before user-facing
  shortcut wording changes.
- TUI binding test showing `Alt+H`, `Alt+R`, and `Alt+U` work from the SQL editor.
- YAGNI checkpoint proving existing `[` and `]` move buffer results after
  `Alt+R` focuses Results in an actual multi-result Run Buffer state. Add
  `Alt+[` and `Alt+]` tests only if that proof fails and design review approves
  the fallback.
- Modal-negative TUI tests showing prompts and confirmations still block the Alt
  fallbacks where they block the matching existing actions, covering at least
  one prompt modal, one confirmation modal, Help, Results or Sources focus, and
  buffer navigation.
- Footer test updated for compact combined labels, exact pane order, and visible
  entries within the expected terminal sizes.
- Help text test updated for the Alt fallback layer.
- Docs tests updated for README, getting-started, TUI guide, troubleshooting,
  and TUI QoL QA wording.

Broader automated checks should use the repo-local `uv` workflow with
`UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql`, starting with focused tests
and widening only after they pass.

Post-implementation manual evidence:

- Refresh macOS Terminal evidence with default Terminal settings to confirm
  existing function keys and the advertised Alt fallbacks still work.
- Refresh VS Code integrated terminal evidence to confirm Alt fallbacks reach the
  TUI for Help, Results, and Sources, then confirm buffer-result navigation from
  Results with plain brackets or an approved conditional fallback.
- Buffer-result navigation evidence must use an actual multi-result Run Buffer
  state, not an empty or no-op state.
- Use a new ignored TUI QoL QA output run id for the post-implementation HEAD.

## Acceptance Criteria

- Existing function-key behavior remains available.
- VS Code-friendly Alt fallbacks are documented and tested.
- The SQL editor can reach Help, Results, and Sources without relying on
  function keys or printable global letters.
- Buffer-result navigation remains Results-only, with `Alt+R` as the path from
  the SQL editor into Results before existing `[` or `]`.
- `Alt+[` and `Alt+]` are added only if existing `[` and `]` are proven
  insufficient after `Alt+R` focuses Results.
- Footer labels stay compact, ordered by pane, and manually legible in normal
  and too-small terminal evidence.
- Advertised footer Alt shortcuts have macOS Terminal and VS Code integrated
  terminal evidence before they remain in footer labels.
- Prompt and confirmation modals continue to block the Alt fallbacks where they
  block the matching existing actions.
- No release-candidate, publish, version, tag, remote, or broad security claim is
  introduced.
