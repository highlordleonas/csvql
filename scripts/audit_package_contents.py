"""Audit built wheel and sdist contents for public release hygiene."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path

WHEEL_SIZE_LIMIT = 1024 * 1024
SDIST_SIZE_LIMIT = 5 * 1024 * 1024
MEMBER_EXPANDED_SIZE_LIMIT = 5 * 1024 * 1024
WHEEL_EXPANDED_SIZE_LIMIT = 10 * WHEEL_SIZE_LIMIT
SDIST_EXPANDED_SIZE_LIMIT = 10 * SDIST_SIZE_LIMIT

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
    "docs/superpowers",
    "docs/CODEX_CAPABILITY_REVIEW.md",
}


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


def find_archives(
    dist_dir: Path, expected_version: str | None = None
) -> tuple[list[Path], list[Path]] | tuple[Path, Path]:
    """Find release archives, or require the exact pair for an expected version."""

    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if not wheels:
        raise SystemExit(f"No wheel found in {dist_dir}")
    if not sdists:
        raise SystemExit(f"No sdist found in {dist_dir}")
    if expected_version is not None:
        expected_wheel = dist_dir / ("localql-" + expected_version + "-py3-none-any.whl")
        expected_sdist = dist_dir / ("localql-" + expected_version + ".tar.gz")
        if set(wheels) != {expected_wheel} or set(sdists) != {expected_sdist}:
            raise SystemExit("Expected exact release archives: one wheel and one sdist.")
        for artifact in (expected_wheel, expected_sdist):
            if artifact.is_symlink() or not artifact.is_file():
                raise SystemExit("Release archives must be regular files.")
        return expected_wheel, expected_sdist
    return wheels, sdists


def audit_archives(wheels: list[Path], sdists: list[Path]) -> None:
    """Validate package archives and raise ``SystemExit`` for forbidden entries."""

    failures: list[str] = []
    for wheel in wheels:
        names = archive_names_from_wheel(wheel)
        if not any(name.startswith("csvql/") for name in names):
            failures.append(f"{wheel}: missing csvql package files")
        for entry in forbidden_entries(names):
            failures.append(f"{wheel}: {entry}")
    for sdist in sdists:
        names = archive_names_from_sdist(sdist)
        if not any("/src/csvql/" in f"/{name}" for name in names):
            failures.append(f"{sdist}: missing src/csvql package files")
        for entry in forbidden_entries(names):
            failures.append(f"{sdist}: {entry}")
    if failures:
        rendered = "\n".join(failures)
        raise SystemExit(f"Forbidden package entries found:\n{rendered}")


def main() -> None:
    """Run the package content audit."""

    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("--expected-version")
    args = parser.parse_args()

    archives = find_archives(args.dist_dir, args.expected_version)
    if args.expected_version is None:
        wheels, sdists = archives
    else:
        wheel, sdist = archives
        wheels, sdists = [wheel], [sdist]
    audit_archives(wheels, sdists)
    print(f"Package content audit passed: {len(wheels)} wheel(s), {len(sdists)} sdist(s).")


if __name__ == "__main__":
    main()
