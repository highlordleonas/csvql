import json
from pathlib import Path

from typer.testing import CliRunner

from csvql.cli import app

runner = CliRunner()


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


def test_query_requires_table_mapping_for_inline_sql() -> None:
    result = runner.invoke(app, ["query", "SELECT 1"])

    assert result.exit_code == 6
    assert "At least one --table mapping is required" in result.output
