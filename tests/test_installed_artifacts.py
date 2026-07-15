"""Contract tests for installed release artifact verification."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess, TimeoutExpired
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "verify_installed_artifacts.py"
sys.path.insert(0, str(SCRIPTS_DIR))

import verify_installed_artifacts as verifier  # noqa: E402

EXPECTED_QUERY = (
    "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status ORDER BY status"
)
EXPECTED_QUERY_PAYLOAD = {
    "columns": ["status", "order_count"],
    "rows": [
        {"status": "paid", "order_count": 2},
        {"status": "pending", "order_count": 1},
    ],
    "row_count": 2,
}
EXPECTED_CHECKS = {
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
}


class RecordingRunner:
    """Record subprocess requests and return deterministic smoke evidence."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.project_catalog: str | None = None
        self.project_csv: str | None = None

    def __call__(
        self,
        args: Sequence[object],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
        shell: bool,
    ) -> CompletedProcess[str]:
        command = [str(part) for part in args]
        self.calls.append(
            {
                "args": command,
                "cwd": Path(cwd),
                "env": dict(env),
                "check": check,
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
                "shell": shell,
            }
        )
        if len(command) > 1 and command[1] == "query":
            self.project_catalog = (Path(cwd) / ".csvql.yml").read_text(encoding="utf-8")
            self.project_csv = (Path(cwd) / "orders.csv").read_text(encoding="utf-8")
            stdout = json.dumps(EXPECTED_QUERY_PAYLOAD) + "\n"
        elif command[-1:] == ["--version"]:
            stdout = "1.0.2\n"
        elif command[-2:] == ["menu", "--help"]:
            stdout = "Usage: csvql menu [OPTIONS]\n"
        else:
            stdout = ""
        return CompletedProcess(args=command, returncode=0, stdout=stdout, stderr="")


def _write_local_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    wheel = inputs / "localql-1.0.2-py3-none-any.whl"
    core_requirements = inputs / "core-requirements.txt"
    tui_requirements = inputs / "tui-requirements.txt"
    wheel.write_bytes(b"synthetic unit-test wheel")
    core_requirements.write_text("core==1.0 --hash=sha256:00\n", encoding="utf-8")
    tui_requirements.write_text("tui==1.0 --hash=sha256:11\n", encoding="utf-8")
    return wheel.resolve(), core_requirements.resolve(), tui_requirements.resolve()


def _verify_local(tmp_path: Path, runner: RecordingRunner) -> tuple[dict[str, object], Path]:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    work_dir = tmp_path / "work"
    evidence = verifier.verify_installed_artifacts(
        wheel=wheel,
        core_requirements=core_requirements,
        tui_requirements=tui_requirements,
        work_dir=work_dir,
        expected_version="1.0.2",
        python_version="3.12.11",
        public_index=False,
        allow_published_version_check=False,
        run_command=runner,
    )
    return evidence, work_dir.resolve()


def test_installed_artifact_verifier_exists() -> None:
    assert SCRIPT_PATH.is_file()


@pytest.mark.parametrize(
    ("os_name", "executable", "expected"),
    [
        ("posix", "python", Path("venv") / "bin" / "python"),
        ("nt", "python", Path("venv") / "Scripts" / "python.exe"),
        ("posix", "csvql", Path("venv") / "bin" / "csvql"),
        ("nt", "csvql", Path("venv") / "Scripts" / "csvql.exe"),
    ],
)
def test_environment_executable_path_uses_native_layout(
    os_name: str,
    executable: str,
    expected: Path,
) -> None:
    assert (
        verifier.environment_executable_path(Path("venv"), executable, os_name=os_name) == expected
    )


def test_local_mode_composes_exact_pip_and_uv_tool_commands(tmp_path: Path) -> None:
    runner = RecordingRunner()
    evidence, work_dir = _verify_local(tmp_path, runner)
    wheel, core_requirements, tui_requirements = (
        (tmp_path / "inputs" / name).resolve()
        for name in (
            "localql-1.0.2-py3-none-any.whl",
            "core-requirements.txt",
            "tui-requirements.txt",
        )
    )
    core_venv = work_dir / "pip-core"
    tui_venv = work_dir / "pip-tui"
    core_python = verifier.environment_executable_path(core_venv, "python")
    tui_python = verifier.environment_executable_path(tui_venv, "python")
    core_csvql = verifier.environment_executable_path(core_venv, "csvql")
    tui_csvql = verifier.environment_executable_path(tui_venv, "csvql")
    wheel_requirement = f"localql[tui] @ {wheel.as_uri()}"
    commands = [call["args"] for call in runner.calls]

    assert commands[:4] == [
        ["uv", "venv", "--python", "3.12.11", "--seed", str(core_venv)],
        [
            str(core_python),
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "-r",
            str(core_requirements),
        ],
        [str(core_python), "-m", "pip", "install", "--no-deps", str(wheel)],
        [str(core_csvql), "--version"],
    ]
    assert [
        "uv",
        "venv",
        "--python",
        "3.12.11",
        "--seed",
        str(tui_venv),
    ] in commands
    assert [
        str(tui_python),
        "-m",
        "pip",
        "install",
        "--require-hashes",
        "-r",
        str(tui_requirements),
    ] in commands
    assert [
        str(tui_python),
        "-m",
        "pip",
        "install",
        "--no-deps",
        wheel_requirement,
    ] in commands
    assert [str(tui_csvql), "menu", "--help"] in commands
    assert [
        "uv",
        "tool",
        "install",
        "--python",
        "3.12.11",
        "--with-requirements",
        str(core_requirements),
        str(wheel),
    ] in commands
    assert [
        "uv",
        "tool",
        "install",
        "--python",
        "3.12.11",
        "--with-requirements",
        str(tui_requirements),
        wheel_requirement,
    ] in commands
    assert all(command[:3] != ["uv", "pip", "install"] for command in commands)
    assert evidence == {
        "checks": EXPECTED_CHECKS,
        "expected_version": "1.0.2",
        "mode": "local-artifact",
        "python": "3.12.11",
        "schema_version": 1,
    }


def test_local_mode_runs_query_api_and_optional_dependency_smokes(tmp_path: Path) -> None:
    runner = RecordingRunner()
    _, work_dir = _verify_local(tmp_path, runner)
    core_python = verifier.environment_executable_path(work_dir / "pip-core", "python")
    core_csvql = verifier.environment_executable_path(work_dir / "pip-core", "csvql")
    commands = [call["args"] for call in runner.calls]

    assert [str(core_csvql), "query", "orders.csv", EXPECTED_QUERY, "--output", "json"] in commands
    assert [str(core_python), "-c", verifier.API_SMOKE] in commands
    assert [str(core_python), "-c", verifier.CORE_WITHOUT_TEXTUAL_SMOKE] in commands
    assert runner.project_catalog == "version: 1\ntables:\n  orders:\n    path: orders.csv\n"
    assert runner.project_csv == ("order_id,status\nORD-1,paid\nORD-2,pending\nORD-3,paid\n")


def test_tui_smokes_use_isolated_python_and_cli(tmp_path: Path) -> None:
    runner = RecordingRunner()
    _, work_dir = _verify_local(tmp_path, runner)
    tui_python = verifier.environment_executable_path(work_dir / "pip-tui", "python")
    tui_csvql = verifier.environment_executable_path(work_dir / "pip-tui", "csvql")
    tool_tui_python = verifier.environment_executable_path(
        work_dir / "uv-tool-tui" / "localql",
        "python",
    )
    tool_tui_csvql = verifier.environment_executable_path(
        work_dir / "uv-tool-tui-bin",
        "csvql",
    )
    commands = [call["args"] for call in runner.calls]

    assert [str(tui_python), "-c", verifier.TUI_IMPORT_SMOKE] in commands
    assert [str(tui_csvql), "menu", "--help"] in commands
    assert [str(tool_tui_python), "-c", verifier.TUI_IMPORT_SMOKE] in commands
    assert [str(tool_tui_csvql), "--version"] in commands
    assert [str(tool_tui_csvql), "menu", "--help"] in commands


def test_subprocess_boundary_is_sanitized_bounded_and_outside_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT / "src"))
    monkeypatch.setenv("UV_TOOL_DIR", "/unsafe/default-tools")
    monkeypatch.setenv("UV_TOOL_BIN_DIR", "/unsafe/default-bin")
    runner = RecordingRunner()
    _, work_dir = _verify_local(tmp_path, runner)

    for call in runner.calls:
        assert call["check"] is True
        assert call["capture_output"] is True
        assert call["text"] is True
        assert call["shell"] is False
        assert call["timeout"] == verifier.COMMAND_TIMEOUT_SECONDS
        assert "PYTHONPATH" not in call["env"]
        assert "PYTHONHOME" not in call["env"]
        assert "VIRTUAL_ENV" not in call["env"]
        assert not call["cwd"].is_relative_to(REPO_ROOT)

    tool_calls = [call for call in runner.calls if call["args"][:3] == ["uv", "tool", "install"]]
    assert len(tool_calls) == 2
    assert tool_calls[0]["env"]["UV_TOOL_DIR"] == str(work_dir / "uv-tool-core")
    assert tool_calls[0]["env"]["UV_TOOL_BIN_DIR"] == str(work_dir / "uv-tool-core-bin")
    assert tool_calls[1]["env"]["UV_TOOL_DIR"] == str(work_dir / "uv-tool-tui")
    assert tool_calls[1]["env"]["UV_TOOL_BIN_DIR"] == str(work_dir / "uv-tool-tui-bin")
    assert tool_calls[0]["env"]["UV_TOOL_DIR"] != tool_calls[1]["env"]["UV_TOOL_DIR"]
    assert tool_calls[0]["env"]["UV_TOOL_BIN_DIR"] != tool_calls[1]["env"]["UV_TOOL_BIN_DIR"]


def test_public_index_mode_uses_only_exact_published_requirements(tmp_path: Path) -> None:
    runner = RecordingRunner()
    work_dir = tmp_path / "public-work"
    evidence = verifier.verify_installed_artifacts(
        wheel=None,
        core_requirements=None,
        tui_requirements=None,
        work_dir=work_dir,
        expected_version="1.0.2",
        python_version="3.12.11",
        public_index=True,
        allow_published_version_check=True,
        run_command=runner,
    )
    resolved_work_dir = work_dir.resolve()
    core_python = verifier.environment_executable_path(resolved_work_dir / "pip-core", "python")
    tui_python = verifier.environment_executable_path(resolved_work_dir / "pip-tui", "python")
    commands = [call["args"] for call in runner.calls]

    assert [str(core_python), "-m", "pip", "install", "localql==1.0.2"] in commands
    assert [str(tui_python), "-m", "pip", "install", "localql[tui]==1.0.2"] in commands
    assert [
        "uv",
        "tool",
        "install",
        "--python",
        "3.12.11",
        "localql==1.0.2",
    ] in commands
    assert [
        "uv",
        "tool",
        "install",
        "--python",
        "3.12.11",
        "localql[tui]==1.0.2",
    ] in commands
    assert all("--with-requirements" not in command for command in commands)
    assert all("--no-deps" not in command for command in commands)
    assert all("file:" not in part for command in commands for part in command)
    assert evidence["mode"] == "public-index"


def test_public_index_requires_explicit_post_publication_gate(tmp_path: Path) -> None:
    runner = RecordingRunner()

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="published-version"):
        verifier.verify_installed_artifacts(
            wheel=None,
            core_requirements=None,
            tui_requirements=None,
            work_dir=tmp_path / "work",
            expected_version="1.0.2",
            python_version="3.12.11",
            public_index=True,
            allow_published_version_check=False,
            run_command=runner,
        )

    assert runner.calls == []
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("local_input", ["wheel", "core", "tui"])
def test_public_index_rejects_every_local_input(tmp_path: Path, local_input: str) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    values = {"wheel": None, "core": None, "tui": None}
    values[local_input] = {
        "wheel": wheel,
        "core": core_requirements,
        "tui": tui_requirements,
    }[local_input]
    runner = RecordingRunner()

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="rejects local"):
        verifier.verify_installed_artifacts(
            wheel=values["wheel"],
            core_requirements=values["core"],
            tui_requirements=values["tui"],
            work_dir=tmp_path / "work",
            expected_version="1.0.2",
            python_version="3.12.11",
            public_index=True,
            allow_published_version_check=True,
            run_command=runner,
        )

    assert runner.calls == []


@pytest.mark.parametrize("missing_input", ["wheel", "core", "tui"])
def test_local_mode_requires_every_exact_input(tmp_path: Path, missing_input: str) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    values: dict[str, Path | None] = {
        "wheel": wheel,
        "core": core_requirements,
        "tui": tui_requirements,
    }
    values[missing_input] = None
    runner = RecordingRunner()

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="requires"):
        verifier.verify_installed_artifacts(
            wheel=values["wheel"],
            core_requirements=values["core"],
            tui_requirements=values["tui"],
            work_dir=tmp_path / "work",
            expected_version="1.0.2",
            python_version="3.12.11",
            public_index=False,
            allow_published_version_check=False,
            run_command=runner,
        )

    assert runner.calls == []


@pytest.mark.parametrize(
    ("role", "wrong_name"),
    [
        ("wheel", "localql-1.0.3-py3-none-any.whl"),
        ("core", "requirements.txt"),
        ("tui", "requirements-tui.txt"),
    ],
)
def test_local_mode_rejects_inexact_input_names(
    tmp_path: Path,
    role: str,
    wrong_name: str,
) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    wrong_path = tmp_path / wrong_name
    wrong_path.write_text("not the exact input\n", encoding="utf-8")
    values = {"wheel": wheel, "core": core_requirements, "tui": tui_requirements}
    values[role] = wrong_path

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="exact filename"):
        verifier.verify_installed_artifacts(
            wheel=values["wheel"],
            core_requirements=values["core"],
            tui_requirements=values["tui"],
            work_dir=tmp_path / "work",
            expected_version="1.0.2",
            python_version="3.12.11",
            public_index=False,
            allow_published_version_check=False,
            run_command=RecordingRunner(),
        )


def test_local_mode_rejects_symlinked_input(tmp_path: Path) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    linked_wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    try:
        linked_wheel.symlink_to(wheel)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="regular file"):
        verifier.verify_installed_artifacts(
            wheel=linked_wheel,
            core_requirements=core_requirements,
            tui_requirements=tui_requirements,
            work_dir=tmp_path / "work",
            expected_version="1.0.2",
            python_version="3.12.11",
            public_index=False,
            allow_published_version_check=False,
            run_command=RecordingRunner(),
        )


@pytest.mark.parametrize("existing_contents", [False, True])
def test_work_dir_must_be_new_and_is_never_deleted(
    tmp_path: Path,
    existing_contents: bool,
) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    marker = work_dir / "keep.txt"
    if existing_contents:
        marker.write_text("owner data\n", encoding="utf-8")

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="must not already exist"):
        verifier.verify_installed_artifacts(
            wheel=wheel,
            core_requirements=core_requirements,
            tui_requirements=tui_requirements,
            work_dir=work_dir,
            expected_version="1.0.2",
            python_version="3.12.11",
            public_index=False,
            allow_published_version_check=False,
            run_command=RecordingRunner(),
        )

    assert work_dir.is_dir()
    assert marker.exists() is existing_contents


def test_python_version_is_exactly_3_12_11(tmp_path: Path) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)

    with pytest.raises(verifier.InstalledArtifactVerificationError, match=r"3\.12\.11"):
        verifier.verify_installed_artifacts(
            wheel=wheel,
            core_requirements=core_requirements,
            tui_requirements=tui_requirements,
            work_dir=tmp_path / "work",
            expected_version="1.0.2",
            python_version="3.12",
            public_index=False,
            allow_published_version_check=False,
            run_command=RecordingRunner(),
        )


def test_subprocess_failure_uses_controlled_context_without_hostile_output(tmp_path: Path) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)

    def failing_runner(args: Sequence[object], **kwargs: object) -> CompletedProcess[str]:
        raise CalledProcessError(
            returncode=17,
            cmd=args,
            output="token=stdout-secret",
            stderr="token=stderr-secret",
        )

    with pytest.raises(verifier.InstalledArtifactVerificationError) as excinfo:
        verifier.verify_installed_artifacts(
            wheel=wheel,
            core_requirements=core_requirements,
            tui_requirements=tui_requirements,
            work_dir=tmp_path / "work",
            expected_version="1.0.2",
            python_version="3.12.11",
            public_index=False,
            allow_published_version_check=False,
            run_command=failing_runner,
        )

    message = str(excinfo.value)
    assert "create core pip environment" in message
    assert "exit status 17" in message
    assert "secret" not in message
    assert str(wheel) not in message


def test_subprocess_timeout_uses_controlled_context(tmp_path: Path) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)

    def timeout_runner(args: Sequence[object], **kwargs: object) -> CompletedProcess[str]:
        raise TimeoutExpired(cmd=args, timeout=1, output="secret-output")

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="timed out") as excinfo:
        verifier.verify_installed_artifacts(
            wheel=wheel,
            core_requirements=core_requirements,
            tui_requirements=tui_requirements,
            work_dir=tmp_path / "work",
            expected_version="1.0.2",
            python_version="3.12.11",
            public_index=False,
            allow_published_version_check=False,
            run_command=timeout_runner,
        )

    assert "secret-output" not in str(excinfo.value)


def test_query_evidence_requires_exact_semantic_subset(tmp_path: Path) -> None:
    class WrongQueryRunner(RecordingRunner):
        def __call__(self, args: Sequence[object], **kwargs: Any) -> CompletedProcess[str]:
            completed = super().__call__(args, **kwargs)
            command = [str(part) for part in args]
            if len(command) > 1 and command[1] == "query":
                return CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout=json.dumps({"columns": [], "token": "secret-payload"}),
                    stderr="",
                )
            return completed

    with pytest.raises(verifier.InstalledArtifactVerificationError) as excinfo:
        _verify_local(tmp_path, WrongQueryRunner())

    assert "core query evidence did not match" in str(excinfo.value)
    assert "secret-payload" not in str(excinfo.value)


def test_version_evidence_requires_exact_expected_version(tmp_path: Path) -> None:
    class WrongVersionRunner(RecordingRunner):
        def __call__(self, args: Sequence[object], **kwargs: Any) -> CompletedProcess[str]:
            completed = super().__call__(args, **kwargs)
            command = [str(part) for part in args]
            if command[-1:] == ["--version"]:
                return CompletedProcess(args=command, returncode=0, stdout="1.0.3\n", stderr="")
            return completed

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="version evidence"):
        _verify_local(tmp_path, WrongVersionRunner())


def test_cli_prints_deterministic_json_evidence_without_running_real_commands(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    runner = RecordingRunner()

    exit_code = verifier.main(
        [
            "--wheel",
            str(wheel),
            "--core-requirements",
            str(core_requirements),
            "--tui-requirements",
            str(tui_requirements),
            "--work-dir",
            str(tmp_path / "work"),
            "--expected-version",
            "1.0.2",
            "--python",
            "3.12.11",
        ],
        run_command=runner,
    )

    assert exit_code == 0
    assert (
        capsys.readouterr().out
        == json.dumps(
            {
                "checks": EXPECTED_CHECKS,
                "expected_version": "1.0.2",
                "mode": "local-artifact",
                "python": "3.12.11",
                "schema_version": 1,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    assert runner.calls


def test_cli_public_gate_fails_before_runner_or_work_dir(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = RecordingRunner()

    with pytest.raises(SystemExit) as excinfo:
        verifier.main(
            [
                "--public-index",
                "--work-dir",
                str(tmp_path / "work"),
                "--expected-version",
                "1.0.2",
                "--python",
                "3.12.11",
            ],
            run_command=runner,
        )

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "allow-published-version-check" in captured.err
    assert runner.calls == []
    assert not (tmp_path / "work").exists()
