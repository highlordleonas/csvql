import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql.cli import app

runner = CliRunner()


def _write_csv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output


def test_run_sql_file_uses_catalog_tables(
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
    assert payload["rows"] == [{"order_count": 2}]


def test_run_sql_file_with_explicit_table_works_without_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "orders.csv"
    query = tmp_path / "count_orders.sql"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "count_orders.sql",
            "--table",
            "orders=orders.csv",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [{"order_count": 1}]


def test_run_sql_file_rejects_empty_sql_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    query = tmp_path / "empty.sql"
    query.write_text("   \n", encoding="utf-8")

    result = runner.invoke(app, ["run", "empty.sql"])

    assert result.exit_code == 9
    assert "SQL file is empty" in result.output
