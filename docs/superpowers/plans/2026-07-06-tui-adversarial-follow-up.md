# TUI Adversarial Follow-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved phased TUI adversarial follow-up: P0 correctness, P1 cancellable responsiveness/discoverability, and P2 durable result/file/path behavior.

**Architecture:** Keep the current Textual app structure, but add explicit boundaries for action gating, long-running operation workers, atomic writes, and temp-backed result storage. P0 lands first and remains independently reviewable; P1 and P2 build on the same boundaries without changing the LocalQL runtime contract.

**Tech Stack:** Python 3.11+, Textual 8.2.8, DuckDB, Typer, PyYAML, Ruff, mypy strict mode, pytest, uv.

## Global Constraints

- LocalQL remains the installable distribution name.
- Runtime surfaces remain `csvql` CLI, `csvql` import package, `.csvql.yml`, and `csvql menu`.
- User-authored SQL remains trusted local DuckDB SQL.
- Do not claim sandbox safety, safe untrusted SQL, production readiness, broad large-file proof, hidden cache/materialization, or broader platform scope.
- Do not add a web app, cloud connectors, NLP execution, dataframe-first API, plugin system, or platform behavior.
- Do not tag, publish, upload artifacts, change version, configure remotes, push, or claim `v1-stable`.
- Do not run release-candidate eligibility proof or manual terminal matrix work in this implementation lane.
- Use repo-local `uv`; do not install global dependencies.
- Use `UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql` for repo `uv` commands in this environment.
- Do not add dependencies or change `uv.lock` unless a task explicitly proves it is necessary and receives separate approval.

---

## File Structure

Modify existing files:

- `src/csvql/tui_app.py` owns Textual bindings, focus/action gating, modal prompts, worker orchestration, status rendering, and paste handling.
- `src/csvql/tui_state.py` owns in-memory session state, active-result state, buffer tabs, query history, and result-store references.
- `src/csvql/tui_workflows.py` owns TUI workflow helpers for source inspection, query execution, exports, derived-source saves, catalog saves, and CSV path parsing.
- `src/csvql/export.py` owns export path validation, formatting, and low-level export writes.
- `src/csvql/project_config.py` owns project catalog persistence.
- `src/csvql/tui_results.py` owns result preview generation and result table population.
- `src/csvql/tui_help.py`, `README.md`, `docs/tui-guide.md`, `docs/release-notes/v1.md`, and `docs/tui-qol-qa.md` own user-facing wording.
- `tests/test_tui_app.py`, `tests/test_tui_state.py`, `tests/test_tui_workflows.py`, `tests/test_export.py`, and `tests/test_v1_polish_docs.py` own regression coverage.

Create new files:

- `src/csvql/atomic_write.py` provides cancellable atomic text writes using temp sibling files.
- `src/csvql/tui_result_store.py` provides memory-or-temp-backed result handles for TUI session results.
- `tests/test_atomic_write.py` covers atomic write success, failure, and cancellation cleanup.
- `tests/test_tui_result_store.py` covers memory versus temp spill thresholds and cleanup.

Task order intentionally puts a reusable atomic write helper before workerized export/save so cancellation can safely remove temp output before final replacement.

---

### Task 1: P0 Modal Action Gate And Results-Only Buffer Navigation

**Files:**
- Modify: `src/csvql/tui_app.py`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: existing `CSVQLMenuApp.check_action(action, parameters)`, `_prompt_screen_active()`, `_is_focused()`, `action_new_query()`, `action_select_previous_buffer_result()`, `action_select_next_buffer_result()`.
- Produces: `CSVQLMenuApp._app_action_blocked_by_modal(action: str) -> bool` and stricter `check_action()` behavior used by every later task.

- [ ] **Step 1: Add failing tests for modal action blocking**

Add these tests near existing modal/help tests in `tests/test_tui_app.py`:

```python
def test_export_prompt_blocks_global_new_query_action(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    state.set_last_result(QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0))

    async def _inner() -> tuple[str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f7")
            await pilot.pause()
            screen_name = type(app.screen).__name__
            await pilot.press("f10")
            await pilot.pause()
            return screen_name, type(app.screen).__name__, sql.text

    first_screen, current_screen, sql_text = asyncio.run(_inner())

    assert first_screen == "_PromptInputScreen"
    assert current_screen == "_PromptInputScreen"
    assert sql_text == "SELECT * FROM customers"
```

```python
def test_remove_source_confirmation_blocks_global_new_query_action(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, str, int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            app.query_one("#sources", DataTable).focus()
            await pilot.press("d")
            await pilot.pause()
            screen_name = type(app.screen).__name__
            await pilot.press("f10")
            await pilot.pause()
            return screen_name, type(app.screen).__name__, sql.text, len(app.state.sources)

    first_screen, current_screen, sql_text, source_count = asyncio.run(_inner())

    assert first_screen == "_ConfirmationScreen"
    assert current_screen == "_ConfirmationScreen"
    assert sql_text == "SELECT * FROM customers"
    assert source_count == 1
```

- [ ] **Step 2: Add failing tests for Results-only buffer navigation**

Add this test near existing buffer result tests:

```python
def test_buffer_result_navigation_only_works_from_results_pane(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text(
                "SELECT customer_id FROM customers ORDER BY customer_id;"
                "SELECT email FROM customers ORDER BY email;"
            )
            await pilot.press("f12")
            await pilot.pause(0.2)
            initial_label = app.state.active_result.label

            app.query_one("#sources", DataTable).focus()
            await pilot.press("[")
            await pilot.pause()
            sources_label = app.state.active_result.label

            app.query_one("#results", DataTable).focus()
            await pilot.press("[")
            await pilot.pause()
            results_label = app.state.active_result.label
            return initial_label, sources_label, results_label

    initial_label, sources_label, results_label = asyncio.run(_inner())

    assert sources_label == initial_label
    assert results_label != initial_label
```

- [ ] **Step 3: Run the focused failing tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_export_prompt_blocks_global_new_query_action \
  tests/test_tui_app.py::test_remove_source_confirmation_blocks_global_new_query_action \
  tests/test_tui_app.py::test_buffer_result_navigation_only_works_from_results_pane -q
```

Expected: at least the export/remove modal tests fail because the underlying app still receives global actions; the buffer navigation test fails if `[`/`]` retarget outside Results.

- [ ] **Step 4: Implement modal action blocking and Results-only navigation**

In `src/csvql/tui_app.py`, add module-level action sets near `_FOOTER_KEY_ORDER_BY_PANE`:

```python
_MODAL_BLOCKED_APP_ACTIONS = {
    "add_source",
    "choose_csv_source",
    "export_last_result",
    "focus_history",
    "focus_results",
    "focus_sources",
    "focus_sql",
    "inspect_source",
    "insert_source_alias",
    "insert_starter_select",
    "new_query",
    "profile_source",
    "quit",
    "quit_from_non_editor",
    "remove_source",
    "reopen_history",
    "rerun_history",
    "run_buffer",
    "run_query",
    "run_selected_or_current_query",
    "sample_source",
    "save_result_as_source",
    "save_sources",
    "select_next_buffer_result",
    "select_previous_buffer_result",
    "show_help",
    "show_source_columns",
}

_RESULTS_ONLY_ACTIONS = {
    "select_next_buffer_result",
    "select_previous_buffer_result",
}
```

Add helpers inside `CSVQLMenuApp`:

```python
def _input_or_confirmation_screen_active(self) -> bool:
    return isinstance(self.screen, (_PromptInputScreen, _ConfirmationScreen))

def _app_action_blocked_by_modal(self, action: str) -> bool:
    return self._input_or_confirmation_screen_active() and action in _MODAL_BLOCKED_APP_ACTIONS
```

Update high-impact action guards:

```python
def action_new_query(self) -> None:
    if self._input_or_confirmation_screen_active():
        return
    sql_widget = self.query_one("#sql", TextArea)
    sql_widget.load_text("")
    sql_widget.focus()
    self._set_status("Ready for next query.")
```

Update `check_action()` before the current TextArea branch:

```python
def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
    del parameters
    if self._app_action_blocked_by_modal(action):
        return False
    if action in _RESULTS_ONLY_ACTIONS and not self._is_focused("#results"):
        return False
    ...
```

- [ ] **Step 5: Run focused tests**

Run the same command from Step 3.

Expected: PASS.

- [ ] **Step 6: Run existing adjacent TUI action tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py -k "prompt or confirmation or buffer_result or source_letter_actions" -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/csvql/tui_app.py tests/test_tui_app.py
git commit -m "fix: fence TUI modal actions"
```

---

### Task 2: P0 Non-Destructive Export Confirmation And Confirmed Catalog Save

**Files:**
- Modify: `src/csvql/tui_app.py`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: Task 1 modal blocking.
- Produces: `CSVQLMenuApp._handle_save_sources_confirmation(confirmed: bool | None) -> None` and export completion that updates status/message without clearing the grid.

- [ ] **Step 1: Add failing tests for export result preservation**

Replace or supplement `test_export_last_result_writes_file_when_result_exists` with a result-grid preservation assertion:

```python
def test_export_last_result_preserves_visible_result_grid(tmp_path: Path) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    export_path = export_dir / "customers.csv"
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[tuple[str, ...], int, tuple[str, ...], int, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers ORDER BY customer_id")
            await pilot.press("f4")
            await pilot.pause(0.2)
            before_columns, before_rows, _ = _result_grid_snapshot(app)

            await pilot.press("f7")
            await pilot.pause()
            app.screen.query_one("#export-path", Input).value = str(export_path)
            await pilot.press("enter")
            await pilot.pause()

            after_columns, after_rows, message = _result_grid_snapshot(app)
            status = app.query_one("#status", Static).content
            return before_columns, before_rows, after_columns, after_rows, message, status

    before_columns, before_rows, after_columns, after_rows, message, status = asyncio.run(_inner())

    assert before_columns == after_columns == ("customer_id", "email")
    assert before_rows == after_rows == 2
    assert "Exported to" in message
    assert "Exported to" in status
```

- [ ] **Step 2: Add failing tests for confirmed catalog save**

Update `test_save_sources_creates_catalog_only_when_invoked` to require confirmation and add cancel coverage:

```python
def test_save_sources_requires_confirmation_before_writing_catalog(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    config_path = tmp_path / ".csvql.yml"

    async def _inner() -> tuple[str, bool, bool, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("w")
            await pilot.pause()
            prompt = app.screen.query_one("#confirm-text", Static).content
            before_confirm = config_path.exists()
            await pilot.press("y")
            await pilot.pause()
            after_confirm = config_path.exists()
            status = app.query_one("#status", Static).content
            return prompt, before_confirm, after_confirm, status

    prompt, before_confirm, after_confirm, status = asyncio.run(_inner())

    assert "Save 1 source path" in prompt
    assert ".csvql.yml" in prompt
    assert before_confirm is False
    assert after_confirm is True
    assert "Saved sources to" in status
```

```python
def test_save_sources_confirmation_can_be_cancelled(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    config_path = tmp_path / ".csvql.yml"

    async def _inner() -> tuple[bool, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("w")
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            return config_path.exists(), app.query_one("#status", Static).content

    exists, status = asyncio.run(_inner())

    assert exists is False
    assert "Source catalog save cancelled." in status
```

- [ ] **Step 3: Run focused failing tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_export_last_result_preserves_visible_result_grid \
  tests/test_tui_app.py::test_save_sources_requires_confirmation_before_writing_catalog \
  tests/test_tui_app.py::test_save_sources_confirmation_can_be_cancelled -q
```

Expected: FAIL before implementation.

- [ ] **Step 4: Implement non-destructive export confirmation**

In `_handle_export_last_result()`, replace:

```python
self._show_output_text(f"Exported to {display_path}.")
```

with:

```python
self.query_one("#results-message", Static).update(f"Exported to {display_path}.")
```

Do not call `_clear_result_grid()` on export success.

- [ ] **Step 5: Implement confirmed catalog save**

Replace `action_save_sources()` with:

```python
def action_save_sources(self) -> None:
    if self._input_or_confirmation_screen_active():
        return
    if not self.state.sources:
        self._show_error(CSVQLError("No sources loaded to save."))
        return

    source_count = len(self.state.sources)
    noun = "source path" if source_count == 1 else "source paths"
    self.push_screen(
        _ConfirmationScreen(
            f"Save {source_count} {noun} to .csvql.yml? Press y to save or n to cancel."
        ),
        callback=self._handle_save_sources_confirmation,
    )
```

Add:

```python
def _handle_save_sources_confirmation(self, confirmed: bool | None) -> None:
    if not confirmed:
        self._set_status("Source catalog save cancelled.")
        self.query_one("#sources", DataTable).focus()
        return

    try:
        context = save_sources_to_project_catalog(
            self.state.sources,
            start_dir=self.start_dir,
            replace=True,
        )
    except CSVQLError as exc:
        self._show_error(exc)
        return

    display_path = _display_path(context.config_path, self.start_dir)
    self._set_status(f"Saved sources to {display_path}.")
    self.query_one("#results-message", Static).update(f"Saved sources to {display_path}.")
    self.query_one("#sources", DataTable).focus()
```

- [ ] **Step 6: Run focused tests**

Run the command from Step 3.

Expected: PASS.

- [ ] **Step 7: Run adjacent export/catalog tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py -k "export_last_result or save_sources" -q
```

Expected: PASS after adjusting existing assertions to account for confirmation.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/csvql/tui_app.py tests/test_tui_app.py
git commit -m "fix: confirm TUI catalog saves"
```

---

### Task 3: P0 Active-Result Docs And Help Wording

**Files:**
- Modify: `src/csvql/tui_help.py`
- Modify: `README.md`
- Modify: `docs/tui-guide.md`
- Modify: `docs/release-notes/v1.md`
- Test: `tests/test_tui_app.py`
- Test: `tests/test_v1_polish_docs.py`

**Interfaces:**
- Consumes: active-result behavior from the current branch.
- Produces: docs/help guardrails that keep "last successful tabular result" from returning where active-result wording is required.

- [ ] **Step 1: Add failing docs/help assertions**

In `tests/test_tui_app.py::test_help_text_documents_workbench_keymap`, add:

```python
assert "F7                  Export active result (.csv, .json, .md, .markdown, .txt)" in help_text
assert "last successful tabular" not in help_text
```

In `tests/test_v1_polish_docs.py`, add:

```python
def test_docs_describe_tui_active_result_not_last_successful_result() -> None:
    docs = "\n".join(
        [
            read_doc("README.md"),
            read_doc("docs/tui-guide.md"),
            read_doc("docs/release-notes/v1.md"),
        ]
    )
    normalized_docs = normalized_markdown_text(docs)

    assert "active result" in normalized_docs
    assert "last successful tabular query result" not in normalized_docs
    assert "last successful tabular result" not in normalized_docs
    assert ".markdown" in docs
```

- [ ] **Step 2: Run focused failing tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_help_text_documents_workbench_keymap \
  tests/test_v1_polish_docs.py::test_docs_describe_tui_active_result_not_last_successful_result -q
```

Expected: FAIL before wording updates.

- [ ] **Step 3: Update help text**

In `src/csvql/tui_help.py`, change the F7 line to:

```text
  F7                  Export active result (.csv, .json, .md, .markdown, .txt)
```

Keep the derived source lines active-result based:

```text
  Ctrl+S              Save active result to .csvql/results/{alias}.csv
  Alt+S / F11         Alternate save-result shortcuts
```

- [ ] **Step 4: Update README and docs**

Use these replacement rules:

- Replace "`Ctrl+S` saves the last successful tabular query result as a derived source." with "`Ctrl+S` saves the active tabular result as a derived source."
- Replace "`last successful tabular result`" with "`active tabular result`" when describing TUI export/save.
- Ensure the F7 export suffix list includes `.markdown`.

- [ ] **Step 5: Run focused docs tests**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/csvql/tui_help.py README.md docs/tui-guide.md docs/release-notes/v1.md tests/test_tui_app.py tests/test_v1_polish_docs.py
git commit -m "docs: align TUI active result wording"
```

---

### Task 4: P1 Source Intelligence Workers And Cancellation State

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `src/csvql/tui_state.py`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: synchronous `inspect_source()`, `sample_source()`, `profile_source()`, `inspect_source_columns()`.
- Produces: `TUIOperationRunState`, `CSVQLMenuApp._start_operation_worker()`, `CSVQLMenuApp.action_cancel_operation()`, and worker result handling for source operations.

- [ ] **Step 1: Add operation state model**

In `src/csvql/tui_state.py`, add imports:

```python
from typing import Literal
```

Extend literals:

```python
TUIOperationKind = Literal["inspect", "sample", "profile", "columns", "export", "save_result"]
```

Add dataclass:

```python
@dataclass(frozen=True, slots=True)
class TUIOperationRunState:
    """Current cancellable non-query operation state."""

    is_running: bool = False
    kind: TUIOperationKind | None = None
    label: str = ""
```

Add field to `TUISessionState`:

```python
operation_run: TUIOperationRunState = field(default_factory=TUIOperationRunState)
```

- [ ] **Step 2: Add failing source worker test**

Add to `tests/test_tui_app.py`:

```python
def test_source_intelligence_action_uses_operation_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_inspect_source(source: TUISource):
        started.set()
        release.wait(timeout=2)
        from csvql.inspection import inspect_csv_source
        from csvql.source import CSVSource, source_from_path

        resolved = source_from_path(str(source.path))
        return inspect_csv_source(CSVSource(resolved.path, source.name, resolved.fingerprint))

    monkeypatch.setattr("csvql.tui_app.inspect_source", slow_inspect_source)

    async def _inner() -> tuple[bool, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("i")
            await pilot.pause(0.1)
            running = app.state.operation_run.is_running
            status = app.query_one("#status", Static).content
            release.set()
            await pilot.pause(0.2)
            final_status = app.query_one("#status", Static).content
            return running, status, final_status

    running, status, final_status = asyncio.run(_inner())

    assert started.is_set()
    assert running is True
    assert "Inspecting customers" in status
    assert "customers: 2 columns." in final_status
```

- [ ] **Step 3: Add failing cancellation test**

```python
def test_escape_cancels_running_source_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_inspect_source(source: TUISource):
        started.set()
        release.wait(timeout=2)
        return inspect_source(source)

    monkeypatch.setattr("csvql.tui_app.inspect_source", slow_inspect_source)

    async def _inner() -> tuple[str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("i")
            await pilot.pause(0.1)
            await pilot.press("escape")
            await pilot.pause()
            release.set()
            await pilot.pause(0.2)
            return app.query_one("#status", Static).content, app.state.operation_run.is_running

    status, is_running = asyncio.run(_inner())

    assert started.is_set()
    assert "Cancelled Inspecting customers." in status
    assert is_running is False
```

- [ ] **Step 4: Run focused failing tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_source_intelligence_action_uses_operation_worker \
  tests/test_tui_app.py::test_escape_cancels_running_source_operation -q
```

Expected: FAIL before worker implementation.

- [ ] **Step 5: Add operation binding and helpers**

In `CSVQLMenuApp.BINDINGS`, add:

```python
Binding("escape", "cancel_operation", "Cancel operation", show=False),
```

Add helper fields in `__init__`:

```python
self._active_operation_worker: Worker[object] | None = None
self._cancelled_operation_names: set[str] = set()
```

Add helpers:

```python
def _operation_running(self) -> bool:
    return self.state.operation_run.is_running

def _start_operation_worker(
    self,
    *,
    kind: TUIOperationKind,
    label: str,
    work: Callable[[], object],
) -> None:
    if self._operation_running():
        self._set_status(f"{self.state.operation_run.label} already running.")
        return
    self.state.operation_run = TUIOperationRunState(is_running=True, kind=kind, label=label)
    self._set_status(f"{label}...")
    worker = self.run_worker(
        work,
        name=f"operation-{kind}",
        group="operation",
        thread=True,
        exit_on_error=False,
    )
    self._active_operation_worker = worker

def action_cancel_operation(self) -> None:
    worker = self._active_operation_worker
    if worker is None or worker.is_finished:
        return
    label = self.state.operation_run.label
    self._cancelled_operation_names.add(worker.name or "")
    worker.cancel()
    self.state.operation_run = TUIOperationRunState()
    self._active_operation_worker = None
    self._set_status(f"Cancelled {label}.")
```

Import `TUIOperationKind` and `TUIOperationRunState` from `csvql.tui_state`.

- [ ] **Step 6: Move source operations into workers**

Define small outcome dataclasses in `src/csvql/tui_app.py` near modal classes:

```python
@dataclass(frozen=True, slots=True)
class _SourceInspectOutcome:
    source_name: str
    columns: tuple[TUISourceColumn, ...]

@dataclass(frozen=True, slots=True)
class _SourceSampleOutcome:
    source_name: str
    result: SampleResult

@dataclass(frozen=True, slots=True)
class _SourceProfileOutcome:
    source_name: str
    result: ProfileResult

@dataclass(frozen=True, slots=True)
class _SourceColumnsOutcome:
    source_name: str
    columns: tuple[TUISourceColumn, ...]
```

Add required imports:

```python
from dataclasses import dataclass
from csvql.models import ProfileResult, QueryResult, SampleResult
```

Change `action_inspect_source()` to start a worker:

```python
def action_inspect_source(self) -> None:
    source = self.state.selected_source()
    if source is None:
        self._show_error(CSVQLError("No source selected."))
        return

    self._start_operation_worker(
        kind="inspect",
        label=f"Inspecting {source.name}",
        work=lambda: _SourceInspectOutcome(
            source_name=source.name,
            columns=tuple(
                TUISourceColumn(name=column.name, duckdb_type=column.duckdb_type)
                for column in inspect_source(source).columns
            ),
        ),
    )
```

Apply the same pattern to `sample`, `profile`, and `columns`.

- [ ] **Step 7: Handle operation worker completion**

Update `on_worker_state_changed()` before the query branch:

```python
if worker.group == "operation":
    self._handle_operation_worker_state(worker, event.state)
    return
```

Add:

```python
def _handle_operation_worker_state(self, worker: Worker[object], state: WorkerState) -> None:
    if not worker.is_finished:
        return
    worker_name = worker.name or ""
    if worker_name in self._cancelled_operation_names:
        self._cancelled_operation_names.discard(worker_name)
        return
    if state == WorkerState.ERROR:
        self.state.operation_run = TUIOperationRunState()
        self._active_operation_worker = None
        self._show_error(CSVQLError("Operation failed.", suggestion=str(worker.error)))
        return
    if state != WorkerState.SUCCESS:
        return
    self.state.operation_run = TUIOperationRunState()
    self._active_operation_worker = None
    self._apply_operation_outcome(worker.result)
```

Add `_apply_operation_outcome()` that renders the four source outcomes with the same table/status behavior the synchronous actions previously used.

- [ ] **Step 8: Disable duplicate operation starts in `check_action()`**

Add near the top of `check_action()` after modal gating:

```python
operation_actions = {
    "inspect_source",
    "sample_source",
    "profile_source",
    "show_source_columns",
    "export_last_result",
    "save_result_as_source",
}
if self._operation_running() and action in operation_actions:
    return False
```

- [ ] **Step 9: Run focused tests**

Run the command from Step 4 plus existing source intelligence tests:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py -k "source_intelligence or inspect_sample_and_profile" -q
```

Expected: PASS.

- [ ] **Step 10: Commit Task 4**

```bash
git add src/csvql/tui_app.py src/csvql/tui_state.py tests/test_tui_app.py
git commit -m "feat: workerize TUI source actions"
```

---

### Task 5: P2 Atomic Text Write Primitive

**Files:**
- Create: `src/csvql/atomic_write.py`
- Modify: `src/csvql/export.py`
- Modify: `src/csvql/tui_workflows.py`
- Modify: `src/csvql/project_config.py`
- Test: `tests/test_atomic_write.py`
- Test: `tests/test_export.py`
- Test: `tests/test_tui_workflows.py`

**Interfaces:**
- Produces: `OperationCancelled`, `OperationToken`, and `write_text_atomic(path: Path, content: str, *, encoding: str = "utf-8", newline: str | None = None, token: OperationToken | None = None) -> None`.
- Consumed by later export/save worker tasks and by project/export helpers.

- [ ] **Step 1: Create failing atomic write tests**

Create `tests/test_atomic_write.py`:

```python
from pathlib import Path

import pytest

from csvql.atomic_write import OperationCancelled, OperationToken, write_text_atomic


def test_write_text_atomic_writes_final_content(tmp_path: Path) -> None:
    output_path = tmp_path / "result.txt"

    write_text_atomic(output_path, "hello\n")

    assert output_path.read_text(encoding="utf-8") == "hello\n"
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_write_text_atomic_preserves_previous_file_when_cancelled_before_replace(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "result.txt"
    output_path.write_text("old\n", encoding="utf-8")
    token = OperationToken()
    token.cancel()

    with pytest.raises(OperationCancelled):
        write_text_atomic(output_path, "new\n", token=token)

    assert output_path.read_text(encoding="utf-8") == "old\n"
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))
```

- [ ] **Step 2: Run failing tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_atomic_write.py -q
```

Expected: FAIL because `csvql.atomic_write` does not exist.

- [ ] **Step 3: Implement atomic write helper**

Create `src/csvql/atomic_write.py`:

```python
"""Atomic local text writes for user-visible CSVQL outputs."""

import os
import tempfile
import threading
from pathlib import Path


class OperationCancelled(Exception):
    """Raised when a cancellable local operation is cancelled before commit."""


class OperationToken:
    """Thread-safe cancellation token for local TUI/file operations."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise OperationCancelled("Operation cancelled.")


def write_text_atomic(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
    token: OperationToken | None = None,
) -> None:
    """Write text through a temp sibling file and atomically replace the target."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if token is not None:
        token.raise_if_cancelled()

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        if token is not None:
            token.raise_if_cancelled()
        os.replace(temp_path, path)
    except BaseException:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise
```

- [ ] **Step 4: Use atomic writes in export, derived results, and project config**

In `src/csvql/export.py`, import `write_text_atomic` and replace `path.write_text(...)`:

```python
from csvql.atomic_write import write_text_atomic
...
write_text_atomic(path, content)
```

In `src/csvql/tui_workflows.py`, import `write_text_atomic` and replace `_write_derived_result_file()` file opening with:

```python
if path.exists():
    raise ExportError(
        f"Derived result already exists at {path}.",
        suggestion="Choose a different alias for this derived result source.",
    )
write_text_atomic(path, content, newline="")
```

In `src/csvql/project_config.py`, import `write_text_atomic` and replace `config_path.write_text(...)` in `save_project()`:

```python
write_text_atomic(
    config_path,
    yaml.safe_dump(payload, sort_keys=False),
)
```

- [ ] **Step 5: Run atomic/export/workflow tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_atomic_write.py tests/test_export.py tests/test_tui_workflows.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/csvql/atomic_write.py src/csvql/export.py src/csvql/tui_workflows.py src/csvql/project_config.py tests/test_atomic_write.py tests/test_export.py tests/test_tui_workflows.py
git commit -m "feat: add atomic output writes"
```

---

### Task 6: P1 Workerized Export And Save-As-Source With Cancellation

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `src/csvql/tui_workflows.py`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: `OperationToken`, `OperationCancelled`, `write_text_atomic()`, Task 4 operation worker state.
- Produces: export/save-as-source workers that can be cancelled before final output is committed.

- [ ] **Step 1: Extend workflow helpers to accept cancellation tokens**

In `src/csvql/tui_workflows.py`, update signatures:

```python
from csvql.atomic_write import OperationToken

def export_last_result(
    result: QueryResult,
    path_value: str,
    *,
    export_format: ExportFormat,
    base_dir: Path,
    force: bool = False,
    token: OperationToken | None = None,
) -> Path:
    ...
    write_export_file(output_path, content, token=token)
    return output_path
```

Update `write_export_file()` in `src/csvql/export.py`:

```python
def write_export_file(path: Path, content: str, *, token: OperationToken | None = None) -> None:
    """Write export content as UTF-8 text."""

    try:
        write_text_atomic(path, content, token=token)
    except OperationCancelled:
        raise
    except OSError as exc:
        raise ExportError(
            f"Failed to write export output: {path}",
            suggestion="Check that the output path is writable.",
        ) from exc
```

Update `save_derived_result_source(..., token: OperationToken | None = None)` and pass `token` into `_write_derived_result_file()`.

- [ ] **Step 2: Add failing export cancellation test**

Add to `tests/test_tui_app.py`:

```python
def test_escape_cancels_running_export_before_final_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    export_path = tmp_path / "exports" / "customers.csv"
    export_path.parent.mkdir()
    state = TUISessionState()
    state.set_last_result(QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0))
    started = threading.Event()
    release = threading.Event()

    def slow_export_last_result(*args, **kwargs):
        token = kwargs["token"]
        started.set()
        release.wait(timeout=2)
        token.raise_if_cancelled()
        return export_last_result(*args, **kwargs)

    monkeypatch.setattr("csvql.tui_app.export_last_result", slow_export_last_result)

    async def _inner() -> tuple[str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f7")
            await pilot.pause()
            app.screen.query_one("#export-path", Input).value = str(export_path)
            await pilot.press("enter")
            await pilot.pause(0.1)
            await pilot.press("escape")
            await pilot.pause()
            release.set()
            await pilot.pause(0.2)
            return app.query_one("#status", Static).content, export_path.exists()

    status, exists = asyncio.run(_inner())

    assert started.is_set()
    assert "Cancelled Exporting active result." in status
    assert exists is False
```

- [ ] **Step 3: Run focused failing test**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_escape_cancels_running_export_before_final_file -q
```

Expected: FAIL before workerized export/save.

- [ ] **Step 4: Add file operation outcomes**

In `src/csvql/tui_app.py`, add:

```python
@dataclass(frozen=True, slots=True)
class _ExportOutcome:
    path: Path

@dataclass(frozen=True, slots=True)
class _SaveResultSourceOutcome:
    source: TUISource
```

Track operation tokens:

```python
self._active_operation_token: OperationToken | None = None
```

Update `_start_operation_worker()` to create/store a token and call a `work(token)` callback:

```python
def _start_operation_worker(
    self,
    *,
    kind: TUIOperationKind,
    label: str,
    work: Callable[[OperationToken], object],
) -> None:
    ...
    token = OperationToken()
    self._active_operation_token = token
    worker = self.run_worker(
        lambda: work(token),
        name=f"operation-{kind}",
        group="operation",
        thread=True,
        exit_on_error=False,
    )
```

Update source worker callers to accept `_token` and ignore it.

- [ ] **Step 5: Start export/save workers from prompt callbacks**

In `_handle_export_last_result()`, after validation, start the worker:

```python
export_path_value, export_format = _export_path_and_format_for_prompt(path_value)
self._start_operation_worker(
    kind="export",
    label="Exporting active result",
    work=lambda token: _ExportOutcome(
        path=export_last_result(
            result,
            export_path_value,
            export_format=export_format,
            base_dir=self.start_dir,
            force=False,
            token=token,
        )
    ),
)
```

In `_handle_save_result_as_source()`, start a `"save_result"` worker with `save_derived_result_source(..., token=token)`.

- [ ] **Step 6: Apply export/save outcomes**

Extend `_apply_operation_outcome()`:

```python
if isinstance(outcome, _ExportOutcome):
    display_path = _display_path(outcome.path, self.start_dir)
    self._set_status(f"Exported to {display_path}.")
    self.query_one("#results-message", Static).update(f"Exported to {display_path}.")
    return

if isinstance(outcome, _SaveResultSourceOutcome):
    source = outcome.source
    self.state.add_source(source)
    self.state.select_source(source.name)
    self._refresh_sources_table()
    display_path = _display_path(source.path, self.start_dir)
    message = (
        f"Saved result as derived source {source.name} at {display_path}. "
        "Use Save sources to persist the alias in .csvql.yml."
    )
    self._set_status(message)
    self.query_one("#results-message", Static).update(message)
    return
```

In `action_cancel_operation()`, cancel the token before cancelling the worker:

```python
if self._active_operation_token is not None:
    self._active_operation_token.cancel()
```

Clear `_active_operation_token` when worker finishes.

- [ ] **Step 7: Run export/save worker tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py -k "export_last_result or save_result_as_source or cancels_running_export" -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 6**

```bash
git add src/csvql/tui_app.py src/csvql/tui_workflows.py src/csvql/export.py tests/test_tui_app.py
git commit -m "feat: workerize TUI result writes"
```

---

### Task 7: P1 Buffer Discoverability And Minimum Terminal Warning

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `src/csvql/tui_help.py`
- Modify: `README.md`
- Modify: `docs/tui-guide.md`
- Test: `tests/test_tui_app.py`
- Test: `tests/test_v1_polish_docs.py`

**Interfaces:**
- Consumes: Task 1 Results-only buffer navigation.
- Produces: visible buffer selector instructions and terminal-size warning helper.

- [ ] **Step 1: Add failing buffer selector docs/UI test**

```python
def test_buffer_result_tabs_show_navigation_hint(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text(
                "SELECT customer_id FROM customers ORDER BY customer_id;"
                "SELECT email FROM customers ORDER BY email;"
            )
            await pilot.press("f12")
            await pilot.pause(0.2)
            return app.query_one("#result-tabs", Static).content

    tabs = asyncio.run(_inner())

    assert "Buffer results" in tabs
    assert "[/] Results only" not in tabs
    assert "[ / ]" not in tabs
    assert "[ and ]" in tabs
```

- [ ] **Step 2: Add terminal-size helper test**

Add pure helper tests:

```python
def test_terminal_size_warning_below_minimum(tmp_path: Path) -> None:
    app = CSVQLMenuApp(start_dir=tmp_path)

    assert app._terminal_size_warning(width=99, height=30) == (
        "Terminal too small for full workbench; use at least 100x30."
    )
    assert app._terminal_size_warning(width=100, height=29) == (
        "Terminal too small for full workbench; use at least 100x30."
    )
    assert app._terminal_size_warning(width=100, height=30) is None
```

- [ ] **Step 3: Run focused failing tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_buffer_result_tabs_show_navigation_hint \
  tests/test_tui_app.py::test_terminal_size_warning_below_minimum -q
```

Expected: FAIL.

- [ ] **Step 4: Implement selector hint and terminal warning helper**

In `src/csvql/tui_app.py`, add constants:

```python
_MIN_TERMINAL_WIDTH = 100
_MIN_TERMINAL_HEIGHT = 30
_RECOMMENDED_TERMINAL_WIDTH = 120
_RECOMMENDED_TERMINAL_HEIGHT = 36
```

Update `_result_tabs_text()`:

```python
return "Buffer results ([ and ] in Results): " + " | ".join(entries)
```

Add helper:

```python
def _terminal_size_warning(self, *, width: int, height: int) -> str | None:
    if width < _MIN_TERMINAL_WIDTH or height < _MIN_TERMINAL_HEIGHT:
        return (
            "Terminal too small for full workbench; "
            f"use at least {_MIN_TERMINAL_WIDTH}x{_MIN_TERMINAL_HEIGHT}."
        )
    return None
```

Add a new resize handler and update status/context when warning applies:

```python
def on_resize(self, event: events.Resize) -> None:
    warning = self._terminal_size_warning(width=event.size.width, height=event.size.height)
    if warning is not None:
        self._set_status(warning)
```

- [ ] **Step 5: Update docs/help**

In `src/csvql/tui_help.py`, add under Results or General:

```text
  [ / ]               Previous/next buffer result when Results is focused
```

In `docs/tui-guide.md`, document:

```markdown
The full workbench needs at least 100 columns by 30 rows. A 120x36 terminal is recommended.
```

- [ ] **Step 6: Run focused tests**

Run the command from Step 3 and docs tests:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_buffer_result_tabs_show_navigation_hint \
  tests/test_tui_app.py::test_terminal_size_warning_below_minimum \
  tests/test_v1_polish_docs.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 7**

```bash
git add src/csvql/tui_app.py src/csvql/tui_help.py README.md docs/tui-guide.md tests/test_tui_app.py tests/test_v1_polish_docs.py
git commit -m "docs: surface TUI buffer navigation"
```

---

### Task 8: P2 Temp-Backed TUI Result Store

**Files:**
- Create: `src/csvql/tui_result_store.py`
- Modify: `src/csvql/tui_state.py`
- Modify: `src/csvql/tui_app.py`
- Test: `tests/test_tui_result_store.py`
- Test: `tests/test_tui_state.py`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Produces: `TUIResultStore`, `TUIStoredResult`, `TUIResultHandle`, and spill thresholds.
- Consumed by export/save/history recall in later tasks.

- [ ] **Step 1: Create failing result store tests**

Create `tests/test_tui_result_store.py`:

```python
from csvql.models import QueryResult
from csvql.tui_result_store import (
    TUI_RESULT_SPILL_CELL_THRESHOLD,
    TUI_RESULT_SPILL_ROW_THRESHOLD,
    TUIResultStore,
)


def _result(row_count: int, column_count: int = 1) -> QueryResult:
    columns = tuple(f"c{index}" for index in range(column_count))
    rows = tuple(tuple(f"{row}-{column}" for column in range(column_count)) for row in range(row_count))
    return QueryResult(columns=columns, rows=rows, elapsed_ms=1.0)


def test_result_store_keeps_small_results_in_memory(tmp_path):
    store = TUIResultStore(temp_root=tmp_path)
    handle = store.put(_result(2), sequence=1)

    assert handle.is_spilled is False
    assert store.get(handle).row_count == 2


def test_result_store_spills_large_row_count(tmp_path):
    store = TUIResultStore(temp_root=tmp_path)
    handle = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert handle.is_spilled is True
    assert handle.temp_path is not None
    assert handle.temp_path.exists()
    assert store.get(handle).row_count == TUI_RESULT_SPILL_ROW_THRESHOLD + 1


def test_result_store_spills_large_cell_count(tmp_path):
    row_count = 101
    column_count = (TUI_RESULT_SPILL_CELL_THRESHOLD // row_count) + 1
    store = TUIResultStore(temp_root=tmp_path)
    handle = store.put(_result(row_count, column_count), sequence=2)

    assert handle.is_spilled is True
    assert store.get(handle).row_count == row_count


def test_result_store_cleanup_removes_spilled_files(tmp_path):
    store = TUIResultStore(temp_root=tmp_path)
    handle = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    assert handle.temp_path is not None

    store.cleanup()

    assert not handle.temp_path.exists()
```

- [ ] **Step 2: Run failing store tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_result_store.py -q
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement `tui_result_store.py`**

Create `src/csvql/tui_result_store.py`:

```python
"""Session-local result storage for the CSVQL TUI."""

import pickle
import tempfile
from dataclasses import dataclass
from pathlib import Path

from csvql.models import QueryResult

TUI_RESULT_SPILL_ROW_THRESHOLD = 10_000
TUI_RESULT_SPILL_CELL_THRESHOLD = 250_000


@dataclass(frozen=True, slots=True)
class TUIResultHandle:
    """Reference to a stored TUI query result."""

    sequence: int
    is_spilled: bool
    temp_path: Path | None = None


@dataclass(frozen=True, slots=True)
class TUIStoredResult:
    """Stored full result plus its lookup handle."""

    handle: TUIResultHandle
    result: QueryResult | None = None


class TUIResultStore:
    """Store small results in memory and large results in session temp files."""

    def __init__(self, *, temp_root: Path | None = None) -> None:
        self._memory_results: dict[int, QueryResult] = {}
        self._temp_dir = tempfile.TemporaryDirectory(
            prefix="csvql-tui-results-",
            dir=str(temp_root) if temp_root is not None else None,
        )
        self._temp_paths: set[Path] = set()

    def put(self, result: QueryResult, *, sequence: int) -> TUIResultHandle:
        if _should_spill(result):
            temp_path = Path(self._temp_dir.name) / f"query-{sequence}.pickle"
            with temp_path.open("wb") as file:
                pickle.dump(result, file, protocol=pickle.HIGHEST_PROTOCOL)
            self._temp_paths.add(temp_path)
            return TUIResultHandle(sequence=sequence, is_spilled=True, temp_path=temp_path)
        self._memory_results[sequence] = result
        return TUIResultHandle(sequence=sequence, is_spilled=False)

    def get(self, handle: TUIResultHandle) -> QueryResult:
        if not handle.is_spilled:
            return self._memory_results[handle.sequence]
        if handle.temp_path is None:
            raise KeyError(f"Missing temp path for result {handle.sequence}.")
        with handle.temp_path.open("rb") as file:
            loaded = pickle.load(file)
        if not isinstance(loaded, QueryResult):
            raise TypeError(f"Unexpected stored result type: {type(loaded).__name__}")
        return loaded

    def cleanup(self) -> None:
        for path in tuple(self._temp_paths):
            path.unlink(missing_ok=True)
        self._temp_paths.clear()
        self._temp_dir.cleanup()


def _should_spill(result: QueryResult) -> bool:
    if result.row_count > TUI_RESULT_SPILL_ROW_THRESHOLD:
        return True
    return result.row_count * len(result.columns) > TUI_RESULT_SPILL_CELL_THRESHOLD
```

- [ ] **Step 4: Integrate handles into session state**

In `src/csvql/tui_state.py`, import `TUIResultHandle` and add:

```python
_query_result_handles: dict[int, TUIResultHandle] = field(default_factory=dict)
```

Add methods:

```python
def record_query_result_handle(self, sequence: int, handle: TUIResultHandle) -> None:
    self._query_result_handles[sequence] = handle

def query_result_handle(self, sequence: int) -> TUIResultHandle | None:
    return self._query_result_handles.get(sequence)
```

Keep `_query_results` during this task for backward compatibility. Later tasks can read through the store first.

- [ ] **Step 5: Add store to app and record handles**

In `CSVQLMenuApp.__init__()`:

```python
from csvql.tui_result_store import TUIResultStore
...
self._result_store = TUIResultStore()
```

In `_handle_query_outcome()` and `_handle_buffer_outcomes()`, before `record_query_success()`:

```python
handle = self._result_store.put(outcome.result, sequence=outcome.sequence)
self.state.record_query_result_handle(outcome.sequence, handle)
```

Add `on_unmount()`:

```python
def on_unmount(self) -> None:
    self._result_store.cleanup()
```

- [ ] **Step 6: Run store and focused TUI tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_result_store.py tests/test_tui_state.py tests/test_tui_app.py -k "runs_query or buffer or history" -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 8**

```bash
git add src/csvql/tui_result_store.py src/csvql/tui_state.py src/csvql/tui_app.py tests/test_tui_result_store.py tests/test_tui_state.py tests/test_tui_app.py
git commit -m "feat: add TUI result store"
```

---

### Task 9: P2 Use Result Store For Export, Save, History, And Preview Labels

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `src/csvql/tui_state.py`
- Modify: `src/csvql/tui_results.py`
- Test: `tests/test_tui_app.py`
- Test: `tests/test_tui_state.py`

**Interfaces:**
- Consumes: Task 8 `TUIResultStore`.
- Produces: full spilled-result export/save and bounded preview labels.

- [ ] **Step 1: Add failing spilled export test**

In `tests/test_tui_app.py`, add:

```python
def test_export_from_spilled_result_writes_full_output(tmp_path: Path) -> None:
    export_path = tmp_path / "exports" / "large.csv"
    export_path.parent.mkdir()
    rows = tuple((index,) for index in range(10001))
    state = TUISessionState()
    result = QueryResult(columns=("id",), rows=rows, elapsed_ms=1.0)

    async def _inner() -> tuple[int, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            handle = app._result_store.put(result, sequence=1)
            app.state.record_query_result_handle(1, handle)
            view = make_result_view_state(result, source_result_sequence=1)
            app.state.record_query_success(1, "SELECT * FROM large", result, view)
            app._refresh_results_display()
            await pilot.press("f7")
            await pilot.pause()
            app.screen.query_one("#export-path", Input).value = str(export_path)
            await pilot.press("enter")
            await pilot.pause(0.5)
            return len(export_path.read_text(encoding="utf-8").splitlines()), app.query_one("#results-message", Static).content

    line_count, message = asyncio.run(_inner())

    assert line_count == 10002
    assert "Showing first 1,000 of 10,001 returned row(s)." in message
```

Add imports in the test file:

```python
from csvql.tui_results import make_result_view_state
```

- [ ] **Step 2: Run failing test**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_export_from_spilled_result_writes_full_output -q
```

Expected: FAIL until export reads from the result store and message wording is updated.

- [ ] **Step 3: Add active result access helper**

In `CSVQLMenuApp`, add:

```python
def _active_query_result(self) -> QueryResult | None:
    sequence = self.state.active_result.sequence
    if sequence is not None:
        handle = self.state.query_result_handle(sequence)
        if handle is not None:
            return self._result_store.get(handle)
    return self.state.last_result
```

Use `_active_query_result()` in `action_export_last_result()`, `_handle_export_last_result()`, `action_save_result_as_source()`, and `_handle_save_result_as_source()`.

- [ ] **Step 4: Improve preview message**

In `_result_message(view)`, change truncated wording to:

```python
if view.is_truncated:
    return (
        f"Showing first {len(view.display_rows):,} of {view.total_row_count:,} "
        "returned row(s). Export/save use the full active result."
    )
```

Keep non-truncated wording unchanged except for commas if existing tests are updated consistently.

- [ ] **Step 5: Run focused tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_export_from_spilled_result_writes_full_output \
  tests/test_tui_app.py -k "export_last_result or save_result_as_source or history" -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 9**

```bash
git add src/csvql/tui_app.py src/csvql/tui_state.py src/csvql/tui_results.py tests/test_tui_app.py tests/test_tui_state.py
git commit -m "feat: export stored TUI results"
```

---

### Task 10: P2 Warn-But-Allow External Catalog Paths

**Files:**
- Modify: `src/csvql/tui_workflows.py`
- Modify: `src/csvql/tui_app.py`
- Modify: `README.md`
- Modify: `docs/tui-guide.md`
- Test: `tests/test_tui_workflows.py`
- Test: `tests/test_tui_app.py`
- Test: `tests/test_v1_polish_docs.py`

**Interfaces:**
- Produces: `external_catalog_source_paths(sources: Sequence[TUISource], *, start_dir: Path) -> tuple[Path, ...]`.
- Consumed by catalog save confirmation prompt.

- [ ] **Step 1: Add failing path policy tests**

In `tests/test_tui_workflows.py`, add:

```python
def test_external_catalog_source_paths_detects_absolute_external_path(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    project_root.mkdir()
    external_root.mkdir()
    external_csv = _write_csv(external_root / "orders.csv")
    source = TUISource(name="orders", path=external_csv.resolve(), origin="session")

    paths = external_catalog_source_paths((source,), start_dir=project_root)

    assert paths == (external_csv.resolve(),)
```

In `tests/test_tui_app.py`, add:

```python
def test_save_sources_confirmation_warns_for_external_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    project_root.mkdir()
    external_root.mkdir()
    external_csv = _create_csv(external_root, "orders.csv", "id\n1\n")
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=external_csv.resolve(), origin="session"))

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=project_root)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("w")
            await pilot.pause()
            return app.screen.query_one("#confirm-text", Static).content

    prompt = asyncio.run(_inner())

    assert "external local filesystem path" in prompt
    assert "may reveal machine-specific locations" in prompt
```

- [ ] **Step 2: Run failing tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_workflows.py::test_external_catalog_source_paths_detects_absolute_external_path \
  tests/test_tui_app.py::test_save_sources_confirmation_warns_for_external_paths -q
```

Expected: FAIL before helper exists.

- [ ] **Step 3: Implement path warning helper**

In `src/csvql/tui_workflows.py`, add:

```python
def external_catalog_source_paths(
    sources: Sequence[TUISource],
    *,
    start_dir: Path,
) -> tuple[Path, ...]:
    """Return source paths that resolve outside the TUI start directory."""

    base_dir = start_dir.expanduser().resolve()
    external_paths: list[Path] = []
    for source in sources:
        resolved_path = source.path.expanduser().resolve(strict=False)
        try:
            resolved_path.relative_to(base_dir)
        except ValueError:
            external_paths.append(resolved_path)
    return tuple(external_paths)
```

In `src/csvql/tui_app.py`, import the helper and update `action_save_sources()` prompt:

```python
external_paths = external_catalog_source_paths(self.state.sources, start_dir=self.start_dir)
warning = ""
if external_paths:
    warning = (
        " Warning: this catalog will persist external local filesystem paths "
        "and may reveal machine-specific locations if shared."
    )
self.push_screen(
    _ConfirmationScreen(
        f"Save {source_count} {noun} to .csvql.yml?{warning} "
        "Press y to save or n to cancel."
    ),
    callback=self._handle_save_sources_confirmation,
)
```

- [ ] **Step 4: Update docs**

Add to README/TUI guide source catalog sections:

```markdown
Saving sources to `.csvql.yml` may persist local filesystem paths. Project-relative paths are portable; external absolute paths are allowed for local workflows but can reveal machine-specific locations if you share the catalog.
```

Add docs test:

```python
def test_docs_warn_catalog_paths_can_reveal_local_locations() -> None:
    docs = "\n".join([read_doc("README.md"), read_doc("docs/tui-guide.md")])

    assert "external absolute paths are allowed for local workflows" in docs
    assert "machine-specific locations" in docs
```

- [ ] **Step 5: Run focused tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_workflows.py::test_external_catalog_source_paths_detects_absolute_external_path \
  tests/test_tui_app.py::test_save_sources_confirmation_warns_for_external_paths \
  tests/test_v1_polish_docs.py::test_docs_warn_catalog_paths_can_reveal_local_locations -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 10**

```bash
git add src/csvql/tui_workflows.py src/csvql/tui_app.py README.md docs/tui-guide.md tests/test_tui_workflows.py tests/test_tui_app.py tests/test_v1_polish_docs.py
git commit -m "feat: warn on external catalog paths"
```

---

### Task 11: P2 Paste/Drop-Only CSV Path Ingestion

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `docs/tui-guide.md`
- Modify: `docs/tui-qol-qa.md`
- Test: `tests/test_tui_app.py`
- Test: `tests/test_v1_polish_docs.py`

**Interfaces:**
- Consumes: existing `_SourcePathTextArea._on_paste()` and `_handle_pasted_csv_sources()`.
- Produces: no automatic ingestion from ordinary `TextArea.Changed` events.

- [ ] **Step 1: Add failing ordinary-editor-change test**

```python
def test_editor_text_change_to_csv_path_does_not_add_source(tmp_path: Path) -> None:
    csv_path = _create_csv(tmp_path, "customers.csv", "id\n1\n")

    async def _inner() -> tuple[str, tuple[TUISource, ...]]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text(str(csv_path))
            await pilot.pause(0.2)
            return sql.text, app.state.sources

    editor_text, sources = asyncio.run(_inner())

    assert editor_text == str(csv_path)
    assert sources == ()
```

- [ ] **Step 2: Run failing test**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py::test_editor_text_change_to_csv_path_does_not_add_source \
  tests/test_tui_app.py::test_pasted_csv_path_adds_source_without_inserting_editor_text -q
```

Expected: new ordinary-change test FAILS; paste test should still PASS after implementation.

- [ ] **Step 3: Remove timer-based text-change ingestion**

In `CSVQLMenuApp.on_text_area_changed()`, remove the call to `_consume_sql_editor_csv_path_text()` and leave the method as:

```python
def on_text_area_changed(self, event: TextArea.Changed) -> None:
    if event.text_area.id == "sql":
        self._sql_source_text_revision += 1
```

In `_schedule_editor_query()`, remove the pre-run call:

```python
if self._consume_sql_editor_csv_path_text(self.query_one("#sql", TextArea)):
    return
```

Keep `_consume_sql_editor_csv_path_text()` only if existing paste/drop cleanup still needs it; otherwise remove it and its tests in the same task.

- [ ] **Step 4: Keep paste/drop behavior**

Do not change `_SourcePathTextArea._on_paste()` except as needed for removed suppression flags. It should still call `_handle_pasted_csv_sources(event.text)`.

Do not add a drop handler in this task. Keep the implementation to paste events because the current app has no drop handler.

- [ ] **Step 5: Update docs and QA matrix**

Change docs language from "editor changes can turn standalone paths into sources" to:

```markdown
Pasting or dropping standalone `.csv` path text into the SQL editor adds session sources. Typing a path as ordinary editor text leaves it as SQL/editor text.
```

Add docs test:

```python
def test_docs_limit_csv_path_ingestion_to_paste_or_drop() -> None:
    docs = "\n".join([read_doc("docs/tui-guide.md"), read_doc("docs/tui-qol-qa.md")])

    assert "Pasting or dropping standalone `.csv` path text" in docs
    assert "ordinary editor text leaves it" in docs
```

- [ ] **Step 6: Run focused tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_app.py -k "csv_path or paste" \
  tests/test_v1_polish_docs.py::test_docs_limit_csv_path_ingestion_to_paste_or_drop -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 11**

```bash
git add src/csvql/tui_app.py docs/tui-guide.md docs/tui-qol-qa.md tests/test_tui_app.py tests/test_v1_polish_docs.py
git commit -m "fix: limit TUI CSV ingestion to paste"
```

---

### Task 12: P2 History Preview Performance And Final Verification Gate

**Files:**
- Modify: `src/csvql/tui_app.py`
- Modify: `src/csvql/tui_state.py`
- Modify: `docs/tui-guide.md`
- Test: `tests/test_tui_app.py`
- Test: `tests/test_tui_state.py`
- Test: `tests/test_v1_polish_docs.py`

**Interfaces:**
- Consumes: Task 8 result handles and preview state.
- Produces: history recall that reuses stored preview state and final docs alignment.

- [ ] **Step 1: Add preview reuse test**

In `tests/test_tui_state.py`, add:

```python
def test_restore_query_result_reuses_stored_result_view() -> None:
    state = TUISessionState()
    result = QueryResult(columns=("id",), rows=tuple((index,) for index in range(1001)), elapsed_ms=1.0)
    view = TUIResultViewState(
        columns=("id",),
        display_rows=(("0",),),
        total_row_count=1001,
        is_truncated=True,
        source_result_sequence=1,
    )
    state.record_query_success(1, "SELECT * FROM large", result, view)
    state.clear_last_result()

    restored = state.restore_query_result(1)

    assert restored is True
    assert state.result_view is view
    assert state.result_view.display_rows == (("0",),)
```

- [ ] **Step 2: Add docs test for F4 versus Run Buffer sessions**

```python
def test_docs_distinguish_f4_and_run_buffer_sessions() -> None:
    guide = read_doc("docs/tui-guide.md")

    assert "F4" in guide
    assert "fresh DuckDB session" in guide
    assert "Run Buffer" in guide
    assert "one shared DuckDB session" in guide
```

- [ ] **Step 3: Run focused tests**

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest \
  tests/test_tui_state.py::test_restore_query_result_reuses_stored_result_view \
  tests/test_v1_polish_docs.py::test_docs_distinguish_f4_and_run_buffer_sessions -q
```

Expected: state test likely PASS already; docs test may FAIL until wording is added.

- [ ] **Step 4: Update docs**

In `docs/tui-guide.md`, add:

```markdown
`F4` or `Ctrl+R` runs the selected/current statement in a fresh DuckDB session. `F12` or `Ctrl+B` Run Buffer runs the editor's semicolon-delimited statements in one shared DuckDB session, so earlier temporary tables can feed later statements in that buffer.
```

- [ ] **Step 5: Run full phase verification**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras mypy src
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest
git diff --check
```

Expected:

- Ruff format check PASS.
- Ruff check PASS.
- mypy PASS.
- pytest PASS.
- diff check PASS.

- [ ] **Step 6: Confirm no release/publish drift**

Run:

```bash
git status --short --branch
git log -1 --oneline
git remote -v
git tag --points-at HEAD
```

Expected:

- Branch remains `fix/tui-help-run-labels`.
- No remote output unless the user separately configured one.
- No tag output unless the user separately created one.
- No untracked generated artifacts from tests.

- [ ] **Step 7: Commit Task 12**

```bash
git add src/csvql/tui_app.py src/csvql/tui_state.py docs/tui-guide.md tests/test_tui_app.py tests/test_tui_state.py tests/test_v1_polish_docs.py
git commit -m "docs: finalize TUI follow-up gates"
```

---

## Plan Self-Review Checklist

- P0 modal action leakage: Task 1.
- P0 hidden buffer navigation outside Results: Task 1.
- P0 export confirmation clearing visible result grid: Task 2.
- P0 unconfirmed source catalog save: Task 2.
- P0 active-result and `.markdown` docs/help drift: Task 3.
- P1 source intelligence workers: Task 4.
- P1 export/save workers and cancellation: Task 6.
- P1 buffer result discoverability: Task 7.
- P1 minimum terminal size warning: Task 7.
- P2 atomic writes: Task 5.
- P2 temp-backed result storage: Tasks 8 and 9.
- P2 warn-but-allow external paths: Task 10.
- P2 paste/drop-only CSV ingestion: Task 11.
- P2 history preview performance and F4/Run Buffer docs: Task 12.
- Verification and no-release-drift gates: Task 12.
