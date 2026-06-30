"""Deterministic synthetic sales-project generation for benchmarking."""

from __future__ import annotations

import random
from csv import DictWriter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import yaml  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from csvql.benchmarking import BenchmarkDatasetRecord

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
    """Deterministic synthetic dataset sizing and seed inputs."""

    dataset_id: str
    seed: int
    customer_count: int
    orders_per_customer: int


def write_synthetic_sales_project(root: Path, spec: SyntheticSalesSpec) -> None:
    """Write a complete benchmark project fixture under ``root``."""

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
) -> BenchmarkDatasetRecord:
    """Return row-count and file-size facts for one generated project."""

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
    """Return the number of data rows in a CSV file with one header row."""

    with path.open(encoding="utf-8") as handle:
        return max(sum(1 for _ in handle) - 1, 0)
