"""Run the approved CSVQL benchmark suite and write local artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from csvql.benchmark_runner import run_default_benchmark_suite


def main() -> None:
    """Parse CLI arguments and print the generated benchmark artifact paths."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="output/benchmarks")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    result = run_default_benchmark_suite(
        repo_root=repo_root,
        output_root=Path(args.output_root),
    )
    print(result.artifact_path)
    print(result.summary_path)


if __name__ == "__main__":
    main()
