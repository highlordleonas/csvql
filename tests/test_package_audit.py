from __future__ import annotations

import importlib.util
import io
import stat
import sys
import tarfile
import tomllib
import warnings
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Literal

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

WheelEntry = tuple[str | zipfile.ZipInfo, str | bytes]
TarEntry = tuple[str | tarfile.TarInfo, str | bytes]
ArchiveKind = Literal["wheel", "sdist"]


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


def write_wheel(
    path: Path,
    members: dict[str, str | bytes] | list[WheelEntry],
) -> None:
    entries = list(members.items()) if isinstance(members, dict) else members
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for member, content in entries:
                archive.writestr(member, content, compress_type=zipfile.ZIP_DEFLATED)


def write_sdist(
    path: Path,
    members: dict[str, str | bytes] | list[TarEntry],
) -> None:
    entries = list(members.items()) if isinstance(members, dict) else members
    with tarfile.open(path, "w:gz") as archive:
        for member, content in entries:
            raw = content.encode() if isinstance(content, str) else content
            info = tarfile.TarInfo(member) if isinstance(member, str) else member
            if info.isfile() or raw:
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
            else:
                info.size = 0
                archive.addfile(info)


def valid_wheel_members(version: str = "1.0.2") -> dict[str, str | bytes]:
    dist_info = f"localql-{version}.dist-info"
    return {
        "csvql/__init__.py": "",
        f"{dist_info}/METADATA": "Metadata-Version: 2.4\n",
        f"{dist_info}/WHEEL": "Wheel-Version: 1.0\n",
        f"{dist_info}/entry_points.txt": "[console_scripts]\n",
        f"{dist_info}/RECORD": "",
        f"{dist_info}/licenses/LICENSE": "MIT License\n",
    }


def valid_sdist_members(version: str = "1.0.2") -> dict[str, str | bytes]:
    root = f"localql-{version}"
    return {
        f"{root}/CHANGELOG.md": "# Changelog\n",
        f"{root}/CODE_OF_CONDUCT.md": "# Code of Conduct\n",
        f"{root}/CONTRIBUTING.md": "# Contributing\n",
        f"{root}/LICENSE": "MIT License\n",
        f"{root}/PKG-INFO": "Metadata-Version: 2.4\n",
        f"{root}/README.md": "# LocalQL\n",
        f"{root}/SECURITY.md": "# Security\n",
        f"{root}/SUPPORT.md": "# Support\n",
        f"{root}/docs/getting-started.md": "# Getting started\n",
        f"{root}/examples/saas_revenue/README.md": "# Example\n",
        f"{root}/pyproject.toml": '[project]\nname = "localql"\n',
        f"{root}/scripts/release-build-constraints.txt": "hatchling==1.28.0\n",
        f"{root}/src/csvql/__init__.py": "",
    }


def wheel_special_member(
    name: str,
    file_type: int,
    content: str | bytes = b"",
) -> WheelEntry:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (file_type | 0o777) << 16
    return info, content


def wheel_symlink(name: str, target: str = "target") -> WheelEntry:
    return wheel_special_member(name, stat.S_IFLNK, target)


def wheel_directory(name: str, content: str | bytes = b"") -> WheelEntry:
    return wheel_special_member(name, stat.S_IFDIR, content)


def tar_special_member(name: str, member_type: bytes) -> TarEntry:
    info = tarfile.TarInfo(name)
    info.type = member_type
    if member_type in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
        info.linkname = "target"
    return info, b""


def finding_pairs(findings: list[object]) -> list[tuple[str, str | None]]:
    return [(finding.category, finding.member) for finding in findings]


def write_secret_archive(
    tmp_path: Path,
    archive_kind: ArchiveKind,
    filename: str,
    content: str | bytes,
) -> tuple[Path, str]:
    if archive_kind == "wheel":
        path = tmp_path / "localql-1.0.2-py3-none-any.whl"
        member_name = f"csvql/{filename}"
        members = valid_wheel_members()
        members[member_name] = content
        write_wheel(path, members)
    else:
        path = tmp_path / "localql-1.0.2.tar.gz"
        member_name = f"localql-1.0.2/src/csvql/{filename}"
        members = valid_sdist_members()
        members[member_name] = content
        write_sdist(path, members)
    return path, member_name


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

    assert forbidden_entries(names) == names[1:]


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


@pytest.mark.parametrize(
    "symlink_name",
    ["localql-1.0.2-py3-none-any.whl", "localql-1.0.2.tar.gz"],
)
def test_find_archives_rejects_symlinked_exact_artifact(tmp_path: Path, symlink_name: str) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    target = tmp_path / symlink_name
    target.write_text("", encoding="utf-8")
    for artifact_name in ("localql-1.0.2-py3-none-any.whl", "localql-1.0.2.tar.gz"):
        artifact = dist_dir / artifact_name
        if artifact_name == symlink_name:
            artifact.symlink_to(target)
        else:
            artifact.write_text("", encoding="utf-8")

    with pytest.raises(SystemExit, match="regular files within"):
        find_archives(dist_dir, "1.0.2")


def test_find_archives_redacts_untrusted_artifact_names(tmp_path: Path) -> None:
    synthetic = "pypi-" + "A" * 40
    (tmp_path / "localql-1.0.2-py3-none-any.whl").write_text("", encoding="utf-8")
    (tmp_path / "localql-1.0.2.tar.gz").write_text("", encoding="utf-8")
    (tmp_path / f"other-{synthetic}\n\x1b[31m.whl").write_text("", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        find_archives(tmp_path, "1.0.2")

    message = str(exc_info.value)
    assert synthetic not in message
    assert "\n" not in message
    assert "\x1b" not in message


def test_find_archives_sanitizes_expected_version_in_error_text(tmp_path: Path) -> None:
    synthetic = "pypi-" + "A" * 40
    expected_version = f"1.0.2-{synthetic}\n\x1b[31mfound: forged"

    with pytest.raises(SystemExit) as exc_info:
        find_archives(tmp_path, expected_version)

    message = str(exc_info.value)
    assert synthetic not in message
    assert "<redacted>" in message
    assert "\n" not in message
    assert "\x1b" not in message


def test_archive_size_ceiling_is_fail_closed(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    wheel.write_bytes(b"x" * (1024 * 1024 + 1))

    findings = audit_module.size_findings(wheel, 1024 * 1024)

    assert finding_pairs(findings) == [("size-ceiling", None)]


def test_compressed_size_failure_short_circuits_before_archive_open(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    wheel.write_bytes(b"not-a-zip" + b"x" * audit_module.WHEEL_SIZE_LIMIT)

    findings = audit_module.audit_archive(wheel, "1.0.2")

    assert finding_pairs(findings) == [("size-ceiling", None)]


def test_expanded_size_and_chunk_limits_are_explicit() -> None:
    assert getattr(audit_module, "MEMBER_EXPANDED_SIZE_LIMIT", None) == 5 * 1024 * 1024
    assert getattr(audit_module, "WHEEL_EXPANDED_SIZE_LIMIT", None) == (
        10 * audit_module.WHEEL_SIZE_LIMIT
    )
    assert getattr(audit_module, "SDIST_EXPANDED_SIZE_LIMIT", None) == (
        10 * audit_module.SDIST_SIZE_LIMIT
    )
    assert getattr(audit_module, "SCAN_CHUNK_SIZE", None) == 64 * 1024


def test_metadata_rejects_oversized_member_before_secret_scan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(audit_module, "MEMBER_EXPANDED_SIZE_LIMIT", 64, raising=False)
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    members = valid_wheel_members()
    members["csvql/__init__.py"] = "pypi-" + "A" * 40
    members["csvql/large.txt"] = b"x" * 65
    write_wheel(wheel, members)

    findings = audit_module.audit_archive(wheel, "1.0.2")

    assert ("expanded-member-size", "csvql/large.txt") in finding_pairs(findings)
    assert all(finding.category != "pypi-token" for finding in findings)


def test_metadata_rejects_cumulative_expanded_size_before_payload_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(audit_module, "MEMBER_EXPANDED_SIZE_LIMIT", 128, raising=False)
    monkeypatch.setattr(audit_module, "WHEEL_EXPANDED_SIZE_LIMIT", 100, raising=False)
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    members = valid_wheel_members()
    members["csvql/a.txt"] = b"a" * 60
    members["csvql/b.txt"] = b"b" * 60
    write_wheel(wheel, members)

    findings = audit_module.audit_archive(wheel, "1.0.2")

    assert ("expanded-total-size", None) in finding_pairs(findings)


def test_audit_opens_each_archive_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    write_wheel(wheel, valid_wheel_members())
    write_sdist(sdist, valid_sdist_members())
    zip_opens = 0
    tar_opens = 0
    original_zip_init = zipfile.ZipFile.__init__
    original_tar_open = tarfile.open

    def counting_zip_init(self: zipfile.ZipFile, *args: object, **kwargs: object) -> None:
        nonlocal zip_opens
        zip_opens += 1
        original_zip_init(self, *args, **kwargs)

    def counting_tar_open(*args: object, **kwargs: object) -> tarfile.TarFile:
        nonlocal tar_opens
        tar_opens += 1
        return original_tar_open(*args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "__init__", counting_zip_init)
    monkeypatch.setattr(tarfile, "open", counting_tar_open)

    assert audit_module.audit_archive(wheel, "1.0.2") == []
    assert audit_module.audit_archive(sdist, "1.0.2") == []
    assert (zip_opens, tar_opens) == (1, 1)


def test_secret_scan_reads_payloads_in_bounded_chunks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    write_wheel(wheel, valid_wheel_members())
    read_sizes: list[int] = []
    original_read = zipfile.ZipExtFile.read

    def counting_read(self: zipfile.ZipExtFile, size: int = -1) -> bytes:
        read_sizes.append(size)
        return original_read(self, size)

    monkeypatch.setattr(zipfile.ZipExtFile, "read", counting_read)

    assert audit_module.audit_archive(wheel, "1.0.2") == []
    assert read_sizes
    assert set(read_sizes) == {64 * 1024}


@pytest.mark.parametrize("archive_kind", ["wheel", "sdist"])
def test_secret_scan_reports_all_categories_for_each_archive_and_deduplicates(
    tmp_path: Path, archive_kind: ArchiveKind
) -> None:
    synthetic_values = [
        "AKIA" + "A" * 16,
        "ghp_" + "B" * 20,
        "-----BEGIN PRIVATE KEY-----",
        "pypi-" + "C" * 40,
    ]
    archive, member_name = write_secret_archive(
        tmp_path,
        archive_kind,
        "synthetic.py",
        "\n".join([*synthetic_values, synthetic_values[-1]]),
    )

    findings = audit_module.secret_findings(archive)

    assert finding_pairs(findings) == [
        ("aws-access-key", member_name),
        ("github-token", member_name),
        ("private-key", member_name),
        ("pypi-token", member_name),
    ]
    for synthetic in synthetic_values:
        assert synthetic not in repr(findings)


def test_secret_scan_finds_token_across_chunk_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(audit_module, "SCAN_CHUNK_SIZE", 16, raising=False)
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    synthetic = "pypi-" + "A" * 40
    members = valid_wheel_members()
    members["csvql/chunked.py"] = "." * 14 + synthetic
    write_wheel(wheel, members)

    findings = audit_module.secret_findings(wheel)

    assert ("pypi-token", "csvql/chunked.py") in finding_pairs(findings)


@pytest.mark.parametrize("archive_kind", ["wheel", "sdist"])
def test_secret_scan_skips_binary_members_containing_nul(
    tmp_path: Path, archive_kind: ArchiveKind
) -> None:
    archive, member_name = write_secret_archive(
        tmp_path,
        archive_kind,
        "data.bin",
        b"pypi-" + b"A" * 40 + b"\0",
    )

    assert all(finding.member != member_name for finding in audit_module.secret_findings(archive))


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

    assert ("unexpected-entry", "README.md") in finding_pairs(findings)
    assert (
        "missing-required-entry",
        "localql-1.0.2.dist-info/RECORD",
    ) in finding_pairs(findings)


def test_audit_archive_rejects_duplicate_raw_wheel_member(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    entries: list[WheelEntry] = list(valid_wheel_members().items())
    entries.extend([("csvql/duplicate.py", "one"), ("csvql/duplicate.py", "two")])
    write_wheel(wheel, entries)

    findings = audit_module.audit_archive(wheel, "1.0.2")

    assert ("duplicate-entry", "csvql/duplicate.py") in finding_pairs(findings)


def test_audit_archive_rejects_duplicate_normalized_wheel_member(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    members = valid_wheel_members()
    members["csvql/duplicate.py"] = "one"
    members["csvql//duplicate.py"] = "two"
    write_wheel(wheel, members)

    findings = audit_module.audit_archive(wheel, "1.0.2")

    assert any(finding.category == "duplicate-normalized-entry" for finding in findings)


def test_audit_archive_rejects_zip_unix_symlink(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    entries: list[WheelEntry] = list(valid_wheel_members().items())
    entries.append(wheel_symlink("csvql/link.py"))
    write_wheel(wheel, entries)

    findings = audit_module.audit_archive(wheel, "1.0.2")

    assert ("special-entry", "csvql/link.py") in finding_pairs(findings)


@pytest.mark.parametrize(
    "file_type",
    [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFBLK],
)
def test_trailing_slash_zip_special_entry_does_not_satisfy_required_tree(
    tmp_path: Path, file_type: int
) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    members = valid_wheel_members()
    members.pop("csvql/__init__.py")
    entries: list[WheelEntry] = list(members.items())
    entries.append(wheel_special_member("csvql/", file_type))
    write_wheel(wheel, entries)

    findings = audit_module.audit_archive(wheel, "1.0.2")

    assert ("special-entry", "csvql/") in finding_pairs(findings)
    assert ("missing-required-entry", "csvql/") in finding_pairs(findings)


def test_audit_archive_rejects_payload_bearing_zip_directory(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    entries: list[WheelEntry] = list(valid_wheel_members().items())
    entries.append(wheel_directory("csvql/data/", b"not-empty"))
    write_wheel(wheel, entries)

    findings = audit_module.audit_archive(wheel, "1.0.2")

    assert ("directory-payload", "csvql/data/") in finding_pairs(findings)


def test_required_wheel_file_must_be_regular(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    members = valid_wheel_members()
    members.pop("localql-1.0.2.dist-info/RECORD")
    entries: list[WheelEntry] = list(members.items())
    entries.append(wheel_symlink("localql-1.0.2.dist-info/RECORD"))
    write_wheel(wheel, entries)

    findings = audit_module.audit_archive(wheel, "1.0.2")

    assert (
        "special-entry",
        "localql-1.0.2.dist-info/RECORD",
    ) in finding_pairs(findings)


def test_required_wheel_tree_needs_regular_descendant(tmp_path: Path) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    members = valid_wheel_members()
    members.pop("csvql/__init__.py")
    entries: list[WheelEntry] = list(members.items())
    entries.append(wheel_symlink("csvql/__init__.py"))
    write_wheel(wheel, entries)

    findings = audit_module.audit_archive(wheel, "1.0.2")

    assert ("special-entry", "csvql/__init__.py") in finding_pairs(findings)
    assert ("missing-required-entry", "csvql/") in finding_pairs(findings)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "/",
        "////",
        "csvql\\evil.py",
        "C:/evil.py",
        "/absolute.py",
        "csvql//evil.py",
        "csvql/./evil.py",
        "csvql/../evil.py",
        "csvql/evil\n.py",
    ],
)
def test_member_name_validator_rejects_hostile_forms(name: str) -> None:
    assert audit_module._is_safe_archive_member(name) is False


@pytest.mark.parametrize(
    "name",
    [
        "csvql\\evil.py",
        "C:/evil.py",
        "/absolute.py",
        "csvql//evil.py",
        "csvql/./evil.py",
        "csvql/../evil.py",
        "csvql/evil\n.py",
    ],
)
def test_audit_archive_rejects_hostile_wheel_member_names(tmp_path: Path, name: str) -> None:
    wheel = tmp_path / "localql-1.0.2-py3-none-any.whl"
    members = valid_wheel_members()
    members[name] = "hostile\n"
    write_wheel(wheel, members)

    findings = audit_module.audit_archive(wheel, "1.0.2")

    assert any(finding.category == "unsafe-member-name" for finding in findings)


def test_audit_archive_accepts_complete_permitted_sdist_contract(tmp_path: Path) -> None:
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    members = valid_sdist_members()
    expected_root_files = {
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
    assert {
        name.removeprefix("localql-1.0.2/")
        for name in members
        if "/" not in name.removeprefix("localql-1.0.2/")
    } == expected_root_files
    write_sdist(sdist, members)

    assert audit_module.audit_archive(sdist, "1.0.2") == []


@pytest.mark.parametrize(
    "member_type",
    [
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.FIFOTYPE,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
        b"Z",
    ],
)
def test_audit_archive_rejects_tar_special_members(tmp_path: Path, member_type: bytes) -> None:
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    entries: list[TarEntry] = list(valid_sdist_members().items())
    entries.append(tar_special_member("localql-1.0.2/docs/special", member_type))
    write_sdist(sdist, entries)

    findings = audit_module.audit_archive(sdist, "1.0.2")

    assert ("special-entry", "localql-1.0.2/docs/special") in finding_pairs(findings)


def test_audit_archive_rejects_payload_bearing_tar_directory(tmp_path: Path) -> None:
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    entries: list[TarEntry] = list(valid_sdist_members().items())
    directory = tarfile.TarInfo("localql-1.0.2/docs/data/")
    directory.type = tarfile.DIRTYPE
    entries.append((directory, b"not-empty"))
    write_sdist(sdist, entries)

    findings = audit_module.audit_archive(sdist, "1.0.2")

    assert ("directory-payload", "localql-1.0.2/docs/data") in finding_pairs(findings)


def test_required_sdist_tree_accepts_real_directory_entry(tmp_path: Path) -> None:
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    members = valid_sdist_members()
    members.pop("localql-1.0.2/docs/getting-started.md")
    entries: list[TarEntry] = list(members.items())
    directory = tarfile.TarInfo("localql-1.0.2/docs/")
    directory.type = tarfile.DIRTYPE
    entries.append((directory, b""))
    write_sdist(sdist, entries)

    assert audit_module.audit_archive(sdist, "1.0.2") == []


def test_audit_archive_rejects_duplicate_raw_sdist_member(tmp_path: Path) -> None:
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    entries: list[TarEntry] = list(valid_sdist_members().items())
    duplicate = "localql-1.0.2/src/csvql/duplicate.py"
    entries.extend([(duplicate, "one"), (duplicate, "two")])
    write_sdist(sdist, entries)

    findings = audit_module.audit_archive(sdist, "1.0.2")

    assert ("duplicate-entry", duplicate) in finding_pairs(findings)


def test_audit_archive_rejects_duplicate_normalized_sdist_member(tmp_path: Path) -> None:
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    members = valid_sdist_members()
    members["localql-1.0.2/src/csvql/duplicate.py"] = "one"
    members["localql-1.0.2/src/csvql//duplicate.py"] = "two"
    write_sdist(sdist, members)

    findings = audit_module.audit_archive(sdist, "1.0.2")

    assert any(finding.category == "duplicate-normalized-entry" for finding in findings)


def test_required_sdist_file_must_be_regular(tmp_path: Path) -> None:
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    members = valid_sdist_members()
    required_member = "localql-1.0.2/README.md"
    members.pop(required_member)
    entries: list[TarEntry] = list(members.items())
    entries.append(tar_special_member(required_member, tarfile.SYMTYPE))
    write_sdist(sdist, entries)

    findings = audit_module.audit_archive(sdist, "1.0.2")

    assert ("special-entry", required_member) in finding_pairs(findings)
    assert ("missing-required-entry", required_member) in finding_pairs(findings)


def test_required_sdist_tree_rejects_special_entry_without_regular_descendant(
    tmp_path: Path,
) -> None:
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    members = valid_sdist_members()
    members.pop("localql-1.0.2/docs/getting-started.md")
    entries: list[TarEntry] = list(members.items())
    entries.append(tar_special_member("localql-1.0.2/docs", tarfile.SYMTYPE))
    write_sdist(sdist, entries)

    findings = audit_module.audit_archive(sdist, "1.0.2")

    assert ("special-entry", "localql-1.0.2/docs") in finding_pairs(findings)
    assert (
        "missing-required-entry",
        "localql-1.0.2/docs/",
    ) in finding_pairs(findings)


@pytest.mark.parametrize(
    "name",
    [
        "localql-1.0.2\\evil.py",
        "C:/evil.py",
        "/localql-1.0.2/absolute.py",
        "localql-1.0.2//docs/evil.py",
        "localql-1.0.2/./docs/evil.py",
        "localql-1.0.2/../README.md",
        "localql-1.0.2/docs/evil\n.md",
    ],
)
def test_audit_archive_rejects_hostile_sdist_member_names(tmp_path: Path, name: str) -> None:
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    members = valid_sdist_members()
    members[name] = "hostile\n"
    write_sdist(sdist, members)

    findings = audit_module.audit_archive(sdist, "1.0.2")

    assert any(finding.category == "unsafe-member-name" for finding in findings)


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

    assert ("unexpected-entry", expected_member) in finding_pairs(findings)


def test_audit_archive_rejects_sdist_missing_required_tree(tmp_path: Path) -> None:
    sdist = tmp_path / "localql-1.0.2.tar.gz"
    members = valid_sdist_members()
    members.pop("localql-1.0.2/examples/saas_revenue/README.md")
    write_sdist(sdist, members)

    findings = audit_module.audit_archive(sdist, "1.0.2")

    assert (
        "missing-required-entry",
        "localql-1.0.2/examples/saas_revenue/",
    ) in finding_pairs(findings)


def test_audit_finding_sanitizes_untrusted_member_before_storage() -> None:
    synthetic = "pypi-" + "A" * 40
    finding = audit_module.AuditFinding(
        "localql-1.0.2.tar.gz",
        "unsafe-member-name",
        f"csvql/report-{synthetic}\n\x1b[31m.py",
    )

    assert finding.member == "csvql/report-<redacted>??[31m.py"
    assert synthetic not in repr(finding)


@pytest.mark.parametrize("archive_kind", ["wheel", "sdist"])
def test_secret_finding_sanitizes_token_shaped_member_name(
    tmp_path: Path, archive_kind: ArchiveKind
) -> None:
    synthetic = "pypi-" + "A" * 40
    archive, member_name = write_secret_archive(
        tmp_path, archive_kind, f"{synthetic}.py", synthetic
    )

    findings = audit_module.secret_findings(archive)

    assert (
        "pypi-token",
        member_name.replace(synthetic, "<redacted>"),
    ) in finding_pairs(findings)
    assert synthetic not in repr(findings)


def test_render_findings_is_redacted_stable_and_terminal_safe() -> None:
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
