"""Local CSV source resolution and metadata."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from csvql.exceptions import FileMissingError


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    """Versioned file metadata used to identify a local CSV source."""

    version: int
    size_bytes: int
    modified_at: str

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-friendly fingerprint payload."""

        return {
            "version": self.version,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
        }


@dataclass(frozen=True, slots=True)
class CSVSource:
    """Resolved local CSV file plus display and fingerprint metadata."""

    path: Path
    display_path: str
    fingerprint: SourceFingerprint

    def to_json_summary(self) -> dict[str, object]:
        """Return the stable JSON source summary used by inspect and sample."""

        return {
            "display_path": self.display_path,
            "resolved_path": str(self.path),
            "size_bytes": self.fingerprint.size_bytes,
            "modified_at": self.fingerprint.modified_at,
            "fingerprint": self.fingerprint.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class RegisteredTable:
    """A validated table alias bound to a resolved CSV source."""

    name: str
    source: CSVSource


def resolve_csv_path(path_value: str, *, base_dir: Path | None = None) -> Path:
    """Resolve and validate a local CSV path."""

    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = (base_dir or Path.cwd()) / candidate
    resolved_path = candidate.resolve(strict=False)
    if not resolved_path.is_file():
        raise FileMissingError(
            f"CSV file not found: {path_value}",
            suggestion="Check the path or run from the directory that contains the CSV file.",
        )
    return resolved_path


def source_from_path(path_value: str, *, base_dir: Path | None = None) -> CSVSource:
    """Build a resolved CSV source from a CLI path value."""

    resolved_path = resolve_csv_path(path_value, base_dir=base_dir)
    stat = resolved_path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
    fingerprint = SourceFingerprint(
        version=1,
        size_bytes=stat.st_size,
        modified_at=modified_at,
    )
    return CSVSource(
        path=resolved_path,
        display_path=path_value,
        fingerprint=fingerprint,
    )
