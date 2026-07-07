# VS Code Alt Keybinding Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add verified VS Code-friendly non-printing TUI key fallbacks for Help, Results, and Sources while preserving existing function-key behavior and keeping buffer-result navigation on existing Results-only brackets unless proven insufficient.

**Architecture:** Extend the existing Textual `CSVQLMenuApp.BINDINGS` entries for Help, Results, and Sources with `Alt` alternatives. Reuse the current action methods and `check_action()` gating so modal blocking, pane focus rules, and Results-only buffer navigation remain centralized.

**Tech Stack:** Python, Textual 8.2.8, pytest, Ruff, mypy, project-local `uv`.

## Global Constraints

- LocalQL is the installable distribution name.
- Runtime/user-facing surfaces stay `csvql` CLI, `csvql` import package, `.csvql.yml`, and `csvql menu`.
- Use repo-local `uv`; do not install global dependencies.
- Use `UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql` for `uv` commands in this environment.
- Do not claim sandbox safety, safe untrusted SQL, security isolation, production readiness, release-candidate eligibility, `v1-stable`, or broad large-file proof.
- Do not tag, publish, upload artifacts, push, configure remotes, change versions, or create release artifacts.
- Do not add a web app, cloud connectors, NLP execution, dataframe-first API, plugin system, hidden cache/materialization, or broader platform scope.
- Keep SQL execution semantics, DuckDB behavior, schemas, migrations, validation SQL, and database contracts untouched.
- Temporary spike code must not be committed unless it becomes the final implementation and passes the normal verification path.
- User-facing docs/help/footer shortcut promises must not be updated until the pre-churn reachability gate passes.

---

## File Structure

- Modify `src/csvql/tui_app.py`
  - Extend existing `Binding(...)` key lists for `show_help`, `focus_results`, and `focus_sources`.
  - Later update `key_display` values for footer labels after the reachability gate passes.
  - Do not add new action methods for these baseline fallbacks.
- Modify `src/csvql/tui_help.py`
  - Document `Alt+H`, `Alt+R`, and `Alt+U` after the reachability gate passes.
  - Keep `[` / `]` described as Results-only buffer navigation.
- Modify `tests/test_tui_app.py`
  - Add focused Textual dispatch tests for `Alt+H`, `Alt+R`, and `Alt+U`.
  - Add the YAGNI checkpoint test proving `Alt+R` plus existing `[` / `]` works in a real multi-result buffer state.
  - Add modal-negative tests for prompt and confirmation modal behavior.
  - Update footer and help assertions after the reachability gate passes.
- Modify `tests/test_v1_polish_docs.py`
  - Add/adjust docs guards for VS Code-friendly fallbacks, default Terminal evidence wording, and existing bracket navigation.
- Modify `README.md`, `docs/getting-started.md`, `docs/tui-guide.md`, `docs/troubleshooting.md`, and `docs/tui-qol-qa.md`
  - Add concise fallback wording after reachability is proven.
  - Keep public examples on installed `csvql ...` commands.
- Do not modify `docs/assets/localql-tui-workbench.svg` in this lane unless a later explicit visual refresh is approved.

---

### Task 1: Automated Textual Reachability Gate And Minimal Bindings

**Files:**
- Modify: `tests/test_tui_app.py`
- Modify: `src/csvql/tui_app.py`

**Interfaces:**
- Consumes: Existing `CSVQLMenuApp`, `TUISessionState`, `TUIBufferResultTab`, `QueryResult`, `_focused_widget_id()`, `_make_source_state()`.
- Produces: Existing actions remain the interface: `show_help`, `focus_results`, `focus_sources`, `select_previous_buffer_result`, `select_next_buffer_result`.

- [ ] **Step 1: Add focused failing tests for Alt dispatch and bracket YAGNI checkpoint**

Add this helper near the existing test helpers in `tests/test_tui_app.py`:

```python
def _make_multi_buffer_state(tmp_path: Path) -> TUISessionState:
    state = _make_source_state(tmp_path)
    state.record_query_success(
        sequence=1,
        sql="SELECT 'first' AS label",
        result=QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
        run_mode="buffer",
        buffer_result_index=1,
    )
    state.record_query_success(
        sequence=2,
        sql="SELECT 'second' AS label",
        result=QueryResult(columns=("label",), rows=(("second",),), elapsed_ms=1.0),
        run_mode="buffer",
        buffer_result_index=2,
    )
    state.set_buffer_result_tabs(
        (
            TUIBufferResultTab(sequence=1, index=1, label="query 1"),
            TUIBufferResultTab(sequence=2, index=2, label="query 2"),
        ),
        selected_sequence=2,
    )
    return state
```

Add these tests near the existing focus/help tests:

```python
def test_alt_fallbacks_reach_help_results_and_sources_from_sql_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()

            await pilot.press("alt+h")
            await pilot.pause()
            help_screen = type(app.screen).__name__
            await pilot.press("escape")
            await pilot.pause()

            await pilot.press("alt+r")
            await pilot.pause()
            results_focus = _focused_widget_id(app)

            await pilot.press("alt+u")
            await pilot.pause()
            sources_focus = _focused_widget_id(app)

            return help_screen, results_focus, sources_focus, sql.text

    help_screen, results_focus, sources_focus, editor_text = asyncio.run(_inner())

    assert help_screen == "_HelpScreen"
    assert results_focus == "results"
    assert sources_focus == "sources"
    assert editor_text == ""
```

Add this test next to `test_buffer_result_selector_controls_export_target`:

```python
def test_alt_r_then_plain_brackets_select_buffer_results(tmp_path: Path) -> None:
    state = _make_multi_buffer_state(tmp_path)

    async def _inner() -> tuple[str, str, tuple[tuple[object, ...], ...]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).focus()

            await pilot.press("alt+r")
            await pilot.pause()
            focus_after_alt_r = _focused_widget_id(app)

            await pilot.press("[")
            await pilot.pause()

            return (
                focus_after_alt_r,
                app.query_one("#results-title", Static).content,
                app.state.last_result.rows if app.state.last_result is not None else (),
            )

    focus_after_alt_r, results_title, rows = asyncio.run(_inner())

    assert focus_after_alt_r == "results"
    assert results_title == "ACTIVE RESULT: buffer 1.1"
    assert rows == (("first",),)
```

- [ ] **Step 2: Run the new tests and verify the Alt dispatch test fails**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_alt_fallbacks_reach_help_results_and_sources_from_sql_editor tests/test_tui_app.py::test_alt_r_then_plain_brackets_select_buffer_results -q
```

Expected before implementation: at least one failure because `alt+h`, `alt+r`, and `alt+u` are not bound yet.

- [ ] **Step 3: Add the minimal non-user-facing bindings**

Change only these existing binding declarations in `src/csvql/tui_app.py`:

```python
Binding("f1,alt+h", "show_help", "Help", key_display="F1", priority=True),
Binding("f5,alt+r", "focus_results", "Results", key_display="F5", priority=True),
Binding("f6,ctrl+up,alt+u", "focus_sources", "Sources", key_display="F6", priority=True),
```

Do not change footer display labels or docs in this task.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_alt_fallbacks_reach_help_results_and_sources_from_sql_editor tests/test_tui_app.py::test_alt_r_then_plain_brackets_select_buffer_results -q
```

Expected after implementation: `2 passed`.

- [ ] **Step 5: Do not commit yet**

Do not commit after Task 1. The bindings are still spike implementation until Task 2 proves VS Code integrated terminal reachability.

---

### Task 2: Manual Pre-Churn VS Code Reachability Gate

**Files:**
- No tracked file changes required.
- Write ignored evidence under `output/tui-qol-qa/20260707-vscode-alt-fallback/vscode-terminal/`.

**Interfaces:**
- Consumes: Task 1 minimal bindings.
- Produces: A pass/fail decision that either promotes Task 1 bindings to final implementation or returns to design review.

- [ ] **Step 1: Start from a clean understanding of the local state**

Run:

```bash
pwd -P
git status --short --branch
git log -1 --oneline
```

Expected: branch is `codex/tui-polish-qa`; tracked changes are limited to the approved spec, this plan, and Task 1 spike files if Task 1 has been applied.

- [ ] **Step 2: Launch VS Code integrated terminal with the same isolated profile/default settings used for the failing evidence**

Use the same isolated VS Code profile approach from the failed VS Code evidence. Do not change VS Code keybindings or terminal settings.

Record in `output/tui-qol-qa/20260707-vscode-alt-fallback/vscode-terminal/RESULT.md`:

```markdown
# VS Code Alt Reachability Spike

- Commit:
- Profile/settings: isolated VS Code profile with default keybindings and terminal settings
- `Alt+H` reaches TUI Help: pass | fail
- `Alt+R` focuses Results from SQL editor: pass | fail
- `Alt+U` focuses Sources from SQL editor: pass | fail
- `Alt+R`, then `[` / `]` navigates actual multi-result Run Buffer results: pass | fail
- Notes:
```

- [ ] **Step 3: Exercise the actual TUI state**

Run `csvql menu` through the project-local workflow:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras csvql menu
```

In the TUI:

- Verify `Alt+H` opens Help from the SQL editor.
- Verify `Alt+R` focuses Results from the SQL editor.
- Verify `Alt+U` focuses Sources from the SQL editor.
- Create or load a multi-result Run Buffer state.
- Verify `Alt+R` focuses Results, then plain `[` and `]` move between buffer results.

- [ ] **Step 4: Decide the gate outcome**

If all four checks pass:

- Keep the Task 1 bindings.
- Continue to Task 3.

If any check fails:

- Revert any temporary spike code that is not part of a proven final implementation.
- Leave README, docs, help text, and footer labels unchanged.
- Stop implementation and return to design review with the failing key evidence.

- [ ] **Step 5: Commit only if the gate passes**

If the gate passes, commit the Task 1 bindings and tests:

```bash
git add src/csvql/tui_app.py tests/test_tui_app.py
git commit -m "test: prove VS Code TUI key fallback reachability"
```

Expected: commit succeeds only after Task 1 automated tests and Task 2 manual gate pass.

---

### Task 3: Modal-Negative Coverage For Fallback Actions

**Files:**
- Modify: `tests/test_tui_app.py`
- Modify: `src/csvql/tui_app.py` only if a regression is exposed.

**Interfaces:**
- Consumes: Task 1 bindings.
- Produces: Regression tests proving prompt and confirmation modals still block fallback actions.

- [ ] **Step 1: Add modal-negative tests**

Add these tests near the existing modal-blocking tests:

```python
def test_prompt_modal_blocks_alt_help_and_focus_fallbacks(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    state.set_last_result(QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0))

    async def _inner() -> tuple[str, str, bool, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f7")
            await pilot.pause()
            prompt_screen = app.screen

            await pilot.press("alt+h")
            await pilot.pause()
            screen_after_help = app.screen is prompt_screen

            await pilot.press("alt+r")
            await pilot.press("alt+u")
            await pilot.pause()
            screen_after_focus = app.screen is prompt_screen

            return (
                type(prompt_screen).__name__,
                type(app.screen).__name__,
                screen_after_help,
                screen_after_focus,
            )

    first_screen, current_screen, screen_after_help, screen_after_focus = asyncio.run(_inner())

    assert first_screen == "_PromptInputScreen"
    assert current_screen == "_PromptInputScreen"
    assert screen_after_help is True
    assert screen_after_focus is True
```

```python
def test_confirmation_modal_blocks_alt_focus_and_buffer_navigation(tmp_path: Path) -> None:
    state = _make_multi_buffer_state(tmp_path)

    async def _inner() -> tuple[str, str, str, tuple[tuple[object, ...], ...]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("d")
            await pilot.pause()
            confirmation_screen = app.screen
            before_title = app.query_one("#results-title", Static).content
            before_rows = app.state.last_result.rows if app.state.last_result is not None else ()

            await pilot.press("alt+r")
            await pilot.press("[")
            await pilot.press("alt+u")
            await pilot.pause()

            return (
                type(confirmation_screen).__name__,
                type(app.screen).__name__,
                before_title,
                before_rows,
            )

    first_screen, current_screen, before_title, before_rows = asyncio.run(_inner())

    assert first_screen == "_ConfirmationScreen"
    assert current_screen == "_ConfirmationScreen"
    assert before_title == "ACTIVE RESULT: buffer 2.2"
    assert before_rows == (("second",),)
```

- [ ] **Step 2: Run the modal-negative tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_prompt_modal_blocks_alt_help_and_focus_fallbacks tests/test_tui_app.py::test_confirmation_modal_blocks_alt_focus_and_buffer_navigation -q
```

Expected: pass if existing `_MODAL_BLOCKED_APP_ACTIONS` and `check_action()` cover the fallback actions.

- [ ] **Step 3: If a test fails, fix the existing action gate only**

If a fallback action bypasses a modal, update `_MODAL_BLOCKED_APP_ACTIONS` in `src/csvql/tui_app.py` by adding the existing action name that leaked. Do not create Alt-specific modal logic.

The action set should continue to include these action names:

```python
"focus_results",
"focus_sources",
"select_next_buffer_result",
"select_previous_buffer_result",
"show_help",
```

- [ ] **Step 4: Run the modal-negative tests again**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_prompt_modal_blocks_alt_help_and_focus_fallbacks tests/test_tui_app.py::test_confirmation_modal_blocks_alt_focus_and_buffer_navigation -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_tui_app.py src/csvql/tui_app.py
git commit -m "test: cover modal blocking for TUI fallback keys"
```

---

### Task 4: Footer, Help, And User-Facing Docs

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `src/csvql/tui_help.py`
- Modify: `tests/test_tui_app.py`
- Modify: `tests/test_v1_polish_docs.py`
- Modify: `README.md`
- Modify: `docs/getting-started.md`
- Modify: `docs/tui-guide.md`
- Modify: `docs/troubleshooting.md`
- Modify: `docs/tui-qol-qa.md`

**Interfaces:**
- Consumes: Task 2 passed reachability decision.
- Produces: Compact visible footer/help/docs wording for `Alt+H`, `Alt+R`, and `Alt+U`; no user-facing `Alt+[` / `Alt+]` promise unless a separate design review approved it.

- [ ] **Step 1: Update footer display tests first**

In `test_footer_is_contextual_between_primary_panes`, update only the affected expected footer tuples:

```python
expected_sql_footer = (
    ("F1/Alt+H", "Help"),
    ("F3", "Open CSV"),
    ("F4", "Run current"),
    ("F5/Alt+R", "Results"),
    ("F6/Alt+U", "Sources"),
    ("F8", "History"),
    ("F9", "Quit"),
    ("F10", "New query"),
    ("F12", "Run buffer"),
)
expected_sources_footer = (
    ("F1/Alt+H", "Help"),
    ("F2", "SQL"),
    ("F3", "Open CSV"),
    ("F5/Alt+R", "Results"),
    ("F8", "History"),
    ("F9", "Quit"),
)
expected_history_footer = (
    ("F1/Alt+H", "Help"),
    ("F2", "SQL"),
    ("F5/Alt+R", "Results"),
    ("F6/Alt+U", "Sources"),
    ("F7", "Export active"),
    ("F9", "Quit"),
    ("Ctrl+S/Alt+S", "Save active"),
)
expected_results_footer = (
    ("F1/Alt+H", "Help"),
    ("F2", "SQL"),
    ("F6/Alt+U", "Sources"),
    ("F7", "Export active"),
    ("F8", "History"),
    ("F9", "Quit"),
    ("Ctrl+S/Alt+S", "Save active"),
)
```

- [ ] **Step 2: Update help/docs assertions**

In `test_help_text_documents_workbench_keymap`, update focus/general assertions:

```python
assert "F5 / Alt+R         Results" in help_text
assert "F6 / Alt+U         Sources" in help_text
assert "F1 / Alt+H         Help" in help_text
assert "[ / ]               Previous/next buffer result when Results is focused" in help_text
assert "Alt+[ / Alt+]" not in help_text
```

In `test_tui_guide_documents_portable_fallbacks_and_run_labels`, add:

```python
assert "| `F5` or `Alt+R` | Focus results |" in guide
assert "| `F6`, `Ctrl+Up`, or `Alt+U` | Focus sources |" in guide
assert "| `F1` or `Alt+H` | Help |" in guide
assert "After `Alt+R` focuses Results, `[` and `]` step through buffer results." in guide
```

In `test_troubleshooting_documents_portable_fallbacks`, add:

```python
assert "- `F6`, `Ctrl+Up`, or `Alt+U`: sources" in troubleshooting
assert "- `F5` or `Alt+R`: results" in troubleshooting
assert "- `F1` or `Alt+H`: help" in troubleshooting
```

In `tests/test_v1_polish_docs.py`, add docs guards:

```python
def test_tui_docs_describe_vscode_friendly_alt_fallbacks_without_alt_brackets() -> None:
    docs = "\n".join(
        [
            read_doc("README.md"),
            read_doc("docs/getting-started.md"),
            read_doc("docs/tui-guide.md"),
            read_doc("docs/troubleshooting.md"),
            read_doc("docs/tui-qol-qa.md"),
        ]
    )
    normalized_docs = normalized_markdown_text(docs)

    assert "`Alt+H`" in docs
    assert "`Alt+R`" in docs
    assert "`Alt+U`" in docs
    assert "After `Alt+R` focuses Results, `[` and `]`" in normalized_docs
    assert "Alt+[" not in docs
    assert "Alt+]" not in docs
    assert "default Terminal settings" in docs
```

- [ ] **Step 3: Run the updated tests and verify they fail before docs/footer implementation**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_footer_is_contextual_between_primary_panes tests/test_tui_app.py::test_help_text_documents_workbench_keymap tests/test_tui_app.py::test_tui_guide_documents_portable_fallbacks_and_run_labels tests/test_tui_app.py::test_troubleshooting_documents_portable_fallbacks tests/test_v1_polish_docs.py::test_tui_docs_describe_vscode_friendly_alt_fallbacks_without_alt_brackets -q
```

Expected before implementation: failures naming missing `Alt+H`, `Alt+R`, or `Alt+U` wording.

- [ ] **Step 4: Update binding footer labels**

In `src/csvql/tui_app.py`, update the key display values:

```python
Binding("f1,alt+h", "show_help", "Help", key_display="F1/Alt+H", priority=True),
Binding("f5,alt+r", "focus_results", "Results", key_display="F5/Alt+R", priority=True),
Binding(
    "f6,ctrl+up,alt+u",
    "focus_sources",
    "Sources",
    key_display="F6/Alt+U",
    priority=True,
),
```

- [ ] **Step 5: Update in-app help text**

In `src/csvql/tui_help.py`, update these lines:

```text
Focus
  F2 / Ctrl+Down      SQL editor
  F5 / Alt+R         Results
  F6 / Alt+U         Sources
  F8                  History
...
General
  F1 / Alt+H         Help
```

Keep the Results section as:

```text
Results
  [ / ]               Previous/next buffer result when Results is focused
```

- [ ] **Step 6: Update user-facing docs**

Update `docs/tui-guide.md` core key table:

```markdown
| `F5` or `Alt+R` | Focus results |
| `F6`, `Ctrl+Up`, or `Alt+U` | Focus sources |
| `F1` or `Alt+H` | Help |
```

Add this sentence near the Run Buffer / Results explanation:

```markdown
After `Alt+R` focuses Results, `[` and `]` step through buffer results.
```

Update `README.md` interactive menu section:

```markdown
Use `F2` or `Ctrl+Down` for the SQL editor, `F3` to choose CSV file(s), `F5` or `Alt+R`
for results, `F6`, `Ctrl+Up`, or `Alt+U` for sources, and `F8` for history.
```

Update the Help sentence:

```markdown
`F1` or `Alt+H` opens help.
```

Update `docs/getting-started.md`:

```markdown
`Ctrl+B` to run the full editor buffer, `F6` or `Alt+U` for sources, `F5` or
`Alt+R` for results, `F8` for history, and `F9` or `q` outside text entry to quit.
```

Update `docs/troubleshooting.md` key list:

```markdown
- `F6`, `Ctrl+Up`, or `Alt+U`: sources
- `F5` or `Alt+R`: results
- `F1` or `Alt+H`: help
```

Update `docs/tui-qol-qa.md` with a compact compatibility note under `Automation Boundary`:

```markdown
For VS Code integrated terminal evidence, verify `Alt+H`, `Alt+R`, and `Alt+U`
with the same isolated profile/default settings used for the failing row. For
macOS Terminal evidence, use default Terminal settings unless a result summary
explicitly records a different setting. After `Alt+R` focuses Results, verify
plain `[` and `]` against an actual multi-result Run Buffer state.
```

- [ ] **Step 7: Run focused docs/footer tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_footer_is_contextual_between_primary_panes tests/test_tui_app.py::test_help_text_documents_workbench_keymap tests/test_tui_app.py::test_tui_guide_documents_portable_fallbacks_and_run_labels tests/test_tui_app.py::test_troubleshooting_documents_portable_fallbacks tests/test_v1_polish_docs.py::test_tui_docs_describe_vscode_friendly_alt_fallbacks_without_alt_brackets -q
```

Expected: selected tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/csvql/tui_app.py src/csvql/tui_help.py tests/test_tui_app.py tests/test_v1_polish_docs.py README.md docs/getting-started.md docs/tui-guide.md docs/troubleshooting.md docs/tui-qol-qa.md
git commit -m "docs: document VS Code TUI key fallbacks"
```

---

### Task 5: Focused And Broad Automated Verification

**Files:**
- No planned edits.

**Interfaces:**
- Consumes: Tasks 1 through 4.
- Produces: Verified automated proof before manual terminal evidence.

- [ ] **Step 1: Run focused TUI tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_tui_app.py::test_alt_fallbacks_reach_help_results_and_sources_from_sql_editor tests/test_tui_app.py::test_alt_r_then_plain_brackets_select_buffer_results tests/test_tui_app.py::test_prompt_modal_blocks_alt_help_and_focus_fallbacks tests/test_tui_app.py::test_confirmation_modal_blocks_alt_focus_and_buffer_navigation tests/test_tui_app.py::test_footer_is_contextual_between_primary_panes tests/test_tui_app.py::test_help_text_documents_workbench_keymap -q
```

Expected: selected tests pass.

- [ ] **Step 2: Run focused docs tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_tui_docs_describe_vscode_friendly_alt_fallbacks_without_alt_brackets tests/test_v1_polish_docs.py::test_tui_qol_qa_gate_is_blocking_and_records_terminal_evidence tests/test_v1_polish_docs.py::test_docs_describe_tui_active_result_not_last_successful_result -q
```

Expected: selected tests pass.

- [ ] **Step 3: Run style and type checks**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras mypy src
```

Expected: each command exits 0.

- [ ] **Step 4: Run full pytest if focused checks pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest
```

Expected: full test suite exits 0.

- [ ] **Step 5: Check whitespace in the touched diff**

Run:

```bash
git diff --check
```

Expected: no output and exit 0.

- [ ] **Step 6: Commit verification-only adjustments if needed**

If verification exposed a small fix, commit only that fix:

```bash
git add src/csvql/tui_app.py src/csvql/tui_help.py tests/test_tui_app.py tests/test_v1_polish_docs.py README.md docs/getting-started.md docs/tui-guide.md docs/troubleshooting.md docs/tui-qol-qa.md
git commit -m "test: stabilize TUI fallback key coverage"
```

If no files changed, do not create a verification-only empty commit.

---

### Task 6: Post-Implementation Manual Evidence

**Files:**
- Write ignored evidence under `output/tui-qol-qa/20260707-vscode-alt-fallback/macos-terminal/`.
- Write ignored evidence under `output/tui-qol-qa/20260707-vscode-alt-fallback/vscode-terminal/`.
- Optionally update ignored `output/tui-qol-qa/20260707-vscode-alt-fallback/RESULT.md`.

**Interfaces:**
- Consumes: Passing automated verification from Task 5.
- Produces: Manual terminal evidence; this does not create release eligibility by itself.

- [ ] **Step 1: Create a new ignored run id for the post-implementation HEAD**

Use this new run id for the post-implementation evidence:

```text
output/tui-qol-qa/20260707-vscode-alt-fallback/
```

- [ ] **Step 2: Record repo truth for the manual run**

Run:

```bash
pwd -P
git status --short --branch
git log -1 --oneline
git tag --points-at HEAD
```

Expected: record the output in local ignored evidence notes. Do not claim `v1-stable`, release-candidate eligibility, or publish readiness.

- [ ] **Step 3: Refresh macOS Terminal evidence with default Terminal settings**

In macOS Terminal with default Terminal settings unless explicitly recorded otherwise:

- Verify existing function keys still work for Help, Results, Sources, Run SQL, Run Buffer, History, and Quit.
- Verify `Alt+H`, `Alt+R`, and `Alt+U` reach Help, Results, and Sources if they are advertised in the footer/docs.
- Verify normal-size and terminal-too-small views show compact footer labels without hiding the resize warning.

Store screenshots/notes under:

```text
output/tui-qol-qa/20260707-vscode-alt-fallback/macos-terminal/
```

- [ ] **Step 4: Refresh VS Code integrated terminal evidence with isolated default profile**

In VS Code integrated terminal using the same isolated profile/default settings as the failing evidence:

- Verify `Alt+H` reaches Help from SQL editor.
- Verify `Alt+R` focuses Results from SQL editor.
- Verify `Alt+U` focuses Sources from SQL editor.
- Verify an actual multi-result Run Buffer state.
- From SQL editor, press `Alt+R`, then verify plain `[` and `]` navigate buffer results in Results.

Store screenshots/notes under:

```text
output/tui-qol-qa/20260707-vscode-alt-fallback/vscode-terminal/
```

- [ ] **Step 5: Summarize manual evidence without overstating release status**

Write an ignored `RESULT.md` summary with this shape:

```markdown
# TUI Fallback Key Manual Evidence

- Run id:
- Commit:
- Overall status: pass | fail | blocked
- macOS Terminal default settings: pass | fail | blocked
- VS Code integrated terminal isolated default profile: pass | fail | blocked
- Existing function keys preserved: pass | fail | blocked
- `Alt+H`, `Alt+R`, `Alt+U`: pass | fail | blocked
- `Alt+R` then plain `[` / `]` in actual multi-result Results state: pass | fail | blocked
- Release status: not claimed
- Notes:
```

- [ ] **Step 6: Do not commit ignored evidence**

Run:

```bash
git status --short --ignored output/tui-qol-qa/20260707-vscode-alt-fallback/
```

Expected: evidence paths are ignored. Do not add them to git.

---

### Task 7: Final Handoff Checks

**Files:**
- No planned edits.

**Interfaces:**
- Consumes: Tasks 1 through 6.
- Produces: Final implementation handoff with exact proof boundaries.

- [ ] **Step 1: Re-run final status checks**

Run:

```bash
git status --short --branch
git log -3 --oneline
git diff --check
```

Expected: tracked tree is clean unless there are intentional uncommitted docs/spec/plan edits. `git diff --check` exits 0.

- [ ] **Step 2: Confirm no prohibited claims were introduced**

Run:

```bash
rg -n "v1-stable|production readiness|safe untrusted|sandbox|release-candidate eligible|publish to PyPI|GitHub release" README.md docs src tests
```

Expected: any matches are existing boundary language or explicit "do not claim" wording, not new positive claims.

- [ ] **Step 3: Confirm no Alt bracket promise was introduced without approval**

Run:

```bash
rg -n "Alt\\+\\[|Alt\\+\\]" README.md docs src/csvql/tui_help.py tests
```

Expected: no matches unless a later design review explicitly approved `Alt+[` / `Alt+]`.

- [ ] **Step 4: Prepare final handoff**

Report:

- Files changed.
- Commits created.
- Automated verification commands and results.
- Manual evidence run id and status.
- Whether `Alt+R` plus plain `[` / `]` passed, or whether the lane returned to design review.
- Remaining terminal matrix gaps.
- No release-candidate, publish, tag, or `v1-stable` claim.
