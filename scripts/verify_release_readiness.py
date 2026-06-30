"""Verify version consistency, build outputs, and installed-wheel smoke behavior."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from csvql.release_readiness import (
    read_package_version,
    read_pyproject_version,
    select_built_wheel,
    version_strings_match,
)


def _run(args: list[str], *, cwd: Path) -> str:
    """Run one bounded repo-local command and return stripped stdout."""

    completed = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def main() -> None:
    """Run the repo-local release-readiness proof and print smoke JSON."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", default="output/release-readiness")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    work_dir = (repo_root / args.work_dir).resolve()
    dist_dir = work_dir / "dist"
    smoke_dir = work_dir / "smoke"
    venv_dir = work_dir / "smoke-venv"
    work_dir.mkdir(parents=True, exist_ok=True)
    smoke_dir.mkdir(parents=True, exist_ok=True)

    pyproject_version = read_pyproject_version(repo_root / "pyproject.toml")
    package_version = read_package_version(repo_root / "src" / "csvql" / "__init__.py")
    cli_version = _run([sys.executable, "-m", "csvql", "--version"], cwd=repo_root)
    if not version_strings_match(pyproject_version, package_version, cli_version):
        raise SystemExit(
            f"Version mismatch: pyproject={pyproject_version} "
            f"package={package_version} cli={cli_version}"
        )

    _run(["uv", "build", "--sdist", "--wheel", "--out-dir", str(dist_dir)], cwd=repo_root)
    wheel = select_built_wheel(dist_dir, pyproject_version)
    _run(["uv", "venv", "--seed", "--clear", str(venv_dir)], cwd=repo_root)
    python_path = venv_dir / "bin" / "python"
    csvql_path = venv_dir / "bin" / "csvql"
    _run(["uv", "pip", "install", "--python", str(python_path), str(wheel)], cwd=repo_root)

    smoke_csv = smoke_dir / "orders.csv"
    smoke_csv.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    _run([str(csvql_path), "--version"], cwd=repo_root)
    inspect_output = _run(
        [str(csvql_path), "inspect", str(smoke_csv), "--output", "json"],
        cwd=repo_root,
    )
    print(inspect_output)


if __name__ == "__main__":
    main()
