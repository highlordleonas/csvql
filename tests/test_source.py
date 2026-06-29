from pathlib import Path

import pytest

from csvql.exceptions import FileMissingError
from csvql.source import source_from_path


def test_source_from_path_records_file_metadata(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")

    source = source_from_path(str(csv_path))

    assert source.path == csv_path
    assert source.display_path == str(csv_path)
    assert source.fingerprint.version == 1
    assert source.fingerprint.size_bytes == csv_path.stat().st_size
    assert source.fingerprint.modified_at
    assert source.to_json_summary()["fingerprint"]["version"] == 1


def test_source_from_path_resolves_relative_paths(tmp_path: Path) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text("customer_id,email\nCUST-1,a@example.com\n", encoding="utf-8")

    source = source_from_path("customers.csv", base_dir=tmp_path)

    assert source.path == csv_path
    assert source.display_path == "customers.csv"


def test_source_from_path_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileMissingError):
        source_from_path("missing.csv", base_dir=tmp_path)
