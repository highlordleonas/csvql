from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import pytest

import csvql.source_manifest as source_manifest
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.source_manifest import (
    DatasetManifestFailure,
    DatasetManifestLimits,
    build_dataset_manifest,
    summarize_manifest_change,
)


def _operation() -> OperationContext:
    return OperationContext(OperationToken())


def test_manifest_freezes_lexically_ordered_members_and_exclusion_evidence(
    tmp_path: Path,
) -> None:
    """Filesystem iteration order or excluded entries must not alter membership."""

    root = tmp_path / "warehouse"
    nested = root / "region=west"
    nested.mkdir(parents=True)
    (root / "z.parq").write_bytes(b"z")
    (nested / "a.PARQUET").write_bytes(b"alpha")
    (root / "notes.txt").write_text("ignored", encoding="utf-8")
    try:
        (root / "linked.parquet").symlink_to(root / "z.parq")
        (root / "linked-dir").symlink_to(nested, target_is_directory=True)
    except OSError:
        pytest.skip("This platform does not permit symlink creation.")

    manifest = build_dataset_manifest(root, operation=_operation())

    assert tuple(member.relative_path for member in manifest.members) == (
        "region=west/a.PARQUET",
        "z.parq",
    )
    assert manifest.member_count == 2
    assert manifest.total_included_bytes == 6
    assert manifest.total_relative_path_bytes == len(b"region=west/a.PARQUET") + len(b"z.parq")
    assert manifest.excluded_regular_file_count == 1
    assert manifest.excluded_suffix_summary == ((".txt", 1),)
    assert manifest.excluded_symlink_paths == ("linked-dir", "linked.parquet")
    assert len(manifest.aggregate_observational_digest) == 64


def test_manifest_rejects_a_symlink_root_without_following_it(tmp_path: Path) -> None:
    """A symlink root could redirect the dataset after explicit selection."""

    root = tmp_path / "warehouse"
    root.mkdir()
    (root / "part.parquet").write_bytes(b"part")
    link = tmp_path / "warehouse-link"
    try:
        link.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("This platform does not permit symlink creation.")

    with pytest.raises(DatasetManifestFailure) as error:
        build_dataset_manifest(link, operation=_operation())

    assert error.value.code == "source.dataset_symlink_rejected"
    assert error.value.detail == "root"


def test_manifest_retains_filesystem_spelling_separately_from_normalized_identity(
    tmp_path: Path,
) -> None:
    """Unicode normalization must not make the recorded member impossible to reopen."""

    root = tmp_path / "warehouse"
    root.mkdir()
    requested_name = "cafe\u0301.parquet"
    (root / requested_name).write_bytes(b"part")
    with os.scandir(root) as entries:
        filesystem_name = next(entries).name

    manifest = build_dataset_manifest(root, operation=_operation())

    assert manifest.members[0].relative_path == unicodedata.normalize("NFC", filesystem_name)
    assert manifest.members[0].locator_relative_path == filesystem_name


def test_manifest_rejects_a_dataset_without_parquet_members(tmp_path: Path) -> None:
    """An explicitly typed directory must not bind an empty hidden glob."""

    root = tmp_path / "warehouse"
    root.mkdir()
    (root / "README.txt").write_text("nothing to query", encoding="utf-8")

    with pytest.raises(DatasetManifestFailure) as error:
        build_dataset_manifest(root, operation=_operation())

    assert error.value.code == "source.parquet_dataset_empty"


@pytest.mark.parametrize(
    ("limits", "layout", "limit_name"),
    (
        (
            DatasetManifestLimits(max_members=1),
            ("a.parquet", "b.parquet"),
            "members",
        ),
        (
            DatasetManifestLimits(max_visited_entries=1),
            ("a.parquet", "b.parquet"),
            "visited_entries",
        ),
        (
            DatasetManifestLimits(max_relative_path_bytes=1),
            ("part.parquet",),
            "relative_path_bytes",
        ),
    ),
)
def test_manifest_rejects_each_bounded_collection_before_returning_partial_state(
    tmp_path: Path,
    limits: DatasetManifestLimits,
    layout: tuple[str, ...],
    limit_name: str,
) -> None:
    """Exceeding a product bound must fail instead of truncating membership."""

    root = tmp_path / "warehouse"
    root.mkdir()
    for relative_path in layout:
        (root / relative_path).write_bytes(b"x")

    with pytest.raises(DatasetManifestFailure) as error:
        build_dataset_manifest(root, operation=_operation(), limits=limits)

    assert error.value.code == "source.dataset_manifest_limit"
    assert error.value.detail == limit_name


def test_manifest_rejects_depth_beyond_the_explicit_bound(tmp_path: Path) -> None:
    """A deep tree must not escape the bounded recursive traversal contract."""

    root = tmp_path / "warehouse"
    nested = root / "one" / "two"
    nested.mkdir(parents=True)
    (nested / "part.parquet").write_bytes(b"x")

    with pytest.raises(DatasetManifestFailure) as error:
        build_dataset_manifest(
            root,
            operation=_operation(),
            limits=DatasetManifestLimits(max_depth=1),
        )

    assert error.value.code == "source.dataset_manifest_limit"
    assert error.value.detail == "depth"


def test_manifest_change_summary_is_deterministic_and_bounded(tmp_path: Path) -> None:
    """Revalidation must report stable member deltas without leaking full datasets."""

    root = tmp_path / "warehouse"
    root.mkdir()
    first = root / "a.parquet"
    removed = root / "b.parquet"
    first.write_bytes(b"one")
    removed.write_bytes(b"two")
    before = build_dataset_manifest(root, operation=_operation())

    first.write_bytes(b"changed")
    removed.unlink()
    (root / "c.parquet").write_bytes(b"three")
    (root / "d.parquet").write_bytes(b"four")
    after = build_dataset_manifest(root, operation=_operation())

    summary = summarize_manifest_change(before, after, max_paths=2)

    assert summary.added_paths == ("c.parquet", "d.parquet")
    assert summary.removed_paths == ()
    assert summary.changed_paths == ()
    assert summary.omitted_path_count == 2
    assert summary.has_changes is True


def test_manifest_change_summary_treats_path_casing_as_membership(
    tmp_path: Path,
) -> None:
    """Case changes must not collapse on case-sensitive filesystems."""

    root = tmp_path / "warehouse"
    root.mkdir()
    member = root / "part.parquet"
    member.write_bytes(b"part")
    before = build_dataset_manifest(root, operation=_operation())
    renamed = root / "PART.parquet"
    member.rename(renamed)
    if not renamed.exists() or member.exists():
        pytest.skip("This filesystem does not expose case-only renames distinctly.")
    after = build_dataset_manifest(root, operation=_operation())

    summary = summarize_manifest_change(before, after)

    assert summary.added_paths == ("PART.parquet",)
    assert summary.removed_paths == ("part.parquet",)
    assert summary.changed_paths == ()


def test_manifest_rejects_an_entry_removed_during_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A racing entry must fail the snapshot instead of producing partial membership."""

    root = tmp_path / "warehouse"
    root.mkdir()
    victim = root / "part.parquet"
    victim.write_bytes(b"part")
    real_scandir = source_manifest.os.scandir

    class MutatingScandir:
        def __init__(self, path: Path) -> None:
            self._path = Path(path)
            self._entries = real_scandir(path)

        def __enter__(self):
            return self._entries

        def __exit__(self, *exc_info: object) -> None:
            self._entries.close()
            if self._path == root:
                victim.unlink()

    monkeypatch.setattr(
        source_manifest.os,
        "scandir",
        lambda path: MutatingScandir(Path(path)),
    )

    with pytest.raises(DatasetManifestFailure) as error:
        build_dataset_manifest(root, operation=_operation())

    assert error.value.code == "source.dataset_changed"
    assert error.value.detail == "part.parquet"


def test_observational_manifest_documents_same_size_same_mtime_limitation(
    tmp_path: Path,
) -> None:
    """Observational evidence must not pretend to detect byte-preserving mutations."""

    root = tmp_path / "warehouse"
    root.mkdir()
    member = root / "part.parquet"
    member.write_bytes(b"before")
    before = build_dataset_manifest(root, operation=_operation())
    original_stat = member.stat()

    member.write_bytes(b"after!")
    os.utime(
        member,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    after = build_dataset_manifest(root, operation=_operation())

    summary = summarize_manifest_change(before, after)

    assert summary.has_changes is False
    assert before.aggregate_observational_digest == after.aggregate_observational_digest


def test_manifest_checks_cancellation_before_filesystem_work(tmp_path: Path) -> None:
    """Cancelled preparation must not continue enumerating dataset entries."""

    root = tmp_path / "warehouse"
    root.mkdir()
    (root / "part.parquet").write_bytes(b"x")
    token = OperationToken()
    token.cancel()

    with pytest.raises(OperationCancelled):
        build_dataset_manifest(
            root,
            operation=OperationContext(token),
        )


def test_manifest_checks_cancellation_during_entry_traversal(tmp_path: Path) -> None:
    """Large explicit datasets must remain cancellable between visited entries."""

    class CancelAfterCheckpoints(OperationToken):
        def __init__(self, allowed: int) -> None:
            super().__init__()
            self._allowed = allowed
            self._checks = 0

        def raise_if_cancelled(self) -> None:
            self._checks += 1
            if self._checks > self._allowed:
                self.cancel()
            super().raise_if_cancelled()

    root = tmp_path / "warehouse"
    root.mkdir()
    for index in range(10):
        (root / f"{index}.parquet").write_bytes(b"x")

    with pytest.raises(OperationCancelled):
        build_dataset_manifest(
            root,
            operation=OperationContext(CancelAfterCheckpoints(4)),
        )
