"""Audit built wheel and sdist contents for public release hygiene."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path

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
    "docs/release-candidate-proof-2026-07-02.md",
}


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
        if any(forbidden in normalized for forbidden in FORBIDDEN_PATH_PARTS):
            blocked.append(name)
    return blocked


def find_archives(dist_dir: Path) -> tuple[list[Path], list[Path]]:
    """Find built wheel and sdist archives in ``dist_dir``."""

    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if not wheels:
        raise SystemExit(f"No wheel found in {dist_dir}")
    if not sdists:
        raise SystemExit(f"No sdist found in {dist_dir}")
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
        for entry in forbidden_entries(names):
            failures.append(f"{sdist}: {entry}")
    if failures:
        rendered = "\n".join(failures)
        raise SystemExit(f"Forbidden package entries found:\n{rendered}")


def main() -> None:
    """Run the package content audit."""

    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    args = parser.parse_args()

    wheels, sdists = find_archives(args.dist_dir)
    audit_archives(wheels, sdists)
    print(f"Package content audit passed: {len(wheels)} wheel(s), {len(sdists)} sdist(s).")


if __name__ == "__main__":
    main()
