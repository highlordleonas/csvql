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


def test_doctor_unreadable_csv_returns_failed_probe_and_exit_12(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    csv_path = tmp_path / "data" / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          orders:
            path: data/orders.csv
        """,
    )

    try:
        csv_path.chmod(0)
        result = runner.invoke(app, ["doctor", "--output", "json"])
    finally:
        csv_path.chmod(0o600)

    assert result.exit_code == 12, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    assert any(
        probe["name"] == "table_readiness"
        and probe["status"] == "failed"
        and probe["table"] == "orders"
        for probe in payload["probes"]
    )


def test_doctor_invalid_utf8_csv_returns_failed_probe_and_exit_12(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_bytes(b"a,b\n\xff,1\n")
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


def test_doctor_fails_when_configured_check_column_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "actual_order_id\nORD-1\n",
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

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 12, result.output
    payload = json.loads(result.output)
    failing_probe = next(probe for probe in payload["probes"] if probe["scope"] == "check")
    assert failing_probe["name"] == "check_schema_resolution"
    assert failing_probe["status"] == "failed"
    assert failing_probe["table"] == "orders"
    assert failing_probe["check"] == "order_id_required"
    assert failing_probe["column"] == "order_id"


def test_doctor_fails_when_foreign_key_reference_column_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "customers.csv").write_text(
        "customer_key\nC-1\n",
        encoding="utf-8",
    )
    (tmp_path / "data" / "subscriptions.csv").write_text(
        "subscription_id,customer_id\nSUB-1,C-1\n",
        encoding="utf-8",
    )
    _write_project_config(
        tmp_path,
        """
        version: 1
        tables:
          customers:
            path: data/customers.csv
          subscriptions:
            path: data/subscriptions.csv
            checks:
              - name: customer_exists
                type: foreign_key
                column: customer_id
                references:
                  table: customers
                  column: customer_id
        """,
    )

    result = runner.invoke(app, ["doctor", "--output", "json"])

    assert result.exit_code == 12, result.output
    payload = json.loads(result.output)
    failing_probe = next(probe for probe in payload["probes"] if probe["scope"] == "check")
    assert failing_probe["name"] == "check_schema_resolution"
    assert failing_probe["status"] == "failed"
    assert failing_probe["reference_table"] == "customers"
    assert failing_probe["reference_column"] == "customer_id"
