# CSVQL TUI Error Recovery Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the previous successful TUI query result when a run action is rejected before DuckDB execution starts.

**Architecture:** Keep the fix inside the optional Textual TUI. Add focused app tests for rejected-run recovery, then route only rejected run branches through a small `CSVQLMenuApp` helper that updates status surfaces without clearing result state or the visible result grid.

**Tech Stack:** Python 3.11+, DuckDB, Textual `TextArea` and `DataTable`, pytest, Ruff, uv.

---

## Review Status

This plan follows:

- `docs/superpowers/specs/2026-07-02-csvql-tui-error-recovery-polish-design.md`
- spec correction commit `3924757`

At plan-writing time, the repository is on `main` with a clean tracked tree
after the spec correction commit. Do not stage or commit `.superpowers/`.

## Scope Check

This plan implements only rejected-run recovery inside `csvql menu`.

It does not implement:

- CLI command changes
- Python API changes
- DuckDB engine changes
- project catalog schema changes
- persisted query history
- new TUI panes, modals, or layout changes
- cancellation support
- retry buttons
- SQL parsing or validation changes
- README, release-readiness, benchmark, tag, publish, or `v1-stable` changes
- safe mode, sandboxing, production-readiness, hidden cache, broad materialization, dataframe runtime, cloud connectors, web UI, notebooks, AI, plugins, or large-file proof claims

## Required Skills At Execution Time

Before executing code tasks, load:

- `python-codebase-standards`
- `testing-strategy`
- `security-best-practices`
- `superpowers:test-driven-development`
- `code-review`
- `superpowers:verification-before-completion`

## File Structure

Modify:

- `tests/test_tui_app.py`: add focused Textual app tests that prove rejected run actions preserve previous result state, result view state, the visible grid, query history, and run-status behavior.
- `src/csvql/tui_app.py`: add one local rejected-run display helper and route only pre-execution rejected run branches through it.

Preserve:

- `src/csvql/tui_state.py`: no state-model change is expected.
- `src/csvql/tui_workflows.py`: DuckDB execution and source registration stay unchanged.
- `src/csvql/cli.py`: CLI boundary stays untouched.
- `README.md` and release docs: no user-facing command or release-status docs change in this slice.
- `.superpowers/`: generated state remains untracked unless Richard explicitly approves tracking it.

## Direction Gate

- Target lane: post-proof TUI polish before optional release promotion.
- Wedge strengthened: trustworthy local TUI iteration and deterministic result recovery.
- Scope rejected: release promotion, publishing, tags, safe mode, sandboxing, persistence, engine changes, CLI changes, and broad UI redesign.
- Contracts touched: TUI rejected-run result-preservation behavior and visible status wording.
- Verification target: focused Textual app tests plus Ruff checks.

---

### Task 1: Add Rejected Empty-SQL And Missing-Source Recovery Tests

**Files:**
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Add a result-grid snapshot helper**

Insert this helper immediately after `_make_source_state()`:

```python
def _result_grid_snapshot(app: CSVQLMenuApp) -> tuple[tuple[str, ...], int, str]:
    results = app.query_one("#results", DataTable)
    return (
        tuple(str(column.label) for column in results.columns.values()),
        results.row_count,
        app.query_one("#results-message", Static).content,
    )
```

- [ ] **Step 2: Replace the empty-SQL rejected-run test**

Replace `test_run_shortcuts_reset_run_status_after_empty_sql` with:

```python
@pytest.mark.parametrize("key", ["f4", "f12"])
def test_run_shortcuts_preserve_previous_result_after_empty_sql(
    tmp_path: Path,
    key: str,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[bool, bool, tuple[str, ...], int, str, str, str, bool, list[str]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            previous_result = app.state.last_result
            previous_view = app.state.result_view
            assert previous_result is not None

            sql.load_text("   \n")
            await pilot.press(key)
            await pilot.pause(0.2)

            columns, row_count, message = _result_grid_snapshot(app)
            return (
                app.state.last_result == previous_result,
                app.state.result_view == previous_view,
                columns,
                row_count,
                message,
                app.query_one("#status", Static).content,
                app.query_one("#run-status", Static).content,
                app.state.query_run.is_running,
                app_history_statuses(app.state),
            )

    (
        result_preserved,
        view_preserved,
        columns,
        row_count,
        message,
        status,
        run_status,
        is_running,
        history_statuses,
    ) = asyncio.run(_inner())

    assert result_preserved is True
    assert view_preserved is True
    assert columns == ("customer_id", "email")
    assert row_count == 2
    assert "Enter SQL before running a query." in status
    assert "Previous result is still available." in status
    assert "Previous result is still available." in message
    assert run_status == "Ready."
    assert is_running is False
    assert history_statuses == ["success"]
```

- [ ] **Step 3: Replace the missing-source rejected-run test**

Replace `test_run_shortcuts_reset_run_status_after_missing_sources` with:

```python
@pytest.mark.parametrize("key", ["f4", "f12"])
def test_run_shortcuts_preserve_previous_result_after_missing_sources(
    tmp_path: Path,
    key: str,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[bool, bool, tuple[str, ...], int, str, str, str, bool, list[str]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            previous_result = app.state.last_result
            previous_view = app.state.result_view
            assert previous_result is not None

            app.state.remove_source("customers")
            app._refresh_sources_table()
            sql.load_text("SELECT * FROM customers")
            await pilot.press(key)
            await pilot.pause(0.2)

            columns, row_count, message = _result_grid_snapshot(app)
            return (
                app.state.last_result == previous_result,
                app.state.result_view == previous_view,
                columns,
                row_count,
                message,
                app.query_one("#status", Static).content,
                app.query_one("#run-status", Static).content,
                app.state.query_run.is_running,
                app_history_statuses(app.state),
            )

    (
        result_preserved,
        view_preserved,
        columns,
        row_count,
        message,
        status,
        run_status,
        is_running,
        history_statuses,
    ) = asyncio.run(_inner())

    assert result_preserved is True
    assert view_preserved is True
    assert columns == ("customer_id", "email")
    assert row_count == 2
    assert "No sources loaded." in status
    assert "Previous result is still available." in status
    assert "Previous result is still available." in message
    assert run_status == "Ready."
    assert is_running is False
    assert history_statuses == ["success"]
```

- [ ] **Step 4: Run the new rejected-run tests and confirm they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest tests/test_tui_app.py::test_run_shortcuts_preserve_previous_result_after_empty_sql tests/test_tui_app.py::test_run_shortcuts_preserve_previous_result_after_missing_sources -q
```

Expected before implementation: FAIL. The empty-SQL and missing-source paths currently clear `state.last_result`, `state.result_view`, and the result grid, and they do not include `Previous result is still available.`.

---

### Task 2: Add Schedule-Failure And Already-Running Recovery Tests

**Files:**
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Add the scheduling-failure preservation test**

Insert this test near `test_run_editor_reads_settled_editor_text_after_refresh`:

```python
def test_schedule_failure_preserves_previous_result_and_resets_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[bool, bool, tuple[str, ...], int, str, str, str, list[str]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            previous_result = app.state.last_result
            previous_view = app.state.result_view
            assert previous_result is not None

            sql.load_text("SELECT email FROM customers")
            monkeypatch.setattr(app, "call_after_refresh", lambda callback: False)
            app.action_run_query()
            await pilot.pause()

            columns, row_count, message = _result_grid_snapshot(app)
            return (
                app.state.last_result == previous_result,
                app.state.result_view == previous_view,
                columns,
                row_count,
                message,
                app.query_one("#status", Static).content,
                app.query_one("#run-status", Static).content,
                app_history_statuses(app.state),
            )

    (
        result_preserved,
        view_preserved,
        columns,
        row_count,
        message,
        status,
        run_status,
        history_statuses,
    ) = asyncio.run(_inner())

    assert result_preserved is True
    assert view_preserved is True
    assert columns == ("customer_id", "email")
    assert row_count == 2
    assert "Unable to schedule query run." in status
    assert "Previous result is still available." in status
    assert "Previous result is still available." in message
    assert run_status == "Ready."
    assert history_statuses == ["success"]
```

- [ ] **Step 2: Add the already-running preservation test**

Insert this test near `test_second_run_while_worker_active_shows_already_running`:

```python
def test_already_running_rejection_preserves_previous_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    worker_started = threading.Event()
    release_worker = threading.Event()
    calls = {"count": 0}

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        del sources
        from csvql.tui_state import TUIQueryOutcome

        calls["count"] += 1
        if calls["count"] == 1:
            return TUIQueryOutcome.success(
                sequence=sequence,
                sql=sql,
                result=QueryResult(
                    columns=("email",),
                    rows=(("alex@example.com",),),
                    elapsed_ms=1.0,
                ),
            )

        worker_started.set()
        assert release_worker.wait(timeout=1.0)
        return TUIQueryOutcome.success(
            sequence=sequence,
            sql=sql,
            result=QueryResult(
                columns=("customer_id",),
                rows=(("CUST-001",),),
                elapsed_ms=5.0,
            ),
        )

    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[
        bool,
        bool,
        tuple[str, ...],
        int,
        str,
        str,
        str,
        bool,
        int | None,
        list[str],
        list[str],
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT email FROM customers LIMIT 1")
            await pilot.press("f4")
            await pilot.pause(0.2)

            previous_result = app.state.last_result
            previous_view = app.state.result_view
            assert previous_result is not None

            sql.load_text("SELECT customer_id FROM customers LIMIT 1")
            await pilot.press("f4")
            await pilot.pause(0.05)
            assert worker_started.is_set()

            await pilot.press("f4")
            await pilot.pause(0.05)

            columns, row_count, message = _result_grid_snapshot(app)
            status = app.query_one("#status", Static).content
            run_status = app.query_one("#run-status", Static).content
            is_running = app.state.query_run.is_running
            sequence = app.state.query_run.sequence
            history_before_release = app_history_statuses(app.state)
            result_preserved = app.state.last_result == previous_result
            view_preserved = app.state.result_view == previous_view

            release_worker.set()
            await pilot.pause(0.2)

            return (
                result_preserved,
                view_preserved,
                columns,
                row_count,
                message,
                status,
                run_status,
                is_running,
                sequence,
                history_before_release,
                app_history_statuses(app.state),
            )

    (
        result_preserved,
        view_preserved,
        columns,
        row_count,
        message,
        status,
        run_status,
        is_running,
        sequence,
        history_before_release,
        final_history_statuses,
    ) = asyncio.run(_inner())

    assert result_preserved is True
    assert view_preserved is True
    assert columns == ("email",)
    assert row_count == 1
    assert "Query already running." in status
    assert "Previous result is still available." in status
    assert "Previous result is still available." in message
    assert run_status == "Running SQL query 2..."
    assert is_running is True
    assert sequence == 2
    assert history_before_release == ["success"]
    assert final_history_statuses == ["success", "success"]
```

- [ ] **Step 3: Run the new scheduling and already-running tests and confirm they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest tests/test_tui_app.py::test_schedule_failure_preserves_previous_result_and_resets_ready tests/test_tui_app.py::test_already_running_rejection_preserves_previous_result -q
```

Expected before implementation: FAIL. The scheduling-failure path currently leaves `#run-status` at `Preparing editor query...`, and both rejected paths currently omit `Previous result is still available.` from the rejection surfaces.

---

### Task 3: Implement The Rejected-Run Display Helper

**Files:**
- Modify: `src/csvql/tui_app.py`

- [ ] **Step 1: Add a rejected-run helper next to `_show_error`**

Replace the current `_show_error()` method with this method block:

```python
    def _show_error(self, error: CSVQLError) -> None:
        message = _error_message(error)
        self._set_status(message)
        self._show_output_text(message)

    def _show_rejected_run(
        self,
        error: CSVQLError,
        *,
        reset_run_status: bool = True,
        simple_message_without_previous: bool = False,
    ) -> None:
        if reset_run_status:
            self._set_run_status_ready()

        rejected_error = error
        if self.state.last_result is not None:
            rejected_error = _with_previous_result_suggestion(error)

        if simple_message_without_previous and self.state.last_result is None:
            message = rejected_error.message
        else:
            message = _error_message(rejected_error)

        self._set_status(message)
        self.query_one("#results-message", Static).update(message)
        self.query_one("#sql", TextArea).focus()
```

- [ ] **Step 2: Add the local message-formatting helpers near `_one_line_sql`**

Insert these helpers immediately before `_one_line_sql()`:

```python
_PREVIOUS_RESULT_AVAILABLE = "Previous result is still available."


def _error_message(error: CSVQLError) -> str:
    lines = [f"Error: {error.message}"]
    if error.suggestion:
        lines.append(f"Suggestion: {error.suggestion}")
    return "\n".join(lines)


def _with_previous_result_suggestion(error: CSVQLError) -> CSVQLError:
    if error.suggestion:
        suggestion = f"{error.suggestion} {_PREVIOUS_RESULT_AVAILABLE}"
    else:
        suggestion = _PREVIOUS_RESULT_AVAILABLE
    return CSVQLError(error.message, suggestion=suggestion)
```

- [ ] **Step 3: Route pending and active run rejections through the helper**

Replace the first branch in `_schedule_editor_query()` with:

```python
        if self._run_editor_pending or self.state.query_run.is_running:
            self._show_rejected_run(
                CSVQLError(
                    "Query already running.",
                    suggestion="Wait for the current query to finish.",
                ),
                reset_run_status=False,
                simple_message_without_previous=True,
            )
            return
```

- [ ] **Step 4: Route schedule failure through the helper**

Replace the `if not self.call_after_refresh(callback):` body in `_schedule_editor_query()` with:

```python
        if not self.call_after_refresh(callback):
            self._run_editor_pending = False
            self._show_rejected_run(
                CSVQLError(
                    "Unable to schedule query run.",
                    suggestion="Try running the query again.",
                )
            )
```

- [ ] **Step 5: Route empty SQL through the helper without clearing result state**

Replace the empty-SQL branch in `_start_query_run()` with:

```python
        if not sql:
            self._show_rejected_run(
                CSVQLError(
                    "Enter SQL before running a query.",
                    suggestion="Type SQL in the editor and try again.",
                )
            )
            return
```

- [ ] **Step 6: Route missing sources through the helper without clearing result state**

Replace the missing-sources branch in `_start_query_run()` with:

```python
        if not self.state.sources:
            self._show_rejected_run(
                CSVQLError(
                    "No sources loaded.",
                    suggestion="Add a source before running SQL.",
                )
            )
            return
```

- [ ] **Step 7: Route `begin_query_run()` rejection through the helper**

Replace the `except RuntimeError:` block in `_start_query_run()` with:

```python
        except RuntimeError:
            self._show_rejected_run(
                CSVQLError(
                    "Query already running.",
                    suggestion="Wait for the current query to finish.",
                ),
                reset_run_status=False,
                simple_message_without_previous=True,
            )
            return
```

- [ ] **Step 8: Run all new rejected-run tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest tests/test_tui_app.py::test_run_shortcuts_preserve_previous_result_after_empty_sql tests/test_tui_app.py::test_run_shortcuts_preserve_previous_result_after_missing_sources tests/test_tui_app.py::test_schedule_failure_preserves_previous_result_and_resets_ready tests/test_tui_app.py::test_already_running_rejection_preserves_previous_result -q
```

Expected after implementation: PASS with 6 passed.

---

### Task 4: Verify Completed-Run Behavior Still Clears When It Should

**Files:**
- Test: `tests/test_tui_app.py`
- Verify implementation in: `src/csvql/tui_app.py`

- [ ] **Step 1: Run existing completed-run regression tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest tests/test_tui_app.py::test_app_clears_stale_result_on_failed_query tests/test_tui_app.py::test_no_result_outcome_clears_last_result_and_disables_export tests/test_tui_app.py::test_error_outcome_records_run_mode_and_marks_history tests/test_tui_app.py::test_unexpected_worker_failure_records_error_and_allows_retry tests/test_tui_app.py::test_second_run_while_worker_active_shows_already_running -q
```

Expected: PASS with 5 passed.

- [ ] **Step 2: Inspect the diff for the no-clear boundary**

Run:

```bash
git diff -- src/csvql/tui_app.py tests/test_tui_app.py
```

Expected:

- `state.clear_last_result()` is removed only from the rejected empty-SQL and missing-source branches.
- `TUIQueryOutcome.error`, `TUIQueryOutcome.no_result`, and `_handle_query_worker_failure()` still clear result/export eligibility through existing state methods and grid clearing.
- `_show_error()` still clears the result grid for real errors and non-query actions that intentionally use the old error display path.
- `_show_rejected_run()` updates `#results-message` without calling `_show_output_text()` or `_clear_result_grid()`.

---

### Task 5: Run Focused Verification And Commit

**Files:**
- Verify: `src/csvql/tui_app.py`
- Verify: `tests/test_tui_app.py`

- [ ] **Step 1: Run the focused Textual app test file**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: PASS.

- [ ] **Step 2: Run focused Ruff format check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run ruff format --check src/csvql/tui_app.py tests/test_tui_app.py
```

Expected: `2 files already formatted`.

- [ ] **Step 3: Run focused Ruff lint check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-proof uv run ruff check src/csvql/tui_app.py tests/test_tui_app.py
```

Expected: `All checks passed!`

- [ ] **Step 4: Confirm the changed-file set**

Run:

```bash
git status --short
```

Expected:

```text
 M src/csvql/tui_app.py
 M tests/test_tui_app.py
?? .superpowers/
```

If `.superpowers/` is absent, continue. If any other file appears, inspect it and either justify it in the final handoff or remove that change from the implementation.

- [ ] **Step 5: Commit only the implementation files**

Run:

```bash
git add src/csvql/tui_app.py tests/test_tui_app.py
git commit -m "fix: preserve tui results on rejected runs"
```

Expected: commit succeeds with only `src/csvql/tui_app.py` and `tests/test_tui_app.py` staged. Do not add `.superpowers/`.

## Plan Self-Review

- Spec coverage: Tasks 1 and 2 cover empty SQL, no sources, schedule failure, and already-running rejected runs. Task 3 implements the helper and routes only rejected branches through it. Task 4 protects completed-run clearing behavior. Task 5 runs the focused verification requested by the spec.
- Scope: No CLI, Python API, DuckDB engine, project catalog, README, release, benchmark, safe-mode, sandbox, persistence, or broad TUI layout work is included.
- Type consistency: The plan uses existing `CSVQLMenuApp`, `CSVQLError`, `QueryResult`, `TUISessionState`, `TextArea`, `DataTable`, and `Static` names already imported in `tests/test_tui_app.py` or `src/csvql/tui_app.py`.
- Result boundary: `_show_rejected_run()` never calls `_show_output_text()` or `_clear_result_grid()`, while completed query outcomes continue through the existing clearing paths.
