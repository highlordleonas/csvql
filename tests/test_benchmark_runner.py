import json
from pathlib import Path
from subprocess import CompletedProcess

from csvql.benchmark_runner import (
    BenchmarkCaseSpec,
    build_default_case_specs,
    run_case_benchmark,
)


def test_build_default_case_specs_match_v07_matrix() -> None:
    assert [case.case_id for case in build_default_case_specs()] == [
        "query_json",
        "run_json",
        "inspect_json",
        "inspect_exact_json",
        "profile_json",
        "check_json",
    ]


def test_run_case_benchmark_uses_python_module_entrypoint(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path]] = []

    def fake_run(args, *, cwd, capture_output, text, check):
        calls.append((list(args), Path(cwd)))
        stdout = json.dumps(
            {
                "columns": ["row_count"],
                "rows": [{"row_count": 1}],
                "row_count": 1,
                "elapsed_ms": 0.2,
            }
        )
        return CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    ticks = iter([1.0, 1.05, 2.0, 2.06, 3.0, 3.08, 4.0, 4.07, 5.0, 5.09, 6.0, 6.10])

    case = BenchmarkCaseSpec(
        case_id="query_json",
        label="query orders json",
        command=(
            "query",
            "data/orders.csv",
            "--output",
            "json",
            "SELECT COUNT(*) AS row_count FROM orders",
        ),
        expected_json_keys=("columns", "rows", "row_count", "elapsed_ms"),
    )

    result = run_case_benchmark(
        case,
        dataset_root=tmp_path,
        run_command=fake_run,
        clock=lambda: next(ticks),
        warmup_runs=1,
        measured_runs=5,
    )

    assert calls[0][0][1:3] == ["-m", "csvql"]
    assert calls[0][1] == tmp_path
    assert result.case_id == "query_json"
    assert len(result.measured_timings_ms) == 5
