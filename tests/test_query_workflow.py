from pathlib import Path

import pytest

from csvql.engine import CSVQLEngine
from csvql.exceptions import TableMappingError
from csvql.query_workflow import (
    build_inline_query_request,
    build_saved_sql_query_request,
    execute_query_request,
)


def _write_csv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_inline_query_request_rejects_table_mappings_for_single_file_mode(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path, "order_id,total_amount\nORD-001,20.00\n")

    with pytest.raises(TableMappingError):
        build_inline_query_request(
            str(csv_path),
            "SELECT * FROM orders",
            ["orders=orders.csv"],
            base_dir=tmp_path,
        )


def test_build_saved_sql_query_request_uses_explicit_table_mappings(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")

    request = build_saved_sql_query_request(
        "SELECT COUNT(*) FROM orders",
        ["orders=orders.csv"],
        base_dir=tmp_path,
    )

    assert request.sql == "SELECT COUNT(*) FROM orders"
    assert request.catalog_fallback is True
    assert len(request.table_sources) == 1
    assert request.table_sources[0].name == "orders"
    assert request.table_sources[0].path == orders


def test_execute_query_request_lazily_loads_missing_catalog_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".csvql.yml").write_text(
        "version: 1\ntables:\n  customers:\n    path: customers.csv\n",
        encoding="utf-8",
    )
    orders = tmp_path / "orders.csv"
    customers = tmp_path / "customers.csv"
    _write_csv(orders, "order_id,customer_id,total_amount\nORD-001,CUST-001,20.00\n")
    _write_csv(customers, "customer_id,email\nCUST-001,alex@example.com\n")
    request = build_inline_query_request(
        (
            "SELECT c.email, SUM(o.total_amount) AS total_amount "
            "FROM orders o JOIN customers c USING (customer_id) "
            "GROUP BY c.email"
        ),
        None,
        [f"orders={orders}"],
        base_dir=tmp_path,
    )

    with CSVQLEngine() as engine:
        result = execute_query_request(engine, request)

    assert result.as_records() == [{"email": "alex@example.com", "total_amount": 20.0}]


def test_execute_query_request_preserves_request_base_dir_for_lazy_catalog_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    outside = tmp_path / "outside"
    project_root.mkdir()
    outside.mkdir()
    monkeypatch.chdir(outside)
    (project_root / ".csvql.yml").write_text(
        "version: 1\ntables:\n  customers:\n    path: customers.csv\n",
        encoding="utf-8",
    )
    orders = project_root / "orders.csv"
    customers = project_root / "customers.csv"
    _write_csv(orders, "order_id,customer_id,total_amount\nORD-001,CUST-001,20.00\n")
    _write_csv(customers, "customer_id,email\nCUST-001,alex@example.com\n")
    request = build_inline_query_request(
        (
            "SELECT c.email, SUM(o.total_amount) AS total_amount "
            "FROM orders o JOIN customers c USING (customer_id) "
            "GROUP BY c.email"
        ),
        None,
        ["orders=orders.csv"],
        base_dir=project_root,
    )

    with CSVQLEngine() as engine:
        result = execute_query_request(engine, request)

    assert result.as_records() == [{"email": "alex@example.com", "total_amount": 20.0}]
