from pathlib import Path

import duckdb
import pytest

from csvql.doctor import DoctorProbeResult, DoctorRunResult, _run_table_readiness_probes
from csvql.project_config import ProjectConfig, ProjectContext, ProjectTable


def test_doctor_run_result_derives_warning_counts_and_json_shape() -> None:
    result = DoctorRunResult(
        project_root=None,
        config_path=None,
        probes=(
            DoctorProbeResult(
                name="project_discovery",
                scope="project",
                status="warning",
                message="No .csvql.yml project catalog found.",
            ),
        ),
    )

    assert result.status == "warning"
    assert result.probe_count == 1
    assert result.passed_count == 0
    assert result.warning_count == 1
    assert result.failed_count == 0
    assert result.as_dict() == {
        "status": "warning",
        "probe_count": 1,
        "passed_count": 0,
        "warning_count": 1,
        "failed_count": 0,
        "project": {
            "config_path": None,
            "project_root": None,
        },
        "probes": [
            {
                "name": "project_discovery",
                "scope": "project",
                "status": "warning",
                "message": "No .csvql.yml project catalog found.",
            }
        ],
    }


def test_table_readiness_propagates_internal_duckdb_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    context = ProjectContext(
        project_root=tmp_path,
        config_path=tmp_path / ".csvql.yml",
        config=ProjectConfig(
            version=1,
            tables=(ProjectTable(name="orders", path="orders.csv"),),
        ),
    )

    class FakeRelation:
        columns = ("order_id", "status")

        def create_view(self, name: str, *, replace: bool) -> None:
            return None

    class FakeCursor:
        def fetchall(self) -> list[object]:
            return []

    class FakeConnection:
        def read_csv(self, path: str, *, auto_detect: bool, header: bool) -> FakeRelation:
            return FakeRelation()

        def execute(self, query: str) -> FakeCursor:
            raise duckdb.InternalException("simulated internal failure")

        def close(self) -> None:
            return None

    monkeypatch.setattr(duckdb, "connect", lambda database: FakeConnection())

    with pytest.raises(duckdb.InternalException, match="simulated internal failure"):
        _run_table_readiness_probes(context, context.config.tables)
