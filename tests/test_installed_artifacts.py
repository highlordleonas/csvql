"""Contract tests for installed release artifact verification."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import sys
import textwrap
import traceback
from collections.abc import Mapping, Sequence
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess, TimeoutExpired
from types import SimpleNamespace
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
EXPECTED_UV_IDENTITY = "uv 0.11.28"
EXPECTED_PYTHON_IDENTITY = "Python 3.12.11"
EXPECTED_API_SMOKE = textwrap.dedent(
    """
    from csvql import CSVQLSession

    session = CSVQLSession.from_config(".")
    result = session.query("SELECT COUNT(*) AS order_count FROM orders")
    assert result.columns == ("order_count",)
    assert result.rows == ((3,),)
    """
).strip()
EXPECTED_CORE_WITHOUT_TEXTUAL_SMOKE = textwrap.dedent(
    """
    from importlib.util import find_spec

    assert find_spec("textual") is None
    """
).strip()
EXPECTED_TUI_IMPORT_SMOKE = textwrap.dedent(
    """
    import csvql.tui_app
    import textual
    """
).strip()
EXPECTED_SMOKE_SNIPPETS = {
    EXPECTED_API_SMOKE,
    EXPECTED_CORE_WITHOUT_TEXTUAL_SMOKE,
    EXPECTED_TUI_IMPORT_SMOKE,
}
EXPECTED_INHERITED_ENVIRONMENT_NAMES = {
    "COMSPEC",
    "CURL_CA_BUNDLE",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "PATHEXT",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "TZ",
    "USERPROFILE",
    "WINDIR",
}


def assert_posix_isolated_mode(mode: int, *, platform_name: str = os.name) -> None:
    if platform_name != "nt":
        assert mode & 0o777 == 0o600


def test_windows_metadata_identity_uses_birthtime_instead_of_deprecated_ctime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = {
        "st_dev": 1,
        "st_ino": 2,
        "st_mode": 0o100600,
        "st_nlink": 1,
        "st_size": 3,
        "st_mtime_ns": 4,
        "st_birthtime_ns": 5,
    }
    path_metadata = SimpleNamespace(**shared, st_ctime_ns=6)
    descriptor_metadata = SimpleNamespace(**shared, st_ctime_ns=7)
    monkeypatch.setattr(verifier.os, "name", "nt")

    assert verifier._metadata_identity(path_metadata) == verifier._metadata_identity(
        descriptor_metadata
    )


def test_snapshot_mode_check_does_not_apply_posix_mask_on_windows() -> None:
    assert_posix_isolated_mode(0o100666, platform_name="nt")

    with pytest.raises(AssertionError):
        assert_posix_isolated_mode(0o100666, platform_name="posix")


EXPECTED_EXPLICIT_ENVIRONMENT = {
    "PIP_CONFIG_FILE": os.devnull,
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_INDEX_URL": "https://pypi.org/simple",
    "PIP_NO_CACHE_DIR": "1",
    "PIP_NO_INPUT": "1",
    "PYTHONNOUSERSITE": "1",
    "UV_DEFAULT_INDEX": "https://pypi.org/simple",
    "UV_NO_CONFIG": "1",
}
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
        elif command == ["uv", "--version"]:
            stdout = f"{EXPECTED_UV_IDENTITY} (unit-test build)\n"
        elif command[-1:] == ["--version"] and Path(command[0]).stem == "python":
            stdout = f"{EXPECTED_PYTHON_IDENTITY}\n"
        elif command[-1:] == ["--version"]:
            stdout = "1.0.2\n"
        elif command[-2:] == ["menu", "--help"]:
            stdout = "Usage: csvql menu [OPTIONS]\n"
        elif len(command) == 3 and command[1] == "-c":
            assert command[2] in EXPECTED_SMOKE_SNIPPETS, "weakened smoke snippet"
            stdout = ""
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_identities() -> dict[str, str]:
    return {
        "pip_core_python": EXPECTED_PYTHON_IDENTITY,
        "pip_tui_python": EXPECTED_PYTHON_IDENTITY,
        "uv": EXPECTED_UV_IDENTITY,
        "uv_tool_core_python": EXPECTED_PYTHON_IDENTITY,
        "uv_tool_tui_python": EXPECTED_PYTHON_IDENTITY,
    }


def _expected_input_evidence(
    wheel: Path,
    core_requirements: Path,
    tui_requirements: Path,
) -> dict[str, dict[str, str]]:
    return {
        "core_requirements": {
            "filename": "core-requirements.txt",
            "sha256": _sha256(core_requirements),
        },
        "tui_requirements": {
            "filename": "tui-requirements.txt",
            "sha256": _sha256(tui_requirements),
        },
        "wheel": {
            "filename": "localql-1.0.2-py3-none-any.whl",
            "sha256": _sha256(wheel),
        },
    }


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


@pytest.mark.parametrize(
    ("os_name", "expected"),
    [
        ("posix", Path("tool-bin") / "csvql"),
        ("nt", Path("tool-bin") / "csvql.exe"),
    ],
)
def test_tool_bin_executable_path_uses_native_layout(
    os_name: str,
    expected: Path,
) -> None:
    assert verifier.tool_bin_executable_path(Path("tool-bin"), "csvql", os_name=os_name) == expected


def test_local_mode_composes_exact_pip_and_uv_tool_commands(tmp_path: Path) -> None:
    runner = RecordingRunner()
    evidence, work_dir = _verify_local(tmp_path, runner)
    original_wheel, original_core_requirements, original_tui_requirements = (
        (tmp_path / "inputs" / name).resolve()
        for name in (
            "localql-1.0.2-py3-none-any.whl",
            "core-requirements.txt",
            "tui-requirements.txt",
        )
    )
    wheel = work_dir / "inputs" / original_wheel.name
    core_requirements = work_dir / "inputs" / original_core_requirements.name
    tui_requirements = work_dir / "inputs" / original_tui_requirements.name
    core_venv = work_dir / "pip-core"
    tui_venv = work_dir / "pip-tui"
    core_python = verifier.environment_executable_path(core_venv, "python")
    tui_python = verifier.environment_executable_path(tui_venv, "python")
    core_csvql = verifier.environment_executable_path(core_venv, "csvql")
    tui_csvql = verifier.environment_executable_path(tui_venv, "csvql")
    tool_core_csvql = verifier.tool_bin_executable_path(
        work_dir / "uv-tool-core-bin",
        "csvql",
    )
    wheel_requirement = f"localql[tui] @ {wheel.as_uri()}"
    commands = [call["args"] for call in runner.calls]

    assert commands[:6] == [
        ["uv", "--version"],
        ["uv", "venv", "--python", "3.12.11", "--seed", str(core_venv)],
        [str(core_python), "--version"],
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
    assert [str(tui_python), "--version"] in commands
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
    assert [str(tool_core_csvql), "--version"] in commands
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
    assert all(
        str(original_path) not in part
        for command in commands
        for part in command
        for original_path in (
            original_wheel,
            original_core_requirements,
            original_tui_requirements,
        )
    )
    assert evidence == {
        "checks": EXPECTED_CHECKS,
        "expected_version": "1.0.2",
        "identities": _expected_identities(),
        "inputs": _expected_input_evidence(
            original_wheel,
            original_core_requirements,
            original_tui_requirements,
        ),
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
    assert [str(core_python), "-c", EXPECTED_API_SMOKE] in commands
    assert [str(core_python), "-c", EXPECTED_CORE_WITHOUT_TEXTUAL_SMOKE] in commands
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
    tool_tui_csvql = verifier.tool_bin_executable_path(
        work_dir / "uv-tool-tui-bin",
        "csvql",
    )
    commands = [call["args"] for call in runner.calls]

    assert [str(tui_python), "-c", EXPECTED_TUI_IMPORT_SMOKE] in commands
    assert [str(tui_csvql), "menu", "--help"] in commands
    assert [str(tool_tui_python), "-c", EXPECTED_TUI_IMPORT_SMOKE] in commands
    assert [str(tool_tui_csvql), "--version"] in commands
    assert [str(tool_tui_csvql), "menu", "--help"] in commands


@pytest.mark.parametrize(
    "production_constant",
    ["API_SMOKE", "CORE_WITHOUT_TEXTUAL_SMOKE", "TUI_IMPORT_SMOKE"],
)
def test_weakened_production_smoke_cannot_yield_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    production_constant: str,
) -> None:
    monkeypatch.setattr(verifier, production_constant, "pass")

    with pytest.raises(AssertionError, match="weakened smoke snippet"):
        _verify_local(tmp_path, RecordingRunner())


def test_subprocess_boundary_is_sanitized_bounded_and_outside_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile_environment = {
        "CONDA_PREFIX": "/hostile/conda",
        "PDM_PROJECT_ROOT": "/hostile/pdm",
        "PIP_BUILD_CONSTRAINT": "/hostile/pip-build-constraints.txt",
        "PIP_CACHE_DIR": "/hostile/pip-cache",
        "PIP_CONFIG_FILE": "/hostile/pip.ini",
        "PIP_CONSTRAINT": "/hostile/pip-constraints.txt",
        "PIP_EXTRA_INDEX_URL": "https://hostile.example/simple",
        "PIP_FIND_LINKS": "/hostile/wheels",
        "PIP_INDEX_URL": "https://hostile.example/simple",
        "PIP_NO_INDEX": "1",
        "PIP_REQUIREMENT": "/hostile/pip-requirements.txt",
        "PIP_TRUSTED_HOST": "hostile.example",
        "POETRY_ACTIVE": "1",
        "PYTHONHASHSEED": "hostile",
        "PYTHONHOME": "/hostile/python-home",
        "PYTHONINSPECT": "1",
        "PYTHONPATH": str(REPO_ROOT / "src"),
        "PYTHONSAFEPATH": "0",
        "PYTHONSTARTUP": "/hostile/startup.py",
        "PYTHONUSERBASE": "/hostile/user-base",
        "PYTHONWARNINGS": "ignore",
        "UV_BUILD_CONSTRAINT": "/hostile/uv-build-constraints.txt",
        "UV_CACHE_DIR": "/hostile/uv-cache",
        "UV_CONFIG_FILE": "/hostile/uv.toml",
        "UV_CONSTRAINT": "/hostile/uv-constraints.txt",
        "UV_DEFAULT_INDEX": "https://hostile.example/simple",
        "UV_EXCLUDE": "/hostile/uv-excludes.txt",
        "UV_EXTRA_INDEX_URL": "https://hostile-extra.example/simple",
        "UV_FIND_LINKS": "/hostile/uv-wheels",
        "UV_INDEX": "https://hostile-priority.example/simple",
        "UV_INDEX_URL": "https://hostile.example/simple",
        "UV_NO_INDEX": "1",
        "UV_OFFLINE": "1",
        "UV_OVERRIDE": "/hostile/uv-overrides.txt",
        "UV_PROJECT": "/hostile/project",
        "UV_PYTHON": "/hostile/python",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_PYTHON_INSTALL_DIR": "/hostile/python-install",
        "UV_TOOL_BIN_DIR": "/hostile/default-bin",
        "UV_TOOL_DIR": "/hostile/default-tools",
        "UV_WORKING_DIR": "/hostile/working-dir",
        "VIRTUAL_ENV": "/hostile/venv",
    }
    for name, value in hostile_environment.items():
        monkeypatch.setenv(name, value)
    runner = RecordingRunner()
    _, work_dir = _verify_local(tmp_path, runner)

    for call in runner.calls:
        assert call["check"] is True
        assert call["capture_output"] is True
        assert call["text"] is True
        assert call["shell"] is False
        assert call["timeout"] == verifier.COMMAND_TIMEOUT_SECONDS
        environment = call["env"]
        for name, hostile_value in hostile_environment.items():
            if name in EXPECTED_EXPLICIT_ENVIRONMENT or name in {
                "UV_CACHE_DIR",
                "UV_PYTHON_INSTALL_DIR",
            }:
                assert environment[name] != hostile_value
            elif name not in {"UV_TOOL_DIR", "UV_TOOL_BIN_DIR"}:
                assert name not in environment
        assert environment | EXPECTED_EXPLICIT_ENVIRONMENT == environment
        assert environment["UV_CACHE_DIR"] == str(work_dir / "uv-cache")
        assert environment["UV_PYTHON_INSTALL_DIR"] == str(work_dir / "uv-python")
        assert set(environment) <= (
            EXPECTED_INHERITED_ENVIRONMENT_NAMES
            | set(EXPECTED_EXPLICIT_ENVIRONMENT)
            | {
                "UV_CACHE_DIR",
                "UV_PYTHON_INSTALL_DIR",
                "UV_TOOL_DIR",
                "UV_TOOL_BIN_DIR",
            }
        )
        assert not call["cwd"].is_relative_to(REPO_ROOT)

    assert (work_dir / "uv-cache").is_dir()
    assert (work_dir / "uv-python").is_dir()

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
    assert evidence == {
        "checks": EXPECTED_CHECKS,
        "expected_version": "1.0.2",
        "identities": _expected_identities(),
        "inputs": {},
        "mode": "public-index",
        "python": "3.12.11",
        "schema_version": 1,
    }


def test_selected_uv_and_every_installed_python_identity_are_exact(tmp_path: Path) -> None:
    runner = RecordingRunner()
    _, work_dir = _verify_local(tmp_path, runner)
    commands = [call["args"] for call in runner.calls]
    expected_python_commands = [
        [str(verifier.environment_executable_path(work_dir / "pip-core", "python")), "--version"],
        [str(verifier.environment_executable_path(work_dir / "pip-tui", "python")), "--version"],
        [
            str(
                verifier.environment_executable_path(
                    work_dir / "uv-tool-core" / "localql",
                    "python",
                )
            ),
            "--version",
        ],
        [
            str(
                verifier.environment_executable_path(
                    work_dir / "uv-tool-tui" / "localql",
                    "python",
                )
            ),
            "--version",
        ],
    ]

    assert commands[0] == ["uv", "--version"]
    assert all(command in commands for command in expected_python_commands)


def test_wrong_selected_uv_identity_fails_closed(tmp_path: Path) -> None:
    class WrongUvRunner(RecordingRunner):
        def __call__(self, args: Sequence[object], **kwargs: Any) -> CompletedProcess[str]:
            completed = super().__call__(args, **kwargs)
            command = [str(part) for part in args]
            if command == ["uv", "--version"]:
                return CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout="uv 0.11.27 (hostile build)\n",
                    stderr="",
                )
            return completed

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="uv identity"):
        _verify_local(tmp_path, WrongUvRunner())


def test_wrong_installed_python_identity_fails_closed(tmp_path: Path) -> None:
    class WrongPythonRunner(RecordingRunner):
        def __call__(self, args: Sequence[object], **kwargs: Any) -> CompletedProcess[str]:
            completed = super().__call__(args, **kwargs)
            command = [str(part) for part in args]
            if command[-1:] == ["--version"] and Path(command[0]).stem == "python":
                return CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout="Python 3.12.10\n",
                    stderr="",
                )
            return completed

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="Python identity"):
        _verify_local(tmp_path, WrongPythonRunner())


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


@pytest.mark.parametrize("role", ["wheel", "core", "tui"])
def test_local_mode_rejects_symlinked_input(tmp_path: Path, role: str) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    values = {"wheel": wheel, "core": core_requirements, "tui": tui_requirements}
    linked_input = tmp_path / values[role].name
    try:
        linked_input.symlink_to(values[role])
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")
    values[role] = linked_input

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="regular file"):
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


@pytest.mark.parametrize("role", ["wheel", "core", "tui"])
def test_local_mode_rejects_hardlinked_input(tmp_path: Path, role: str) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    values = {"wheel": wheel, "core": core_requirements, "tui": tui_requirements}
    linked_dir = tmp_path / "hardlinks"
    linked_dir.mkdir()
    linked_input = linked_dir / values[role].name
    try:
        os.link(values[role], linked_input)
    except OSError:
        pytest.skip("hardlinks are unavailable on this platform")
    values[role] = linked_input

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="hardlink"):
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


@pytest.mark.parametrize("role", ["wheel", "core", "tui"])
def test_local_mode_rejects_nonregular_input(tmp_path: Path, role: str) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    values = {"wheel": wheel, "core": core_requirements, "tui": tui_requirements}
    nonregular_root = tmp_path / "nonregular"
    nonregular_root.mkdir()
    nonregular_input = nonregular_root / values[role].name
    nonregular_input.mkdir()
    values[role] = nonregular_input

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="regular file"):
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


@pytest.mark.parametrize("role", ["wheel", "core", "tui"])
def test_source_replacement_between_lstat_and_open_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    values = {"wheel": wheel, "core": core_requirements, "tui": tui_requirements}
    source = values[role]
    original_open = os.open
    replaced = False

    def replacing_open(path: object, flags: int, mode: int = 0o777, **kwargs: object) -> int:
        nonlocal replaced
        if not replaced and Path(path) == source:
            replaced = True
            source.unlink()
            source.write_bytes(b"replacement after lstat")
        return original_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(verifier.os, "open", replacing_open)

    with pytest.raises(
        verifier.InstalledArtifactVerificationError, match="changed before snapshot"
    ):
        verifier.verify_installed_artifacts(
            wheel=wheel,
            core_requirements=core_requirements,
            tui_requirements=tui_requirements,
            work_dir=tmp_path / "work",
            expected_version="1.0.2",
            python_version="3.12.11",
            public_index=False,
            allow_published_version_check=False,
            run_command=RecordingRunner(),
        )

    assert replaced is True


@pytest.mark.parametrize("role", ["wheel", "core", "tui"])
def test_source_mutation_during_snapshot_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    values = {"wheel": wheel, "core": core_requirements, "tui": tui_requirements}
    source = values[role]
    source_identity = (source.stat().st_dev, source.stat().st_ino)
    original_read = os.read
    mutated = False

    def mutating_read(fd: int, size: int) -> bytes:
        nonlocal mutated
        chunk = original_read(fd, size)
        opened_metadata = os.fstat(fd)
        if (
            chunk
            and not mutated
            and (opened_metadata.st_dev, opened_metadata.st_ino) == source_identity
        ):
            mutated = True
            with source.open("ab") as source_file:
                source_file.write(b"mutation during snapshot")
        return chunk

    monkeypatch.setattr(verifier.os, "read", mutating_read)

    with pytest.raises(
        verifier.InstalledArtifactVerificationError, match="changed during snapshot"
    ):
        verifier.verify_installed_artifacts(
            wheel=wheel,
            core_requirements=core_requirements,
            tui_requirements=tui_requirements,
            work_dir=tmp_path / "work",
            expected_version="1.0.2",
            python_version="3.12.11",
            public_index=False,
            allow_published_version_check=False,
            run_command=RecordingRunner(),
        )

    assert mutated is True


def test_snapshots_are_regular_single_link_files_with_posix_isolated_mode(tmp_path: Path) -> None:
    runner = RecordingRunner()
    _, work_dir = _verify_local(tmp_path, runner)

    for snapshot in (work_dir / "inputs").iterdir():
        metadata = snapshot.lstat()
        assert snapshot.is_file()
        assert not snapshot.is_symlink()
        assert metadata.st_nlink == 1
        assert_posix_isolated_mode(metadata.st_mode)


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


def test_work_dir_leaf_symlink_is_rejected_without_creating_target(tmp_path: Path) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    target = tmp_path / "symlink-target"
    work_dir = tmp_path / "work"
    try:
        work_dir.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="symlink"):
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

    assert work_dir.is_symlink()
    assert not target.exists()


def test_work_dir_parent_must_not_be_a_symlink(tmp_path: Path) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(verifier.InstalledArtifactVerificationError, match="real existing parent"):
        verifier.verify_installed_artifacts(
            wheel=wheel,
            core_requirements=core_requirements,
            tui_requirements=tui_requirements,
            work_dir=linked_parent / "work",
            expected_version="1.0.2",
            python_version="3.12.11",
            public_index=False,
            allow_published_version_check=False,
            run_command=RecordingRunner(),
        )

    assert not (real_parent / "work").exists()


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
            cmd=["uv", "--config-file", "/secret/config/path"],
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
    assert "verify selected uv" in message
    assert "exit status 17" in message
    assert "secret" not in message
    assert str(wheel) not in message
    rendered_traceback = "".join(traceback.format_exception(excinfo.value))
    assert "/secret/config/path" not in rendered_traceback
    assert "stdout-secret" not in rendered_traceback
    assert "stderr-secret" not in rendered_traceback
    assert excinfo.value.__suppress_context__ is True


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
    rendered_traceback = "".join(traceback.format_exception(excinfo.value))
    assert "secret-output" not in rendered_traceback
    assert excinfo.value.__suppress_context__ is True


def test_subprocess_os_error_preserves_safe_errno_without_hostile_context(
    tmp_path: Path,
) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)

    def os_error_runner(args: Sequence[object], **kwargs: object) -> CompletedProcess[str]:
        raise OSError(
            errno.EAGAIN,
            "token=secret-spawn-detail",
            "/secret/executable/path",
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
            run_command=os_error_runner,
        )

    message = str(excinfo.value)
    assert "verify selected uv" in message
    assert f"EAGAIN (errno {errno.EAGAIN})" in message
    assert "secret" not in message
    rendered_traceback = "".join(traceback.format_exception(excinfo.value))
    assert "/secret/executable/path" not in rendered_traceback
    assert "secret-spawn-detail" not in rendered_traceback
    assert excinfo.value.__suppress_context__ is True


def test_subprocess_os_error_rejects_hostile_non_numeric_errno(tmp_path: Path) -> None:
    wheel, core_requirements, tui_requirements = _write_local_inputs(tmp_path)

    def os_error_runner(args: Sequence[object], **kwargs: object) -> CompletedProcess[str]:
        raise OSError(
            "token=secret-errno",
            "token=secret-spawn-detail",
            "/secret/executable/path",
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
            run_command=os_error_runner,
        )

    message = str(excinfo.value)
    assert "verify selected uv" in message
    assert "UNKNOWN (errno unavailable)" in message
    assert "secret" not in message
    rendered_traceback = "".join(traceback.format_exception(excinfo.value))
    assert "/secret/executable/path" not in rendered_traceback
    assert "secret-errno" not in rendered_traceback
    assert "secret-spawn-detail" not in rendered_traceback
    assert excinfo.value.__suppress_context__ is True


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
            if (
                command[-1:] == ["--version"]
                and command[0] != "uv"
                and Path(command[0]).stem != "python"
            ):
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
                "identities": _expected_identities(),
                "inputs": _expected_input_evidence(
                    wheel,
                    core_requirements,
                    tui_requirements,
                ),
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
