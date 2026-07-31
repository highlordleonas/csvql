"""Deterministic bounded manifests for explicitly selected local datasets."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from csvql.operation import OperationContext
from csvql.source import ObservedFileFacts

DATASET_INCLUSION_POLICY_VERSION = "1"
PARQUET_EXTENSIONS = frozenset({".parquet", ".parq"})


@dataclass(frozen=True, slots=True)
class DatasetManifestLimits:
    """Product bounds for one explicit local dataset traversal."""

    max_members: int = 100_000
    max_visited_entries: int = 200_000
    max_relative_path_bytes: int = 32 * 1024 * 1024
    max_depth: int = 64

    def __post_init__(self) -> None:
        if (
            self.max_members <= 0
            or self.max_visited_entries <= 0
            or self.max_relative_path_bytes <= 0
            or self.max_depth < 0
        ):
            raise ValueError("Dataset manifest limits must be positive.")


class DatasetManifestFailure(Exception):
    """Deterministic local dataset enumeration failure."""

    def __init__(self, code: str, message: str, *, detail: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


@dataclass(frozen=True, slots=True)
class DatasetMember:
    """One immutable normalized regular-file member."""

    relative_path: str
    observed: ObservedFileFacts
    file_type_evidence: str = "regular_file"
    provider_evidence: str | None = None
    locator_relative_path: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """Frozen membership and observational identity for one explicit dataset."""

    canonical_root: str
    inclusion_policy_version: str
    root_device: int
    root_inode: int
    members: tuple[DatasetMember, ...]
    excluded_regular_file_count: int
    excluded_suffix_summary: tuple[tuple[str, int], ...]
    excluded_symlink_paths: tuple[str, ...]
    total_included_bytes: int
    total_relative_path_bytes: int
    aggregate_observational_digest: str

    @property
    def member_count(self) -> int:
        """Return the immutable number of included members."""

        return len(self.members)


@dataclass(frozen=True, slots=True)
class DatasetManifestChange:
    """Bounded deterministic difference between two dataset observations."""

    added_paths: tuple[str, ...] = ()
    removed_paths: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    root_changed: bool = False
    omitted_path_count: int = 0

    @property
    def has_changes(self) -> bool:
        """Return whether membership, facts, or the root identity changed."""

        return (
            self.root_changed
            or bool(self.added_paths)
            or bool(self.removed_paths)
            or bool(self.changed_paths)
            or self.omitted_path_count > 0
        )


@dataclass(slots=True)
class _TraversalState:
    visited_entries: int = 0
    relative_path_bytes: int = 0
    excluded_regular_file_count: int = 0


def build_dataset_manifest(
    root: Path,
    *,
    operation: OperationContext,
    limits: DatasetManifestLimits | None = None,
) -> DatasetManifest:
    """Enumerate one explicit Parquet dataset without following symlinks."""

    active_limits = limits or DatasetManifestLimits()
    operation.checkpoint()
    canonical_root = Path(os.path.abspath(os.path.normpath(os.fspath(root))))
    try:
        root_stat = canonical_root.lstat()
    except OSError as exc:
        raise DatasetManifestFailure(
            "source.dataset_changed",
            "The dataset root is missing or unreadable.",
            detail="root",
        ) from exc
    if stat.S_ISLNK(root_stat.st_mode):
        raise DatasetManifestFailure(
            "source.dataset_symlink_rejected",
            "A dataset root cannot be a symbolic link.",
            detail="root",
        )
    if not stat.S_ISDIR(root_stat.st_mode):
        raise DatasetManifestFailure(
            "source.dataset_changed",
            "The dataset root is not a directory.",
            detail="root",
        )

    state = _TraversalState()
    members: dict[str, DatasetMember] = {}
    symlink_paths: set[str] = set()
    excluded_suffixes: Counter[str] = Counter()

    def walk(
        directory: Path,
        relative_parent: PurePosixPath,
        locator_parent: PurePosixPath,
        depth: int,
    ) -> None:
        operation.checkpoint()
        try:
            with os.scandir(directory) as entries:
                scanned_entries = []
                for entry in entries:
                    operation.checkpoint()
                    state.visited_entries += 1
                    if state.visited_entries > active_limits.max_visited_entries:
                        raise _limit_failure("visited_entries")
                    scanned_entries.append(entry)
        except DatasetManifestFailure:
            raise
        except OSError as exc:
            raise DatasetManifestFailure(
                "source.dataset_changed",
                "The dataset changed or became unreadable during enumeration.",
                detail="entry",
            ) from exc

        for entry in sorted(scanned_entries, key=lambda item: _normalize_name(item.name)):
            operation.checkpoint()
            relative_path = _normalized_relative_path(relative_parent, entry.name)
            locator_relative_path = (locator_parent / entry.name).as_posix()
            try:
                # DirEntry may retain enumeration-time metadata on Windows.
                # Re-stat the path so a removed or replaced member fails closed.
                entry_stat = os.stat(entry.path, follow_symlinks=False)
            except OSError as exc:
                raise DatasetManifestFailure(
                    "source.dataset_changed",
                    "The dataset changed or became unreadable during enumeration.",
                    detail=relative_path,
                ) from exc
            if stat.S_ISLNK(entry_stat.st_mode):
                symlink_paths.add(relative_path)
                continue
            if stat.S_ISDIR(entry_stat.st_mode):
                child_depth = depth + 1
                if child_depth > active_limits.max_depth:
                    raise _limit_failure("depth")
                walk(
                    Path(entry.path),
                    PurePosixPath(relative_path),
                    PurePosixPath(locator_relative_path),
                    child_depth,
                )
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                continue

            suffix = PurePosixPath(relative_path).suffix.casefold()
            if suffix not in PARQUET_EXTENSIONS:
                state.excluded_regular_file_count += 1
                excluded_suffixes[suffix or "<none>"] += 1
                continue
            if relative_path in members:
                raise DatasetManifestFailure(
                    "source.dataset_changed",
                    "Two dataset entries normalize to the same relative path.",
                    detail=relative_path,
                )
            relative_path_size = len(relative_path.encode("utf-8"))
            if (
                state.relative_path_bytes + relative_path_size
                > active_limits.max_relative_path_bytes
            ):
                raise _limit_failure("relative_path_bytes")
            if len(members) + 1 > active_limits.max_members:
                raise _limit_failure("members")
            state.relative_path_bytes += relative_path_size
            members[relative_path] = DatasetMember(
                relative_path=relative_path,
                observed=ObservedFileFacts(
                    size_bytes=entry_stat.st_size,
                    modified_time_ns=entry_stat.st_mtime_ns,
                ),
                locator_relative_path=locator_relative_path,
            )

    walk(canonical_root, PurePosixPath(), PurePosixPath(), 0)
    operation.checkpoint()
    duplicate_symlink_paths = set(members) & symlink_paths
    if duplicate_symlink_paths:
        raise DatasetManifestFailure(
            "source.dataset_symlink_rejected",
            "A symbolic link collides with an included dataset member.",
            detail=min(duplicate_symlink_paths),
        )
    ordered_members = tuple(members[path] for path in sorted(members))
    if not ordered_members:
        raise DatasetManifestFailure(
            "source.parquet_dataset_empty",
            "The selected directory contains no Parquet members.",
            detail="members",
        )
    digest = _manifest_digest(
        root_device=root_stat.st_dev,
        root_inode=root_stat.st_ino,
        members=ordered_members,
    )
    return DatasetManifest(
        canonical_root=str(canonical_root),
        inclusion_policy_version=DATASET_INCLUSION_POLICY_VERSION,
        root_device=root_stat.st_dev,
        root_inode=root_stat.st_ino,
        members=ordered_members,
        excluded_regular_file_count=state.excluded_regular_file_count,
        excluded_suffix_summary=tuple(sorted(excluded_suffixes.items())),
        excluded_symlink_paths=tuple(sorted(symlink_paths)),
        total_included_bytes=sum(member.observed.size_bytes for member in ordered_members),
        total_relative_path_bytes=state.relative_path_bytes,
        aggregate_observational_digest=digest,
    )


def summarize_manifest_change(
    recorded: DatasetManifest,
    current: DatasetManifest,
    *,
    max_paths: int = 20,
) -> DatasetManifestChange:
    """Return a bounded path-level comparison without replacing recorded state."""

    if max_paths < 0:
        raise ValueError("Manifest change summaries require a non-negative path bound.")
    recorded_members = {member.relative_path: member for member in recorded.members}
    current_members = {member.relative_path: member for member in current.members}
    added = sorted(set(current_members) - set(recorded_members))
    removed = sorted(set(recorded_members) - set(current_members))
    changed = sorted(
        path
        for path in set(recorded_members) & set(current_members)
        if recorded_members[path] != current_members[path]
    )
    remaining = max_paths
    bounded_added = tuple(added[:remaining])
    remaining -= len(bounded_added)
    bounded_removed = tuple(removed[:remaining])
    remaining -= len(bounded_removed)
    bounded_changed = tuple(changed[:remaining])
    included_count = len(bounded_added) + len(bounded_removed) + len(bounded_changed)
    total_count = len(added) + len(removed) + len(changed)
    return DatasetManifestChange(
        added_paths=bounded_added,
        removed_paths=bounded_removed,
        changed_paths=bounded_changed,
        root_changed=(
            recorded.canonical_root != current.canonical_root
            or recorded.root_device != current.root_device
            or recorded.root_inode != current.root_inode
        ),
        omitted_path_count=total_count - included_count,
    )


def _normalize_name(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def _normalized_relative_path(parent: PurePosixPath, name: str) -> str:
    normalized_name = _normalize_name(name)
    relative_path = parent / normalized_name
    normalized = relative_path.as_posix()
    if not normalized or normalized.startswith("/") or ".." in relative_path.parts:
        raise DatasetManifestFailure(
            "source.dataset_changed",
            "A dataset member has an invalid normalized relative path.",
            detail="relative_path",
        )
    return normalized


def _limit_failure(limit_name: str) -> DatasetManifestFailure:
    return DatasetManifestFailure(
        "source.dataset_manifest_limit",
        "The selected dataset exceeds a deterministic manifest bound.",
        detail=limit_name,
    )


def _manifest_digest(
    *,
    root_device: int,
    root_inode: int,
    members: tuple[DatasetMember, ...],
) -> str:
    material = {
        "inclusion_policy_version": DATASET_INCLUSION_POLICY_VERSION,
        "root_device": root_device,
        "root_inode": root_inode,
        "members": [
            {
                "relative_path": member.relative_path,
                "size_bytes": member.observed.size_bytes,
                "modified_time_ns": member.observed.modified_time_ns,
                "file_type_evidence": member.file_type_evidence,
                "provider_evidence": member.provider_evidence,
            }
            for member in members
        ],
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
