# Three-OS TUI Release Proof Design

## Status

Approved design pending implementation and proof-execution planning.

This status records explicit parent approval on 2026-07-07. Implementation and
proof-execution planning remain gated by the Skill Activation Contract below.

This design defines the next release-proof lane for LocalQL TUI quality across
the three target OS families: macOS, Windows, and Linux. It is a proof-gate
design, not a release action or support claim.

## Context

LocalQL is the installable distribution name. The runtime contract remains the
`csvql` CLI, the `csvql` Python import package, `.csvql.yml` project config,
and the `csvql menu` TUI command.

Prior proof history at the time this design was created:

- `fb52ebb test: format v1 polish docs coverage`
- latest proof inventory: `output/release-proof-inventory-20260707-fb52ebb/`
- classification: `v1-hardening`
- automated proof is available after rerun
- release-readiness and package audit passed after approved network escalation
- benchmark proof passed
- unsupported-claim scan found guardrails and non-claims only
- manual v1 QA and the full TUI terminal matrix remain incomplete

This history is not a substitute for live repo truth. Any implementation or
proof-execution lane must re-baseline from the current live `HEAD` before
making proof claims:

- `pwd -P`
- `git status --short --branch`
- `git log -1 --oneline`
- `git remote -v`
- `git tag --points-at HEAD`

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
- Require same-`HEAD` automated support proof for macOS, Windows, and Linux
  before the final proof result can pass.
- Keep all proof tied to the same candidate `HEAD`.
- Preserve product and release boundaries: no tag, publish, release artifact
  upload, version change, remote configuration, or release-status claim.
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
- No PyPI publish, GitHub release, release artifact upload, tag, push, remote
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

The Windows row must use a native Windows environment and native Windows
Python/`uv` setup. A Windows Terminal tab running WSL counts as Linux/WSL
evidence, not Windows evidence, unless a separate design review explicitly
approves a different classification before proof execution.

The Linux row must use a real desktop terminal emulator, not an IDE-integrated
terminal, CI pseudo-terminal, browser shell, SSH-only session, or terminal
multiplexer. GNOME Terminal is preferred. Konsole, Xfce Terminal, xterm, or
another normal locally displayed Linux desktop terminal is acceptable only if
the evidence names the terminal and version.

## Proof Model

The proof model has two layers.

### Automated Support Proof

Automated proof should cover what automation can honestly prove:

- format, lint, type check, and full pytest
- release-readiness script on the candidate `HEAD`
- package-content audit on the candidate `HEAD`
- benchmark proof on the candidate `HEAD`
- unsupported-claim scan on the candidate `HEAD`
- deterministic TUI behavior through pytest/Textual tests
- three-OS automated support proof for macOS, Windows, and Linux before any
  future candidate-eligibility claim

Automation does not prove real terminal compatibility. It cannot replace manual
evidence for function-key delivery, host-terminal key interception, native file
picker behavior, actual rendering, or resize ergonomics.

Hosted GitHub CI expansion is optional; the required support proof may come
from hosted CI or equivalent runner output captured for all three OS families.
Claims about hosted CI passing require actual cited job outputs. This design
does not approve a push, remote configuration, or workflow run by itself. If CI
workflow edits are needed, they must be tracked docs/code changes in the
implementation plan, and any remote push or hosted run requires separate
explicit approval.

Minimum three-OS automated support proof:

- one run on macOS, one run on native Windows, and one run on Linux
- Python 3.12 on each OS, matching a supported project classifier and avoiding
  a full cross-product matrix for this lane
- dependency setup through `uv sync --all-extras --frozen`
- exact dependency install command, output path, and exit status recorded
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run --all-extras mypy src`
- `uv run --all-extras pytest`
- baseline truth transcript for that automated proof source, including
  `uv --version`, `uv run python --version`, and
  `uv run --all-extras csvql --version`

Any dependency install command other than `uv sync --all-extras --frozen` is a
deviation. The evidence packet must record the exact command, reason,
environment constraint, and why the output is still comparable.

Python 3.11 remains supported by project metadata and existing CI intent, but
this lane does not require a Python 3.11 by OS-family matrix unless a later
implementation or CI plan explicitly broadens the automated gate.

Release-readiness proof, package-content audit, benchmark proof, and
unsupported-claim scans remain required same-`HEAD` release-readiness evidence,
but they do not need to run on all three OS families for this lane unless a
later approved plan explicitly broadens them. They also do not replace the
three-OS automated support proof above.

Equivalent runner output must identify the OS name/version, runner or machine
source, shell, Python version, `uv` version, `uv` setup path, source access
method, commit verification command, exact dependency install command, exact
commands run, exit statuses, and output or transcript paths. Unlabeled local
notes are not equivalent runner output.

Three-OS automated support proof is a required gate for the final proof result,
not optional background evidence. If it is missing, stale, or not tied to the
same candidate `HEAD`, the final result is `blocked` even if the manual terminal
rows pass.

### Manual Real-Terminal Proof

Manual proof is required for each of the three required terminal rows. Each row
must run the full TUI QoL behavior matrix from `docs/tui-qol-qa.md`.

Reducing required terminal rows, reducing required flows, or changing pass/fail
rules is not an implementation-plan detail. It requires explicit design review
and user approval before execution.

Terminal proof should use default terminal settings. A non-default setting is
allowed only when explicitly approved before the run and recorded as a
deviation in the result packet.

Each row must record:

- date
- candidate commit SHA
- tester or outside observer
- OS name and version
- terminal name and version
- shell name and version
- whether terminal settings are default or non-default
- relevant locale or encoding settings if they may affect rendering or keyboard
  behavior
- Python and `uv` setup path used for the run
- viewport size range tested
- pass/fail for every TUI QoL flow
- blocker notes
- media artifact paths
- deviations from the checklist, if any

Screenshots or recordings live under ignored `output/tui-qol-qa/<run-id>/...`
paths. They are local proof artifacts and are not committed unless a separate
tracked-artifact decision is made.

## Pre-Proof Execution Gate

Proof execution must not start until tracked authority docs and guard tests
reflect the approved three-OS scope and automated proof requirements. At
minimum, `docs/tui-qol-qa.md`, `docs/v1-manual-qa.md`,
`docs/release-readiness.md`, `docs/release-notes/v1.md`, and
`tests/test_v1_polish_docs.py` must agree with this design before any manual
terminal proof, observer collection, or automated support proof is treated as
release-proof evidence.

If tracked docs still require the older six-row matrix, classify the execution
lane as not started or `blocked`; do not run around the authority mismatch.

## Windows And Linux Evidence Collection

Windows and Linux evidence may come from either:

- an actual Windows or Linux environment the user provides later, or
- an outside observer who follows the exact checklist and returns the required
  notes plus media artifacts.

The result packet must say which source was used. If outside-observer evidence
is used, the packet must identify the observer label, OS, terminal, viewport
range, media path, and any deviations from the checklist. Do not silently treat
secondhand evidence as locally reproduced proof.

## Candidate Source Access Contract

Every manual terminal row and automated support proof source must run the exact
candidate `HEAD`. This design does not approve pushing, configuring remotes,
uploading release artifacts, publishing packages, or creating release
artifacts.

An observer or automated runner may obtain the candidate source only through an
already-approved access path, such as:

- a pre-existing repository checkout that can be verified at the target commit
- a user-provided local or external transfer path approved outside this lane
- another explicit source-access path approved by the user before evidence
  collection

The evidence packet must record:

- source access method
- candidate commit SHA
- command used to verify the commit
- whether the working tree was clean before the run
- any archive name, checksum, or transfer identifier if a user-approved archive
  or transfer was used

If no approved source access path exists for a required platform row or
automated support proof source, that evidence item is `blocked`. Do not infer
Windows or Linux evidence from macOS proof, CI output, or an unverified source
copy.

Source and evidence transfer for observer collection is allowed only through an
explicit user-approved path recorded in the evidence packet. That transfer is
not a release artifact upload and must not be used to publish or distribute a
release package.

## Baseline Truth Transcript

Every manual platform row and automated platform proof must include a transcript
path or embedded transcript that records:

- `pwd -P`
- `git status --short --branch`
- `git log -1 --oneline`
- `git remote -v`
- `git tag --points-at HEAD`
- for source-checkout proof: `uv --version`
- for source-checkout proof: `uv run python --version`
- for source-checkout proof: `uv run --all-extras csvql --version`
- for installed-wheel proof only: `csvql --version`

The transcript must be tied to the same source checkout or installed candidate
used for that row. Empty command output, such as a repo with no remotes or no
tags at `HEAD`, should be recorded explicitly rather than omitted.

Plain `csvql --version` is not sufficient for source-checkout proof because the
console script may not be on `PATH`. It is allowed only for installed-wheel
proof, and the proof packet must record the wheel/install source, install
command, and why installed-wheel proof was used.

## Outside-Observer Evidence Contract

Outside-observer evidence must include:

- observer label
- date and local timezone or UTC timestamp
- OS name and version
- terminal name and version
- shell name and version
- terminal settings, including whether defaults were used
- locale or encoding settings if relevant
- candidate source access method and commit verification command
- evidence transfer method, if any
- Python and `uv` setup commands
- command transcript for setup and the applicable version commands from the
  Baseline Truth Transcript section
- per-flow notes for every TUI QoL matrix item
- media files named so they map to platform and flow ids
- viewport size range tested
- deviations, skipped steps, failures, and blocker notes

Privacy and redaction rules:

- Do not include secrets, credentials, tokens, private keys, customer data, or
  sensitive personal data in transcripts or media.
- Prefer project-relative paths in notes.
- If a screenshot or transcript exposes a personal home path or machine name,
  redact it unless that exact path is necessary to prove the result.

Outside-observer evidence is accepted as observer evidence, not locally
reproduced proof. The result packet must keep that distinction visible.

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
- Tracked release-proof docs should make three-OS automated support proof a
  required same-`HEAD` gate for any final pass result.
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
- `commands/`: command transcripts, setup outputs, or cited job-output notes
  for automated support checks.

Automated support proof outputs should use a clearly mapped naming convention,
such as:

- `commands/automated-macos.*`
- `commands/automated-windows.*`
- `commands/automated-linux.*`

An equivalent naming scheme is acceptable only if `RESULT.md` maps each file to
the OS family, runner, command set, and proof status.

`RESULT.md` must include:

- run id
- candidate commit SHA
- source access method and commit verification command for each platform row
- source access method and commit verification command for each automated
  support proof source
- evidence source for each row: local or observer-provided
- final status: `pass`, `fail`, or `blocked`
- tester and outside-observer labels, including observer timestamp and timezone
  where observer evidence is used
- per-platform terminal table
- shell, terminal settings, Python/`uv` setup path, and viewport range for each
  platform row
- per-flow matrix for all required TUI QoL flows
- transcript path or embedded command transcript for setup, baseline truth, and
  applicable version commands
- automated support proof status by OS, output paths or cited job outputs,
  exact dependency install command, exact command set, exit statuses,
  deviations, and same-`HEAD` check
- media paths
- deviations, skipped steps, failures, and whether non-default terminal settings
  were approved
- blockers
- explicit statement that VS Code, iTerm2, and tmux/SSH were out of scope
- explicit statement that no tag, publish, release artifact upload, version
  change, remote configuration, or release action occurred

## Classification Rules

- `pass`: all three required terminal rows pass every required flow with media
  evidence, and required three-OS automated support proof is recorded, all on
  the same candidate `HEAD`.
- `fail`: a required terminal row runs and a flow fails, or required automated
  support proof runs and a required command fails.
- `blocked`: any required terminal row is missing, untested, lacks media, lacks
  commit identity, cannot be trusted as same-`HEAD` evidence, or required
  three-OS automated support proof is missing, stale, or untrusted.

Release readiness remains `v1-hardening` unless this TUI proof passes and every
other documented release-readiness prerequisite is also satisfied on the same
candidate `HEAD`.

A local `pass` result from this lane is evidence only. Changing any release
label, release status, public status, tag, or published artifact still requires
separate explicit approval.

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

Implementation and proof-execution lanes must not start until they load the
required skills for the files, behavior, and evidence being touched.

- Before creating the implementation plan or proof-execution plan, use
  `superpowers:writing-plans`.
- Before editing user-facing docs, use `documentation`.
- Before editing `src/csvql/**/*.py`, `tests/**/*.py`, package metadata, typing,
  CLI/TUI behavior, or dependency surfaces, use `python-codebase-standards`.
- Before changing terminal scope, required matrix rows, required flows,
  classification rules, or release proof boundaries, return to design review
  and use `superpowers:brainstorming`.
- Before editing `.github/workflows/**`, inspect the existing workflows, use
  `python-codebase-standards` for Python gate/tooling expectations, and use a
  workflow-specific skill if one is available in the active session. Hosted CI
  pass claims are external proof and require cited job outputs.
- Before coordinating observer evidence, source/evidence transfer, terminal
  proof execution, or CI evidence collection, confirm the Candidate Source
  Access Contract, Outside-Observer Evidence Contract, and classification rules.
  If the plan needs different proof boundaries, return to design review and use
  `superpowers:brainstorming`.
- If keybinding, terminal evidence, or TUI timing behavior contradicts
  assumptions, stop and use `superpowers:systematic-debugging` before changing
  approach.
- Before claiming implementation or proof-execution completion, use
  `superpowers:verification-before-completion` or
  `verification-before-completion`.
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
- Required three-OS automated support proof is represented in tracked docs,
  result-packet requirements, classification rules, and verification guidance.
- Proof execution is blocked until tracked authority docs and guard tests agree
  with the approved three-OS scope and automated proof requirements.
- Hosted GitHub CI expansion, if implemented, supports cross-OS automated proof
  but does not replace manual terminal media evidence.
- The final TUI QoL result packet records all three required terminal rows,
  source access, observer/local evidence source, shell, terminal settings,
  transcript paths, media paths, pass/fail status, and blockers.
- No release action, tag, push, release artifact upload, remote configuration,
  version change, or publish action is performed.

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

Before any `pass` classification, the execution lane must also verify that
`RESULT.md` records the source access method, commit verification command,
local-versus-observer evidence source, shell, terminal settings, transcript
path or command transcript, observer timestamp/timezone when applicable,
deviations, baseline truth transcript, and three-OS automated support proof for
the same candidate `HEAD`.

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
