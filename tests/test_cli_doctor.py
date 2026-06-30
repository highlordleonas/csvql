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


def test_doctor_without_catalog_returns_warning_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "warning"
    assert payload["project"] == {"config_path": None, "project_root": None}
    assert payload["warning_count"] == 1
    assert payload["failed_count"] == 0
    assert payload["probes"][0]["name"] == "project_discovery"
    assert payload["probes"][0]["status"] == "warning"


def test_doctor_invalid_yaml_returns_failed_json_and_exit_12(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text("version: [\n", encoding="utf-8")

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 12, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    assert payload["probes"][0]["name"] == "project_discovery"
    assert payload["probes"][1]["name"] == "config_load"
    assert payload["probes"][1]["status"] == "failed"
    assert "Invalid YAML" in payload["probes"][1]["message"]


def test_doctor_empty_project_catalog_returns_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables: {}
        """,
    )

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "warning"
    assert payload["probes"][-1]["name"] == "catalog_tables_present"
    assert payload["probes"][-1]["status"] == "warning"


def test_doctor_valid_project_returns_passed_json(
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
          orders:
            path: data/orders.csv
        """,
    )

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "passed"
    assert payload["failed_count"] == 0
    assert payload["warning_count"] == 0
    assert any(
        probe["name"] == "table_readiness"
        and probe["status"] == "passed"
        and probe["table"] == "orders"
        for probe in payload["probes"]
    )


def test_doctor_header_only_csv_still_passes_table_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "order_id,status\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
        """,
    )

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "passed"
    assert any(
        probe["name"] == "table_readiness"
        and probe["status"] == "passed"
        and probe["table"] == "orders"
        for probe in payload["probes"]
    )


def test_doctor_missing_csv_returns_failed_probe_and_exit_12(
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

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 12, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    assert any(
        probe["name"] == "table_readiness"
        and probe["status"] == "failed"
        and probe["table"] == "orders"
        for probe in payload["probes"]
    )
