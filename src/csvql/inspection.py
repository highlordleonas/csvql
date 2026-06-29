"""CSV inspection and sampling services."""

import csv
from pathlib import Path

import duckdb

from csvql.exceptions import CSVInspectionError
from csvql.models import ColumnInfo, DialectInfo, InspectResult, RowCountInfo, SampleResult
from csvql.source import CSVSource

SNIFF_BYTES = 64 * 1024


def inspect_csv_source(source: CSVSource, *, exact: bool = False) -> InspectResult:
    """Inspect a CSV source and return schema, dialect, and row-count status."""

    warnings: list[str] = []
    dialect = DialectInfo(
        delimiter=None,
        quote=None,
        escape=None,
        header=None,
        encoding="utf-8",
    )
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        dialect = _detect_dialect(source.path, warnings=warnings)
        connection = duckdb.connect(database=":memory:")
        relation = connection.read_csv(
            str(source.path),
            auto_detect=True,
            header=True,
        )
        columns = tuple(
            ColumnInfo(name=str(name), duckdb_type=str(duckdb_type))
            for name, duckdb_type in zip(relation.columns, relation.types, strict=True)
        )
        row_count = RowCountInfo.not_counted()
        if exact:
            count_row = relation.aggregate("count(*)").fetchone()
            if count_row is None:
                raise CSVInspectionError(
                    f"Failed to inspect CSV file: {source.display_path}",
                    suggestion="Check that the file is a readable CSV with a header row.",
                )
            row_count = RowCountInfo.exact_count(int(count_row[0]))
    except (OSError, duckdb.Error) as exc:
        raise CSVInspectionError(
            f"Failed to inspect CSV file: {source.display_path}",
            suggestion="Check that the file is a readable CSV with a header row.",
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    return InspectResult(
        source=source.to_json_summary(),
        dialect=dialect,
        columns=columns,
        row_count=row_count,
        warnings=tuple(warnings),
    )


def sample_csv_source(source: CSVSource, *, limit: int = 10) -> SampleResult:
    """Return a bounded row sample from a CSV source."""

    if limit <= 0:
        raise ValueError("Sample limit must be greater than zero.")

    warnings: list[str] = []
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = duckdb.connect(database=":memory:")
        relation = connection.read_csv(
            str(source.path),
            auto_detect=True,
            header=True,
        )
        sample_relation = relation.limit(limit)
        rows = tuple(tuple(row) for row in sample_relation.fetchall())
        columns = tuple(str(column) for column in relation.columns)
    except (OSError, duckdb.Error) as exc:
        raise CSVInspectionError(
            f"Failed to sample CSV file: {source.display_path}",
            suggestion="Check that the file is a readable CSV with a header row.",
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    return SampleResult(
        source=source.to_json_summary(),
        limit=limit,
        columns=columns,
        rows=rows,
        warnings=tuple(warnings),
    )


def _detect_dialect(path: Path, *, warnings: list[str]) -> DialectInfo:
    with path.open("r", encoding="utf-8", errors="replace") as file:
        sample = file.read(SNIFF_BYTES)
    if not sample:
        warnings.append("CSV file is empty; dialect detection used default values.")
        return DialectInfo(
            delimiter=None,
            quote=None,
            escape=None,
            header=None,
            encoding="utf-8",
        )

    try:
        sniffed = csv.Sniffer().sniff(sample)
    except csv.Error:
        warnings.append("Could not detect CSV dialect from the bounded sample.")
        return DialectInfo(
            delimiter=None,
            quote=None,
            escape=None,
            header=None,
            encoding="utf-8",
        )

    try:
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        has_header = None
        warnings.append("Could not determine whether the CSV has a header row.")

    return DialectInfo(
        delimiter=sniffed.delimiter,
        quote=sniffed.quotechar,
        escape=sniffed.escapechar,
        header=has_header,
        encoding="utf-8",
    )
