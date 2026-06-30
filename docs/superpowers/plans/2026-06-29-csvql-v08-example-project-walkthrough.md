# CSVQL v0.8 Example Project And Walkthrough Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a stronger `examples/saas_revenue` project with deterministic example data, a copy/paste walkthrough, and focused proof that the existing CSVQL CLI surfaces compose into a believable local analytics workflow.

**Architecture:** Introduce one new primary example under `examples/saas_revenue` with committed CSVs, a small deterministic regeneration script, one canonical `revenue_health.sql` saved query, and end-to-end tests that exercise `inspect`, `profile`, `check`, `run`, and `export`. Keep `examples/sales` untouched in this slice as a compatibility fixture for the already-built v0.7 benchmark hardening work; move user-facing docs to the new example without changing CLI behavior.

**Tech Stack:** Python 3.12, standard-library `csv` and `pathlib`, Typer `CliRunner`, DuckDB-backed CSVQL commands, uv, pytest, Ruff, mypy, Markdown docs.

---

## Preconditions

- The current worktree contains uncommitted v0.7 benchmark-release-hardening changes. Implement this plan only after those changes are committed or in a fresh worktree branched from the committed v0.7 state.
- Sync the project environment first:

```bash
uv sync --all-extras --frozen
```

- Confirm the local test runner is available before touching files:

```bash
uv run pytest --co -q
```

Expected: test collection output instead of a missing-runner error.

## Scope And Constraints

- Do not add a new CLI command.
- Do not change any existing CLI semantics.
- Do not change any existing JSON payload shape.
- Do not change the `.csvql.yml` schema.
- Do not add `csvql doctor`, Python API work, JSON contract docs, or failure-gallery work in this plan.
- Do not migrate or rewrite the v0.7 benchmark harness in this plan.
- Keep `examples/sales` in place so the benchmark fixture remains stable.
- Make `examples/saas_revenue` the documented primary example.
- Commit an `output/` directory under the example using `.gitkeep`, because `csvql export` requires the destination directory to exist.
- Keep claims precise: no sandbox, production, or large-file claims.

## Command, JSON, Exit-Code, Config, Docs, And Test Impact

Command impact:

- none
- this plan uses existing `inspect`, `profile`, `check`, `run`, and `export` surfaces only

JSON impact:

- none to contracts
- the new example depends on current JSON behavior from `inspect`, `profile`, `check`, `run`, and `export --format json`

Exit-code impact:

- none
- `csvql check` keeps exit code `11` for configured-check failures

Config impact:

- one new example-local `.csvql.yml`
- no schema expansion

Docs impact:

- create `examples/saas_revenue/README.md`
- update top-level `README.md` to point to the new example and use its commands

Test impact:

- create one focused end-to-end example workflow test module
- keep the repo-wide gate unchanged

## File Map

- Create: `examples/saas_revenue/README.md`
- Create: `examples/saas_revenue/.csvql.yml`
- Create: `examples/saas_revenue/data/customers.csv`
- Create: `examples/saas_revenue/data/subscriptions.csv`
- Create: `examples/saas_revenue/data/revenue_movements.csv`
- Create: `examples/saas_revenue/queries/revenue_health.sql`
- Create: `examples/saas_revenue/scripts/regenerate_data.py`
- Create: `examples/saas_revenue/output/.gitkeep`
- Create: `tests/test_example_project.py`
- Modify: `README.md`

`examples/saas_revenue/scripts/regenerate_data.py`
: writes the three committed CSV files deterministically from explicit row constants

`examples/saas_revenue/.csvql.yml`
: registers the example tables and configures believable project-health checks

`examples/saas_revenue/queries/revenue_health.sql`
: produces the single canonical revenue-health readout used in the walkthrough

`examples/saas_revenue/README.md`
: holds the copy/paste golden path and explains what each command proves

`tests/test_example_project.py`
: verifies exact regeneration plus the full example workflow across existing CLI commands

`README.md`
: updates user-facing examples to point at `examples/saas_revenue`

Retain unchanged:

- `examples/sales/**`
- `src/csvql/benchmark_*.py`
- `docs/benchmarking.md`
- `tests/test_benchmark_*.py`

## Task 1: Add Failing Proof Tests For The New Example Workflow

**Files:**
- Create: `tests/test_example_project.py`

- [ ] **Step 1: Write the failing end-to-end example tests**

Create `tests/test_example_project.py` with:

```python
import json
import runpy
import shutil
from hashlib import sha256
from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql.cli import app

runner = CliRunner()
EXAMPLE_ROOT = Path(__file__).resolve().parents[1] / "examples" / "saas_revenue"


def _copy_example_project(tmp_path: Path) -> Path:
    target = tmp_path / "saas_revenue"
    shutil.copytree(EXAMPLE_ROOT, target)
    return target


def _hash_csv_outputs(project_root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(project_root)): sha256(path.read_bytes()).hexdigest()
        for path in sorted((project_root / "data").glob("*.csv"))
    }


def test_saas_revenue_regeneration_rewrites_the_same_csv_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _copy_example_project(tmp_path)
    before = _hash_csv_outputs(project_root)
    monkeypatch.chdir(project_root)

    runpy.run_path(str(project_root / "scripts" / "regenerate_data.py"), run_name="__main__")

    after = _hash_csv_outputs(project_root)
    assert after == before


def test_saas_revenue_walkthrough_commands_succeed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _copy_example_project(tmp_path)
    monkeypatch.chdir(project_root)

    inspect_result = runner.invoke(
        app,
        ["inspect", "data/revenue_movements.csv", "--output", "json"],
    )
    profile_result = runner.invoke(
        app,
        ["profile", "revenue_movements", "--output", "json"],
    )
    check_result = runner.invoke(app, ["check", "--output", "json"])
    run_result = runner.invoke(
        app,
        ["run", "queries/revenue_health.sql", "--output", "json"],
    )
    export_json_result = runner.invoke(
        app,
        [
            "export",
            "queries/revenue_health.sql",
            "--format",
            "json",
            "--out",
            "output/revenue-health.json",
        ],
    )
    export_markdown_result = runner.invoke(
        app,
        [
            "export",
            "queries/revenue_health.sql",
            "--format",
            "markdown",
            "--out",
            "output/revenue-health.md",
        ],
    )

    assert inspect_result.exit_code == 0, inspect_result.output
    inspect_payload = json.loads(inspect_result.output)
    assert inspect_payload["row_count"] == 11
    assert inspect_payload["columns"][0]["name"] == "movement_id"

    assert profile_result.exit_code == 0, profile_result.output
    profile_payload = json.loads(profile_result.output)
    assert profile_payload["row_count"] == 11
    assert profile_payload["duplicate_row_count"] == 0

    assert check_result.exit_code == 0, check_result.output
    check_payload = json.loads(check_result.output)
    assert check_payload["status"] == "passed"
    assert check_payload["check_count"] == 12

    assert run_result.exit_code == 0, run_result.output
    run_payload = json.loads(run_result.output)
    assert run_payload["row_count"] == 4
    assert run_payload["rows"][-1]["report_month"] == "2025-04-01"
    assert run_payload["rows"][-1]["starting_mrr"] == 925.0
    assert run_payload["rows"][-1]["ending_mrr"] == 950.0
    assert run_payload["rows"][-1]["net_revenue_retention_pct"] == 102.7

    assert export_json_result.exit_code == 0, export_json_result.output
    export_json_payload = json.loads(
        (project_root / "output" / "revenue-health.json").read_text(encoding="utf-8")
    )
    assert export_json_payload["rows"] == run_payload["rows"]

    assert export_markdown_result.exit_code == 0, export_markdown_result.output
    markdown_text = (project_root / "output" / "revenue-health.md").read_text(
        encoding="utf-8"
    )
    assert "| report_month | starting_mrr |" in markdown_text
    assert "| 2025-04-01 | 925.0 | 0.0 | 75.0 | 0.0 | 150.0 | 100.0 | 25.0 | 950.0 | 11400.0 | 102.7 |" in markdown_text
```

- [ ] **Step 2: Run the new focused tests and confirm they fail**

Run:

```bash
uv run pytest tests/test_example_project.py -q
```

Expected: FAIL because `examples/saas_revenue/` and its files do not exist yet.

## Task 2: Build The New Example Project And Make The Focused Tests Pass

**Files:**
- Create: `examples/saas_revenue/.csvql.yml`
- Create: `examples/saas_revenue/queries/revenue_health.sql`
- Create: `examples/saas_revenue/scripts/regenerate_data.py`
- Create: `examples/saas_revenue/output/.gitkeep`
- Create: `examples/saas_revenue/data/customers.csv`
- Create: `examples/saas_revenue/data/subscriptions.csv`
- Create: `examples/saas_revenue/data/revenue_movements.csv`
- Modify: `tests/test_example_project.py` only if a typo is discovered while making it pass

- [ ] **Step 1: Add the example config, canonical query, and deterministic regeneration script**

Create `examples/saas_revenue/.csvql.yml` with:

```yaml
version: 1
tables:
  customers:
    path: data/customers.csv
    checks:
      - name: customer_id_required
        type: not_null
        column: customer_id
      - name: customer_id_unique
        type: unique
        column: customer_id
  subscriptions:
    path: data/subscriptions.csv
    checks:
      - name: subscription_id_required
        type: not_null
        column: subscription_id
      - name: subscription_id_unique
        type: unique
        column: subscription_id
      - name: subscription_customer_exists
        type: foreign_key
        column: customer_id
        references:
          table: customers
          column: customer_id
      - name: current_mrr_nonnegative
        type: min
        column: current_mrr
        value: 0
  revenue_movements:
    path: data/revenue_movements.csv
    checks:
      - name: movement_id_required
        type: not_null
        column: movement_id
      - name: movement_id_unique
        type: unique
        column: movement_id
      - name: movement_customer_exists
        type: foreign_key
        column: customer_id
        references:
          table: customers
          column: customer_id
      - name: movement_subscription_exists
        type: foreign_key
        column: subscription_id
        references:
          table: subscriptions
          column: subscription_id
      - name: movement_type_known
        type: accepted_values
        column: movement_type
        values: [new, expansion, contraction, churn, reactivation]
      - name: movement_rows_present
        type: row_count_between
        min: 1
```

Create `examples/saas_revenue/queries/revenue_health.sql` with:

```sql
WITH monthly_changes AS (
    SELECT
        CAST(movement_month AS DATE) AS report_month,
        SUM(CASE WHEN movement_type = 'new' THEN mrr_delta ELSE 0 END) AS new_mrr,
        SUM(CASE WHEN movement_type = 'expansion' THEN mrr_delta ELSE 0 END) AS expansion_mrr,
        SUM(CASE WHEN movement_type = 'contraction' THEN ABS(mrr_delta) ELSE 0 END) AS contraction_mrr,
        SUM(CASE WHEN movement_type = 'churn' THEN ABS(mrr_delta) ELSE 0 END) AS churn_mrr,
        SUM(CASE WHEN movement_type = 'reactivation' THEN mrr_delta ELSE 0 END) AS reactivation_mrr,
        SUM(mrr_delta) AS net_mrr_change
    FROM revenue_movements
    GROUP BY 1
),
monthly_balances AS (
    SELECT
        report_month,
        new_mrr,
        expansion_mrr,
        contraction_mrr,
        churn_mrr,
        reactivation_mrr,
        net_mrr_change,
        SUM(net_mrr_change) OVER (ORDER BY report_month) AS ending_mrr
    FROM monthly_changes
),
revenue_health AS (
    SELECT
        CAST(report_month AS VARCHAR) AS report_month,
        COALESCE(LAG(ending_mrr) OVER (ORDER BY report_month), 0) AS starting_mrr,
        new_mrr,
        expansion_mrr,
        contraction_mrr,
        churn_mrr,
        reactivation_mrr,
        net_mrr_change,
        ending_mrr
    FROM monthly_balances
)
SELECT
    report_month,
    ROUND(starting_mrr, 1) AS starting_mrr,
    ROUND(new_mrr, 1) AS new_mrr,
    ROUND(expansion_mrr, 1) AS expansion_mrr,
    ROUND(contraction_mrr, 1) AS contraction_mrr,
    ROUND(churn_mrr, 1) AS churn_mrr,
    ROUND(reactivation_mrr, 1) AS reactivation_mrr,
    ROUND(net_mrr_change, 1) AS net_mrr_change,
    ROUND(ending_mrr, 1) AS ending_mrr,
    ROUND(ending_mrr * 12, 1) AS ending_arr,
    CASE
        WHEN starting_mrr = 0 THEN NULL
        ELSE ROUND(
            (
                starting_mrr
                + expansion_mrr
                + reactivation_mrr
                - contraction_mrr
                - churn_mrr
            ) / starting_mrr * 100,
            1
        )
    END AS net_revenue_retention_pct
FROM revenue_health
ORDER BY report_month;
```

Create `examples/saas_revenue/scripts/regenerate_data.py` with:

```python
from __future__ import annotations

from csv import DictWriter
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"


@dataclass(frozen=True, slots=True)
class CustomerRow:
    customer_id: str
    company_name: str
    segment: str
    created_at: str


@dataclass(frozen=True, slots=True)
class SubscriptionRow:
    subscription_id: str
    customer_id: str
    plan_name: str
    billing_period: str
    status: str
    started_at: str
    ended_at: str
    current_mrr: float


@dataclass(frozen=True, slots=True)
class RevenueMovementRow:
    movement_id: str
    customer_id: str
    subscription_id: str
    movement_month: str
    movement_type: str
    mrr_delta: float


CUSTOMERS = (
    CustomerRow("CUST-001", "Acme Analytics", "smb", "2024-11-15"),
    CustomerRow("CUST-002", "BrightPath Labs", "mid_market", "2024-12-03"),
    CustomerRow("CUST-003", "Cedar Health", "enterprise", "2025-01-12"),
    CustomerRow("CUST-004", "Delta Ops", "smb", "2025-02-01"),
    CustomerRow("CUST-005", "Echo Retail", "mid_market", "2025-03-05"),
)

SUBSCRIPTIONS = (
    SubscriptionRow("SUB-001", "CUST-001", "starter", "monthly", "active", "2025-01-01", "", 100.0),
    SubscriptionRow("SUB-002", "CUST-002", "growth", "monthly", "active", "2025-01-01", "", 225.0),
    SubscriptionRow("SUB-003", "CUST-003", "scale", "annual", "active", "2025-02-01", "", 375.0),
    SubscriptionRow("SUB-004", "CUST-004", "starter", "monthly", "cancelled", "2025-03-01", "2025-04-01", 0.0),
    SubscriptionRow("SUB-005", "CUST-005", "growth", "monthly", "active", "2025-03-01", "", 250.0),
)

REVENUE_MOVEMENTS = (
    RevenueMovementRow("MOV-001", "CUST-001", "SUB-001", "2025-01-01", "new", 100.0),
    RevenueMovementRow("MOV-002", "CUST-002", "SUB-002", "2025-01-01", "new", 200.0),
    RevenueMovementRow("MOV-003", "CUST-003", "SUB-003", "2025-02-01", "new", 300.0),
    RevenueMovementRow("MOV-004", "CUST-002", "SUB-002", "2025-02-01", "expansion", 50.0),
    RevenueMovementRow("MOV-005", "CUST-004", "SUB-004", "2025-03-01", "new", 150.0),
    RevenueMovementRow("MOV-006", "CUST-005", "SUB-005", "2025-03-01", "new", 250.0),
    RevenueMovementRow("MOV-007", "CUST-002", "SUB-002", "2025-03-01", "contraction", -25.0),
    RevenueMovementRow("MOV-008", "CUST-001", "SUB-001", "2025-03-01", "churn", -100.0),
    RevenueMovementRow("MOV-009", "CUST-001", "SUB-001", "2025-04-01", "reactivation", 100.0),
    RevenueMovementRow("MOV-010", "CUST-003", "SUB-003", "2025-04-01", "expansion", 75.0),
    RevenueMovementRow("MOV-011", "CUST-004", "SUB-004", "2025-04-01", "churn", -150.0),
)


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: tuple[object, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def main() -> None:
    _write_csv(
        DATA_ROOT / "customers.csv",
        ("customer_id", "company_name", "segment", "created_at"),
        CUSTOMERS,
    )
    _write_csv(
        DATA_ROOT / "subscriptions.csv",
        (
            "subscription_id",
            "customer_id",
            "plan_name",
            "billing_period",
            "status",
            "started_at",
            "ended_at",
            "current_mrr",
        ),
        SUBSCRIPTIONS,
    )
    _write_csv(
        DATA_ROOT / "revenue_movements.csv",
        (
            "movement_id",
            "customer_id",
            "subscription_id",
            "movement_month",
            "movement_type",
            "mrr_delta",
        ),
        REVENUE_MOVEMENTS,
    )
    print(DATA_ROOT / "customers.csv")
    print(DATA_ROOT / "subscriptions.csv")
    print(DATA_ROOT / "revenue_movements.csv")


if __name__ == "__main__":
    main()
```

Create the output directory marker:

```bash
mkdir -p examples/saas_revenue/output
touch examples/saas_revenue/output/.gitkeep
```

- [ ] **Step 2: Run the regeneration script to materialize the committed CSV fixtures**

Run:

```bash
uv run python examples/saas_revenue/scripts/regenerate_data.py
```

Expected output:

```text
/.../examples/saas_revenue/data/customers.csv
/.../examples/saas_revenue/data/subscriptions.csv
/.../examples/saas_revenue/data/revenue_movements.csv
```

- [ ] **Step 3: Run the focused tests and keep editing until they pass**

Run:

```bash
uv run pytest tests/test_example_project.py -q
```

Expected: PASS.

- [ ] **Step 4: Run a manual CLI smoke from the new example directory**

Run:

```bash
cd examples/saas_revenue
uv run csvql check --output json
uv run csvql run queries/revenue_health.sql --output json
uv run csvql export queries/revenue_health.sql --format json --out output/revenue-health.json
uv run csvql export queries/revenue_health.sql --format markdown --out output/revenue-health.md
```

Expected:

- `check` exits `0` and reports `"status": "passed"`
- `run` exits `0` and returns four monthly rows
- both `export` commands exit `0`

- [ ] **Step 5: Commit the new example project and focused tests**

```bash
git add \
  examples/saas_revenue/.csvql.yml \
  examples/saas_revenue/data/customers.csv \
  examples/saas_revenue/data/subscriptions.csv \
  examples/saas_revenue/data/revenue_movements.csv \
  examples/saas_revenue/output/.gitkeep \
  examples/saas_revenue/queries/revenue_health.sql \
  examples/saas_revenue/scripts/regenerate_data.py \
  tests/test_example_project.py
git commit -m "feat: add saas revenue example project"
```

## Task 3: Write The Copy/Paste Walkthrough And Promote The New Example In README

**Files:**
- Create: `examples/saas_revenue/README.md`
- Modify: `README.md`

- [ ] **Step 1: Add the example-local walkthrough README**

Create `examples/saas_revenue/README.md` with:

````markdown
# SaaS Revenue Example

This example models a small local B2B SaaS revenue project with three CSVs:

- `customers.csv`
- `subscriptions.csv`
- `revenue_movements.csv`

It is the primary copy/paste example for CSVQL v0.8 planning. The goal is to
show that the existing CLI surface can inspect a project, validate it, run a
saved analysis, and export results for both automation and human review.

## Quickstart

```bash
cd examples/saas_revenue

uv run csvql inspect data/revenue_movements.csv --output json
uv run csvql profile revenue_movements --output json
uv run csvql check --output json
uv run csvql run queries/revenue_health.sql --output json
uv run csvql export queries/revenue_health.sql --format json --out output/revenue-health.json
uv run csvql export queries/revenue_health.sql --format markdown --out output/revenue-health.md
```

## What The Outputs Prove

- `inspect` shows the raw shape of a core project table
- `profile` shows row counts, duplicate counts, and column-level completeness
- `check` validates project health from `.csvql.yml`
- `run` returns the canonical revenue-health readout as JSON
- `export` writes the same analysis to machine-readable JSON and a Markdown sidecar

## Main Analysis

`queries/revenue_health.sql` returns one row per month with:

- starting MRR
- new MRR
- expansion MRR
- contraction MRR
- churn MRR
- reactivation MRR
- ending MRR
- ending ARR
- net revenue retention percentage

## Regenerate The Data

The committed CSVs are intentional and reproducible. To rewrite them exactly:

```bash
cd examples/saas_revenue
uv run python scripts/regenerate_data.py
```

The script rewrites only the files under `data/`.
````

- [ ] **Step 2: Update the top-level README to point to the new example**

Replace the opening query example in `README.md` with:

````markdown
```bash
csvql query \
  --table customers=examples/saas_revenue/data/customers.csv \
  --table subscriptions=examples/saas_revenue/data/subscriptions.csv \
  "SELECT
      c.segment,
      COUNT(*) AS active_subscriptions,
      SUM(s.current_mrr) AS current_mrr
   FROM customers c
   JOIN subscriptions s USING (customer_id)
   WHERE s.status = 'active'
   GROUP BY c.segment
   ORDER BY current_mrr DESC"
```
````

Replace the single-file shortcut example with:

````markdown
```bash
uv run csvql query examples/saas_revenue/data/revenue_movements.csv \
  "SELECT movement_type, SUM(mrr_delta) AS net_mrr_change
   FROM revenue_movements
   GROUP BY movement_type
   ORDER BY movement_type"
```
````

Replace the multi-table query example with:

````markdown
```bash
uv run csvql query \
  --table customers=examples/saas_revenue/data/customers.csv \
  --table subscriptions=examples/saas_revenue/data/subscriptions.csv \
  "SELECT
      c.customer_id,
      c.company_name,
      s.plan_name,
      s.current_mrr
   FROM customers c
   JOIN subscriptions s USING (customer_id)
   WHERE s.status = 'active'
   ORDER BY s.current_mrr DESC"
```
````

Replace the JSON automation example with:

````markdown
```bash
uv run csvql query \
  --table revenue_movements=examples/saas_revenue/data/revenue_movements.csv \
  --output json \
   "SELECT movement_month, SUM(mrr_delta) AS net_mrr_change
   FROM revenue_movements
   GROUP BY movement_month
   ORDER BY movement_month"
```
````

Replace the catalog registration example with:

````markdown
```bash
uv run csvql add revenue_movements examples/saas_revenue/data/revenue_movements.csv
```
````

Replace the saved-workflow example section with:

````markdown
## Saved Workflow Examples

Run SQL from a file using catalog aliases:

```bash
cd examples/saas_revenue
uv run csvql run queries/revenue_health.sql --output json
```

Inspect a registered catalog alias and profile it:

```bash
uv run csvql inspect revenue_movements --output json
uv run csvql profile revenue_movements --output json
```

Export the main analysis:

```bash
uv run csvql export queries/revenue_health.sql \
  --format json \
  --out output/revenue-health.json

uv run csvql export queries/revenue_health.sql \
  --format markdown \
  --out output/revenue-health.md
```

See `examples/saas_revenue/README.md` for the full copy/paste walkthrough.
````

Replace the inspect and sample examples with:

````markdown
## Inspect And Sample Examples

Inspect the core revenue-movement table:

```bash
uv run csvql inspect examples/saas_revenue/data/revenue_movements.csv --output json
```

Calculate an exact row count when you explicitly want a full scan:

```bash
uv run csvql inspect examples/saas_revenue/data/revenue_movements.csv --exact --output json
```

Sample rows from the same table:

```bash
uv run csvql sample examples/saas_revenue/data/revenue_movements.csv --limit 5
```
````

Replace the profile examples with:

````markdown
## Profile Examples

Profile the revenue-movement CSV with a full scan:

```bash
uv run csvql profile examples/saas_revenue/data/revenue_movements.csv
```

Return JSON profile metrics:

```bash
uv run csvql profile examples/saas_revenue/data/revenue_movements.csv --output json
```

Profile a registered catalog alias:

```bash
cd examples/saas_revenue
uv run csvql profile revenue_movements --output json
```
````

Replace the data-quality config example with:

````markdown
```yaml
version: 1
tables:
  customers:
    path: data/customers.csv
    checks:
      - name: customer_id_required
        type: not_null
        column: customer_id
      - name: customer_id_unique
        type: unique
        column: customer_id
  subscriptions:
    path: data/subscriptions.csv
    checks:
      - name: subscription_id_required
        type: not_null
        column: subscription_id
      - name: subscription_id_unique
        type: unique
        column: subscription_id
      - name: subscription_customer_exists
        type: foreign_key
        column: customer_id
        references:
          table: customers
          column: customer_id
  revenue_movements:
    path: data/revenue_movements.csv
    checks:
      - name: movement_id_required
        type: not_null
        column: movement_id
      - name: movement_id_unique
        type: unique
        column: movement_id
      - name: movement_type_known
        type: accepted_values
        column: movement_type
        values: [new, expansion, contraction, churn, reactivation]
```
````

- [ ] **Step 3: Verify the docs point to the new example and the golden path still works**

Run:

```bash
rg -n "examples/sales" README.md
uv run pytest tests/test_example_project.py -q
```

Expected:

- `rg` prints no matches from `README.md`
- the focused example workflow tests still pass

- [ ] **Step 4: Commit the walkthrough and README updates**

```bash
git add README.md examples/saas_revenue/README.md
git commit -m "docs: add saas revenue walkthrough"
```

## Task 4: Run The Full Repo Gate And Final Diff Checks

**Files:**
- No intended file changes

- [ ] **Step 1: Re-run the deterministic generator and focused example tests**

Run:

```bash
uv run python examples/saas_revenue/scripts/regenerate_data.py
uv run pytest tests/test_example_project.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the standard repo quality gate**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
git diff --check
```

Expected: PASS for all commands.

- [ ] **Step 3: Inspect the final diff before handoff**

Run:

```bash
git status --short
git diff -- examples/saas_revenue README.md tests/test_example_project.py
```

Expected:

- only the planned example, test, and README changes are present
- no accidental changes under `examples/sales`

## Self-Review Checklist

- Spec coverage:
  - new primary example directory: Task 2
  - deterministic regeneration: Task 2 and Task 4
  - walkthrough docs: Task 3
  - JSON plus Markdown export proof: Tasks 1 and 2
  - existing-command-only workflow: Tasks 1 and 2
- Placeholder scan:
  - none left intentionally
- Type and naming consistency:
  - `revenue_health.sql`, `revenue-health.json`, and `revenue-health.md` use one naming convention
  - `revenue_movements` is the canonical inspected/profiled table across tests and docs
