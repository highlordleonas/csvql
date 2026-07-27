from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest

import csvql.csv_adapter as csv_adapter_module
import csvql.engine as engine_module
from csvql.csv_adapter import SNIFF_BYTES
from csvql.exceptions import CSVInspectionError
from csvql.inspection import inspect_csv_source, sample_csv_source
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


def test_sample_csv_source_wraps_missing_file_after_source_resolution(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    source = source_from_path(str(csv_path))
    csv_path.unlink()

    with pytest.raises(CSVInspectionError) as exc_info:
        sample_csv_source(source, limit=1)

    assert str(exc_info.value) == f"Failed to sample CSV file: {csv_path}"
    assert exc_info.value.suggestion == ("Check that the file is a readable CSV with a header row.")


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (lambda source: inspect_csv_source(source), "Failed to inspect CSV file"),
        (lambda source: sample_csv_source(source), "Failed to sample CSV file"),
    ],
)
def test_inspection_facades_translate_raw_duckdb_connect_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: Callable[[object], object],
    message: str,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    source = source_from_path(str(csv_path))

    def fail_connect(*args: object, **kwargs: object) -> None:
        raise duckdb.IOException("injected connection failure")

    monkeypatch.setattr(engine_module.duckdb, "connect", fail_connect)

    with pytest.raises(CSVInspectionError) as exc_info:
        operation(source)

    assert str(exc_info.value) == f"{message}: {csv_path}"
    assert exc_info.value.suggestion == ("Check that the file is a readable CSV with a header row.")


def test_sample_facade_translates_success_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    source = source_from_path(str(csv_path))
    original_close = csv_adapter_module._CSVRelationalBinding.close

    def fail_after_close(binding: object, context: object) -> None:
        original_close(binding, context)
        raise RuntimeError("injected cleanup failure")

    monkeypatch.setattr(csv_adapter_module._CSVRelationalBinding, "close", fail_after_close)

    with pytest.raises(CSVInspectionError) as exc_info:
        sample_csv_source(source)

    assert str(exc_info.value) == f"Failed to sample CSV file: {csv_path}"
    assert exc_info.value.suggestion == ("Check that the file is a readable CSV with a header row.")


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


def test_csv_adapter_detects_dialect_from_only_sniff_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_path = tmp_path / "large.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    original_open = Path.open
    read_sizes: list[int] = []

    class RecordingFile:
        def __init__(self, path: Path, *args: object, **kwargs: object) -> None:
            self._file = original_open(path, *args, **kwargs)

        def __enter__(self) -> "RecordingFile":
            return self

        def __exit__(self, *exc_info: object) -> None:
            self._file.close()

        def fileno(self) -> int:
            return self._file.fileno()

        def read(self, size: int = -1) -> bytes:
            read_sizes.append(size)
            return self._file.read(size)

    def recording_open(path: Path, *args: object, **kwargs: object) -> object:
        if path == csv_path:
            return RecordingFile(path, *args, **kwargs)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", recording_open)

    result = inspect_csv_source(source_from_path(str(csv_path)))

    assert read_sizes
    assert set(read_sizes) == {SNIFF_BYTES}
    assert result.dialect.delimiter == ","
    assert result.dialect.header is True
