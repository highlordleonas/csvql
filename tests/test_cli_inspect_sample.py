import json
from pathlib import Path

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

    result = runner.invoke(app, ["sample", str(csv_path), "--limit", "0"])

    assert result.exit_code == 2
    assert "--limit" in result.output


def test_inspect_missing_file_uses_existing_file_error() -> None:
    result = runner.invoke(app, ["inspect", "missing.csv"])

    assert result.exit_code == 4
    assert "CSV file not found" in result.output
