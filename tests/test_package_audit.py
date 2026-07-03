from __future__ import annotations

import importlib.util
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_audit_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "audit_package_contents",
        REPO_ROOT / "scripts" / "audit_package_contents.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit_module = load_audit_module()
audit_archives = audit_module.audit_archives
find_archives = audit_module.find_archives
forbidden_entries = audit_module.forbidden_entries


def write_wheel(path: Path, names: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, "")


def write_sdist(path: Path, names: list[str]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name in names:
            file_path = path.parent / name.replace("/", "_")
            file_path.write_text("", encoding="utf-8")
            archive.add(file_path, arcname=name)


def test_forbidden_entries_detects_internal_and_ignored_paths() -> None:
    names = [
        "localql-1.0.0/README.md",
        "localql-1.0.0/docs/superpowers/specs/design.md",
        "localql-1.0.0/.DS_Store",
        "localql-1.0.0/output/proof.json",
        "localql-1.0.0/csvql_project_pack.zip",
    ]

    assert forbidden_entries(names) == [
        "localql-1.0.0/docs/superpowers/specs/design.md",
        "localql-1.0.0/.DS_Store",
        "localql-1.0.0/output/proof.json",
        "localql-1.0.0/csvql_project_pack.zip",
    ]


def test_find_archives_requires_wheel_and_sdist(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.0-py3-none-any.whl"
    sdist = tmp_path / "localql-1.0.0.tar.gz"
    wheel.write_text("", encoding="utf-8")
    sdist.write_text("", encoding="utf-8")

    assert find_archives(tmp_path) == ([wheel], [sdist])


def test_audit_archives_accepts_clean_package(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.0-py3-none-any.whl"
    sdist = tmp_path / "localql-1.0.0.tar.gz"
    write_wheel(wheel, ["csvql/__init__.py", "localql-1.0.0.dist-info/METADATA"])
    write_sdist(sdist, ["localql-1.0.0/README.md", "localql-1.0.0/src/csvql/__init__.py"])

    audit_archives([wheel], [sdist])


def test_audit_archives_rejects_forbidden_package_entries(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.0-py3-none-any.whl"
    sdist = tmp_path / "localql-1.0.0.tar.gz"
    write_wheel(wheel, ["csvql/__init__.py", ".DS_Store"])
    write_sdist(sdist, ["localql-1.0.0/README.md"])

    with pytest.raises(SystemExit, match="Forbidden package entries"):
        audit_archives([wheel], [sdist])
