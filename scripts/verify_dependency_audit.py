"""Collect locked core and TUI dependency-audit evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess, TimeoutExpired

from packaging.markers import UndefinedComparison, UndefinedEnvironmentName, default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

AUDIT_TOOL = "pip-audit==2.10.1"
COMMAND_TIMEOUT_SECONDS = 300.0
PACKAGING_DISTRIBUTION = "packaging"
REQUIRED_PACKAGING_VERSION = "26.2"
REQUIREMENTS_PARSER = f"{PACKAGING_DISTRIBUTION}=={REQUIRED_PACKAGING_VERSION}"
REQUIRED_PYTHON_VERSION = "3.12.11"
REPO_ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR_RELATIVE_IO = os.name == "posix"
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
COMMAND_ROLES = (
    "export locked core requirements",
    "export locked TUI requirements",
    "audit locked core requirements",
    "audit locked TUI requirements",
)
GENERATED_FILENAMES = (
    "core-requirements.txt",
    "tui-requirements.txt",
    "core-pip-audit.json",
    "tui-pip-audit.json",
)
HASH_OPTION_PATTERN = re.compile(r"(?<!\S)--hash=([^\s]+)")
SHA256_HASH_PATTERN = re.compile(r"sha256:[0-9a-fA-F]{64}")

RunCommand = Callable[..., CompletedProcess[str]]
Clock = Callable[[], datetime]
PathIdentity = tuple[int, int, int, int, int, int, int]
DirectoryIdentity = tuple[int, int, int]


class DependencyAuditError(RuntimeError):
    """Raised when dependency-audit evidence cannot be trusted."""


@dataclass(frozen=True, slots=True)
class PreparedEvidenceDirectory:
    """Exclusive evidence directory with optional POSIX-held descriptors."""

    path: Path
    parent_descriptor: int | None
    evidence_descriptor: int | None
    parent_identity: DirectoryIdentity
    evidence_identity: DirectoryIdentity
    path_identities: tuple[tuple[Path, DirectoryIdentity], ...]


@dataclass(frozen=True, slots=True)
class FrozenLockSnapshot:
    """Identity and digest of the exact frozen lock used by every command."""

    path: Path
    identity: PathIdentity
    sha256: str


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    """Digests that must still match immediately before manifest publication."""

    digests: tuple[tuple[str, str], ...]
    lock: FrozenLockSnapshot


@dataclass(frozen=True, slots=True)
class CommandCapture:
    """Captured output from one named command boundary."""

    role: str
    stdout: str
    stderr: str


def build_commands(evidence_dir: Path) -> tuple[tuple[str, ...], ...]:
    """Build the exact frozen export and pinned dependency-audit commands."""

    core_path = evidence_dir / "core-requirements.txt"
    tui_path = evidence_dir / "tui-requirements.txt"
    core_output = evidence_dir / "core-pip-audit.json"
    tui_output = evidence_dir / "tui-pip-audit.json"
    return (
        (
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--format",
            "requirements.txt",
            "--output-file",
            str(core_path),
        ),
        (
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--extra",
            "tui",
            "--format",
            "requirements.txt",
            "--output-file",
            str(tui_path),
        ),
        (
            "uvx",
            "--from",
            AUDIT_TOOL,
            "pip-audit",
            "--requirement",
            str(core_path),
            "--no-deps",
            "--disable-pip",
            "--format",
            "json",
            "--output",
            str(core_output),
        ),
        (
            "uvx",
            "--from",
            AUDIT_TOOL,
            "pip-audit",
            "--requirement",
            str(tui_path),
            "--no-deps",
            "--disable-pip",
            "--format",
            "json",
            "--output",
            str(tui_output),
        ),
    )


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _directory_identity(metadata: os.stat_result) -> DirectoryIdentity:
    return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


def _identity_change_time_ns(metadata: os.stat_result) -> int:
    if os.name == "nt":
        birthtime_ns = getattr(metadata, "st_birthtime_ns", None)
        if isinstance(birthtime_ns, int):
            return birthtime_ns
    return metadata.st_ctime_ns


def _file_identity(metadata: os.stat_result) -> PathIdentity:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        _identity_change_time_ns(metadata),
    )


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _regular_file_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _validate_parent_chain(candidate: Path) -> None:
    for parent in candidate.parents:
        try:
            parent_metadata = parent.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise DependencyAuditError("evidence directory parent could not be inspected") from None
        if stat.S_ISLNK(parent_metadata.st_mode):
            raise DependencyAuditError("evidence directory parent must not be a symlink")
        if not stat.S_ISDIR(parent_metadata.st_mode):
            raise DependencyAuditError("evidence directory parent must be a directory")


def _open_parent_directory(path: Path) -> int:
    try:
        return os.open(path, _directory_open_flags())
    except OSError:
        raise DependencyAuditError("evidence directory parent could not be opened safely") from None


def _open_evidence_directory(candidate: Path, parent_descriptor: int) -> int:
    try:
        return os.open(candidate.name, _directory_open_flags(), dir_fd=parent_descriptor)
    except OSError:
        raise DependencyAuditError("evidence directory changed during creation") from None


def _prepare_evidence_directory(evidence_dir: Path) -> PreparedEvidenceDirectory:
    candidate = _absolute_path(evidence_dir)
    try:
        existing_metadata = candidate.lstat()
    except FileNotFoundError:
        existing_metadata = None
    except OSError:
        raise DependencyAuditError("evidence directory path could not be inspected") from None
    if existing_metadata is not None and stat.S_ISLNK(existing_metadata.st_mode):
        raise DependencyAuditError("evidence directory must not be a symlink")
    if existing_metadata is not None:
        raise DependencyAuditError("evidence directory must not already exist")

    _validate_parent_chain(candidate)
    try:
        candidate.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        raise DependencyAuditError("evidence directory parent could not be created") from None
    _validate_parent_chain(candidate)

    parent_descriptor: int | None = None
    evidence_descriptor: int | None = None
    try:
        if DESCRIPTOR_RELATIVE_IO:
            parent_descriptor = _open_parent_directory(candidate.parent)
            parent_metadata = os.fstat(parent_descriptor)
            try:
                parent_path_metadata = candidate.parent.lstat()
            except OSError:
                raise DependencyAuditError("evidence directory changed during creation") from None
            if _directory_identity(parent_metadata) != _directory_identity(parent_path_metadata):
                raise DependencyAuditError("evidence directory changed during creation")
        else:
            try:
                parent_metadata = candidate.parent.lstat()
            except OSError:
                raise DependencyAuditError("evidence directory changed during creation") from None

        try:
            if parent_descriptor is not None:
                os.mkdir(candidate.name, mode=0o700, dir_fd=parent_descriptor)
            else:
                candidate.mkdir(mode=0o700, parents=False, exist_ok=False)
        except FileExistsError:
            raise DependencyAuditError("evidence directory must not already exist") from None
        except OSError:
            raise DependencyAuditError("evidence directory could not be created") from None

        if parent_descriptor is not None:
            evidence_descriptor = _open_evidence_directory(candidate, parent_descriptor)
            evidence_metadata = os.fstat(evidence_descriptor)
        else:
            try:
                evidence_metadata = candidate.lstat()
            except OSError:
                raise DependencyAuditError("evidence directory changed during creation") from None
        path_identities: list[tuple[Path, DirectoryIdentity]] = []
        for component in (candidate, *candidate.parents):
            try:
                metadata = component.lstat()
            except OSError:
                raise DependencyAuditError("evidence directory changed during creation") from None
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise DependencyAuditError("evidence directory changed during creation")
            path_identities.append((component, _directory_identity(metadata)))
        if _directory_identity(parent_metadata) != path_identities[1][1]:
            raise DependencyAuditError("evidence directory changed during creation")
        if _directory_identity(evidence_metadata) != path_identities[0][1]:
            raise DependencyAuditError("evidence directory changed during creation")
        return PreparedEvidenceDirectory(
            path=candidate,
            parent_descriptor=parent_descriptor,
            evidence_descriptor=evidence_descriptor,
            parent_identity=_directory_identity(parent_metadata),
            evidence_identity=_directory_identity(evidence_metadata),
            path_identities=tuple(path_identities),
        )
    except BaseException:
        if evidence_descriptor is not None:
            os.close(evidence_descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)
        raise


def _close_evidence_directory(prepared: PreparedEvidenceDirectory) -> None:
    if prepared.evidence_descriptor is not None:
        os.close(prepared.evidence_descriptor)
    if prepared.parent_descriptor is not None:
        os.close(prepared.parent_descriptor)


def _require_prepared_directory(
    prepared: PreparedEvidenceDirectory,
    *,
    phase: str = "collection",
) -> None:
    descriptors = (prepared.parent_descriptor, prepared.evidence_descriptor)
    if (descriptors[0] is None) != (descriptors[1] is None):
        raise DependencyAuditError(f"evidence directory path changed during {phase}")
    if descriptors[0] is not None and descriptors[1] is not None:
        try:
            parent_metadata = os.fstat(descriptors[0])
            evidence_metadata = os.fstat(descriptors[1])
        except OSError:
            raise DependencyAuditError(f"evidence directory path changed during {phase}") from None
        if _directory_identity(parent_metadata) != prepared.parent_identity:
            raise DependencyAuditError(f"evidence directory path changed during {phase}")
        if _directory_identity(evidence_metadata) != prepared.evidence_identity:
            raise DependencyAuditError(f"evidence directory path changed during {phase}")
    for component, expected_identity in prepared.path_identities:
        try:
            metadata = component.lstat()
        except OSError:
            raise DependencyAuditError(f"evidence directory path changed during {phase}") from None
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise DependencyAuditError(f"evidence directory path changed during {phase}")
        if _directory_identity(metadata) != expected_identity:
            raise DependencyAuditError(f"evidence directory path changed during {phase}")


def _read_descriptor(file_descriptor: int, *, role: str) -> bytes:
    chunks: list[bytes] = []
    try:
        while chunk := os.read(file_descriptor, 1024 * 1024):
            chunks.append(chunk)
    except OSError:
        raise DependencyAuditError(f"{role} could not be read safely") from None
    return b"".join(chunks)


def _snapshot_frozen_lock() -> FrozenLockSnapshot:
    lockfile = REPO_ROOT / "uv.lock"
    try:
        metadata_before = lockfile.lstat()
    except OSError:
        raise DependencyAuditError("repo uv.lock must be a nonempty regular file") from None
    if stat.S_ISLNK(metadata_before.st_mode) or not stat.S_ISREG(metadata_before.st_mode):
        raise DependencyAuditError("repo uv.lock must be a nonempty regular file")
    if metadata_before.st_nlink != 1:
        raise DependencyAuditError("repo uv.lock must be a single-link regular file")
    if metadata_before.st_size == 0:
        raise DependencyAuditError("repo uv.lock must be a nonempty regular file")
    try:
        file_descriptor = os.open(lockfile, _regular_file_open_flags())
    except OSError:
        raise DependencyAuditError("repo uv.lock could not be opened safely") from None
    try:
        opened_metadata = os.fstat(file_descriptor)
        if _file_identity(opened_metadata) != _file_identity(metadata_before):
            raise DependencyAuditError("repo uv.lock changed while opening")
        payload = _read_descriptor(file_descriptor, role="repo uv.lock")
        opened_metadata_after = os.fstat(file_descriptor)
    finally:
        os.close(file_descriptor)
    try:
        metadata_after = lockfile.lstat()
    except OSError:
        raise DependencyAuditError("repo uv.lock changed while reading") from None
    if _file_identity(metadata_after) != _file_identity(opened_metadata_after):
        raise DependencyAuditError("repo uv.lock changed while reading")
    if _file_identity(opened_metadata_after) != _file_identity(opened_metadata):
        raise DependencyAuditError("repo uv.lock changed while reading")
    if not payload:
        raise DependencyAuditError("repo uv.lock must be a nonempty regular file")
    return FrozenLockSnapshot(
        path=lockfile,
        identity=_file_identity(metadata_after),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _revalidate_frozen_lock(
    expected: FrozenLockSnapshot,
    *,
    before_publication: bool = False,
) -> None:
    try:
        current = _snapshot_frozen_lock()
    except DependencyAuditError:
        suffix = " before publication" if before_publication else " during dependency audit"
        raise DependencyAuditError(f"uv.lock changed{suffix}") from None
    if current != expected:
        suffix = " before publication" if before_publication else " during dependency audit"
        raise DependencyAuditError(f"uv.lock changed{suffix}")


def _require_requirements_parser() -> str:
    try:
        observed_version = metadata.version(PACKAGING_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        raise DependencyAuditError(f"{REQUIREMENTS_PARSER} is required") from None
    if observed_version != REQUIRED_PACKAGING_VERSION:
        raise DependencyAuditError(f"{REQUIREMENTS_PARSER} is required")
    return REQUIREMENTS_PARSER


def _sanitized_environment(
    *,
    uv_cache_dir: Path,
    uv_python_install_dir: Path,
    uv_tool_dir: Path,
) -> dict[str, str]:
    environment = {
        name: os.environ[name] for name in INHERITED_ENVIRONMENT_ALLOWLIST if name in os.environ
    }
    environment.update(
        {
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_NO_INPUT": "1",
            "PYTHONNOUSERSITE": "1",
            "UV_CACHE_DIR": str(uv_cache_dir),
            "UV_NO_CONFIG": "1",
            "UV_PYTHON": REQUIRED_PYTHON_VERSION,
            "UV_PYTHON_INSTALL_DIR": str(uv_python_install_dir),
            "UV_TOOL_DIR": str(uv_tool_dir),
        }
    )
    return environment


def _captured_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _format_combined_log(captures: Sequence[CommandCapture]) -> str:
    sections: list[str] = []
    for capture in captures:
        sections.extend(
            (
                f"## {capture.role}\n",
                "### stdout\n",
                capture.stdout,
                "" if capture.stdout.endswith("\n") else "\n",
                "### stderr\n",
                capture.stderr,
                "" if capture.stderr.endswith("\n") else "\n",
            )
        )
    return "".join(sections)


def _relative_stat(prepared: PreparedEvidenceDirectory, filename: str) -> os.stat_result:
    if prepared.evidence_descriptor is not None:
        return os.stat(filename, dir_fd=prepared.evidence_descriptor, follow_symlinks=False)
    return (prepared.path / filename).lstat()


def _relative_open(
    prepared: PreparedEvidenceDirectory,
    filename: str,
    flags: int,
    mode: int = 0o777,
) -> int:
    if prepared.evidence_descriptor is not None:
        return os.open(filename, flags, mode, dir_fd=prepared.evidence_descriptor)
    return os.open(prepared.path / filename, flags, mode)


def _relative_unlink(prepared: PreparedEvidenceDirectory, filename: str) -> None:
    if prepared.evidence_descriptor is not None:
        os.unlink(filename, dir_fd=prepared.evidence_descriptor)
    else:
        (prepared.path / filename).unlink()


def _relative_replace(
    prepared: PreparedEvidenceDirectory,
    source_name: str,
    destination_name: str,
) -> None:
    if prepared.evidence_descriptor is not None:
        os.replace(
            source_name,
            destination_name,
            src_dir_fd=prepared.evidence_descriptor,
            dst_dir_fd=prepared.evidence_descriptor,
        )
    else:
        os.replace(prepared.path / source_name, prepared.path / destination_name)


def _relative_link(
    prepared: PreparedEvidenceDirectory,
    source_name: str,
    destination_name: str,
) -> None:
    if prepared.evidence_descriptor is not None:
        os.link(
            source_name,
            destination_name,
            src_dir_fd=prepared.evidence_descriptor,
            dst_dir_fd=prepared.evidence_descriptor,
            follow_symlinks=False,
        )
    else:
        os.link(
            prepared.path / source_name,
            prepared.path / destination_name,
            follow_symlinks=False,
        )


def _remove_relative_temporary(prepared: PreparedEvidenceDirectory, filename: str) -> None:
    try:
        _relative_unlink(prepared, filename)
    except FileNotFoundError:
        return
    except OSError:
        raise DependencyAuditError("temporary evidence file could not be cleaned up") from None


def _create_relative_temporary(
    prepared: PreparedEvidenceDirectory,
    destination_name: str,
) -> tuple[str, int]:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    for _ in range(16):
        temporary_name = f".{destination_name}.{secrets.token_hex(8)}.tmp"
        try:
            return temporary_name, _relative_open(prepared, temporary_name, flags, 0o600)
        except FileExistsError:
            continue
        except OSError:
            raise DependencyAuditError("temporary evidence file could not be created") from None
    raise DependencyAuditError("temporary evidence filename allocation was exhausted")


def _write_relative_temporary(
    prepared: PreparedEvidenceDirectory,
    destination_name: str,
    content: str,
) -> str:
    temporary_name, file_descriptor = _create_relative_temporary(prepared, destination_name)
    try:
        payload = content.encode("utf-8")
        offset = 0
        while offset < len(payload):
            written = os.write(file_descriptor, payload[offset:])
            if written <= 0:
                raise OSError("atomic evidence write made no progress")
            offset += written
        os.fsync(file_descriptor)
    except OSError:
        os.close(file_descriptor)
        _remove_relative_temporary(prepared, temporary_name)
        raise DependencyAuditError("evidence output could not be written atomically") from None
    os.close(file_descriptor)
    return temporary_name


def _write_combined_log(
    prepared: PreparedEvidenceDirectory,
    captures: Sequence[CommandCapture],
) -> None:
    _require_prepared_directory(prepared)
    temporary_name = _write_relative_temporary(
        prepared,
        "pip-audit.log",
        _format_combined_log(captures),
    )
    try:
        _require_prepared_directory(prepared)
        _relative_replace(prepared, temporary_name, "pip-audit.log")
        temporary_name = ""
    except OSError:
        raise DependencyAuditError("evidence output could not be written atomically") from None
    finally:
        if temporary_name:
            _remove_relative_temporary(prepared, temporary_name)


def _run_checked(
    command: Sequence[str],
    *,
    role: str,
    prepared: PreparedEvidenceDirectory,
    environment: Mapping[str, str],
    captures: list[CommandCapture],
    run_command: RunCommand,
) -> CompletedProcess[str]:
    _require_prepared_directory(prepared)
    try:
        completed = run_command(
            list(command),
            cwd=REPO_ROOT,
            env=dict(environment),
            check=True,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            shell=False,
        )
    except CalledProcessError as exc:
        captures.append(
            CommandCapture(
                role,
                _captured_text(exc.stdout if exc.stdout is not None else exc.output),
                _captured_text(exc.stderr),
            )
        )
        _write_combined_log(prepared, captures)
        raise DependencyAuditError(f"{role} failed with exit status {exc.returncode}") from None
    except TimeoutExpired as exc:
        captures.append(
            CommandCapture(role, _captured_text(exc.stdout), _captured_text(exc.stderr))
        )
        _write_combined_log(prepared, captures)
        raise DependencyAuditError(f"{role} timed out") from None
    except OSError:
        captures.append(CommandCapture(role, "", ""))
        _write_combined_log(prepared, captures)
        raise DependencyAuditError(f"{role} could not be executed") from None

    captures.append(
        CommandCapture(
            role,
            _captured_text(completed.stdout),
            _captured_text(completed.stderr),
        )
    )
    _write_combined_log(prepared, captures)
    if completed.returncode != 0:
        raise DependencyAuditError(f"{role} failed with exit status {completed.returncode}")
    return completed


def _read_generated_file(
    prepared: PreparedEvidenceDirectory,
    path: Path,
    *,
    role: str,
) -> tuple[str, str]:
    if path.parent != prepared.path or path.name not in {*GENERATED_FILENAMES, "pip-audit.log"}:
        raise DependencyAuditError(f"{role} escaped the evidence directory")
    _require_prepared_directory(prepared)
    try:
        metadata_before = _relative_stat(prepared, path.name)
    except OSError:
        raise DependencyAuditError(f"{role} must be a regular non-symlink file") from None
    if stat.S_ISLNK(metadata_before.st_mode) or not stat.S_ISREG(metadata_before.st_mode):
        raise DependencyAuditError(f"{role} must be a regular non-symlink file")
    if metadata_before.st_nlink != 1:
        raise DependencyAuditError(f"{role} must be a single-link regular file")
    if metadata_before.st_size == 0:
        raise DependencyAuditError(f"{role} must not be empty")
    try:
        file_descriptor = _relative_open(prepared, path.name, _regular_file_open_flags())
    except OSError:
        raise DependencyAuditError(f"{role} changed before validation") from None
    try:
        opened_metadata = os.fstat(file_descriptor)
        if _file_identity(opened_metadata) != _file_identity(metadata_before):
            raise DependencyAuditError(f"{role} changed before validation")
        payload = _read_descriptor(file_descriptor, role=role)
        opened_metadata_after = os.fstat(file_descriptor)
    finally:
        os.close(file_descriptor)
    try:
        metadata_after = _relative_stat(prepared, path.name)
    except OSError:
        raise DependencyAuditError(f"{role} changed during validation") from None
    if _file_identity(metadata_after) != _file_identity(opened_metadata_after):
        raise DependencyAuditError(f"{role} changed during validation")
    if _file_identity(opened_metadata_after) != _file_identity(opened_metadata):
        raise DependencyAuditError(f"{role} changed during validation")
    _require_prepared_directory(prepared)
    if not payload:
        raise DependencyAuditError(f"{role} must not be empty")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise DependencyAuditError(f"{role} must be valid UTF-8") from None
    return text, hashlib.sha256(payload).hexdigest()


def _requirement_entries(text: str, *, role: str) -> tuple[str, ...]:
    entries: list[str] = []
    continued: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        is_continuation = stripped.endswith("\\")
        continued.append(stripped[:-1].rstrip() if is_continuation else stripped)
        if not is_continuation:
            entries.append(" ".join(continued))
            continued = []
    if continued:
        raise DependencyAuditError(f"{role} must contain complete hash-locked entries")
    if not entries:
        raise DependencyAuditError(f"{role} must contain hash-locked requirements")
    return tuple(entries)


def _marker_environment() -> dict[str, str]:
    environment = default_environment()
    environment.update(
        {
            "implementation_version": REQUIRED_PYTHON_VERSION,
            "python_full_version": REQUIRED_PYTHON_VERSION,
            "python_version": "3.12",
        }
    )
    return environment


def _parse_requirement_entry(entry: str, *, role: str) -> tuple[str, str, bool, str]:
    hash_matches = tuple(HASH_OPTION_PATTERN.finditer(entry))
    if not hash_matches:
        raise DependencyAuditError(f"{role} must contain only hash-locked requirements")
    if any(SHA256_HASH_PATTERN.fullmatch(match.group(1)) is None for match in hash_matches):
        raise DependencyAuditError(f"{role} contains a non-SHA256 requirements hash")
    requirement_text = HASH_OPTION_PATTERN.sub("", entry).strip()
    if not requirement_text or requirement_text.startswith("-") or "--hash" in requirement_text:
        raise DependencyAuditError(f"{role} contains an unsupported requirements option")
    try:
        requirement = Requirement(requirement_text)
    except InvalidRequirement:
        raise DependencyAuditError(f"{role} contains an invalid requirements entry") from None
    specifiers = tuple(requirement.specifier)
    if (
        requirement.url is not None
        or len(specifiers) != 1
        or specifiers[0].operator != "=="
        or "*" in specifiers[0].version
    ):
        raise DependencyAuditError(f"{role} contains an unpinned or URL requirements entry")
    try:
        is_active = requirement.marker is None or requirement.marker.evaluate(_marker_environment())
    except (UndefinedComparison, UndefinedEnvironmentName):
        raise DependencyAuditError(f"{role} contains an unsupported requirements marker") from None
    return (
        str(canonicalize_name(requirement.name)),
        specifiers[0].version,
        is_active,
        requirement_text,
    )


def _validate_requirements(
    prepared: PreparedEvidenceDirectory,
    path: Path,
    *,
    role: str,
) -> tuple[str, dict[str, str]]:
    text, digest = _read_generated_file(prepared, path, role=role)
    active_versions: dict[str, str] = {}
    seen_entries: set[str] = set()
    for entry in _requirement_entries(text, role=role):
        name, version, is_active, requirement_text = _parse_requirement_entry(entry, role=role)
        if requirement_text in seen_entries:
            raise DependencyAuditError(f"{role} contains duplicate requirements entries")
        seen_entries.add(requirement_text)
        if not is_active:
            continue
        previous_version = active_versions.get(name)
        if previous_version is not None and previous_version != version:
            raise DependencyAuditError(f"{role} contains multiple active versions for {name}")
        active_versions[name] = version
    if not active_versions:
        raise DependencyAuditError(f"{role} contains no active hash-locked requirements")
    return digest, active_versions


def _audit_dependencies(payload: object, *, role: str) -> list[object]:
    if not isinstance(payload, dict):
        raise DependencyAuditError(f"{role} must be a JSON object")
    if set(payload) != {"dependencies", "fixes"}:
        raise DependencyAuditError(f"{role} must contain exactly dependencies and fixes")
    dependencies = payload["dependencies"]
    fixes = payload["fixes"]
    if not isinstance(dependencies, list) or not isinstance(fixes, list):
        raise DependencyAuditError(f"{role} dependencies and fixes must be lists")
    if fixes:
        raise DependencyAuditError(f"{role} fixes must be empty")
    return dependencies


def _validate_audit_output(
    prepared: PreparedEvidenceDirectory,
    path: Path,
    *,
    role: str,
    active_requirements: Mapping[str, str],
) -> str:
    text, digest = _read_generated_file(prepared, path, role=role)
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        raise DependencyAuditError(f"{role} must contain valid JSON") from None
    dependencies = _audit_dependencies(payload, role=role)
    audited_versions: dict[str, str] = {}
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            raise DependencyAuditError(f"{role} did not contain valid pip-audit JSON")
        if not set(dependency).issubset({"name", "version", "vulns", "skip_reason"}):
            raise DependencyAuditError(f"{role} did not contain valid pip-audit JSON")
        name = dependency.get("name")
        version = dependency.get("version")
        vulnerabilities = dependency.get("vulns")
        skip_reason = dependency.get("skip_reason", "")
        if not isinstance(name, str) or not name:
            raise DependencyAuditError(f"{role} dependency name is required")
        if not isinstance(version, str) or not version:
            raise DependencyAuditError(f"{role} dependency version is required")
        if not isinstance(vulnerabilities, list):
            raise DependencyAuditError(f"{role} dependency vulnerabilities must be a list")
        if vulnerabilities:
            raise DependencyAuditError(f"{role} reported vulnerabilities")
        if not isinstance(skip_reason, str):
            raise DependencyAuditError(f"{role} skip reason must be text")
        if skip_reason.strip():
            raise DependencyAuditError(f"{role} contains a nonempty skip reason")
        normalized_name = str(canonicalize_name(name))
        if normalized_name in audited_versions:
            raise DependencyAuditError(f"{role} contained a duplicate dependency record")
        audited_versions[normalized_name] = version
    if audited_versions != dict(active_requirements):
        raise DependencyAuditError(
            f"{role} active dependency map and dependency set did not match requirements"
        )
    return digest


def _utc_now() -> datetime:
    # The release plan requires this exact observation-time source.
    return datetime.now(timezone.utc)  # noqa: UP017


def _observation_timestamp(now: Clock) -> str:
    observed_at = now()
    if observed_at.tzinfo is None or observed_at.utcoffset() != timedelta(0):
        raise DependencyAuditError("observation time must be timezone-aware UTC")
    return observed_at.isoformat()


def _revalidate_success_snapshot(
    prepared: PreparedEvidenceDirectory,
    snapshot: EvidenceSnapshot,
) -> None:
    _require_prepared_directory(prepared, phase="publication")
    for filename, expected_digest in snapshot.digests:
        _, current_digest = _read_generated_file(
            prepared,
            prepared.path / filename,
            role=f"{filename} evidence",
        )
        if current_digest != expected_digest:
            raise DependencyAuditError("generated evidence changed before publication")
    _revalidate_frozen_lock(snapshot.lock, before_publication=True)
    _require_prepared_directory(prepared, phase="publication")


def _write_manifest(
    prepared: PreparedEvidenceDirectory,
    observed_at: str,
    snapshot: EvidenceSnapshot,
    requirements_parser: str,
) -> None:
    sha256 = dict(snapshot.digests)
    sha256["uv.lock"] = snapshot.lock.sha256
    manifest = {
        "audit_tool": AUDIT_TOOL,
        "observed_at": observed_at,
        "paths": {
            "core": {
                "requirements": "core-requirements.txt",
                "result": "core-pip-audit.json",
            },
            "tui": {
                "requirements": "tui-requirements.txt",
                "result": "tui-pip-audit.json",
            },
        },
        "requirements_parser": requirements_parser,
        "sha256": sha256,
    }
    content = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    temporary_name = _write_relative_temporary(prepared, "manifest.json", content)
    published = False
    try:
        _revalidate_success_snapshot(prepared, snapshot)
        try:
            _relative_link(prepared, temporary_name, "manifest.json")
        except FileExistsError:
            raise DependencyAuditError("dependency audit manifest already exists") from None
        except OSError:
            raise DependencyAuditError("dependency audit manifest could not be published") from None
        published = True
    finally:
        try:
            _remove_relative_temporary(prepared, temporary_name)
        except DependencyAuditError:
            if not published:
                raise


def _collect_final_snapshot(
    prepared: PreparedEvidenceDirectory,
    initial_digests: Mapping[str, str],
    core_active: Mapping[str, str],
    tui_active: Mapping[str, str],
    lock: FrozenLockSnapshot,
) -> EvidenceSnapshot:
    core_requirements = prepared.path / "core-requirements.txt"
    tui_requirements = prepared.path / "tui-requirements.txt"
    core_result = prepared.path / "core-pip-audit.json"
    tui_result = prepared.path / "tui-pip-audit.json"
    final_core_digest, final_core_active = _validate_requirements(
        prepared,
        core_requirements,
        role="core requirements output",
    )
    final_tui_digest, final_tui_active = _validate_requirements(
        prepared,
        tui_requirements,
        role="TUI requirements output",
    )
    if (
        final_core_digest != initial_digests["core-requirements.txt"]
        or final_tui_digest != initial_digests["tui-requirements.txt"]
    ):
        raise DependencyAuditError("generated evidence changed after validation")
    final_digests = {
        "core-requirements.txt": final_core_digest,
        "tui-requirements.txt": final_tui_digest,
        "core-pip-audit.json": _validate_audit_output(
            prepared,
            core_result,
            role="core audit output",
            active_requirements=final_core_active,
        ),
        "tui-pip-audit.json": _validate_audit_output(
            prepared,
            tui_result,
            role="TUI audit output",
            active_requirements=final_tui_active,
        ),
    }
    if final_core_active != dict(core_active) or final_tui_active != dict(tui_active):
        raise DependencyAuditError("generated evidence changed after validation")
    if final_digests != dict(initial_digests):
        raise DependencyAuditError("generated evidence changed after validation")
    _, log_digest = _read_generated_file(
        prepared,
        prepared.path / "pip-audit.log",
        role="combined audit log",
    )
    final_digests["pip-audit.log"] = log_digest
    _revalidate_frozen_lock(lock)
    return EvidenceSnapshot(tuple(sorted(final_digests.items())), lock)


def verify_dependency_audit(
    evidence_dir: Path,
    *,
    run_command: RunCommand = subprocess.run,
    now: Clock = _utc_now,
) -> tuple[Path, Path]:
    """Export and audit locked dependency paths, then write success evidence.

    The evidence directory must be new. Each subprocess is bounded and runs
    from the exact repository root against one immutable frozen lock snapshot.
    A manifest is written only after both requirement sets, both audit results,
    the combined log, and the lock validate immediately before publication.

    Args:
        evidence_dir: New directory that will own all generated audit evidence.
        run_command: Injected subprocess boundary used by unit tests.
        now: UTC observation-time provider.

    Returns:
        The validated core and TUI audit result paths.

    Raises:
        DependencyAuditError: If collection or evidence validation fails.
    """

    requirements_parser = _require_requirements_parser()
    lock = _snapshot_frozen_lock()
    prepared = _prepare_evidence_directory(evidence_dir)
    try:
        commands = build_commands(prepared.path)
        captures: list[CommandCapture] = []
        core_requirements = prepared.path / "core-requirements.txt"
        tui_requirements = prepared.path / "tui-requirements.txt"
        core_result = prepared.path / "core-pip-audit.json"
        tui_result = prepared.path / "tui-pip-audit.json"
        outputs = (core_requirements, tui_requirements, core_result, tui_result)
        initial_digests: dict[str, str] = {}
        active_requirements: dict[str, dict[str, str]] = {}

        try:
            with tempfile.TemporaryDirectory(prefix="localql-dependency-audit-") as run_temp_text:
                run_temp = Path(run_temp_text)
                uv_cache_dir = run_temp / "uv-cache"
                uv_python_install_dir = run_temp / "uv-python"
                uv_tool_dir = run_temp / "uv-tools"
                uv_cache_dir.mkdir(mode=0o700)
                uv_python_install_dir.mkdir(mode=0o700)
                uv_tool_dir.mkdir(mode=0o700)
                environment = _sanitized_environment(
                    uv_cache_dir=uv_cache_dir,
                    uv_python_install_dir=uv_python_install_dir,
                    uv_tool_dir=uv_tool_dir,
                )

                for command_index, (command, role, output) in enumerate(
                    zip(commands, COMMAND_ROLES, outputs, strict=True)
                ):
                    _require_prepared_directory(prepared)
                    _revalidate_frozen_lock(lock)
                    try:
                        _run_checked(
                            command,
                            role=role,
                            prepared=prepared,
                            environment=environment,
                            captures=captures,
                            run_command=run_command,
                        )
                    finally:
                        _require_prepared_directory(prepared)
                        _revalidate_frozen_lock(lock)
                    if command_index == 0:
                        digest, active_requirements["core"] = _validate_requirements(
                            prepared,
                            output,
                            role="core requirements output",
                        )
                    elif command_index == 1:
                        digest, active_requirements["tui"] = _validate_requirements(
                            prepared,
                            output,
                            role="TUI requirements output",
                        )
                    elif command_index == 2:
                        digest = _validate_audit_output(
                            prepared,
                            output,
                            role="core audit output",
                            active_requirements=active_requirements["core"],
                        )
                    else:
                        digest = _validate_audit_output(
                            prepared,
                            output,
                            role="TUI audit output",
                            active_requirements=active_requirements["tui"],
                        )
                    initial_digests[output.name] = digest
        except OSError:
            raise DependencyAuditError("private dependency-audit runtime cleanup failed") from None

        snapshot = _collect_final_snapshot(
            prepared,
            initial_digests,
            active_requirements["core"],
            active_requirements["tui"],
            lock,
        )
        observed_at = _observation_timestamp(now)
        _write_manifest(prepared, observed_at, snapshot, requirements_parser)
        return core_result, tui_result
    finally:
        _close_evidence_directory(prepared)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit frozen LocalQL core and TUI dependency paths."
    )
    parser.add_argument("--evidence-dir", type=Path, required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    run_command: RunCommand = subprocess.run,
    now: Clock = _utc_now,
) -> int:
    """Run fail-closed dependency audits and print both validated result paths."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        core_result, tui_result = verify_dependency_audit(
            args.evidence_dir,
            run_command=run_command,
            now=now,
        )
    except DependencyAuditError as exc:
        parser.error(str(exc))
    print(core_result)
    print(tui_result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
