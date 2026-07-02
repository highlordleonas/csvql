"""Verify version consistency, build outputs, and installed-wheel smoke behavior."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from csvql.release_readiness import (
    ReleaseReadinessCommandError,
    format_release_readiness_summary,
    verify_release_readiness,
)


def main() -> None:
    """Run the repo-local release-readiness proof and print a proof summary."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", default="output/release-readiness")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    work_dir = (repo_root / args.work_dir).resolve()
    try:
        result = verify_release_readiness(
            repo_root,
            work_dir=work_dir,
            python_executable=sys.executable,
        )
    except (ReleaseReadinessCommandError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(format_release_readiness_summary(result))


if __name__ == "__main__":
    main()
