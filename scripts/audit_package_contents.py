"""Audit built wheel and sdist contents for public release hygiene."""

from __future__ import annotations

import argparse
import posixpath
import re
import stat
import tarfile
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

WHEEL_SIZE_LIMIT = 1024 * 1024
SDIST_SIZE_LIMIT = 5 * 1024 * 1024
MEMBER_EXPANDED_SIZE_LIMIT = 5 * 1024 * 1024
WHEEL_EXPANDED_SIZE_LIMIT = 10 * WHEEL_SIZE_LIMIT
SDIST_EXPANDED_SIZE_LIMIT = 10 * SDIST_SIZE_LIMIT
SCAN_CHUNK_SIZE = 64 * 1024

WHEEL_ALLOWED_ROOTS = {"csvql", "localql-1.0.2.dist-info"}
SDIST_ALLOWED_ROOT_FILES = {
    ".gitignore",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "PKG-INFO",
    "README.md",
    "SECURITY.md",
    "SUPPORT.md",
    "pyproject.toml",
}
SDIST_ALLOWED_ROOT_TREES = {"docs", "examples", "scripts", "src"}
SDIST_ALLOWED_SCRIPT_FILES = {"scripts/release-build-constraints.txt"}

SECRET_PATTERNS = {
    "aws-access-key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "github-token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "pypi-token": re.compile(rb"\bpypi-[A-Za-z0-9_-]{20,}\b"),
}

SECRET_TEXT_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bpypi-[A-Za-z0-9_-]{20,}\b"),
)

FORBIDDEN_NAMES = {
    ".DS_Store",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    ".csvql",
    "output",
    "keys.log",
    "csvql_project_pack",
    "csvql_project_pack.zip",
    "AGENTS.md",
}

FORBIDDEN_PATH_PARTS = {
    "docs/governance/audits",
    "docs/superpowers",
    "docs/CODEX_CAPABILITY_REVIEW.md",
}


def _sanitize_untrusted_text(value: str) -> str:
    sanitized = value
    for pattern in SECRET_TEXT_PATTERNS:
        sanitized = pattern.sub("<redacted>", sanitized)
    return "".join(character if character.isprintable() else "?" for character in sanitized)


@dataclass(frozen=True, slots=True)
class AuditFinding:
    """A redacted package-audit failure tied to an artifact and optional member."""

    artifact: str
    category: str
    member: str | None = None

    def __post_init__(self) -> None:
        """Sanitize untrusted archive identifiers before retaining them."""

        object.__setattr__(self, "artifact", _sanitize_untrusted_text(self.artifact))
        if self.member is not None:
            object.__setattr__(self, "member", _sanitize_untrusted_text(self.member))


@dataclass(frozen=True, slots=True)
class ArchiveMember:
    """Security-relevant metadata for one enumerated archive member."""

    name: str
    size: int
    is_regular: bool
    is_directory: bool


def is_release_candidate_proof_entry(parts: list[str]) -> bool:
    """Return whether an archive path points at an internal proof packet."""

    for index, part in enumerate(parts[:-1]):
        next_part = parts[index + 1]
        if (
            part == "docs"
            and next_part.startswith("release-candidate-proof-")
            and next_part.endswith(".md")
        ):
            return True
    return False


def archive_names_from_wheel(path: Path) -> list[str]:
    """Return all member names from a wheel archive."""

    with zipfile.ZipFile(path) as archive:
        return sorted(info.filename for info in archive.infolist())


def archive_names_from_sdist(path: Path) -> list[str]:
    """Return all member names from an sdist archive."""

    with tarfile.open(path) as archive:
        return sorted(info.name for info in archive.getmembers())


def forbidden_entries(names: list[str]) -> list[str]:
    """Return archive entries that should not appear in public package artifacts."""

    blocked: list[str] = []
    for name in names:
        normalized = name.strip("/")
        parts = normalized.split("/")
        if any(part in FORBIDDEN_NAMES for part in parts):
            blocked.append(name)
            continue
        if is_release_candidate_proof_entry(parts):
            blocked.append(name)
            continue
        if any(forbidden in normalized for forbidden in FORBIDDEN_PATH_PARTS):
            blocked.append(name)
    return blocked


def find_archives(dist_dir: Path, expected_version: str) -> tuple[Path, Path]:
    """Return the exact regular wheel and sdist contained by ``dist_dir``."""

    wheel = dist_dir / f"localql-{expected_version}-py3-none-any.whl"
    sdist = dist_dir / f"localql-{expected_version}.tar.gz"
    expected = {wheel, sdist}
    try:
        resolved_dist_dir = dist_dir.resolve(strict=True)
        observed = {
            path
            for path in dist_dir.iterdir()
            if path.name.endswith(".whl") or path.name.endswith(".tar.gz")
        }
    except OSError as error:
        safe_dist_dir = _sanitize_untrusted_text(str(dist_dir))
        raise SystemExit(f"Unable to inspect release archive directory: {safe_dist_dir}") from error

    if observed != expected:
        expected_names = ", ".join(sorted(_sanitize_untrusted_text(path.name) for path in expected))
        observed_names = (
            ", ".join(sorted(_sanitize_untrusted_text(path.name) for path in observed)) or "none"
        )
        safe_dist_dir = _sanitize_untrusted_text(str(dist_dir))
        raise SystemExit(
            f"Expected exact release archives in {safe_dist_dir}: {expected_names}; "
            f"found: {observed_names}"
        )

    for artifact in (wheel, sdist):
        try:
            mode = artifact.lstat().st_mode
            resolved_artifact = artifact.resolve(strict=True)
        except OSError as error:
            raise SystemExit(
                "Expected exact release archives to be regular files within the "
                "distribution directory"
            ) from error
        if (
            artifact.is_symlink()
            or not stat.S_ISREG(mode)
            or not resolved_artifact.is_relative_to(resolved_dist_dir)
        ):
            raise SystemExit(
                "Expected exact release archives to be regular files within the "
                "distribution directory"
            )
    return wheel, sdist


def size_findings(path: Path, limit: int) -> list[AuditFinding]:
    """Return a finding when an archive exceeds its compressed-byte ceiling."""

    return [AuditFinding(path.name, "size-ceiling")] if path.stat().st_size > limit else []


def _missing_member_finding(path: Path, member: str) -> AuditFinding:
    return AuditFinding(path.name, "missing-required-entry", member)


def _is_safe_archive_member(name: str) -> bool:
    if not name or name.startswith("/") or "\\" in name or "//" in name:
        return False
    if any(not character.isprintable() for character in name):
        return False
    canonical_name = name[:-1] if name.endswith("/") else name
    if not canonical_name:
        return False
    parts = canonical_name.split("/")
    return all(
        part not in {"", ".", ".."} and re.match(r"^[A-Za-z]:", part) is None for part in parts
    )


def _normalized_member_name(name: str) -> str:
    return posixpath.normpath(name.replace("\\", "/")).lstrip("/").rstrip("/")


def _zip_member(info: zipfile.ZipInfo) -> ArchiveMember:
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode) if info.create_system == 3 else 0
    filename_is_directory = info.is_dir()
    if file_type == 0:
        is_directory = filename_is_directory
        is_regular = not filename_is_directory
    else:
        unix_is_directory = file_type == stat.S_IFDIR
        metadata_agrees = filename_is_directory == unix_is_directory
        is_directory = metadata_agrees and unix_is_directory
        is_regular = metadata_agrees and file_type == stat.S_IFREG
    return ArchiveMember(info.orig_filename, info.file_size, is_regular, is_directory)


def _tar_member(info: tarfile.TarInfo) -> ArchiveMember:
    return ArchiveMember(info.name, info.size, info.isreg(), info.isdir())


def _metadata_findings(
    path: Path,
    members: list[ArchiveMember],
    expanded_total_limit: int,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    raw_name_counts = Counter(member.name for member in members)
    for name, count in sorted(raw_name_counts.items()):
        if count > 1:
            findings.append(AuditFinding(path.name, "duplicate-entry", name))

    normalized_name_groups: defaultdict[str, set[str]] = defaultdict(set)
    for member in members:
        normalized_name_groups[_normalized_member_name(member.name)].add(member.name)
    for normalized_name, raw_names in sorted(normalized_name_groups.items()):
        if len(raw_names) > 1:
            findings.append(AuditFinding(path.name, "duplicate-normalized-entry", normalized_name))

    for member in members:
        if not _is_safe_archive_member(member.name):
            findings.append(AuditFinding(path.name, "unsafe-member-name", member.name))
        if not member.is_regular and not member.is_directory:
            findings.append(AuditFinding(path.name, "special-entry", member.name))
        if member.is_directory and member.size != 0:
            findings.append(AuditFinding(path.name, "directory-payload", member.name))
        if member.size < 0 or member.size > MEMBER_EXPANDED_SIZE_LIMIT:
            findings.append(AuditFinding(path.name, "expanded-member-size", member.name))

    if sum(max(member.size, 0) for member in members) > expanded_total_limit:
        findings.append(AuditFinding(path.name, "expanded-total-size"))
    return findings


def _wheel_content_findings(
    path: Path,
    members: list[ArchiveMember],
    expected_version: str,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    names = [member.name for member in members]
    blocked = set(forbidden_entries(names))
    findings.extend(AuditFinding(path.name, "forbidden-entry", name) for name in sorted(blocked))

    expected_dist_info = f"localql-{expected_version}.dist-info"
    safe_members = [
        member
        for member in members
        if _is_safe_archive_member(member.name)
        and member.name not in blocked
        and (member.is_regular or member.is_directory)
    ]
    regular_names = {member.name.rstrip("/") for member in safe_members if member.is_regular}
    directory_names = {member.name.rstrip("/") for member in safe_members if member.is_directory}

    for member in safe_members:
        normalized = member.name.rstrip("/")
        root = normalized.split("/", maxsplit=1)[0]
        if root not in WHEEL_ALLOWED_ROOTS:
            findings.append(AuditFinding(path.name, "unexpected-entry", member.name))

    has_csvql_tree = "csvql" in directory_names or any(
        name.startswith("csvql/") for name in regular_names
    )
    if not has_csvql_tree:
        findings.append(_missing_member_finding(path, "csvql/"))

    dist_info_roots = {
        name.split("/", maxsplit=1)[0]
        for name in regular_names | directory_names
        if name.split("/", maxsplit=1)[0].endswith(".dist-info")
    }
    if dist_info_roots != {expected_dist_info}:
        findings.append(_missing_member_finding(path, f"{expected_dist_info}/"))

    for filename in ("METADATA", "WHEEL", "entry_points.txt", "RECORD"):
        member = f"{expected_dist_info}/{filename}"
        if member not in regular_names:
            findings.append(_missing_member_finding(path, member))

    has_license = any(
        name.startswith(f"{expected_dist_info}/")
        and PurePosixPath(name).name.upper().startswith("LICENSE")
        for name in regular_names
    )
    if not has_license:
        findings.append(_missing_member_finding(path, f"{expected_dist_info}/LICENSE*"))
    return findings


def _sdist_content_findings(
    path: Path,
    members: list[ArchiveMember],
    expected_version: str,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    names = [member.name for member in members]
    blocked = set(forbidden_entries(names))
    findings.extend(AuditFinding(path.name, "forbidden-entry", name) for name in sorted(blocked))

    expected_root = f"localql-{expected_version}"
    safe_members = [
        member
        for member in members
        if _is_safe_archive_member(member.name)
        and member.name not in blocked
        and (member.is_regular or member.is_directory)
    ]
    regular_names = {member.name.rstrip("/") for member in safe_members if member.is_regular}
    directory_names = {member.name.rstrip("/") for member in safe_members if member.is_directory}

    for member in safe_members:
        normalized = member.name.rstrip("/")
        parts = normalized.split("/")
        if parts[0] != expected_root:
            findings.append(AuditFinding(path.name, "unexpected-entry", member.name))
            continue
        relative_parts = parts[1:]
        if not relative_parts:
            if not member.is_directory:
                findings.append(AuditFinding(path.name, "unexpected-entry", member.name))
            continue
        relative = "/".join(relative_parts)
        if len(relative_parts) == 1:
            is_allowed_root_file = member.is_regular and relative in SDIST_ALLOWED_ROOT_FILES
            is_allowed_root_tree = member.is_directory and relative in SDIST_ALLOWED_ROOT_TREES
            if not is_allowed_root_file and not is_allowed_root_tree:
                findings.append(AuditFinding(path.name, "unexpected-entry", member.name))
            continue
        root_tree = relative_parts[0]
        if root_tree not in SDIST_ALLOWED_ROOT_TREES or (
            root_tree == "scripts" and relative not in SDIST_ALLOWED_SCRIPT_FILES
        ):
            findings.append(AuditFinding(path.name, "unexpected-entry", member.name))

    required_files = (
        "CHANGELOG.md",
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "scripts/release-build-constraints.txt",
    )
    for relative in required_files:
        member = f"{expected_root}/{relative}"
        if member not in regular_names:
            findings.append(_missing_member_finding(path, member))

    required_trees = ("docs", "examples/saas_revenue", "src/csvql")
    for relative in required_trees:
        member = f"{expected_root}/{relative}"
        has_real_tree = member in directory_names or any(
            name.startswith(f"{member}/") for name in regular_names
        )
        if not has_real_tree:
            findings.append(_missing_member_finding(path, f"{member}/"))
    return findings


def _secret_findings_for_stream(
    artifact: str,
    member_name: str,
    member_file: BinaryIO,
) -> list[AuditFinding]:
    payload = bytearray()
    while chunk := member_file.read(SCAN_CHUNK_SIZE):
        if b"\0" in chunk:
            return []
        payload.extend(chunk)
    return [
        AuditFinding(artifact, category, member_name)
        for category, pattern in SECRET_PATTERNS.items()
        if pattern.search(payload) is not None
    ]


def _zip_secret_findings(
    path: Path,
    archive: zipfile.ZipFile,
    infos: list[zipfile.ZipInfo],
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for info in infos:
        if not _zip_member(info).is_regular:
            continue
        with archive.open(info) as member_file:
            findings.extend(_secret_findings_for_stream(path.name, info.filename, member_file))
    return findings


def _tar_secret_findings(
    path: Path,
    archive: tarfile.TarFile,
    infos: list[tarfile.TarInfo],
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for info in infos:
        if not info.isreg():
            continue
        member_file = archive.extractfile(info)
        if member_file is None:
            findings.append(AuditFinding(path.name, "invalid-member-payload", info.name))
            continue
        with member_file:
            findings.extend(_secret_findings_for_stream(path.name, info.name, member_file))
    return findings


def secret_findings(path: Path) -> list[AuditFinding]:
    """Return redacted secret-shape findings while retaining one bounded member."""

    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            members = [_zip_member(info) for info in infos]
            if _metadata_findings(path, members, WHEEL_EXPANDED_SIZE_LIMIT):
                return []
            return _zip_secret_findings(path, archive, infos)
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            infos = archive.getmembers()
            members = [_tar_member(info) for info in infos]
            if _metadata_findings(path, members, SDIST_EXPANDED_SIZE_LIMIT):
                return []
            return _tar_secret_findings(path, archive, infos)
    safe_name = _sanitize_untrusted_text(path.name)
    raise ValueError(f"Unsupported package archive: {safe_name}")


def _audit_wheel(path: Path, expected_version: str) -> list[AuditFinding]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        members = [_zip_member(info) for info in infos]
        findings = [
            *_metadata_findings(path, members, WHEEL_EXPANDED_SIZE_LIMIT),
            *_wheel_content_findings(path, members, expected_version),
        ]
        if findings:
            return findings
        return _zip_secret_findings(path, archive, infos)


def _audit_sdist(path: Path, expected_version: str) -> list[AuditFinding]:
    with tarfile.open(path) as archive:
        infos = archive.getmembers()
        members = [_tar_member(info) for info in infos]
        findings = [
            *_metadata_findings(path, members, SDIST_EXPANDED_SIZE_LIMIT),
            *_sdist_content_findings(path, members, expected_version),
        ]
        if findings:
            return findings
        return _tar_secret_findings(path, archive, infos)


def audit_archive(path: Path, expected_version: str) -> list[AuditFinding]:
    """Audit one exact release archive without exposing matched secret values."""

    wheel_name = f"localql-{expected_version}-py3-none-any.whl"
    sdist_name = f"localql-{expected_version}.tar.gz"
    if path.name == wheel_name:
        compressed_limit = WHEEL_SIZE_LIMIT
        audit_content = _audit_wheel
    elif path.name == sdist_name:
        compressed_limit = SDIST_SIZE_LIMIT
        audit_content = _audit_sdist
    else:
        return [AuditFinding(path.name, "archive-identity")]

    try:
        compressed_size_findings = size_findings(path, compressed_limit)
        if compressed_size_findings:
            return compressed_size_findings
        return audit_content(path, expected_version)
    except (OSError, EOFError, tarfile.TarError, zipfile.BadZipFile, RuntimeError):
        return [AuditFinding(path.name, "invalid-archive")]


def render_findings(findings: list[AuditFinding]) -> str:
    """Render findings without including inspected member contents."""

    return "\n".join(
        f"{item.artifact}: {item.category}"
        + (f" in {item.member}" if item.member is not None else "")
        for item in findings
    )


def main() -> None:
    """Run the package content audit."""

    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()

    wheel, sdist = find_archives(args.dist_dir, args.expected_version)
    findings = [
        *audit_archive(wheel, args.expected_version),
        *audit_archive(sdist, args.expected_version),
    ]
    if findings:
        raise SystemExit("Package audit failed:\n" + render_findings(findings))
    print("Package content audit passed: 1 wheel(s), 1 sdist(s).")


if __name__ == "__main__":
    main()
