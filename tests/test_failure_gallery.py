from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql.api import CSVQLSession
from csvql.cli import app
from csvql.exceptions import ProjectConfigError, QueryExecutionError, SQLFileError
from csvql.quality import CheckRunResult

runner = CliRunner()


def _write_csv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_gallery_project(
    root: Path,
    *,
    rows: str = "ORD-001,paid\nORD-002,pending\n",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "queries").mkdir(parents=True, exist_ok=True)
    _write_csv(root / "data" / "orders.csv", "order_id,status\n" + rows)
    (root / "queries" / "count_orders.sql").write_text(
        "SELECT COUNT(*) AS order_count FROM orders",
        encoding="utf-8",
    )
    (root / ".csvql.yml").write_text(
        (
            "version: 1\n"
            "tables:\n"
            "  orders:\n"
            "    path: data/orders.csv\n"
            "    checks:\n"
            "      - name: order_id_required\n"
            "        type: not_null\n"
            "        column: order_id\n"
        ),
        encoding="utf-8",
    )


def test_gallery_direct_missing_csv_path_returns_exit_4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["query", "missing.csv", "SELECT 1"])

    assert result.exit_code == 4
    assert "Error: CSV file not found: missing.csv" in result.output
    assert (
        "Suggestion: Check the path or run from the directory that contains the CSV file."
        in result.output
    )


def test_gallery_project_catalog_missing_csv_path_returns_exit_4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".csvql.yml").write_text(
        ("version: 1\ntables:\n  orders:\n    path: data/missing.csv\n"),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["query", "SELECT COUNT(*) FROM orders"])

    assert result.exit_code == 4
    assert "CSV file not found for project catalog table 'orders': data/missing.csv" in (
        result.output
    )
    assert "Update .csvql.yml, run csvql add orders <path> --replace" in result.output


@pytest.mark.parametrize(
    ("mapping", "expected_message", "expected_suggestion"),
    [
        (
            "orders",
            "Invalid table mapping 'orders'.",
            "Use --table name=path, for example --table orders=data/orders.csv.",
        ),
        (
            "orders=",
            "Missing CSV path for table alias 'orders'.",
            "Use --table name=path, for example --table orders=data/orders.csv.",
        ),
        (
            "1orders=orders.csv",
            "Invalid table alias '1orders'.",
            "Use letters, numbers, and underscores; start with a letter or underscore.",
        ),
    ],
)
def test_gallery_bad_table_mapping_cli_errors_use_exit_6(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mapping: str,
    expected_message: str,
    expected_suggestion: str,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["query", "--table", mapping, "SELECT 1"])

    assert result.exit_code == 6
    assert f"Error: {expected_message}" in result.output
    if mapping == "1orders=orders.csv":
        assert "Suggestion: Use letters, numbers, and underscores; start with a letter or " in (
            result.output
        )
        assert "underscore." in result.output
    else:
        assert f"Suggestion: {expected_suggestion}" in result.output


def test_gallery_single_file_shortcut_uses_generated_safe_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_csv(tmp_path / "2026-orders.csv", "order_id\nORD-001\n")

    result = runner.invoke(
        app,
        [
            "query",
            "2026-orders.csv",
            "SELECT COUNT(*) AS row_count FROM table_2026_orders",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [{"row_count": 1}]


def test_gallery_duckdb_query_failure_uses_exit_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_csv(tmp_path / "orders.csv", "order_id\nORD-001\n")

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            "orders=orders.csv",
            "SELECT missing_column FROM orders",
        ],
    )

    assert result.exit_code == 1
    assert "Error: DuckDB query failed:" in result.output
    assert "Suggestion: Check table names, column names, and SQL syntax." in result.output


def test_gallery_missing_project_catalog_uses_exit_8(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["query", "SELECT 1"])

    assert result.exit_code == 8
    assert "Error: No .csvql.yml project catalog found." in result.output
    assert "Suggestion: Run project init/add or pass --table mappings explicitly." in (
        result.output
    )


def test_gallery_invalid_project_catalog_doctor_uses_exit_12(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".csvql.yml").write_text("version: [\n", encoding="utf-8")

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 12, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    assert payload["probes"][1]["name"] == "config_load"
    assert payload["probes"][1]["status"] == "failed"
    assert "Invalid YAML" in payload["probes"][1]["message"]


def test_gallery_saved_sql_file_failures_use_exit_9(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "empty.sql").write_text("   \n", encoding="utf-8")

    missing_run = runner.invoke(app, ["run", "queries/missing.sql"])
    empty_run = runner.invoke(app, ["run", "empty.sql"])
    missing_export = runner.invoke(
        app,
        [
            "export",
            "queries/missing.sql",
            "--format",
            "csv",
            "--out",
            "out.csv",
        ],
    )

    assert missing_run.exit_code == 9
    assert "Error: SQL file not found: queries/missing.sql" in missing_run.output
    assert empty_run.exit_code == 9
    assert "Error: SQL file is empty: empty.sql" in empty_run.output
    assert missing_export.exit_code == 9
    assert "Error: SQL file not found: queries/missing.sql" in missing_export.output


def test_gallery_export_overwrite_protection_uses_exit_10(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "query.sql").write_text("SELECT 1 AS one", encoding="utf-8")
    (tmp_path / "out.csv").write_text("existing", encoding="utf-8")

    result = runner.invoke(
        app,
        ["export", "query.sql", "--format", "csv", "--out", "out.csv"],
    )

    assert result.exit_code == 10
    assert "Error: Export output already exists:" in result.output
    assert "Suggestion: Pass --force to overwrite it or choose a different output path." in (
        result.output
    )
    assert (tmp_path / "out.csv").read_text(encoding="utf-8") == "existing"


def test_gallery_data_quality_failure_uses_exit_11_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_gallery_project(tmp_path, rows="ORD-001,paid\n,pending\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["check", "--output", "json", "--show-failures", "--failure-limit", "1"],
    )

    assert result.exit_code == 11, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    assert payload["failed_count"] == 1
    assert payload["checks"][0]["name"] == "order_id_required"
    assert payload["checks"][0]["failures"][0]["row_number"] == 2


def test_gallery_doctor_warning_and_failure_statuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty_project = tmp_path / "empty"
    empty_project.mkdir()
    monkeypatch.chdir(empty_project)

    warning_result = runner.invoke(app, ["doctor", "--output", "json"])

    assert warning_result.exit_code == 0, warning_result.output
    warning_payload = json.loads(warning_result.output)
    assert warning_payload["status"] == "warning"
    assert warning_payload["probes"][0]["name"] == "project_discovery"
    assert warning_payload["probes"][0]["status"] == "warning"

    broken_project = tmp_path / "broken"
    broken_project.mkdir()
    (broken_project / ".csvql.yml").write_text(
        ("version: 1\ntables:\n  orders:\n    path: data/missing.csv\n"),
        encoding="utf-8",
    )
    monkeypatch.chdir(broken_project)

    failure_result = runner.invoke(app, ["doctor", "--output", "json"])

    assert failure_result.exit_code == 12, failure_result.output
    failure_payload = json.loads(failure_result.output)
    assert failure_payload["status"] == "failed"
    assert any(
        probe["name"] == "table_readiness"
        and probe["status"] == "failed"
        and probe["table"] == "orders"
        for probe in failure_payload["probes"]
    )


def test_gallery_python_api_propagates_errors_but_check_failures_return_result(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_gallery_project(project_root, rows="ORD-001,paid\n,pending\n")

    with pytest.raises(ProjectConfigError):
        CSVQLSession.from_config(tmp_path / "missing-project")

    session = CSVQLSession.from_config(project_root)

    with pytest.raises(QueryExecutionError):
        session.query("SELECT missing_column FROM orders")

    with pytest.raises(SQLFileError):
        session.run_file("queries/missing.sql")

    result = session.check(show_failures=True, failure_limit=1)

    assert isinstance(result, CheckRunResult)
    assert result.status == "failed"
    assert result.failed_count == 1
    assert result.checks[0].name == "order_id_required"
    assert result.checks[0].failures[0].row_number == 2
