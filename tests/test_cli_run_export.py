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


def test_run_json_contract_matches_query_result_shape(
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
    assert set(payload) == {"columns", "rows", "row_count", "elapsed_ms"}
    assert payload["columns"] == ["order_count"]
    assert payload["rows"] == [{"order_count": 2}]
    assert payload["row_count"] == 1
    assert isinstance(payload["elapsed_ms"], float)


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


def test_export_sql_file_writes_csv(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.csv"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\nORD-002,10.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "queries/count_orders.sql", "--format", "csv", "--out", "result.csv"],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_bytes() == b"order_count\r\n2\r\n"
    assert "Wrote export" in result.output


def test_export_success_output_encodes_terminal_controls_in_output_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "orders.csv"
    query = tmp_path / "count_orders.sql"
    unsafe_output_path = tmp_path / "result\x1b]0;spoof\x07\x7f\x85\x9b31m.csv"
    written_exports: list[tuple[Path, str, bool]] = []
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")

    def fake_resolve_export_path(
        path_value: str,
        *,
        base_dir: Path | None = None,
        force: bool = False,
    ) -> Path:
        assert path_value == "result.csv"
        assert base_dir == tmp_path
        assert force is False
        return unsafe_output_path

    def fake_write_export_file(path: Path, content: str, *, overwrite: bool) -> None:
        written_exports.append((path, content, overwrite))

    monkeypatch.setattr("csvql.cli.resolve_export_path", fake_resolve_export_path)
    monkeypatch.setattr("csvql.cli.write_export_file", fake_write_export_file)

    result = runner.invoke(
        app,
        [
            "export",
            "count_orders.sql",
            "--format",
            "csv",
            "--out",
            "result.csv",
            "--table",
            "orders=orders.csv",
        ],
    )

    assert result.exit_code == 0, result.output
    assert written_exports == [(unsafe_output_path, "order_count\r\n1\r\n", False)]
    assert all(control not in result.output for control in "\x1b\x07\x7f\x85\x9b")
    assert r"result\x1b]0;spoof\x07\x7f\x85\x9b31m.csv" in result.output


def test_export_sql_file_writes_json(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.json"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "queries/count_orders.sql", "--format", "json", "--out", "result.json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["rows"] == [{"order_count": 1}]


def test_export_json_contract_matches_query_result_shape_on_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.json"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "queries/count_orders.sql", "--format", "json", "--out", "result.json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert set(payload) == {"columns", "rows", "row_count", "elapsed_ms"}
    assert payload["columns"] == ["order_count"]
    assert payload["rows"] == [{"order_count": 1}]
    assert payload["row_count"] == 1
    assert isinstance(payload["elapsed_ms"], float)


def test_export_sql_file_writes_markdown(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.md"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        [
            "export",
            "queries/count_orders.sql",
            "--format",
            "markdown",
            "--out",
            "result.md",
        ],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_text(encoding="utf-8") == ("| order_count |\n| --- |\n| 1 |\n")


def test_export_sql_file_writes_text(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.txt"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "queries/count_orders.sql", "--format", "text", "--out", "result.txt"],
    )

    assert result.exit_code == 0, result.output
    content = output_path.read_text(encoding="utf-8")
    assert "order_count" in content
    assert "1 row(s)" in content


def test_export_refuses_overwrite_without_force(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "count_orders.sql"
    output_path = tmp_path / "result.csv"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    output_path.write_text("existing", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "count_orders.sql", "--format", "csv", "--out", "result.csv"],
    )

    assert result.exit_code == 10
    assert "Export output already exists" in result.output
    assert output_path.read_text(encoding="utf-8") == "existing"


def test_export_force_overwrites_existing_file(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "count_orders.sql"
    output_path = tmp_path / "result.csv"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    output_path.write_text("existing", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "count_orders.sql", "--format", "csv", "--out", "result.csv", "--force"],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_bytes() == b"order_count\r\n1\r\n"
