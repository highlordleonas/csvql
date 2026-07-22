from __future__ import annotations

import importlib.util
import tarfile
import tomllib
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
is_protected_package_path = audit_module.is_protected_package_path


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


def test_forbidden_entries_detects_protected_and_ignored_paths() -> None:
    names = [
        "localql-1.0.0/README.md",
        "localql-1.0.0/.internal/release-proof.md",
        "localql-1.0.0/docs/superpowers/specs/design.md",
        "localql-1.0.0/docs/CODEX_CAPABILITY_REVIEW.md",
        "localql-1.0.0/docs/release-candidate-proof-2026-07-03.md",
        "localql-1.0.0/.DS_Store",
        "localql-1.0.0/output/proof.json",
        "localql-1.0.0/csvql_project_pack.zip",
        "localql-1.0.0/AGENTS.md",
        "localql-1.0.0/docs/AGENTS.override.md",
        "localql-1.0.0/.agents/instructions.md",
        "localql-1.0.0/.codex/session.json",
        "localql-1.0.0/docs/reference/.agents/instructions.md",
        "localql-1.0.0/docs/reference/.codex/session.json",
        "localql-1.0.0/docs/.internal/release-proof.md",
    ]

    assert forbidden_entries(names) == [
        "localql-1.0.0/.internal/release-proof.md",
        "localql-1.0.0/docs/superpowers/specs/design.md",
        "localql-1.0.0/docs/CODEX_CAPABILITY_REVIEW.md",
        "localql-1.0.0/docs/release-candidate-proof-2026-07-03.md",
        "localql-1.0.0/.DS_Store",
        "localql-1.0.0/output/proof.json",
        "localql-1.0.0/csvql_project_pack.zip",
        "localql-1.0.0/AGENTS.md",
        "localql-1.0.0/docs/AGENTS.override.md",
        "localql-1.0.0/.agents/instructions.md",
        "localql-1.0.0/.codex/session.json",
        "localql-1.0.0/docs/reference/.agents/instructions.md",
        "localql-1.0.0/docs/reference/.codex/session.json",
        "localql-1.0.0/docs/.internal/release-proof.md",
    ]


@pytest.mark.parametrize(
    "noncanonical_name",
    [
        "./.internal/release-proof.md",
        "localql-1.0.4/docs/./superpowers/design.md",
        "./.agents/instructions.md",
        "./.codex/session.json",
        "C:/.internal/release-proof.md",
        "localql-1.0.4/D:/.agents/instructions.md",
        "E:/.codex/session.json",
    ],
)
def test_forbidden_entries_rejects_noncanonical_names_before_protected_predicate(
    monkeypatch: pytest.MonkeyPatch,
    noncanonical_name: str,
) -> None:
    def predicate_must_not_run(_parts: object) -> bool:
        raise AssertionError("protected predicate must receive canonical names only")

    monkeypatch.setattr(audit_module, "is_protected_package_path", predicate_must_not_run)

    assert forbidden_entries([noncanonical_name]) == [noncanonical_name]


def test_shared_protected_predicate_rejects_private_engineering_artifacts() -> None:
    assert "AGENTS.md" not in audit_module.FORBIDDEN_NAMES
    assert "AGENTS.override.md" not in audit_module.FORBIDDEN_NAMES
    assert is_protected_package_path(("AGENTS.md",))
    assert is_protected_package_path(("docs", "AGENTS.md"))
    assert is_protected_package_path(("docs", "AGENTS.override.md"))
    assert is_protected_package_path(("docs", "CODEX_CAPABILITY_REVIEW.md"))
    assert is_protected_package_path(("docs", "release-candidate-proof-2026-07-03.md"))
    assert is_protected_package_path(("docs", ".internal", "release-proof.md"))
    assert is_protected_package_path(("docs", "reference", ".agents", "instructions.md"))
    assert is_protected_package_path(("docs", "reference", ".codex", "session.json"))
    assert forbidden_entries(["localql-1.0.4/docs/AGENTS.md"]) == ["localql-1.0.4/docs/AGENTS.md"]


@pytest.mark.parametrize(
    "lookalike_parts",
    [
        ("docs", ".internalized", "guide.md"),
        ("docs", "reference", ".agents-guide", "instructions.md"),
        ("docs", "reference", ".codex-config", "session.json"),
    ],
)
def test_protected_predicate_allows_nonmatching_directory_lookalikes(
    lookalike_parts: tuple[str, ...],
) -> None:
    assert not is_protected_package_path(lookalike_parts)


def test_sdist_build_config_explicitly_includes_only_public_package_inputs() -> None:
    payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    sdist_target = (
        payload.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("sdist", {})
    )

    assert sdist_target.get("include") == [
        "/README.md",
        "/LICENSE",
        "/CHANGELOG.md",
        "/docs",
        "/examples",
        "/pyproject.toml",
        "/scripts/release-build-constraints.txt",
        "/src",
    ]

    excluded_paths = set(sdist_target.get("exclude", []))
    assert {
        "/.internal",
        "/docs/superpowers",
        "/AGENTS.md",
        "/AGENTS.override.md",
        "/.agents",
        "/.codex",
        "/output",
    } <= excluded_paths


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


def test_audit_archives_rejects_sdist_without_package_source(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.0-py3-none-any.whl"
    sdist = tmp_path / "localql-1.0.0.tar.gz"
    write_wheel(wheel, ["csvql/__init__.py", "localql-1.0.0.dist-info/METADATA"])
    write_sdist(sdist, ["localql-1.0.0/README.md"])

    with pytest.raises(SystemExit, match="missing src/csvql package files"):
        audit_archives([wheel], [sdist])
