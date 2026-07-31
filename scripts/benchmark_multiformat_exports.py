"""Run the LocalQL multi-format export benchmark and write local evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from csvql.export_benchmark import run_export_benchmark_suite


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        default="output/benchmarks/multiformat-exports",
    )
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--measured-runs", type=int, default=3)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    result = run_export_benchmark_suite(
        repo_root=repo_root,
        output_root=Path(args.output_root),
        source_row_count=args.rows,
        warmup_runs=args.warmup_runs,
        measured_runs=args.measured_runs,
    )
    print(result.artifact_path)
    print(result.summary_path)


if __name__ == "__main__":
    main()
