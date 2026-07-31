from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from csvql.export import ExportFormat
from csvql.export_benchmark import (
    build_export_benchmark_case_specs,
    render_export_benchmark_summary,
    run_export_benchmark_suite,
    run_export_case_benchmark,
)


def test_export_benchmark_matrix_covers_all_five_sources_and_three_outputs(
    tmp_path: Path,
) -> None:
    cases = build_export_benchmark_case_specs(tmp_path, source_row_count=10)

    assert len(cases) == 15
    assert {case.case_id for case in cases} == {
        f"{source_format}_to_{export_format}"
        for source_format in ("csv", "json", "ndjson", "parquet", "excel")
        for export_format in ("ndjson", "parquet", "excel")
    }
    excel_case = next(case for case in cases if case.case_id == "excel_to_parquet")
    assert "records.sheet=Sheet1" in excel_case.command
    assert "records.range=A1:D11" in excel_case.command
    assert "records.type_mode=infer" in excel_case.command
    assert excel_case.command[-1] == "--force"


def test_export_case_benchmark_measures_cli_and_validates_final_output(
    tmp_path: Path,
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "queries").mkdir()
    (tmp_path / "output").mkdir()
    input_path = tmp_path / "data" / "records.csv"
    input_path.write_text("id,category,amount,active\n0,a,1.0,true\n1,b,2.0,false\n")
    case = build_export_benchmark_case_specs(
        tmp_path,
        source_row_count=2,
        source_formats=("csv",),
        export_formats=(ExportFormat.ndjson,),
    )[0]
    calls: list[tuple[list[str], Path]] = []

    def fake_run(args, *, cwd, capture_output, text, check, timeout):
        del capture_output, text, check, timeout
        calls.append((list(args), Path(cwd)))
        case.output_path.write_text(
            "\n".join(
                (
                    json.dumps({"active": True, "amount": "1.00", "category": "a", "id": 0}),
                    json.dumps({"active": False, "amount": "2.00", "category": "b", "id": 1}),
                    "",
                )
            ),
            encoding="utf-8",
        )
        return CompletedProcess(args=args, returncode=0, stdout="Wrote export.\n", stderr="")

    ticks = iter((1.0, 1.01, 2.0, 2.02, 3.0, 3.03))

    result = run_export_case_benchmark(
        case,
        project_root=tmp_path,
        expected_rows=2,
        warmup_runs=1,
        measured_runs=2,
        run_command=fake_run,
        clock=lambda: next(ticks),
    )

    assert len(calls) == 3
    assert calls[0][0][1:3] == ["-m", "csvql"]
    assert calls[0][1] == tmp_path
    assert result.measured_timings_ms == pytest.approx((20.0, 30.0))
    assert result.median_ms == pytest.approx(25.0)
    assert result.validation == {
        "row_count": 2,
        "id_sum": 1,
        "minimum_id": 0,
        "maximum_id": 1,
    }


def test_small_real_export_benchmark_writes_valid_artifact_and_summary(
    tmp_path: Path,
) -> None:
    result = run_export_benchmark_suite(
        repo_root=tmp_path,
        output_root=tmp_path / "benchmarks",
        source_row_count=20,
        warmup_runs=0,
        measured_runs=1,
        source_formats=("csv", "parquet"),
        export_formats=(ExportFormat.ndjson, ExportFormat.parquet),
    )

    assert result.artifact_path.is_file()
    assert result.summary_path.is_file()
    assert [case.case_id for case in result.artifact.cases] == [
        "csv_to_ndjson",
        "csv_to_parquet",
        "parquet_to_ndjson",
        "parquet_to_parquet",
    ]
    assert all(case.validation["row_count"] == 20 for case in result.artifact.cases)
    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["source_row_count"] == 20
    assert payload["metadata"]["measured_runs"] == 1
    summary = render_export_benchmark_summary(result.artifact)
    assert "| csv | ndjson |" in summary
    assert "| csv | parquet |" in summary
    assert "| parquet | ndjson |" in summary


@pytest.mark.parametrize("row_count", (0, -1, True, 1_048_576))
def test_export_benchmark_rejects_invalid_or_excel_incompatible_row_counts(
    tmp_path: Path,
    row_count: int,
) -> None:
    with pytest.raises(ValueError, match="source_row_count"):
        build_export_benchmark_case_specs(tmp_path, source_row_count=row_count)
