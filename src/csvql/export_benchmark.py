"""End-to-end CLI benchmark matrix for structured source and export formats."""

from __future__ import annotations

import csv
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from csvql import __version__
from csvql.export import ExportFormat

EXPORT_BENCHMARK_SOURCE_FORMATS = ("csv", "json", "ndjson", "parquet", "excel")
EXPORT_BENCHMARK_OUTPUT_FORMATS = (
    ExportFormat.ndjson,
    ExportFormat.parquet,
    ExportFormat.excel,
)

_EXTENSION_DIRECTORY_ENV = "LOCALQL_TEST_DUCKDB_EXTENSION_DIRECTORY"
_DUCKDB_SAFETY_CONFIG = {
    "autoinstall_known_extensions": "false",
    "autoload_known_extensions": "false",
}
_EXCEL_MAX_DATA_ROWS = 1_048_575

RunCommand = Callable[..., subprocess.CompletedProcess[str]]
Clock = Callable[[], float]
OutputValidator = Callable[[Path, ExportFormat, int], dict[str, object]]


@dataclass(frozen=True, slots=True)
class ExportBenchmarkCaseSpec:
    """One source-format to export-format CLI benchmark case."""

    case_id: str
    source_format: str
    export_format: ExportFormat
    command: tuple[str, ...]
    input_path: Path
    output_path: Path


@dataclass(frozen=True, slots=True)
class ExportBenchmarkCaseResult:
    """Measured timing, size, throughput, and correctness facts for one case."""

    case_id: str
    source_format: str
    export_format: str
    command: tuple[str, ...]
    input_bytes: int
    output_bytes: int
    measured_timings_ms: tuple[float, ...]
    median_ms: float
    min_ms: float
    max_ms: float
    rows_per_second: float
    validation: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "source_format": self.source_format,
            "export_format": self.export_format,
            "command": list(self.command),
            "input_bytes": self.input_bytes,
            "output_bytes": self.output_bytes,
            "measured_timings_ms": list(self.measured_timings_ms),
            "median_ms": self.median_ms,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "rows_per_second": self.rows_per_second,
            "validation": self.validation,
        }


@dataclass(frozen=True, slots=True)
class ExportBenchmarkArtifact:
    """Serializable evidence from one complete multi-format export run."""

    generated_at: str
    csvql_version: str
    duckdb_version: str
    python_version: str
    platform: str
    source_row_count: int
    warmup_runs: int
    measured_runs: int
    source_files: dict[str, dict[str, object]]
    cases: tuple[ExportBenchmarkCaseResult, ...]
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "metadata": {
                "schema_version": 1,
                "generated_at": self.generated_at,
                "csvql_version": self.csvql_version,
                "duckdb_version": self.duckdb_version,
                "python_version": self.python_version,
                "platform": self.platform,
                "source_row_count": self.source_row_count,
                "warmup_runs": self.warmup_runs,
                "measured_runs": self.measured_runs,
            },
            "source_files": dict(sorted(self.source_files.items())),
            "cases": [case.as_dict() for case in self.cases],
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class ExportBenchmarkRunOutput:
    """Artifact and summary locations for one benchmark run."""

    artifact: ExportBenchmarkArtifact
    run_root: Path
    artifact_path: Path
    summary_path: Path


def build_export_benchmark_case_specs(
    project_root: Path,
    *,
    source_row_count: int,
    source_formats: Sequence[str] = EXPORT_BENCHMARK_SOURCE_FORMATS,
    export_formats: Sequence[ExportFormat] = EXPORT_BENCHMARK_OUTPUT_FORMATS,
) -> tuple[ExportBenchmarkCaseSpec, ...]:
    """Build the deterministic source/output matrix for one prepared project."""

    _validate_source_row_count(source_row_count)
    normalized_sources = _validate_source_formats(source_formats)
    normalized_exports = _validate_export_formats(export_formats)
    cases: list[ExportBenchmarkCaseSpec] = []
    for source_format in normalized_sources:
        input_path = project_root / "data" / f"records.{_source_suffix(source_format)}"
        for export_format in normalized_exports:
            output_path = (
                project_root / "output" / f"{source_format}-to-{_export_suffix(export_format)}."
                f"{_export_suffix(export_format)}"
            )
            source_options: tuple[str, ...] = ()
            if source_format == "excel":
                source_options = (
                    "--source-option",
                    "records.sheet=Sheet1",
                    "--source-option",
                    f"records.range=A1:D{source_row_count + 1}",
                    "--source-option",
                    "records.type_mode=infer",
                )
            command = (
                "export",
                "queries/export.sql",
                "--format",
                export_format.value,
                "--out",
                str(output_path.relative_to(project_root)),
                "--source",
                f"records={input_path.relative_to(project_root)}",
                "--source-type",
                f"records={source_format}",
                *source_options,
                "--force",
            )
            cases.append(
                ExportBenchmarkCaseSpec(
                    case_id=f"{source_format}_to_{export_format.value}",
                    source_format=source_format,
                    export_format=export_format,
                    command=command,
                    input_path=input_path,
                    output_path=output_path,
                )
            )
    return tuple(cases)


def run_export_case_benchmark(
    case: ExportBenchmarkCaseSpec,
    *,
    project_root: Path,
    expected_rows: int,
    warmup_runs: int,
    measured_runs: int,
    run_command: RunCommand = subprocess.run,
    clock: Clock = time.perf_counter,
    validate_output: OutputValidator | None = None,
) -> ExportBenchmarkCaseResult:
    """Measure one end-to-end CLI export and validate the final artifact."""

    if warmup_runs < 0:
        raise ValueError("warmup_runs must be non-negative")
    if measured_runs <= 0:
        raise ValueError("measured_runs must be positive")
    if expected_rows <= 0:
        raise ValueError("expected_rows must be positive")
    for _ in range(warmup_runs):
        _run_export_once(
            case,
            project_root=project_root,
            run_command=run_command,
            clock=clock,
        )

    timings: list[float] = []
    for _ in range(measured_runs):
        timings.append(
            _run_export_once(
                case,
                project_root=project_root,
                run_command=run_command,
                clock=clock,
            )
        )

    validator = validate_output or validate_export_benchmark_output
    validation = validator(case.output_path, case.export_format, expected_rows)
    median_ms = float(statistics.median(timings))
    return ExportBenchmarkCaseResult(
        case_id=case.case_id,
        source_format=case.source_format,
        export_format=case.export_format.value,
        command=case.command,
        input_bytes=case.input_path.stat().st_size,
        output_bytes=case.output_path.stat().st_size,
        measured_timings_ms=tuple(timings),
        median_ms=median_ms,
        min_ms=min(timings),
        max_ms=max(timings),
        rows_per_second=expected_rows / (median_ms / 1000),
        validation=validation,
    )


def run_export_benchmark_suite(
    *,
    repo_root: Path,
    output_root: Path,
    source_row_count: int = 100_000,
    warmup_runs: int = 1,
    measured_runs: int = 3,
    source_formats: Sequence[str] = EXPORT_BENCHMARK_SOURCE_FORMATS,
    export_formats: Sequence[ExportFormat] = EXPORT_BENCHMARK_OUTPUT_FORMATS,
) -> ExportBenchmarkRunOutput:
    """Generate deterministic fixtures and benchmark the full CLI export matrix."""

    _validate_source_row_count(source_row_count)
    if warmup_runs < 0:
        raise ValueError("warmup_runs must be non-negative")
    if measured_runs <= 0:
        raise ValueError("measured_runs must be positive")
    normalized_sources = _validate_source_formats(source_formats)
    normalized_exports = _validate_export_formats(export_formats)
    if "excel" in normalized_sources or ExportFormat.excel in normalized_exports:
        _require_provisioned_excel_extension()

    resolved_repo_root = repo_root.resolve()
    resolved_output_root = (
        output_root.resolve()
        if output_root.is_absolute()
        else (resolved_repo_root / output_root).resolve()
    )
    generated_at = datetime.now(UTC)
    run_root = resolved_output_root / generated_at.strftime("%Y%m%dT%H%M%S.%fZ")
    project_root = run_root / "project"
    (project_root / "data").mkdir(parents=True)
    (project_root / "queries").mkdir()
    (project_root / "output").mkdir()
    (project_root / "queries" / "export.sql").write_text(
        """
        SELECT
            CAST(id AS BIGINT) AS id,
            CAST(category AS VARCHAR) AS category,
            CAST(amount AS DECIMAL(18,2)) AS amount,
            CAST(active AS BOOLEAN) AS active
        FROM records
        """,
        encoding="utf-8",
    )
    source_paths = _write_benchmark_sources(
        project_root / "data",
        source_row_count=source_row_count,
        source_formats=normalized_sources,
    )
    cases = build_export_benchmark_case_specs(
        project_root,
        source_row_count=source_row_count,
        source_formats=normalized_sources,
        export_formats=normalized_exports,
    )
    results = tuple(
        run_export_case_benchmark(
            case,
            project_root=project_root,
            expected_rows=source_row_count,
            warmup_runs=warmup_runs,
            measured_runs=measured_runs,
        )
        for case in cases
    )
    source_files = {
        source_format: {
            "path": str(path.relative_to(project_root)),
            "bytes": path.stat().st_size,
        }
        for source_format, path in source_paths.items()
    }
    artifact = ExportBenchmarkArtifact(
        generated_at=generated_at.isoformat(),
        csvql_version=__version__,
        duckdb_version=duckdb.__version__,
        python_version=platform.python_version(),
        platform=platform.platform(),
        source_row_count=source_row_count,
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
        source_files=source_files,
        cases=results,
        notes=(
            "End-to-end local CLI timings include process startup, deterministic "
            "source resolution, query execution, export writing, and atomic publication.",
            "Output validation is performed after timing and checks row count and ID bounds.",
            "Results describe only the recorded machine, runtime, dataset size, and formats.",
        ),
    )
    artifact_path = run_root / "multiformat-export-benchmark.json"
    summary_path = run_root / "multiformat-export-benchmark.md"
    artifact_path.write_text(
        json.dumps(artifact.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(render_export_benchmark_summary(artifact), encoding="utf-8")
    return ExportBenchmarkRunOutput(
        artifact=artifact,
        run_root=run_root,
        artifact_path=artifact_path,
        summary_path=summary_path,
    )


def validate_export_benchmark_output(
    path: Path,
    export_format: ExportFormat,
    expected_rows: int,
) -> dict[str, object]:
    """Validate one benchmark output without including validation in its timing."""

    if export_format is ExportFormat.ndjson:
        row_count = 0
        id_sum = 0
        minimum_id: int | None = None
        maximum_id: int | None = None
        with path.open(encoding="utf-8") as output:
            for line in output:
                payload = json.loads(line)
                if not isinstance(payload, dict) or set(payload) != {
                    "active",
                    "amount",
                    "category",
                    "id",
                }:
                    raise ValueError("NDJSON benchmark output has an unexpected record shape")
                row_id = int(payload["id"])
                row_count += 1
                id_sum += row_id
                minimum_id = row_id if minimum_id is None else min(minimum_id, row_id)
                maximum_id = row_id if maximum_id is None else max(maximum_id, row_id)
    else:
        connection = _duckdb_connection()
        try:
            if export_format is ExportFormat.parquet:
                relation_sql = "read_parquet(?)"
            elif export_format is ExportFormat.excel:
                connection.load_extension("excel")
                relation_sql = "read_xlsx(?, header=true)"
            else:
                raise ValueError(f"Unsupported benchmark export format: {export_format}")
            row = connection.execute(
                f"""
                SELECT
                    count(*),
                    sum(CAST(id AS BIGINT)),
                    min(CAST(id AS BIGINT)),
                    max(CAST(id AS BIGINT))
                FROM {relation_sql}
                """,
                [str(path)],
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ValueError("Benchmark output validation returned no aggregate row")
        row_count = int(row[0])
        id_sum = int(row[1])
        minimum_id = int(row[2])
        maximum_id = int(row[3])

    expected_sum = expected_rows * (expected_rows - 1) // 2
    expected_maximum = expected_rows - 1
    if (
        row_count != expected_rows
        or id_sum != expected_sum
        or minimum_id != 0
        or maximum_id != expected_maximum
    ):
        raise ValueError(
            f"Benchmark output validation failed for {export_format.value}: "
            f"rows={row_count}, id_sum={id_sum}, min={minimum_id}, max={maximum_id}"
        )
    return {
        "row_count": row_count,
        "id_sum": id_sum,
        "minimum_id": minimum_id,
        "maximum_id": maximum_id,
    }


def render_export_benchmark_summary(artifact: ExportBenchmarkArtifact) -> str:
    """Render one concise Markdown table from a benchmark artifact."""

    lines = [
        "# LocalQL Multi-format Export Benchmark",
        "",
        f"- LocalQL: `{artifact.csvql_version}`",
        f"- DuckDB: `{artifact.duckdb_version}`",
        f"- Python: `{artifact.python_version}`",
        f"- Platform: `{artifact.platform}`",
        f"- Source rows per case: `{artifact.source_row_count}`",
        f"- Warmup runs: `{artifact.warmup_runs}`",
        f"- Measured runs: `{artifact.measured_runs}`",
        "",
        "| Source | Output | Input bytes | Output bytes | Median ms | Rows/s |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for case in artifact.cases:
        lines.append(
            f"| {case.source_format} | {case.export_format} | "
            f"{case.input_bytes} | {case.output_bytes} | "
            f"{case.median_ms:.3f} | {case.rows_per_second:.1f} |"
        )
    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {note}" for note in artifact.notes)
    lines.append("")
    return "\n".join(lines)


def _run_export_once(
    case: ExportBenchmarkCaseSpec,
    *,
    project_root: Path,
    run_command: RunCommand,
    clock: Clock,
) -> float:
    args = [sys.executable, "-m", "csvql", *case.command]
    started = clock()
    completed = run_command(
        args,
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    elapsed_ms = (clock() - started) * 1000
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no command output"
        raise RuntimeError(f"{case.case_id} failed: {detail}")
    if not case.output_path.is_file():
        raise RuntimeError(f"{case.case_id} did not create its expected output file")
    return elapsed_ms


def _write_benchmark_sources(
    data_root: Path,
    *,
    source_row_count: int,
    source_formats: tuple[str, ...],
) -> dict[str, Path]:
    source_paths = {
        source_format: data_root / f"records.{_source_suffix(source_format)}"
        for source_format in source_formats
    }
    csv_path = data_root / "records.csv"
    if "csv" in source_formats or any(
        source_format in source_formats for source_format in ("parquet", "excel")
    ):
        _write_csv_source(csv_path, source_row_count)
    if "json" in source_formats:
        _write_json_source(source_paths["json"], source_row_count, ndjson=False)
    if "ndjson" in source_formats:
        _write_json_source(source_paths["ndjson"], source_row_count, ndjson=True)
    if "parquet" in source_formats or "excel" in source_formats:
        connection = _duckdb_connection()
        try:
            relation_sql = """
                SELECT
                    CAST(id AS BIGINT) AS id,
                    CAST(category AS VARCHAR) AS category,
                    CAST(amount AS DECIMAL(18,2)) AS amount,
                    CAST(active AS BOOLEAN) AS active
                FROM read_csv_auto(?, header=true)
            """
            if "parquet" in source_formats:
                connection.execute(
                    f"COPY ({relation_sql}) TO ? (FORMAT PARQUET)",
                    [str(source_paths["parquet"]), str(csv_path)],
                )
            if "excel" in source_formats:
                connection.load_extension("excel")
                connection.execute(
                    f"COPY ({relation_sql}) TO ? (FORMAT XLSX, HEADER true)",
                    [str(source_paths["excel"]), str(csv_path)],
                )
        finally:
            connection.close()
    if "csv" not in source_formats:
        csv_path.unlink(missing_ok=True)
    return source_paths


def _write_csv_source(path: Path, row_count: int) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(("id", "category", "amount", "active"))
        for row_id in range(row_count):
            writer.writerow(
                (
                    row_id,
                    f"group-{row_id % 10}",
                    f"{(row_id % 100_000) / 100:.2f}",
                    "true" if row_id % 2 == 0 else "false",
                )
            )


def _write_json_source(path: Path, row_count: int, *, ndjson: bool) -> None:
    with path.open("w", encoding="utf-8") as output:
        if not ndjson:
            output.write("[")
        for row_id in range(row_count):
            if not ndjson and row_id:
                output.write(",")
            output.write(
                json.dumps(
                    {
                        "id": row_id,
                        "category": f"group-{row_id % 10}",
                        "amount": (row_id % 100_000) / 100,
                        "active": row_id % 2 == 0,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            if ndjson:
                output.write("\n")
        if not ndjson:
            output.write("]\n")


def _require_provisioned_excel_extension() -> None:
    connection = _duckdb_connection()
    try:
        state = connection.execute(
            """
            SELECT installed OR loaded
            FROM duckdb_extensions()
            WHERE extension_name = ?
            """,
            ["excel"],
        ).fetchone()
        if state is None or not state[0]:
            raise RuntimeError(
                "The multi-format export benchmark requires a provisioned DuckDB "
                "excel extension and never installs it automatically."
            )
        connection.load_extension("excel")
    finally:
        connection.close()


def _duckdb_connection() -> duckdb.DuckDBPyConnection:
    config: dict[str, str | bool | int | float | list[str]] = dict(_DUCKDB_SAFETY_CONFIG)
    raw_directory = os.environ.get(_EXTENSION_DIRECTORY_ENV)
    if raw_directory is not None:
        extension_directory = Path(raw_directory)
        if not extension_directory.is_absolute() or not extension_directory.is_dir():
            raise RuntimeError(
                f"{_EXTENSION_DIRECTORY_ENV} must name an existing absolute directory."
            )
        config["extension_directory"] = str(extension_directory)
    return duckdb.connect(database=":memory:", config=config)


def _validate_source_row_count(source_row_count: int) -> None:
    if (
        not isinstance(source_row_count, int)
        or isinstance(source_row_count, bool)
        or source_row_count <= 0
    ):
        raise ValueError("source_row_count must be a positive integer")
    if source_row_count > _EXCEL_MAX_DATA_ROWS:
        raise ValueError(
            f"source_row_count cannot exceed {_EXCEL_MAX_DATA_ROWS} for the Excel matrix"
        )


def _validate_source_formats(source_formats: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(source_formats)
    if not normalized:
        raise ValueError("source_formats must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("source_formats must not contain duplicates")
    unsupported = [
        source_format
        for source_format in normalized
        if source_format not in EXPORT_BENCHMARK_SOURCE_FORMATS
    ]
    if unsupported:
        raise ValueError(f"Unsupported source benchmark format(s): {unsupported}")
    return normalized


def _validate_export_formats(
    export_formats: Sequence[ExportFormat],
) -> tuple[ExportFormat, ...]:
    normalized = tuple(export_formats)
    if not normalized:
        raise ValueError("export_formats must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("export_formats must not contain duplicates")
    unsupported = [
        export_format
        for export_format in normalized
        if export_format not in EXPORT_BENCHMARK_OUTPUT_FORMATS
    ]
    if unsupported:
        raise ValueError(f"Unsupported export benchmark format(s): {unsupported}")
    return normalized


def _source_suffix(source_format: str) -> str:
    return "xlsx" if source_format == "excel" else source_format


def _export_suffix(export_format: ExportFormat) -> str:
    return "xlsx" if export_format is ExportFormat.excel else export_format.value
