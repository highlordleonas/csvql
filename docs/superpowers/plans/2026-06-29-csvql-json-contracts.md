# CSVQL JSON Contracts Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document the current `v0.8` JSON contract for `query`, `run`, `inspect`, `profile`, `check`, and `export --format json`, define the ideal normalized `v1` envelope, and lock the documented current shapes down with focused tests.

**Architecture:** Add one user-facing contract doc at `docs/json-contracts.md` that records current runtime truth first and the ideal `v1` target second. Reuse the current JSON emitters and CLI commands exactly as they exist today, strengthen structural JSON tests around the shared query-shaped family plus `inspect`, `profile`, and `check`, and add one README link so the contract doc is discoverable.

**Tech Stack:** Markdown, Python 3.12, Typer CLI, pytest, `uv`, existing CSVQL output formatters, repo-local CLI fixtures.

---

## Preconditions

- Start from a clean worktree on the current feature branch.
- Use the committed spec at `docs/superpowers/specs/2026-06-29-csvql-json-contracts-design.md` as the authority for scope.
- Do not change `src/csvql/*.py` unless a targeted JSON test proves the runtime does not match current documented truth.
- Sync the environment before editing:

```bash
uv sync --all-extras --frozen
```

- Confirm the repo gate is green before touching files:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

Expected: PASS for all commands.

## Scope And Constraints

- Cover only:
  - `query --output json`
  - `run --output json`
  - `inspect --output json`
  - `profile --output json`
  - `check --output json`
  - `export --format json`
- Do not document `sample`, `tables`, benchmark artifacts, or Python API JSON in this slice.
- Do not add JSON Schema files.
- Do not normalize or redesign the current runtime output in code.
- Do not change exit codes, CLI flags, or field names in this slice.
- Keep `docs/json-contracts.md` split into:
  - current `v0.8` contract
  - ideal `v1` contract direction
  - explicit per-command deltas
- Treat `elapsed_ms`, timestamps, and absolute paths as documented current facts but volatile automation values.

## Command, JSON, Exit-Code, Docs, And Test Impact

Command impact:

- none
- this slice documents existing command behavior only

JSON impact:

- no runtime JSON changes intended
- current JSON shapes become explicitly documented
- ideal `v1` shape is design guidance only

Exit-code impact:

- none
- `check` keeps current payload semantics and current CLI exit-code behavior

Docs impact:

- create `docs/json-contracts.md`
- optionally add one README documentation link

Test impact:

- strengthen structural JSON assertions in existing test modules
- verify:
  - shared query-shaped output
  - inspect structure
  - profile structure
  - check structure with and without `failures`

## File Structure

- Create: `docs/json-contracts.md`
- Modify: `README.md`
- Modify: `tests/test_output.py`
- Modify: `tests/test_cli_query.py`
- Modify: `tests/test_cli_run_export.py`
- Modify: `tests/test_cli_inspect_sample.py`
- Modify: `tests/test_cli_profile.py`
- Modify: `tests/test_cli_check.py`

`docs/json-contracts.md`
: the user-facing source of truth for current `v0.8` automation JSON and the ideal `v1` target

`README.md`
: adds one documentation link so the contract doc is discoverable from the main repo entrypoint

`tests/test_output.py`
: locks the formatter-level JSON family shape, especially `format_json_result`

`tests/test_cli_query.py`
: locks CLI-level `query --output json` structure

`tests/test_cli_run_export.py`
: locks CLI-level `run --output json` and `export --format json` shape parity with query-shaped output

`tests/test_cli_inspect_sample.py`
: locks CLI-level `inspect --output json` structure

`tests/test_cli_profile.py`
: locks CLI-level `profile --output json` structure

`tests/test_cli_check.py`
: locks CLI-level `check --output json` structure with and without failure samples

## Task 1: Strengthen Query-Shaped JSON Contract Tests

**Files:**
- Modify: `tests/test_output.py`
- Modify: `tests/test_cli_query.py`
- Modify: `tests/test_cli_run_export.py`

- [ ] **Step 1: Add a formatter-level test for the shared query-shaped JSON family**

In `tests/test_output.py`, update the imports to include `QueryResult` and `format_json_result`:

```python
from csvql.models import (
    ColumnInfo,
    ColumnProfile,
    DialectInfo,
    InspectResult,
    ProfileResult,
    QueryResult,
    RowCountInfo,
    SampleResult,
)
from csvql.output import (
    format_check_result_json,
    format_check_result_table,
    format_inspect_result_json,
    format_inspect_result_table,
    format_json_result,
    format_profile_result_json,
    format_profile_result_table,
    format_project_tables_json,
    format_project_tables_table,
    format_sample_result_json,
    format_sample_result_table,
)
```

Add this new test near the other JSON formatter tests:

```python
def test_format_json_result_is_deterministic() -> None:
    result = QueryResult(
        columns=("name", "amount"),
        rows=(("Alex", 20.5),),
        elapsed_ms=1.23456,
    )

    payload = json.loads(format_json_result(result))

    assert payload == {
        "columns": ["name", "amount"],
        "elapsed_ms": 1.235,
        "row_count": 1,
        "rows": [{"name": "Alex", "amount": 20.5}],
    }
```

- [ ] **Step 2: Run the new formatter-level query JSON test**

Run:

```bash
uv run pytest tests/test_output.py::test_format_json_result_is_deterministic -q
```

Expected: PASS.

- [ ] **Step 3: Add one CLI query contract test that asserts the full key set**

In `tests/test_cli_query.py`, add:

```python
def test_query_json_contract_includes_query_result_fields(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text(
        "order_id,total_amount\nORD-001,20.00\nORD-002,10.00\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            f"orders={orders}",
            "--output",
            "json",
            "SELECT COUNT(*) AS order_count FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {"columns", "rows", "row_count", "elapsed_ms"}
    assert payload["columns"] == ["order_count"]
    assert payload["rows"] == [{"order_count": 2}]
    assert payload["row_count"] == 1
    assert isinstance(payload["elapsed_ms"], float)
```

- [ ] **Step 4: Run the new CLI query contract test**

Run:

```bash
uv run pytest tests/test_cli_query.py::test_query_json_contract_includes_query_result_fields -q
```

Expected: PASS.

- [ ] **Step 5: Add `run` and `export --format json` parity tests**

In `tests/test_cli_run_export.py`, add:

```python
def test_run_json_contract_matches_query_result_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\nORD-002,10.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(app, ["run", "queries/count_orders.sql", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {"columns", "rows", "row_count", "elapsed_ms"}
    assert payload["columns"] == ["order_count"]
    assert payload["rows"] == [{"order_count": 2}]
    assert payload["row_count"] == 1
    assert isinstance(payload["elapsed_ms"], float)


def test_export_json_contract_matches_query_result_shape_on_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.json"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "queries/count_orders.sql", "--format", "json", "--out", "result.json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert set(payload) == {"columns", "rows", "row_count", "elapsed_ms"}
    assert payload["columns"] == ["order_count"]
    assert payload["rows"] == [{"order_count": 1}]
    assert payload["row_count"] == 1
    assert isinstance(payload["elapsed_ms"], float)
```

- [ ] **Step 6: Run the new `run` and `export` parity tests**

Run:

```bash
uv run pytest \
  tests/test_cli_run_export.py::test_run_json_contract_matches_query_result_shape \
  tests/test_cli_run_export.py::test_export_json_contract_matches_query_result_shape_on_disk -q
```

Expected: PASS.

- [ ] **Step 7: Commit the query-shaped test batch**

```bash
git add tests/test_output.py tests/test_cli_query.py tests/test_cli_run_export.py
git commit -m "test: lock query json contract shape"
```

## Task 2: Strengthen Inspect, Profile, And Check JSON Contract Tests

**Files:**
- Modify: `tests/test_cli_inspect_sample.py`
- Modify: `tests/test_cli_profile.py`
- Modify: `tests/test_cli_check.py`

- [ ] **Step 1: Add a structural inspect contract test**

In `tests/test_cli_inspect_sample.py`, add:

```python
def test_inspect_json_contract_includes_source_dialect_columns_row_count_and_warnings(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["inspect", str(csv_path), "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {"source", "dialect", "columns", "row_count", "warnings"}
    assert payload["dialect"] == {
        "delimiter": ",",
        "quote": "\"",
        "escape": None,
        "header": True,
        "encoding": "utf-8",
    }
    assert payload["columns"][0] == {"name": "order_id", "duckdb_type": "VARCHAR"}
    assert payload["row_count"] == {
        "mode": "not_counted",
        "value": None,
        "exact": False,
    }
    assert payload["warnings"] == []
    assert payload["source"]["display_path"] == str(csv_path)
    assert payload["source"]["resolved_path"] == str(csv_path.resolve())
    assert payload["source"]["size_bytes"] == csv_path.stat().st_size
    assert payload["source"]["fingerprint"]["version"] == 1
```

- [ ] **Step 2: Run the new inspect contract test**

Run:

```bash
uv run pytest tests/test_cli_inspect_sample.py::test_inspect_json_contract_includes_source_dialect_columns_row_count_and_warnings -q
```

Expected: PASS.

- [ ] **Step 3: Add a structural profile contract test**

In `tests/test_cli_profile.py`, add:

```python
def test_profile_json_contract_includes_source_counts_columns_and_warnings(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-1,paid\nORD-2,\nORD-2,\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["profile", str(csv_path), "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {
        "source",
        "row_count",
        "column_count",
        "duplicate_row_count",
        "columns",
        "warnings",
    }
    assert payload["source"]["display_path"] == str(csv_path)
    assert payload["source"]["resolved_path"] == str(csv_path.resolve())
    assert payload["source"]["fingerprint"]["version"] == 1
    assert payload["row_count"] == 3
    assert payload["column_count"] == 2
    assert payload["duplicate_row_count"] == 1
    assert payload["warnings"] == []
    assert payload["columns"][1]["name"] == "status"
    assert payload["columns"][1]["null_percentage"] == 66.667
```

- [ ] **Step 4: Run the new profile contract test**

Run:

```bash
uv run pytest tests/test_cli_profile.py::test_profile_json_contract_includes_source_counts_columns_and_warnings -q
```

Expected: PASS.

- [ ] **Step 5: Add default and failure-sample check contract tests**

In `tests/test_cli_check.py`, add:

```python
def test_check_json_contract_omits_failures_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
            checks:
              - name: order_id_required
                type: not_null
                column: order_id
        """,
    )

    result = runner.invoke(app, ["check", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {
        "status",
        "check_count",
        "passed_count",
        "failed_count",
        "checks",
        "warnings",
    }
    assert payload["status"] == "passed"
    assert payload["check_count"] == 1
    assert payload["passed_count"] == 1
    assert payload["failed_count"] == 0
    assert payload["warnings"] == []
    assert "failures" not in payload["checks"][0]


def test_check_json_contract_includes_failure_samples_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "order_id,status\nORD-1,paid\n,unknown\n,paid\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
            checks:
              - name: order_id_required
                type: not_null
                column: order_id
        """,
    )

    result = runner.invoke(
        app,
        ["check", "--output", "json", "--show-failures", "--failure-limit", "1"],
    )

    assert result.exit_code == 11, result.output
    payload = json.loads(result.output)
    assert set(payload) == {
        "status",
        "check_count",
        "passed_count",
        "failed_count",
        "checks",
        "warnings",
    }
    assert payload["status"] == "failed"
    assert payload["check_count"] == 1
    assert payload["passed_count"] == 0
    assert payload["failed_count"] == 1
    assert payload["warnings"] == []
    assert payload["checks"][0]["failed_count"] == 2
    assert payload["checks"][0]["failures"][0]["row_number"] == 2
    assert payload["checks"][0]["failures"][0]["row"] == {
        "order_id": None,
        "status": "unknown",
    }
```

- [ ] **Step 6: Run the new check contract tests**

Run:

```bash
uv run pytest \
  tests/test_cli_check.py::test_check_json_contract_omits_failures_by_default \
  tests/test_cli_check.py::test_check_json_contract_includes_failure_samples_when_requested -q
```

Expected: PASS.

- [ ] **Step 7: Commit the inspect/profile/check test batch**

```bash
git add tests/test_cli_inspect_sample.py tests/test_cli_profile.py tests/test_cli_check.py
git commit -m "test: lock automation json contract details"
```

## Task 3: Capture Real CLI Payloads And Write `docs/json-contracts.md`

**Files:**
- Create: `docs/json-contracts.md`

- [ ] **Step 1: Create tiny fixture projects for exact JSON capture**

Run:

```bash
mkdir -p /private/tmp/csvql-json-contracts-fixture/data /private/tmp/csvql-json-contracts-fixture/queries
cat > /private/tmp/csvql-json-contracts-fixture/.csvql.yml <<'EOF'
version: 1
tables:
  orders:
    path: data/orders.csv
    checks:
      - name: order_id_required
        type: not_null
        column: order_id
EOF
cat > /private/tmp/csvql-json-contracts-fixture/data/orders.csv <<'EOF'
order_id,status,total_amount
ORD-1,paid,20.0
ORD-2,pending,10.0
EOF
cat > /private/tmp/csvql-json-contracts-fixture/queries/count_orders.sql <<'EOF'
SELECT COUNT(*) AS order_count FROM orders
EOF

mkdir -p /private/tmp/csvql-json-contracts-failure/data
cat > /private/tmp/csvql-json-contracts-failure/.csvql.yml <<'EOF'
version: 1
tables:
  orders:
    path: data/orders.csv
    checks:
      - name: order_id_required
        type: not_null
        column: order_id
EOF
cat > /private/tmp/csvql-json-contracts-failure/data/orders.csv <<'EOF'
order_id,status,total_amount
ORD-1,paid,20.0
,unknown,10.0
,paid,5.0
EOF
```

Expected:

- the fixture project exists at `/private/tmp/csvql-json-contracts-fixture`
- the failure fixture exists at `/private/tmp/csvql-json-contracts-failure`
- both projects contain `.csvql.yml` plus the expected CSV inputs

- [ ] **Step 2: Capture exact current runtime payloads into scratch files**

Run:

```bash
mkdir -p /private/tmp/csvql-json-contracts

(
  cd /private/tmp/csvql-json-contracts-fixture
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/.codex/worktrees/ecb3/csvql csvql query --output json \
    "SELECT COUNT(*) AS order_count FROM orders" \
    > /private/tmp/csvql-json-contracts/query.json

  env UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/.codex/worktrees/ecb3/csvql csvql run queries/count_orders.sql --output json \
    > /private/tmp/csvql-json-contracts/run.json

  env UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/.codex/worktrees/ecb3/csvql csvql inspect data/orders.csv --output json \
    > /private/tmp/csvql-json-contracts/inspect.json

  env UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/.codex/worktrees/ecb3/csvql csvql profile data/orders.csv --output json \
    > /private/tmp/csvql-json-contracts/profile.json

  env UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/.codex/worktrees/ecb3/csvql csvql check --output json \
    > /private/tmp/csvql-json-contracts/check-passing.json

  env UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/.codex/worktrees/ecb3/csvql csvql export queries/count_orders.sql --format json --out /private/tmp/csvql-json-contracts/export.json --force
)

status=0
(
  cd /private/tmp/csvql-json-contracts-failure
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run --project /Users/richarddemke/.codex/worktrees/ecb3/csvql csvql check --output json --show-failures --failure-limit 1
) > /private/tmp/csvql-json-contracts/check-failure.json || status=$?
test "$status" -eq 11
```

Expected:

- `query.json`, `run.json`, `inspect.json`, `profile.json`, `check-passing.json`, `check-failure.json`, and `export.json` exist under `/private/tmp/csvql-json-contracts`
- the first capture block succeeds cleanly
- the failing `check` capture proves the command still exits `11`

- [ ] **Step 3: Create `docs/json-contracts.md` with the full current-contract and future-contract sections**

Create `docs/json-contracts.md` with:

````markdown
# JSON Contracts

## Scope And Guarantees

This document records the current `v0.8` JSON output for CSVQL's
automation-oriented command surfaces:

- `csvql query --output json`
- `csvql run --output json`
- `csvql inspect --output json`
- `csvql profile --output json`
- `csvql check --output json`
- `csvql export --format json`

Runtime truth wins. The `Current v0.8 contract` sections below describe the
JSON exactly as the CLI emits it today. The `Ideal v1 normalized contract`
section is future-facing design guidance only; it is not the current runtime
envelope.

Not covered here:

- `csvql sample --output json`
- `csvql tables --output json`
- benchmark artifact JSON
- future Python API result objects

### Stable vs Volatile Fields

- `elapsed_ms` is part of current runtime output for query-shaped results, but
  its exact numeric value is volatile
- `source.resolved_path`, `source.modified_at`, and
  `source.fingerprint.modified_at` are machine-local values and are redacted in
  the examples below
- `source.size_bytes` reflects the specific input file used in each example and
  can vary if the input changes
- field names, nesting, omission behavior, and scalar types are the stable part
  of the contract

## Current `v0.8` Contract

### Shared Query-Shaped Results

These three surfaces currently share the same JSON family:

- `query`
- `run`
- `export --format json`

Common fields:

- `columns`: ordered list of output column names
- `rows`: record-oriented rows keyed by column name
- `row_count`: number of returned rows
- `elapsed_ms`: rounded wall-clock execution time in milliseconds

Example `query` payload:

```json
{
  "columns": [
    "order_count"
  ],
  "elapsed_ms": 7.651,
  "row_count": 1,
  "rows": [
    {
      "order_count": 2
    }
  ]
}
```

Example `run` payload:

```json
{
  "columns": [
    "order_count"
  ],
  "elapsed_ms": 7.71,
  "row_count": 1,
  "rows": [
    {
      "order_count": 2
    }
  ]
}
```

Example `export --format json` payload:

```json
{
  "columns": [
    "order_count"
  ],
  "elapsed_ms": 7.754,
  "row_count": 1,
  "rows": [
    {
      "order_count": 2
    }
  ]
}
```

### `inspect --output json`

Current fields:

- `source`
- `dialect`
- `columns`
- `row_count`
- `warnings`

Example:

```json
{
  "columns": [
    {
      "duckdb_type": "VARCHAR",
      "name": "order_id"
    },
    {
      "duckdb_type": "VARCHAR",
      "name": "status"
    },
    {
      "duckdb_type": "DOUBLE",
      "name": "total_amount"
    }
  ],
  "dialect": {
    "delimiter": ",",
    "encoding": "utf-8",
    "escape": null,
    "header": true,
    "quote": "\""
  },
  "row_count": {
    "exact": false,
    "mode": "not_counted",
    "value": null
  },
  "source": {
    "display_path": "data/orders.csv",
    "fingerprint": {
      "modified_at": "<modified-at>",
      "size_bytes": 64,
      "version": 1
    },
    "modified_at": "<modified-at>",
    "resolved_path": "<tmp>/csvql-json-contracts-fixture/data/orders.csv",
    "size_bytes": 64
  },
  "warnings": []
}
```

### `profile --output json`

Current fields:

- `source`
- `row_count`
- `column_count`
- `duplicate_row_count`
- `columns`
- `warnings`

Example:

```json
{
  "column_count": 3,
  "columns": [
    {
      "distinct_count": 2,
      "duckdb_type": "VARCHAR",
      "max": "ORD-2",
      "min": "ORD-1",
      "name": "order_id",
      "non_null_count": 2,
      "null_count": 0,
      "null_percentage": 0.0
    },
    {
      "distinct_count": 2,
      "duckdb_type": "VARCHAR",
      "max": "pending",
      "min": "paid",
      "name": "status",
      "non_null_count": 2,
      "null_count": 0,
      "null_percentage": 0.0
    },
    {
      "distinct_count": 2,
      "duckdb_type": "DOUBLE",
      "max": 20.0,
      "min": 10.0,
      "name": "total_amount",
      "non_null_count": 2,
      "null_count": 0,
      "null_percentage": 0.0
    }
  ],
  "duplicate_row_count": 0,
  "row_count": 2,
  "source": {
    "display_path": "data/orders.csv",
    "fingerprint": {
      "modified_at": "<modified-at>",
      "size_bytes": 64,
      "version": 1
    },
    "modified_at": "<modified-at>",
    "resolved_path": "<tmp>/csvql-json-contracts-fixture/data/orders.csv",
    "size_bytes": 64
  },
  "warnings": []
}
```

### `check --output json`

Current fields:

- `status`
- `check_count`
- `passed_count`
- `failed_count`
- `checks`
- `warnings`

Passing example:

```json
{
  "check_count": 1,
  "checks": [
    {
      "column": "order_id",
      "failed_count": 0,
      "name": "order_id_required",
      "status": "passed",
      "table": "orders",
      "type": "not_null"
    }
  ],
  "failed_count": 0,
  "passed_count": 1,
  "status": "passed",
  "warnings": []
}
```

When `--show-failures` is used and failures exist, a check entry may include a
`failures` array:

```json
{
  "check_count": 1,
  "checks": [
    {
      "column": "order_id",
      "failed_count": 2,
      "failures": [
        {
          "row": {
            "order_id": null,
            "status": "unknown",
            "total_amount": 10.0
          },
          "row_number": 2,
          "value": null
        }
      ],
      "name": "order_id_required",
      "status": "failed",
      "table": "orders",
      "type": "not_null"
    }
  ],
  "failed_count": 1,
  "passed_count": 0,
  "status": "failed",
  "warnings": []
}
```

## Cross-Command Rules In `v0.8`

- `query`, `run`, and `export --format json` currently share one query-shaped
  family
- `warnings` is always present for `inspect`, `profile`, and `check`
- `inspect.row_count` is structured metadata, but `profile.row_count` is an
  integer
- `check.failures` is conditional and omitted unless failure samples are
  requested and present
- current source metadata can include absolute paths, timestamps, and file
  fingerprints that vary per machine and run

## Ideal `v1` Normalized Contract

Recommended future envelope:

```json
{
  "schema_version": 1,
  "command": "profile",
  "data": {
    "row_count": 2,
    "column_count": 3,
    "duplicate_row_count": 0,
    "columns": []
  },
  "warnings": [],
  "meta": {
    "source": {
      "display_path": "data/orders.csv"
    },
    "elapsed_ms": 7.651
  }
}
```

Recommended rules:

- `data` contains the semantic result the caller actually wants
- `warnings` is always present and always a list
- `meta` contains volatile operational or provenance details
- query-shaped results converge under one shared table-result family
- inspect and profile stop diverging about where count and source metadata live

## Delta From Current `v0.8` To Ideal `v1`

### `query`, `run`, and `export --format json`

Current:

- top-level `columns`, `rows`, `row_count`, `elapsed_ms`

Ideal `v1`:

- move `columns`, `rows`, and `row_count` under `data`
- move `elapsed_ms` under `meta`
- add `schema_version` and `command`

### `inspect`

Current:

- top-level `source`, `dialect`, `columns`, `row_count`, `warnings`

Ideal `v1`:

- move `dialect`, `columns`, and `row_count` under `data`
- move machine-local source provenance under `meta`

### `profile`

Current:

- top-level `source`, `row_count`, `column_count`, `duplicate_row_count`,
  `columns`, `warnings`

Ideal `v1`:

- move result metrics under `data`
- move source provenance under `meta`
- converge count and source placement with inspect

### `check`

Current:

- top-level run verdict and counts
- conditional `checks[*].failures`

Ideal `v1`:

- move verdict and counts under `data`
- keep `warnings` top-level
- keep sampled failures command-specific inside `data.checks[*]`
````

- [ ] **Step 4: Run a focused docs review and inspect the rendered diff**

Run:

```bash
sed -n '1,260p' docs/json-contracts.md
git diff --no-index -- /dev/null docs/json-contracts.md
```

Expected:

- the doc contains all five planned sections
- the current `v0.8` sections document only the agreed six automation surfaces
- the examples use exact small runtime payloads with redaction only for
  machine-local paths and timestamps
- the ideal `v1` section is clearly labeled as future-facing

- [ ] **Step 5: Commit the new contract doc**

```bash
git add docs/json-contracts.md
git commit -m "docs: add json contracts reference"
```

## Task 4: Add The README Link And Tighten Discoverability

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the JSON contract reference to the documentation list**

In `README.md`, update the documentation section to include:

```markdown
## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Benchmarking](docs/benchmarking.md)
- [JSON contracts](docs/json-contracts.md)
- [Product direction](docs/PRODUCT_DIRECTION.md)
- [Release readiness](docs/release-readiness.md)
- [Roadmap](docs/ROADMAP.md)
- [Codex capability review](docs/CODEX_CAPABILITY_REVIEW.md)
- [v1 Quality Spine design](docs/superpowers/specs/2026-06-26-csvql-v1-quality-spine-design.md)
```

- [ ] **Step 2: Run a focused README diff check**

Run:

```bash
rg -n "JSON contracts" README.md
git diff -- README.md
```

Expected:

- `README.md` contains the new documentation link exactly once
- no unrelated README sections changed

- [ ] **Step 3: Commit the README discoverability change**

```bash
git add README.md
git commit -m "docs: link json contracts reference"
```

## Task 5: Run The Full Gate And Final Diff Review

**Files:**
- No intended new files beyond the planned docs and test changes

- [ ] **Step 1: Run the focused JSON contract tests together**

Run:

```bash
uv run pytest \
  tests/test_output.py::test_format_json_result_is_deterministic \
  tests/test_cli_query.py::test_query_json_contract_includes_query_result_fields \
  tests/test_cli_run_export.py::test_run_json_contract_matches_query_result_shape \
  tests/test_cli_run_export.py::test_export_json_contract_matches_query_result_shape_on_disk \
  tests/test_cli_inspect_sample.py::test_inspect_json_contract_includes_source_dialect_columns_row_count_and_warnings \
  tests/test_cli_profile.py::test_profile_json_contract_includes_source_counts_columns_and_warnings \
  tests/test_cli_check.py::test_check_json_contract_omits_failures_by_default \
  tests/test_cli_check.py::test_check_json_contract_includes_failure_samples_when_requested -q
```

Expected: PASS.

- [ ] **Step 2: Run the standard repo quality gate**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

Expected: PASS for all commands.

- [ ] **Step 3: Inspect the final tree and recent commit stack**

Run:

```bash
git status --short
git log --oneline -4
```

Expected:

- the working tree is clean after the earlier task commits
- the recent commit stack contains the query-shaped test batch, the
  inspect/profile/check batch, the contract doc, and the README link
- no scope drift into `sample`, `tables`, benchmark artifacts, JSON Schema
  files, or unplanned runtime edits

## Plan Self-Review Checklist

- Spec coverage:
  - current `v0.8` contract doc: covered by Task 3
  - ideal `v1` direction: covered by Task 3
  - focused structural tests: covered by Tasks 1 and 2
  - README discoverability: covered by Task 4
  - full gate and final tree review: covered by Task 5

- Placeholder scan:
  - no `TBD`, `TODO`, or implied “fill this in later” steps remain

- Type consistency:
  - query-shaped payload uses `columns`, `rows`, `row_count`, `elapsed_ms`
  - inspect uses structured `row_count`
  - profile uses integer `row_count`
  - check uses conditional `checks[*].failures`
