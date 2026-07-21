from __future__ import annotations

import email.policy
import hashlib
import importlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import warnings
import zipfile
from dataclasses import FrozenInstanceError, fields
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from types import ModuleType

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_release_artifacts.py"
sys.path.insert(0, str(MODULE_PATH.parents[1]))
EXPECTED_WHEEL = "localql-1.0.5-py3-none-any.whl"
EXPECTED_SDIST = "localql-1.0.5.tar.gz"
DIST_INFO = "localql-1.0.5.dist-info"
SDIST_ROOT = "localql-1.0.5"
SOURCE_COMMIT = "a" * 40
TAG_OBJECT = "b" * 40
CONSTRAINTS_DIGEST = "c" * 64

EXPECTED_METADATA_KEYS = (
    "Name",
    "Version",
    "Summary",
    "Requires-Python",
    "Requires-Dist",
    "Provides-Extra",
    "Project-URL",
    "License-Expression",
    "Classifier",
    "Description-Content-Type",
)

BASE_METADATA: dict[str, list[str]] = {
    "Name": ["localql"],
    "Version": ["1.0.5"],
    "Summary": ["Local CSV analytics"],
    "Requires-Python": [">=3.11,<3.15"],
    "Requires-Dist": ["duckdb<2,>=1.5.0", "typer>=0.12.3"],
    "Provides-Extra": ["tui"],
    "Project-URL": [
        "Documentation, https://example.invalid/docs",
        "Repository, https://example.invalid/repository",
    ],
    "License-Expression": ["MIT"],
    "Classifier": [
        "Environment :: Console",
        "Programming Language :: Python :: 3",
    ],
    "Description-Content-Type": ["text/markdown"],
}
BASE_DESCRIPTION = "# LocalQL\n\nLocal-first CSV analytics."
ENTRY_POINTS = "[console_scripts]\ncsvql = csvql.cli:main\n"


def release_module() -> ModuleType:
    assert MODULE_PATH.is_file(), "release artifact verifier must exist"
    return importlib.import_module("scripts.verify_release_artifacts")


def metadata_bytes(
    *,
    replacements: dict[str, list[str]] | None = None,
    description: str = BASE_DESCRIPTION,
    reverse_repeatable_fields: bool = False,
) -> bytes:
    values = {key: list(items) for key, items in BASE_METADATA.items()}
    if replacements is not None:
        values.update(replacements)
    lines = ["Metadata-Version: 2.4"]
    for key in EXPECTED_METADATA_KEYS:
        field_values = values[key]
        if reverse_repeatable_fields and len(field_values) > 1:
            field_values = list(reversed(field_values))
        lines.extend(f"{key}: {value}" for value in field_values)
    return ("\n".join(lines) + "\n\n" + description + "\n").encode()


def parse_metadata(payload: bytes) -> Message:
    return BytesParser(policy=email.policy.default).parsebytes(payload)


def zip_info(
    name: str,
    *,
    timestamp: tuple[int, int, int, int, int, int] = (2026, 1, 1, 0, 0, 0),
    file_type: int | None = None,
) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=timestamp)
    if file_type is not None:
        info.create_system = 3
        info.external_attr = (file_type | 0o644) << 16
    return info


def wheel_entries(
    metadata: bytes | None = None,
    *,
    entry_points: str | None = ENTRY_POINTS,
    record: str = "record-one\n",
) -> list[tuple[str | zipfile.ZipInfo, bytes | str]]:
    entries: list[tuple[str | zipfile.ZipInfo, bytes | str]] = [
        ("csvql/__init__.py", '__version__ = "1.0.5"\n'),
        (f"{DIST_INFO}/WHEEL", "Wheel-Version: 1.0\n"),
        (f"{DIST_INFO}/RECORD", record),
    ]
    if metadata is not None:
        entries.append((f"{DIST_INFO}/METADATA", metadata))
    if entry_points is not None:
        entries.append((f"{DIST_INFO}/entry_points.txt", entry_points))
    return entries


def write_wheel(
    path: Path,
    entries: list[tuple[str | zipfile.ZipInfo, bytes | str]],
    *,
    timestamp: tuple[int, int, int, int, int, int] = (2026, 1, 1, 0, 0, 0),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for member, content in entries:
                info = zip_info(member, timestamp=timestamp) if isinstance(member, str) else member
                archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED)


def write_sdist(
    path: Path,
    metadata: bytes,
    *,
    metadata_name: str = f"{SDIST_ROOT}/PKG-INFO",
    extra_entries: list[tuple[tarfile.TarInfo, bytes]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo(metadata_name)
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
        readme = b"# LocalQL\n"
        readme_info = tarfile.TarInfo(f"{SDIST_ROOT}/README.md")
        readme_info.size = len(readme)
        archive.addfile(readme_info, io.BytesIO(readme))
        for extra_info, content in extra_entries or []:
            extra_info.size = len(content)
            archive.addfile(extra_info, io.BytesIO(content))


def write_artifact_pair(
    directory: Path,
    *,
    wheel_metadata: bytes | None = None,
    sdist_metadata: bytes | None = None,
    entry_points: str | None = ENTRY_POINTS,
) -> tuple[Path, Path]:
    wheel = directory / EXPECTED_WHEEL
    sdist = directory / EXPECTED_SDIST
    wheel_payload = wheel_metadata or metadata_bytes()
    sdist_payload = sdist_metadata or metadata_bytes(reverse_repeatable_fields=True)
    write_wheel(wheel, wheel_entries(wheel_payload, entry_points=entry_points))
    write_sdist(sdist, sdist_payload)
    return wheel, sdist


def write_custody_evidence(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "python_identity_file": directory / "python-identity.txt",
        "uv_identity_file": directory / "uv-identity.txt",
        "build_constraints_digest_file": directory / "release-build-constraints.sha256",
    }
    paths["python_identity_file"].write_text("CPython 3.14.6\n", encoding="utf-8", newline="\n")
    paths["uv_identity_file"].write_text("uv 0.8.22\n", encoding="utf-8", newline="\n")
    paths["build_constraints_digest_file"].write_text(
        f"{CONSTRAINTS_DIGEST}  scripts/release-build-constraints.txt\n",
        encoding="utf-8",
        newline="\n",
    )
    return paths


def custody_cli_arguments(
    mode: str,
    dist_dir: Path,
    evidence: dict[str, Path],
    manifest: Path,
    sha256sums: Path,
) -> list[str]:
    return [
        "verify_release_artifacts.py",
        mode,
        str(dist_dir),
        "--expected-version",
        "1.0.5",
        "--manifest",
        str(manifest),
        "--sha256sums",
        str(sha256sums),
        "--source-commit",
        SOURCE_COMMIT,
        "--tag-name",
        "v1.0.5",
        "--tag-object",
        TAG_OBJECT,
        "--peeled-commit",
        SOURCE_COMMIT,
        "--python-identity-file",
        str(evidence["python_identity_file"]),
        "--uv-identity-file",
        str(evidence["uv_identity_file"]),
        "--build-constraints-digest-file",
        str(evidence["build_constraints_digest_file"]),
    ]


def invoke_custody_cli(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    dist_dir: Path,
    evidence: dict[str, Path],
    manifest: Path,
    sha256sums: Path,
) -> None:
    module = release_module()
    monkeypatch.setattr(
        sys,
        "argv",
        custody_cli_arguments(mode, dist_dir, evidence, manifest, sha256sums),
    )
    assert module.main() is None


def invoke_wheel_archive_interface(
    module: ModuleType,
    interface: str,
    wheel: Path,
    tmp_path: Path,
) -> None:
    if interface == "artifact-pair":
        sdist = wheel.parent / EXPECTED_SDIST
        write_sdist(sdist, metadata_bytes())
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.5")
        return
    if interface == "semantic-manifest":
        module.semantic_wheel_manifest(wheel)
        return
    counterpart = tmp_path / f"{interface}-counterpart" / EXPECTED_WHEEL
    write_wheel(counterpart, wheel_entries(metadata_bytes()))
    if interface == "rebuilt-original":
        module.verify_rebuilt_wheel(wheel, counterpart)
        return
    if interface == "rebuilt-candidate":
        module.verify_rebuilt_wheel(counterpart, wheel)
        return
    raise AssertionError(f"unknown test interface: {interface}")


def wheel_with_total_members(path: Path, total_members: int) -> None:
    entries = wheel_entries(metadata_bytes())
    entries.extend(
        (f"csvql/generated_{index:04d}.py", "") for index in range(total_members - len(entries))
    )
    write_wheel(path, entries)


def wheel_with_name_volume(path: Path, minimum_name_bytes: int) -> None:
    entries = wheel_entries(metadata_bytes())
    index = 0
    observed_name_bytes = sum(
        len((member.filename if isinstance(member, zipfile.ZipInfo) else member).encode("utf-8"))
        for member, _ in entries
    )
    while observed_name_bytes <= minimum_name_bytes:
        name = f"csvql/{index:04d}_{'n' * 500}.py"
        entries.append((name, ""))
        observed_name_bytes += len(name.encode("utf-8"))
        index += 1
    write_wheel(path, entries)


def sdist_with_total_members(path: Path, total_members: int) -> None:
    extras: list[tuple[tarfile.TarInfo, bytes]] = []
    for index in range(total_members - 2):
        extras.append((tarfile.TarInfo(f"{SDIST_ROOT}/generated_{index:04d}.py"), b""))
    write_sdist(path, metadata_bytes(), extra_entries=extras)


def sdist_with_name_volume(path: Path, minimum_name_bytes: int) -> None:
    extras: list[tuple[tarfile.TarInfo, bytes]] = []
    observed_name_bytes = len(f"{SDIST_ROOT}/PKG-INFO".encode()) + len(
        f"{SDIST_ROOT}/README.md".encode()
    )
    index = 0
    while observed_name_bytes <= minimum_name_bytes:
        name = f"{SDIST_ROOT}/generated/{index:04d}_{'n' * 500}.py"
        extras.append((tarfile.TarInfo(name), b""))
        observed_name_bytes += len(name.encode("utf-8"))
        index += 1
    write_sdist(path, metadata_bytes(), extra_entries=extras)


def test_public_interfaces_and_constants_are_exact(tmp_path: Path) -> None:
    assert MODULE_PATH.is_file(), "release artifact verifier must exist"
    from scripts.verify_release_artifacts import (
        ArtifactSet,
        create_custody_files,
        metadata_contract,
        semantic_wheel_manifest,
        verify_artifact_pair,
        verify_custody_files,
        verify_rebuilt_wheel,
    )

    wheel, sdist = write_artifact_pair(tmp_path)
    artifacts = ArtifactSet(wheel=wheel, sdist=sdist)

    assert tuple(field.name for field in fields(ArtifactSet)) == ("wheel", "sdist")
    assert not hasattr(artifacts, "__dict__")
    with pytest.raises(FrozenInstanceError):
        artifacts.wheel = sdist
    assert callable(metadata_contract)
    assert callable(semantic_wheel_manifest)
    assert callable(verify_artifact_pair)
    assert callable(verify_rebuilt_wheel)
    assert callable(create_custody_files)
    assert callable(verify_custody_files)

    module = release_module()
    assert module.METADATA_KEYS == EXPECTED_METADATA_KEYS
    assert module.EXPECTED_WHEEL == EXPECTED_WHEEL
    assert module.EXPECTED_SDIST == EXPECTED_SDIST
    assert module.EXPECTED_ENTRY_POINT == "csvql = csvql.cli:main"


def test_metadata_contract_is_order_insensitive_for_repeatable_fields() -> None:
    module = release_module()
    forward = parse_metadata(metadata_bytes())
    reversed_fields = parse_metadata(metadata_bytes(reverse_repeatable_fields=True))

    contract = module.metadata_contract(forward)

    assert contract == module.metadata_contract(reversed_fields)
    assert tuple(contract) == EXPECTED_METADATA_KEYS
    assert contract["Requires-Dist"] == tuple(sorted(BASE_METADATA["Requires-Dist"]))
    assert contract["Project-URL"] == tuple(sorted(BASE_METADATA["Project-URL"]))


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("Name", "not-localql"),
        ("Version", "9.9.9"),
        ("Summary", "Changed summary"),
        ("Requires-Python", ">=3.12"),
        ("Requires-Dist", "duckdb==0.0.1"),
        ("Provides-Extra", "other"),
        ("Project-URL", "Repository, https://example.invalid/changed"),
        ("License-Expression", "Apache-2.0"),
        ("Classifier", "Operating System :: POSIX"),
        ("Description-Content-Type", "text/plain"),
    ],
)
def test_artifact_pair_rejects_each_metadata_contract_mismatch(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    module = release_module()
    changed = {field: [replacement]}
    wheel, sdist = write_artifact_pair(
        tmp_path,
        sdist_metadata=metadata_bytes(replacements=changed),
    )

    with pytest.raises(ValueError, match="metadata"):
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.5")


def test_artifact_pair_rejects_long_description_mismatch(tmp_path: Path) -> None:
    module = release_module()
    wheel, sdist = write_artifact_pair(
        tmp_path,
        sdist_metadata=metadata_bytes(description="# Different README"),
    )

    with pytest.raises(ValueError, match="long description"):
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.5")


def test_artifact_pair_accepts_exact_metadata_and_entry_point(tmp_path: Path) -> None:
    module = release_module()
    wheel, sdist = write_artifact_pair(tmp_path)

    assert module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.5") is None


@pytest.mark.parametrize(
    "entry_points",
    [
        None,
        "[other]\ncsvql = csvql.cli:main\n",
        "[console_scripts]\ncsvql = csvql.cli:not_main\n",
        "[console_scripts]\ncsvql = csvql.cli:main\ncsvql = csvql.cli:main\n",
    ],
)
def test_artifact_pair_rejects_missing_wrong_or_duplicate_entry_point(
    tmp_path: Path,
    entry_points: str | None,
) -> None:
    module = release_module()
    wheel, sdist = write_artifact_pair(tmp_path, entry_points=entry_points)

    with pytest.raises(ValueError, match="entry point"):
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.5")


@pytest.mark.parametrize("bad_kind", ["duplicate", "noncanonical", "special"])
def test_artifact_pair_rejects_ambiguous_or_unsafe_metadata_members(
    tmp_path: Path,
    bad_kind: str,
) -> None:
    module = release_module()
    wheel = tmp_path / EXPECTED_WHEEL
    sdist = tmp_path / EXPECTED_SDIST
    entries = wheel_entries(metadata_bytes())
    if bad_kind == "duplicate":
        entries.append((f"{DIST_INFO}/METADATA", metadata_bytes()))
    elif bad_kind == "noncanonical":
        entries = [
            (f"{DIST_INFO}/./METADATA", content)
            if member == f"{DIST_INFO}/METADATA"
            else (member, content)
            for member, content in entries
        ]
    else:
        entries = [
            (zip_info(f"{DIST_INFO}/METADATA", file_type=stat.S_IFLNK), content)
            if member == f"{DIST_INFO}/METADATA"
            else (member, content)
            for member, content in entries
        ]
    write_wheel(wheel, entries)
    write_sdist(sdist, metadata_bytes())

    with pytest.raises(ValueError):
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.5")


def test_metadata_contract_rejects_duplicate_headers() -> None:
    module = release_module()
    duplicate_singleton = parse_metadata(
        metadata_bytes().replace(b"Name: localql\n", b"Name: localql\nName: localql\n")
    )
    duplicate_repeatable = parse_metadata(
        metadata_bytes().replace(
            b"Requires-Dist: typer>=0.12.3\n",
            b"Requires-Dist: typer>=0.12.3\nRequires-Dist: typer>=0.12.3\n",
        )
    )

    with pytest.raises(ValueError, match="duplicate"):
        module.metadata_contract(duplicate_singleton)
    with pytest.raises(ValueError, match="duplicate"):
        module.metadata_contract(duplicate_repeatable)


def test_sdist_requires_exactly_one_two_component_pkg_info(tmp_path: Path) -> None:
    module = release_module()
    wheel = tmp_path / EXPECTED_WHEEL
    sdist = tmp_path / EXPECTED_SDIST
    write_wheel(wheel, wheel_entries(metadata_bytes()))
    extra = tarfile.TarInfo("other-root/PKG-INFO")
    write_sdist(sdist, metadata_bytes(), extra_entries=[(extra, metadata_bytes())])

    with pytest.raises(ValueError, match="PKG-INFO"):
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.5")


def test_semantic_manifest_ignores_timestamp_order_and_record(tmp_path: Path) -> None:
    module = release_module()
    original = tmp_path / "original" / EXPECTED_WHEEL
    rebuilt = tmp_path / "rebuilt" / EXPECTED_WHEEL
    entries = wheel_entries(metadata_bytes(), record="first-record\n")
    write_wheel(original, entries, timestamp=(2025, 1, 1, 0, 0, 0))
    rebuilt_entries = list(reversed(wheel_entries(metadata_bytes(), record="other-record\n")))
    write_wheel(rebuilt, rebuilt_entries, timestamp=(2026, 6, 6, 6, 6, 6))

    assert module.semantic_wheel_manifest(original) == module.semantic_wheel_manifest(rebuilt)
    assert module.verify_rebuilt_wheel(original, rebuilt) is None


@pytest.mark.parametrize("drift_kind", ["member", "content"])
def test_rebuilt_wheel_rejects_semantic_member_or_content_drift(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    module = release_module()
    original = tmp_path / "original" / EXPECTED_WHEEL
    rebuilt = tmp_path / "rebuilt" / EXPECTED_WHEEL
    original_entries = wheel_entries(metadata_bytes())
    rebuilt_entries = wheel_entries(metadata_bytes())
    if drift_kind == "member":
        rebuilt_entries.append(("csvql/extra.py", "EXTRA = True\n"))
    else:
        rebuilt_entries = [
            (member, "CHANGED = True\n") if member == "csvql/__init__.py" else (member, content)
            for member, content in rebuilt_entries
        ]
    write_wheel(original, original_entries)
    write_wheel(rebuilt, rebuilt_entries)

    with pytest.raises(ValueError, match="semantic"):
        module.verify_rebuilt_wheel(original, rebuilt)


def test_rebuilt_wheel_reports_metadata_drift_separately(tmp_path: Path) -> None:
    module = release_module()
    original = tmp_path / "original" / EXPECTED_WHEEL
    rebuilt = tmp_path / "rebuilt" / EXPECTED_WHEEL
    write_wheel(original, wheel_entries(metadata_bytes()))
    write_wheel(
        rebuilt,
        wheel_entries(metadata_bytes(replacements={"Requires-Dist": ["changed>=1"]})),
    )

    with pytest.raises(ValueError, match="metadata"):
        module.verify_rebuilt_wheel(original, rebuilt)


@pytest.mark.parametrize("bad_kind", ["duplicate", "noncanonical", "special"])
def test_semantic_manifest_rejects_duplicate_noncanonical_or_special_members(
    tmp_path: Path,
    bad_kind: str,
) -> None:
    module = release_module()
    wheel = tmp_path / EXPECTED_WHEEL
    entries = wheel_entries(metadata_bytes())
    if bad_kind == "duplicate":
        entries.append(("csvql/__init__.py", "duplicate\n"))
    elif bad_kind == "noncanonical":
        entries.append(("csvql/../escape.py", "unsafe\n"))
    else:
        entries.append((zip_info("csvql/link.py", file_type=stat.S_IFLNK), "target"))
    write_wheel(wheel, entries)

    with pytest.raises(ValueError):
        module.semantic_wheel_manifest(wheel)


@pytest.mark.parametrize(
    "archive_kind, protected_member",
    [
        ("wheel", ".internal"),
        ("wheel", ".internal/release-proof.md"),
        ("wheel", "docs/superpowers"),
        ("wheel", "docs/superpowers/design.md"),
        ("wheel", "docs/CODEX_CAPABILITY_REVIEW.md"),
        ("wheel", "docs/release-candidate-proof-2026-07-03.md"),
        ("wheel", "AGENTS.md"),
        ("wheel", "docs/AGENTS.override.md"),
        ("wheel", ".agents/instructions.md"),
        ("wheel", ".codex/session.json"),
        ("wheel", "csvql/.internal/secret.py"),
        ("wheel", "csvql/.agents/instructions.md"),
        ("wheel", "csvql/.codex/session.json"),
        ("sdist", ".internal"),
        ("sdist", ".internal/release-proof.md"),
        ("sdist", "docs/superpowers"),
        ("sdist", "docs/superpowers/design.md"),
        ("sdist", "docs/CODEX_CAPABILITY_REVIEW.md"),
        ("sdist", "docs/release-candidate-proof-2026-07-03.md"),
        ("sdist", "AGENTS.md"),
        ("sdist", "docs/AGENTS.override.md"),
        ("sdist", ".agents/instructions.md"),
        ("sdist", ".codex/session.json"),
        ("sdist", "docs/.internal/secret.md"),
        ("sdist", "docs/reference/.agents/instructions.md"),
        ("sdist", "examples/.codex/session.json"),
    ],
)
def test_artifact_pair_rejects_canonical_protected_members(
    tmp_path: Path,
    archive_kind: str,
    protected_member: str,
) -> None:
    module = release_module()
    wheel, sdist = write_artifact_pair(tmp_path)
    if archive_kind == "wheel":
        entries = wheel_entries(metadata_bytes())
        entries.append((protected_member, "private\n"))
        write_wheel(wheel, entries)
    else:
        extra_info = tarfile.TarInfo(f"{SDIST_ROOT}/{protected_member}")
        write_sdist(sdist, metadata_bytes(), extra_entries=[(extra_info, b"private\n")])

    with pytest.raises(ValueError, match="protected") as error:
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.5")

    assert protected_member not in str(error.value)


def test_inspect_creates_no_custody_files(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = release_module()
    dist_dir = tmp_path / "dist"
    write_artifact_pair(dist_dir)
    manifest = tmp_path / "manifest.json"
    sha256sums = tmp_path / "SHA256SUMS.txt"
    before = tuple(sorted(path.name for path in dist_dir.iterdir()))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_artifacts.py",
            "inspect",
            str(dist_dir),
            "--expected-version",
            "1.0.5",
        ],
    )

    assert module.main() is None
    assert capsys.readouterr().out == (
        "Release artifact inspection passed: 1 wheel(s), 1 sdist(s).\n"
    )
    assert tuple(sorted(path.name for path in dist_dir.iterdir())) == before
    assert not manifest.exists()
    assert not sha256sums.exists()


def test_create_manifest_schema_and_derived_sums_are_exact_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wheel, sdist = write_artifact_pair(tmp_path / "dist")
    evidence = write_custody_evidence(tmp_path / "evidence")
    manifest = tmp_path / "manifest.json"
    sha256sums = tmp_path / "SHA256SUMS.txt"
    expected = {
        "artifacts": [
            {
                "filename": EXPECTED_WHEEL,
                "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "size": wheel.stat().st_size,
            },
            {
                "filename": EXPECTED_SDIST,
                "sha256": hashlib.sha256(sdist.read_bytes()).hexdigest(),
                "size": sdist.stat().st_size,
            },
        ],
        "distribution": "localql",
        "schema_version": 1,
        "source": {
            "commit": SOURCE_COMMIT,
            "peeled_commit": SOURCE_COMMIT,
            "tag": "v1.0.5",
            "tag_object": TAG_OBJECT,
        },
        "toolchain": {
            "build_constraints_sha256": CONSTRAINTS_DIGEST,
            "python": "CPython 3.14.6",
            "uv": "uv 0.8.22",
        },
        "version": "1.0.5",
    }

    invoke_custody_cli(
        monkeypatch,
        "create-manifest",
        wheel.parent,
        evidence,
        manifest,
        sha256sums,
    )
    expected_text = json.dumps(expected, indent=2, sort_keys=True) + "\n"
    expected_sums = (
        f"{expected['artifacts'][0]['sha256']}  {EXPECTED_WHEEL}\n"
        f"{expected['artifacts'][1]['sha256']}  {EXPECTED_SDIST}\n"
    )
    assert manifest.read_text(encoding="utf-8") == expected_text
    assert sha256sums.read_text(encoding="utf-8") == expected_sums

    invoke_custody_cli(
        monkeypatch,
        "create-manifest",
        wheel.parent,
        evidence,
        manifest,
        sha256sums,
    )
    assert manifest.read_text(encoding="utf-8") == expected_text
    assert sha256sums.read_text(encoding="utf-8") == expected_sums


class TrackingReader(io.BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        assert size == 1024 * 1024
        self.read_sizes.append(size)
        return super().read(size)


class TrackingPath:
    def __init__(self, content: bytes) -> None:
        self.reader = TrackingReader(content)

    def open(self, mode: str) -> TrackingReader:
        assert mode == "rb"
        return self.reader


def test_sha256_file_streams_in_one_mib_chunks() -> None:
    module = release_module()
    content = b"a" * (1024 * 1024 + 7)
    path = TrackingPath(content)

    assert module.sha256_file(path) == hashlib.sha256(content).hexdigest()
    assert len(path.reader.read_sizes) == 3


def test_verify_accepts_untampered_transported_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dist = tmp_path / "source-dist"
    wheel, sdist = write_artifact_pair(source_dist)
    source_evidence = write_custody_evidence(tmp_path / "source-evidence")
    manifest = tmp_path / "manifest.json"
    sha256sums = tmp_path / "SHA256SUMS.txt"
    invoke_custody_cli(
        monkeypatch,
        "create-manifest",
        source_dist,
        source_evidence,
        manifest,
        sha256sums,
    )

    transported_dist = tmp_path / "transported-dist"
    transported_dist.mkdir()
    shutil.copy2(wheel, transported_dist / wheel.name)
    shutil.copy2(sdist, transported_dist / sdist.name)
    transported_evidence = write_custody_evidence(tmp_path / "transported-evidence")

    invoke_custody_cli(
        monkeypatch,
        "verify-manifest",
        transported_dist,
        transported_evidence,
        manifest,
        sha256sums,
    )


def test_cli_module_executes_as_a_standalone_script() -> None:
    completed = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--help"],
        cwd=MODULE_PATH.parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "inspect" in completed.stdout
    assert "create-manifest" in completed.stdout
    assert "verify-manifest" in completed.stdout
    assert "--rebuilt-wheel" not in completed.stdout


def test_cli_rejects_extra_archive_in_exact_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = release_module()
    write_artifact_pair(tmp_path)
    (tmp_path / "localql-1.0.1.tar.gz").write_bytes(b"extra")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_artifacts.py",
            "inspect",
            str(tmp_path),
            "--expected-version",
            "1.0.5",
        ],
    )

    with pytest.raises(SystemExit, match="exact release artifacts"):
        module.main()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-top-key",
        "extra-top-key",
        "wrong-schema-type",
        "extra-source-key",
        "missing-toolchain-key",
        "extra-artifact-key",
        "reversed-artifacts",
        "boolean-size",
        "string-size",
        "uppercase-digest",
        "unexpected-filename",
    ],
)
def test_verify_rejects_strict_manifest_schema_types_keys_and_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    dist_dir = tmp_path / "dist"
    write_artifact_pair(dist_dir)
    evidence = write_custody_evidence(tmp_path / "evidence")
    manifest = tmp_path / "manifest.json"
    sha256sums = tmp_path / "SHA256SUMS.txt"
    invoke_custody_cli(
        monkeypatch,
        "create-manifest",
        dist_dir,
        evidence,
        manifest,
        sha256sums,
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if mutation == "missing-top-key":
        del payload["distribution"]
    elif mutation == "extra-top-key":
        payload["unexpected"] = "rejected"
    elif mutation == "wrong-schema-type":
        payload["schema_version"] = True
    elif mutation == "extra-source-key":
        payload["source"]["unexpected"] = "rejected"
    elif mutation == "missing-toolchain-key":
        del payload["toolchain"]["uv"]
    elif mutation == "extra-artifact-key":
        payload["artifacts"][0]["unexpected"] = "rejected"
    elif mutation == "reversed-artifacts":
        payload["artifacts"].reverse()
    elif mutation == "boolean-size":
        payload["artifacts"][0]["size"] = True
    elif mutation == "string-size":
        payload["artifacts"][0]["size"] = str(payload["artifacts"][0]["size"])
    elif mutation == "uppercase-digest":
        payload["artifacts"][0]["sha256"] = payload["artifacts"][0]["sha256"].upper()
    else:
        payload["artifacts"][0]["filename"] = "localql-aliased.whl"
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="manifest"):
        invoke_custody_cli(
            monkeypatch,
            "verify-manifest",
            dist_dir,
            evidence,
            manifest,
            sha256sums,
        )


@pytest.mark.parametrize(
    "malformation", ["duplicate-key", "invalid-json", "invalid-utf8", "oversized"]
)
def test_verify_rejects_duplicate_malformed_invalid_utf8_or_oversized_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    malformation: str,
) -> None:
    dist_dir = tmp_path / "dist"
    write_artifact_pair(dist_dir)
    evidence = write_custody_evidence(tmp_path / "evidence")
    manifest = tmp_path / "manifest.json"
    sha256sums = tmp_path / "SHA256SUMS.txt"
    invoke_custody_cli(
        monkeypatch,
        "create-manifest",
        dist_dir,
        evidence,
        manifest,
        sha256sums,
    )
    if malformation == "duplicate-key":
        original = manifest.read_text(encoding="utf-8")
        manifest.write_text(
            original.replace(
                '  "distribution":', '  "distribution": "localql",\n  "distribution":', 1
            ),
            encoding="utf-8",
        )
    elif malformation == "invalid-json":
        manifest.write_text('{"pypi-sensitive-token":', encoding="utf-8")
    elif malformation == "invalid-utf8":
        manifest.write_bytes(b"\xff\xfe")
    else:
        manifest.write_bytes(b"{" + b" " * (64 * 1024) + b"}")

    with pytest.raises(SystemExit) as error_info:
        invoke_custody_cli(
            monkeypatch,
            "verify-manifest",
            dist_dir,
            evidence,
            manifest,
            sha256sums,
        )

    assert "pypi-sensitive-token" not in str(error_info.value)


@pytest.mark.parametrize(
    "tamper_kind",
    [
        "source-context",
        "tag-context",
        "python-evidence",
        "constraints-evidence",
        "sums",
        "manifest",
        "artifact",
    ],
)
def test_verify_rejects_context_evidence_sums_manifest_and_artifact_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tamper_kind: str,
) -> None:
    dist_dir = tmp_path / "dist"
    wheel, _ = write_artifact_pair(dist_dir)
    evidence = write_custody_evidence(tmp_path / "evidence")
    manifest = tmp_path / "manifest.json"
    sha256sums = tmp_path / "SHA256SUMS.txt"
    invoke_custody_cli(
        monkeypatch,
        "create-manifest",
        dist_dir,
        evidence,
        manifest,
        sha256sums,
    )
    arguments = custody_cli_arguments(
        "verify-manifest",
        dist_dir,
        evidence,
        manifest,
        sha256sums,
    )
    if tamper_kind == "source-context":
        changed = "d" * 40
        arguments[arguments.index("--source-commit") + 1] = changed
        arguments[arguments.index("--peeled-commit") + 1] = changed
    elif tamper_kind == "tag-context":
        arguments[arguments.index("--tag-name") + 1] = "v9.9.9"
    elif tamper_kind == "python-evidence":
        evidence["python_identity_file"].write_text("CPython changed\n", encoding="utf-8")
    elif tamper_kind == "constraints-evidence":
        evidence["build_constraints_digest_file"].write_text(
            f"{'d' * 64}  scripts/release-build-constraints.txt\n",
            encoding="utf-8",
        )
    elif tamper_kind == "sums":
        sha256sums.write_text(f"{'0' * 64}  {EXPECTED_WHEEL}\n", encoding="utf-8")
    elif tamper_kind == "manifest":
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["source"]["commit"] = "d" * 40
        manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        wheel.write_bytes(wheel.read_bytes() + b"transport tamper")
    monkeypatch.setattr(sys, "argv", arguments)

    with pytest.raises(SystemExit):
        release_module().main()


@pytest.mark.parametrize(
    "invalid_context",
    ["uppercase-source", "source-peeled-disagreement", "tag-object-equals-commit"],
)
def test_create_rejects_invalid_custody_identity_relationships(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    invalid_context: str,
) -> None:
    dist_dir = tmp_path / "dist"
    write_artifact_pair(dist_dir)
    evidence = write_custody_evidence(tmp_path / "evidence")
    manifest = tmp_path / "manifest.json"
    sha256sums = tmp_path / "SHA256SUMS.txt"
    arguments = custody_cli_arguments(
        "create-manifest",
        dist_dir,
        evidence,
        manifest,
        sha256sums,
    )
    if invalid_context == "uppercase-source":
        arguments[arguments.index("--source-commit") + 1] = "A" * 40
    elif invalid_context == "source-peeled-disagreement":
        arguments[arguments.index("--peeled-commit") + 1] = "d" * 40
    else:
        arguments[arguments.index("--tag-object") + 1] = SOURCE_COMMIT
    monkeypatch.setattr(sys, "argv", arguments)

    with pytest.raises(SystemExit):
        release_module().main()

    assert not manifest.exists()
    assert not sha256sums.exists()


@pytest.mark.parametrize(
    "invalid_evidence",
    ["identity-empty", "identity-multiline", "identity-control", "constraints-format", "symlink"],
)
def test_create_rejects_malformed_or_nonregular_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    invalid_evidence: str,
) -> None:
    dist_dir = tmp_path / "dist"
    write_artifact_pair(dist_dir)
    evidence = write_custody_evidence(tmp_path / "evidence")
    python_identity = evidence["python_identity_file"]
    if invalid_evidence == "identity-empty":
        python_identity.write_text("", encoding="utf-8")
    elif invalid_evidence == "identity-multiline":
        python_identity.write_text("first\nsecond\n", encoding="utf-8")
    elif invalid_evidence == "identity-control":
        python_identity.write_bytes(b"python\x1bidentity\n")
    elif invalid_evidence == "constraints-format":
        evidence["build_constraints_digest_file"].write_text(
            f"{CONSTRAINTS_DIGEST} scripts/release-build-constraints.txt\n",
            encoding="utf-8",
        )
    else:
        target = tmp_path / "python-target.txt"
        target.write_text("CPython 3.14.6\n", encoding="utf-8")
        python_identity.unlink()
        python_identity.symlink_to(target)
    manifest = tmp_path / "manifest.json"
    sha256sums = tmp_path / "SHA256SUMS.txt"

    with pytest.raises(SystemExit):
        invoke_custody_cli(
            monkeypatch,
            "create-manifest",
            dist_dir,
            evidence,
            manifest,
            sha256sums,
        )

    assert not manifest.exists()
    assert not sha256sums.exists()


@pytest.mark.parametrize("mode", ["inspect", "create-manifest", "verify-manifest"])
@pytest.mark.parametrize(
    "directory_problem", ["extra", "missing", "symlink", "hardlink-alias", "directory"]
)
def test_all_modes_reject_extra_missing_aliased_or_nonregular_directory_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    directory_problem: str,
) -> None:
    module = release_module()
    dist_dir = tmp_path / "dist"
    wheel, sdist = write_artifact_pair(dist_dir)
    if directory_problem == "extra":
        (dist_dir / "unexpected.txt").write_text("extra\n", encoding="utf-8")
    elif directory_problem == "missing":
        sdist.unlink()
    elif directory_problem == "symlink":
        target = tmp_path / EXPECTED_WHEEL
        shutil.copy2(wheel, target)
        wheel.unlink()
        wheel.symlink_to(target)
    elif directory_problem == "hardlink-alias":
        sdist.unlink()
        os.link(wheel, sdist)
    else:
        wheel.unlink()
        wheel.mkdir()
    if mode == "inspect":
        arguments = [
            "verify_release_artifacts.py",
            mode,
            str(dist_dir),
            "--expected-version",
            "1.0.5",
        ]
    else:
        evidence = write_custody_evidence(tmp_path / "evidence")
        arguments = custody_cli_arguments(
            mode,
            dist_dir,
            evidence,
            tmp_path / "manifest.json",
            tmp_path / "SHA256SUMS.txt",
        )
    monkeypatch.setattr(sys, "argv", arguments)

    with pytest.raises(SystemExit, match="exact release artifacts"):
        module.main()


@pytest.mark.parametrize("destination_kind", ["manifest", "sha256sums"])
def test_create_rejects_symlink_destinations_without_touching_targets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    destination_kind: str,
) -> None:
    dist_dir = tmp_path / "dist"
    write_artifact_pair(dist_dir)
    evidence = write_custody_evidence(tmp_path / "evidence")
    manifest = tmp_path / "manifest.json"
    sha256sums = tmp_path / "SHA256SUMS.txt"
    destination = manifest if destination_kind == "manifest" else sha256sums
    target = tmp_path / f"{destination_kind}-target.txt"
    target.write_text("preserve me\n", encoding="utf-8")
    destination.symlink_to(target)

    with pytest.raises(SystemExit):
        invoke_custody_cli(
            monkeypatch,
            "create-manifest",
            dist_dir,
            evidence,
            manifest,
            sha256sums,
        )

    assert target.read_text(encoding="utf-8") == "preserve me\n"
    assert destination.is_symlink()


def test_create_rejects_manifest_and_sums_destination_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    write_artifact_pair(dist_dir)
    evidence = write_custody_evidence(tmp_path / "evidence")
    destination = tmp_path / "custody.txt"

    with pytest.raises(SystemExit):
        invoke_custody_cli(
            monkeypatch,
            "create-manifest",
            dist_dir,
            evidence,
            destination,
            destination,
        )

    assert not destination.exists()


def test_create_rejects_normalized_manifest_and_sums_destination_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    write_artifact_pair(dist_dir)
    evidence = write_custody_evidence(tmp_path / "evidence")
    (tmp_path / "nested").mkdir()
    manifest = tmp_path / "nested" / ".." / "custody.txt"
    sha256sums = tmp_path / "custody.txt"

    with pytest.raises(SystemExit):
        invoke_custody_cli(
            monkeypatch,
            "create-manifest",
            dist_dir,
            evidence,
            manifest,
            sha256sums,
        )

    assert not sha256sums.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["inspect", "dist", "--expected-version", "1.0.5", "--manifest", "manifest.json"],
        ["create-manifest", "dist", "--expected-version", "1.0.5"],
        ["verify-manifest", "dist", "--expected-version", "1.0.5", "--rebuilt-wheel", "wheel"],
        ["verify-rebuild", "dist", "--expected-version", "1.0.5"],
    ],
)
def test_cli_requires_and_rejects_mode_specific_arguments(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["verify_release_artifacts.py", *arguments])

    with pytest.raises(SystemExit) as error_info:
        release_module().main()

    assert error_info.value.code == 2


def test_verify_rebuild_cli_accepts_only_a_semantically_identical_wheel(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    rebuilt_dir = tmp_path / "rebuilt"
    write_artifact_pair(dist_dir)
    rebuilt_wheel = rebuilt_dir / EXPECTED_WHEEL
    write_wheel(rebuilt_wheel, wheel_entries(metadata_bytes()))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_artifacts.py",
            "verify-rebuild",
            str(dist_dir),
            "--expected-version",
            "1.0.5",
            "--rebuilt-wheel",
            str(rebuilt_wheel),
        ],
    )

    assert release_module().main() is None
    assert capsys.readouterr().out == (
        "Release artifact rebuild verification passed: 1 wheel(s), 1 sdist(s).\n"
    )


def test_verify_rebuild_cli_rejects_divergent_executable_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    rebuilt_dir = tmp_path / "rebuilt"
    write_artifact_pair(dist_dir)
    rebuilt_wheel = rebuilt_dir / EXPECTED_WHEEL
    divergent_entries = wheel_entries(metadata_bytes())
    divergent_entries.append(("csvql/divergent.py", "DIVERGED = True\n"))
    write_wheel(rebuilt_wheel, divergent_entries)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_artifacts.py",
            "verify-rebuild",
            str(dist_dir),
            "--expected-version",
            "1.0.5",
            "--rebuilt-wheel",
            str(rebuilt_wheel),
        ],
    )

    with pytest.raises(SystemExit, match="semantic member or content mismatch"):
        release_module().main()


def test_failures_do_not_expose_member_contents_or_terminal_controls(tmp_path: Path) -> None:
    module = release_module()
    wheel = tmp_path / EXPECTED_WHEEL
    synthetic = "pypi-" + "A" * 40
    unsafe_member = f"csvql/{synthetic}\x1b.py"
    entries = wheel_entries(metadata_bytes())
    entries.append((unsafe_member, synthetic))
    write_wheel(wheel, entries)

    with pytest.raises(ValueError) as error_info:
        module.semantic_wheel_manifest(wheel)

    rendered = str(error_info.value)
    assert synthetic not in rendered
    assert "\x1b" not in rendered


@pytest.mark.parametrize(
    "hostile_member",
    [
        f"nested/{DIST_INFO}/METADATA",
        "alternate-1.0.4.dist-info/METADATA",
        f"nested/{DIST_INFO}/RECORD",
        "alternate-1.0.4.dist-info/RECORD",
    ],
)
@pytest.mark.parametrize(
    "interface",
    ["artifact-pair", "semantic-manifest", "rebuilt-original", "rebuilt-candidate"],
)
def test_wheel_interfaces_reject_every_noncanonical_dist_info_namespace(
    tmp_path: Path,
    interface: str,
    hostile_member: str,
) -> None:
    module = release_module()
    wheel = tmp_path / "hostile" / EXPECTED_WHEEL
    entries = wheel_entries(metadata_bytes())
    content = metadata_bytes() if hostile_member.endswith("/METADATA") else "ignored-record\n"
    entries.append((hostile_member, content))
    write_wheel(wheel, entries)

    with pytest.raises(ValueError, match="dist-info namespace"):
        invoke_wheel_archive_interface(module, interface, wheel, tmp_path)


def test_semantic_manifest_excludes_only_exact_canonical_record(tmp_path: Path) -> None:
    module = release_module()
    wheel = tmp_path / EXPECTED_WHEEL
    entries = wheel_entries(metadata_bytes())
    entries.append((f"csvql/{DIST_INFO}/RECORD", "must-not-be-ignored\n"))
    write_wheel(wheel, entries)

    with pytest.raises(ValueError, match="dist-info namespace"):
        module.semantic_wheel_manifest(wheel)


def test_archive_limits_reuse_artifact_compressed_size_constants() -> None:
    audit_module = importlib.import_module("scripts.audit_package_contents")
    module = release_module()

    assert module.WHEEL_SIZE_LIMIT == audit_module.WHEEL_SIZE_LIMIT
    assert module.SDIST_SIZE_LIMIT == audit_module.SDIST_SIZE_LIMIT


@pytest.mark.parametrize(
    "interface",
    [
        "artifact-pair",
        "semantic-manifest",
        "rebuilt-original",
        "rebuilt-candidate",
    ],
)
def test_wheel_compressed_size_limit_applies_to_every_direct_interface(
    tmp_path: Path,
    interface: str,
) -> None:
    module = release_module()
    hostile = tmp_path / "hostile" / EXPECTED_WHEEL
    hostile.parent.mkdir(parents=True)
    hostile.write_bytes(b"x" * (1024 * 1024 + 1))

    with pytest.raises(ValueError, match="compressed size"):
        invoke_wheel_archive_interface(module, interface, hostile, tmp_path)


def test_sdist_compressed_size_limit_applies_to_artifact_pair(tmp_path: Path) -> None:
    module = release_module()
    wheel = tmp_path / EXPECTED_WHEEL
    sdist = tmp_path / EXPECTED_SDIST
    write_wheel(wheel, wheel_entries(metadata_bytes()))
    sdist.write_bytes(b"x" * (5 * 1024 * 1024 + 1))

    with pytest.raises(ValueError, match="compressed size"):
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.5")


@pytest.mark.parametrize(
    "interface",
    ["artifact-pair", "semantic-manifest", "rebuilt-original", "rebuilt-candidate"],
)
def test_wheel_member_count_limit_applies_to_every_archive_reading_interface(
    tmp_path: Path,
    interface: str,
) -> None:
    module = release_module()
    hostile = tmp_path / "hostile" / EXPECTED_WHEEL
    wheel_with_total_members(hostile, 4097)

    with pytest.raises(ValueError, match="member count"):
        invoke_wheel_archive_interface(module, interface, hostile, tmp_path)


def test_sdist_member_count_limit_is_fail_closed(tmp_path: Path) -> None:
    module = release_module()
    wheel = tmp_path / EXPECTED_WHEEL
    sdist = tmp_path / EXPECTED_SDIST
    write_wheel(wheel, wheel_entries(metadata_bytes()))
    sdist_with_total_members(sdist, 4097)

    with pytest.raises(ValueError, match="member count"):
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.5")


@pytest.mark.parametrize(
    "interface",
    ["artifact-pair", "semantic-manifest", "rebuilt-original", "rebuilt-candidate"],
)
def test_wheel_member_name_volume_limit_applies_to_every_archive_reading_interface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    interface: str,
) -> None:
    module = release_module()
    hostile = tmp_path / "hostile" / EXPECTED_WHEEL
    wheel_with_name_volume(hostile, 1024 * 1024)
    monkeypatch.setattr(module, "WHEEL_SIZE_LIMIT", hostile.stat().st_size + 1, raising=False)

    with pytest.raises(ValueError, match="member-name bytes"):
        invoke_wheel_archive_interface(module, interface, hostile, tmp_path)


def test_sdist_member_name_volume_limit_is_fail_closed(tmp_path: Path) -> None:
    module = release_module()
    wheel = tmp_path / EXPECTED_WHEEL
    sdist = tmp_path / EXPECTED_SDIST
    write_wheel(wheel, wheel_entries(metadata_bytes()))
    sdist_with_name_volume(sdist, 1024 * 1024)

    with pytest.raises(ValueError, match="member-name bytes"):
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.5")


class IncrementalTarArchive:
    def __init__(self, *, budget: str) -> None:
        self.budget = budget
        self.yielded = 0

    def __enter__(self) -> IncrementalTarArchive:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def __iter__(self) -> IncrementalTarArchive:
        return self

    def __next__(self) -> tarfile.TarInfo:
        self.yielded += 1
        if self.budget == "member count":
            if self.yielded > 4097:
                raise AssertionError("tar enumeration continued beyond the first exceeded budget")
            return tarfile.TarInfo(f"{SDIST_ROOT}/generated_{self.yielded:04d}.py")
        if self.yielded > 1:
            raise AssertionError("tar enumeration continued beyond the first exceeded budget")
        return tarfile.TarInfo("n" * (1024 * 1024 + 1))

    def getmembers(self) -> list[tarfile.TarInfo]:
        raise AssertionError("tar metadata must be enumerated incrementally")

    def extractfile(self, _info: tarfile.TarInfo) -> None:
        raise AssertionError("payload processing must not start after a metadata budget failure")


@pytest.mark.parametrize("budget", ["member count", "member-name bytes"])
def test_sdist_metadata_enumeration_stops_at_first_budget_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    budget: str,
) -> None:
    module = release_module()
    wheel = tmp_path / EXPECTED_WHEEL
    sdist = tmp_path / EXPECTED_SDIST
    write_wheel(wheel, wheel_entries(metadata_bytes()))
    sdist.write_bytes(b"synthetic tar boundary")
    archive = IncrementalTarArchive(budget=budget)
    monkeypatch.setattr(module.tarfile, "open", lambda *_args, **_kwargs: archive)

    with pytest.raises(ValueError, match=budget):
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.5")

    expected_yielded = 4097 if budget == "member count" else 1
    assert archive.yielded == expected_yielded
