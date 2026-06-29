import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql.cli import app

runner = CliRunner()


def test_profile_outputs_json_for_direct_path(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-1,paid\nORD-2,\nORD-2,\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["profile", str(csv_path), "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"]["display_path"] == str(csv_path)
    assert payload["row_count"] == 3
    assert payload["column_count"] == 2
    assert payload["duplicate_row_count"] == 1
    assert payload["columns"][1]["name"] == "status"
    assert payload["columns"][1]["null_percentage"] == 66.667


def test_profile_outputs_table_by_default(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")

    result = runner.invoke(app, ["profile", str(csv_path)])

    assert result.exit_code == 0, result.output
    assert "Rows: 1" in result.output
    assert "Duplicate rows: 0" in result.output
    assert "order_id" in result.output


def test_profile_catalog_alias_outputs_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "data" / "orders.csv"
    orders.parent.mkdir(parents=True)
    orders.write_text("order_id,total_amount\nORD-001,20.00\n", encoding="utf-8")
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(app, ["profile", "orders", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"]["display_path"] == "orders"
    assert payload["row_count"] == 1
    assert payload["columns"][0]["name"] == "order_id"


def test_profile_catalog_alias_matches_case_insensitively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "data" / "orders.csv"
    orders.parent.mkdir(parents=True)
    orders.write_text("order_id,total_amount\nORD-001,20.00\n", encoding="utf-8")
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["add", "Orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(app, ["profile", "orders", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"]["display_path"] == "orders"
    assert payload["columns"][0]["name"] == "order_id"


def test_profile_missing_file_uses_existing_file_error() -> None:
    result = runner.invoke(app, ["profile", "missing.csv"])

    assert result.exit_code == 4
    assert "CSV file not found" in result.output
