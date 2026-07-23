from pathlib import Path

import pytest

from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVQLError, QueryExecutionError, TableMappingError
from csvql.models import TableSource
from csvql.operation import OperationContext, OperationToken
from csvql.query_workflow import (
    build_inline_query_request,
    build_saved_sql_query_request,
    execute_query_request,
    execute_query_request_stream,
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
            operation=OperationContext(token=OperationToken()),
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
        operation=OperationContext(token=OperationToken()),
    )

    assert request.sql == "SELECT COUNT(*) FROM orders"
    assert len(request.required_sources) == 1
    assert request.required_sources[0].spec.alias == "orders"
    assert request.required_sources[0].canonical_locator == str(orders)
    assert request.fallback_sources == ()


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
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        (
            "SELECT c.email, SUM(o.total_amount) AS total_amount "
            "FROM orders o JOIN customers c USING (customer_id) "
            "GROUP BY c.email"
        ),
        None,
        [f"orders={orders}"],
        base_dir=tmp_path,
        operation=operation,
    )

    with CSVQLEngine(operation=operation) as engine:
        result = execute_query_request(engine, request, operation=operation)

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
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        (
            "SELECT c.email, SUM(o.total_amount) AS total_amount "
            "FROM orders o JOIN customers c USING (customer_id) "
            "GROUP BY c.email"
        ),
        None,
        ["orders=orders.csv"],
        base_dir=project_root,
        operation=operation,
    )

    with CSVQLEngine(operation=operation) as engine:
        result = execute_query_request(engine, request, operation=operation)

    assert result.as_records() == [{"email": "alex@example.com", "total_amount": 20.0}]


def test_engine_query_error_keeps_bindings_live_for_lazy_fallback_retry(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    customers = tmp_path / "customers.csv"
    _write_csv(orders, "order_id,customer_id\nORD-001,CUST-001\n")
    _write_csv(customers, "customer_id,email\nCUST-001,alex@example.com\n")

    with CSVQLEngine() as engine:
        engine.register_tables([TableSource(name="orders", path=orders)])
        with pytest.raises(QueryExecutionError, match="customers"):
            engine.query("SELECT * FROM orders JOIN customers USING (customer_id)")
        engine.register_tables([TableSource(name="customers", path=customers)])
        result = engine.query("SELECT email FROM orders JOIN customers USING (customer_id)")

    assert result.rows == (("alex@example.com",),)


def test_execute_query_request_rejects_mismatched_operation_context(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    build_operation = OperationContext(token=OperationToken())
    run_operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "SELECT * FROM orders",
        None,
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=build_operation,
    )

    with (
        CSVQLEngine(operation=run_operation) as engine,
        pytest.raises(
            CSVQLError,
            match="one shared operation context",
        ),
    ):
        execute_query_request(engine, request, operation=build_operation)


def test_execute_query_request_stream_only_applies_fallback_while_starting(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    customers = tmp_path / "customers.csv"
    _write_csv(orders, "order_id,customer_id\nORD-001,CUST-001\n")
    _write_csv(customers, "customer_id,email\nCUST-001,alex@example.com\n")
    (tmp_path / ".csvql.yml").write_text(
        "version: 1\ntables:\n  customers:\n    path: customers.csv\n",
        encoding="utf-8",
    )
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        (
            "SELECT c.email "
            "FROM orders o JOIN customers c USING (customer_id) "
            "ORDER BY c.email"
        ),
        None,
        [f"orders={orders}"],
        base_dir=tmp_path,
        operation=operation,
    )

    with CSVQLEngine(operation=operation) as engine:
        stream = execute_query_request_stream(engine, request, operation=operation)
        first = stream.fetch_rows(1)
        second = stream.fetch_rows(1)

    assert first.rows == (("alex@example.com",),)
    assert first.exhausted is False
    assert second.rows == ()
    assert second.exhausted is True


def test_execute_query_request_does_not_retry_after_stream_fetch_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orders = tmp_path / "orders.csv"
    customers = tmp_path / "customers.csv"
    _write_csv(orders, "order_id,customer_id\nORD-001,CUST-001\n")
    _write_csv(customers, "customer_id,email\nCUST-001,alex@example.com\n")
    (tmp_path / ".csvql.yml").write_text(
        "version: 1\ntables:\n  customers:\n    path: customers.csv\n",
        encoding="utf-8",
    )
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "SELECT c.email FROM orders o JOIN customers c USING (customer_id)",
        None,
        [f"orders={orders}", f"customers={customers}"],
        base_dir=tmp_path,
        operation=operation,
    )

    real_stream = CSVQLEngine.stream
    calls = 0

    def failing_stream(self: CSVQLEngine, sql: str, params=None):
        nonlocal calls
        calls += 1
        stream = real_stream(self, sql, params)

        def fail_once(max_rows: int):
            raise QueryExecutionError(
                "DuckDB query failed: fetch broke",
                suggestion="Check table names, column names, and SQL syntax.",
            )

        real_close = stream.close

        def close_with_failure() -> None:
            real_close()
            raise RuntimeError("close broke")

        object.__setattr__(stream, "fetch_rows", fail_once)
        object.__setattr__(stream, "close", close_with_failure)
        return stream

    monkeypatch.setattr(CSVQLEngine, "stream", failing_stream)

    with CSVQLEngine(operation=operation) as engine, pytest.raises(
        QueryExecutionError,
        match="fetch broke",
    ) as captured:
        execute_query_request(engine, request, operation=operation)

    assert calls == 1
    notes = "\n".join(getattr(captured.value, "__notes__", ()))
    assert "cursor could not be closed" in notes
