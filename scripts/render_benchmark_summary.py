"""Render Markdown from a benchmark artifact JSON file."""

from __future__ import annotations

import argparse
from pathlib import Path

from csvql.benchmarking import load_benchmark_artifact, render_benchmark_summary


def main() -> None:
    """Load a benchmark artifact JSON file and write its Markdown summary."""

    parser = argparse.ArgumentParser()
    parser.add_argument("artifact")
    parser.add_argument("--out")
    args = parser.parse_args()

    artifact_path = Path(args.artifact).resolve()
    out_path = (
        Path(args.out).resolve() if args.out else artifact_path.with_name("benchmark-summary.md")
    )
    artifact = load_benchmark_artifact(artifact_path)
    out_path.write_text(render_benchmark_summary(artifact), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
