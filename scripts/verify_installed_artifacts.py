"""Verify installed LocalQL release artifacts in isolated environments."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import textwrap
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess, TimeoutExpired

COMMAND_TIMEOUT_SECONDS = 300.0
REQUIRED_PYTHON_VERSION = "3.12.11"
REPO_ROOT = Path(__file__).resolve().parents[1]
QUERY_SQL = "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status ORDER BY status"
EXPECTED_QUERY_SUBSET: Mapping[str, object] = {
    "columns": ["status", "order_count"],
    "rows": [
        {"status": "paid", "order_count": 2},
        {"status": "pending", "order_count": 1},
    ],
    "row_count": 2,
}
API_SMOKE = textwrap.dedent(
    """
    from csvql import CSVQLSession

    session = CSVQLSession.from_config(".")
    result = session.query("SELECT COUNT(*) AS order_count FROM orders")
    assert result.columns == ("order_count",)
    assert result.rows == ((3,),)
    """
).strip()
CORE_WITHOUT_TEXTUAL_SMOKE = textwrap.dedent(
    """
    from importlib.util import find_spec

    assert find_spec("textual") is None
    """
).strip()
TUI_IMPORT_SMOKE = textwrap.dedent(
    """
    import csvql.tui_app
    import textual
    """
).strip()

RunCommand = Callable[..., CompletedProcess[str]]


class InstalledArtifactVerificationError(RuntimeError):
    """Raised when isolated installed-artifact evidence is invalid."""


def environment_executable_path(
    environment_dir: Path,
    executable: str,
    *,
    os_name: str = os.name,
) -> Path:
    """Return an executable path for a virtual environment's native layout."""

    if os_name == "nt":
        return environment_dir / "Scripts" / f"{executable}.exe"
    return environment_dir / "bin" / executable


def _validate_expected_version(expected_version: str) -> None:
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}", expected_version) is None:
        raise InstalledArtifactVerificationError(
            "expected version must be an exact three-component release version"
        )


def _validate_local_file(path: Path, *, exact_name: str, role: str) -> Path:
    candidate = path.expanduser()
    if candidate.name != exact_name:
        raise InstalledArtifactVerificationError(f"{role} must use the exact filename")
    if candidate.is_symlink() or not candidate.is_file():
        raise InstalledArtifactVerificationError(f"{role} must be a regular file, not a symlink")
    try:
        return candidate.resolve(strict=True)
    except OSError as exc:
        raise InstalledArtifactVerificationError(f"{role} must be a readable regular file") from exc


def _prepare_work_dir(work_dir: Path) -> Path:
    candidate = work_dir.expanduser().resolve(strict=False)
    if candidate.exists() or candidate.is_symlink():
        raise InstalledArtifactVerificationError("work directory must not already exist")
    if not candidate.parent.is_dir():
        raise InstalledArtifactVerificationError(
            "work directory parent must be an existing directory"
        )
    try:
        candidate.mkdir(mode=0o700)
    except OSError as exc:
        raise InstalledArtifactVerificationError("could not create the work directory") from exc
    return candidate


def _sanitized_environment(*, public_index: bool) -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "VIRTUAL_ENV",
        "PIP_TARGET",
        "PIP_PREFIX",
        "UV_TOOL_DIR",
        "UV_TOOL_BIN_DIR",
    ):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PIP_CONFIG_FILE"] = os.devnull
    environment["UV_NO_CONFIG"] = "1"
    if public_index:
        for name in (
            "PIP_EXTRA_INDEX_URL",
            "PIP_FIND_LINKS",
            "PIP_INDEX_URL",
            "PIP_NO_INDEX",
            "UV_DEFAULT_INDEX",
            "UV_EXTRA_INDEX_URL",
            "UV_FIND_LINKS",
            "UV_INDEX",
            "UV_INDEX_URL",
            "UV_NO_INDEX",
        ):
            environment.pop(name, None)
        environment["PIP_INDEX_URL"] = "https://pypi.org/simple"
        environment["UV_DEFAULT_INDEX"] = "https://pypi.org/simple"
    return environment


def _run_checked(
    command: Sequence[str],
    *,
    role: str,
    cwd: Path,
    environment: Mapping[str, str],
    run_command: RunCommand,
) -> CompletedProcess[str]:
    try:
        completed = run_command(
            list(command),
            cwd=cwd,
            env=dict(environment),
            check=True,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            shell=False,
        )
    except CalledProcessError as exc:
        raise InstalledArtifactVerificationError(
            f"{role} failed with exit status {exc.returncode}"
        ) from exc
    except TimeoutExpired as exc:
        raise InstalledArtifactVerificationError(f"{role} timed out") from exc
    except OSError as exc:
        raise InstalledArtifactVerificationError(f"{role} could not be executed") from exc
    if completed.returncode != 0:
        raise InstalledArtifactVerificationError(
            f"{role} failed with exit status {completed.returncode}"
        )
    return completed


def _require_version(completed: CompletedProcess[str], *, expected_version: str, role: str) -> None:
    if completed.stdout.strip() != expected_version:
        raise InstalledArtifactVerificationError(f"{role} version evidence did not match")


def _require_query_evidence(completed: CompletedProcess[str]) -> None:
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InstalledArtifactVerificationError("core query evidence was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise InstalledArtifactVerificationError("core query evidence was not a JSON object")
    observed = {key: payload.get(key) for key in EXPECTED_QUERY_SUBSET}
    if observed != EXPECTED_QUERY_SUBSET:
        raise InstalledArtifactVerificationError(
            "core query evidence did not match expected result"
        )


def _write_smoke_project(project_dir: Path) -> None:
    (project_dir / ".csvql.yml").write_text(
        "version: 1\ntables:\n  orders:\n    path: orders.csv\n",
        encoding="utf-8",
    )
    (project_dir / "orders.csv").write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\nORD-3,paid\n",
        encoding="utf-8",
    )


def _run_pip_smokes(
    *,
    wheel: Path | None,
    core_requirements: Path | None,
    tui_requirements: Path | None,
    work_dir: Path,
    project_dir: Path,
    expected_version: str,
    python_version: str,
    public_index: bool,
    environment: Mapping[str, str],
    run_command: RunCommand,
) -> None:
    core_venv = work_dir / "pip-core"
    core_python = environment_executable_path(core_venv, "python")
    core_csvql = environment_executable_path(core_venv, "csvql")
    _run_checked(
        ["uv", "venv", "--python", python_version, "--seed", str(core_venv)],
        role="create core pip environment",
        cwd=project_dir,
        environment=environment,
        run_command=run_command,
    )
    if public_index:
        _run_checked(
            [str(core_python), "-m", "pip", "install", f"localql=={expected_version}"],
            role="install published core package",
            cwd=project_dir,
            environment=environment,
            run_command=run_command,
        )
    else:
        assert wheel is not None
        assert core_requirements is not None
        _run_checked(
            [
                str(core_python),
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "-r",
                str(core_requirements),
            ],
            role="install locked core requirements",
            cwd=project_dir,
            environment=environment,
            run_command=run_command,
        )
        _run_checked(
            [str(core_python), "-m", "pip", "install", "--no-deps", str(wheel)],
            role="install local core wheel",
            cwd=project_dir,
            environment=environment,
            run_command=run_command,
        )
    completed = _run_checked(
        [str(core_csvql), "--version"],
        role="run core pip version smoke",
        cwd=project_dir,
        environment=environment,
        run_command=run_command,
    )
    _require_version(completed, expected_version=expected_version, role="core pip")
    completed = _run_checked(
        [str(core_csvql), "query", "orders.csv", QUERY_SQL, "--output", "json"],
        role="run core query smoke",
        cwd=project_dir,
        environment=environment,
        run_command=run_command,
    )
    _require_query_evidence(completed)
    _run_checked(
        [str(core_python), "-c", API_SMOKE],
        role="run installed Python API smoke",
        cwd=project_dir,
        environment=environment,
        run_command=run_command,
    )
    _run_checked(
        [str(core_python), "-c", CORE_WITHOUT_TEXTUAL_SMOKE],
        role="verify core package excludes Textual",
        cwd=project_dir,
        environment=environment,
        run_command=run_command,
    )

    tui_venv = work_dir / "pip-tui"
    tui_python = environment_executable_path(tui_venv, "python")
    tui_csvql = environment_executable_path(tui_venv, "csvql")
    _run_checked(
        ["uv", "venv", "--python", python_version, "--seed", str(tui_venv)],
        role="create TUI pip environment",
        cwd=project_dir,
        environment=environment,
        run_command=run_command,
    )
    if public_index:
        _run_checked(
            [str(tui_python), "-m", "pip", "install", f"localql[tui]=={expected_version}"],
            role="install published TUI package",
            cwd=project_dir,
            environment=environment,
            run_command=run_command,
        )
    else:
        assert wheel is not None
        assert tui_requirements is not None
        _run_checked(
            [
                str(tui_python),
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "-r",
                str(tui_requirements),
            ],
            role="install locked TUI requirements",
            cwd=project_dir,
            environment=environment,
            run_command=run_command,
        )
        wheel_requirement = f"localql[tui] @ {wheel.as_uri()}"
        _run_checked(
            [str(tui_python), "-m", "pip", "install", "--no-deps", wheel_requirement],
            role="install local TUI wheel",
            cwd=project_dir,
            environment=environment,
            run_command=run_command,
        )
    _run_checked(
        [str(tui_python), "-c", TUI_IMPORT_SMOKE],
        role="run pip TUI import smoke",
        cwd=project_dir,
        environment=environment,
        run_command=run_command,
    )
    _run_checked(
        [str(tui_csvql), "menu", "--help"],
        role="run pip TUI menu smoke",
        cwd=project_dir,
        environment=environment,
        run_command=run_command,
    )


def _tool_environment(
    base_environment: Mapping[str, str],
    *,
    tool_dir: Path,
    tool_bin_dir: Path,
) -> dict[str, str]:
    tool_dir.mkdir(mode=0o700)
    tool_bin_dir.mkdir(mode=0o700)
    environment = dict(base_environment)
    environment["UV_TOOL_DIR"] = str(tool_dir)
    environment["UV_TOOL_BIN_DIR"] = str(tool_bin_dir)
    return environment


def _run_uv_tool_smokes(
    *,
    wheel: Path | None,
    core_requirements: Path | None,
    tui_requirements: Path | None,
    work_dir: Path,
    project_dir: Path,
    expected_version: str,
    python_version: str,
    public_index: bool,
    environment: Mapping[str, str],
    run_command: RunCommand,
) -> None:
    core_tool_dir = work_dir / "uv-tool-core"
    core_bin_dir = work_dir / "uv-tool-core-bin"
    core_environment = _tool_environment(
        environment,
        tool_dir=core_tool_dir,
        tool_bin_dir=core_bin_dir,
    )
    if public_index:
        core_install_command = [
            "uv",
            "tool",
            "install",
            "--python",
            python_version,
            f"localql=={expected_version}",
        ]
    else:
        assert wheel is not None
        assert core_requirements is not None
        core_install_command = [
            "uv",
            "tool",
            "install",
            "--python",
            python_version,
            "--with-requirements",
            str(core_requirements),
            str(wheel),
        ]
    _run_checked(
        core_install_command,
        role="install core uv tool",
        cwd=project_dir,
        environment=core_environment,
        run_command=run_command,
    )
    core_csvql = environment_executable_path(core_bin_dir, "csvql")
    completed = _run_checked(
        [str(core_csvql), "--version"],
        role="run core uv-tool version smoke",
        cwd=project_dir,
        environment=core_environment,
        run_command=run_command,
    )
    _require_version(completed, expected_version=expected_version, role="core uv-tool")

    tui_tool_dir = work_dir / "uv-tool-tui"
    tui_bin_dir = work_dir / "uv-tool-tui-bin"
    tui_environment = _tool_environment(
        environment,
        tool_dir=tui_tool_dir,
        tool_bin_dir=tui_bin_dir,
    )
    if public_index:
        tui_install_command = [
            "uv",
            "tool",
            "install",
            "--python",
            python_version,
            f"localql[tui]=={expected_version}",
        ]
    else:
        assert wheel is not None
        assert tui_requirements is not None
        wheel_requirement = f"localql[tui] @ {wheel.as_uri()}"
        tui_install_command = [
            "uv",
            "tool",
            "install",
            "--python",
            python_version,
            "--with-requirements",
            str(tui_requirements),
            wheel_requirement,
        ]
    _run_checked(
        tui_install_command,
        role="install TUI uv tool",
        cwd=project_dir,
        environment=tui_environment,
        run_command=run_command,
    )
    tui_csvql = environment_executable_path(tui_bin_dir, "csvql")
    completed = _run_checked(
        [str(tui_csvql), "--version"],
        role="run TUI uv-tool version smoke",
        cwd=project_dir,
        environment=tui_environment,
        run_command=run_command,
    )
    _require_version(completed, expected_version=expected_version, role="TUI uv-tool")
    tui_python = environment_executable_path(tui_tool_dir / "localql", "python")
    _run_checked(
        [str(tui_python), "-c", TUI_IMPORT_SMOKE],
        role="run uv-tool TUI import smoke",
        cwd=project_dir,
        environment=tui_environment,
        run_command=run_command,
    )
    _run_checked(
        [str(tui_csvql), "menu", "--help"],
        role="run uv-tool TUI menu smoke",
        cwd=project_dir,
        environment=tui_environment,
        run_command=run_command,
    )


def verify_installed_artifacts(
    *,
    wheel: Path | None,
    core_requirements: Path | None,
    tui_requirements: Path | None,
    work_dir: Path,
    expected_version: str,
    python_version: str,
    public_index: bool,
    allow_published_version_check: bool,
    run_command: RunCommand = subprocess.run,
) -> dict[str, object]:
    """Run isolated pip and uv-tool release smokes and return JSON evidence.

    The injected runner is the only subprocess boundary. Local paths are exact,
    regular inputs, and public-index mode cannot accept them.
    """

    _validate_expected_version(expected_version)
    if python_version != REQUIRED_PYTHON_VERSION:
        raise InstalledArtifactVerificationError(
            f"Python must be exactly {REQUIRED_PYTHON_VERSION} for release evidence"
        )
    if public_index:
        if not allow_published_version_check:
            raise InstalledArtifactVerificationError(
                "public-index mode requires --allow-published-version-check"
            )
        if any(path is not None for path in (wheel, core_requirements, tui_requirements)):
            raise InstalledArtifactVerificationError(
                "public-index mode rejects local artifact inputs"
            )
        resolved_wheel = None
        resolved_core_requirements = None
        resolved_tui_requirements = None
    else:
        if allow_published_version_check:
            raise InstalledArtifactVerificationError(
                "--allow-published-version-check is valid only with --public-index"
            )
        if wheel is None or core_requirements is None or tui_requirements is None:
            raise InstalledArtifactVerificationError(
                "local mode requires wheel, core requirements, and TUI requirements"
            )
        resolved_wheel = _validate_local_file(
            wheel,
            exact_name=f"localql-{expected_version}-py3-none-any.whl",
            role="wheel",
        )
        resolved_core_requirements = _validate_local_file(
            core_requirements,
            exact_name="core-requirements.txt",
            role="core requirements",
        )
        resolved_tui_requirements = _validate_local_file(
            tui_requirements,
            exact_name="tui-requirements.txt",
            role="TUI requirements",
        )

    resolved_work_dir = _prepare_work_dir(work_dir)
    environment = _sanitized_environment(public_index=public_index)
    with tempfile.TemporaryDirectory(prefix="localql-installed-smoke-") as project_text:
        project_dir = Path(project_text).resolve()
        if project_dir.is_relative_to(REPO_ROOT):
            raise InstalledArtifactVerificationError(
                "temporary smoke project must be outside the repository source tree"
            )
        _write_smoke_project(project_dir)
        _run_pip_smokes(
            wheel=resolved_wheel,
            core_requirements=resolved_core_requirements,
            tui_requirements=resolved_tui_requirements,
            work_dir=resolved_work_dir,
            project_dir=project_dir,
            expected_version=expected_version,
            python_version=python_version,
            public_index=public_index,
            environment=environment,
            run_command=run_command,
        )
        _run_uv_tool_smokes(
            wheel=resolved_wheel,
            core_requirements=resolved_core_requirements,
            tui_requirements=resolved_tui_requirements,
            work_dir=resolved_work_dir,
            project_dir=project_dir,
            expected_version=expected_version,
            python_version=python_version,
            public_index=public_index,
            environment=environment,
            run_command=run_command,
        )

    return {
        "checks": {
            "pip_core_api": "passed",
            "pip_core_query": "passed",
            "pip_core_version": "passed",
            "pip_core_without_textual": "passed",
            "pip_tui_import": "passed",
            "pip_tui_menu_help": "passed",
            "uv_tool_core_version": "passed",
            "uv_tool_tui_import": "passed",
            "uv_tool_tui_menu_help": "passed",
            "uv_tool_tui_version": "passed",
        },
        "expected_version": expected_version,
        "mode": "public-index" if public_index else "local-artifact",
        "python": python_version,
        "schema_version": 1,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify LocalQL through isolated pip and uv-tool installations."
    )
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--core-requirements", type=Path)
    parser.add_argument("--tui-requirements", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--python", dest="python_version", required=True)
    parser.add_argument("--public-index", action="store_true")
    parser.add_argument("--allow-published-version-check", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    run_command: RunCommand = subprocess.run,
) -> int:
    """Parse CLI inputs, run installed-artifact smokes, and print JSON evidence."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        evidence = verify_installed_artifacts(
            wheel=args.wheel,
            core_requirements=args.core_requirements,
            tui_requirements=args.tui_requirements,
            work_dir=args.work_dir,
            expected_version=args.expected_version,
            python_version=args.python_version,
            public_index=args.public_index,
            allow_published_version_check=args.allow_published_version_check,
            run_command=run_command,
        )
    except InstalledArtifactVerificationError as exc:
        parser.error(str(exc))
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
