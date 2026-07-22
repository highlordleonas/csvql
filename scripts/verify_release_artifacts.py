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
        is_protected_package_path,
    )
except ModuleNotFoundError:
    from audit_package_contents import (  # type: ignore[no-redef]
        MEMBER_EXPANDED_SIZE_LIMIT,
        SDIST_EXPANDED_SIZE_LIMIT,
        SDIST_SIZE_LIMIT,
        WHEEL_EXPANDED_SIZE_LIMIT,
        WHEEL_SIZE_LIMIT,
        is_protected_package_path,
    )

EXPECTED_VERSION = "1.0.5"
EXPECTED_WHEEL = "localql-1.0.5-py3-none-any.whl"
EXPECTED_SDIST = "localql-1.0.5.tar.gz"
EXPECTED_ENTRY_POINT = "csvql = csvql.cli:main"
EXPECTED_DIST_INFO = "localql-1.0.5.dist-info"
EXPECTED_SDIST_ROOT = "localql-1.0.5"
EXPECTED_RECORD = "localql-1.0.5.dist-info/RECORD"

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
CUSTODY_INPUT_SIZE_LIMIT = 64 * 1024
IDENTITY_INPUT_SIZE_LIMIT = 4 * 1024
LOWER_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
LOWER_SHA256_RE = re.compile(r"[0-9a-f]{64}")
CONSTRAINTS_DIGEST_RE = re.compile(r"([0-9a-f]{64})  scripts/release-build-constraints\.txt\n")


class ArtifactVerificationError(ValueError):
    """Raised when an artifact fails a bounded identity or agreement check."""


@dataclass(frozen=True, slots=True)
class ArtifactSet:
    """The exact wheel and sdist selected for one release candidate."""

    wheel: Path
    sdist: Path


@dataclass(frozen=True, slots=True)
class CustodyContext:
    """Validated immutable source and build-tool identity for one artifact pair."""

    source_commit: str
    tag_name: str
    tag_object: str
    peeled_commit: str
    python_identity: str
    uv_identity: str
    build_constraints_sha256: str


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


def _reject_protected_package_members(
    names: list[str],
    *,
    role: str,
    project_root: str | None = None,
) -> None:
    """Reject protected project paths after canonical archive-name validation."""

    for name in names:
        parts = tuple(name.rstrip("/").split("/"))
        if project_root is not None and parts and parts[0] == project_root:
            parts = parts[1:]
        if is_protected_package_path(parts):
            raise _fail(f"{role} contains a protected package member.")


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
    _reject_protected_package_members(
        [info.filename for info in infos],
        role="Wheel archive",
    )
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
    _reject_protected_package_members(
        [info.name for info in infos],
        role="Sdist archive",
        project_root=EXPECTED_SDIST_ROOT,
    )
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


def _select_exact_artifact_pair(dist_dir: Path, expected_version: str) -> ArtifactSet:
    _validate_expected_version(expected_version)
    try:
        directory_stat = dist_dir.lstat()
        entries = list(dist_dir.iterdir())
    except OSError:
        raise _fail("Unable to inspect the exact release artifact directory.") from None
    if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
        raise _fail("Expected an accessible non-symlink release artifact directory.")
    expected_names = {EXPECTED_WHEEL, EXPECTED_SDIST}
    if len(entries) != 2 or {entry.name for entry in entries} != expected_names:
        raise _fail("Expected exact release artifacts: one wheel and one sdist.")

    wheel = dist_dir / EXPECTED_WHEEL
    sdist = dist_dir / EXPECTED_SDIST
    try:
        entry_stats = [wheel.lstat(), sdist.lstat()]
        aliases = os.path.samefile(wheel, sdist)
    except OSError:
        raise _fail("Expected exact release artifacts as accessible regular files.") from None
    if aliases or any(
        stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISREG(entry_stat.st_mode)
        for entry_stat in entry_stats
    ):
        raise _fail("Expected exact release artifacts as distinct non-symlink regular files.")
    return ArtifactSet(wheel, sdist)


def _read_bounded_regular_file(path: Path, *, size_limit: int, role: str) -> bytes:
    try:
        path_stat = path.lstat()
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or path_stat.st_size > size_limit
        ):
            raise _fail(f"{role} must be a bounded non-symlink regular file.")
        with path.open("rb") as input_file:
            opened_stat = os.fstat(input_file.fileno())
            if (opened_stat.st_dev, opened_stat.st_ino) != (
                path_stat.st_dev,
                path_stat.st_ino,
            ) or not stat.S_ISREG(opened_stat.st_mode):
                raise _fail(f"{role} must be a stable non-symlink regular file.")
            content = input_file.read(size_limit + 1)
            final_stat = os.fstat(input_file.fileno())
    except ArtifactVerificationError:
        raise
    except OSError:
        raise _fail(f"Unable to read the bounded {role.lower()}.") from None
    if (
        len(content) > size_limit
        or final_stat.st_size != len(content)
        or path_stat.st_size != len(content)
    ):
        raise _fail(f"{role} must remain within its bounded input size.")
    return content


def _identity_line(path: Path, *, role: str) -> str:
    content = _read_bounded_regular_file(
        path,
        size_limit=IDENTITY_INPUT_SIZE_LIMIT,
        role=role,
    )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise _fail(f"{role} is not a valid identity line.") from None
    line = text[:-1] if text.endswith("\n") else text
    if not line or "\n" in line or "\r" in line or not line.isprintable():
        raise _fail(f"{role} is not a valid identity line.")
    return line


def _constraints_digest(path: Path) -> str:
    content = _read_bounded_regular_file(
        path,
        size_limit=IDENTITY_INPUT_SIZE_LIMIT,
        role="Build constraints digest evidence",
    )
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError:
        raise _fail("Build constraints digest evidence is invalid.") from None
    match = CONSTRAINTS_DIGEST_RE.fullmatch(text)
    if match is None:
        raise _fail("Build constraints digest evidence is invalid.")
    return match.group(1)


def _load_custody_context(
    expected_version: str,
    *,
    source_commit: str,
    tag_name: str,
    tag_object: str,
    peeled_commit: str,
    python_identity_file: Path,
    uv_identity_file: Path,
    build_constraints_digest_file: Path,
) -> CustodyContext:
    expected_tag = f"v{expected_version}"
    if (
        LOWER_COMMIT_RE.fullmatch(source_commit) is None
        or LOWER_COMMIT_RE.fullmatch(tag_object) is None
        or LOWER_COMMIT_RE.fullmatch(peeled_commit) is None
        or tag_name != expected_tag
        or peeled_commit != source_commit
        or tag_object == peeled_commit
    ):
        raise _fail("Release custody source identity is invalid.")
    return CustodyContext(
        source_commit=source_commit,
        tag_name=tag_name,
        tag_object=tag_object,
        peeled_commit=peeled_commit,
        python_identity=_identity_line(python_identity_file, role="Python identity evidence"),
        uv_identity=_identity_line(uv_identity_file, role="uv identity evidence"),
        build_constraints_sha256=_constraints_digest(build_constraints_digest_file),
    )


def _stable_artifact_record(path: Path) -> dict[str, object]:
    try:
        before = path.lstat()
        digest = sha256_file(path)
        after = path.lstat()
    except OSError:
        raise _fail("Unable to recompute release artifact custody metadata.") from None
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if before.st_size <= 0 or any(
        getattr(before, field) != getattr(after, field) for field in stable_fields
    ):
        raise _fail("Release artifact changed during custody metadata calculation.")
    return {"filename": path.name, "sha256": digest, "size": before.st_size}


def _custody_manifest_payload(
    artifacts: ArtifactSet,
    expected_version: str,
    context: CustodyContext,
) -> dict[str, object]:
    return {
        "artifacts": [
            _stable_artifact_record(artifacts.wheel),
            _stable_artifact_record(artifacts.sdist),
        ],
        "distribution": "localql",
        "schema_version": 1,
        "source": {
            "commit": context.source_commit,
            "peeled_commit": context.peeled_commit,
            "tag": context.tag_name,
            "tag_object": context.tag_object,
        },
        "toolchain": {
            "build_constraints_sha256": context.build_constraints_sha256,
            "python": context.python_identity,
            "uv": context.uv_identity,
        },
        "version": expected_version,
    }


def _manifest_text(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _sha256sums_text(payload: dict[str, object]) -> str:
    artifacts = payload["artifacts"]
    assert isinstance(artifacts, list)
    return "".join(
        f"{artifact['sha256']}  {artifact['filename']}\n"
        for artifact in artifacts
        if isinstance(artifact, dict)
    )


def _paths_alias(left: Path, right: Path) -> bool:
    try:
        normalized_left = left.resolve(strict=False)
        normalized_right = right.resolve(strict=False)
    except OSError:
        raise _fail("Unable to normalize release custody paths safely.") from None
    if normalized_left == normalized_right:
        return True
    try:
        return os.path.samefile(left, right)
    except FileNotFoundError:
        return False
    except OSError:
        raise _fail("Unable to compare release custody paths safely.") from None


def _validate_atomic_destination(destination: Path, protected_paths: tuple[Path, ...]) -> None:
    try:
        parent_stat = destination.parent.lstat()
    except OSError:
        raise _fail("Release custody destination parent is not accessible.") from None
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise _fail("Release custody destination parent must be a non-symlink directory.")
    try:
        destination_stat = destination.lstat()
    except FileNotFoundError:
        destination_stat = None
    except OSError:
        raise _fail("Unable to inspect a release custody destination.") from None
    if destination_stat is not None and (
        stat.S_ISLNK(destination_stat.st_mode) or not stat.S_ISREG(destination_stat.st_mode)
    ):
        raise _fail("Release custody destination must be absent or a non-symlink regular file.")
    if any(_paths_alias(destination, protected_path) for protected_path in protected_paths):
        raise _fail("Release custody destination aliases a protected input.")


def _remove_temporary_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        raise _fail("Unable to clean up a temporary release custody file.") from None


def _write_text_atomically(
    destination: Path,
    content: str,
    protected_paths: tuple[Path, ...],
) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        _validate_atomic_destination(destination, protected_paths)
        os.replace(temporary_path, destination)
    except ArtifactVerificationError:
        if temporary_path is not None:
            _remove_temporary_file(temporary_path)
        raise
    except OSError:
        if temporary_path is not None:
            _remove_temporary_file(temporary_path)
        raise _fail("Unable to write a release custody file atomically.") from None


def create_custody_files(
    artifacts: ArtifactSet,
    expected_version: str,
    *,
    manifest: Path,
    sha256sums: Path,
    source_commit: str,
    tag_name: str,
    tag_object: str,
    peeled_commit: str,
    python_identity_file: Path,
    uv_identity_file: Path,
    build_constraints_digest_file: Path,
) -> None:
    """Verify artifacts and atomically create their strict custody files."""

    verify_artifact_pair(artifacts, expected_version)
    context = _load_custody_context(
        expected_version,
        source_commit=source_commit,
        tag_name=tag_name,
        tag_object=tag_object,
        peeled_commit=peeled_commit,
        python_identity_file=python_identity_file,
        uv_identity_file=uv_identity_file,
        build_constraints_digest_file=build_constraints_digest_file,
    )
    protected_paths = (
        artifacts.wheel,
        artifacts.sdist,
        python_identity_file,
        uv_identity_file,
        build_constraints_digest_file,
    )
    _validate_atomic_destination(manifest, protected_paths)
    _validate_atomic_destination(sha256sums, protected_paths)
    if _paths_alias(manifest, sha256sums):
        raise _fail("Release custody destinations must be distinct.")
    try:
        artifact_directory = artifacts.wheel.parent.resolve(strict=True)
        destination_directories = [
            destination.parent.resolve(strict=True) for destination in (manifest, sha256sums)
        ]
    except OSError:
        raise _fail("Unable to resolve release custody destination directories.") from None
    if artifact_directory in destination_directories:
        raise _fail("Release custody files must be outside the exact artifact directory.")

    payload = _custody_manifest_payload(artifacts, expected_version, context)
    _write_text_atomically(manifest, _manifest_text(payload), protected_paths)
    _write_text_atomically(sha256sums, _sha256sums_text(payload), protected_paths)


def _object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("Release custody manifest contains duplicate keys.")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise _fail("Release custody manifest contains an invalid JSON value.")


def _exact_dict(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise _fail("Release custody manifest has an invalid object schema.")
    return value


def _validate_custody_manifest_schema(
    payload: object,
    expected_version: str,
) -> dict[str, object]:
    manifest = _exact_dict(
        payload,
        {"artifacts", "distribution", "schema_version", "source", "toolchain", "version"},
    )
    if (
        manifest["distribution"] != "localql"
        or type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 1
        or manifest["version"] != expected_version
    ):
        raise _fail("Release custody manifest identity is invalid.")

    artifacts = manifest["artifacts"]
    if type(artifacts) is not list or len(artifacts) != 2:
        raise _fail("Release custody manifest artifact schema is invalid.")
    for value, expected_name in zip(artifacts, (EXPECTED_WHEEL, EXPECTED_SDIST), strict=True):
        artifact = _exact_dict(value, {"filename", "sha256", "size"})
        if (
            artifact["filename"] != expected_name
            or type(artifact["sha256"]) is not str
            or LOWER_SHA256_RE.fullmatch(artifact["sha256"]) is None
            or type(artifact["size"]) is not int
            or artifact["size"] <= 0
        ):
            raise _fail("Release custody manifest artifact entry is invalid.")

    source = _exact_dict(manifest["source"], {"commit", "peeled_commit", "tag", "tag_object"})
    if (
        type(source["commit"]) is not str
        or type(source["peeled_commit"]) is not str
        or type(source["tag"]) is not str
        or type(source["tag_object"]) is not str
        or LOWER_COMMIT_RE.fullmatch(source["commit"]) is None
        or LOWER_COMMIT_RE.fullmatch(source["peeled_commit"]) is None
        or LOWER_COMMIT_RE.fullmatch(source["tag_object"]) is None
        or source["commit"] != source["peeled_commit"]
        or source["tag"] != f"v{expected_version}"
        or source["tag_object"] == source["peeled_commit"]
    ):
        raise _fail("Release custody manifest source identity is invalid.")

    toolchain = _exact_dict(
        manifest["toolchain"],
        {"build_constraints_sha256", "python", "uv"},
    )
    if (
        type(toolchain["build_constraints_sha256"]) is not str
        or LOWER_SHA256_RE.fullmatch(toolchain["build_constraints_sha256"]) is None
        or type(toolchain["python"]) is not str
        or not toolchain["python"]
        or not toolchain["python"].isprintable()
        or type(toolchain["uv"]) is not str
        or not toolchain["uv"]
        or not toolchain["uv"].isprintable()
    ):
        raise _fail("Release custody manifest toolchain identity is invalid.")
    return manifest


def _parse_custody_manifest(path: Path, expected_version: str) -> dict[str, object]:
    content = _read_bounded_regular_file(
        path,
        size_limit=CUSTODY_INPUT_SIZE_LIMIT,
        role="Release custody manifest",
    )
    try:
        text = content.decode("utf-8")
        payload = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except ArtifactVerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _fail("Release custody manifest is malformed.") from None
    manifest = _validate_custody_manifest_schema(payload, expected_version)
    if content != _manifest_text(manifest).encode("utf-8"):
        raise _fail("Release custody manifest is not canonical.")
    return manifest


def verify_custody_files(
    artifacts: ArtifactSet,
    expected_version: str,
    *,
    manifest: Path,
    sha256sums: Path,
    source_commit: str,
    tag_name: str,
    tag_object: str,
    peeled_commit: str,
    python_identity_file: Path,
    uv_identity_file: Path,
    build_constraints_digest_file: Path,
) -> None:
    """Strictly verify transported custody files against independently supplied evidence."""

    verify_artifact_pair(artifacts, expected_version)
    context = _load_custody_context(
        expected_version,
        source_commit=source_commit,
        tag_name=tag_name,
        tag_object=tag_object,
        peeled_commit=peeled_commit,
        python_identity_file=python_identity_file,
        uv_identity_file=uv_identity_file,
        build_constraints_digest_file=build_constraints_digest_file,
    )
    transported_manifest = _parse_custody_manifest(manifest, expected_version)
    expected_manifest = _custody_manifest_payload(artifacts, expected_version, context)
    if transported_manifest != expected_manifest:
        raise _fail("Release custody manifest does not match recomputed evidence.")
    transported_sums = _read_bounded_regular_file(
        sha256sums,
        size_limit=CUSTODY_INPUT_SIZE_LIMIT,
        role="Release custody SHA256SUMS",
    )
    if transported_sums != _sha256sums_text(expected_manifest).encode("ascii"):
        raise _fail("Release custody SHA256SUMS does not match the strict manifest.")


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("--expected-version", required=True)


def _add_custody_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sha256sums", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--tag-name", required=True)
    parser.add_argument("--tag-object", required=True)
    parser.add_argument("--peeled-commit", required=True)
    parser.add_argument("--python-identity-file", type=Path, required=True)
    parser.add_argument("--uv-identity-file", type=Path, required=True)
    parser.add_argument("--build-constraints-digest-file", type=Path, required=True)


def main() -> None:
    """Inspect artifacts, verify a rebuild, or create/verify the custody contract."""

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    _add_common_arguments(inspect_parser)
    rebuild_parser = subparsers.add_parser("verify-rebuild")
    _add_common_arguments(rebuild_parser)
    rebuild_parser.add_argument("--rebuilt-wheel", type=Path, required=True)
    for mode in ("create-manifest", "verify-manifest"):
        custody_parser = subparsers.add_parser(mode)
        _add_common_arguments(custody_parser)
        _add_custody_arguments(custody_parser)
    args = parser.parse_args()

    try:
        artifacts = _select_exact_artifact_pair(args.dist_dir, args.expected_version)
        if args.mode == "inspect":
            verify_artifact_pair(artifacts, args.expected_version)
        elif args.mode == "verify-rebuild":
            verify_artifact_pair(artifacts, args.expected_version)
            verify_rebuilt_wheel(artifacts.wheel, args.rebuilt_wheel)
        else:
            operation = (
                create_custody_files if args.mode == "create-manifest" else verify_custody_files
            )
            operation(
                artifacts,
                args.expected_version,
                manifest=args.manifest,
                sha256sums=args.sha256sums,
                source_commit=args.source_commit,
                tag_name=args.tag_name,
                tag_object=args.tag_object,
                peeled_commit=args.peeled_commit,
                python_identity_file=args.python_identity_file,
                uv_identity_file=args.uv_identity_file,
                build_constraints_digest_file=args.build_constraints_digest_file,
            )
    except ArtifactVerificationError as error:
        raise SystemExit(str(error)) from None
    success_messages = {
        "inspect": "Release artifact inspection passed: 1 wheel(s), 1 sdist(s).",
        "verify-rebuild": ("Release artifact rebuild verification passed: 1 wheel(s), 1 sdist(s)."),
        "create-manifest": "Release artifact custody files created: 1 wheel(s), 1 sdist(s).",
        "verify-manifest": (
            "Release artifact custody verification passed: 1 wheel(s), 1 sdist(s)."
        ),
    }
    print(success_messages[args.mode])


if __name__ == "__main__":
    main()
