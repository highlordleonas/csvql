"""Benchmark execution for CSVQL repo-local hardening workflows."""

from __future__ import annotations

import json
import platform
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from csvql import __version__
from csvql.benchmark_data import (
    SyntheticSalesSpec,
    describe_sales_project,
    write_synthetic_sales_project,
)
from csvql.benchmarking import (
    BenchmarkArtifact,
    BenchmarkCaseResult,
    BenchmarkDatasetRecord,
    BenchmarkMetadata,
    render_benchmark_summary,
)

RunCommand = Callable[..., subprocess.CompletedProcess[str]]
Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class BenchmarkCaseSpec:
    """One CLI benchmark case and the JSON keys it must emit."""

    case_id: str
    label: str
    command: tuple[str, ...]
    expected_json_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkRunOutput:
    """Materialized artifact and rendered summary paths for one run."""

    artifact: BenchmarkArtifact
    run_root: Path
    artifact_path: Path
    summary_path: Path


def build_default_case_specs() -> tuple[BenchmarkCaseSpec, ...]:
    """Return the approved v0.7 benchmark matrix."""

    return (
        BenchmarkCaseSpec(
            case_id="query_json",
            label="query orders json",
            command=(
                "query",
                "data/orders.csv",
                "--output",
                "json",
                (
                    "SELECT status, COUNT(*) AS order_count "
                    "FROM orders GROUP BY status ORDER BY status"
                ),
            ),
            expected_json_keys=("columns", "rows", "row_count", "elapsed_ms"),
        ),
        BenchmarkCaseSpec(
            case_id="run_json",
            label="run revenue_by_month json",
            command=("run", "queries/revenue_by_month.sql", "--output", "json"),
            expected_json_keys=("columns", "rows", "row_count", "elapsed_ms"),
        ),
        BenchmarkCaseSpec(
            case_id="inspect_json",
            label="inspect orders json",
            command=("inspect", "orders", "--output", "json"),
            expected_json_keys=("source", "dialect", "columns", "row_count", "warnings"),
        ),
        BenchmarkCaseSpec(
            case_id="inspect_exact_json",
            label="inspect orders exact json",
            command=("inspect", "orders", "--exact", "--output", "json"),
            expected_json_keys=("source", "dialect", "columns", "row_count", "warnings"),
        ),
        BenchmarkCaseSpec(
            case_id="profile_json",
            label="profile orders json",
            command=("profile", "orders", "--output", "json"),
            expected_json_keys=(
                "source",
                "row_count",
                "column_count",
                "duplicate_row_count",
                "columns",
                "warnings",
            ),
        ),
        BenchmarkCaseSpec(
            case_id="check_json",
            label="check orders json",
            command=("check", "orders", "--output", "json"),
            expected_json_keys=(
                "status",
                "check_count",
                "passed_count",
                "failed_count",
                "checks",
                "warnings",
            ),
        ),
    )


def run_case_benchmark(
    case: BenchmarkCaseSpec,
    *,
    dataset_root: Path,
    dataset_id: str | None = None,
    run_command: RunCommand = subprocess.run,
    clock: Clock = time.perf_counter,
    warmup_runs: int,
    measured_runs: int,
) -> BenchmarkCaseResult:
    """Run one benchmark case with warmup and measured timing passes."""

    if warmup_runs < 0:
        raise ValueError("warmup_runs must be non-negative")
    if measured_runs <= 0:
        raise ValueError("measured_runs must be positive")

    resolved_root = dataset_root.resolve()
    for _ in range(warmup_runs):
        _run_once(case, dataset_root=resolved_root, run_command=run_command, clock=clock)

    timings: list[float] = []
    validation: dict[str, object] = {}
    for _ in range(measured_runs):
        elapsed_ms, payload = _run_once(
            case,
            dataset_root=resolved_root,
            run_command=run_command,
            clock=clock,
        )
        timings.append(elapsed_ms)
        validation = _validate_json_payload(case, payload)

    return BenchmarkCaseResult(
        case_id=case.case_id,
        dataset_id=resolved_root.name if dataset_id is None else dataset_id,
        label=case.label,
        command=case.command,
        measured_timings_ms=tuple(timings),
        median_ms=float(statistics.median(timings)),
        min_ms=min(timings),
        max_ms=max(timings),
        validation=validation,
    )


def run_default_benchmark_suite(
    *,
    repo_root: Path,
    output_root: Path,
    warmup_runs: int = 1,
    measured_runs: int = 5,
) -> BenchmarkRunOutput:
    """Run the approved benchmark suite and persist its artifact files."""

    resolved_repo_root = repo_root.resolve()
    resolved_output_root = _resolve_output_root(
        repo_root=resolved_repo_root,
        output_root=output_root,
    )
    generated_at = datetime.now(UTC)
    run_root = resolved_output_root / generated_at.strftime("%Y%m%dT%H%M%SZ")
    datasets_root = run_root / "datasets"
    datasets_root.mkdir(parents=True, exist_ok=True)

    fixture_root = resolved_repo_root / "examples" / "sales"
    medium_root = datasets_root / "synthetic_medium"
    large_root = datasets_root / "synthetic_large"

    write_synthetic_sales_project(
        medium_root,
        SyntheticSalesSpec(
            dataset_id="synthetic_medium",
            seed=20260629,
            customer_count=10_000,
            orders_per_customer=10,
        ),
    )
    write_synthetic_sales_project(
        large_root,
        SyntheticSalesSpec(
            dataset_id="synthetic_large",
            seed=20260629,
            customer_count=50_000,
            orders_per_customer=10,
        ),
    )

    dataset_records = (
        describe_sales_project(
            fixture_root,
            dataset_id="fixture",
            seed=None,
            project_path="examples/sales",
        ),
        describe_sales_project(
            medium_root,
            dataset_id="synthetic_medium",
            seed=20260629,
            project_path=str(medium_root.relative_to(resolved_repo_root)),
        ),
        describe_sales_project(
            large_root,
            dataset_id="synthetic_large",
            seed=20260629,
            project_path=str(large_root.relative_to(resolved_repo_root)),
        ),
    )

    case_results = _run_case_matrix(
        dataset_records=dataset_records,
        dataset_roots={
            "fixture": fixture_root,
            "synthetic_medium": medium_root,
            "synthetic_large": large_root,
        },
        case_specs=build_default_case_specs(),
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
    )

    artifact = BenchmarkArtifact(
        metadata=BenchmarkMetadata(
            schema_version=1,
            csvql_version=__version__,
            duckdb_version=duckdb.__version__,
            python_version=platform.python_version(),
            platform=platform.platform(),
            generated_at=generated_at.isoformat(),
            warmup_runs=warmup_runs,
            measured_runs=measured_runs,
        ),
        datasets=dataset_records,
        cases=case_results,
        notes=(
            "Local benchmark evidence only.",
            "Do not claim large-file proof beyond the recorded datasets.",
        ),
    )

    artifact_path = run_root / "benchmark.json"
    summary_path = run_root / "benchmark-summary.md"
    artifact.write_json(artifact_path)
    summary_path.write_text(render_benchmark_summary(artifact), encoding="utf-8")
    return BenchmarkRunOutput(
        artifact=artifact,
        run_root=run_root,
        artifact_path=artifact_path,
        summary_path=summary_path,
    )


def _run_case_matrix(
    *,
    dataset_records: tuple[BenchmarkDatasetRecord, ...],
    dataset_roots: dict[str, Path],
    case_specs: tuple[BenchmarkCaseSpec, ...],
    warmup_runs: int,
    measured_runs: int,
) -> tuple[BenchmarkCaseResult, ...]:
    """Run every benchmark case against every dataset tier."""

    case_results: list[BenchmarkCaseResult] = []
    for dataset_record in dataset_records:
        dataset_root = dataset_roots[dataset_record.dataset_id]
        for case in case_specs:
            case_results.append(
                run_case_benchmark(
                    case,
                    dataset_root=dataset_root,
                    dataset_id=dataset_record.dataset_id,
                    warmup_runs=warmup_runs,
                    measured_runs=measured_runs,
                )
            )
    return tuple(case_results)


def _resolve_output_root(*, repo_root: Path, output_root: Path) -> Path:
    """Resolve the output root relative to the repository when needed."""

    if output_root.is_absolute():
        return output_root
    return repo_root / output_root


def _run_once(
    case: BenchmarkCaseSpec,
    *,
    dataset_root: Path,
    run_command: RunCommand,
    clock: Clock,
) -> tuple[float, str]:
    """Execute one CLI invocation and return elapsed milliseconds plus stdout."""

    args = [sys.executable, "-m", "csvql", *case.command]
    started = clock()
    if run_command is subprocess.run:
        completed = run_command(
            args,
            cwd=dataset_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=300,
        )
    else:
        completed = run_command(
            args,
            cwd=dataset_root,
            capture_output=True,
            text=True,
            check=True,
        )
    elapsed_ms = (clock() - started) * 1000
    return elapsed_ms, completed.stdout


def _validate_json_payload(case: BenchmarkCaseSpec, stdout: str) -> dict[str, object]:
    """Validate the JSON shape for one benchmark case and record stable facts."""

    payload = json.loads(stdout)
    if not isinstance(payload, dict):
        raise ValueError(f"{case.case_id} expected a JSON object payload")

    missing = [key for key in case.expected_json_keys if key not in payload]
    if missing:
        raise ValueError(f"{case.case_id} missing JSON keys: {missing}")

    validation: dict[str, object] = {"stdout_keys": sorted(payload.keys())}
    for key in (
        "row_count",
        "status",
        "check_count",
        "passed_count",
        "failed_count",
        "column_count",
        "duplicate_row_count",
    ):
        if key in payload:
            validation[key] = payload[key]
    return validation
