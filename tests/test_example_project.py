import json
import runpy
import shutil
from hashlib import sha256
from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql.cli import app

runner = CliRunner()
EXAMPLE_ROOT = Path(__file__).resolve().parents[1] / "examples" / "saas_revenue"


def _copy_example_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "saas_revenue"
    shutil.copytree(EXAMPLE_ROOT, project_root)
    return project_root


def _hash_csv_outputs(project_root: Path) -> dict[str, str]:
    return {
        csv_path.name: sha256(csv_path.read_bytes()).hexdigest()
        for csv_path in sorted(project_root.glob("data/*.csv"))
    }


def test_saas_revenue_regeneration_rewrites_the_same_csv_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _copy_example_project(tmp_path)
    before_hashes = _hash_csv_outputs(project_root)

    monkeypatch.chdir(project_root)
    runpy.run_path(str(project_root / "scripts" / "regenerate_data.py"), run_name="__main__")

    after_hashes = _hash_csv_outputs(project_root)

    assert after_hashes == before_hashes


def test_saas_revenue_walkthrough_commands_succeed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _copy_example_project(tmp_path)
    monkeypatch.chdir(project_root)

    inspect_result = runner.invoke(
        app,
        ["inspect", "data/revenue_movements.csv", "--output", "json"],
    )
    assert inspect_result.exit_code == 0, inspect_result.output
    inspect_payload = json.loads(inspect_result.output)
    assert inspect_payload["row_count"] == {
        "mode": "not_counted",
        "value": None,
        "exact": False,
    }
    assert inspect_payload["columns"][0]["name"] == "movement_id"

    profile_result = runner.invoke(
        app,
        ["profile", "revenue_movements", "--output", "json"],
    )
    assert profile_result.exit_code == 0, profile_result.output
    profile_payload = json.loads(profile_result.output)
    assert profile_payload["row_count"] == 11
    assert profile_payload["duplicate_row_count"] == 0

    check_result = runner.invoke(app, ["check", "--output", "json"])
    assert check_result.exit_code == 0, check_result.output
    check_payload = json.loads(check_result.output)
    assert check_payload["status"] == "passed"
    assert check_payload["check_count"] == 12
    assert sorted(check["name"] for check in check_payload["checks"]) == [
        "current_mrr_nonnegative",
        "customer_id_required",
        "customer_id_unique",
        "movement_customer_exists",
        "movement_id_required",
        "movement_id_unique",
        "movement_rows_present",
        "movement_subscription_exists",
        "movement_type_known",
        "subscription_customer_exists",
        "subscription_id_required",
        "subscription_id_unique",
    ]

    run_result = runner.invoke(
        app,
        ["run", "queries/revenue_health.sql", "--output", "json"],
    )
    assert run_result.exit_code == 0, run_result.output
    run_payload = json.loads(run_result.output)
    assert run_payload["row_count"] == 4
    assert run_payload["rows"] == [
        {
            "report_month": "2025-01-01",
            "starting_mrr": 0.0,
            "new_mrr": 300.0,
            "expansion_mrr": 0.0,
            "contraction_mrr": 0.0,
            "churn_mrr": 0.0,
            "reactivation_mrr": 0.0,
            "net_mrr_change": 300.0,
            "ending_mrr": 300.0,
            "ending_arr": 3600.0,
            "net_revenue_retention_pct": None,
        },
        {
            "report_month": "2025-02-01",
            "starting_mrr": 300.0,
            "new_mrr": 300.0,
            "expansion_mrr": 50.0,
            "contraction_mrr": 0.0,
            "churn_mrr": 0.0,
            "reactivation_mrr": 0.0,
            "net_mrr_change": 350.0,
            "ending_mrr": 650.0,
            "ending_arr": 7800.0,
            "net_revenue_retention_pct": 116.7,
        },
        {
            "report_month": "2025-03-01",
            "starting_mrr": 650.0,
            "new_mrr": 400.0,
            "expansion_mrr": 0.0,
            "contraction_mrr": 25.0,
            "churn_mrr": 100.0,
            "reactivation_mrr": 0.0,
            "net_mrr_change": 275.0,
            "ending_mrr": 925.0,
            "ending_arr": 11100.0,
            "net_revenue_retention_pct": 80.8,
        },
        {
            "report_month": "2025-04-01",
            "starting_mrr": 925.0,
            "new_mrr": 0.0,
            "expansion_mrr": 75.0,
            "contraction_mrr": 0.0,
            "churn_mrr": 150.0,
            "reactivation_mrr": 100.0,
            "net_mrr_change": 25.0,
            "ending_mrr": 950.0,
            "ending_arr": 11400.0,
            "net_revenue_retention_pct": 102.7,
        },
    ]

    export_json_args = [
        "export",
        "queries/revenue_health.sql",
        "--format",
        "json",
        "--out",
        "output/revenue-health.json",
        "--force",
    ]
    export_json_result = runner.invoke(app, export_json_args)
    assert export_json_result.exit_code == 0, export_json_result.output
    repeat_export_json_result = runner.invoke(app, export_json_args)
    assert repeat_export_json_result.exit_code == 0, repeat_export_json_result.output
    export_json_payload = json.loads(
        (project_root / "output" / "revenue-health.json").read_text(encoding="utf-8")
    )
    assert export_json_payload["rows"] == run_payload["rows"]

    export_markdown_args = [
        "export",
        "queries/revenue_health.sql",
        "--format",
        "markdown",
        "--out",
        "output/revenue-health.md",
        "--force",
    ]
    export_markdown_result = runner.invoke(app, export_markdown_args)
    assert export_markdown_result.exit_code == 0, export_markdown_result.output
    repeat_export_markdown_result = runner.invoke(app, export_markdown_args)
    assert repeat_export_markdown_result.exit_code == 0, repeat_export_markdown_result.output
    export_markdown_text = (project_root / "output" / "revenue-health.md").read_text(
        encoding="utf-8"
    )
    assert "| report_month | starting_mrr |" in export_markdown_text
    assert (
        "| 2025-04-01 | 925.0 | 0.0 | 75.0 | 0.0 | 150.0 | 100.0 | 25.0 | 950.0 | 11400.0 | 102.7 |"
        in export_markdown_text
    )
