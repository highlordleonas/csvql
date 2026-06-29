"""Core value objects shared by CSVQL services."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


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


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    """Column metadata inferred from DuckDB."""

    name: str
    duckdb_type: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "duckdb_type": self.duckdb_type,
        }


@dataclass(frozen=True, slots=True)
class DialectInfo:
    """Best-effort CSV dialect metadata from a bounded file sample."""

    delimiter: str | None
    quote: str | None
    escape: str | None
    header: bool | None
    encoding: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "delimiter": self.delimiter,
            "quote": self.quote,
            "escape": self.escape,
            "header": self.header,
            "encoding": self.encoding,
        }


@dataclass(frozen=True, slots=True)
class RowCountInfo:
    """Count metadata for an inspected source."""

    mode: Literal["not_counted", "exact"]
    value: int | None
    exact: bool

    @classmethod
    def not_counted(cls) -> "RowCountInfo":
        return cls(mode="not_counted", value=None, exact=False)

    @classmethod
    def exact_count(cls, value: int) -> "RowCountInfo":
        return cls(mode="exact", value=value, exact=True)

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "value": self.value,
            "exact": self.exact,
        }


@dataclass(frozen=True, slots=True)
class InspectResult:
    """Structured result for `csvql inspect`."""

    source: dict[str, object]
    dialect: DialectInfo
    columns: tuple[ColumnInfo, ...]
    row_count: RowCountInfo
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "dialect": self.dialect.as_dict(),
            "columns": [column.as_dict() for column in self.columns],
            "row_count": self.row_count.as_dict(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class SampleResult:
    """Structured result for `csvql sample`."""

    source: dict[str, object]
    limit: int
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    warnings: tuple[str, ...]

    def as_records(self) -> list[dict[str, object]]:
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "limit": self.limit,
            "columns": list(self.columns),
            "rows": self.as_records(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class ColumnProfile:
    """Full-scan profile metrics for one CSV column."""

    name: str
    duckdb_type: str
    non_null_count: int
    null_count: int
    null_percentage: float
    distinct_count: int
    min: object
    max: object

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "duckdb_type": self.duckdb_type,
            "non_null_count": self.non_null_count,
            "null_count": self.null_count,
            "null_percentage": self.null_percentage,
            "distinct_count": self.distinct_count,
            "min": self.min,
            "max": self.max,
        }


@dataclass(frozen=True, slots=True)
class ProfileResult:
    """Structured result for `csvql profile`."""

    source: dict[str, object]
    row_count: int
    column_count: int
    duplicate_row_count: int
    columns: tuple[ColumnProfile, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "duplicate_row_count": self.duplicate_row_count,
            "columns": [column.as_dict() for column in self.columns],
            "warnings": list(self.warnings),
        }
