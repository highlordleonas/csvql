from __future__ import annotations

import email.policy
import hashlib
import importlib
import io
import json
import os
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
EXPECTED_WHEEL = "localql-1.0.4-py3-none-any.whl"
EXPECTED_SDIST = "localql-1.0.4.tar.gz"
DIST_INFO = "localql-1.0.4.dist-info"
SDIST_ROOT = "localql-1.0.4"

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
    "Version": ["1.0.4"],
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
        ("csvql/__init__.py", '__version__ = "1.0.4"\n'),
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


def invoke_wheel_archive_interface(
    module: ModuleType,
    interface: str,
    wheel: Path,
    tmp_path: Path,
) -> None:
    if interface == "artifact-pair":
        sdist = wheel.parent / EXPECTED_SDIST
        write_sdist(sdist, metadata_bytes())
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.4")
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
        metadata_contract,
        semantic_wheel_manifest,
        verify_artifact_pair,
        verify_rebuilt_wheel,
        write_artifact_manifest,
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
    assert callable(write_artifact_manifest)

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
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.4")


def test_artifact_pair_rejects_long_description_mismatch(tmp_path: Path) -> None:
    module = release_module()
    wheel, sdist = write_artifact_pair(
        tmp_path,
        sdist_metadata=metadata_bytes(description="# Different README"),
    )

    with pytest.raises(ValueError, match="long description"):
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.4")


def test_artifact_pair_accepts_exact_metadata_and_entry_point(tmp_path: Path) -> None:
    module = release_module()
    wheel, sdist = write_artifact_pair(tmp_path)

    assert module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.4") is None


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
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.4")


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
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.4")


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
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.4")


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


def test_artifact_manifest_is_exact_deterministic_json_with_final_newline(tmp_path: Path) -> None:
    module = release_module()
    wheel, sdist = write_artifact_pair(tmp_path / "dist")
    destination = tmp_path / "artifact-manifest.json"
    artifacts = module.ArtifactSet(wheel, sdist)
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
        "version": "1.0.4",
    }

    assert module.write_artifact_manifest(artifacts, destination) is None
    expected_text = json.dumps(expected, indent=2, sort_keys=True) + "\n"
    assert destination.read_text(encoding="utf-8") == expected_text
    module.write_artifact_manifest(artifacts, destination)
    assert destination.read_text(encoding="utf-8") == expected_text


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


def test_cli_selects_exact_pair_repeated_rebuilds_and_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = release_module()
    dist_dir = tmp_path / "dist"
    wheel, _ = write_artifact_pair(dist_dir)
    rebuilt_one = tmp_path / "rebuilt-one" / EXPECTED_WHEEL
    rebuilt_two = tmp_path / "rebuilt-two" / EXPECTED_WHEEL
    entries = wheel_entries(metadata_bytes())
    write_wheel(rebuilt_one, entries, timestamp=(2025, 1, 1, 0, 0, 0))
    write_wheel(rebuilt_two, list(reversed(entries)), timestamp=(2026, 1, 1, 0, 0, 0))
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_artifacts.py",
            str(dist_dir),
            "--expected-version",
            "1.0.4",
            "--rebuilt-wheel",
            str(rebuilt_one),
            "--rebuilt-wheel",
            str(rebuilt_two),
            "--manifest",
            str(manifest),
        ],
    )

    assert module.main() is None
    assert manifest.is_file()
    assert (
        json.loads(manifest.read_text(encoding="utf-8"))["artifacts"][0]["filename"] == wheel.name
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
    assert "--rebuilt-wheel" in completed.stdout
    assert "--manifest" in completed.stdout


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
            str(tmp_path),
            "--expected-version",
            "1.0.4",
            "--manifest",
            str(tmp_path / "manifest.json"),
        ],
    )

    with pytest.raises(SystemExit, match="exact release archives"):
        module.main()


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


@pytest.mark.parametrize("artifact_name", [EXPECTED_WHEEL, EXPECTED_SDIST])
def test_manifest_rejects_direct_input_path_alias(
    tmp_path: Path,
    artifact_name: str,
) -> None:
    module = release_module()
    wheel, sdist = write_artifact_pair(tmp_path)
    artifacts = module.ArtifactSet(wheel, sdist)
    destination = tmp_path / artifact_name
    before = destination.read_bytes()

    with pytest.raises(ValueError, match="alias of a release artifact"):
        module.write_artifact_manifest(artifacts, destination)

    assert destination.read_bytes() == before


def test_manifest_rejects_symlink_destination_without_touching_target(tmp_path: Path) -> None:
    module = release_module()
    wheel, sdist = write_artifact_pair(tmp_path / "dist")
    artifacts = module.ArtifactSet(wheel, sdist)
    target = tmp_path / "existing-manifest.json"
    target.write_text("preserve me\n", encoding="utf-8")
    destination = tmp_path / "artifact-manifest.json"
    destination.symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        module.write_artifact_manifest(artifacts, destination)

    assert target.read_text(encoding="utf-8") == "preserve me\n"
    assert destination.is_symlink()


@pytest.mark.skipif(not hasattr(os, "link"), reason="hardlinks are unavailable")
def test_manifest_rejects_hardlink_alias_without_touching_artifact(tmp_path: Path) -> None:
    module = release_module()
    wheel, sdist = write_artifact_pair(tmp_path / "dist")
    artifacts = module.ArtifactSet(wheel, sdist)
    destination = tmp_path / "artifact-manifest.json"
    before = wheel.read_bytes()
    os.link(wheel, destination)

    with pytest.raises(ValueError, match="alias of a release artifact"):
        module.write_artifact_manifest(artifacts, destination)

    assert wheel.read_bytes() == before
    assert destination.read_bytes() == before


def test_manifest_rejects_special_file_destination(tmp_path: Path) -> None:
    module = release_module()
    wheel, sdist = write_artifact_pair(tmp_path / "dist")
    destination = tmp_path / "artifact-manifest.json"
    destination.mkdir()

    with pytest.raises(ValueError, match="non-symlink regular file"):
        module.write_artifact_manifest(module.ArtifactSet(wheel, sdist), destination)


def test_manifest_replace_failure_preserves_destination_and_removes_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = release_module()
    wheel, sdist = write_artifact_pair(tmp_path / "dist")
    destination = tmp_path / "artifact-manifest.json"
    destination.write_text("previous complete manifest\n", encoding="utf-8")

    def fail_replace(source: str | Path, target: str | Path) -> None:
        source_path = Path(source)
        assert source_path.parent == destination.parent
        assert source_path.is_file()
        assert Path(target) == destination
        raise OSError("synthetic atomic replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(ValueError, match="write the release artifact manifest"):
        module.write_artifact_manifest(module.ArtifactSet(wheel, sdist), destination)

    assert destination.read_text(encoding="utf-8") == "previous complete manifest\n"
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []


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
        "artifact-manifest",
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
        if interface == "artifact-manifest":
            sdist = hostile.parent / EXPECTED_SDIST
            write_sdist(sdist, metadata_bytes())
            module.write_artifact_manifest(
                module.ArtifactSet(hostile, sdist),
                tmp_path / "manifest.json",
            )
        else:
            invoke_wheel_archive_interface(module, interface, hostile, tmp_path)


@pytest.mark.parametrize("interface", ["artifact-pair", "artifact-manifest"])
def test_sdist_compressed_size_limit_applies_to_every_direct_interface(
    tmp_path: Path,
    interface: str,
) -> None:
    module = release_module()
    wheel = tmp_path / EXPECTED_WHEEL
    sdist = tmp_path / EXPECTED_SDIST
    write_wheel(wheel, wheel_entries(metadata_bytes()))
    sdist.write_bytes(b"x" * (5 * 1024 * 1024 + 1))

    with pytest.raises(ValueError, match="compressed size"):
        artifacts = module.ArtifactSet(wheel, sdist)
        if interface == "artifact-pair":
            module.verify_artifact_pair(artifacts, "1.0.4")
        else:
            module.write_artifact_manifest(artifacts, tmp_path / "manifest.json")


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
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.4")


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
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.4")


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
        module.verify_artifact_pair(module.ArtifactSet(wheel, sdist), "1.0.4")

    expected_yielded = 4097 if budget == "member count" else 1
    assert archive.yielded == expected_yielded
