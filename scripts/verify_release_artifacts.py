"""Verify exact release metadata, semantic wheel rebuilds, and artifact hashes."""

from __future__ import annotations

import argparse
import configparser
import email.policy
import hashlib
import json
import os
import posixpath
import re
import stat
import tarfile
import tempfile
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from typing import BinaryIO

try:
    from scripts.audit_package_contents import (
        MEMBER_EXPANDED_SIZE_LIMIT,
        SDIST_EXPANDED_SIZE_LIMIT,
        SDIST_SIZE_LIMIT,
        WHEEL_EXPANDED_SIZE_LIMIT,
        WHEEL_SIZE_LIMIT,
        find_archives,
    )
except ModuleNotFoundError:
    from audit_package_contents import (  # type: ignore[no-redef]
        MEMBER_EXPANDED_SIZE_LIMIT,
        SDIST_EXPANDED_SIZE_LIMIT,
        SDIST_SIZE_LIMIT,
        WHEEL_EXPANDED_SIZE_LIMIT,
        WHEEL_SIZE_LIMIT,
        find_archives,
    )

EXPECTED_VERSION = "1.0.3"
EXPECTED_WHEEL = "localql-1.0.3-py3-none-any.whl"
EXPECTED_SDIST = "localql-1.0.3.tar.gz"
EXPECTED_ENTRY_POINT = "csvql = csvql.cli:main"
EXPECTED_DIST_INFO = "localql-1.0.3.dist-info"
EXPECTED_SDIST_ROOT = "localql-1.0.3"
EXPECTED_RECORD = "localql-1.0.3.dist-info/RECORD"

METADATA_KEYS = (
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

REPEATABLE_METADATA_KEYS = {
    "Requires-Dist",
    "Provides-Extra",
    "Project-URL",
    "Classifier",
}
MAX_ARCHIVE_MEMBERS = 4096
MAX_MEMBER_NAME_BYTES = 1024 * 1024
HASH_CHUNK_SIZE = 1024 * 1024
READ_CHUNK_SIZE = 64 * 1024


class ArtifactVerificationError(ValueError):
    """Raised when an artifact fails a bounded identity or agreement check."""


@dataclass(frozen=True, slots=True)
class ArtifactSet:
    """The exact wheel and sdist selected for one release candidate."""

    wheel: Path
    sdist: Path


def _fail(message: str) -> ArtifactVerificationError:
    return ArtifactVerificationError(message)


def _validate_expected_version(expected_version: str) -> None:
    if expected_version != EXPECTED_VERSION:
        raise _fail(f"Expected release version must be {EXPECTED_VERSION}.")


def _validate_regular_artifact(
    path: Path,
    expected_name: str,
    compressed_size_limit: int,
) -> None:
    if path.name != expected_name:
        raise _fail("Release artifact filename does not match the exact expected identity.")
    try:
        artifact_stat = path.lstat()
    except OSError:
        raise _fail("Release artifact must be an accessible regular file.") from None
    if path.is_symlink() or not stat.S_ISREG(artifact_stat.st_mode):
        raise _fail("Release artifact must be a non-symlink regular file.")
    if artifact_stat.st_size > compressed_size_limit:
        raise _fail("Release artifact exceeds the compressed size limit.")


def _validate_artifact_paths(artifacts: ArtifactSet) -> None:
    _validate_regular_artifact(artifacts.wheel, EXPECTED_WHEEL, WHEEL_SIZE_LIMIT)
    _validate_regular_artifact(artifacts.sdist, EXPECTED_SDIST, SDIST_SIZE_LIMIT)
    try:
        wheel_parent = artifacts.wheel.parent.resolve(strict=True)
        sdist_parent = artifacts.sdist.parent.resolve(strict=True)
    except OSError:
        raise _fail("Release artifact directory could not be resolved.") from None
    if wheel_parent != sdist_parent:
        raise _fail("Release wheel and sdist must be selected from the same directory.")


def _is_canonical_member_name(name: str, *, is_directory: bool) -> bool:
    if not name or name.startswith("/") or "\\" in name or "//" in name:
        return False
    if any(not character.isprintable() for character in name):
        return False
    canonical_name = name[:-1] if is_directory and name.endswith("/") else name
    if not canonical_name or (name.endswith("/") and not is_directory):
        return False
    parts = canonical_name.split("/")
    if any(part in {"", ".", ".."} or re.match(r"^[A-Za-z]:", part) for part in parts):
        return False
    return posixpath.normpath(canonical_name) == canonical_name


def _normalized_member_name(name: str) -> str:
    return posixpath.normpath(name.replace("\\", "/")).lstrip("/").rstrip("/")


def _zip_member_kind(info: zipfile.ZipInfo) -> tuple[bool, bool]:
    filename_is_directory = info.is_dir()
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode) if info.create_system == 3 else 0
    if file_type == 0:
        return not filename_is_directory, filename_is_directory
    unix_is_directory = file_type == stat.S_IFDIR
    metadata_agrees = filename_is_directory == unix_is_directory
    return metadata_agrees and file_type == stat.S_IFREG, metadata_agrees and unix_is_directory


def _reject_duplicate_or_ambiguous_names(
    names_and_directory_flags: list[tuple[str, bool]],
    *,
    role: str,
) -> None:
    names = [name for name, _ in names_and_directory_flags]
    if any(count > 1 for count in Counter(names).values()):
        raise _fail(f"{role} contains duplicate archive members.")

    normalized_names: defaultdict[str, list[str]] = defaultdict(list)
    for name, _ in names_and_directory_flags:
        normalized_names[_normalized_member_name(name)].append(name)
    if any(len(raw_names) > 1 for raw_names in normalized_names.values()):
        raise _fail(f"{role} contains ambiguous normalized archive members.")


def _member_name_size(name: str, *, role: str) -> int:
    try:
        return len(name.encode("utf-8"))
    except UnicodeEncodeError:
        raise _fail(f"{role} contains a noncanonical member name.") from None


def _validate_member_metadata_budget(
    *,
    role: str,
    member_count: int,
    member_name_bytes: int,
) -> None:
    if member_count > MAX_ARCHIVE_MEMBERS:
        raise _fail(f"{role} member count exceeds the metadata budget.")
    if member_name_bytes > MAX_MEMBER_NAME_BYTES:
        raise _fail(f"{role} member-name bytes exceed the metadata budget.")


def _validate_dist_info_namespace(
    infos: list[zipfile.ZipInfo],
    kinds: list[tuple[bool, bool]],
) -> None:
    canonical_namespace_seen = False
    for info, (_, is_directory) in zip(infos, kinds, strict=True):
        name = info.filename[:-1] if is_directory and info.filename.endswith("/") else info.filename
        components = name.split("/")
        dist_info_components = [
            (index, component)
            for index, component in enumerate(components)
            if component.endswith(".dist-info")
        ]
        if not dist_info_components:
            continue
        if dist_info_components != [(0, EXPECTED_DIST_INFO)]:
            raise _fail("Wheel archive contains a noncanonical dist-info namespace.")
        if len(components) == 1 and not is_directory:
            raise _fail("Wheel archive contains a noncanonical dist-info namespace.")
        canonical_namespace_seen = True
    if not canonical_namespace_seen:
        raise _fail("Wheel archive is missing the canonical dist-info namespace.")


def _validated_zip_infos(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    _validate_member_metadata_budget(
        role="Wheel archive",
        member_count=len(infos),
        member_name_bytes=0,
    )
    member_name_bytes = sum(
        _member_name_size(info.filename, role="Wheel archive") for info in infos
    )
    _validate_member_metadata_budget(
        role="Wheel archive",
        member_count=len(infos),
        member_name_bytes=member_name_bytes,
    )
    kinds = [_zip_member_kind(info) for info in infos]
    names_and_directory_flags = [
        (info.filename, is_directory) for info, (_, is_directory) in zip(infos, kinds, strict=True)
    ]
    _reject_duplicate_or_ambiguous_names(names_and_directory_flags, role="Wheel archive")

    total_size = 0
    for info, (is_regular, is_directory) in zip(infos, kinds, strict=True):
        if not _is_canonical_member_name(info.filename, is_directory=is_directory):
            raise _fail("Wheel archive contains a noncanonical member name.")
        if not is_regular and not is_directory:
            raise _fail("Wheel archive contains a special member.")
        if is_directory and info.file_size != 0:
            raise _fail("Wheel archive contains a payload-bearing directory.")
        if info.file_size < 0 or info.file_size > MEMBER_EXPANDED_SIZE_LIMIT:
            raise _fail("Wheel archive member exceeds the expanded size limit.")
        total_size += info.file_size
    if total_size > WHEEL_EXPANDED_SIZE_LIMIT:
        raise _fail("Wheel archive exceeds the expanded total size limit.")
    _validate_dist_info_namespace(infos, kinds)
    return infos


def _validated_tar_infos(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    infos: list[tarfile.TarInfo] = []
    member_name_bytes = 0
    for info in archive:
        member_name_bytes += _member_name_size(info.name, role="Sdist archive")
        _validate_member_metadata_budget(
            role="Sdist archive",
            member_count=len(infos) + 1,
            member_name_bytes=member_name_bytes,
        )
        infos.append(info)
    names_and_directory_flags = [(info.name, info.isdir()) for info in infos]
    _reject_duplicate_or_ambiguous_names(names_and_directory_flags, role="Sdist archive")

    total_size = 0
    for info in infos:
        if not _is_canonical_member_name(info.name, is_directory=info.isdir()):
            raise _fail("Sdist archive contains a noncanonical member name.")
        if not info.isreg() and not info.isdir():
            raise _fail("Sdist archive contains a special member.")
        if info.isdir() and info.size != 0:
            raise _fail("Sdist archive contains a payload-bearing directory.")
        if info.size < 0 or info.size > MEMBER_EXPANDED_SIZE_LIMIT:
            raise _fail("Sdist archive member exceeds the expanded size limit.")
        total_size += info.size
    if total_size > SDIST_EXPANDED_SIZE_LIMIT:
        raise _fail("Sdist archive exceeds the expanded total size limit.")
    return infos


def _read_bounded(member_file: BinaryIO, declared_size: int, *, role: str) -> bytes:
    payload = bytearray()
    while chunk := member_file.read(READ_CHUNK_SIZE):
        payload.extend(chunk)
        if len(payload) > declared_size or len(payload) > MEMBER_EXPANDED_SIZE_LIMIT:
            raise _fail(f"{role} payload exceeds its declared bounded size.")
    if len(payload) != declared_size:
        raise _fail(f"{role} payload does not match its declared size.")
    return bytes(payload)


def _read_zip_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    role: str,
) -> bytes:
    try:
        with archive.open(info) as member_file:
            return _read_bounded(member_file, info.file_size, role=role)
    except ArtifactVerificationError:
        raise
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile):
        raise _fail(f"Unable to read {role} payload.") from None


def _read_tar_member(
    archive: tarfile.TarFile,
    info: tarfile.TarInfo,
    *,
    role: str,
) -> bytes:
    try:
        member_file = archive.extractfile(info)
        if member_file is None:
            raise _fail(f"Unable to read {role} payload.")
        with member_file:
            return _read_bounded(member_file, info.size, role=role)
    except ArtifactVerificationError:
        raise
    except (OSError, EOFError, tarfile.TarError):
        raise _fail(f"Unable to read {role} payload.") from None


def metadata_contract(message: Message) -> dict[str, tuple[str, ...]]:
    """Return the normalized metadata fields that must agree across artifacts."""

    if message.defects:
        raise _fail("Package metadata contains parser defects.")

    contract: dict[str, tuple[str, ...]] = {}
    for key in METADATA_KEYS:
        raw_values = message.get_all(key, [])
        values = tuple(sorted(str(value).strip() for value in raw_values))
        if key not in REPEATABLE_METADATA_KEYS and len(values) > 1:
            raise _fail(f"Package metadata contains a duplicate {key} header.")
        if len(values) != len(set(values)):
            raise _fail(f"Package metadata contains a duplicate {key} value.")
        if any(
            not value or any(not character.isprintable() for character in value) for value in values
        ):
            raise _fail(f"Package metadata contains an invalid {key} value.")
        contract[key] = values
    return contract


def _metadata_description(message: Message) -> str:
    payload = message.get_payload()
    if not isinstance(payload, str):
        raise _fail("Package metadata long description must be a single text payload.")
    return payload.rstrip()


def _parse_metadata(payload: bytes) -> Message:
    message = BytesParser(policy=email.policy.default).parsebytes(payload)
    metadata_contract(message)
    _metadata_description(message)
    return message


def _wheel_metadata(path: Path) -> tuple[str, Message, bytes]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = _validated_zip_infos(archive)
            candidates = [
                info
                for info in infos
                if len(info.filename.split("/")) == 2
                and info.filename.endswith(".dist-info/METADATA")
                and _zip_member_kind(info)[0]
            ]
            if len(candidates) != 1:
                raise _fail("Wheel must contain exactly one dist-info METADATA file.")
            metadata_info = candidates[0]
            root = metadata_info.filename.split("/", maxsplit=1)[0]
            payload = _read_zip_member(archive, metadata_info, role="wheel METADATA")
            return root, _parse_metadata(payload), payload
    except ArtifactVerificationError:
        raise
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile):
        raise _fail("Unable to inspect wheel metadata.") from None


def _sdist_metadata(path: Path) -> tuple[str, Message]:
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            infos = _validated_tar_infos(archive)
            candidates = [
                info
                for info in infos
                if len(info.name.split("/")) == 2
                and info.name.endswith("/PKG-INFO")
                and info.isreg()
            ]
            if len(candidates) != 1:
                raise _fail("Sdist must contain exactly one two-component root PKG-INFO file.")
            metadata_info = candidates[0]
            root = metadata_info.name.split("/", maxsplit=1)[0]
            payload = _read_tar_member(archive, metadata_info, role="sdist PKG-INFO")
            return root, _parse_metadata(payload)
    except ArtifactVerificationError:
        raise
    except (OSError, EOFError, tarfile.TarError):
        raise _fail("Unable to inspect sdist metadata.") from None


def _verify_entry_point(path: Path, dist_info_root: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = _validated_zip_infos(archive)
            expected_member = f"{dist_info_root}/entry_points.txt"
            candidates = [
                info
                for info in infos
                if info.filename.endswith(".dist-info/entry_points.txt")
                and _zip_member_kind(info)[0]
            ]
            if len(candidates) != 1 or candidates[0].filename != expected_member:
                raise _fail("Wheel must contain exactly one entry point metadata file.")
            payload = _read_zip_member(archive, candidates[0], role="wheel entry point")
    except ArtifactVerificationError:
        raise
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile):
        raise _fail("Unable to inspect wheel entry point metadata.") from None

    try:
        text = payload.decode("utf-8")
        parser = configparser.ConfigParser(
            interpolation=None,
            strict=True,
            empty_lines_in_values=False,
        )
        parser.optionxform = str
        parser.read_string(text)
        if parser.defaults() or not parser.has_section("console_scripts"):
            raise _fail("Wheel does not define the exact required console entry point.")
        target = parser["console_scripts"].get("csvql")
        if target is None or f"csvql = {target.strip()}" != EXPECTED_ENTRY_POINT:
            raise _fail("Wheel does not define the exact required console entry point.")
    except ArtifactVerificationError:
        raise
    except (UnicodeDecodeError, configparser.Error):
        raise _fail("Wheel entry point metadata is invalid.") from None


def _verify_metadata_agreement(left: Message, right: Message, *, context: str) -> None:
    if metadata_contract(left) != metadata_contract(right):
        raise _fail(f"{context} metadata contract mismatch.")
    if _metadata_description(left) != _metadata_description(right):
        raise _fail(f"{context} long description mismatch.")


def _verify_release_metadata_identity(message: Message, expected_version: str) -> None:
    contract = metadata_contract(message)
    if contract["Name"] != ("localql",) or contract["Version"] != (expected_version,):
        raise _fail("Release metadata identity does not match localql and the expected version.")


def verify_artifact_pair(artifacts: ArtifactSet, expected_version: str) -> None:
    """Verify exact wheel/sdist identity, metadata agreement, and console entry point."""

    _validate_expected_version(expected_version)
    _validate_artifact_paths(artifacts)
    wheel_root, wheel_message, _ = _wheel_metadata(artifacts.wheel)
    sdist_root, sdist_message = _sdist_metadata(artifacts.sdist)
    if wheel_root != EXPECTED_DIST_INFO or sdist_root != EXPECTED_SDIST_ROOT:
        raise _fail("Release archive metadata roots do not match the exact expected identity.")
    _verify_release_metadata_identity(wheel_message, expected_version)
    _verify_release_metadata_identity(sdist_message, expected_version)
    _verify_metadata_agreement(wheel_message, sdist_message, context="Wheel/sdist")
    _verify_entry_point(artifacts.wheel, wheel_root)


def _sha256_stream(member_file: BinaryIO) -> str:
    digest = hashlib.sha256()
    observed_size = 0
    while chunk := member_file.read(HASH_CHUNK_SIZE):
        observed_size += len(chunk)
        if observed_size > MEMBER_EXPANDED_SIZE_LIMIT:
            raise _fail("Wheel member exceeds the bounded hashing size.")
        digest.update(chunk)
    return digest.hexdigest()


def semantic_wheel_manifest(path: Path) -> dict[str, str]:
    """Return content digests for canonical wheel members other than RECORD."""

    _validate_regular_artifact(path, EXPECTED_WHEEL, WHEEL_SIZE_LIMIT)
    try:
        with zipfile.ZipFile(path) as archive:
            infos = _validated_zip_infos(archive)
            manifest: dict[str, str] = {}
            for info in sorted(infos, key=lambda item: item.filename):
                is_regular, _ = _zip_member_kind(info)
                if not is_regular or info.filename == EXPECTED_RECORD:
                    continue
                with archive.open(info) as member_file:
                    manifest[info.filename] = _sha256_stream(member_file)
            return manifest
    except ArtifactVerificationError:
        raise
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile):
        raise _fail("Unable to build semantic wheel manifest.") from None


def verify_rebuilt_wheel(original: Path, rebuilt: Path) -> None:
    """Require a rebuilt wheel to match metadata and decompressed member content."""

    _validate_regular_artifact(original, EXPECTED_WHEEL, WHEEL_SIZE_LIMIT)
    _validate_regular_artifact(rebuilt, EXPECTED_WHEEL, WHEEL_SIZE_LIMIT)
    original_root, original_message, _ = _wheel_metadata(original)
    rebuilt_root, rebuilt_message, _ = _wheel_metadata(rebuilt)
    if original_root != EXPECTED_DIST_INFO or rebuilt_root != EXPECTED_DIST_INFO:
        raise _fail("Rebuilt wheel metadata root does not match the expected identity.")
    _verify_metadata_agreement(original_message, rebuilt_message, context="Rebuilt wheel")
    if semantic_wheel_manifest(original) != semantic_wheel_manifest(rebuilt):
        raise _fail("Rebuilt wheel semantic member or content mismatch.")


def sha256_file(path: Path) -> str:
    """Hash a file by streaming it in one MiB chunks."""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_manifest_destination(artifacts: ArtifactSet, destination: Path) -> None:
    try:
        destination_stat = destination.lstat()
    except FileNotFoundError:
        return
    except OSError:
        raise _fail("Unable to inspect the release artifact manifest destination.") from None

    if stat.S_ISLNK(destination_stat.st_mode):
        raise _fail("Release artifact manifest destination must not be a symlink.")
    if not stat.S_ISREG(destination_stat.st_mode):
        raise _fail(
            "Release artifact manifest destination must be absent or a non-symlink regular file."
        )
    try:
        aliases_input = any(
            os.path.samefile(destination, artifact)
            for artifact in (artifacts.wheel, artifacts.sdist)
        )
    except OSError:
        raise _fail("Unable to compare the release artifact manifest destination.") from None
    if aliases_input:
        raise _fail("Release artifact manifest destination is an alias of a release artifact.")


def _remove_temporary_manifest(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        raise _fail("Unable to clean up the temporary release artifact manifest.") from None


def _write_manifest_atomically(
    artifacts: ArtifactSet,
    destination: Path,
    content: str,
) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        _validate_manifest_destination(artifacts, destination)
        os.replace(temporary_path, destination)
    except ArtifactVerificationError:
        if temporary_path is not None:
            _remove_temporary_manifest(temporary_path)
        raise
    except OSError:
        if temporary_path is not None:
            _remove_temporary_manifest(temporary_path)
        raise _fail("Unable to write the release artifact manifest.") from None
    else:
        if temporary_path is not None:
            _remove_temporary_manifest(temporary_path)


def write_artifact_manifest(artifacts: ArtifactSet, destination: Path) -> None:
    """Write the deterministic SHA-256 and size manifest for the exact artifact pair."""

    _validate_artifact_paths(artifacts)
    _validate_manifest_destination(artifacts, destination)
    try:
        payload = {
            "artifacts": [
                {
                    "filename": artifacts.wheel.name,
                    "sha256": sha256_file(artifacts.wheel),
                    "size": artifacts.wheel.stat().st_size,
                },
                {
                    "filename": artifacts.sdist.name,
                    "sha256": sha256_file(artifacts.sdist),
                    "size": artifacts.sdist.stat().st_size,
                },
            ],
            "distribution": "localql",
            "version": "1.0.3",
        }
        content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    except OSError:
        raise _fail("Unable to write the release artifact manifest.") from None
    _write_manifest_atomically(artifacts, destination, content)


def main() -> None:
    """Verify exact artifacts, optional rebuilds, and write the release manifest."""

    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--rebuilt-wheel", action="append", type=Path, default=[])
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    wheel, sdist = find_archives(args.dist_dir, args.expected_version)
    artifacts = ArtifactSet(wheel=wheel, sdist=sdist)
    try:
        verify_artifact_pair(artifacts, args.expected_version)
        for rebuilt_wheel in args.rebuilt_wheel:
            verify_rebuilt_wheel(artifacts.wheel, rebuilt_wheel)
        write_artifact_manifest(artifacts, args.manifest)
    except ArtifactVerificationError as error:
        raise SystemExit(str(error)) from None
    print(
        "Release artifact verification passed: "
        f"1 wheel(s), 1 sdist(s), {len(args.rebuilt_wheel)} rebuilt wheel(s)."
    )


if __name__ == "__main__":
    main()
