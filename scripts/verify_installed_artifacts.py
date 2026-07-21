"""Verify installed LocalQL release artifacts in isolated environments."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess, TimeoutExpired

COMMAND_TIMEOUT_SECONDS = 300.0
COPY_CHUNK_SIZE = 1024 * 1024
REQUIRED_PYTHON_VERSION = "3.12.11"
REQUIRED_UV_VERSION = "0.11.28"
PUBLIC_INDEX_URL = "https://pypi.org/simple"
REPO_ROOT = Path(__file__).resolve().parents[1]
INHERITED_ENVIRONMENT_ALLOWLIST = frozenset(
    {
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
)
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


@dataclass(frozen=True, slots=True)
class SnapshottedInput:
    """Isolated immutable input used by every local installation command."""

    path: Path
    filename: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SmokeFormatPaths:
    """Per-format isolated paths for installed-artifact smoke execution."""

    root: Path
    tmp_dir: Path
    uv_cache_dir: Path
    uv_python_install_dir: Path
    pip_core_venv: Path
    pip_tui_venv: Path
    uv_tool_core_dir: Path
    uv_tool_core_bin_dir: Path
    uv_tool_tui_dir: Path
    uv_tool_tui_bin_dir: Path


class InstalledArtifactVerificationError(RuntimeError):
    """Raised when isolated installed-artifact evidence is invalid."""


SMOKE_CHECKS: dict[str, str] = {
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


def tool_bin_executable_path(
    tool_bin_dir: Path,
    executable: str,
    *,
    os_name: str = os.name,
) -> Path:
    """Return an executable path from uv's flat tool bin directory."""

    if os_name == "nt":
        return tool_bin_dir / f"{executable}.exe"
    return tool_bin_dir / executable


def _validate_expected_version(expected_version: str) -> None:
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}", expected_version) is None:
        raise InstalledArtifactVerificationError(
            "expected version must be an exact three-component release version"
        )


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _validate_local_file(path: Path, *, exact_name: str, role: str) -> Path:
    candidate = _absolute_path(path)
    if candidate.name != exact_name:
        raise InstalledArtifactVerificationError(f"{role} must use the exact filename")
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise InstalledArtifactVerificationError(f"{role} must be a readable regular file") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise InstalledArtifactVerificationError(f"{role} must be a regular file, not a symlink")
    if metadata.st_nlink != 1:
        raise InstalledArtifactVerificationError(f"{role} must not be a hardlink")
    return candidate


def _prepare_work_dir(work_dir: Path) -> Path:
    candidate = _absolute_path(work_dir)
    if candidate.is_relative_to(REPO_ROOT):
        raise InstalledArtifactVerificationError(
            "work directory must be outside the repository source tree"
        )
    try:
        existing_metadata = candidate.lstat()
    except FileNotFoundError:
        existing_metadata = None
    except OSError as exc:
        raise InstalledArtifactVerificationError(
            "work directory path could not be inspected"
        ) from exc
    if existing_metadata is not None and stat.S_ISLNK(existing_metadata.st_mode):
        raise InstalledArtifactVerificationError("work directory must not be a symlink")
    if existing_metadata is not None:
        raise InstalledArtifactVerificationError("work directory must not already exist")
    try:
        parent_metadata = candidate.parent.lstat()
    except OSError as exc:
        raise InstalledArtifactVerificationError(
            "work directory requires a real existing parent directory"
        ) from exc
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
        raise InstalledArtifactVerificationError(
            "work directory requires a real existing parent directory"
        )
    try:
        os.mkdir(candidate, mode=0o700)
    except FileExistsError:
        raise InstalledArtifactVerificationError("work directory must not already exist") from None
    except OSError as exc:
        raise InstalledArtifactVerificationError("could not create the work directory") from exc
    return candidate


def _make_isolated_directory(path: Path) -> Path:
    try:
        os.mkdir(path, mode=0o700)
    except OSError as exc:
        raise InstalledArtifactVerificationError(
            "could not create a isolated proof directory"
        ) from exc
    return path


def _sanitized_environment(
    *,
    uv_cache_dir: Path,
    uv_python_install_dir: Path,
    tmp_dir: Path | None = None,
) -> dict[str, str]:
    environment = {
        name: os.environ[name] for name in INHERITED_ENVIRONMENT_ALLOWLIST if name in os.environ
    }
    environment.update(
        {
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_INDEX_URL": PUBLIC_INDEX_URL,
            "PIP_NO_CACHE_DIR": "1",
            "PIP_NO_INPUT": "1",
            "PYTHONNOUSERSITE": "1",
            "UV_CACHE_DIR": str(uv_cache_dir),
            "UV_DEFAULT_INDEX": PUBLIC_INDEX_URL,
            "UV_NO_CONFIG": "1",
            "UV_PYTHON_INSTALL_DIR": str(uv_python_install_dir),
        }
    )
    if tmp_dir is not None:
        environment.update(
            {
                "TEMP": str(tmp_dir),
                "TMP": str(tmp_dir),
                "TMPDIR": str(tmp_dir),
            }
        )
    return environment


def _identity_change_time_ns(metadata: os.stat_result) -> int:
    if os.name == "nt":
        birthtime_ns = getattr(metadata, "st_birthtime_ns", None)
        if isinstance(birthtime_ns, int):
            return birthtime_ns
    return metadata.st_ctime_ns


def _metadata_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        _identity_change_time_ns(metadata),
    )


def _write_all(file_descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(file_descriptor, content[offset:])
        if written <= 0:
            raise OSError("snapshot write made no progress")
        offset += written


def _snapshot_input(source: Path, *, destination_dir: Path, role: str) -> SnapshottedInput:
    destination = destination_dir / source.name
    try:
        path_metadata_before = source.lstat()
    except OSError:
        raise InstalledArtifactVerificationError(f"{role} changed before snapshot") from None
    if stat.S_ISLNK(path_metadata_before.st_mode) or not stat.S_ISREG(path_metadata_before.st_mode):
        raise InstalledArtifactVerificationError(f"{role} must remain a regular file")
    if path_metadata_before.st_nlink != 1:
        raise InstalledArtifactVerificationError(f"{role} must not be a hardlink")

    source_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    source_flags |= getattr(os, "O_NOFOLLOW", 0)
    destination_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        source_descriptor = os.open(source, source_flags)
    except OSError:
        raise InstalledArtifactVerificationError(f"{role} changed before snapshot") from None

    destination_descriptor: int | None = None
    try:
        opened_metadata_before = os.fstat(source_descriptor)
        if _metadata_identity(opened_metadata_before) != _metadata_identity(path_metadata_before):
            raise InstalledArtifactVerificationError(f"{role} changed before snapshot")
        if not stat.S_ISREG(opened_metadata_before.st_mode) or opened_metadata_before.st_nlink != 1:
            raise InstalledArtifactVerificationError(
                f"{role} must remain a single-link regular file"
            )
        try:
            destination_descriptor = os.open(destination, destination_flags, 0o600)
        except OSError:
            raise InstalledArtifactVerificationError(
                f"could not create the isolated {role} snapshot"
            ) from None

        digest = hashlib.sha256()
        copied_size = 0
        try:
            while chunk := os.read(source_descriptor, COPY_CHUNK_SIZE):
                digest.update(chunk)
                _write_all(destination_descriptor, chunk)
                copied_size += len(chunk)
            os.fsync(destination_descriptor)
        except OSError:
            raise InstalledArtifactVerificationError(
                f"could not copy the {role} snapshot"
            ) from None

        opened_metadata_after = os.fstat(source_descriptor)
        try:
            path_metadata_after = source.lstat()
        except OSError:
            raise InstalledArtifactVerificationError(f"{role} changed during snapshot") from None
        initial_identity = _metadata_identity(opened_metadata_before)
        if (
            _metadata_identity(opened_metadata_after) != initial_identity
            or _metadata_identity(path_metadata_after) != initial_identity
        ):
            raise InstalledArtifactVerificationError(f"{role} changed during snapshot")

        destination_metadata = os.fstat(destination_descriptor)
        if (
            not stat.S_ISREG(destination_metadata.st_mode)
            or destination_metadata.st_nlink != 1
            or destination_metadata.st_size != copied_size
        ):
            raise InstalledArtifactVerificationError(f"isolated {role} snapshot was not stable")
    finally:
        if destination_descriptor is not None:
            os.close(destination_descriptor)
        os.close(source_descriptor)

    return SnapshottedInput(
        path=destination,
        filename=source.name,
        sha256=digest.hexdigest(),
    )


def _snapshot_local_inputs(
    *,
    wheel: Path,
    sdist: Path,
    core_requirements: Path,
    tui_requirements: Path,
    work_dir: Path,
) -> dict[str, SnapshottedInput]:
    artifacts_dir = _make_isolated_directory(work_dir / "artifacts")
    inputs_dir = _make_isolated_directory(work_dir / "inputs")
    return {
        "core_requirements": _snapshot_input(
            core_requirements,
            destination_dir=inputs_dir,
            role="core requirements",
        ),
        "tui_requirements": _snapshot_input(
            tui_requirements,
            destination_dir=inputs_dir,
            role="TUI requirements",
        ),
        "sdist": _snapshot_input(sdist, destination_dir=artifacts_dir, role="sdist"),
        "wheel": _snapshot_input(wheel, destination_dir=artifacts_dir, role="wheel"),
    }


def _input_evidence(
    inputs: Mapping[str, SnapshottedInput],
) -> dict[str, dict[str, str]]:
    return {
        role: {"filename": snapshot.filename, "sha256": snapshot.sha256}
        for role, snapshot in inputs.items()
    }


def _format_smoke_paths(work_dir: Path, format_name: str) -> SmokeFormatPaths:
    root = _make_isolated_directory(work_dir / format_name)
    return SmokeFormatPaths(
        root=root,
        tmp_dir=_make_isolated_directory(root / "tmp"),
        uv_cache_dir=_make_isolated_directory(root / "uv-cache"),
        uv_python_install_dir=_make_isolated_directory(root / "uv-python"),
        pip_core_venv=root / "pip-core",
        pip_tui_venv=root / "pip-tui",
        uv_tool_core_dir=root / "uv-tool-core",
        uv_tool_core_bin_dir=root / "uv-tool-core-bin",
        uv_tool_tui_dir=root / "uv-tool-tui",
        uv_tool_tui_bin_dir=root / "uv-tool-tui-bin",
    )


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
        ) from None
    except TimeoutExpired:
        raise InstalledArtifactVerificationError(f"{role} timed out") from None
    except OSError as exc:
        error_number = exc.errno
        if type(error_number) is not int:
            error_identity = "UNKNOWN (errno unavailable)"
        else:
            error_name = errno.errorcode.get(error_number, "UNKNOWN")
            error_identity = f"{error_name} (errno {error_number})"
        raise InstalledArtifactVerificationError(
            f"{role} could not be executed: {error_identity}"
        ) from None
    if completed.returncode != 0:
        raise InstalledArtifactVerificationError(
            f"{role} failed with exit status {completed.returncode}"
        )
    return completed


def _require_uv_identity(completed: CompletedProcess[str]) -> str:
    match = re.fullmatch(r"uv ([^\s]+)(?: .*)?", completed.stdout.strip())
    if match is None or match.group(1) != REQUIRED_UV_VERSION:
        raise InstalledArtifactVerificationError("selected uv identity did not match")
    return f"uv {match.group(1)}"


def _require_python_identity(completed: CompletedProcess[str], *, role: str) -> str:
    observed = completed.stdout.strip() or completed.stderr.strip()
    expected = f"Python {REQUIRED_PYTHON_VERSION}"
    if observed != expected:
        raise InstalledArtifactVerificationError(f"{role} Python identity did not match")
    return observed


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
    artifact: Path | None,
    core_requirements: Path | None,
    tui_requirements: Path | None,
    format_paths: SmokeFormatPaths,
    project_dir: Path,
    expected_version: str,
    python_version: str,
    public_index: bool,
    environment: Mapping[str, str],
    run_command: RunCommand,
) -> dict[str, str]:
    core_venv = format_paths.pip_core_venv
    core_python = environment_executable_path(core_venv, "python")
    core_csvql = environment_executable_path(core_venv, "csvql")
    _run_checked(
        ["uv", "venv", "--python", python_version, "--seed", str(core_venv)],
        role="create core pip environment",
        cwd=project_dir,
        environment=environment,
        run_command=run_command,
    )
    completed = _run_checked(
        [str(core_python), "--version"],
        role="verify core pip Python",
        cwd=project_dir,
        environment=environment,
        run_command=run_command,
    )
    core_python_identity = _require_python_identity(completed, role="core pip")
    if public_index:
        _run_checked(
            [str(core_python), "-m", "pip", "install", f"localql=={expected_version}"],
            role="install published core package",
            cwd=project_dir,
            environment=environment,
            run_command=run_command,
        )
    else:
        assert artifact is not None
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
            [str(core_python), "-m", "pip", "install", "--no-deps", str(artifact)],
            role="install local core artifact",
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

    tui_venv = format_paths.pip_tui_venv
    tui_python = environment_executable_path(tui_venv, "python")
    tui_csvql = environment_executable_path(tui_venv, "csvql")
    _run_checked(
        ["uv", "venv", "--python", python_version, "--seed", str(tui_venv)],
        role="create TUI pip environment",
        cwd=project_dir,
        environment=environment,
        run_command=run_command,
    )
    completed = _run_checked(
        [str(tui_python), "--version"],
        role="verify TUI pip Python",
        cwd=project_dir,
        environment=environment,
        run_command=run_command,
    )
    tui_python_identity = _require_python_identity(completed, role="TUI pip")
    if public_index:
        _run_checked(
            [str(tui_python), "-m", "pip", "install", f"localql[tui]=={expected_version}"],
            role="install published TUI package",
            cwd=project_dir,
            environment=environment,
            run_command=run_command,
        )
    else:
        assert artifact is not None
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
        wheel_requirement = f"localql[tui] @ {artifact.as_uri()}"
        _run_checked(
            [str(tui_python), "-m", "pip", "install", "--no-deps", wheel_requirement],
            role="install local TUI artifact",
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
    return {
        "pip_core_python": core_python_identity,
        "pip_tui_python": tui_python_identity,
    }


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
    artifact: Path | None,
    core_requirements: Path | None,
    tui_requirements: Path | None,
    format_paths: SmokeFormatPaths,
    project_dir: Path,
    expected_version: str,
    python_version: str,
    public_index: bool,
    environment: Mapping[str, str],
    run_command: RunCommand,
) -> dict[str, str]:
    core_tool_dir = format_paths.uv_tool_core_dir
    core_bin_dir = format_paths.uv_tool_core_bin_dir
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
        assert artifact is not None
        assert core_requirements is not None
        core_install_command = [
            "uv",
            "tool",
            "install",
            "--python",
            python_version,
            "--with-requirements",
            str(core_requirements),
            str(artifact),
        ]
    _run_checked(
        core_install_command,
        role="install core uv tool",
        cwd=project_dir,
        environment=core_environment,
        run_command=run_command,
    )
    core_python = environment_executable_path(core_tool_dir / "localql", "python")
    completed = _run_checked(
        [str(core_python), "--version"],
        role="verify core uv-tool Python",
        cwd=project_dir,
        environment=core_environment,
        run_command=run_command,
    )
    core_python_identity = _require_python_identity(completed, role="core uv-tool")
    core_csvql = tool_bin_executable_path(core_bin_dir, "csvql")
    completed = _run_checked(
        [str(core_csvql), "--version"],
        role="run core uv-tool version smoke",
        cwd=project_dir,
        environment=core_environment,
        run_command=run_command,
    )
    _require_version(completed, expected_version=expected_version, role="core uv-tool")

    tui_tool_dir = format_paths.uv_tool_tui_dir
    tui_bin_dir = format_paths.uv_tool_tui_bin_dir
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
        assert artifact is not None
        assert tui_requirements is not None
        wheel_requirement = f"localql[tui] @ {artifact.as_uri()}"
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
    tui_python = environment_executable_path(tui_tool_dir / "localql", "python")
    completed = _run_checked(
        [str(tui_python), "--version"],
        role="verify TUI uv-tool Python",
        cwd=project_dir,
        environment=tui_environment,
        run_command=run_command,
    )
    tui_python_identity = _require_python_identity(completed, role="TUI uv-tool")
    tui_csvql = tool_bin_executable_path(tui_bin_dir, "csvql")
    completed = _run_checked(
        [str(tui_csvql), "--version"],
        role="run TUI uv-tool version smoke",
        cwd=project_dir,
        environment=tui_environment,
        run_command=run_command,
    )
    _require_version(completed, expected_version=expected_version, role="TUI uv-tool")
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
    return {
        "uv_tool_core_python": core_python_identity,
        "uv_tool_tui_python": tui_python_identity,
    }


def verify_installed_artifacts(
    *,
    wheel: Path | None,
    sdist: Path | None,
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
        if any(path is not None for path in (wheel, sdist, core_requirements, tui_requirements)):
            raise InstalledArtifactVerificationError(
                "public-index mode rejects local artifact inputs"
            )
        resolved_wheel = None
        resolved_sdist = None
        resolved_core_requirements = None
        resolved_tui_requirements = None
    else:
        if allow_published_version_check:
            raise InstalledArtifactVerificationError(
                "--allow-published-version-check is valid only with --public-index"
            )
        if wheel is None or sdist is None or core_requirements is None or tui_requirements is None:
            raise InstalledArtifactVerificationError(
                "local mode requires wheel, sdist, core requirements, and TUI requirements"
            )
        resolved_wheel = _validate_local_file(
            wheel,
            exact_name=f"localql-{expected_version}-py3-none-any.whl",
            role="wheel",
        )
        resolved_sdist = _validate_local_file(
            sdist,
            exact_name=f"localql-{expected_version}.tar.gz",
            role="sdist",
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
    if public_index:
        snapshotted_inputs: dict[str, SnapshottedInput] = {}
    else:
        assert resolved_wheel is not None
        assert resolved_sdist is not None
        assert resolved_core_requirements is not None
        assert resolved_tui_requirements is not None
        snapshotted_inputs = _snapshot_local_inputs(
            wheel=resolved_wheel,
            sdist=resolved_sdist,
            core_requirements=resolved_core_requirements,
            tui_requirements=resolved_tui_requirements,
            work_dir=resolved_work_dir,
        )
        resolved_wheel = snapshotted_inputs["wheel"].path
        resolved_sdist = snapshotted_inputs["sdist"].path
        resolved_core_requirements = snapshotted_inputs["core_requirements"].path
        resolved_tui_requirements = snapshotted_inputs["tui_requirements"].path
    trusted_python = str(Path(sys.executable).resolve())

    if public_index:
        format_paths = _format_smoke_paths(resolved_work_dir, "public-index")
        environment = _sanitized_environment(
            uv_cache_dir=format_paths.uv_cache_dir,
            uv_python_install_dir=format_paths.uv_python_install_dir,
            tmp_dir=format_paths.tmp_dir,
        )
        with tempfile.TemporaryDirectory(prefix="project-", dir=format_paths.root) as project_text:
            project_dir = Path(project_text).resolve()
            if project_dir.is_relative_to(REPO_ROOT):
                raise InstalledArtifactVerificationError(
                    "temporary smoke project must be outside the repository source tree"
                )
            _write_smoke_project(project_dir)
            completed = _run_checked(
                ["uv", "--version"],
                role="verify selected uv",
                cwd=project_dir,
                environment=environment,
                run_command=run_command,
            )
            identities = {"uv": _require_uv_identity(completed)}
            identities.update(
                _run_pip_smokes(
                    artifact=None,
                    core_requirements=None,
                    tui_requirements=None,
                    format_paths=format_paths,
                    project_dir=project_dir,
                    expected_version=expected_version,
                    python_version=python_version,
                    public_index=True,
                    environment=environment,
                    run_command=run_command,
                )
            )
            identities.update(
                _run_uv_tool_smokes(
                    artifact=None,
                    core_requirements=None,
                    tui_requirements=None,
                    format_paths=format_paths,
                    project_dir=project_dir,
                    expected_version=expected_version,
                    python_version=python_version,
                    public_index=True,
                    environment=environment,
                    run_command=run_command,
                )
            )
        return {
            "assurance": (
                "public-index name-resolution check; not exact supplied-artifact evidence"
            ),
            "expected_version": expected_version,
            "identities": {"public_index": identities},
            "inputs": {},
            "mode": "public-index",
            "python": python_version,
            "public_index": {"checks": dict(SMOKE_CHECKS)},
            "schema_version": 2,
        }

    assert resolved_wheel is not None
    assert resolved_sdist is not None
    assert resolved_core_requirements is not None
    assert resolved_tui_requirements is not None
    preflight_paths = _format_smoke_paths(resolved_work_dir, "preflight")
    preflight_environment = _sanitized_environment(
        uv_cache_dir=preflight_paths.uv_cache_dir,
        uv_python_install_dir=preflight_paths.uv_python_install_dir,
        tmp_dir=preflight_paths.tmp_dir,
    )
    artifact_dir = resolved_wheel.parent
    _run_checked(
        [
            trusted_python,
            str(REPO_ROOT / "scripts" / "audit_package_contents.py"),
            str(artifact_dir),
            "--expected-version",
            expected_version,
        ],
        role="audit local artifact pair",
        cwd=resolved_work_dir,
        environment=preflight_environment,
        run_command=run_command,
    )
    _run_checked(
        [
            trusted_python,
            str(REPO_ROOT / "scripts" / "verify_release_artifacts.py"),
            "inspect",
            str(artifact_dir),
            "--expected-version",
            expected_version,
        ],
        role="inspect local artifact pair",
        cwd=resolved_work_dir,
        environment=preflight_environment,
        run_command=run_command,
    )

    identities: dict[str, dict[str, str]] = {}
    for format_name, artifact in (
        ("wheel", resolved_wheel),
        ("sdist", resolved_sdist),
    ):
        format_paths = _format_smoke_paths(resolved_work_dir, format_name)
        environment = _sanitized_environment(
            uv_cache_dir=format_paths.uv_cache_dir,
            uv_python_install_dir=format_paths.uv_python_install_dir,
            tmp_dir=format_paths.tmp_dir,
        )
        with tempfile.TemporaryDirectory(prefix="project-", dir=format_paths.root) as project_text:
            project_dir = Path(project_text).resolve()
            if project_dir.is_relative_to(REPO_ROOT):
                raise InstalledArtifactVerificationError(
                    "temporary smoke project must be outside the repository source tree"
                )
            _write_smoke_project(project_dir)
            completed = _run_checked(
                ["uv", "--version"],
                role=f"verify selected uv for {format_name}",
                cwd=project_dir,
                environment=environment,
                run_command=run_command,
            )
            smoke_identities = {"uv": _require_uv_identity(completed)}
            smoke_identities.update(
                _run_pip_smokes(
                    artifact=artifact,
                    core_requirements=resolved_core_requirements,
                    tui_requirements=resolved_tui_requirements,
                    format_paths=format_paths,
                    project_dir=project_dir,
                    expected_version=expected_version,
                    python_version=python_version,
                    public_index=False,
                    environment=environment,
                    run_command=run_command,
                )
            )
            smoke_identities.update(
                _run_uv_tool_smokes(
                    artifact=artifact,
                    core_requirements=resolved_core_requirements,
                    tui_requirements=resolved_tui_requirements,
                    format_paths=format_paths,
                    project_dir=project_dir,
                    expected_version=expected_version,
                    python_version=python_version,
                    public_index=False,
                    environment=environment,
                    run_command=run_command,
                )
            )
        identities[format_name] = smoke_identities

    return {
        "assurance": {
            "sdist": "current-index consumer install; not reproducible build-custody evidence",
            "wheel": "exact supplied artifact install",
        },
        "checks": {
            "preflight": {
                "package_contents": "passed",
                "release_pair_inspection": "passed",
            },
            "sdist": dict(SMOKE_CHECKS),
            "wheel": dict(SMOKE_CHECKS),
        },
        "expected_version": expected_version,
        "identities": identities,
        "inputs": _input_evidence(snapshotted_inputs),
        "mode": "local-artifacts",
        "python": python_version,
        "schema_version": 2,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify LocalQL through isolated pip and uv-tool installations."
    )
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sdist", type=Path)
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
            sdist=args.sdist,
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
