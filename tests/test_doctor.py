from csvql.doctor import DoctorProbeResult, DoctorRunResult


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
