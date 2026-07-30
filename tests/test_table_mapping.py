from pathlib import Path

import pytest

from csvql.exceptions import FileMissingError, TableMappingError
from csvql.models import SourceDefinition
from csvql.project_config import ProjectTable
from csvql.source import (
    source_options_as_python,
    source_spec_from_catalog_table,
    source_spec_from_tui_source,
)
from csvql.table_mapping import (
    build_source_definitions,
    derive_alias_from_locator,
    derive_alias_from_path,
    parse_source_option_value,
    parse_table_mapping,
    source_from_single_csv,
    validate_table_alias,
)
from csvql.tui_state import TUISource


def test_parse_table_mapping_resolves_file(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")

    source = parse_table_mapping(f"orders={csv_path}")

    assert source.name == "orders"
    assert source.path == csv_path


@pytest.mark.parametrize("alias", ["orders", "_orders", "orders_2026"])
def test_validate_table_alias_accepts_safe_identifiers(alias: str) -> None:
    assert validate_table_alias(alias) == alias


def test_validate_table_alias_rejects_reserved_prefix() -> None:
    with pytest.raises(TableMappingError, match="reserved prefix"):
        validate_table_alias("__localql_orders")


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
        ("__localql_orders.csv", "localql_orders"),
        ("___localql_orders___.csv", "localql_orders"),
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


def test_source_from_single_csv_normalizes_reserved_prefix_from_filename(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "__localql_orders.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")

    source = source_from_single_csv(str(csv_path))

    assert source.name == "localql_orders"
    assert source.path == csv_path


def test_source_definition_freezes_provider_neutral_intent(tmp_path: Path) -> None:
    definition = SourceDefinition(
        "events",
        "data/events.json",
        source_type="json",
        options={"schema": {"id": "BIGINT"}, "sample_size": 50},
        base_dir=tmp_path,
    )

    assert definition.alias == "events"
    assert definition.locator == "data/events.json"
    assert definition.source_type == "json"
    assert definition.base_dir == tmp_path.resolve()
    assert source_options_as_python(definition.options) == {
        "sample_size": 50,
        "schema": {"id": "BIGINT"},
    }


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("true", True),
        ("false", False),
        ("null", None),
        ("42", 42),
        ("-1.5e2", -150.0),
        ('{"id":"BIGINT"}', {"id": "BIGINT"}),
        ("[1,2]", [1, 2]),
        ("Orders", "Orders"),
    ],
)
def test_parse_source_option_value_uses_one_deterministic_value_grammar(
    raw_value: str,
    expected: object,
) -> None:
    assert parse_source_option_value(raw_value) == expected


def test_parse_source_option_value_rejects_invalid_structured_json() -> None:
    with pytest.raises(TableMappingError, match="Invalid JSON"):
        parse_source_option_value('{"id":}')


def test_build_source_definitions_associates_types_and_options_by_alias(
    tmp_path: Path,
) -> None:
    definitions = build_source_definitions(
        ("orders=data/orders.parquet", "events=data/events.json"),
        ("orders=parquet",),
        (
            "orders.partitioning=hive",
            "orders.union_by_name=true",
            'events.schema={"id":"BIGINT"}',
        ),
        base_dir=tmp_path,
    )

    assert [(item.alias, item.locator, item.source_type) for item in definitions] == [
        ("orders", "data/orders.parquet", "parquet"),
        ("events", "data/events.json", None),
    ]
    assert source_options_as_python(definitions[0].options) == {
        "partitioning": "hive",
        "union_by_name": True,
    }
    assert source_options_as_python(definitions[1].options) == {"schema": {"id": "BIGINT"}}


def test_build_source_definitions_rejects_undeclared_and_duplicate_references() -> None:
    with pytest.raises(TableMappingError, match="undeclared source"):
        build_source_definitions(("orders=orders.csv",), ("events=json",))

    with pytest.raises(TableMappingError, match="Duplicate source option"):
        build_source_definitions(
            ("orders=orders.csv",),
            source_option_mappings=("orders.header=true", "orders.header=false"),
        )


def test_derive_alias_from_locator_uses_directory_name_instead_of_suffix(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "warehouse.v1"
    directory.mkdir()

    assert derive_alias_from_locator(str(directory)) == "warehouse_v1"


def test_catalog_entry_conversion_preserves_relative_locator_and_project_anchor(
    tmp_path: Path,
) -> None:
    table = ProjectTable(name="Orders", path="data/orders.csv")

    spec = source_spec_from_catalog_table(table, project_root=tmp_path)

    assert spec.alias == "Orders"
    assert spec.kind == "csv"
    assert spec.locator == "data/orders.csv"
    assert spec.anchor == tmp_path


def test_tui_source_facade_conversion_preserves_alias_and_path_anchor(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    source = TUISource(name="Orders", path=csv_path, origin="argument")

    spec = source_spec_from_tui_source(source)

    assert spec.alias == "Orders"
    assert spec.kind == "csv"
    assert spec.locator == str(csv_path)
    assert spec.anchor == tmp_path
