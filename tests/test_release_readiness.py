from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess

import pytest

from csvql.release_readiness import (
    ReleaseReadinessCommandError,
    ReleaseReadinessResult,
    _venv_command_path,
    format_release_readiness_summary,
    read_pyproject_name,
    run_release_command,
    select_built_wheel,
    verify_release_readiness,
    version_strings_match,
)


def test_version_strings_match_requires_all_three_sources() -> None:
    assert version_strings_match("0.1.0", "0.1.0", "0.1.0") is True
    assert version_strings_match("0.1.0", "0.1.1", "0.1.0") is False


def test_read_pyproject_name_returns_distribution_name(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "localql"
version = "0.1.0"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    assert read_pyproject_name(pyproject) == "localql"


def test_select_built_wheel_returns_matching_wheel(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-0.1.0-py3-none-any.whl"
    wheel.write_text("", encoding="utf-8")

    assert select_built_wheel(tmp_path, "localql", "0.1.0") == wheel


def test_select_built_wheel_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        select_built_wheel(tmp_path, "localql", "0.1.0")


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


def test_venv_command_path_uses_native_layout() -> None:
    assert _venv_command_path(Path("venv"), "python", os_name="posix") == (
        Path("venv") / "bin" / "python"
    )
    assert _venv_command_path(Path("venv"), "python", os_name="nt") == (
        Path("venv") / "Scripts" / "python.exe"
    )


def test_verify_release_readiness_returns_smoke_output(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "csvql").mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text(
        """
[project]
name = "localql"
version = "0.1.0"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo_root / "src" / "csvql" / "__init__.py").write_text(
        '__version__ = "0.1.0"\n',
        encoding="utf-8",
    )

    seen_commands: list[list[str]] = []
    venv_dir = repo_root / "out" / "smoke-venv"
    python_path = _venv_command_path(venv_dir, "python")

    def fake_run(args, *, cwd, capture_output, text, check):
        command = [str(part) for part in args]
        seen_commands.append(command)
        if command == ["/fake/python", "-m", "csvql", "--version"]:
            return CompletedProcess(args=args, returncode=0, stdout="0.1.0\n", stderr="")
        if command[:2] == ["uv", "build"]:
            dist_dir = Path(command[-1])
            dist_dir.mkdir(parents=True, exist_ok=True)
            (dist_dir / "localql-0.1.0-py3-none-any.whl").write_text("", encoding="utf-8")
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if command[:2] == ["uv", "venv"]:
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if command[:2] == ["uv", "pip"]:
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if command[:3] == [
            str(python_path),
            "-c",
            "import textual; import csvql.tui_app; print('tui-extra-ok')",
        ]:
            return CompletedProcess(args=args, returncode=0, stdout="tui-extra-ok\n", stderr="")
        if command[-1] == "--version":
            return CompletedProcess(args=args, returncode=0, stdout="0.1.0\n", stderr="")
        if command[-2:] == ["menu", "--help"]:
            return CompletedProcess(
                args=args,
                returncode=0,
                stdout="Open the interactive CSVQL terminal menu.\n",
                stderr="",
            )
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
    assert result.tui_import_output == "tui-extra-ok"
    assert "interactive CSVQL terminal menu" in result.menu_help_output
    assert result.distribution_name == "localql"
    assert result.wheel_path.name == "localql-0.1.0-py3-none-any.whl"
    assert (repo_root / "out" / "smoke" / "orders.csv").exists()
    assert [
        "uv",
        "pip",
        "install",
        "--python",
        str(python_path),
        f"localql[tui] @ file://{repo_root / 'out' / 'dist' / 'localql-0.1.0-py3-none-any.whl'}",
    ] in seen_commands


def test_format_release_readiness_summary_includes_tui_proof(tmp_path: Path) -> None:
    result = ReleaseReadinessResult(
        distribution_name="localql",
        pyproject_version="0.1.0",
        package_version="0.1.0",
        cli_version="0.1.0",
        wheel_path=tmp_path / "dist" / "localql-0.1.0-py3-none-any.whl",
        inspect_output='{"row_count":{"mode":"not_counted"}}',
        tui_import_output="tui-extra-ok",
        menu_help_output="Open the interactive CSVQL terminal menu.",
    )

    summary = format_release_readiness_summary(result)

    assert "Release readiness proof passed." in summary
    assert "Distribution: localql" in summary
    assert "localql-0.1.0-py3-none-any.whl" in summary
    assert "tui-extra-ok" in summary
    assert "Open the interactive CSVQL terminal menu." in summary
