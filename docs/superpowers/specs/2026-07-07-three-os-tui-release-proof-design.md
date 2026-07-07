# Three-OS TUI Release Proof Design

## Status

Approved design pending written-spec review.

This design defines the next release-proof lane for LocalQL TUI quality across
the three supported OS families: macOS, Windows, and Linux. It is a proof-gate
design, not a release action.

## Context

LocalQL is the installable distribution name. The runtime contract remains the
`csvql` CLI, the `csvql` Python import package, `.csvql.yml` project config,
and the `csvql menu` TUI command.

Current `main` proof base:

- `fb52ebb test: format v1 polish docs coverage`
- latest proof inventory: `output/release-proof-inventory-20260707-fb52ebb/`
- classification: `v1-hardening`
- automated proof is available after rerun
- release-readiness and package audit passed after approved network escalation
- benchmark proof passed
- unsupported-claim scan found guardrails and non-claims only
- manual v1 QA and the full TUI terminal matrix remain incomplete

The previous broad TUI terminal matrix listed macOS Terminal, iTerm2, VS Code
terminal, Linux terminal, Windows Terminal, and tmux/SSH. That is now too broad
for this release lane. VS Code exposed host-key and Option-key behavior that is
not worth solving before release. iTerm2 and tmux/SSH are not release-blocking
for this target. The user-selected release target is macOS, Windows, and Linux.

## Goals

- Define release-proof terminal coverage as macOS Terminal, Windows Terminal,
  and one normal Linux terminal.
- Require the full TUI QoL behavior matrix on each of those three OS terminal
  rows.
- Keep VS Code integrated terminal, iTerm2, and tmux/SSH explicitly out of
  scope for this release lane.
- Use automated proof to support, not replace, real terminal evidence.
- Keep all proof tied to the same candidate `HEAD`.
- Preserve product and release boundaries: no tag, publish, upload, version
  change, remote configuration, or release-status claim.
- Keep status in `v1-hardening` until the three required terminal rows pass
  with media evidence and all release-readiness requirements are satisfied.

## Non-Goals

- No VS Code keybinding fallback work.
- No iTerm2-specific repair.
- No tmux/SSH compatibility work.
- No terminal mocking as a substitute for real terminal evidence.
- No web UI, cloud connector, NLP execution, dataframe-first API, plugin
  system, hidden cache/materialization, or broader platform scope.
- No claims of sandbox safety, safe untrusted SQL, security isolation,
  production readiness, broad large-file proof, `release-candidate eligible`,
  `release-candidate`, or `v1-stable`.
- No PyPI publish, GitHub release, artifact upload, tag, push, remote
  configuration, or package version change.

## Platform Scope

Required release-proof rows:

| OS family | Required terminal row | Evidence directory |
| --- | --- | --- |
| macOS | macOS Terminal | `output/tui-qol-qa/<run-id>/macos-terminal/` |
| Windows | Windows Terminal | `output/tui-qol-qa/<run-id>/windows-terminal/` |
| Linux | GNOME Terminal or an equivalent normal desktop terminal | `output/tui-qol-qa/<run-id>/linux-terminal/` |

Out-of-scope rows for this release lane:

- VS Code integrated terminal
- iTerm2
- tmux/SSH

Out-of-scope does not mean unsupported forever. It means those terminal hosts do
not block this release proof lane and must not be used to claim failure or pass
status for the macOS/Windows/Linux target.

## Proof Model

The proof model has two layers.

### Automated Support Proof

Automated proof should cover what automation can honestly prove:

- format, lint, type check, and full pytest
- release-readiness script
- package-content audit
- benchmark proof
- unsupported-claim scan
- deterministic TUI behavior through pytest/Textual tests
- optional tracked CI expansion to run the automated gate on macOS, Windows,
  and Linux runners if the implementation plan chooses to update CI

Automation does not prove real terminal compatibility. It cannot replace manual
evidence for function-key delivery, host-terminal key interception, native file
picker behavior, actual rendering, or resize ergonomics.

### Manual Real-Terminal Proof

Manual proof is required for each of the three required terminal rows. Each row
must run the full TUI QoL behavior matrix from `docs/tui-qol-qa.md` unless the
implementation plan deliberately rewrites that matrix with a reviewed tracked
docs change.

Each row must record:

- date
- candidate commit SHA
- tester or outside observer
- OS name and version
- terminal name and version
- viewport size range tested
- pass/fail for every TUI QoL flow
- blocker notes
- media artifact paths

Screenshots or recordings live under ignored `output/tui-qol-qa/<run-id>/...`
paths. They are local proof artifacts and are not committed unless a separate
tracked-artifact decision is made.

## Windows And Linux Evidence Collection

Windows and Linux evidence may come from either:

- an actual Windows or Linux environment the user provides later, or
- an outside observer who follows the exact checklist and returns the required
  notes plus media artifacts.

The result packet must say which source was used. If outside-observer evidence
is used, the packet must identify the observer label, OS, terminal, viewport
range, media path, and any deviations from the checklist. Do not silently treat
secondhand evidence as locally reproduced proof.

## Documentation Changes Expected In Implementation

The implementation plan should update tracked docs and guards so release
authority matches this design:

- `docs/tui-qol-qa.md` should list only macOS Terminal, Windows Terminal, and
  Linux terminal as required release rows for this lane.
- `docs/tui-qol-qa.md` should mark VS Code, iTerm2, and tmux/SSH as out of
  scope for this release lane.
- `docs/v1-manual-qa.md`, `docs/release-readiness.md`, and
  `docs/release-notes/v1.md` should stop saying the release-blocking TUI gate
  requires the older six-row matrix.
- `tests/test_v1_polish_docs.py` should guard the new three-OS requirement and
  the out-of-scope rows.

The implementation plan may also update `.github/workflows/ci.yml` to add
macOS and Windows automated gate jobs. CI expansion supports cross-OS runtime
confidence, but real terminal media evidence remains required.

## Result Packet

The execution lane should create one ignored proof root:

```text
output/tui-qol-qa/<run-id>/
```

Expected contents:

- `RESULT.md`: overall TUI QoL result and classification.
- `macos-terminal/`: macOS Terminal notes and media.
- `windows-terminal/`: Windows Terminal notes and media.
- `linux-terminal/`: Linux terminal notes and media.
- optional `commands/`: command outputs for setup or automated support checks.

`RESULT.md` must include:

- run id
- candidate commit SHA
- final status: `pass`, `fail`, or `blocked`
- tester and outside-observer labels
- per-platform terminal table
- per-flow matrix for all required TUI QoL flows
- media paths
- blockers
- explicit statement that VS Code, iTerm2, and tmux/SSH were out of scope
- explicit statement that no tag, publish, upload, version change, or release
  action occurred

## Classification Rules

- `pass`: all three required terminal rows pass every required flow with media
  evidence on the same candidate `HEAD`.
- `fail`: a required terminal row runs and a flow fails.
- `blocked`: any required terminal row is missing, untested, lacks media, lacks
  commit identity, or cannot be trusted as same-`HEAD` evidence.

Release readiness remains `v1-hardening` unless this TUI proof passes and every
other documented release-readiness prerequisite is also satisfied on the same
candidate `HEAD`.

## Error Handling

If a platform row fails:

- record the exact flow id
- record the terminal and OS
- record the key/action attempted
- record expected and observed behavior
- keep media evidence
- do not silently replace the terminal row with a different terminal
- do not change keybindings or docs promises without a new design review

If a platform row cannot be run:

- classify the TUI result as `blocked`
- record why it could not be run
- record what evidence would unblock it

If automated support proof contradicts manual evidence, stop and debug before
changing the release gate. Manual terminal behavior is the authority for real
terminal compatibility; automated tests are the authority for deterministic app
behavior inside the test harness.

## Skill Activation Contract

Implementation must not start until the implementation lane loads the required
skills for the files and behavior being touched.

- Before creating the implementation plan, use `superpowers:writing-plans`.
- Before editing user-facing docs, use `documentation`.
- Before editing `src/csvql/**/*.py`, `tests/**/*.py`, package metadata, typing,
  CLI/TUI behavior, or dependency surfaces, use `python-codebase-standards`.
- If keybinding, terminal evidence, or TUI timing behavior contradicts
  assumptions, stop and use `superpowers:systematic-debugging` before changing
  approach.
- Before claiming completion, use `superpowers:verification-before-completion`
  or `verification-before-completion`.
- This lane should not touch SQL execution semantics, DuckDB behavior, schemas,
  migrations, validation SQL, or database contracts. If it does, stop and use
  `postgresql-database-standards` before proceeding.

## Acceptance Criteria

- A tracked spec and implementation plan define the three-OS TUI release proof
  lane.
- Tracked docs define macOS Terminal, Windows Terminal, and Linux terminal as
  the release-blocking TUI evidence rows for this lane.
- Tracked docs mark VS Code, iTerm2, and tmux/SSH out of scope for this release
  lane.
- Focused docs tests guard the new platform scope and prevent accidental claims
  that mocks or CI replace real terminal evidence.
- Optional CI expansion, if implemented, supports cross-OS automated proof but
  does not replace manual terminal media evidence.
- The final TUI QoL result packet records all three required terminal rows,
  media paths, pass/fail status, and blockers.
- No release action, tag, push, upload, remote configuration, version change, or
  publish action is performed.

## Verification

The implementation plan should verify tracked docs/test changes with:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py -q
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check .
git diff --check
```

If CI workflow files change, review the workflow diff manually and run the local
gate available on the current machine. Do not claim GitHub-hosted macOS or
Windows CI passed unless those jobs actually ran and their outputs are cited.

The execution lane should verify ignored proof artifacts with:

```bash
test -f output/tui-qol-qa/<run-id>/RESULT.md
git status --short --branch
git tag --points-at HEAD
git remote -v
```

## Risks And Mitigations

- Mock overclaim risk: mitigate by stating that Textual tests and CI do not
  replace real terminal media evidence.
- Windows/Linux access risk: mitigate by allowing either user-provided
  environments or outside observers, while requiring the evidence source to be
  named.
- Keybinding divergence risk: mitigate by recording exact key/action behavior
  per platform and stopping for design review before changing key promises.
- Evidence consistency risk: mitigate with one run id, fixed result template,
  per-flow pass/fail entries, and media paths.
- Release overclaim risk: mitigate by keeping status in `v1-hardening` until
  the three OS terminal rows and every other release-readiness prerequisite pass
  on the same `HEAD`.
