"""Core value objects shared by CSVQL services."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TableSource:
    """A local CSV file exposed to DuckDB under a validated table name."""

    name: str
    path: Path


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Rows and metadata returned from a SQL query."""

    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    elapsed_ms: float

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def as_records(self) -> list[dict[str, object]]:
        """Return rows as JSON-friendly dictionaries keyed by column name."""

        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]
