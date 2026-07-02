"""Helpers for repo-local release-readiness verification."""

from __future__ import annotations

import re
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

_VERSION_RE = re.compile(r'^__version__ = "(?P<version>[^"]+)"$', re.MULTILINE)
RunCommand = Callable[..., subprocess.CompletedProcess[str]]


class ReleaseReadinessCommandError(RuntimeError):
    """Raised when a release-proof subprocess command fails."""


@dataclass(frozen=True, slots=True)
class ReleaseReadinessResult:
    """Successful release-readiness proof outputs."""

    pyproject_version: str
    package_version: str
    cli_version: str
    wheel_path: Path
    inspect_output: str
    tui_import_output: str
    menu_help_output: str


def format_release_readiness_summary(result: ReleaseReadinessResult) -> str:
    """Return a human-readable summary for release-readiness proof output."""

    return "\n".join(
        (
            "Release readiness proof passed.",
            (
                "Versions: "
                f"pyproject={result.pyproject_version}, "
                f"package={result.package_version}, "
                f"cli={result.cli_version}"
            ),
            f"Wheel: {result.wheel_path}",
            "Inspect smoke output:",
            result.inspect_output,
            f"TUI extra import: {result.tui_import_output}",
            "Menu help smoke output:",
            result.menu_help_output,
        )
    )


def read_pyproject_version(pyproject_path: Path) -> str:
    """Return the package version declared in ``pyproject.toml``."""

    payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def read_package_version(init_path: Path) -> str:
    """Return the package ``__version__`` string from ``__init__.py``."""

    match = _VERSION_RE.search(init_path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"Could not find __version__ in {init_path}")
    return match.group("version")


def version_strings_match(pyproject_version: str, package_version: str, cli_version: str) -> bool:
    """Return whether all release-proof version strings agree."""

    return pyproject_version == package_version == cli_version


def select_built_wheel(dist_dir: Path, version: str) -> Path:
    """Return the built wheel for ``version`` from ``dist_dir``."""

    matches = sorted(dist_dir.glob(f"csvql-{version}-*.whl"))
    if not matches:
        raise FileNotFoundError(f"No wheel found for csvql {version} in {dist_dir}")
    return matches[0]


def run_release_command(
    args: Sequence[str | Path],
    *,
    cwd: Path,
    run_command: RunCommand = subprocess.run,
) -> str:
    """Run one bounded repo-local command and return stripped stdout."""

    normalized_args = [str(part) for part in args]
    try:
        completed = run_command(
            normalized_args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.output.strip() or "Command failed without output."
        rendered_command = " ".join(normalized_args)
        raise ReleaseReadinessCommandError(
            f"Command failed with exit status {exc.returncode}: {rendered_command}\n{detail}"
        ) from exc
    return completed.stdout.strip()


def verify_release_readiness(
    repo_root: Path,
    *,
    work_dir: Path,
    python_executable: str | Path,
    run_command: RunCommand = subprocess.run,
) -> ReleaseReadinessResult:
    """Build, install, and smoke-test the package from a wheel."""

    dist_dir = work_dir / "dist"
    smoke_dir = work_dir / "smoke"
    venv_dir = work_dir / "smoke-venv"
    work_dir.mkdir(parents=True, exist_ok=True)
    smoke_dir.mkdir(parents=True, exist_ok=True)

    pyproject_version = read_pyproject_version(repo_root / "pyproject.toml")
    package_version = read_package_version(repo_root / "src" / "csvql" / "__init__.py")
    cli_version = run_release_command(
        (python_executable, "-m", "csvql", "--version"),
        cwd=repo_root,
        run_command=run_command,
    )
    if not version_strings_match(pyproject_version, package_version, cli_version):
        raise ValueError(
            f"Version mismatch: pyproject={pyproject_version} "
            f"package={package_version} cli={cli_version}"
        )

    run_release_command(
        ("uv", "build", "--sdist", "--wheel", "--out-dir", dist_dir),
        cwd=repo_root,
        run_command=run_command,
    )
    wheel = select_built_wheel(dist_dir, pyproject_version)
    run_release_command(
        ("uv", "venv", "--seed", "--clear", venv_dir),
        cwd=repo_root,
        run_command=run_command,
    )
    python_path = venv_dir / "bin" / "python"
    csvql_path = venv_dir / "bin" / "csvql"
    run_release_command(
        ("uv", "pip", "install", "--python", python_path, wheel),
        cwd=repo_root,
        run_command=run_command,
    )

    smoke_csv = smoke_dir / "orders.csv"
    smoke_csv.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    run_release_command((csvql_path, "--version"), cwd=repo_root, run_command=run_command)
    inspect_output = run_release_command(
        (csvql_path, "inspect", smoke_csv, "--output", "json"),
        cwd=repo_root,
        run_command=run_command,
    )
    run_release_command(
        ("uv", "pip", "install", "--python", python_path, f"{wheel}[tui]"),
        cwd=repo_root,
        run_command=run_command,
    )
    tui_import_output = run_release_command(
        (
            python_path,
            "-c",
            "import textual; import csvql.tui_app; print('tui-extra-ok')",
        ),
        cwd=repo_root,
        run_command=run_command,
    )
    menu_help_output = run_release_command(
        (csvql_path, "menu", "--help"),
        cwd=repo_root,
        run_command=run_command,
    )
    return ReleaseReadinessResult(
        pyproject_version=pyproject_version,
        package_version=package_version,
        cli_version=cli_version,
        wheel_path=wheel,
        inspect_output=inspect_output,
        tui_import_output=tui_import_output,
        menu_help_output=menu_help_output,
    )
