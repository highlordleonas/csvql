from pathlib import Path

import pytest

from csvql.exceptions import CSVInspectionError
from csvql.inspection import SNIFF_BYTES, _detect_dialect, inspect_csv_source, sample_csv_source
from csvql.source import source_from_path


def test_inspect_csv_source_returns_columns_without_counting_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,total_amount\nORD-1,12.34\nORD-2,99.00\n",
        encoding="utf-8",
    )
    source = source_from_path(str(csv_path))

    result = inspect_csv_source(source)

    payload = result.as_dict()
    assert payload["source"]["display_path"] == str(csv_path)
    assert payload["row_count"] == {
        "mode": "not_counted",
        "value": None,
        "exact": False,
    }
    assert payload["columns"] == [
        {"name": "order_id", "duckdb_type": "VARCHAR"},
        {"name": "total_amount", "duckdb_type": "DOUBLE"},
    ]
    assert payload["warnings"] == []


def test_inspect_csv_source_exact_counts_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,total_amount\nORD-1,12.34\nORD-2,99.00\n",
        encoding="utf-8",
    )
    source = source_from_path(str(csv_path))

    result = inspect_csv_source(source, exact=True)

    assert result.row_count.as_dict() == {
        "mode": "exact",
        "value": 2,
        "exact": True,
    }


def test_inspect_csv_source_wraps_missing_file_after_source_resolution(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,total_amount\nORD-1,12.34\n",
        encoding="utf-8",
    )
    source = source_from_path(str(csv_path))
    csv_path.unlink()

    with pytest.raises(CSVInspectionError) as exc_info:
        inspect_csv_source(source)

    assert str(exc_info.value) == f"Failed to inspect CSV file: {csv_path}"
    assert exc_info.value.suggestion == ("Check that the file is a readable CSV with a header row.")


def test_inspect_csv_source_reports_detected_dialect(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.tsv"
    csv_path.write_text(
        "order_id\tstatus\nORD-1\tpaid\n",
        encoding="utf-8",
    )
    source = source_from_path(str(csv_path))

    result = inspect_csv_source(source)

    assert result.dialect.delimiter == "\t"
    assert result.dialect.header is True
    assert result.dialect.encoding == "utf-8"


def test_sample_csv_source_returns_bounded_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\nORD-3,paid\n",
        encoding="utf-8",
    )
    source = source_from_path(str(csv_path))

    result = sample_csv_source(source, limit=2)

    assert result.as_dict()["limit"] == 2
    assert result.columns == ("order_id", "status")
    assert result.rows == (("ORD-1", "paid"), ("ORD-2", "pending"))
    assert result.warnings == ()


def test_sample_csv_source_rejects_non_positive_limit(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    source = source_from_path(str(csv_path))

    try:
        sample_csv_source(source, limit=0)
    except ValueError as exc:
        assert str(exc) == "Sample limit must be greater than zero."
    else:
        raise AssertionError("sample_csv_source accepted a non-positive limit")


def test_detect_dialect_reads_only_sniff_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_path = tmp_path / "large.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")

    read_sizes: list[int] = []

    class FakeFile:
        def __enter__(self) -> "FakeFile":
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

        def read(self, size: int = -1) -> str:
            read_sizes.append(size)
            return "order_id,total_amount\nORD-1,12.34\n"

    def fake_open(self: Path, *args: object, **kwargs: object) -> FakeFile:
        return FakeFile()

    monkeypatch.setattr(Path, "open", fake_open, raising=True)

    dialect = _detect_dialect(csv_path, warnings=[])

    assert read_sizes == [SNIFF_BYTES]
    assert dialect.delimiter == ","
    assert dialect.header is True
