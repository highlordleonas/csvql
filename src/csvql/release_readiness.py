"""Helpers for repo-local release-readiness verification."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_VERSION_RE = re.compile(r'^__version__ = "(?P<version>[^"]+)"$', re.MULTILINE)


def read_pyproject_version(pyproject_path: Path) -> str:
    """Return the package version declared in ``pyproject.toml``."""

    payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def read_package_version(init_path: Path) -> str:
    """Return the package ``__version__`` string from ``__init__.py``."""

    match = _VERSION_RE.search(init_path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"Could not find __version__ in {init_path}")
    return match.group("version")


def version_strings_match(pyproject_version: str, package_version: str, cli_version: str) -> bool:
    """Return whether all release-proof version strings agree."""

    return pyproject_version == package_version == cli_version


def select_built_wheel(dist_dir: Path, version: str) -> Path:
    """Return the built wheel for ``version`` from ``dist_dir``."""

    matches = sorted(dist_dir.glob(f"csvql-{version}-*.whl"))
    if not matches:
        raise FileNotFoundError(f"No wheel found for csvql {version} in {dist_dir}")
    return matches[0]
