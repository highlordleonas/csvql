# TUI Tab Completion Follow-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Tab` the primary SQL-editor completion trigger in `csvql menu`, falling back to four-space indentation while keeping `Ctrl+Space` as a secondary trigger and leaving pane navigation unchanged.

**Architecture:** Keep completion-item generation in the existing SQL-assist helper flow and move only the trigger decision into the focused SQL editor widget. `_SourcePathTextArea` should own plain `Tab`, call a shared `CSVQLMenuApp` completion-opening helper, and use the existing editor text-replacement path to indent when no completion items exist.

**Tech Stack:** Python 3.11+, Textual 8.2.8, pytest, Ruff, mypy, uv.

## Global Constraints

- LocalQL remains the installable distribution name.
- Runtime surfaces remain `csvql` CLI, `csvql` import package, `.csvql.yml`, and `csvql menu`.
- User-authored SQL remains trusted local DuckDB SQL.
- No NLP, natural-language query generation, AI insight generation, hidden execution, or automatic background file scans while typing.
- No SQL parser, completion engine, or new runtime/development dependency by default.
- Do not change dependencies, `uv.lock`, or package metadata without separate approval.
- Do not add a web app, cloud connectors, dataframe-first API, plugin system, or platform behavior.
- Do not claim sandbox safety, safe untrusted SQL, production readiness, broad large-file proof, hidden cache/materialization, or `v1-stable`.
- Do not tag, publish, upload artifacts, change version, configure remotes, push, run hosted CI, or create a GitHub release.
- Use repo-local `uv`; do not install global dependencies.
- Before code/test edits, use `python-codebase-standards`.
- Before behavior or guard-test changes, use `superpowers:test-driven-development` unless the executor embeds failing-test-first steps.
- Before completion claims, use `superpowers:verification-before-completion`.

---

## File Structure

Modify:

- `src/csvql/tui_app.py`: move SQL-editor completion opening behind a shared helper, add editor-owned `Tab`, and reuse the existing editor replacement path for four-space indentation.
- `tests/test_tui_app.py`: add regressions for `Tab` completion, `Tab` indentation, focus retention, and the updated docs/help contract.
- `src/csvql/tui_help.py`: name `Tab` as the primary SQL-editor completion key and keep `Ctrl+Space` as secondary.
- `README.md`: update the workbench description to say `Tab` is primary, `Ctrl+Space` is secondary, and pane focus still uses explicit focus keys.
- `docs/tui-guide.md`: update the TUI guide to describe editor-owned `Tab` completion and unchanged pane focus keys.
- `docs/release-notes/v1.md`: update the stable TUI contract wording for the `Tab` follow-up.

Do not modify:

- `src/csvql/tui_sql_assist.py`
- `tests/test_tui_sql_assist.py`
- dependency, lockfile, package metadata, CI, release, or remote files

---

### Task 1: Make `Tab` Editor-Owned Completion With Indentation Fallback

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `tests/test_tui_app.py`

**Interfaces:**
- Consumes:
  - `build_completion_items(sources: Sequence[SQLAssistSource], *, text: str, cursor_index: int) -> tuple[SQLCompletionItem, ...]`
  - `CSVQLMenuApp._replace_sql_editor_text(start_index: int, end_index: int, replacement: str) -> None`
  - `_text_index_from_location(text: str, location: tuple[int, int]) -> int`
- Produces:
  - `CSVQLMenuApp._sql_completion_items_for_editor(sql: TextArea) -> tuple[SQLCompletionItem, ...]`
  - `CSVQLMenuApp._open_sql_completion_for_editor(sql: TextArea, *, empty_status_message: str | None) -> bool`
  - `CSVQLMenuApp._replace_sql_editor_selection(replacement: str) -> None`
  - `_SourcePathTextArea.action_complete_or_indent() -> None`

- [ ] **Step 1: Write the failing TUI regression tests**

Add these tests near the existing SQL-completion tests in `tests/test_tui_app.py`:

```python
def test_sql_completion_tab_single_source_replaces_token_with_bare_column(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_source_columns(
        "customers",
        (
            TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),
            TUISourceColumn(name="email", duckdb_type="VARCHAR"),
        ),
    )

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT cust")
            sql.move_cursor((0, len("SELECT cust")))
            await pilot.press("tab")
            await pilot.pause()
            screen_name = type(app.screen).__name__
            await pilot.press("enter")
            await pilot.pause()
            return screen_name, sql.text

    screen_name, editor_text = asyncio.run(_inner())

    assert screen_name == "_SQLAssistPickerScreen"
    assert editor_text == "SELECT customer_id"


def test_sql_completion_tab_inserts_spaces_and_keeps_focus_when_no_items(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT")
            sql.move_cursor((0, len("SELECT")))
            await pilot.press("tab")
            await pilot.pause()
            return sql.text, _focused_widget_id(app), type(app.screen).__name__

    editor_text, focused_widget, screen_name = asyncio.run(_inner())

    assert editor_text == "SELECT    "
    assert focused_widget == "sql"
    assert screen_name == "Screen"


def test_sql_completion_tab_unknown_qualifier_indents_instead_of_guessing(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_source_columns(
        "customers",
        (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),),
    )

    async def _inner() -> tuple[str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT rm.")
            sql.move_cursor((0, len("SELECT rm.")))
            await pilot.press("tab")
            await pilot.pause()
            return sql.text, app.query_one("#status", Static).content, type(app.screen).__name__

    editor_text, status, screen_name = asyncio.run(_inner())

    assert editor_text == "SELECT rm.    "
    assert "No completion items" not in status
    assert screen_name == "Screen"


def test_sql_completion_ctrl_space_still_opens_picker_after_tab_follow_up(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_source_columns(
        "customers",
        (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),),
    )

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT cust")
            sql.move_cursor((0, len("SELECT cust")))
            await pilot.press("ctrl+space")
            await pilot.pause()
            return type(app.screen).__name__

    assert asyncio.run(_inner()) == "_SQLAssistPickerScreen"
```

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql \
  uv run --all-extras pytest \
  tests/test_tui_app.py::test_sql_completion_tab_single_source_replaces_token_with_bare_column \
  tests/test_tui_app.py::test_sql_completion_tab_inserts_spaces_and_keeps_focus_when_no_items \
  tests/test_tui_app.py::test_sql_completion_tab_unknown_qualifier_indents_instead_of_guessing \
  tests/test_tui_app.py::test_sql_completion_ctrl_space_still_opens_picker_after_tab_follow_up \
  -q
```

Expected: FAIL because plain `Tab` still leaves the SQL editor instead of opening completion or inserting spaces.

- [ ] **Step 3: Write the minimal implementation**

In `src/csvql/tui_app.py`, refactor the existing `Ctrl+Space` path into a shared helper and bind plain `Tab` on `_SourcePathTextArea`:

```python
    def _sql_completion_items_for_editor(self, sql: TextArea) -> tuple[SQLCompletionItem, ...]:
        return build_completion_items(
            self._assist_sources(),
            text=sql.text,
            cursor_index=_text_index_from_location(sql.text, sql.selection.end),
        )

    def _open_sql_completion_for_editor(
        self,
        sql: TextArea,
        *,
        empty_status_message: str | None,
    ) -> bool:
        items = self._sql_completion_items_for_editor(sql)
        if not items:
            if empty_status_message is not None:
                self._set_status(empty_status_message)
            return False

        self._sql_assist_choices = {item.key: item for item in items}
        self.push_screen(
            _SQLAssistPickerScreen(
                tuple((item.key, item.label, item.item_kind, item.detail) for item in items)
            ),
            callback=self._handle_sql_completion_selection,
        )
        return True

    def action_open_sql_completion(self) -> None:
        if not isinstance(self.focused, TextArea):
            return

        self._open_sql_completion_for_editor(
            self.query_one("#sql", TextArea),
            empty_status_message="No completion items available.",
        )

    def _replace_sql_editor_selection(self, replacement: str) -> None:
        sql = self.query_one("#sql", TextArea)
        self._replace_sql_editor_text(
            _text_index_from_location(sql.text, sql.selection.start),
            _text_index_from_location(sql.text, sql.selection.end),
            replacement,
        )
```

Add a widget-local binding and action on `_SourcePathTextArea`:

```python
class _SourcePathTextArea(TextArea):
    """SQL editor that turns pasted CSV path payloads into sources."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("tab", "complete_or_indent", "Complete SQL", show=False),
    ]

    _last_regular_paste_text: str | None = None
    _last_regular_paste_result_text: str | None = None

    def action_complete_or_indent(self) -> None:
        if not isinstance(self.app, CSVQLMenuApp):
            return
        if self.app._open_sql_completion_for_editor(self, empty_status_message=None):
            return
        self.app._replace_sql_editor_selection("    ")
```

Keep `check_action()` unchanged for `open_sql_completion`; the new `Tab` path is widget-owned and should not widen completion to non-editor panes.

- [ ] **Step 4: Run the targeted tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql \
  uv run --all-extras pytest \
  tests/test_tui_app.py::test_sql_completion_tab_single_source_replaces_token_with_bare_column \
  tests/test_tui_app.py::test_sql_completion_tab_inserts_spaces_and_keeps_focus_when_no_items \
  tests/test_tui_app.py::test_sql_completion_tab_unknown_qualifier_indents_instead_of_guessing \
  tests/test_tui_app.py::test_sql_completion_ctrl_space_still_opens_picker_after_tab_follow_up \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/csvql/tui_app.py tests/test_tui_app.py
git commit -m "feat: add tab-triggered tui sql completion"
```

### Task 2: Update Help And Public TUI Contract Copy

**Files:**
- Modify: `src/csvql/tui_help.py`
- Modify: `README.md`
- Modify: `docs/tui-guide.md`
- Modify: `docs/release-notes/v1.md`
- Modify: `tests/test_tui_app.py`

**Interfaces:**
- Consumes:
  - `WORKBENCH_HELP`
  - `_read_readme_text() -> str`
  - `_read_doc_text(relative_path: str) -> str`
  - `_normalized_markdown_text(text: str) -> str`
  - Task 1 `Tab` behavior
- Produces:
  - `test_completion_docs_describe_tab_primary_and_ctrl_space_secondary() -> None`
  - updated help and docs copy that names `Tab` as primary, `Ctrl+Space` as secondary, and explicit pane-focus keys as unchanged

- [ ] **Step 1: Write the failing docs/help regression test**

Add this test near the existing doc assertions in `tests/test_tui_app.py`:

```python
def test_completion_docs_describe_tab_primary_and_ctrl_space_secondary() -> None:
    from csvql.tui_help import WORKBENCH_HELP

    readme = _normalized_markdown_text(_read_readme_text())
    guide = _normalized_markdown_text(_read_doc_text("docs/tui-guide.md"))
    release_notes = _normalized_markdown_text(_read_doc_text("docs/release-notes/v1.md"))

    assert "Tab                 Complete SQL if available, otherwise indent" in WORKBENCH_HELP
    assert "Ctrl+Space          Alternate SQL completion where terminal supports it" in WORKBENCH_HELP
    assert (
        "`Tab` opens explicit SQL completion when items are available; otherwise it inserts four spaces and keeps focus in the SQL editor."
        in readme
    )
    assert "`Ctrl+Space` remains available where the terminal delivers it." in readme
    assert "`Tab` is the primary SQL-editor completion key." in guide
    assert "Pane focus stays on `F2`, `F5`, `F6`, and `F8`." in guide
    assert "`Tab` is the primary SQL-editor completion key." in release_notes
    assert "`Ctrl+Space` remains a secondary trigger where the terminal delivers it." in release_notes
```

- [ ] **Step 2: Run the docs/help regression test and verify it fails**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql \
  uv run --all-extras pytest \
  tests/test_tui_app.py::test_help_text_documents_workbench_keymap \
  tests/test_tui_app.py::test_completion_docs_describe_tab_primary_and_ctrl_space_secondary \
  tests/test_tui_app.py::test_tui_guide_documents_portable_fallbacks_and_run_labels \
  -q
```

Expected: FAIL because help and docs still claim `Ctrl+Space` is the primary completion key.

- [ ] **Step 3: Update the help text and docs**

In `src/csvql/tui_help.py`, replace the current completion line with the new primary/secondary contract:

```python
Run SQL
  F4 / Ctrl+R         Run selected SQL, otherwise current statement
  F12 / Ctrl+B        Run Buffer
  Ctrl+N / F10        Clear editor for a new query
  Tab                 Complete SQL if available, otherwise indent
  Ctrl+Space          Alternate SQL completion where terminal supports it
```

In `README.md`, update the source-intelligence paragraph to this wording:

```markdown
When the source pane is focused, Source Intelligence actions use `i` to inspect
the selected source and load columns, `c` to load/show columns directly, `l` to
insert the selected source alias, and `x` to open deterministic starter SQL
templates. Preview rows and row count are always available from `x`; column-aware
templates appear after `c` or `i` loads metadata. `Tab` opens explicit SQL
completion when items are available; otherwise it inserts four spaces and keeps
focus in the SQL editor. `Ctrl+Space` remains available where the terminal
delivers it. Generated SQL is inserted into the editor and does not run until
you run it. Pane focus stays on `F2`, `F5`, `F6`, and `F8` plus the existing
documented control-key paths. Column metadata is session-local and is not
written to `.csvql.yml`.
```

In `docs/tui-guide.md`, update the completion paragraph to this wording:

```markdown
Column metadata is session-local and is not written to `.csvql.yml`.
`x` always offers preview rows and row count, and column-aware templates appear
after `c` or `i` loads metadata. `Tab` is the primary SQL-editor completion key.
When completion items are available, it opens explicit SQL completion; otherwise
it inserts four spaces and keeps focus in the SQL editor. `Ctrl+Space` remains
available where the terminal delivers it. Generated SQL is editable and does not
execute automatically. Pane focus stays on `F2`, `F5`, `F6`, and `F8`.
```

In `docs/release-notes/v1.md`, update the stable-contract paragraph to this wording:

```markdown
Source Intelligence keeps metadata local to the current TUI session. `i`
inspects the selected source and loads columns, `c` loads/shows columns
directly, `x` opens deterministic starter SQL templates, and `Tab` is the
primary SQL-editor completion key. When no completion items are available,
`Tab` inserts four spaces and keeps focus in the SQL editor. `Ctrl+Space`
remains a secondary trigger where the terminal delivers it. Pane focus stays on
the existing explicit focus keys and documented control-key paths. Generated SQL
is inserted into the editor and does not run until the user explicitly runs it.
```

- [ ] **Step 4: Run the docs/help regression tests and verify they pass**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql \
  uv run --all-extras pytest \
  tests/test_tui_app.py::test_help_text_documents_workbench_keymap \
  tests/test_tui_app.py::test_completion_docs_describe_tab_primary_and_ctrl_space_secondary \
  tests/test_tui_app.py::test_tui_guide_documents_portable_fallbacks_and_run_labels \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/csvql/tui_help.py README.md docs/tui-guide.md docs/release-notes/v1.md tests/test_tui_app.py
git commit -m "docs: document tab-first tui sql completion"
```

## Verification Ladder

After both tasks are complete, run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql \
  uv run --all-extras pytest \
  tests/test_tui_app.py::test_sql_completion_tab_single_source_replaces_token_with_bare_column \
  tests/test_tui_app.py::test_sql_completion_tab_inserts_spaces_and_keeps_focus_when_no_items \
  tests/test_tui_app.py::test_sql_completion_tab_unknown_qualifier_indents_instead_of_guessing \
  tests/test_tui_app.py::test_sql_completion_ctrl_space_still_opens_picker_after_tab_follow_up \
  tests/test_tui_app.py::test_help_text_documents_workbench_keymap \
  tests/test_tui_app.py::test_completion_docs_describe_tab_primary_and_ctrl_space_secondary \
  -q
```

Expected: PASS.

```bash
uv run ruff format --check src/csvql/tui_app.py src/csvql/tui_help.py tests/test_tui_app.py
```

Expected: PASS.

```bash
uv run ruff check src/csvql/tui_app.py src/csvql/tui_help.py tests/test_tui_app.py
```

Expected: PASS.

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run mypy src
```

Expected: PASS.

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest
```

Expected: PASS.
