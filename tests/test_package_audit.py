from __future__ import annotations

import importlib.util
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SDIST_INCLUDES = [
    "/CHANGELOG.md",
    "/CODE_OF_CONDUCT.md",
    "/CONTRIBUTING.md",
    "/LICENSE",
    "/README.md",
    "/SECURITY.md",
    "/SUPPORT.md",
    "/docs",
    "/examples",
    "/pyproject.toml",
    "/scripts/release-build-constraints.txt",
    "/src",
]


def load_audit_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "audit_package_contents",
        REPO_ROOT / "scripts" / "audit_package_contents.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit_module = load_audit_module()
find_archives = audit_module.find_archives
forbidden_entries = audit_module.forbidden_entries


def write_wheel(path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def write_sdist(path: Path, members: dict[str, str]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for index, (name, content) in enumerate(members.items()):
            file_path = path.parent / f"sdist-member-{index}"
            file_path.write_text(content, encoding="utf-8")
            archive.add(file_path, arcname=name)


def valid_wheel_members(version: str = "1.0.2") -> dict[str, str]:
    dist_info = f"localql-{version}.dist-info"
    return {
        "csvql/__init__.py": "",
        f"{dist_info}/METADATA": "Metadata-Version: 2.4\n",
        f"{dist_info}/WHEEL": "Wheel-Version: 1.0\n",
        f"{dist_info}/entry_points.txt": "[console_scripts]\n",
        f"{dist_info}/RECORD": "",
        f"{dist_info}/licenses/LICENSE": "MIT License\n",
    }


def valid_sdist_members(version: str = "1.0.2") -> dict[str, str]:
    root = f"localql-{version}"
    return {
        f"{root}/CHANGELOG.md": "# Changelog\n",
        f"{root}/LICENSE": "MIT License\n",
        f"{root}/README.md": "# LocalQL\n",
        f"{root}/docs/getting-started.md": "# Getting started\n",
        f"{root}/examples/saas_revenue/README.md": "# Example\n",
        f"{root}/pyproject.toml": '[project]\nname = "localql"\n',
        f"{root}/scripts/release-build-constraints.txt": "hatchling==1.28.0\n",
        f"{root}/src/csvql/__init__.py": "",
    }


def test_forbidden_entries_detects_internal_and_ignored_paths() -> None:
    names = [
        "localql-1.0.2/README.md",
        "localql-1.0.2/docs/superpowers/specs/design.md",
        "localql-1.0.2/docs/governance/audits/stewardship.md",
        "localql-1.0.2/docs/release-candidate-proof-2026-07-03.md",
        "localql-1.0.2/.DS_Store",
        "localql-1.0.2/output/proof.json",
        "localql-1.0.2/csvql_project_pack.zip",
    ]

    assert forbidden_entries(names) == [
        "localql-1.0.2/docs/superpowers/specs/design.md",
        "localql-1.0.2/docs/governance/audits/stewardship.md",
        "localql-1.0.2/docs/release-candidate-proof-2026-07-03.md",
        "localql-1.0.2/.DS_Store",
        "localql-1.0.2/output/proof.json",
        "localql-1.0.2/csvql_project_pack.zip",
    ]


def test_sdist_build_config_excludes_non_distribution_governance() -> None:
    payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    sdist_target = (
        payload.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("sdist", {})
    )

    assert sdist_target.get("include") == EXPECTED_SDIST_INCLUDES
    assert set(sdist_target.get("exclude", [])) == {
        "/docs/governance/audits",
        "/docs/superpowers",
    }


def test_find_archives_requires_exact_release_pair(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    wheel.write_text("", encoding="utf-8")
    sdist.write_text("", encoding="utf-8")

    assert find_archives(tmp_path, "1.0.2") == (wheel, sdist)


@pytest.mark.parametrize(
    "unexpected_name",
    [
        "localql-1.0.1-py3-none-any.whl",
        "localql-1.0.2-py3-none-macosx.whl",
        "localql-1.0.1.tar.gz",
    ],
)
def test_find_archives_rejects_extra_or_differently_named_archives(
    tmp_path: Path, unexpected_name: str
) -> None:
    (tmp_path / "localql-1.0.2-py3-none-any.whl").write_text("", encoding="utf-8")
    (tmp_path / "localql-1.0.2.tar.gz").write_text("", encoding="utf-8")
    (tmp_path / unexpected_name).write_text("", encoding="utf-8")

    with pytest.raises(SystemExit, match="exact release archives"):
        find_archives(tmp_path, "1.0.2")


def test_archive_size_ceiling_is_fail_closed(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    wheel.write_bytes(b"x" * (1024 * 1024 + 1))

    findings = audit_module.size_findings(wheel, 1024 * 1024)

    assert [(finding.category, finding.member) for finding in findings] == [("size-ceiling", None)]


def test_secret_scan_reports_category_and_member_without_value(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    synthetic = "pypi-" + "A" * 40
    write_wheel(
        wheel,
        {
            "csvql/__init__.py": synthetic,
            "localql-1.0.2.dist-info/METADATA": "Metadata-Version: 2.4\n",
        },
    )

    findings = audit_module.secret_findings(wheel)

    assert [(finding.category, finding.member) for finding in findings] == [
        ("pypi-token", "csvql/__init__.py")
    ]
    assert synthetic not in repr(findings)


def test_secret_scan_skips_binary_members_containing_nul(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("csvql/data.bin", b"\x00pypi-" + b"A" * 40)

    assert audit_module.secret_findings(wheel) == []


def test_audit_archive_accepts_required_wheel_members(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    write_wheel(wheel, valid_wheel_members())

    assert audit_module.audit_archive(wheel, "1.0.2") == []


def test_audit_archive_rejects_wheel_readme_and_missing_record(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    members = valid_wheel_members()
    members.pop("localql-1.0.2.dist-info/RECORD")
    members["README.md"] = "# LocalQL\n"
    write_wheel(wheel, members)

    findings = audit_module.audit_archive(wheel, "1.0.2")

    assert any(finding.member == "README.md" for finding in findings)
    assert any(finding.member == "localql-1.0.2.dist-info/RECORD" for finding in findings)


def test_audit_archive_rejects_traversal_shaped_member(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    members = valid_wheel_members()
    members["csvql/../README.md"] = "# LocalQL\n"
    write_wheel(wheel, members)

    findings = audit_module.audit_archive(wheel, "1.0.2")

    assert any(finding.member == "csvql/../README.md" for finding in findings)


def test_audit_archive_accepts_required_sdist_members(tmp_path: Path) -> None:
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    write_sdist(sdist, valid_sdist_members())

    assert audit_module.audit_archive(sdist, "1.0.2") == []


@pytest.mark.parametrize(
    ("unexpected_member", "expected_member"),
    [
        ("localql-1.0.2/Makefile", "localql-1.0.2/Makefile"),
        (
            "localql-1.0.2/scripts/verify_release_readiness.py",
            "localql-1.0.2/scripts/verify_release_readiness.py",
        ),
        ("other-root/README.md", "other-root/README.md"),
    ],
)
def test_audit_archive_rejects_sdist_members_outside_allowlist(
    tmp_path: Path, unexpected_member: str, expected_member: str
) -> None:
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    members = valid_sdist_members()
    members[unexpected_member] = "unexpected\n"
    write_sdist(sdist, members)

    findings = audit_module.audit_archive(sdist, "1.0.2")

    assert any(finding.member == expected_member for finding in findings)


def test_audit_archive_rejects_sdist_missing_required_tree(tmp_path: Path) -> None:
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    members = valid_sdist_members()
    members.pop("localql-1.0.2/examples/saas_revenue/README.md")
    write_sdist(sdist, members)

    findings = audit_module.audit_archive(sdist, "1.0.2")

    assert any(finding.member == "localql-1.0.2/examples/saas_revenue/" for finding in findings)


def test_render_findings_is_redacted_and_stable() -> None:
    findings = [
        audit_module.AuditFinding("localql-1.0.2.tar.gz", "size-ceiling"),
        audit_module.AuditFinding(
            "localql-1.0.2-py3-none-any.whl",
            "pypi-token",
            "csvql/__init__.py",
        ),
    ]

    assert audit_module.render_findings(findings) == (
        "localql-1.0.2.tar.gz: size-ceiling\n"
        "localql-1.0.2-py3-none-any.whl: pypi-token in csvql/__init__.py"
    )


def test_cli_requires_expected_version(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["audit_package_contents.py", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        audit_module.main()

    assert exc_info.value.code == 2


def test_cli_failure_is_redacted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    synthetic = "pypi-" + "A" * 40
    wheel_members = valid_wheel_members()
    wheel_members["csvql/__init__.py"] = synthetic
    write_wheel(wheel, wheel_members)
    write_sdist(sdist, valid_sdist_members())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_package_contents.py",
            str(tmp_path),
            "--expected-version",
            "1.0.2",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        audit_module.main()

    assert str(exc_info.value) == (
        "Package audit failed:\nlocalql-1.0.2-py3-none-any.whl: pypi-token in csvql/__init__.py"
    )
    assert synthetic not in str(exc_info.value)
