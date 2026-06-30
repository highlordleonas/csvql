# CSVQL v0.7 Benchmark And Release Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reproducible benchmark and release-readiness workflows for the existing CSVQL CLI without changing public command contracts, config schema, or exit-code behavior.

**Architecture:** Keep all v0.7 hardening logic outside `csvql.cli` by adding internal benchmark and release helper modules under `src/csvql/` plus thin repo-local scripts under `scripts/`. Reuse the shipped `examples/sales` project as the fixture tier by giving it passing checks, generate medium and large synthetic sales-like projects with the same query/config shape, and emit one JSON artifact plus one derived Markdown summary per benchmark run under ignored `output/`.

**Tech Stack:** Python 3.12, Typer runtime, DuckDB, PyYAML, Rich, uv, pytest, Ruff, mypy, hatchling via `uv build`.

---

## Preconditions

- The current handoff checkout is detached at `e40d648`, and `codex/v07-benchmark-release-hardening` is still active in another worktree. Before starting Task 1, free that branch or create a fresh named implementation branch/worktree from `e40d648` so the commit steps below do not land on detached `HEAD`.
- Sync the dev environment before any test or script task. Use:

```bash
uv sync --all-extras --frozen
```

- Verify the local test runner exists before file edits:

```bash
uv run pytest --co -q
```

Expected: test collection output instead of `Failed to spawn: pytest`.

## Scope And Constraints

- Do not add a public `csvql benchmark` command.
- Do not change existing JSON payloads for `query`, `inspect`, `sample`, `run`, `export`, `profile`, or `check`.
- Do not change `.csvql.yml` schema beyond adding passing checks to the shipped example project.
- Do not add publish automation, PyPI workflow, GitHub release automation, or changelog policy work.
- Keep benchmark artifacts machine-local and untracked under `output/`.
- Use `sys.executable -m csvql` inside the benchmark runner so timing excludes `uv` startup.
- The benchmark matrix is fixed for v0.7:
  - `query data/orders.csv --output json`
  - `run queries/revenue_by_month.sql --output json`
  - `inspect orders --output json`
  - `inspect orders --exact --output json`
  - `profile orders --output json`
  - `check orders --output json`
- Fixture, medium, and large tiers must all support the full matrix, including `check`.
- Do not claim large-file readiness, production readiness, sandbox safety, or untrusted-SQL safety anywhere in code or docs.

## File Map

- Modify: `examples/sales/.csvql.yml`
- Create: `src/csvql/benchmarking.py`
- Create: `src/csvql/benchmark_data.py`
- Create: `src/csvql/benchmark_runner.py`
- Create: `src/csvql/release_readiness.py`
- Create: `scripts/benchmark_csvql.py`
- Create: `scripts/render_benchmark_summary.py`
- Create: `scripts/verify_release_readiness.py`
- Create: `tests/test_benchmarking.py`
- Create: `tests/test_benchmark_data.py`
- Create: `tests/test_benchmark_runner.py`
- Create: `tests/test_release_readiness.py`
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`
- Create: `docs/benchmarking.md`
- Create: `docs/release-readiness.md`

`src/csvql/benchmarking.py`
: typed artifact models, JSON serialization, JSON loading, and Markdown summary rendering

`src/csvql/benchmark_data.py`
: deterministic synthetic sales-project generation and dataset metadata capture

`src/csvql/benchmark_runner.py`
: benchmark case matrix, subprocess execution, timing, validation, and artifact writing

`src/csvql/release_readiness.py`
: version consistency checks, built-wheel selection, smoke-fixture creation, and release-proof helpers

`scripts/*.py`
: thin wrappers only; no benchmark or release logic should live exclusively in script-local code

## Task 1: Turn The Shipped Example Project Into A Valid Benchmark Fixture

**Files:**
- Modify: `examples/sales/.csvql.yml`
- Create: `tests/test_benchmark_data.py`
- Test: `tests/test_cli_check.py`

- [ ] **Step 1: Add a failing fixture-proof test**

Create `tests/test_benchmark_data.py` with:

```python
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql.cli import app

runner = CliRunner()
EXAMPLE_SALES = Path(__file__).resolve().parents[1] / "examples" / "sales"


def test_shipped_sales_example_passes_check_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(EXAMPLE_SALES)

    result = runner.invoke(app, ["check", "orders", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "passed"
    assert payload["check_count"] == 5
    assert [check["name"] for check in payload["checks"]] == [
        "order_id_required",
        "order_id_unique",
        "customer_exists",
        "total_amount_nonnegative",
        "row_count_expected",
    ]
```

- [ ] **Step 2: Run the focused failing test**

Run:

```bash
uv run pytest tests/test_benchmark_data.py::test_shipped_sales_example_passes_check_command -q
```

Expected: FAIL because `examples/sales/.csvql.yml` does not define the required checks yet.

- [ ] **Step 3: Add passing checks to the shipped example project**

Replace `examples/sales/.csvql.yml` with:

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
  orders:
    path: data/orders.csv
    checks:
      - name: order_id_required
        type: not_null
        column: order_id
      - name: order_id_unique
        type: unique
        column: order_id
      - name: customer_exists
        type: foreign_key
        column: customer_id
        references:
          table: customers
          column: customer_id
      - name: total_amount_nonnegative
        type: min
        column: total_amount
        value: 0
      - name: row_count_expected
        type: row_count_between
        min: 1
```

- [ ] **Step 4: Verify the fixture proof plus existing check behavior**

Run:

```bash
uv run pytest tests/test_benchmark_data.py tests/test_cli_check.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the fixture benchmark baseline**

```bash
git add examples/sales/.csvql.yml tests/test_benchmark_data.py
git commit -m "test: add passing checks to benchmark fixture"
```

## Task 2: Add Benchmark Artifact Models And Markdown Summary Rendering

**Files:**
- Create: `src/csvql/benchmarking.py`
- Create: `tests/test_benchmarking.py`

- [ ] **Step 1: Add failing tests for artifact serialization and Markdown rendering**

Create `tests/test_benchmarking.py` with:

```python
from csvql.benchmarking import (
    BenchmarkArtifact,
    BenchmarkCaseResult,
    BenchmarkDatasetRecord,
    BenchmarkMetadata,
    load_benchmark_artifact,
    render_benchmark_summary,
)


def test_benchmark_artifact_round_trips_through_json(tmp_path) -> None:
    artifact = BenchmarkArtifact(
        metadata=BenchmarkMetadata(
            schema_version=1,
            csvql_version="0.1.0",
            duckdb_version="1.5.4",
            python_version="3.12.11",
            platform="macOS-15-arm64",
            generated_at="2026-06-29T18:00:00Z",
            warmup_runs=1,
            measured_runs=5,
        ),
        datasets=(
            BenchmarkDatasetRecord(
                dataset_id="fixture",
                project_path="examples/sales",
                seed=None,
                customer_rows=3,
                order_rows=4,
                file_sizes={"data/customers.csv": 120, "data/orders.csv": 220},
            ),
        ),
        cases=(
            BenchmarkCaseResult(
                case_id="profile_json",
                dataset_id="fixture",
                label="profile orders json",
                command=("profile", "orders", "--output", "json"),
                measured_timings_ms=(8.0, 8.5, 9.0, 8.2, 8.7),
                median_ms=8.5,
                min_ms=8.0,
                max_ms=9.0,
                validation={"row_count": 4},
            ),
        ),
        notes=(
            "Local benchmark evidence only.",
            "No large-file claim beyond recorded datasets.",
        ),
    )

    artifact_path = tmp_path / "benchmark.json"
    artifact.write_json(artifact_path)
    loaded = load_benchmark_artifact(artifact_path)

    assert loaded == artifact


def test_render_benchmark_summary_includes_dataset_table_and_notes() -> None:
    artifact = BenchmarkArtifact(
        metadata=BenchmarkMetadata(
            schema_version=1,
            csvql_version="0.1.0",
            duckdb_version="1.5.4",
            python_version="3.12.11",
            platform="macOS-15-arm64",
            generated_at="2026-06-29T18:00:00Z",
            warmup_runs=1,
            measured_runs=5,
        ),
        datasets=(
            BenchmarkDatasetRecord(
                dataset_id="fixture",
                project_path="examples/sales",
                seed=None,
                customer_rows=3,
                order_rows=4,
                file_sizes={"data/customers.csv": 120, "data/orders.csv": 220},
            ),
        ),
        cases=(
            BenchmarkCaseResult(
                case_id="query_json",
                dataset_id="fixture",
                label="query orders json",
                command=("query", "data/orders.csv", "--output", "json", "SELECT 1"),
                measured_timings_ms=(3.0, 3.1, 3.2, 3.3, 3.4),
                median_ms=3.2,
                min_ms=3.0,
                max_ms=3.4,
                validation={"row_count": 1},
            ),
        ),
        notes=("Local benchmark evidence only.",),
    )

    summary = render_benchmark_summary(artifact)

    assert "# CSVQL Benchmark Summary" in summary
    assert "fixture" in summary
    assert "query orders json" in summary
    assert "3.200" in summary
    assert "Local benchmark evidence only." in summary
```

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
uv run pytest tests/test_benchmarking.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'csvql.benchmarking'`.

- [ ] **Step 3: Add typed artifact and summary helpers**

Create `src/csvql/benchmarking.py`:

```python
"""Typed benchmark artifacts and Markdown rendering."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BenchmarkMetadata:
    schema_version: int
    csvql_version: str
    duckdb_version: str
    python_version: str
    platform: str
    generated_at: str
    warmup_runs: int
    measured_runs: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "csvql_version": self.csvql_version,
            "duckdb_version": self.duckdb_version,
            "python_version": self.python_version,
            "platform": self.platform,
            "generated_at": self.generated_at,
            "warmup_runs": self.warmup_runs,
            "measured_runs": self.measured_runs,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkDatasetRecord:
    dataset_id: str
    project_path: str
    seed: int | None
    customer_rows: int
    order_rows: int
    file_sizes: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "project_path": self.project_path,
            "seed": self.seed,
            "customer_rows": self.customer_rows,
            "order_rows": self.order_rows,
            "file_sizes": dict(sorted(self.file_sizes.items())),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkCaseResult:
    case_id: str
    dataset_id: str
    label: str
    command: tuple[str, ...]
    measured_timings_ms: tuple[float, ...]
    median_ms: float
    min_ms: float
    max_ms: float
    validation: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "dataset_id": self.dataset_id,
            "label": self.label,
            "command": list(self.command),
            "measured_timings_ms": list(self.measured_timings_ms),
            "median_ms": self.median_ms,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "validation": self.validation,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkArtifact:
    metadata: BenchmarkMetadata
    datasets: tuple[BenchmarkDatasetRecord, ...]
    cases: tuple[BenchmarkCaseResult, ...]
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "metadata": self.metadata.as_dict(),
            "datasets": [dataset.as_dict() for dataset in self.datasets],
            "cases": [case.as_dict() for case in self.cases],
            "notes": list(self.notes),
        }

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def load_benchmark_artifact(path: Path) -> BenchmarkArtifact:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return BenchmarkArtifact(
        metadata=BenchmarkMetadata(**payload["metadata"]),
        datasets=tuple(BenchmarkDatasetRecord(**dataset) for dataset in payload["datasets"]),
        cases=tuple(
            BenchmarkCaseResult(
                case_id=case["case_id"],
                dataset_id=case["dataset_id"],
                label=case["label"],
                command=tuple(case["command"]),
                measured_timings_ms=tuple(case["measured_timings_ms"]),
                median_ms=case["median_ms"],
                min_ms=case["min_ms"],
                max_ms=case["max_ms"],
                validation=case["validation"],
            )
            for case in payload["cases"]
        ),
        notes=tuple(payload["notes"]),
    )


def render_benchmark_summary(artifact: BenchmarkArtifact) -> str:
    lines = [
        "# CSVQL Benchmark Summary",
        "",
        f"- CSVQL: `{artifact.metadata.csvql_version}`",
        f"- DuckDB: `{artifact.metadata.duckdb_version}`",
        f"- Python: `{artifact.metadata.python_version}`",
        f"- Platform: `{artifact.metadata.platform}`",
        f"- Generated: `{artifact.metadata.generated_at}`",
        "",
        "## Dataset Tiers",
        "",
        "| Dataset | Customers | Orders | Seed |",
        "| --- | ---: | ---: | ---: |",
    ]
    for dataset in artifact.datasets:
        seed = "" if dataset.seed is None else str(dataset.seed)
        lines.append(
            f"| {dataset.dataset_id} | {dataset.customer_rows} | {dataset.order_rows} | {seed} |"
        )

    lines.extend(
        [
            "",
            "## Benchmark Cases",
            "",
            "| Dataset | Case | Median (ms) | Min (ms) | Max (ms) |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for case in artifact.cases:
        lines.append(
            f"| {case.dataset_id} | {case.label} | "
            f"{case.median_ms:.3f} | {case.min_ms:.3f} | {case.max_ms:.3f} |"
        )

    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {note}" for note in artifact.notes)
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Verify artifact tests**

Run:

```bash
uv run pytest tests/test_benchmarking.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the benchmark artifact layer**

```bash
git add src/csvql/benchmarking.py tests/test_benchmarking.py
git commit -m "feat: add benchmark artifact models"
```

## Task 3: Generate Deterministic Synthetic Benchmark Projects

**Files:**
- Create: `src/csvql/benchmark_data.py`
- Modify: `tests/test_benchmark_data.py`

- [ ] **Step 1: Add failing tests for deterministic project generation**

Append to `tests/test_benchmark_data.py`:

```python
from hashlib import sha256

from csvql.checks import run_configured_checks
from csvql.benchmarking import BenchmarkDatasetRecord
from csvql.project_config import load_project
from csvql.benchmark_data import (
    SyntheticSalesSpec,
    describe_sales_project,
    write_synthetic_sales_project,
)


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_write_synthetic_sales_project_is_deterministic_for_same_seed(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    spec = SyntheticSalesSpec(
        dataset_id="synthetic_medium",
        seed=20260629,
        customer_count=10,
        orders_per_customer=3,
    )

    write_synthetic_sales_project(left, spec)
    write_synthetic_sales_project(right, spec)

    assert _hash_tree(left) == _hash_tree(right)


def test_generated_project_loads_and_all_checks_pass(tmp_path: Path) -> None:
    spec = SyntheticSalesSpec(
        dataset_id="synthetic_medium",
        seed=20260629,
        customer_count=8,
        orders_per_customer=2,
    )
    write_synthetic_sales_project(tmp_path, spec)

    context = load_project(tmp_path)
    result = run_configured_checks(
        context,
        table_name="orders",
        show_failures=False,
        failure_limit=5,
    )

    assert result.status == "passed"
    assert result.check_count == 5


def test_describe_sales_project_returns_row_counts_and_file_sizes(tmp_path: Path) -> None:
    spec = SyntheticSalesSpec(
        dataset_id="synthetic_medium",
        seed=20260629,
        customer_count=8,
        orders_per_customer=2,
    )
    write_synthetic_sales_project(tmp_path, spec)

    record = describe_sales_project(
        tmp_path,
        dataset_id="synthetic_medium",
        seed=20260629,
        project_path="datasets/synthetic_medium",
    )

    assert record == BenchmarkDatasetRecord(
        dataset_id="synthetic_medium",
        project_path="datasets/synthetic_medium",
        seed=20260629,
        customer_rows=8,
        order_rows=16,
        file_sizes=record.file_sizes,
    )
    assert set(record.file_sizes) == {"data/customers.csv", "data/orders.csv"}
```

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
uv run pytest tests/test_benchmark_data.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'csvql.benchmark_data'`.

- [ ] **Step 3: Add deterministic synthetic-project generation**

Create `src/csvql/benchmark_data.py`:

```python
"""Deterministic synthetic sales-project generation for benchmarking."""

from __future__ import annotations

from csv import DictWriter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import random

import yaml

CONFIG_TEXT = {
    "version": 1,
    "tables": {
        "customers": {
            "path": "data/customers.csv",
            "checks": [
                {"name": "customer_id_required", "type": "not_null", "column": "customer_id"},
                {"name": "customer_id_unique", "type": "unique", "column": "customer_id"},
            ],
        },
        "orders": {
            "path": "data/orders.csv",
            "checks": [
                {"name": "order_id_required", "type": "not_null", "column": "order_id"},
                {"name": "order_id_unique", "type": "unique", "column": "order_id"},
                {
                    "name": "customer_exists",
                    "type": "foreign_key",
                    "column": "customer_id",
                    "references": {"table": "customers", "column": "customer_id"},
                },
                {
                    "name": "total_amount_nonnegative",
                    "type": "min",
                    "column": "total_amount",
                    "value": 0,
                },
                {"name": "row_count_expected", "type": "row_count_between", "min": 1},
            ],
        },
    },
}

REVENUE_BY_MONTH_SQL = """SELECT
    date_trunc('month', order_date) AS order_month,
    COUNT(*) AS order_count,
    SUM(total_amount) AS revenue
FROM orders
GROUP BY 1
ORDER BY 1;
"""

CUSTOMER_LTV_SQL = """SELECT
    c.customer_id,
    c.email,
    COUNT(o.order_id) AS order_count,
    SUM(o.total_amount) AS lifetime_value
FROM customers c
JOIN orders o USING (customer_id)
GROUP BY c.customer_id, c.email
ORDER BY lifetime_value DESC;
"""


@dataclass(frozen=True, slots=True)
class SyntheticSalesSpec:
    dataset_id: str
    seed: int
    customer_count: int
    orders_per_customer: int


def write_synthetic_sales_project(root: Path, spec: SyntheticSalesSpec) -> None:
    rng = random.Random(spec.seed)
    data_dir = root / "data"
    query_dir = root / "queries"
    data_dir.mkdir(parents=True, exist_ok=True)
    query_dir.mkdir(parents=True, exist_ok=True)

    customers_path = data_dir / "customers.csv"
    orders_path = data_dir / "orders.csv"

    with customers_path.open("w", encoding="utf-8", newline="") as handle:
        writer = DictWriter(handle, fieldnames=["customer_id", "email", "created_at"])
        writer.writeheader()
        for index in range(1, spec.customer_count + 1):
            writer.writerow(
                {
                    "customer_id": f"CUST-{index:05d}",
                    "email": f"customer{index:05d}@example.com",
                    "created_at": (date(2025, 1, 1) + timedelta(days=index % 90)).isoformat(),
                }
            )

    statuses = ("paid", "pending", "refunded")
    with orders_path.open("w", encoding="utf-8", newline="") as handle:
        writer = DictWriter(
            handle,
            fieldnames=["order_id", "customer_id", "order_date", "status", "total_amount"],
        )
        writer.writeheader()
        order_index = 1
        for customer_index in range(1, spec.customer_count + 1):
            customer_id = f"CUST-{customer_index:05d}"
            for _ in range(spec.orders_per_customer):
                writer.writerow(
                    {
                        "order_id": f"ORD-{order_index:07d}",
                        "customer_id": customer_id,
                        "order_date": (
                            date(2025, 3, 1) + timedelta(days=order_index % 120)
                        ).isoformat(),
                        "status": statuses[order_index % len(statuses)],
                        "total_amount": f"{rng.uniform(10, 500):.2f}",
                    }
                )
                order_index += 1

    (root / ".csvql.yml").write_text(
        yaml.safe_dump(CONFIG_TEXT, sort_keys=False),
        encoding="utf-8",
    )
    (query_dir / "revenue_by_month.sql").write_text(REVENUE_BY_MONTH_SQL, encoding="utf-8")
    (query_dir / "customer_ltv.sql").write_text(CUSTOMER_LTV_SQL, encoding="utf-8")


def describe_sales_project(
    root: Path,
    *,
    dataset_id: str,
    seed: int | None,
    project_path: str,
) -> "BenchmarkDatasetRecord":
    from csvql.benchmarking import BenchmarkDatasetRecord

    customers_path = root / "data" / "customers.csv"
    orders_path = root / "data" / "orders.csv"
    return BenchmarkDatasetRecord(
        dataset_id=dataset_id,
        project_path=project_path,
        seed=seed,
        customer_rows=_csv_row_count(customers_path),
        order_rows=_csv_row_count(orders_path),
        file_sizes={
            "data/customers.csv": customers_path.stat().st_size,
            "data/orders.csv": orders_path.stat().st_size,
        },
    )


def _csv_row_count(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return max(sum(1 for _ in handle) - 1, 0)
```

- [ ] **Step 4: Verify synthetic generation plus fixture proof**

Run:

```bash
uv run pytest tests/test_benchmark_data.py tests/test_cli_check.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the benchmark data generator**

```bash
git add src/csvql/benchmark_data.py tests/test_benchmark_data.py
git commit -m "feat: add synthetic benchmark project generator"
```

## Task 4: Add The Benchmark Runner Core And Thin Benchmark Scripts

**Files:**
- Create: `src/csvql/benchmark_runner.py`
- Create: `scripts/benchmark_csvql.py`
- Create: `scripts/render_benchmark_summary.py`
- Create: `tests/test_benchmark_runner.py`

- [ ] **Step 1: Add failing tests for the case matrix and subprocess runner**

Create `tests/test_benchmark_runner.py`:

```python
from pathlib import Path
from subprocess import CompletedProcess
import json

from csvql.benchmark_runner import (
    BenchmarkCaseSpec,
    build_default_case_specs,
    run_case_benchmark,
)


def test_build_default_case_specs_match_v07_matrix() -> None:
    assert [case.case_id for case in build_default_case_specs()] == [
        "query_json",
        "run_json",
        "inspect_json",
        "inspect_exact_json",
        "profile_json",
        "check_json",
    ]


def test_run_case_benchmark_uses_python_module_entrypoint(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path]] = []

    def fake_run(args, *, cwd, capture_output, text, check):
        calls.append((list(args), Path(cwd)))
        stdout = json.dumps(
            {
                "columns": ["row_count"],
                "rows": [{"row_count": 1}],
                "row_count": 1,
                "elapsed_ms": 0.2,
            }
        )
        return CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    ticks = iter([1.0, 1.05, 2.0, 2.06, 3.0, 3.08, 4.0, 4.07, 5.0, 5.09, 6.0, 6.10])

    case = BenchmarkCaseSpec(
        case_id="query_json",
        label="query orders json",
        command=(
            "query",
            "data/orders.csv",
            "--output",
            "json",
            "SELECT COUNT(*) AS row_count FROM orders",
        ),
        expected_json_keys=("columns", "rows", "row_count", "elapsed_ms"),
    )

    result = run_case_benchmark(
        case,
        dataset_root=tmp_path,
        run_command=fake_run,
        clock=lambda: next(ticks),
        warmup_runs=1,
        measured_runs=5,
    )

    assert calls[0][0][1:3] == ["-m", "csvql"]
    assert calls[0][1] == tmp_path
    assert result.case_id == "query_json"
    assert len(result.measured_timings_ms) == 5
```

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
uv run pytest tests/test_benchmark_runner.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'csvql.benchmark_runner'`.

- [ ] **Step 3: Add the core runner**

Create `src/csvql/benchmark_runner.py`:

```python
"""Benchmark execution for CSVQL repo-local hardening workflows."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

from csvql.benchmarking import BenchmarkCaseResult


@dataclass(frozen=True, slots=True)
class BenchmarkCaseSpec:
    case_id: str
    label: str
    command: tuple[str, ...]
    expected_json_keys: tuple[str, ...]


def build_default_case_specs() -> tuple[BenchmarkCaseSpec, ...]:
    return (
        BenchmarkCaseSpec(
            case_id="query_json",
            label="query orders json",
            command=(
                "query",
                "data/orders.csv",
                "--output",
                "json",
                "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status ORDER BY status",
            ),
            expected_json_keys=("columns", "rows", "row_count", "elapsed_ms"),
        ),
        BenchmarkCaseSpec(
            case_id="run_json",
            label="run revenue_by_month json",
            command=("run", "queries/revenue_by_month.sql", "--output", "json"),
            expected_json_keys=("columns", "rows", "row_count", "elapsed_ms"),
        ),
        BenchmarkCaseSpec(
            case_id="inspect_json",
            label="inspect orders json",
            command=("inspect", "orders", "--output", "json"),
            expected_json_keys=("source", "dialect", "columns", "row_count", "warnings"),
        ),
        BenchmarkCaseSpec(
            case_id="inspect_exact_json",
            label="inspect orders exact json",
            command=("inspect", "orders", "--exact", "--output", "json"),
            expected_json_keys=("source", "dialect", "columns", "row_count", "warnings"),
        ),
        BenchmarkCaseSpec(
            case_id="profile_json",
            label="profile orders json",
            command=("profile", "orders", "--output", "json"),
            expected_json_keys=(
                "source",
                "row_count",
                "column_count",
                "duplicate_row_count",
                "columns",
                "warnings",
            ),
        ),
        BenchmarkCaseSpec(
            case_id="check_json",
            label="check orders json",
            command=("check", "orders", "--output", "json"),
            expected_json_keys=("status", "check_count", "passed_count", "failed_count", "checks", "warnings"),
        ),
    )


def run_case_benchmark(
    case: BenchmarkCaseSpec,
    *,
    dataset_root: Path,
    run_command=subprocess.run,
    clock=time.perf_counter,
    warmup_runs: int,
    measured_runs: int,
) -> BenchmarkCaseResult:
    for _ in range(warmup_runs):
        _run_once(case, dataset_root=dataset_root, run_command=run_command, clock=clock)

    timings: list[float] = []
    validation: dict[str, object] = {}
    for _ in range(measured_runs):
        elapsed_ms, payload = _run_once(
            case,
            dataset_root=dataset_root,
            run_command=run_command,
            clock=clock,
        )
        timings.append(elapsed_ms)
        validation = _validate_json_payload(case, payload)

    return BenchmarkCaseResult(
        case_id=case.case_id,
        dataset_id=dataset_root.name,
        label=case.label,
        command=case.command,
        measured_timings_ms=tuple(timings),
        median_ms=statistics.median(timings),
        min_ms=min(timings),
        max_ms=max(timings),
        validation=validation,
    )


def _run_once(case: BenchmarkCaseSpec, *, dataset_root: Path, run_command, clock) -> tuple[float, str]:
    args = [sys.executable, "-m", "csvql", *case.command]
    started = clock()
    completed = run_command(
        args,
        cwd=dataset_root,
        capture_output=True,
        text=True,
        check=True,
    )
    elapsed_ms = (clock() - started) * 1000
    return elapsed_ms, completed.stdout


def _validate_json_payload(case: BenchmarkCaseSpec, stdout: str) -> dict[str, object]:
    payload = json.loads(stdout)
    missing = [key for key in case.expected_json_keys if key not in payload]
    if missing:
        raise ValueError(f"{case.case_id} missing JSON keys: {missing}")
    validation: dict[str, object] = {"stdout_keys": sorted(payload.keys())}
    if "row_count" in payload:
        validation["row_count"] = payload["row_count"]
    if "status" in payload:
        validation["status"] = payload["status"]
    return validation
```

- [ ] **Step 4: Add the benchmark entry scripts**

Create `scripts/benchmark_csvql.py`:

```python
from pathlib import Path

from csvql.benchmark_runner import run_case_benchmark


def main() -> None:
    raise SystemExit("Replace this stub in the next step with the full suite entrypoint.")


if __name__ == "__main__":
    main()
```

Replace the stub immediately with a real entrypoint:

```python
import argparse
from datetime import UTC, datetime
from pathlib import Path
import platform

import duckdb

from csvql import __version__
from csvql.benchmark_data import (
    SyntheticSalesSpec,
    describe_sales_project,
    write_synthetic_sales_project,
)
from csvql.benchmark_runner import build_default_case_specs, run_case_benchmark
from csvql.benchmarking import BenchmarkArtifact, BenchmarkDatasetRecord, BenchmarkMetadata, render_benchmark_summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="output/benchmarks")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    run_root = repo_root / args.output_root / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    datasets_root = run_root / "datasets"
    datasets_root.mkdir(parents=True, exist_ok=True)

    fixture_root = repo_root / "examples" / "sales"
    medium_root = datasets_root / "synthetic_medium"
    large_root = datasets_root / "synthetic_large"
    write_synthetic_sales_project(medium_root, SyntheticSalesSpec("synthetic_medium", 20260629, 10000, 10))
    write_synthetic_sales_project(large_root, SyntheticSalesSpec("synthetic_large", 20260629, 50000, 10))

    dataset_roots = {
        "fixture": fixture_root,
        "synthetic_medium": medium_root,
        "synthetic_large": large_root,
    }

    dataset_records = (
        describe_sales_project(
            fixture_root,
            dataset_id="fixture",
            seed=None,
            project_path="examples/sales",
        ),
        describe_sales_project(
            medium_root,
            dataset_id="synthetic_medium",
            seed=20260629,
            project_path=str(medium_root.relative_to(repo_root)),
        ),
        describe_sales_project(
            large_root,
            dataset_id="synthetic_large",
            seed=20260629,
            project_path=str(large_root.relative_to(repo_root)),
        ),
    )

    case_results = []
    for dataset_id, dataset_root in dataset_roots.items():
        for case in build_default_case_specs():
            result = run_case_benchmark(case, dataset_root=dataset_root, warmup_runs=1, measured_runs=5)
            case_results.append(
                result if result.dataset_id == dataset_id else result.__class__(
                    case_id=result.case_id,
                    dataset_id=dataset_id,
                    label=result.label,
                    command=result.command,
                    measured_timings_ms=result.measured_timings_ms,
                    median_ms=result.median_ms,
                    min_ms=result.min_ms,
                    max_ms=result.max_ms,
                    validation=result.validation,
                )
            )

    artifact = BenchmarkArtifact(
        metadata=BenchmarkMetadata(
            schema_version=1,
            csvql_version=__version__,
            duckdb_version=duckdb.__version__,
            python_version=platform.python_version(),
            platform=platform.platform(),
            generated_at=datetime.now(UTC).isoformat(),
            warmup_runs=1,
            measured_runs=5,
        ),
        datasets=dataset_records,
        cases=tuple(case_results),
        notes=(
            "Local benchmark evidence only.",
            "Do not claim large-file proof beyond the recorded datasets.",
        ),
    )
    artifact_path = run_root / "benchmark.json"
    summary_path = run_root / "benchmark-summary.md"
    artifact.write_json(artifact_path)
    summary_path.write_text(render_benchmark_summary(artifact), encoding="utf-8")
    print(artifact_path)
    print(summary_path)


if __name__ == "__main__":
    main()
```

Create `scripts/render_benchmark_summary.py`:

```python
import argparse
from pathlib import Path

from csvql.benchmarking import load_benchmark_artifact, render_benchmark_summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact")
    parser.add_argument("--out")
    args = parser.parse_args()

    artifact_path = Path(args.artifact).resolve()
    out_path = Path(args.out).resolve() if args.out else artifact_path.with_name("benchmark-summary.md")
    artifact = load_benchmark_artifact(artifact_path)
    out_path.write_text(render_benchmark_summary(artifact), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Verify the runner tests and benchmark scripts**

Run:

```bash
uv run pytest tests/test_benchmarking.py tests/test_benchmark_data.py tests/test_benchmark_runner.py -q
uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Expected:
- pytest PASS
- the script prints two paths under `output/benchmarks/<run-id>/`
- both `benchmark.json` and `benchmark-summary.md` exist

- [ ] **Step 6: Commit the benchmark execution surface**

```bash
git add src/csvql/benchmark_runner.py scripts/benchmark_csvql.py scripts/render_benchmark_summary.py tests/test_benchmark_runner.py
git commit -m "feat: add benchmark runner scripts"
```

## Task 5: Add Release-Readiness Verification And Installed-Wheel Smoke Proof

**Files:**
- Create: `src/csvql/release_readiness.py`
- Create: `scripts/verify_release_readiness.py`
- Create: `tests/test_release_readiness.py`

- [ ] **Step 1: Add failing tests for version consistency and wheel selection**

Create `tests/test_release_readiness.py`:

```python
from pathlib import Path

import pytest

from csvql.release_readiness import (
    select_built_wheel,
    version_strings_match,
)


def test_version_strings_match_requires_all_three_sources() -> None:
    assert version_strings_match("0.1.0", "0.1.0", "0.1.0") is True
    assert version_strings_match("0.1.0", "0.1.1", "0.1.0") is False


def test_select_built_wheel_returns_matching_wheel(tmp_path: Path) -> None:
    wheel = tmp_path / "csvql-0.1.0-py3-none-any.whl"
    wheel.write_text("", encoding="utf-8")

    assert select_built_wheel(tmp_path, "0.1.0") == wheel


def test_select_built_wheel_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        select_built_wheel(tmp_path, "0.1.0")
```

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
uv run pytest tests/test_release_readiness.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'csvql.release_readiness'`.

- [ ] **Step 3: Add release-readiness helpers**

Create `src/csvql/release_readiness.py`:

```python
"""Helpers for repo-local release-readiness verification."""

from __future__ import annotations

from pathlib import Path
import re
import tomllib

_VERSION_RE = re.compile(r'^__version__ = "(?P<version>[^"]+)"$', re.MULTILINE)


def read_pyproject_version(pyproject_path: Path) -> str:
    payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def read_package_version(init_path: Path) -> str:
    match = _VERSION_RE.search(init_path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"Could not find __version__ in {init_path}")
    return match.group("version")


def version_strings_match(pyproject_version: str, package_version: str, cli_version: str) -> bool:
    return pyproject_version == package_version == cli_version


def select_built_wheel(dist_dir: Path, version: str) -> Path:
    matches = sorted(dist_dir.glob(f"csvql-{version}-*.whl"))
    if not matches:
        raise FileNotFoundError(f"No wheel found for csvql {version} in {dist_dir}")
    return matches[0]
```

- [ ] **Step 4: Add the release-readiness script**

Create `scripts/verify_release_readiness.py`:

```python
import argparse
from pathlib import Path
import subprocess
import sys

from csvql.release_readiness import (
    read_package_version,
    read_pyproject_version,
    select_built_wheel,
    version_strings_match,
)


def _run(args: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)
    return completed.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", default="output/release-readiness")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    work_dir = (repo_root / args.work_dir).resolve()
    dist_dir = work_dir / "dist"
    smoke_dir = work_dir / "smoke"
    venv_dir = work_dir / "smoke-venv"
    work_dir.mkdir(parents=True, exist_ok=True)
    smoke_dir.mkdir(parents=True, exist_ok=True)

    pyproject_version = read_pyproject_version(repo_root / "pyproject.toml")
    package_version = read_package_version(repo_root / "src" / "csvql" / "__init__.py")
    cli_version = _run([sys.executable, "-m", "csvql", "--version"], cwd=repo_root)
    if not version_strings_match(pyproject_version, package_version, cli_version):
        raise SystemExit(
            f"Version mismatch: pyproject={pyproject_version} package={package_version} cli={cli_version}"
        )

    _run(["uv", "build", "--sdist", "--wheel", "--out-dir", str(dist_dir)], cwd=repo_root)
    wheel = select_built_wheel(dist_dir, pyproject_version)
    _run(["uv", "venv", "--seed", str(venv_dir)], cwd=repo_root)
    python_path = venv_dir / "bin" / "python"
    csvql_path = venv_dir / "bin" / "csvql"
    _run(["uv", "pip", "install", "--python", str(python_path), str(wheel)], cwd=repo_root)

    smoke_csv = smoke_dir / "orders.csv"
    smoke_csv.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    _run([str(csvql_path), "--version"], cwd=repo_root)
    inspect_output = _run([str(csvql_path), "inspect", str(smoke_csv), "--output", "json"], cwd=repo_root)
    print(inspect_output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Verify release-readiness tests and smoke script**

Run:

```bash
uv run pytest tests/test_release_readiness.py -q
uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

Expected:
- pytest PASS
- the script prints JSON from the installed wheel's `inspect` command
- `output/release-readiness/dist/` contains both an sdist and a wheel

- [ ] **Step 6: Commit the release-readiness surface**

```bash
git add src/csvql/release_readiness.py scripts/verify_release_readiness.py tests/test_release_readiness.py
git commit -m "feat: add release readiness verification"
```

## Task 6: Document The New Hardening Workflows And Mark v0.7 Implemented

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`
- Create: `docs/benchmarking.md`
- Create: `docs/release-readiness.md`

- [ ] **Step 1: Add failing docs assertions for the new surfaces**

Append to `tests/test_benchmarking.py`:

```python
from pathlib import Path


def test_readme_mentions_repo_local_benchmark_workflow() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")

    assert "uv run python scripts/benchmark_csvql.py" in readme
    assert "uv run python scripts/verify_release_readiness.py" in readme
    assert "Local benchmark evidence only" in readme
```

- [ ] **Step 2: Run the focused failing docs test**

Run:

```bash
uv run pytest tests/test_benchmarking.py::test_readme_mentions_repo_local_benchmark_workflow -q
```

Expected: FAIL because the README does not mention the new workflows yet.

- [ ] **Step 3: Add benchmark and release-readiness docs**

Create `docs/benchmarking.md`:

```markdown
# Benchmarking

CSVQL v0.7 includes a repo-local benchmark harness for the existing CLI surface.

## Scope

The benchmark matrix covers:

- `query data/orders.csv --output json`
- `run queries/revenue_by_month.sql --output json`
- `inspect orders --output json`
- `inspect orders --exact --output json`
- `profile orders --output json`
- `check orders --output json`

## Run It

Run `uv run python scripts/benchmark_csvql.py --output-root output/benchmarks`.

The run writes:

- `output/benchmarks/<run-id>/benchmark.json`
- `output/benchmarks/<run-id>/benchmark-summary.md`

## Claims Boundary

- Local benchmark evidence only
- No large-file proof beyond the recorded datasets
- No production-readiness claim
```

Create `docs/release-readiness.md`:

```markdown
# Release Readiness

CSVQL v0.7 adds repo-local proof that the package can be built and installed from a wheel.

## Run It

Run `uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness`.

This workflow verifies:

- `pyproject.toml`, `src/csvql/__init__.py`, and `csvql --version` agree
- `uv build --sdist --wheel` succeeds
- an isolated wheel install can run `csvql --version`
- the installed wheel can run a tiny `inspect` command

This does not publish anything and does not create a release candidate claim.
```

- [ ] **Step 4: Update README status and command examples**

Update `README.md`:

```markdown
## Status

This repository has the v0.1 query workflow, the first inspect/sample vertical,
the v0.3 project catalog workflow, the v0.4 saved-workflow surfaces, the v0.5
profiling surface, the v0.6 data-quality check surface, and the v0.7 benchmark
and release-hardening workflows implemented for local CLI use.
```

Replace:

```markdown
Planned later:

- benchmarks and release workflow
```

with:

```markdown
Repo-local hardening now:

- benchmark harness with JSON artifact and Markdown summary
- release-readiness verification for version consistency, build smoke, and installed-wheel smoke
- local output under `output/`
```

Add a new section near the bottom:

```markdown
## Benchmark And Release Hardening

Generate local benchmark evidence:

- `uv run python scripts/benchmark_csvql.py --output-root output/benchmarks`

Verify build and install proof:

- `uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness`

These workflows are local evidence only. They do not prove production readiness
or large-file readiness beyond the recorded datasets.
```

- [ ] **Step 5: Mark v0.7 implemented in the roadmap**

Update `docs/ROADMAP.md`:

```markdown
## v0.7.0 - Benchmark And Release Hardening

Implemented:

- benchmark harness and JSON artifact
- Markdown benchmark summary
- reproducible synthetic and fixture-sized benchmark inputs
- benchmark documentation that avoids large-file claims beyond the recorded artifact
- version consistency verification
- build smoke for sdist and wheel
- installed-wheel smoke verification
- release-readiness documentation
```

- [ ] **Step 6: Verify docs tests plus file hygiene**

Run:

```bash
uv run pytest tests/test_benchmarking.py -q
git diff --check
```

Expected: PASS and no whitespace errors.

- [ ] **Step 7: Commit the documentation and roadmap updates**

```bash
git add README.md docs/ROADMAP.md docs/benchmarking.md docs/release-readiness.md tests/test_benchmarking.py
git commit -m "docs: add benchmark and release hardening workflows"
```

## Task 7: Run The Full v0.7 Verification Suite

**Files:**
- No file changes expected

- [ ] **Step 1: Run the repo quality gate**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

Expected: PASS.

- [ ] **Step 2: Generate one fresh benchmark artifact and summary**

Run:

```bash
uv run python scripts/benchmark_csvql.py --output-root output/benchmarks
```

Expected: prints the fresh artifact and summary paths under `output/benchmarks/<run-id>/`.

- [ ] **Step 3: Run the release-readiness proof**

Run:

```bash
uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness
```

Expected: prints JSON from the installed-wheel smoke run and leaves build outputs under `output/release-readiness/`.

- [ ] **Step 4: Re-render the summary from the saved artifact**

Run:

```bash
uv run python scripts/render_benchmark_summary.py output/benchmarks/<run-id>/benchmark.json
```

Expected: prints the path to `benchmark-summary.md` and overwrites it deterministically.

- [ ] **Step 5: Final diff hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected:
- `git diff --check` prints no output
- `git status --short` shows only the intended v0.7 files

## Spec Coverage Check

- Example fixture supports the full benchmark matrix: Task 1 and Task 3
- JSON artifact and Markdown summary: Task 2 and Task 4
- Deterministic medium/large synthetic projects: Task 3
- End-to-end CLI timing via `sys.executable -m csvql`: Task 4
- Untracked output under `output/`: Task 4, Task 5, and Task 6 docs
- Version consistency, build smoke, installed-wheel smoke: Task 5
- README and roadmap truth: Task 6
- Full verification and no unsupported claims: Task 7

## Notes For The Implementer

- Keep `scripts/*.py` thin. If a script starts accumulating domain logic, move it into `src/csvql/`.
- Reuse the shipped sales example query/config shape in synthetic generation. Do not invent a second benchmark-only schema.
- If the benchmark runner needs more metadata than planned, add fields to the artifact models rather than writing ad hoc dicts in the script.
- If any packaging smoke step requires a command different from this plan, update the script and docs together and prove the new command live before calling the task complete.
