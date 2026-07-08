import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql.cli import app

runner = CliRunner()


def test_inspect_outputs_json_without_counting_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["inspect", str(csv_path), "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == {
        "mode": "not_counted",
        "value": None,
        "exact": False,
    }
    assert payload["columns"][0]["name"] == "order_id"


def test_inspect_json_contract_includes_source_dialect_columns_row_count_and_warnings(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["inspect", str(csv_path), "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {"source", "dialect", "columns", "row_count", "warnings"}
    assert payload["dialect"] == {
        "delimiter": ",",
        "quote": '"',
        "escape": None,
        "header": True,
        "encoding": "utf-8",
    }
    assert payload["columns"][0] == {
        "name": "order_id",
        "duckdb_type": "VARCHAR",
    }
    assert payload["row_count"] == {
        "mode": "not_counted",
        "value": None,
        "exact": False,
    }
    assert payload["warnings"] == []
    assert payload["source"]["display_path"] == str(csv_path)
    assert payload["source"]["resolved_path"] == str(csv_path.resolve())
    assert payload["source"]["size_bytes"] == csv_path.stat().st_size
    assert payload["source"]["fingerprint"]["version"] == 1


def test_inspect_exact_outputs_exact_row_count(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["inspect", str(csv_path), "--exact", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == {
        "mode": "exact",
        "value": 2,
        "exact": True,
    }


def test_sample_outputs_json_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["sample", str(csv_path), "--limit", "1", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["limit"] == 1
    assert payload["rows"] == [{"order_id": "ORD-1", "status": "paid"}]


def test_sample_outputs_table_by_default(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")

    result = runner.invoke(app, ["sample", str(csv_path)])

    assert result.exit_code == 0, result.output
    assert "ORD-1" in result.output
    assert "paid" in result.output


def test_sample_rejects_non_positive_limit(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")

    result = runner.invoke(app, ["sample", str(csv_path), "--limit", "0"], terminal_width=120)

    assert result.exit_code == 2
    assert "--limit" in result.output


def test_inspect_missing_file_uses_existing_file_error() -> None:
    result = runner.invoke(app, ["inspect", "missing.csv"])

    assert result.exit_code == 4
    assert "CSV file not found" in result.output


def test_inspect_catalog_alias_outputs_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "data" / "orders.csv"
    orders.parent.mkdir(parents=True)
    orders.write_text("order_id,total_amount\nORD-001,20.00\n", encoding="utf-8")
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(app, ["inspect", "orders", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"]["display_path"] == "orders"
    assert payload["columns"][0]["name"] == "order_id"


def test_inspect_catalog_alias_matches_case_insensitively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "data" / "orders.csv"
    orders.parent.mkdir(parents=True)
    orders.write_text("order_id,total_amount\nORD-001,20.00\n", encoding="utf-8")
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["add", "Orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(app, ["inspect", "orders", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"]["display_path"] == "orders"
    assert payload["columns"][0]["name"] == "order_id"


def test_sample_catalog_alias_outputs_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "data" / "orders.csv"
    orders.parent.mkdir(parents=True)
    orders.write_text("order_id,total_amount\nORD-001,20.00\n", encoding="utf-8")
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(app, ["sample", "orders", "--limit", "1", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"]["display_path"] == "orders"
    assert payload["rows"] == [{"order_id": "ORD-001", "total_amount": 20.0}]


def test_sample_catalog_alias_matches_case_insensitively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "data" / "orders.csv"
    orders.parent.mkdir(parents=True)
    orders.write_text("order_id,total_amount\nORD-001,20.00\n", encoding="utf-8")
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["add", "Orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(app, ["sample", "orders", "--limit", "1", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"]["display_path"] == "orders"
    assert payload["rows"] == [{"order_id": "ORD-001", "total_amount": 20.0}]
