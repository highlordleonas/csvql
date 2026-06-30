import json
from hashlib import sha256
from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql.benchmark_data import (
    SyntheticSalesSpec,
    describe_sales_project,
    write_synthetic_sales_project,
)
from csvql.benchmarking import BenchmarkDatasetRecord
from csvql.checks import run_configured_checks
from csvql.cli import app
from csvql.project_config import load_project

runner = CliRunner()
EXAMPLE_SALES = Path(__file__).resolve().parents[1] / "examples" / "sales"


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


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
