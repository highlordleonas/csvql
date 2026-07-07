# TUI QoL Scope Closeout Design

## Status

Approved direction pending written-spec review.

This design closes the VS Code keybinding fallback lane and turns the remaining
work into a narrow documentation and guard-test closeout. It does not authorize
runtime behavior changes.

## Context

LocalQL is the installable distribution name. The runtime contract remains the
`csvql` CLI, the `csvql` Python import package, `.csvql.yml` project config,
and the `csvql menu` TUI command.

The previous VS Code fallback design attempted to add `Alt+H`, `Alt+R`, and
`Alt+U` as integrated-terminal-friendly alternatives for Help, Results, and
Sources. The pre-churn manual gate failed on 2026-07-07: in default isolated
VS Code integrated terminal settings on macOS, `Alt+H` inserted the macOS
Option-H dot glyph into the SQL editor instead of opening Help. The spike code
and tests were reverted. No implementation commit was created, and help,
footer, and public docs were not changed.

The current local evidence remains:

- macOS Terminal row passed in the earlier TUI QoL run.
- VS Code integrated terminal exposed key interception and Option-key behavior
  that makes it unsuitable for this fallback lane.
- iTerm2 and tmux were not locally available.
- Linux and Windows rows were not run locally.

This closeout keeps the work aligned with the product goal: a local-first
Python CLI/TUI for querying local CSV files through DuckDB. It avoids broad
terminal-platform work, new keymaps, plugin systems, web UI, cloud features,
release actions, and new security claims.

## Goals

- Close the VS Code-specific fallback plan so it is not accidentally executed.
- Make `docs/tui-qol-qa.md` distinguish verified macOS Terminal evidence from
  known VS Code limitations and unverified terminal rows.
- Keep release-status language honest: macOS Terminal evidence alone does not
  establish `release-candidate eligible`, `release-candidate`, or `v1-stable`.
- Add focused docs tests that fail if public docs claim VS Code support,
  cross-terminal pass status, or release eligibility without evidence.
- Preserve existing runtime behavior, keybindings, help text, footer labels,
  SQL execution semantics, DuckDB behavior, and package metadata.

## Non-Goals

- No new keybindings.
- No user-configurable keymap.
- No VS Code terminal workaround.
- No manual screenshot rerun.
- No release-candidate eligibility proof.
- No tag, PyPI upload, GitHub release, artifact upload, version change, push,
  or remote configuration.
- No claims of sandbox safety, safe untrusted SQL, production readiness, or
  broad large-file proof.

## Documentation Design

`docs/superpowers/specs/2026-07-07-vscode-alt-keybinding-fallback-design.md`
: Keep as a historical record, but its status must clearly say the design is
  superseded and must not be implemented unless a new design review reopens
  terminal compatibility work.

`docs/superpowers/plans/2026-07-07-vscode-alt-keybinding-fallback.md`
: Keep as a historical record, but its status must clearly say the plan is
  closed and must not be executed.

`docs/tui-qol-qa.md`
: Add a current closeout/status section near the top:
  - macOS Terminal is the verified local pass row for this TUI QoL lane.
  - VS Code integrated terminal is out of scope for this closeout and has a
    recorded keybinding failure.
  - iTerm2, Linux, Windows Terminal, and tmux/SSH remain unverified or blocked
    unless outside observer evidence is added later.
  - This closeout does not make the project `release-candidate eligible`.

Release authority docs
: Update only if needed to avoid overclaiming. The intended language is that the
  current closeout records local TUI QoL evidence and residual terminal gaps; it
  does not satisfy any release-candidate eligibility requirement that still
  depends on a complete terminal matrix.

Public user docs
: Do not add VS Code fallback instructions or `Alt+H`, `Alt+R`, `Alt+U`
  shortcut promises. Public docs should keep the current function-key behavior
  and existing fallback wording that is already proven.

## Guard-Test Design

Use `tests/test_v1_polish_docs.py` for guard tests because it already owns
public docs and release-status claim checks.

Add or revise focused tests so they prove:

- `docs/tui-qol-qa.md` contains the current closeout status and names macOS
  Terminal as the verified local row.
- `docs/tui-qol-qa.md` records VS Code integrated terminal as out of scope for
  this closeout and as a known failed row from the 2026-07-07 spike.
- Public docs do not advertise `Alt+H`, `Alt+R`, `Alt+U`, or
  VS Code-friendly TUI key fallbacks.
- Release/readiness docs do not claim the TUI QoL closeout by itself is
  `release-candidate eligible`, `release-candidate`, or `v1-stable`.
- The closed VS Code fallback spec and plan remain marked closed/superseded.

The tests should be text guards only. They should not invoke Textual, launch a
terminal, create screenshots, or inspect ignored `output/` artifacts.

## Acceptance Criteria

- The VS Code fallback spec and plan are clearly closed historical records.
- `docs/tui-qol-qa.md` separates local macOS Terminal evidence, known VS Code
  limitation, and unverified outside terminal rows.
- Public docs do not promise the rejected Alt fallback layer.
- Release docs do not imply the current TUI QoL closeout is release eligibility.
- Focused docs tests cover those claim boundaries.
- No runtime files are changed.
- No release action, tag, version change, push, remote configuration, or upload
  is performed.

## Verification

Use repo-local `uv` with the established cache path:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py -q
git diff --check
```

Run broader checks only if the implementation touches files outside the docs
and docs-test scope, which this design does not expect.

## Risks And Mitigations

- Overclaim risk: mitigated by explicit closeout wording and docs guards.
- Release-status risk: mitigated by retaining the distinction between local
  evidence, terminal matrix gaps, and release eligibility.
- Future-agent drift: mitigated by closing the stale VS Code plan and adding
  tests against public fallback claims.
- Scope creep: mitigated by forbidding runtime keybinding, footer, help, and
  manual GUI work in this closeout lane.
