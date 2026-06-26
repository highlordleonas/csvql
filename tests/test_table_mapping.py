from pathlib import Path

import pytest

from csvql.exceptions import FileMissingError, TableMappingError
from csvql.table_mapping import (
    derive_alias_from_path,
    parse_table_mapping,
    source_from_single_csv,
    validate_table_alias,
)


def test_parse_table_mapping_resolves_file(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")

    source = parse_table_mapping(f"orders={csv_path}")

    assert source.name == "orders"
    assert source.path == csv_path


@pytest.mark.parametrize("alias", ["orders", "_orders", "orders_2026"])
def test_validate_table_alias_accepts_safe_identifiers(alias: str) -> None:
    assert validate_table_alias(alias) == alias


@pytest.mark.parametrize("alias", ["", "123orders", "order-items", "order items"])
def test_validate_table_alias_rejects_unsafe_identifiers(alias: str) -> None:
    with pytest.raises(TableMappingError):
        validate_table_alias(alias)


def test_parse_table_mapping_requires_equals() -> None:
    with pytest.raises(TableMappingError):
        parse_table_mapping("orders")


def test_parse_table_mapping_requires_existing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.csv"

    with pytest.raises(FileMissingError):
        parse_table_mapping(f"orders={missing_path}")


@pytest.mark.parametrize(
    ("filename", "alias"),
    [
        ("orders.csv", "orders"),
        ("orders-2026.csv", "orders_2026"),
        ("2026 orders.csv", "table_2026_orders"),
    ],
)
def test_derive_alias_from_path_normalizes_file_stem(filename: str, alias: str) -> None:
    assert derive_alias_from_path(Path(filename)) == alias


def test_source_from_single_csv_uses_derived_alias(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders-2026.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")

    source = source_from_single_csv(str(csv_path))

    assert source.name == "orders_2026"
    assert source.path == csv_path
