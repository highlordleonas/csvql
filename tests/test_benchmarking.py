from pathlib import Path

from csvql.benchmarking import (
    BenchmarkArtifact,
    BenchmarkCaseResult,
    BenchmarkDatasetRecord,
    BenchmarkMetadata,
    load_benchmark_artifact,
    render_benchmark_summary,
)


def test_benchmark_artifact_round_trips_through_json(tmp_path) -> None:
    artifact = BenchmarkArtifact(
        metadata=BenchmarkMetadata(
            schema_version=1,
            csvql_version="0.1.0",
            duckdb_version="1.5.4",
            python_version="3.12.11",
            platform="macOS-15-arm64",
            generated_at="2026-06-29T18:00:00Z",
            warmup_runs=1,
            measured_runs=5,
        ),
        datasets=(
            BenchmarkDatasetRecord(
                dataset_id="fixture",
                project_path="examples/sales",
                seed=None,
                customer_rows=3,
                order_rows=4,
                file_sizes={"data/customers.csv": 120, "data/orders.csv": 220},
            ),
        ),
        cases=(
            BenchmarkCaseResult(
                case_id="profile_json",
                dataset_id="fixture",
                label="profile orders json",
                command=("profile", "orders", "--output", "json"),
                measured_timings_ms=(8.0, 8.5, 9.0, 8.2, 8.7),
                median_ms=8.5,
                min_ms=8.0,
                max_ms=9.0,
                validation={"row_count": 4},
            ),
        ),
        notes=(
            "Local benchmark evidence only.",
            "No large-file claim beyond recorded datasets.",
        ),
    )

    artifact_path = tmp_path / "benchmark.json"
    artifact.write_json(artifact_path)
    loaded = load_benchmark_artifact(artifact_path)

    assert loaded == artifact


def test_render_benchmark_summary_includes_dataset_table_and_notes() -> None:
    artifact = BenchmarkArtifact(
        metadata=BenchmarkMetadata(
            schema_version=1,
            csvql_version="0.1.0",
            duckdb_version="1.5.4",
            python_version="3.12.11",
            platform="macOS-15-arm64",
            generated_at="2026-06-29T18:00:00Z",
            warmup_runs=1,
            measured_runs=5,
        ),
        datasets=(
            BenchmarkDatasetRecord(
                dataset_id="fixture",
                project_path="examples/sales",
                seed=None,
                customer_rows=3,
                order_rows=4,
                file_sizes={"data/customers.csv": 120, "data/orders.csv": 220},
            ),
        ),
        cases=(
            BenchmarkCaseResult(
                case_id="query_json",
                dataset_id="fixture",
                label="query orders json",
                command=("query", "data/orders.csv", "--output", "json", "SELECT 1"),
                measured_timings_ms=(3.0, 3.1, 3.2, 3.3, 3.4),
                median_ms=3.2,
                min_ms=3.0,
                max_ms=3.4,
                validation={"row_count": 1},
            ),
        ),
        notes=("Local benchmark evidence only.",),
    )

    summary = render_benchmark_summary(artifact)

    assert "# CSVQL Benchmark Summary" in summary
    assert "fixture" in summary
    assert "query orders json" in summary
    assert "3.200" in summary
    assert "Local benchmark evidence only." in summary


def test_readme_mentions_repo_local_benchmark_workflow() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")

    assert "uv run python scripts/benchmark_csvql.py" in readme
    assert "uv run python scripts/verify_release_readiness.py" in readme
    assert "Local benchmark evidence only" in readme
