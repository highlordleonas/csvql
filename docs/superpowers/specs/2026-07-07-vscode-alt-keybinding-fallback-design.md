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
- Let users reach Help, Results, Sources, and buffer-result navigation from the
  SQL editor without typing characters into the editor.
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
| Previous buffer result | `[` | `Alt+[` |
| Next buffer result | `]` | `Alt+]` |

`Alt+S` is intentionally not used for Sources because it already saves the
active result as a derived source. Plain printable letters are intentionally not
used for these global fallbacks because they would type into the SQL editor.

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

Docs should describe Alt bindings as fallbacks for terminals that intercept
function keys, not as a replacement keymap.

## Error Handling And Gating

The Alt fallbacks call existing actions, so behavior should match the current
function-key and bracket behavior:

- Help remains one modal at a time.
- Results and Sources focus actions remain global except when a prompt or
  confirmation modal blocks app actions.
- `Alt+[` and `Alt+]` select buffer results only when Results is focused.
- `Alt+[` and `Alt+]` do nothing from SQL, Sources, or History.
- Operation-running restrictions for export/save/source inspection remain
  unchanged.

## Verification Plan

Focused automated checks:

- TUI binding test showing `Alt+H`, `Alt+R`, and `Alt+U` work from the SQL editor.
- TUI binding test showing `Alt+[` and `Alt+]` move buffer results only when
  Results is focused.
- Footer test updated for compact combined labels.
- Help text test updated for the Alt fallback layer.
- Docs tests updated for README, getting-started, TUI guide, troubleshooting,
  and TUI QoL QA wording.

Broader automated checks should use the repo-local `uv` workflow with
`UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql`, starting with focused tests
and widening only after they pass.

Manual evidence after implementation:

- Refresh macOS Terminal evidence to confirm existing function keys still work.
- Refresh VS Code integrated terminal evidence to confirm Alt fallbacks reach the
  TUI for Help, Results, Sources, and buffer-result navigation.
- Keep evidence under the ignored TUI QoL QA output run directory, using a new
  run id if HEAD changes.

## Acceptance Criteria

- Existing function-key behavior remains available.
- VS Code-friendly Alt fallbacks are documented and tested.
- The SQL editor can reach Help, Results, Sources, and buffer-result navigation
  without relying on function keys or printable global letters.
- No release-candidate, publish, version, tag, remote, or broad security claim is
  introduced.
