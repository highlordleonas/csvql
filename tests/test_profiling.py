from pathlib import Path

import pytest

from csvql.exceptions import CSVInspectionError
from csvql.profiling import profile_csv_source
from csvql.source import source_from_path


def test_profile_csv_source_returns_full_scan_metrics(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "\n".join(
            [
                "order_id,status,total_amount,ordered_at",
                "ORD-1,paid,12.34,2026-01-02",
                "ORD-2,,99.00,2026-01-03",
                "ORD-2,,99.00,2026-01-03",
                "ORD-2,,99.00,2026-01-03",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    source = source_from_path(str(csv_path))

    result = profile_csv_source(source)
    payload = result.as_dict()

    assert payload["source"]["display_path"] == str(csv_path)
    assert payload["row_count"] == 4
    assert payload["column_count"] == 4
    assert payload["duplicate_row_count"] == 2
    assert payload["warnings"] == []

    columns = {column["name"]: column for column in payload["columns"]}
    assert columns["status"] == {
        "name": "status",
        "duckdb_type": "VARCHAR",
        "non_null_count": 1,
        "null_count": 3,
        "null_percentage": 75.0,
        "distinct_count": 1,
        "min": "paid",
        "max": "paid",
    }
    assert columns["order_id"]["distinct_count"] == 2
    assert columns["order_id"]["min"] == "ORD-1"
    assert columns["order_id"]["max"] == "ORD-2"
    assert columns["total_amount"]["min"] == 12.34
    assert columns["total_amount"]["max"] == 99.0
    assert str(columns["ordered_at"]["min"]) == "2026-01-02"
    assert str(columns["ordered_at"]["max"]) == "2026-01-03"


def test_profile_csv_source_reports_zero_null_percentage_for_empty_data_rows(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("order_id,status\n", encoding="utf-8")
    source = source_from_path(str(csv_path))

    result = profile_csv_source(source)

    assert result.row_count == 0
    assert result.duplicate_row_count == 0
    assert [column.null_percentage for column in result.columns] == [0.0, 0.0]
    assert [column.distinct_count for column in result.columns] == [0, 0]


def test_profile_csv_source_quotes_odd_column_names(tmp_path: Path) -> None:
    csv_path = tmp_path / "odd.csv"
    csv_path.write_text(
        "order id,total-amount,select\nORD-1,12.34,paid\nORD-2,,pending\n",
        encoding="utf-8",
    )
    source = source_from_path(str(csv_path))

    result = profile_csv_source(source)

    columns = {column.name: column for column in result.columns}
    assert columns["order id"].distinct_count == 2
    assert columns["total-amount"].null_count == 1
    assert columns["select"].min == "paid"
    assert columns["select"].max == "pending"


def test_profile_csv_source_quotes_embedded_double_quote_column_names(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "quoted_header.csv"
    csv_path.write_text(
        '"weird""name",status\nalpha,paid\nbeta,pending\n',
        encoding="utf-8",
    )
    source = source_from_path(str(csv_path))

    result = profile_csv_source(source)

    columns = {column.name: column for column in result.columns}
    assert columns['weird"name'].distinct_count == 2
    assert columns['weird"name'].min == "alpha"
    assert columns['weird"name'].max == "beta"


def test_profile_csv_source_wraps_missing_file_after_source_resolution(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    source = source_from_path(str(csv_path))
    csv_path.unlink()

    with pytest.raises(CSVInspectionError) as exc_info:
        profile_csv_source(source)

    assert str(exc_info.value) == f"Failed to profile CSV file: {csv_path}"
    assert exc_info.value.suggestion == ("Check that the file is a readable CSV with a header row.")
