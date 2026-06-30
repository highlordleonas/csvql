from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess

import pytest

from csvql.release_readiness import (
    ReleaseReadinessCommandError,
    run_release_command,
    select_built_wheel,
    verify_release_readiness,
    version_strings_match,
)


def test_version_strings_match_requires_all_three_sources() -> None:
    assert version_strings_match("0.1.0", "0.1.0", "0.1.0") is True
    assert version_strings_match("0.1.0", "0.1.1", "0.1.0") is False


def test_select_built_wheel_returns_matching_wheel(tmp_path: Path) -> None:
    wheel = tmp_path / "csvql-0.1.0-py3-none-any.whl"
    wheel.write_text("", encoding="utf-8")

    assert select_built_wheel(tmp_path, "0.1.0") == wheel


def test_select_built_wheel_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        select_built_wheel(tmp_path, "0.1.0")


def test_run_release_command_returns_stripped_stdout(tmp_path: Path) -> None:
    def fake_run(args, *, cwd, capture_output, text, check):
        return CompletedProcess(args=args, returncode=0, stdout="0.1.0\n", stderr="")

    assert run_release_command(("uv", "build"), cwd=tmp_path, run_command=fake_run) == "0.1.0"


def test_run_release_command_wraps_subprocess_failure(tmp_path: Path) -> None:
    def fake_run(args, *, cwd, capture_output, text, check):
        raise CalledProcessError(
            returncode=2,
            cmd=args,
            output="",
            stderr="dns error",
        )

    with pytest.raises(ReleaseReadinessCommandError) as excinfo:
        run_release_command(("uv", "build"), cwd=tmp_path, run_command=fake_run)

    assert "uv build" in str(excinfo.value)
    assert "exit status 2" in str(excinfo.value)
    assert "dns error" in str(excinfo.value)


def test_verify_release_readiness_returns_smoke_output(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "csvql").mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text(
        """
[project]
version = "0.1.0"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo_root / "src" / "csvql" / "__init__.py").write_text(
        '__version__ = "0.1.0"\n',
        encoding="utf-8",
    )

    def fake_run(args, *, cwd, capture_output, text, check):
        command = [str(part) for part in args]
        if command == ["/fake/python", "-m", "csvql", "--version"]:
            return CompletedProcess(args=args, returncode=0, stdout="0.1.0\n", stderr="")
        if command[:2] == ["uv", "build"]:
            dist_dir = Path(command[-1])
            dist_dir.mkdir(parents=True, exist_ok=True)
            (dist_dir / "csvql-0.1.0-py3-none-any.whl").write_text("", encoding="utf-8")
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if command[:2] == ["uv", "venv"]:
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if command[:2] == ["uv", "pip"]:
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if command[-1] == "--version":
            return CompletedProcess(args=args, returncode=0, stdout="0.1.0\n", stderr="")
        if command[1:3] == ["inspect", str(repo_root / "out" / "smoke" / "orders.csv")]:
            return CompletedProcess(
                args=args,
                returncode=0,
                stdout='{"row_count":{"mode":"not_counted"}}\n',
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {command}")

    result = verify_release_readiness(
        repo_root,
        work_dir=repo_root / "out",
        python_executable="/fake/python",
        run_command=fake_run,
    )

    assert result.inspect_output == '{"row_count":{"mode":"not_counted"}}'
    assert result.wheel_path.name == "csvql-0.1.0-py3-none-any.whl"
    assert (repo_root / "out" / "smoke" / "orders.csv").exists()
