"""Saved SQL file loading."""

from dataclasses import dataclass
from pathlib import Path

from csvql.exceptions import SQLFileError


@dataclass(frozen=True, slots=True)
class SQLFile:
    """A resolved local SQL file and its text."""

    display_path: str
    path: Path
    sql: str


def load_sql_file(path_value: str, *, base_dir: Path | None = None) -> SQLFile:
    """Resolve and read a non-empty UTF-8 SQL file."""

    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = (base_dir or Path.cwd()) / candidate
    resolved_path = candidate.resolve(strict=False)

    if not resolved_path.exists():
        raise SQLFileError(
            f"SQL file not found: {path_value}",
            suggestion="Check the path or run from the directory that contains the SQL file.",
        )
    if resolved_path.is_dir():
        raise SQLFileError(
            f"SQL file path is a directory: {path_value}",
            suggestion="Choose a .sql file instead of a directory.",
        )

    try:
        sql = resolved_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SQLFileError(
            f"Failed to read SQL file: {path_value}",
            suggestion="Check that the SQL file is readable.",
        ) from exc

    if not sql.strip():
        raise SQLFileError(
            f"SQL file is empty: {path_value}",
            suggestion="Add a SQL statement before running it.",
        )

    return SQLFile(display_path=path_value, path=resolved_path, sql=sql)
