import json
from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from csvql.cli import app
from csvql.project_config import CONFIG_FILENAME

runner = CliRunner()


def _write_project_config(tmp_path: Path, text: str) -> None:
    (tmp_path / CONFIG_FILENAME).write_text(dedent(text).lstrip(), encoding="utf-8")


def test_check_outputs_json_for_passing_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
            checks:
              - name: order_id_required
                type: not_null
                column: order_id
        """,
    )

    result = runner.invoke(app, ["check", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "passed"
    assert payload["check_count"] == 1
    assert payload["checks"][0]["status"] == "passed"
    assert payload["checks"][0]["failed_count"] == 0


def test_check_json_contract_omits_failures_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
            checks:
              - name: order_id_required
                type: not_null
                column: order_id
        """,
    )

    result = runner.invoke(app, ["check", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {
        "status",
        "check_count",
        "passed_count",
        "failed_count",
        "checks",
        "warnings",
    }
    assert payload["status"] == "passed"
    assert payload["check_count"] == 1
    assert payload["passed_count"] == 1
    assert payload["failed_count"] == 0
    assert payload["warnings"] == []
    assert "failures" not in payload["checks"][0]


def test_check_outputs_table_and_exits_11_for_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "order_id,status\nORD-1,paid\n,unknown\nORD-3,paid\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
            checks:
              - name: order_id_required
                type: not_null
                column: order_id
        """,
    )

    result = runner.invoke(app, ["check"])

    assert result.exit_code == 11, result.output
    assert "Status: failed" in result.output
    assert result.output.count("Status: failed") == 1
    assert "order_id_required" in result.output
    assert "Error: Configured data-quality checks failed." not in result.output


def test_check_table_filter_matches_case_insensitively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "order_id,status\nORD-1,paid\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          Orders:
            path: data/orders.csv
            checks:
              - name: order_id_required
                type: not_null
                column: order_id
        """,
    )

    result = runner.invoke(app, ["check", "orders", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["check_count"] == 1
    assert payload["checks"][0]["table"] == "Orders"
    assert payload["checks"][0]["status"] == "passed"


def test_check_show_failures_honors_failure_limit_in_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "order_id,status\nORD-1,paid\n,unknown\n,paid\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
            checks:
              - name: order_id_required
                type: not_null
                column: order_id
        """,
    )

    result = runner.invoke(
        app,
        ["check", "--output", "json", "--show-failures", "--failure-limit", "1"],
    )

    assert result.exit_code == 11, result.output
    payload = json.loads(result.output)
    assert payload["checks"][0]["failed_count"] == 2
    assert len(payload["checks"][0]["failures"]) == 1
    assert payload["checks"][0]["failures"][0]["row_number"] == 2


def test_check_json_contract_includes_failure_samples_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "order_id,status\nORD-1,paid\n,unknown\n,\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
            checks:
              - name: order_id_required
                type: not_null
                column: order_id
        """,
    )

    result = runner.invoke(
        app,
        ["check", "--output", "json", "--show-failures", "--failure-limit", "1"],
    )

    assert result.exit_code == 11, result.output
    payload = json.loads(result.output)
    assert set(payload) == {
        "status",
        "check_count",
        "passed_count",
        "failed_count",
        "checks",
        "warnings",
    }
    assert payload["status"] == "failed"
    assert payload["check_count"] == 1
    assert payload["passed_count"] == 0
    assert payload["failed_count"] == 1
    assert payload["warnings"] == []
    assert payload["checks"][0]["failed_count"] == 2
    assert payload["checks"][0]["failures"][0]["row_number"] == 2
    assert payload["checks"][0]["failures"][0]["row"] == {
        "order_id": None,
        "status": "unknown",
    }


def test_check_without_configured_checks_returns_zero_and_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
        """,
    )

    result = runner.invoke(app, ["check"])

    assert result.exit_code == 0, result.output
    assert "Status: passed" in result.output
    assert "Warnings:" in result.output
    assert "No data quality checks configured." in result.output


def test_check_missing_catalog_uses_project_config_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check"])

    assert result.exit_code == 8
    assert "No .csvql.yml project catalog found." in result.output


def test_check_missing_csv_uses_file_missing_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: missing.csv
            checks:
              - name: order_id_required
                type: not_null
                column: order_id
        """,
    )

    result = runner.invoke(app, ["check"])

    assert result.exit_code == 4
    assert "CSV file not found" in result.output


def test_check_rejects_invalid_failure_limit_via_typer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["check", "--failure-limit", "0"], terminal_width=120)

    assert result.exit_code == 2
    assert "Invalid value" in result.output
    assert "range x>=1" in result.output
