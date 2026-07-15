"""Collect locked core and TUI dependency-audit evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess, TimeoutExpired

AUDIT_TOOL = "pip-audit==2.10.1"
COMMAND_TIMEOUT_SECONDS = 300.0
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
COMMAND_ROLES = (
    "export locked core requirements",
    "export locked TUI requirements",
    "audit locked core requirements",
    "audit locked TUI requirements",
)
HASH_PATTERN = re.compile(r"(?:^|\s)--hash=sha256:[0-9a-fA-F]{64}(?=$|\s)")
PACKAGE_NAME_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")

RunCommand = Callable[..., CompletedProcess[str]]
Clock = Callable[[], datetime]
PathIdentity = tuple[int, int, int, int, int, int, int]
DirectoryIdentity = tuple[int, int, int]


class DependencyAuditError(RuntimeError):
    """Raised when dependency-audit evidence cannot be trusted."""


@dataclass(frozen=True, slots=True)
class PreparedEvidenceDirectory:
    """Exclusive evidence directory and its non-symlink path-chain identities."""

    path: Path
    identities: tuple[tuple[Path, DirectoryIdentity], ...]


@dataclass(frozen=True, slots=True)
class RequirementNames:
    """Package names encoded by a hash-locked requirement export."""

    all_names: frozenset[str]
    unconditional_names: frozenset[str]


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


def _file_identity(metadata: os.stat_result) -> PathIdentity:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _validate_frozen_lock() -> None:
    lockfile = REPO_ROOT / "uv.lock"
    try:
        metadata = lockfile.lstat()
    except OSError:
        raise DependencyAuditError("repo uv.lock must be a nonempty regular file") from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise DependencyAuditError("repo uv.lock must be a nonempty regular file")
    if metadata.st_size == 0:
        raise DependencyAuditError("repo uv.lock must be a nonempty regular file")


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

    try:
        candidate.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError:
        raise DependencyAuditError("evidence directory must not already exist") from None
    except OSError:
        raise DependencyAuditError("evidence directory could not be created") from None

    identities: list[tuple[Path, DirectoryIdentity]] = []
    for component in (candidate, *candidate.parents):
        try:
            metadata = component.lstat()
        except OSError:
            raise DependencyAuditError("evidence directory path changed during creation") from None
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise DependencyAuditError("evidence directory path changed during creation")
        identities.append((component, _directory_identity(metadata)))
    return PreparedEvidenceDirectory(candidate, tuple(identities))


def _require_prepared_directory(prepared: PreparedEvidenceDirectory) -> None:
    for component, expected_identity in prepared.identities:
        try:
            metadata = component.lstat()
        except OSError:
            raise DependencyAuditError(
                "evidence directory path changed during collection"
            ) from None
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise DependencyAuditError("evidence directory path changed during collection")
        if _directory_identity(metadata) != expected_identity:
            raise DependencyAuditError("evidence directory path changed during collection")


def _sanitized_environment() -> dict[str, str]:
    environment = {
        name: os.environ[name] for name in INHERITED_ENVIRONMENT_ALLOWLIST if name in os.environ
    }
    environment.update(
        {
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_NO_INPUT": "1",
            "PYTHONNOUSERSITE": "1",
            "UV_NO_CONFIG": "1",
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


def _remove_temporary_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        raise DependencyAuditError("temporary evidence file could not be cleaned up") from None


def _write_text_atomically(
    prepared: PreparedEvidenceDirectory,
    destination: Path,
    content: str,
    *,
    exclusive: bool,
) -> None:
    if destination.parent != prepared.path:
        raise DependencyAuditError("evidence output escaped the evidence directory")
    _require_prepared_directory(prepared)
    file_descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        file_descriptor, temporary_text = tempfile.mkstemp(
            dir=prepared.path,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_text)
        os.fchmod(file_descriptor, 0o600)
        payload = content.encode("utf-8")
        offset = 0
        while offset < len(payload):
            written = os.write(file_descriptor, payload[offset:])
            if written <= 0:
                raise OSError("atomic evidence write made no progress")
            offset += written
        os.fsync(file_descriptor)
        os.close(file_descriptor)
        file_descriptor = None
        _require_prepared_directory(prepared)
        if exclusive:
            try:
                os.link(temporary_path, destination, follow_symlinks=False)
            except FileExistsError:
                raise DependencyAuditError("dependency audit manifest already exists") from None
        else:
            os.replace(temporary_path, destination)
            temporary_path = None
    except DependencyAuditError:
        raise
    except OSError:
        raise DependencyAuditError("evidence output could not be written atomically") from None
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if temporary_path is not None:
            _remove_temporary_file(temporary_path)


def _write_combined_log(
    prepared: PreparedEvidenceDirectory,
    captures: Sequence[CommandCapture],
) -> None:
    _write_text_atomically(
        prepared,
        prepared.path / "pip-audit.log",
        _format_combined_log(captures),
        exclusive=False,
    )


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
    if path.parent != prepared.path:
        raise DependencyAuditError(f"{role} escaped the evidence directory")
    _require_prepared_directory(prepared)
    try:
        metadata_before = path.lstat()
    except OSError:
        raise DependencyAuditError(f"{role} must be a regular non-symlink file") from None
    if stat.S_ISLNK(metadata_before.st_mode) or not stat.S_ISREG(metadata_before.st_mode):
        raise DependencyAuditError(f"{role} must be a regular non-symlink file")
    if metadata_before.st_nlink != 1:
        raise DependencyAuditError(f"{role} must be a single-link regular file")
    if metadata_before.st_size == 0:
        raise DependencyAuditError(f"{role} must not be empty")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags)
    except OSError:
        raise DependencyAuditError(f"{role} changed before validation") from None
    try:
        opened_metadata = os.fstat(file_descriptor)
        if _file_identity(opened_metadata) != _file_identity(metadata_before):
            raise DependencyAuditError(f"{role} changed before validation")
        chunks: list[bytes] = []
        while chunk := os.read(file_descriptor, 1024 * 1024):
            chunks.append(chunk)
        opened_metadata_after = os.fstat(file_descriptor)
    except OSError:
        raise DependencyAuditError(f"{role} could not be read safely") from None
    finally:
        os.close(file_descriptor)
    try:
        metadata_after = path.lstat()
    except OSError:
        raise DependencyAuditError(f"{role} changed during validation") from None
    if _file_identity(metadata_after) != _file_identity(opened_metadata_after):
        raise DependencyAuditError(f"{role} changed during validation")
    if _file_identity(opened_metadata_after) != _file_identity(opened_metadata):
        raise DependencyAuditError(f"{role} changed during validation")
    _require_prepared_directory(prepared)

    payload = b"".join(chunks)
    if not payload:
        raise DependencyAuditError(f"{role} must not be empty")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise DependencyAuditError(f"{role} must be valid UTF-8") from None
    return text, hashlib.sha256(payload).hexdigest()


def _normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


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


def _validate_requirements(
    prepared: PreparedEvidenceDirectory,
    path: Path,
    *,
    role: str,
) -> tuple[str, RequirementNames]:
    text, digest = _read_generated_file(prepared, path, role=role)
    all_names: set[str] = set()
    unconditional_names: set[str] = set()
    for entry in _requirement_entries(text, role=role):
        if HASH_PATTERN.search(entry) is None:
            raise DependencyAuditError(f"{role} must contain only hash-locked requirements")
        name_match = PACKAGE_NAME_PATTERN.match(entry)
        if name_match is None:
            raise DependencyAuditError(f"{role} contains an invalid requirement entry")
        normalized_name = _normalize_package_name(name_match.group(1))
        all_names.add(normalized_name)
        if ";" not in entry:
            unconditional_names.add(normalized_name)
    return digest, RequirementNames(frozenset(all_names), frozenset(unconditional_names))


def _audit_dependencies(payload: object, *, role: str) -> list[object]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise DependencyAuditError(f"{role} did not contain valid pip-audit JSON")
    dependencies = payload.get("dependencies")
    fixes = payload.get("fixes", [])
    if not isinstance(dependencies, list) or not isinstance(fixes, list) or fixes:
        raise DependencyAuditError(f"{role} did not contain valid pip-audit JSON")
    return dependencies


def _validate_audit_output(
    prepared: PreparedEvidenceDirectory,
    path: Path,
    *,
    role: str,
    requirement_names: RequirementNames,
) -> str:
    text, digest = _read_generated_file(prepared, path, role=role)
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        raise DependencyAuditError(f"{role} must contain valid JSON") from None
    dependencies = _audit_dependencies(payload, role=role)
    if not dependencies:
        raise DependencyAuditError(f"{role} did not contain audited dependencies")

    audited_names: set[str] = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            raise DependencyAuditError(f"{role} did not contain valid pip-audit JSON")
        name = dependency.get("name")
        version = dependency.get("version")
        vulnerabilities = dependency.get("vulns")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(version, str)
            or not version
            or not isinstance(vulnerabilities, list)
        ):
            raise DependencyAuditError(f"{role} did not contain valid pip-audit JSON")
        if vulnerabilities:
            raise DependencyAuditError(f"{role} reported vulnerabilities")
        normalized_name = _normalize_package_name(name)
        if normalized_name in audited_names:
            raise DependencyAuditError(f"{role} contained duplicate dependency evidence")
        audited_names.add(normalized_name)

    if not requirement_names.unconditional_names.issubset(audited_names):
        raise DependencyAuditError(f"{role} dependency set did not match requirements")
    if not audited_names.issubset(requirement_names.all_names):
        raise DependencyAuditError(f"{role} dependency set did not match requirements")
    return digest


def _utc_now() -> datetime:
    # The release plan requires this exact observation-time source.
    return datetime.now(timezone.utc)  # noqa: UP017


def _observation_timestamp(now: Clock) -> str:
    observed_at = now()
    if observed_at.tzinfo is None or observed_at.utcoffset() != timedelta(0):
        raise DependencyAuditError("observation time must be timezone-aware UTC")
    return observed_at.isoformat()


def _write_manifest(prepared: PreparedEvidenceDirectory, observed_at: str) -> None:
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
    }
    _write_text_atomically(
        prepared,
        prepared.path / "manifest.json",
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        exclusive=True,
    )


def verify_dependency_audit(
    evidence_dir: Path,
    *,
    run_command: RunCommand = subprocess.run,
    now: Clock = _utc_now,
) -> tuple[Path, Path]:
    """Export and audit locked dependency paths, then write success evidence.

    The evidence directory must be new. Each subprocess is bounded and runs
    from the exact repository root against the frozen lock. A manifest is
    written only after both requirement sets and both audit results validate.

    Args:
        evidence_dir: New directory that will own all generated audit evidence.
        run_command: Injected subprocess boundary used by unit tests.
        now: UTC observation-time provider.

    Returns:
        The validated core and TUI audit result paths.

    Raises:
        DependencyAuditError: If collection or evidence validation fails.
    """

    _validate_frozen_lock()
    prepared = _prepare_evidence_directory(evidence_dir)
    commands = build_commands(prepared.path)
    environment = _sanitized_environment()
    captures: list[CommandCapture] = []
    core_requirements = prepared.path / "core-requirements.txt"
    tui_requirements = prepared.path / "tui-requirements.txt"
    core_result = prepared.path / "core-pip-audit.json"
    tui_result = prepared.path / "tui-pip-audit.json"
    outputs = (core_requirements, tui_requirements, core_result, tui_result)
    digests: dict[Path, str] = {}
    requirement_contracts: dict[str, RequirementNames] = {}

    for command_index, (command, role, output) in enumerate(
        zip(commands, COMMAND_ROLES, outputs, strict=True)
    ):
        _run_checked(
            command,
            role=role,
            prepared=prepared,
            environment=environment,
            captures=captures,
            run_command=run_command,
        )
        if command_index == 0:
            digest, requirement_contracts["core"] = _validate_requirements(
                prepared,
                output,
                role="core requirements output",
            )
        elif command_index == 1:
            digest, requirement_contracts["tui"] = _validate_requirements(
                prepared,
                output,
                role="TUI requirements output",
            )
        elif command_index == 2:
            digest = _validate_audit_output(
                prepared,
                output,
                role="core audit output",
                requirement_names=requirement_contracts["core"],
            )
        else:
            digest = _validate_audit_output(
                prepared,
                output,
                role="TUI audit output",
                requirement_names=requirement_contracts["tui"],
            )
        digests[output] = digest

    final_core_digest, final_core_contract = _validate_requirements(
        prepared,
        core_requirements,
        role="core requirements output",
    )
    final_tui_digest, final_tui_contract = _validate_requirements(
        prepared,
        tui_requirements,
        role="TUI requirements output",
    )
    final_digests = {
        core_requirements: final_core_digest,
        tui_requirements: final_tui_digest,
        core_result: _validate_audit_output(
            prepared,
            core_result,
            role="core audit output",
            requirement_names=final_core_contract,
        ),
        tui_result: _validate_audit_output(
            prepared,
            tui_result,
            role="TUI audit output",
            requirement_names=final_tui_contract,
        ),
    }
    if final_digests != digests:
        raise DependencyAuditError("generated evidence changed after validation")

    _write_manifest(prepared, _observation_timestamp(now))
    return core_result, tui_result


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
