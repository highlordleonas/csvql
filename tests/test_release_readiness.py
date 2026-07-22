import importlib.util
import subprocess
from inspect import signature
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

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_release_readiness.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "verify_release_readiness_script",
    SCRIPT_PATH,
)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
verify_release_readiness_script = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(verify_release_readiness_script)


def _write_release_readiness_repo(tmp_path: Path) -> Path:
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
    return repo_root


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


def test_verify_release_readiness_returns_local_compatibility_evidence(tmp_path: Path) -> None:
    repo_root = _write_release_readiness_repo(tmp_path)
    seen_commands: list[list[str]] = []
    venv_dir = repo_root / "out" / "smoke-venv"
    python_path = _venv_command_path(venv_dir, "python")
    csvql_path = _venv_command_path(venv_dir, "csvql")
    audit_script = repo_root / "scripts" / "audit_package_contents.py"
    inspect_script = repo_root / "scripts" / "verify_release_artifacts.py"

    def fake_run(args, *, cwd, capture_output, text, check):
        command = [str(part) for part in args]
        seen_commands.append(command)
        if command[:2] == ["uv", "build"]:
            dist_dir = Path(command[-1])
            dist_dir.mkdir(parents=True, exist_ok=True)
            (dist_dir / "localql-0.1.0-py3-none-any.whl").write_text("", encoding="utf-8")
            (dist_dir / "localql-0.1.0.tar.gz").write_text("", encoding="utf-8")
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if command == [
            "/fake/python",
            str(audit_script),
            str(repo_root / "out" / "dist"),
            "--expected-version",
            "0.1.0",
        ]:
            return CompletedProcess(
                args=args,
                returncode=0,
                stdout="Package content audit passed: 1 wheel(s), 1 sdist(s).\n",
                stderr="",
            )
        if command == [
            "/fake/python",
            str(inspect_script),
            "inspect",
            str(repo_root / "out" / "dist"),
            "--expected-version",
            "0.1.0",
        ]:
            return CompletedProcess(
                args=args,
                returncode=0,
                stdout="Release artifact inspection passed: 1 wheel(s), 1 sdist(s).\n",
                stderr="",
            )
        if command[:2] == ["uv", "venv"]:
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if command[:2] == ["uv", "pip"]:
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if command == [str(csvql_path), "--version"]:
            return CompletedProcess(args=args, returncode=0, stdout="0.1.0\n", stderr="")
        if command[:3] == [
            str(csvql_path),
            "inspect",
            str(repo_root / "out" / "smoke" / "orders.csv"),
        ]:
            return CompletedProcess(
                args=args,
                returncode=0,
                stdout='{"row_count":{"mode":"not_counted"}}\n',
                stderr="",
            )
        if command[:3] == [
            str(python_path),
            "-c",
            "import textual; import csvql.tui_app; print('tui-extra-ok')",
        ]:
            return CompletedProcess(args=args, returncode=0, stdout="tui-extra-ok\n", stderr="")
        if command[-2:] == ["menu", "--help"]:
            return CompletedProcess(
                args=args,
                returncode=0,
                stdout="Open the interactive CSVQL terminal menu.\n",
                stderr="",
            )
        if command[1:3] == ["query", str(repo_root / "out" / "smoke" / "orders.csv")]:
            return CompletedProcess(
                args=args,
                returncode=0,
                stdout='{"columns":["order_count"],"rows":[{"order_count":1}],"row_count":1}\n',
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
    assert result.query_output == (
        '{"columns":["order_count"],"rows":[{"order_count":1}],"row_count":1}'
    )
    assert result.tui_import_output == "tui-extra-ok"
    assert "interactive CSVQL terminal menu" in result.menu_help_output
    assert result.distribution_name == "localql"
    assert result.pyproject_version == "0.1.0"
    assert result.package_version == "0.1.0"
    assert result.cli_version == "0.1.0"
    assert result.wheel_path.name == "localql-0.1.0-py3-none-any.whl"
    assert (repo_root / "out" / "smoke" / "orders.csv").exists()
    assert seen_commands[:4] == [
        [
            "uv",
            "build",
            "--sdist",
            "--wheel",
            "--no-create-gitignore",
            "--out-dir",
            str(repo_root / "out" / "dist"),
        ],
        [
            "/fake/python",
            str(audit_script),
            str(repo_root / "out" / "dist"),
            "--expected-version",
            "0.1.0",
        ],
        [
            "/fake/python",
            str(inspect_script),
            "inspect",
            str(repo_root / "out" / "dist"),
            "--expected-version",
            "0.1.0",
        ],
        ["uv", "venv", "--seed", "--clear", str(venv_dir)],
    ]
    assert [
        "uv",
        "pip",
        "install",
        "--python",
        str(python_path),
        (
            "localql[tui] @ "
            f"{(repo_root / 'out' / 'dist' / 'localql-0.1.0-py3-none-any.whl').resolve().as_uri()}"
        ),
    ] in seen_commands
    assert not any(
        "create-manifest" in part or "verify-manifest" in part
        for command in seen_commands
        for part in command
    )
    assert not any(
        part
        in {
            "--manifest",
            "--sha256sums",
            "--source-commit",
            "--tag-name",
            "--tag-object",
            "--peeled-commit",
            "--python-identity-file",
            "--uv-identity-file",
            "--build-constraints-digest-file",
        }
        for command in seen_commands
        for part in command
    )
    assert "Local compatibility evidence passed." in verify_release_readiness_script.__doc__
    assert "does not authorize release custody" in verify_release_readiness_script.__doc__
    assert "publication" in verify_release_readiness_script.__doc__


def test_verify_release_readiness_package_audit_failure_prevents_inspector_and_artifacts(
    tmp_path: Path,
) -> None:
    repo_root = _write_release_readiness_repo(tmp_path)
    seen_commands: list[list[str]] = []
    audit_script = repo_root / "scripts" / "audit_package_contents.py"
    inspect_script = repo_root / "scripts" / "verify_release_artifacts.py"

    def fake_run(args, *, cwd, capture_output, text, check):
        command = [str(part) for part in args]
        seen_commands.append(command)
        if command[:2] == ["uv", "build"]:
            dist_dir = Path(command[-1])
            dist_dir.mkdir(parents=True, exist_ok=True)
            (dist_dir / "localql-0.1.0-py3-none-any.whl").write_text("", encoding="utf-8")
            (dist_dir / "localql-0.1.0.tar.gz").write_text("", encoding="utf-8")
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if command == [
            "/fake/python",
            str(audit_script),
            str(repo_root / "out" / "dist"),
            "--expected-version",
            "0.1.0",
        ]:
            raise CalledProcessError(returncode=2, cmd=args, output="", stderr="audit failed")
        if command == [
            "/fake/python",
            str(inspect_script),
            "inspect",
            str(repo_root / "out" / "dist"),
            "--expected-version",
            "0.1.0",
        ]:
            raise AssertionError("inspector should not run after package audit failure")
        raise AssertionError(f"Unexpected command: {command}")

    with pytest.raises(ReleaseReadinessCommandError) as excinfo:
        verify_release_readiness(
            repo_root,
            work_dir=repo_root / "out",
            python_executable="/fake/python",
            run_command=fake_run,
        )

    assert "audit failed" in str(excinfo.value)
    assert all("inspect" not in command for command in seen_commands[1:])
    assert all("uv venv" not in " ".join(command) for command in seen_commands)
    assert all("uv pip" not in " ".join(command) for command in seen_commands)


def test_verify_release_readiness_inspector_failure_prevents_artifact_execution(
    tmp_path: Path,
) -> None:
    repo_root = _write_release_readiness_repo(tmp_path)
    seen_commands: list[list[str]] = []
    audit_script = repo_root / "scripts" / "audit_package_contents.py"
    inspect_script = repo_root / "scripts" / "verify_release_artifacts.py"

    def fake_run(args, *, cwd, capture_output, text, check):
        command = [str(part) for part in args]
        seen_commands.append(command)
        if command[:2] == ["uv", "build"]:
            dist_dir = Path(command[-1])
            dist_dir.mkdir(parents=True, exist_ok=True)
            (dist_dir / "localql-0.1.0-py3-none-any.whl").write_text("", encoding="utf-8")
            (dist_dir / "localql-0.1.0.tar.gz").write_text("", encoding="utf-8")
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if command == [
            "/fake/python",
            str(audit_script),
            str(repo_root / "out" / "dist"),
            "--expected-version",
            "0.1.0",
        ]:
            return CompletedProcess(
                args=args,
                returncode=0,
                stdout="Package content audit passed: 1 wheel(s), 1 sdist(s).\n",
                stderr="",
            )
        if command == [
            "/fake/python",
            str(inspect_script),
            "inspect",
            str(repo_root / "out" / "dist"),
            "--expected-version",
            "0.1.0",
        ]:
            raise CalledProcessError(returncode=3, cmd=args, output="", stderr="inspect failed")
        raise AssertionError(f"Unexpected command: {command}")

    with pytest.raises(ReleaseReadinessCommandError) as excinfo:
        verify_release_readiness(
            repo_root,
            work_dir=repo_root / "out",
            python_executable="/fake/python",
            run_command=fake_run,
        )

    assert "inspect failed" in str(excinfo.value)
    assert all("uv venv" not in " ".join(command) for command in seen_commands)
    assert all("uv pip" not in " ".join(command) for command in seen_commands)
    assert all(
        "csvql" not in command[0] or command[0] == "/fake/python" for command in seen_commands
    )


def test_verify_release_readiness_signature_and_result_shape_are_unchanged() -> None:
    parameters = signature(verify_release_readiness).parameters
    assert list(parameters) == ["repo_root", "work_dir", "python_executable", "run_command"]
    assert parameters["repo_root"].kind.name == "POSITIONAL_OR_KEYWORD"
    assert parameters["work_dir"].kind.name == "KEYWORD_ONLY"
    assert parameters["python_executable"].kind.name == "KEYWORD_ONLY"
    assert parameters["run_command"].kind.name == "KEYWORD_ONLY"
    assert parameters["run_command"].default is subprocess.run

    assert [field.name for field in ReleaseReadinessResult.__dataclass_fields__.values()] == [
        "distribution_name",
        "pyproject_version",
        "package_version",
        "cli_version",
        "wheel_path",
        "query_output",
        "inspect_output",
        "tui_import_output",
        "menu_help_output",
    ]


def test_format_release_readiness_summary_includes_local_compatibility_language(
    tmp_path: Path,
) -> None:
    result = ReleaseReadinessResult(
        distribution_name="localql",
        pyproject_version="0.1.0",
        package_version="0.1.0",
        cli_version="0.1.0",
        wheel_path=tmp_path / "dist" / "localql-0.1.0-py3-none-any.whl",
        query_output='{"columns":["order_count"],"rows":[{"order_count":1}],"row_count":1}',
        inspect_output='{"row_count":{"mode":"not_counted"}}',
        tui_import_output="tui-extra-ok",
        menu_help_output="Open the interactive CSVQL terminal menu.",
    )

    summary = format_release_readiness_summary(result)

    assert "Local compatibility evidence passed." in summary
    assert "does not authorize release custody" in summary
    assert "publication" in summary
    assert "Distribution: localql" in summary
    assert "localql-0.1.0-py3-none-any.whl" in summary
    assert '"order_count":1' in summary
    assert "tui-extra-ok" in summary
    assert "Open the interactive CSVQL terminal menu." in summary


def test_verify_release_readiness_main_help_mentions_local_compatibility_and_denial(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        verify_release_readiness_script.sys,
        "argv",
        ["verify_release_readiness.py", "--help"],
    )

    with pytest.raises(SystemExit) as excinfo:
        verify_release_readiness_script.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 0
    assert "local compatibility evidence" in captured.out.lower()
    assert "does not authorize release custody" in captured.out.lower()
    assert "publication" in captured.out.lower()
