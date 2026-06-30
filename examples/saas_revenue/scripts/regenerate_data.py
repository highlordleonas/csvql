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
    SubscriptionRow(
        "SUB-004", "CUST-004", "starter", "monthly", "cancelled", "2025-03-01", "2025-04-01", 0.0
    ),
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
        writer = DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
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
