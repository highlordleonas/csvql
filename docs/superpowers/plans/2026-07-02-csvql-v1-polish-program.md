# CSVQL V1 Polish Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the v1 polish lane by making the CLI and optional TUI paths easier to understand, adding a repeatable manual QA matrix, and closing with release-proof gates.

**Architecture:** Keep CSVQL's runtime architecture unchanged: Typer remains the CLI boundary, DuckDB execution remains in engine/workflow layers, and the Textual TUI remains an optional surface over existing services. The implementation is mostly documentation, proof, and small TUI help/status polish, with focused tests for docs and help text regressions.

**Tech Stack:** Python 3.11+, Typer, DuckDB, Textual, pytest, Ruff, mypy, uv.

---

## Scope Check

This plan implements:

- `docs/superpowers/specs/2026-07-02-csvql-v1-polish-program-design.md`

It does not implement:

- pandas or Polars dependencies
- Parquet reads or writes
- hidden cache or automatic materialization
- safe mode or sandbox behavior
- dashboards, web UI, notebooks, AI, or plugins
- telemetry
- public Python API expansion
- project catalog schema changes

The current branch already has verified but uncommitted v1/TUI polish edits.
Task 1 preserves and commits that baseline before adding new polish work.

## File Structure

Create:

- `tests/test_v1_polish_docs.py`: docs regression tests for the CLI reusable-result path, manual QA matrix, and release-readiness links.
- `docs/v1-manual-qa.md`: compact human QA checklist for v1 candidate proof.

Modify:

- `README.md`: add first-user and CLI-only reusable-result guidance, link manual QA.
- `docs/release-readiness.md`: add manual QA matrix as a release-candidate proof step.
- `docs/release-notes/v1.md`: mention CLI-only reusable result reuse and manual QA proof in the release notes.
- `src/csvql/tui_help.py`: clarify derived-source save and persistence in in-app help.
- `tests/test_tui_app.py`: assert the refined help text.

Preserve unless a proof-blocking bug is found:

- `src/csvql/cli.py`
- `src/csvql/engine.py`
- `src/csvql/session.py`
- `pyproject.toml`
- `uv.lock`
- `.superpowers/`

---

### Task 1: Preserve And Commit Current V1/TUI Polish Baseline

**Files:**
- Modify already-dirty files only:
  - `.github/workflows/ci.yml`
  - `.gitignore`
  - `AGENTS.md`
  - `CHANGELOG.md`
  - `Makefile`
  - `README.md`
  - `docs/ARCHITECTURE.md`
  - `docs/PRODUCT_DIRECTION.md`
  - `docs/ROADMAP.md`
  - `docs/failure-gallery.md`
  - `docs/release-notes/v1.md`
  - `docs/release-readiness.md`
  - `scripts/verify_release_readiness.py`
  - `src/csvql/release_readiness.py`
  - `src/csvql/tui_app.py`
  - `src/csvql/tui_help.py`
  - `tests/test_release_readiness.py`
  - `tests/test_tui_app.py`
- Do not stage: `.superpowers/`

- [ ] **Step 1: Capture baseline status**

Run:

```bash
pwd
git status --short --branch
git rev-parse HEAD
git diff --stat
```

Expected:

- branch is `codex-menu-tui`
- `.superpowers/` is untracked
- the dirty tracked file list matches the files named above

- [ ] **Step 2: Confirm `keys.log` is ignored without reading it**

Run:

```bash
git check-ignore -v keys.log
```

Expected output includes:

```text
.gitignore:20:keys.log	keys.log
```

- [ ] **Step 3: Run focused baseline tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_release_readiness.py tests/test_tui_app.py::test_help_text_documents_workbench_keymap tests/test_tui_app.py::test_save_result_source_shortcuts -q
```

Expected:

```text
10 passed
```

- [ ] **Step 4: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code `0`.

- [ ] **Step 5: Stage only the baseline files**

Run:

```bash
git add .github/workflows/ci.yml .gitignore AGENTS.md CHANGELOG.md Makefile README.md docs/ARCHITECTURE.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/failure-gallery.md docs/release-notes/v1.md docs/release-readiness.md scripts/verify_release_readiness.py src/csvql/release_readiness.py src/csvql/tui_app.py src/csvql/tui_help.py tests/test_release_readiness.py tests/test_tui_app.py
```

- [ ] **Step 6: Verify staged set**

Run:

```bash
git diff --cached --name-status
```

Expected: only the 18 baseline files from Step 5 are listed.

- [ ] **Step 7: Commit baseline**

Run:

```bash
git commit -m "chore: polish v1 tui release surfaces"
```

Expected: commit succeeds. `.superpowers/` remains untracked.

---

### Task 2: Add Docs Regression Tests For CLI Reuse And Manual QA

**Files:**
- Create: `tests/test_v1_polish_docs.py`

- [ ] **Step 1: Write failing docs tests**

Create `tests/test_v1_polish_docs.py` with this content:

```python
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_doc(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_readme_documents_cli_reusable_result_sources() -> None:
    readme = read_doc("README.md")

    assert "## Reusable Result Sources" in readme
    assert "mkdir -p .csvql/results" in readme
    assert "uv run csvql export queries/revenue_health.sql" in readme
    assert "--out .csvql/results/revenue_health.csv" in readme
    assert "uv run csvql add revenue_health_result .csvql/results/revenue_health.csv" in readme
    assert "--table revenue_health_result=.csvql/results/revenue_health.csv" in readme
    assert "normal CSV reuse" in readme
    assert "not a typed derived-source catalog feature" in readme


def test_manual_qa_matrix_covers_cli_and_tui_release_paths() -> None:
    matrix = read_doc("docs/v1-manual-qa.md")

    assert "# CSVQL V1 Manual QA Matrix" in matrix
    assert "- [ ] CLI single-file query" in matrix
    assert "- [ ] CLI project catalog query" in matrix
    assert "- [ ] CLI export and reuse as CSV source" in matrix
    assert "- [ ] TUI launch" in matrix
    assert "- [ ] TUI repeated query" in matrix
    assert "- [ ] TUI derived save and query" in matrix
    assert "- [ ] Bad SQL" in matrix
    assert "- [ ] No-result SQL" in matrix
    assert "- [ ] Export overwrite refusal and force" in matrix
    assert "- [ ] Missing file behavior" in matrix
    assert "- [ ] Quit path" in matrix
    assert "- [ ] Mac keybinding path" in matrix


def test_release_readiness_links_manual_qa_matrix() -> None:
    readiness = read_doc("docs/release-readiness.md")

    assert "[Manual v1 QA matrix](v1-manual-qa.md)" in readiness
    assert "Run the manual v1 QA matrix" in readiness
```

- [ ] **Step 2: Run docs tests and verify they fail**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_v1_polish_docs.py -q
```

Expected: fail because `docs/v1-manual-qa.md` does not exist and README does not yet contain `## Reusable Result Sources`.

---

### Task 3: Add README CLI Reusable Result Guidance

**Files:**
- Modify: `README.md`
- Test: `tests/test_v1_polish_docs.py`

- [ ] **Step 1: Add a first-user bridge after the development install section**

In `README.md`, after:

```markdown
Run the CLI from the repo:

```bash
uv run csvql --help
```
```

add:

```markdown
## First 10 Minutes

Start with the CLI path. Query one CSV, then decide whether you want the
optional terminal workbench.

```bash
uv run csvql query examples/saas_revenue/data/revenue_movements.csv \
  "SELECT movement_type, SUM(mrr_delta) AS net_mrr_change
   FROM revenue_movements
   GROUP BY movement_type
   ORDER BY movement_type"
```

For repeatable work, initialize a project catalog, add sources once, and keep
SQL in files:

```bash
cd examples/saas_revenue
uv run csvql tables
uv run csvql run queries/revenue_health.sql --output json
```

Use `csvql menu` only when an interactive terminal workbench helps. The CLI
remains the complete core workflow.
```

- [ ] **Step 2: Add reusable-result section after Saved Workflow Examples**

In `README.md`, after:

```markdown
See `examples/saas_revenue/README.md` for the full copy/paste walkthrough.
```

add:

````markdown
## Reusable Result Sources

You can turn a saved SQL result into a reusable CSV source without opening the
TUI. This is normal CSV reuse: export a result, add the exported CSV as a table
alias, then query it like any other CSVQL source.

```bash
cd examples/saas_revenue
mkdir -p .csvql/results
uv run csvql export queries/revenue_health.sql \
  --format csv \
  --out .csvql/results/revenue_health.csv \
  --force

uv run csvql add revenue_health_result .csvql/results/revenue_health.csv --replace
uv run csvql query "SELECT COUNT(*) AS result_rows FROM revenue_health_result"
```

For one command without catalog persistence, pass the exported result with
`--table`:

```bash
cd examples/saas_revenue
uv run csvql query \
  --table revenue_health_result=.csvql/results/revenue_health.csv \
  "SELECT * FROM revenue_health_result"
```

This CLI path is practical parity with the TUI's Save Result As Source action,
but it is not a typed derived-source catalog feature. The current project
catalog stores table paths; it does not store source-kind metadata.
````

- [ ] **Step 3: Link manual QA from Documentation**

In the `## Documentation` list in `README.md`, add:

```markdown
- [Manual v1 QA matrix](docs/v1-manual-qa.md)
```

- [ ] **Step 4: Run the README docs test**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_v1_polish_docs.py::test_readme_documents_cli_reusable_result_sources -q
```

Expected:

```text
1 passed
```

Do not commit yet. Task 4 adds the manual matrix required by the remaining docs tests.

---

### Task 4: Add Manual V1 QA Matrix And Release Links

**Files:**
- Create: `docs/v1-manual-qa.md`
- Modify: `docs/release-readiness.md`
- Modify: `docs/release-notes/v1.md`
- Modify: `README.md`
- Test: `tests/test_v1_polish_docs.py`

- [ ] **Step 1: Create manual QA matrix**

Create `docs/v1-manual-qa.md` with this content:

````markdown
# CSVQL V1 Manual QA Matrix

Status: manual proof checklist for local v1 candidate evaluation.

This matrix is local evidence only. It does not publish, tag, upload, or claim
`v1-stable`.

Run from the repository root unless a step explicitly changes directories.

## Setup

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql --version
```

Expected: prints `1.0.0`.

## Checklist

- [ ] CLI single-file query

  ```bash
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query \
    examples/saas_revenue/data/revenue_movements.csv \
    "SELECT COUNT(*) AS movement_count FROM revenue_movements"
  ```

  Expected: table output contains `movement_count`.

- [ ] CLI project catalog query

  ```bash
  cd examples/saas_revenue
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query \
    "SELECT COUNT(*) AS customer_count FROM customers"
  ```

  Expected: table output contains `customer_count`.

- [ ] CLI export and reuse as CSV source

  ```bash
  cd examples/saas_revenue
  mkdir -p .csvql/results
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql export queries/revenue_health.sql \
    --format csv \
    --out .csvql/results/revenue_health.csv \
    --force
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query \
    --table revenue_health_result=.csvql/results/revenue_health.csv \
    "SELECT COUNT(*) AS result_rows FROM revenue_health_result"
  ```

  Expected: export succeeds and the follow-up query returns `result_rows`.

- [ ] TUI launch

  ```bash
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras csvql menu \
    examples/saas_revenue/data/revenue_movements.csv
  ```

  Expected: Workbench opens with a loaded source alias.

- [ ] TUI repeated query

  In the TUI, run:

  ```sql
  SELECT COUNT(*) AS movement_count FROM revenue_movements;
  ```

  Then clear the editor and run:

  ```sql
  SELECT movement_type, COUNT(*) AS rows
  FROM revenue_movements
  GROUP BY movement_type;
  ```

  Expected: both runs complete, history records both attempts, and the editor
  remains usable.

- [ ] TUI derived save and query

  In the TUI, save the last tabular result with `Ctrl+S`, use alias
  `movement_counts`, then run:

  ```sql
  SELECT * FROM movement_counts;
  ```

  Expected: `.csvql/results/movement_counts.csv` is written under the current
  local root, Sources shows `movement_counts` with kind `derived`, and the query
  returns rows from the saved result.

- [ ] Bad SQL

  Run:

  ```bash
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query \
    --table revenue_movements=examples/saas_revenue/data/revenue_movements.csv \
    "SELECT missing_column FROM revenue_movements"
  ```

  Expected: exit code `1`, an error beginning `DuckDB query failed`, and a
  suggestion to check table names, column names, and SQL syntax.

- [ ] No-result SQL

  In the TUI, run:

  ```sql
  CREATE TABLE scratch AS SELECT 1 AS value;
  ```

  Expected: prior results are cleared and the TUI reports that the statement
  completed with no tabular result to display.

- [ ] Export overwrite refusal and force

  ```bash
  cd examples/saas_revenue
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql export queries/revenue_health.sql \
    --format csv \
    --out output/revenue-health.csv
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql export queries/revenue_health.sql \
    --format csv \
    --out output/revenue-health.csv
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql export queries/revenue_health.sql \
    --format csv \
    --out output/revenue-health.csv \
    --force
  ```

  Expected: first export succeeds, second export exits `10` with overwrite
  guidance, third export succeeds.

- [ ] Missing file behavior

  ```bash
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query missing.csv "SELECT 1"
  ```

  Expected: exit code `4` and a message that the CSV file was not found.

- [ ] Quit path

  In the TUI, press `F9`.

  Expected: the app exits cleanly without a traceback.

- [ ] Mac keybinding path

  On macOS, use `Ctrl+S` for Save Result As Source. Confirm `F11` is not the
  only documented save path because macOS may intercept it for Show Desktop.

## Result Recording

Record the final manual result in release notes or handoff text with:

- date
- commit SHA
- terminal app
- passed checklist items
- failed checklist items and blockers
````

- [ ] **Step 2: Link matrix from release readiness**

In `docs/release-readiness.md`, after the `## Full Local Gate` section, add:

```markdown
## Manual V1 QA Matrix

Run the manual v1 QA matrix before classifying a final candidate:

- [Manual v1 QA matrix](v1-manual-qa.md)

The matrix covers CLI-only reuse, optional TUI flows, derived-source save and
query, bad SQL, no-result SQL, export overwrite behavior, missing files, quit
behavior, and Mac keybinding paths.
```

In the numbered `## Local Candidate Workflow`, insert this new step after
release-readiness proof and before benchmark proof:

```markdown
5. Run the manual v1 QA matrix and record the date, commit SHA, terminal app,
   passed items, and blockers.
```

Renumber the later steps so the workflow remains ordered.

- [ ] **Step 3: Link matrix from release notes**

In `docs/release-notes/v1.md`, under `## Candidate Proof Checklist`, after the
release-readiness proof command, add:

```markdown
Run the manual QA matrix:

- [Manual v1 QA matrix](../v1-manual-qa.md)
```

Under `## Implemented Surfaces`, add:

```markdown
- CLI-only reusable result source workflow through `csvql export`, `csvql add`,
  and `--table`
```

- [ ] **Step 4: Run docs tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_v1_polish_docs.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit docs matrix work**

Run:

```bash
git add README.md docs/v1-manual-qa.md docs/release-readiness.md docs/release-notes/v1.md tests/test_v1_polish_docs.py
git commit -m "docs: add v1 polish qa matrix"
```

---

### Task 5: Tighten TUI Help For Derived Source Persistence

**Files:**
- Modify: `src/csvql/tui_help.py`
- Modify: `tests/test_tui_app.py`

- [ ] **Step 1: Write failing help assertions**

In `tests/test_tui_app.py`, inside `test_help_text_documents_workbench_keymap`, add:

```python
    assert "Derived sources" in help_text
    assert ".csvql/results/{alias}.csv" in help_text
    assert "Persist source paths to .csvql.yml" in help_text
```

- [ ] **Step 2: Run the focused help test and verify it fails**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py::test_help_text_documents_workbench_keymap -q
```

Expected: fail because the help text does not contain `Derived sources`.

- [ ] **Step 3: Update TUI help text**

Replace the `General` block in `src/csvql/tui_help.py`:

```python
General
  F1                  Help
  ?                   Help outside the SQL editor
  F7                  Export last tabular result
  Ctrl+S              Save last tabular result as a derived source
  Alt+S / F11         Alternate save-result shortcuts
  F9                  Quit
  Esc                 Close help or modal
```

with:

```python
General
  F1                  Help
  ?                   Help outside the SQL editor
  F7                  Export last tabular result
  F9                  Quit
  Esc                 Close help or modal

Derived sources
  Ctrl+S              Save result to .csvql/results/{alias}.csv
  Alt+S / F11         Alternate save-result shortcuts
  w in Sources        Persist source paths to .csvql.yml
```

- [ ] **Step 4: Run the focused help test and verify it passes**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py::test_help_text_documents_workbench_keymap -q
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Run TUI app tests**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_app.py -q
```

Expected: all `tests/test_tui_app.py` tests pass.

- [ ] **Step 6: Commit TUI help polish**

Run:

```bash
git add src/csvql/tui_help.py tests/test_tui_app.py
git commit -m "docs: clarify tui derived source help"
```

---

### Task 6: Run Manual CLI Proof For Reusable Result Sources

**Files:**
- No tracked file changes expected.

- [ ] **Step 1: Create temp proof directory**

Run:

```bash
mkdir -p /private/tmp/csvql-v1-cli-reuse-proof
```

Expected: directory exists.

- [ ] **Step 2: Copy example project inputs into temp proof directory**

Run:

```bash
cp -R examples/saas_revenue /private/tmp/csvql-v1-cli-reuse-proof/saas_revenue
```

Expected: `/private/tmp/csvql-v1-cli-reuse-proof/saas_revenue/.csvql.yml` exists.

- [ ] **Step 3: Run CLI export and reuse proof**

Run from `/private/tmp/csvql-v1-cli-reuse-proof/saas_revenue`:

```bash
mkdir -p .csvql/results
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/Documents/csvql csvql export queries/revenue_health.sql --format csv --out .csvql/results/revenue_health.csv --force
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/Documents/csvql csvql query --table revenue_health_result=.csvql/results/revenue_health.csv "SELECT COUNT(*) AS result_rows FROM revenue_health_result"
```

Expected:

- first command prints `Wrote export`
- second command prints table output containing `result_rows`

- [ ] **Step 4: Record proof result in final implementation handoff**

Record:

- temp directory path
- export command result
- query command result
- any blocker

Do not commit files from `/private/tmp`.

---

### Task 7: Final Verification And Release Proof

**Files:**
- No new source files expected.
- Generated output remains ignored.

- [ ] **Step 1: Run formatting check**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
```

Expected:

```text
69 files already formatted
```

- [ ] **Step 2: Run lint**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
```

Expected:

```text
All checks passed!
```

- [ ] **Step 3: Run mypy**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src
```

Expected:

```text
Success: no issues found in 31 source files
```

- [ ] **Step 4: Run full pytest**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest
```

Expected: all tests pass.

- [ ] **Step 5: Run release-readiness proof**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-v1-polish uv run python scripts/verify_release_readiness.py --work-dir /private/tmp/csvql-v1-polish-release-readiness
```

Expected output starts with:

```text
Release readiness proof passed.
```

Expected output includes:

```text
TUI extra import: tui-extra-ok
Menu help smoke output:
```

- [ ] **Step 6: Run unsupported-claim scan**

Run:

```bash
rg -n "v1-ready|v1 ready|production-safe|production ready|production-readiness|production readiness|sandbox-safe|sandbox safety|sandbox|large-file-proven|large file proven|large-file performance|large file performance|hidden cache|automatic materialization" AGENTS.md README.md CHANGELOG.md docs/PRODUCT_DIRECTION.md docs/ROADMAP.md docs/ARCHITECTURE.md docs/json-contracts.md docs/benchmarking.md docs/failure-gallery.md docs/release-readiness.md docs/release-notes/v1.md docs/v1-manual-qa.md
```

Expected: matches are guardrails, non-claims, generated regex text, or future-work language. A current claim that CSVQL is sandbox-safe, production-ready, large-file-proven, or externally `v1-stable` blocks completion.

- [ ] **Step 7: Run diff whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code `0`.

- [ ] **Step 8: Capture final status**

Run:

```bash
git status --short --branch
git log -3 --oneline
```

Expected:

- branch is `codex-menu-tui`
- `.superpowers/` remains untracked unless Richard separately approved tracking it
- no generated proof artifacts are staged

- [ ] **Step 9: Commit final verification docs if any files remain dirty**

If only intentional tracked files from Tasks 2 through 5 remain dirty, run:

```bash
git add README.md docs/v1-manual-qa.md docs/release-readiness.md docs/release-notes/v1.md src/csvql/tui_help.py tests/test_tui_app.py tests/test_v1_polish_docs.py
git commit -m "docs: finish v1 polish proof path"
```

If no tracked files remain dirty, skip this step and report that all changes were already committed.

---

## Completion Handoff

Final implementation handoff must include:

- skills used
- files changed
- commit SHAs created
- focused tests run
- full gate results
- release-readiness proof result
- CLI reusable-result manual proof result
- unsupported-claim scan classification
- remaining risk
- explicit note that no tag, PyPI upload, GitHub release, artifact upload, or
  `v1-stable` claim was made
