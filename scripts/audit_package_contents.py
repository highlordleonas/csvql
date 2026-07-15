"""Audit built wheel and sdist contents for public release hygiene."""

from __future__ import annotations

import argparse
import re
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

WHEEL_SIZE_LIMIT = 1024 * 1024
SDIST_SIZE_LIMIT = 5 * 1024 * 1024

WHEEL_ALLOWED_ROOTS = {"csvql", "localql-1.0.2.dist-info"}
SDIST_ALLOWED_ROOT_FILES = {
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


@dataclass(frozen=True, slots=True)
class AuditFinding:
    """A redacted package-audit failure tied to an artifact and optional member."""

    artifact: str
    category: str
    member: str | None = None


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
        return sorted(archive.namelist())


def archive_names_from_sdist(path: Path) -> list[str]:
    """Return all member names from an sdist archive."""

    with tarfile.open(path) as archive:
        return sorted(archive.getnames())


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
    """Return the exact universal wheel and sdist for ``expected_version``."""

    wheel = dist_dir / f"localql-{expected_version}-py3-none-any.whl"
    sdist = dist_dir / f"localql-{expected_version}.tar.gz"
    expected = {wheel, sdist}
    observed = {
        path
        for path in dist_dir.iterdir()
        if path.is_file() and (path.name.endswith(".whl") or path.name.endswith(".tar.gz"))
    }
    if observed != expected:
        expected_names = ", ".join(sorted(path.name for path in expected))
        observed_names = ", ".join(sorted(path.name for path in observed)) or "none"
        raise SystemExit(
            f"Expected exact release archives in {dist_dir}: {expected_names}; "
            f"found: {observed_names}"
        )
    return wheel, sdist


def size_findings(path: Path, limit: int) -> list[AuditFinding]:
    """Return a finding when an archive exceeds its byte ceiling."""

    return [AuditFinding(path.name, "size-ceiling")] if path.stat().st_size > limit else []


def _secret_findings_for_members(
    artifact: str, members: list[tuple[str, bytes]]
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for member_name, content in members:
        if b"\0" in content:
            continue
        for category, pattern in SECRET_PATTERNS.items():
            if pattern.search(content) is not None:
                findings.append(AuditFinding(artifact, category, member_name))
    return findings


def secret_findings(path: Path) -> list[AuditFinding]:
    """Return redacted high-confidence secret-shape findings for text members."""

    members: list[tuple[str, bytes]] = []
    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as archive:
            for member in sorted(archive.infolist(), key=lambda item: item.filename):
                if member.is_dir():
                    continue
                members.append((member.filename, archive.read(member)))
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            for member in sorted(archive.getmembers(), key=lambda item: item.name):
                if not member.isfile():
                    continue
                member_file = archive.extractfile(member)
                if member_file is not None:
                    members.append((member.name, member_file.read()))
    else:
        raise ValueError(f"Unsupported package archive: {path.name}")
    return _secret_findings_for_members(path.name, members)


def _missing_member_finding(path: Path, member: str) -> AuditFinding:
    return AuditFinding(path.name, "missing-required-entry", member)


def _is_safe_archive_member(name: str) -> bool:
    normalized = name.strip("/")
    return (
        bool(normalized)
        and not name.startswith("/")
        and all(part not in {"", ".", ".."} for part in normalized.split("/"))
    )


def _wheel_content_findings(
    path: Path, names: list[str], expected_version: str
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    blocked = set(forbidden_entries(names))
    findings.extend(AuditFinding(path.name, "forbidden-entry", name) for name in sorted(blocked))

    expected_dist_info = f"localql-{expected_version}.dist-info"
    normalized_names = {name.strip("/") for name in names if name.strip("/")}
    file_names = {name.strip("/") for name in names if name.strip("/") and not name.endswith("/")}

    for name in names:
        normalized = name.strip("/")
        if not normalized or name in blocked:
            continue
        if not _is_safe_archive_member(name):
            findings.append(AuditFinding(path.name, "unexpected-entry", name))
            continue
        root = normalized.split("/", maxsplit=1)[0]
        if root not in WHEEL_ALLOWED_ROOTS:
            findings.append(AuditFinding(path.name, "unexpected-entry", name))

    if not any(name.startswith("csvql/") for name in file_names):
        findings.append(_missing_member_finding(path, "csvql/"))

    dist_info_roots = {
        name.split("/", maxsplit=1)[0]
        for name in normalized_names
        if name.split("/", maxsplit=1)[0].endswith(".dist-info")
    }
    if dist_info_roots != {expected_dist_info}:
        findings.append(_missing_member_finding(path, f"{expected_dist_info}/"))

    for filename in ("METADATA", "WHEEL", "entry_points.txt", "RECORD"):
        member = f"{expected_dist_info}/{filename}"
        if member not in file_names:
            findings.append(_missing_member_finding(path, member))

    has_license = any(
        name.startswith(f"{expected_dist_info}/")
        and PurePosixPath(name).name.upper().startswith("LICENSE")
        for name in file_names
    )
    if not has_license:
        findings.append(_missing_member_finding(path, f"{expected_dist_info}/LICENSE*"))
    return findings


def _sdist_content_findings(
    path: Path, names: list[str], expected_version: str
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    blocked = set(forbidden_entries(names))
    findings.extend(AuditFinding(path.name, "forbidden-entry", name) for name in sorted(blocked))

    expected_root = f"localql-{expected_version}"
    normalized_names = {name.strip("/") for name in names if name.strip("/")}
    for name in names:
        normalized = name.strip("/")
        if not normalized or name in blocked:
            continue
        if not _is_safe_archive_member(name):
            findings.append(AuditFinding(path.name, "unexpected-entry", name))
            continue
        parts = normalized.split("/")
        if parts[0] != expected_root:
            findings.append(AuditFinding(path.name, "unexpected-entry", name))
            continue
        relative_parts = parts[1:]
        if not relative_parts:
            continue
        relative = "/".join(relative_parts)
        if len(relative_parts) == 1:
            if relative not in SDIST_ALLOWED_ROOT_FILES:
                findings.append(AuditFinding(path.name, "unexpected-entry", name))
            continue
        root_tree = relative_parts[0]
        if root_tree not in SDIST_ALLOWED_ROOT_TREES or (
            root_tree == "scripts" and relative not in SDIST_ALLOWED_SCRIPT_FILES
        ):
            findings.append(AuditFinding(path.name, "unexpected-entry", name))

    required_files = (
        "CHANGELOG.md",
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "scripts/release-build-constraints.txt",
    )
    for relative in required_files:
        member = f"{expected_root}/{relative}"
        if member not in normalized_names:
            findings.append(_missing_member_finding(path, member))

    required_trees = ("docs/", "examples/saas_revenue/", "src/csvql/")
    for relative in required_trees:
        member = f"{expected_root}/{relative}"
        member_without_slash = member.rstrip("/")
        if not any(
            name == member_without_slash or name.startswith(member) for name in normalized_names
        ):
            findings.append(_missing_member_finding(path, member))
    return findings


def audit_archive(path: Path, expected_version: str) -> list[AuditFinding]:
    """Audit one exact release archive without exposing matched secret values."""

    wheel_name = f"localql-{expected_version}-py3-none-any.whl"
    sdist_name = f"localql-{expected_version}.tar.gz"
    if path.name == wheel_name:
        findings = size_findings(path, WHEEL_SIZE_LIMIT)
        names_reader = archive_names_from_wheel
        content_checker = _wheel_content_findings
    elif path.name == sdist_name:
        findings = size_findings(path, SDIST_SIZE_LIMIT)
        names_reader = archive_names_from_sdist
        content_checker = _sdist_content_findings
    else:
        return [AuditFinding(path.name, "archive-identity")]

    try:
        names = names_reader(path)
        findings.extend(content_checker(path, names, expected_version))
        findings.extend(secret_findings(path))
    except (OSError, tarfile.TarError, zipfile.BadZipFile):
        findings.append(AuditFinding(path.name, "invalid-archive"))
    return findings


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
