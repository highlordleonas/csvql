# TUI QoL QA Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a blocking TUI quality-of-life QA gate, link it into release readiness, and add deterministic automated regressions for the TUI behaviors that can be tested reliably.

**Architecture:** The manual gate lives in a new docs authority surface, `docs/tui-qol-qa.md`, and release-readiness docs link to it as a blocking candidate requirement. Automated coverage stays in existing focused tests: docs assertions in `tests/test_v1_polish_docs.py` and TUI behavior assertions in `tests/test_tui_app.py`. OS-terminal-specific behavior remains manual proof under ignored `output/tui-qol-qa/<run-id>/`.

**Tech Stack:** Markdown docs, Python 3.12, pytest, Textual test pilot, Ruff, mypy, `uv`.

---

### Task 1: Add The TUI QoL QA Authority Doc And Narrow Public-Branch Guard

**Files:**
- Create: `docs/tui-qol-qa.md`
- Modify: `tests/test_v1_polish_docs.py`
- Modify: `tests/test_open_source_launch_docs.py`

- [ ] **Step 1: Write failing docs tests**

Add this test to `tests/test_v1_polish_docs.py` after `test_manual_qa_matrix_covers_cli_and_tui_release_paths`:

```python
def test_tui_qol_qa_gate_is_blocking_and_records_terminal_evidence() -> None:
    matrix = read_doc("docs/tui-qol-qa.md")

    assert "# TUI QoL QA Gate" in matrix
    assert "Any failed item blocks `release-candidate eligible`." in matrix
    for terminal in (
        "macOS Terminal",
        "iTerm2",
        "VS Code terminal",
        "Linux terminal",
        "Windows Terminal",
        "tmux/SSH",
    ):
        assert terminal in matrix
    for flow in (
        "Launch empty",
        "Launch with one CSV",
        "Launch from a project catalog",
        "Add a source with `F3`",
        "Add a source through the Add Source prompt",
        "Add a source by pasted path",
        "Run selected SQL",
        "Run the current statement",
        "Run full-buffer multi-statement SQL with `F12`",
        "Recall History results",
        "Rerun History rows",
        "Export a recalled result",
        "Save a derived source from the latest result",
        "Save a derived source from a recalled History result",
        "Open and close help repeatedly from every pane",
        "Try every documented key from every pane",
        "Resize the terminal while using each pane",
        "Run invalid SQL",
        "Run SQL against a missing source or missing file path",
        "Run DDL or no-result SQL",
        "Run batch SQL where a middle statement fails",
    ):
        assert flow in matrix
    assert "output/tui-qol-qa/<run-id>/<terminal-id>/" in matrix
    assert "media evidence is required for every terminal run" in matrix
    assert "Which pane is active?" in matrix
    assert "Which source, query, History row, result, export, or derived-source target is affected?" in matrix
```

Update `tests/test_open_source_launch_docs.py` by changing `test_internal_operator_material_is_not_on_public_branch` to this:

```python
def test_removed_internal_operator_material_is_not_on_public_branch() -> None:
    for path in (
        "AGENTS.md",
        "docs/CODEX_CAPABILITY_REVIEW.md",
    ):
        assert not (REPO_ROOT / path).exists(), path
    assert not list((REPO_ROOT / "docs").glob("release-candidate-proof-*.md"))
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_tui_qol_qa_gate_is_blocking_and_records_terminal_evidence tests/test_open_source_launch_docs.py::test_removed_internal_operator_material_is_not_on_public_branch -q
```

Expected before implementation:

```text
FAILED tests/test_v1_polish_docs.py::test_tui_qol_qa_gate_is_blocking_and_records_terminal_evidence
```

The launch-doc guard test should pass after renaming/narrowing it because the approved Superpowers workflow intentionally stores specs and plans under `docs/superpowers/`.

- [ ] **Step 3: Create `docs/tui-qol-qa.md`**

Create the file with this content:

````markdown
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
| QOL-04 | Add a source with `F3` | Native picker works where available; otherwise the documented path prompt appears and accepts a CSV path. |
| QOL-05 | Add a source through the Add Source prompt | `name=path` adds the expected session source and selects it predictably. |
| QOL-06 | Add a source by pasted path | Pasted CSV path becomes a session source and does not remain as SQL text. |
| QOL-07 | Run selected SQL | Only the selected SQL runs and History records one attempt. |
| QOL-08 | Run the current statement | `F4` runs the statement around the cursor, not unrelated editor text. |
| QOL-09 | Run full-buffer multi-statement SQL with `F12` | Each statement is recorded as a separate History row and successful rows can be recalled. |
| QOL-10 | Recall History results | Highlighting a successful History row restores that result without rerunning SQL. |
| QOL-11 | Rerun History rows | Rerun appends a new sequence and selects the new query row. |
| QOL-12 | Export a recalled result | Export writes the recalled result, not a stale or unrelated result. |
| QOL-13 | Save a derived source from the latest result | Derived CSV is written under `.csvql/results/`, added as a session source, and queryable. |
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
````

- [ ] **Step 4: Run docs tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_tui_qol_qa_gate_is_blocking_and_records_terminal_evidence tests/test_open_source_launch_docs.py::test_removed_internal_operator_material_is_not_on_public_branch -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

Run:

```bash
git add docs/tui-qol-qa.md tests/test_v1_polish_docs.py tests/test_open_source_launch_docs.py
git commit -m "docs: add TUI QoL QA gate"
```

### Task 2: Link The Gate Into Manual QA And Release Readiness

**Files:**
- Modify: `docs/v1-manual-qa.md`
- Modify: `docs/release-readiness.md`
- Modify: `tests/test_v1_polish_docs.py`

- [ ] **Step 1: Write failing linkage tests**

Update `test_release_readiness_links_manual_qa_matrix` in `tests/test_v1_polish_docs.py` to:

```python
def test_release_readiness_links_manual_qa_matrix() -> None:
    readiness = read_doc("docs/release-readiness.md")

    assert "[Manual v1 QA matrix](v1-manual-qa.md)" in readiness
    assert "[TUI QoL QA gate](tui-qol-qa.md)" in readiness
    assert "Run the manual v1 QA matrix" in readiness
    assert "Run the TUI QoL QA gate" in readiness
    assert "Any failed TUI QoL matrix item blocks `release-candidate eligible`." in readiness
    assert "TUI QoL run id" in readiness
```

Add this test after it:

```python
def test_manual_qa_matrix_links_tui_qol_gate() -> None:
    matrix = read_doc("docs/v1-manual-qa.md")

    assert "[TUI QoL QA gate](tui-qol-qa.md)" in matrix
    assert "The TUI QoL QA gate is blocking for `release-candidate eligible`." in matrix
```

- [ ] **Step 2: Run the failing linkage tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_release_readiness_links_manual_qa_matrix tests/test_v1_polish_docs.py::test_manual_qa_matrix_links_tui_qol_gate -q
```

Expected before docs edits:

```text
FAILED tests/test_v1_polish_docs.py::test_release_readiness_links_manual_qa_matrix
FAILED tests/test_v1_polish_docs.py::test_manual_qa_matrix_links_tui_qol_gate
```

- [ ] **Step 3: Link from `docs/v1-manual-qa.md`**

After the paragraph ending with `` `v1-stable`. ``, add:

```markdown
The dedicated [TUI QoL QA gate](tui-qol-qa.md) is blocking for
`release-candidate eligible`. Run it in addition to this matrix before making
any positive candidate eligibility assessment.
```

- [ ] **Step 4: Link from `docs/release-readiness.md` manual QA section**

Replace the `## Manual V1 QA Matrix` section with:

```markdown
## Manual QA Gates

Run both manual QA gates before classifying a final candidate:

- [Manual v1 QA matrix](v1-manual-qa.md)
- [TUI QoL QA gate](tui-qol-qa.md)

The manual v1 matrix covers CLI-only reuse, optional TUI flows,
derived-source save and query, bad SQL, TUI DDL metadata results, export
overwrite behavior, missing files, quit behavior, and Mac keybinding paths.

The TUI QoL QA gate covers terminal-specific quality-of-life behavior across
macOS Terminal, iTerm2, VS Code terminal, Linux terminal, Windows Terminal, and
tmux/SSH. Any failed TUI QoL matrix item blocks `release-candidate eligible`.
```

- [ ] **Step 5: Update release-readiness workflow step 5**

In `docs/release-readiness.md`, replace workflow step 5 with:

```markdown
5. Run the manual v1 QA matrix and record the date, commit SHA, terminal app,
   passed items, and blockers.
6. Run the TUI QoL QA gate and record the TUI QoL run id, commit SHA, terminal
   coverage, media artifact paths, passed items, and blockers. Any failed,
   untested, or missing-media TUI QoL item blocks `release-candidate eligible`.
7. Run benchmark proof or explicitly cite a current local benchmark artifact.
   A current local benchmark artifact must come from the same candidate-state
   `HEAD`; record both `output/benchmarks/<run-id>/benchmark.json` and
   `output/benchmarks/<run-id>/benchmark-summary.md`. Rerunning
   `uv run python scripts/benchmark_csvql.py --output-root output/benchmarks`
   during final candidate evaluation is preferred.
8. Scan for unsupported current claims:
```

Then renumber the later workflow steps so classification is step 9 and the no-publish stop is step 10.

- [ ] **Step 6: Update release-readiness label rules**

In `docs/release-readiness.md`, add this bullet to the `release-candidate eligible` prerequisites:

```markdown
- the TUI QoL QA gate passes on every required terminal, with a TUI QoL run id
  and media artifact paths recorded
```

- [ ] **Step 7: Run linkage tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py -q
```

Expected:

```text
7 passed
```

The exact count may be higher if more tests have been added to the file; all tests in `tests/test_v1_polish_docs.py` must pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add docs/v1-manual-qa.md docs/release-readiness.md tests/test_v1_polish_docs.py
git commit -m "docs: link TUI QoL gate to release readiness"
```

### Task 3: Add Regression Tests For Recalled Result Export And Save

**Files:**
- Modify: `tests/test_tui_app.py`
- Modify only if tests fail for a real product gap: `src/csvql/tui_app.py` or `src/csvql/tui_state.py`

- [ ] **Step 1: Add recalled export/save tests**

Add these tests after `test_export_last_result_writes_file_when_result_exists` in `tests/test_tui_app.py`:

```python
def test_export_uses_recalled_history_result(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    first_sequence = state.begin_query_run("SELECT 'first' AS label")
    state.record_query_success(
        first_sequence,
        "SELECT 'first' AS label",
        QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
    )
    second_sequence = state.begin_query_run("SELECT 'second' AS label")
    state.record_query_success(
        second_sequence,
        "SELECT 'second' AS label",
        QueryResult(columns=("label",), rows=(("second",),), elapsed_ms=1.0),
    )
    export_path = tmp_path / "exports" / "recalled.csv"
    export_path.parent.mkdir()

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=0)
            await pilot.pause()

            await pilot.press("f7")
            await pilot.pause()
            export_input = app.screen.query_one("#export-path", Input)
            export_input.value = str(export_path)
            await pilot.press("enter")
            await pilot.pause()

            return (
                app.query_one("#status", Static).content,
                export_path.read_text(encoding="utf-8"),
            )

    status, content = asyncio.run(_inner())

    assert "Exported to" in status
    assert content == "label\nfirst\n"
```

Add this test after `test_save_result_as_source_writes_csv_and_adds_derived_source`:

```python
def test_save_result_as_source_uses_recalled_history_result(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    first_sequence = state.begin_query_run("SELECT 'first' AS label")
    state.record_query_success(
        first_sequence,
        "SELECT 'first' AS label",
        QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
    )
    second_sequence = state.begin_query_run("SELECT 'second' AS label")
    state.record_query_success(
        second_sequence,
        "SELECT 'second' AS label",
        QueryResult(columns=("label",), rows=(("second",),), elapsed_ms=1.0),
    )

    async def _inner() -> tuple[tuple[TUISource, ...], str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=0)
            await pilot.pause()

            await pilot.press("f11")
            await pilot.pause()
            alias_input = app.screen.query_one("#derived-source-alias", Input)
            alias_input.value = "recalled_first"
            await pilot.press("enter")
            await pilot.pause()

            output_path = tmp_path / ".csvql" / "results" / "recalled_first.csv"
            return (
                app.state.sources,
                app.query_one("#status", Static).content,
                output_path.read_text(encoding="utf-8"),
            )

    sources, status, content = asyncio.run(_inner())

    assert sources[-1] == TUISource(
        name="recalled_first",
        path=(tmp_path / ".csvql" / "results" / "recalled_first.csv").resolve(),
        origin="session",
        kind="derived",
    )
    assert "Saved result as derived source recalled_first" in status
    assert content == "label\nfirst\n"
```

- [ ] **Step 2: Run the new tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_export_uses_recalled_history_result tests/test_tui_app.py::test_save_result_as_source_uses_recalled_history_result -q
```

Expected:

```text
2 passed
```

If either test fails because focusing History does not restore `last_result`, inspect `CSVQLMenuApp.action_focus_history`, `CSVQLMenuApp.on_data_table_row_highlighted`, and `TUISessionState.restore_query_result`. The correct implementation is that successful History highlight restores both `last_result` and `result_view` without running SQL.

- [ ] **Step 3: Run focused TUI app tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 4: Commit**

Run:

```bash
git add tests/test_tui_app.py src/csvql/tui_app.py src/csvql/tui_state.py
git commit -m "test: cover recalled TUI result export and save"
```

If `src/csvql/tui_app.py` and `src/csvql/tui_state.py` did not change, omit them from `git add`.

### Task 4: Add Regression Tests For Batch Mid-Failure And Help Focus Restoration

**Files:**
- Modify: `tests/test_tui_app.py`
- Modify only if tests fail for a real product gap: `src/csvql/tui_app.py`

- [ ] **Step 1: Add batch mid-failure test**

Add this test after `test_run_all_shortcut_runs_whole_editor_when_current_statement_is_not_enough`:

```python
def test_run_all_stops_batch_after_middle_statement_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    seen_runs: list[tuple[int, str]] = []

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        del sources
        from csvql.tui_state import TUIQueryOutcome

        seen_runs.append((sequence, sql))
        if "broken" in sql:
            return TUIQueryOutcome.error(
                sequence=sequence,
                sql=sql,
                error_message="simulated failure",
                suggestion="Fix statement 2.",
            )
        return TUIQueryOutcome.success(
            sequence=sequence,
            sql=sql,
            result=QueryResult(columns=("value",), rows=((sequence,),), elapsed_ms=1.0),
        )

    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[list[tuple[int, str]], list[str], list[int], str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text(
                "SELECT 1 AS first;\n"
                "SELECT broken FROM customers;\n"
                "SELECT 3 AS third;"
            )

            await pilot.press("f12")
            await pilot.pause(0.2)

            return (
                seen_runs,
                app_history_statuses(app.state),
                [item.sequence for item in app.state.query_history],
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.query_one("#run-status", Static).content,
            )

    seen_runs, statuses, sequences, status, message, run_status = asyncio.run(_inner())

    assert seen_runs == [
        (1, "SELECT 1 AS first"),
        (2, "SELECT broken FROM customers"),
    ]
    assert statuses == ["success", "error"]
    assert sequences == [1, 2]
    assert "simulated failure" in status
    assert "simulated failure" in message
    assert run_status == "Ready."
```

- [ ] **Step 2: Add help focus restoration test**

Add this test after `test_help_action_does_not_stack_multiple_help_screens`:

```python
@pytest.mark.parametrize("selector", ["#sql", "#sources", "#history", "#results"])
def test_help_escape_restores_focus_to_opening_pane(tmp_path: Path, selector: str) -> None:
    state = _make_source_state(tmp_path)
    sequence = state.begin_query_run("SELECT 1 AS value")
    state.record_query_success(
        sequence,
        "SELECT 1 AS value",
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
    )

    async def _inner() -> bool:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            opening_widget = app.query_one(selector)
            opening_widget.focus()
            await pilot.press("?")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            return app.focused is opening_widget

    assert asyncio.run(_inner()) is True
```

- [ ] **Step 3: Run the new tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_run_all_stops_batch_after_middle_statement_failure tests/test_tui_app.py::test_help_escape_restores_focus_to_opening_pane -q
```

Expected:

```text
5 passed
```

- [ ] **Step 4: If help focus restoration fails, implement explicit return focus**

If `test_help_escape_restores_focus_to_opening_pane` fails, modify `src/csvql/tui_app.py`.

Add this import near the other Textual imports:

```python
from textual.widget import Widget
```

In `CSVQLMenuApp.__init__`, add:

```python
self._help_return_focus: Widget | None = None
```

Replace `_show_help_once` and `_mark_help_closed` with:

```python
def _show_help_once(self) -> None:
    if self._help_screen_open or isinstance(self.screen, _HelpScreen):
        return
    self._help_return_focus = self.focused
    self._help_screen_open = True
    self.push_screen(_HelpScreen(), callback=lambda _: self._mark_help_closed())

def _mark_help_closed(self) -> None:
    self._help_screen_open = False
    return_focus = self._help_return_focus
    self._help_return_focus = None
    if return_focus is not None:
        return_focus.focus()
```

- [ ] **Step 5: Run focused TUI app tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 6: Commit**

Run:

```bash
git add tests/test_tui_app.py src/csvql/tui_app.py
git commit -m "test: cover TUI batch failure and help focus"
```

If `src/csvql/tui_app.py` did not change, omit it from `git add`.

### Task 5: Add Regression Tests For Pane Key Availability And Simulated Viewports

**Files:**
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Add documented-key pane behavior test**

Add this test after `test_source_letter_actions_only_work_when_sources_focused`:

```python
def test_documented_keys_have_predictable_pane_behavior(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)

            sql.focus()
            await pilot.press("a")
            await pilot.pause()
            editor_after_a = sql.text

            app.query_one("#sources", DataTable).focus()
            await pilot.press("enter")
            await pilot.pause()
            focused_after_source_enter = type(app.focused).__name__ if app.focused else ""

            app.query_one("#history", DataTable).focus()
            await pilot.press("i")
            await pilot.pause()
            editor_after_history_i = sql.text

            await pilot.press("f2")
            await pilot.pause()
            focused_after_f2 = type(app.focused).__name__ if app.focused else ""

            await pilot.press("f6")
            await pilot.pause()
            focused_after_f6 = type(app.focused).__name__ if app.focused else ""

            return (
                editor_after_a,
                focused_after_source_enter,
                editor_after_history_i,
                focused_after_f2,
                focused_after_f6,
            )

    (
        editor_after_a,
        focused_after_source_enter,
        editor_after_history_i,
        focused_after_f2,
        focused_after_f6,
    ) = asyncio.run(_inner())

    assert editor_after_a == "a"
    assert focused_after_source_enter == "DataTable"
    assert editor_after_history_i == "a"
    assert focused_after_f2 == "TextArea"
    assert focused_after_f6 == "DataTable"
```

- [ ] **Step 2: Add simulated viewport smoke test**

Add this test after `test_workbench_focus_shortcuts_cover_all_panes`:

```python
@pytest.mark.parametrize("size", [(60, 18), (160, 45)])
def test_core_panes_mount_and_remain_focusable_at_simulated_viewport_sizes(
    tmp_path: Path,
    size: tuple[int, int],
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[int, int, int, object | None, object | None, object | None, object | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            sources = app.query_one("#sources", DataTable)
            history = app.query_one("#history", DataTable)
            results = app.query_one("#results", DataTable)

            await pilot.press("f6")
            sources_focus = app.focused
            await pilot.press("f8")
            history_focus = app.focused
            await pilot.press("f5")
            results_focus = app.focused
            await pilot.press("f2")
            sql_focus = app.focused

            return (
                sources.row_count,
                history.row_count,
                results.row_count,
                sources_focus,
                history_focus,
                results_focus,
                sql_focus,
            )

    (
        sources_count,
        history_count,
        results_count,
        sources_focus,
        history_focus,
        results_focus,
        sql_focus,
    ) = asyncio.run(_inner())

    assert sources_count == 1
    assert history_count == 0
    assert results_count == 0
    assert isinstance(sources_focus, DataTable)
    assert isinstance(history_focus, DataTable)
    assert isinstance(results_focus, DataTable)
    assert isinstance(sql_focus, TextArea)
```

- [ ] **Step 3: Run the new tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_documented_keys_have_predictable_pane_behavior tests/test_tui_app.py::test_core_panes_mount_and_remain_focusable_at_simulated_viewport_sizes -q
```

Expected:

```text
3 passed
```

- [ ] **Step 4: Run focused TUI tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py tests/test_tui_editor.py tests/test_tui_state.py tests/test_tui_results.py tests/test_tui_workflows.py -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 5: Commit**

Run:

```bash
git add tests/test_tui_app.py
git commit -m "test: cover TUI pane keys and viewport smoke"
```

### Task 6: Final Verification

**Files:**
- Read-only verification across the repository.

- [ ] **Step 1: Run full format check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff format --check .
```

Expected:

```text
75 files already formatted
```

The file count may increase if new test/doc files affect Ruff's discovered Python files; the command must exit 0.

- [ ] **Step 2: Run full lint**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check .
```

Expected:

```text
All checks passed!
```

- [ ] **Step 3: Run full typecheck**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras mypy src
```

Expected:

```text
Success: no issues found in 32 source files
```

- [ ] **Step 4: Run full tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest
```

Expected:

```text
all tests passed
```

The exact count will be higher than the current 496 after the new tests land.

- [ ] **Step 5: Run whitespace diff check**

Run:

```bash
git diff --check
```

Expected: command exits 0 with no output.

- [ ] **Step 6: Run stale phrase scan**

Run:

```bash
rg -n "Run the whole SQL editor|F1 and \\?|\\? and F1|Ctrl\\+Enter|ctrl\\+enter|drag/drop|drag and drop|dropped files" README.md docs src tests --glob '!docs/superpowers/**'
```

Expected: command exits 1 with no matches.

- [ ] **Step 7: Run claim-boundary scan**

Run:

```bash
rg -n "v1-ready|v1 ready|production-safe|production ready|production-readiness|production readiness|sandbox-safe|sandbox safety|sandbox|large-file-proven|large file proven|large-file performance|large file performance" README.md CHANGELOG.md docs/development.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/benchmarking.md docs/failure-gallery.md docs/release-readiness.md docs/release-notes/v1.md
```

Expected: matches are guardrails, negations, or the documented scan commands. A current positive claim blocks completion.

- [ ] **Step 8: Confirm clean working tree**

Run:

```bash
git status --short --branch
git log -1 --oneline
```

Expected:

```text
## main
```

`git status --short --branch` must show no modified or untracked files after
the `## main` branch line. `git log -1 --oneline` must show the final commit
created by the implementation worker.

If final verification required a fix, commit the fix with a narrow message and rerun the relevant verification command.
