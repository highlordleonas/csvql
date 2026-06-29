"""Full-scan CSV profiling services."""

import duckdb

from csvql.exceptions import CSVInspectionError
from csvql.models import ColumnProfile, ProfileResult
from csvql.source import CSVSource
from csvql.sql_utils import quote_identifier

PROFILE_VIEW_NAME = "__csvql_profile_source"


def profile_csv_source(source: CSVSource) -> ProfileResult:
    """Profile a CSV source with DuckDB-controlled aggregate SQL."""

    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = duckdb.connect(database=":memory:")
        relation = connection.read_csv(
            str(source.path),
            auto_detect=True,
            header=True,
        )
        relation.create_view(PROFILE_VIEW_NAME, replace=True)
        columns = tuple(str(column) for column in relation.columns)
        duckdb_types = tuple(str(duckdb_type) for duckdb_type in relation.types)
        row_count = _fetch_scalar_int(
            connection,
            f"SELECT count(*) FROM {quote_identifier(PROFILE_VIEW_NAME)}",
        )
        column_profiles = tuple(
            _profile_column(
                connection,
                column_name=column_name,
                duckdb_type=duckdb_type,
                row_count=row_count,
            )
            for column_name, duckdb_type in zip(columns, duckdb_types, strict=True)
        )
        duplicate_row_count = _duplicate_row_count(connection, columns)
    except (OSError, duckdb.Error) as exc:
        raise CSVInspectionError(
            f"Failed to profile CSV file: {source.display_path}",
            suggestion="Check that the file is a readable CSV with a header row.",
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    return ProfileResult(
        source=source.to_json_summary(),
        row_count=row_count,
        column_count=len(columns),
        duplicate_row_count=duplicate_row_count,
        columns=column_profiles,
        warnings=(),
    )


def _profile_column(
    connection: duckdb.DuckDBPyConnection,
    *,
    column_name: str,
    duckdb_type: str,
    row_count: int,
) -> ColumnProfile:
    quoted_column = quote_identifier(column_name)
    query = f"""
        SELECT
            count({quoted_column}) AS non_null_count,
            count(*) - count({quoted_column}) AS null_count,
            count(DISTINCT {quoted_column}) AS distinct_count,
            min({quoted_column}) AS min_value,
            max({quoted_column}) AS max_value
        FROM {quote_identifier(PROFILE_VIEW_NAME)}
    """
    row = connection.execute(query).fetchone()
    if row is None:
        raise CSVInspectionError(
            "Failed to profile CSV column.",
            suggestion="Check that the file is a readable CSV with a header row.",
        )

    non_null_count = int(row[0])
    null_count = int(row[1])
    distinct_count = int(row[2])
    null_percentage = 0.0 if row_count == 0 else round((null_count / row_count) * 100, 3)
    return ColumnProfile(
        name=column_name,
        duckdb_type=duckdb_type,
        non_null_count=non_null_count,
        null_count=null_count,
        null_percentage=null_percentage,
        distinct_count=distinct_count,
        min=row[3],
        max=row[4],
    )


def _duplicate_row_count(
    connection: duckdb.DuckDBPyConnection,
    columns: tuple[str, ...],
) -> int:
    if not columns:
        row_count = _fetch_scalar_int(
            connection,
            f"SELECT count(*) FROM {quote_identifier(PROFILE_VIEW_NAME)}",
        )
        return max(row_count - 1, 0)

    quoted_columns = ", ".join(quote_identifier(column) for column in columns)
    query = f"""
        SELECT coalesce(sum(row_count - 1), 0)
        FROM (
            SELECT count(*) AS row_count
            FROM {quote_identifier(PROFILE_VIEW_NAME)}
            GROUP BY {quoted_columns}
            HAVING count(*) > 1
        )
    """
    return _fetch_scalar_int(connection, query)


def _fetch_scalar_int(connection: duckdb.DuckDBPyConnection, query: str) -> int:
    row = connection.execute(query).fetchone()
    if row is None:
        return 0
    return int(row[0] or 0)
