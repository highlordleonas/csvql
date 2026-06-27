import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql.cli import app

runner = CliRunner()


def _write_csv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    return tmp_path


def test_query_multiple_tables_as_json(tmp_path: Path) -> None:
    customers = tmp_path / "customers.csv"
    customers.write_text(
        "customer_id,email\nCUST-001,alex@example.com\nCUST-002,blair@example.com\n",
        encoding="utf-8",
    )
    orders = tmp_path / "orders.csv"
    orders.write_text(
        "order_id,customer_id,total_amount\nORD-001,CUST-001,120.50\nORD-002,CUST-001,80.00\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            f"customers={customers}",
            "--table",
            f"orders={orders}",
            "--output",
            "json",
            (
                "SELECT c.email, SUM(o.total_amount) AS revenue "
                "FROM customers c JOIN orders o USING (customer_id) "
                "GROUP BY c.email"
            ),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["columns"] == ["email", "revenue"]
    assert payload["row_count"] == 1
    assert payload["rows"][0]["email"] == "alex@example.com"
    assert payload["rows"][0]["revenue"] == 200.5


def test_query_inline_sql_uses_catalog_tables_from_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _create_catalog(tmp_path, monkeypatch)
    orders = project_root / "data" / "orders.csv"
    _write_csv(
        orders,
        "order_id,status,total_amount\nORD-001,paid,120.50\nORD-002,pending,80.00\n",
    )
    result = runner.invoke(
        app,
        [
            "add",
            "orders",
            "data/orders.csv",
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "query",
            "--output",
            "json",
            "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status ORDER BY status",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["columns"] == ["status", "order_count"]
    assert payload["row_count"] == 2
    assert payload["rows"] == [
        {"status": "paid", "order_count": 1},
        {"status": "pending", "order_count": 1},
    ]


def test_query_inline_sql_uses_catalog_tables_from_subdirectory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _create_catalog(tmp_path, monkeypatch)
    nested_dir = project_root / "nested" / "child"
    nested_dir.mkdir(parents=True)
    orders = project_root / "data" / "orders.csv"
    _write_csv(
        orders,
        "order_id,status,total_amount\nORD-001,paid,120.50\nORD-002,pending,80.00\n",
    )
    result = runner.invoke(app, ["add", "orders", "data/orders.csv"])
    assert result.exit_code == 0, result.output

    monkeypatch.chdir(nested_dir)
    result = runner.invoke(
        app,
        [
            "query",
            "--output",
            "json",
            "SELECT COUNT(*) AS order_count FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == 1
    assert payload["rows"][0]["order_count"] == 2


def test_query_inline_sql_explicit_table_overrides_catalog_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _create_catalog(tmp_path, monkeypatch)
    catalog_orders = project_root / "data" / "catalog_orders.csv"
    explicit_orders = project_root / "data" / "explicit_orders.csv"
    _write_csv(
        catalog_orders,
        "order_id,total_amount\nORD-001,10.00\n",
    )
    _write_csv(
        explicit_orders,
        "order_id,total_amount\nORD-001,20.00\n",
    )
    result = runner.invoke(app, ["add", "orders", "data/catalog_orders.csv"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            "orders=data/explicit_orders.csv",
            "--output",
            "json",
            "SELECT SUM(total_amount) AS total_amount FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == 1
    assert payload["rows"][0]["total_amount"] == 20.0


def test_query_inline_sql_explicit_table_ignores_missing_catalog_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / ".csvql.yml"
    config_path.write_text(
        "version: 1\ntables:\n  orders:\n    path: missing.csv\n",
        encoding="utf-8",
    )
    explicit_orders = tmp_path / "good.csv"
    _write_csv(
        explicit_orders,
        "order_id,total_amount\nORD-001,20.00\n",
    )

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            f"orders={explicit_orders}",
            "--output",
            "json",
            "SELECT SUM(total_amount) AS total_amount FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == 1
    assert payload["rows"][0]["total_amount"] == 20.0


def test_query_inline_sql_explicit_table_succeeds_without_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "orders.csv"
    _write_csv(
        orders,
        "order_id,status,total_amount\nORD-001,paid,120.50\nORD-002,pending,80.00\n",
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
    assert payload["row_count"] == 1
    assert payload["rows"][0]["order_count"] == 2


def test_query_inline_sql_without_catalog_returns_project_config_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["query", "SELECT 1"], catch_exceptions=False)

    assert result.exit_code == 8
    assert "No .csvql.yml project catalog found" in result.output
    assert "Run project init/add or pass --table mappings explicitly." in result.output


def test_query_single_file_shortcut_outputs_table(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text(
        "order_id,status,total_amount\nORD-001,paid,120.50\nORD-002,pending,80.00\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "query",
            str(orders),
            "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status ORDER BY status",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "paid" in result.output
    assert "pending" in result.output
    assert "2 row(s)" in result.output


def test_query_single_file_shortcut_rejects_table_mappings(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    other = tmp_path / "other.csv"
    orders.write_text(
        "order_id,status,total_amount\nORD-001,paid,120.50\nORD-002,pending,80.00\n",
        encoding="utf-8",
    )
    other.write_text("id,value\n1,2\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "query",
            str(orders),
            "SELECT status FROM orders",
            "--table",
            f"something={other}",
        ],
    )

    assert result.exit_code == 6
    assert "Single-file shortcut mode cannot be combined with --table mappings" in result.output
