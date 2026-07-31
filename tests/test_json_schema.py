from __future__ import annotations

import importlib

import pytest


def test_schema_hint_normalizes_types_and_sorts_columns() -> None:
    """Insertion order and type aliases must not affect schema identity."""

    schema_module = importlib.import_module("csvql.json_schema")

    hint = schema_module.parse_json_schema_hint(
        {
            "z_value": " int ",
            "A_value": "text",
        }
    )

    assert hint.columns == (
        ("A_value", "VARCHAR"),
        ("z_value", "INTEGER"),
    )
    assert hint.as_duckdb_columns() == {
        "A_value": "VARCHAR",
        "z_value": "INTEGER",
    }
    assert hint.structure_json == '{"A_value":"VARCHAR","z_value":"INTEGER"}'


@pytest.mark.parametrize(
    ("declared_type", "canonical_type"),
    (
        ("BOOLEAN", "BOOLEAN"),
        ("BOOL", "BOOLEAN"),
        ("TINYINT", "TINYINT"),
        ("SMALLINT", "SMALLINT"),
        ("INTEGER", "INTEGER"),
        ("BIGINT", "BIGINT"),
        ("HUGEINT", "HUGEINT"),
        ("UTINYINT", "UTINYINT"),
        ("USMALLINT", "USMALLINT"),
        ("UINTEGER", "UINTEGER"),
        ("UBIGINT", "UBIGINT"),
        ("UHUGEINT", "UHUGEINT"),
        ("REAL", "REAL"),
        ("FLOAT", "REAL"),
        ("DOUBLE", "DOUBLE"),
        ("VARCHAR", "VARCHAR"),
        ("DATE", "DATE"),
        ("TIME", "TIME"),
        ("TIMESTAMP", "TIMESTAMP"),
        ("TIMESTAMPTZ", "TIMESTAMPTZ"),
        ("UUID", "UUID"),
        ("JSON", "JSON"),
        ("decimal ( 38 , 10 )", "DECIMAL(38,10)"),
    ),
)
def test_schema_hint_accepts_only_the_v12_scalar_grammar(
    declared_type: str,
    canonical_type: str,
) -> None:
    """Removing or misnormalizing an approved scalar must break this contract."""

    schema_module = importlib.import_module("csvql.json_schema")

    hint = schema_module.parse_json_schema_hint({"value": declared_type})

    assert hint.columns == (("value", canonical_type),)


@pytest.mark.parametrize(
    "declared_type",
    (
        "",
        "DECIMAL",
        "DECIMAL(0,0)",
        "DECIMAL(39,0)",
        "DECIMAL(10,11)",
        "LIST(INTEGER)",
        "STRUCT(id INTEGER)",
        "INTEGER; DROP TABLE records",
        "INTEGER -- comment",
        "made_up_type",
    ),
)
def test_schema_hint_rejects_types_outside_the_v12_grammar(
    declared_type: str,
) -> None:
    """Unvalidated type expressions must never reach DuckDB."""

    schema_module = importlib.import_module("csvql.json_schema")

    with pytest.raises(schema_module.JSONSchemaHintError) as captured:
        schema_module.parse_json_schema_hint({"value": declared_type})

    assert captured.value.reason == "type_invalid"


@pytest.mark.parametrize(
    "schema",
    (
        None,
        {},
        {"": "INTEGER"},
        {"has space": "INTEGER"},
        {"1leading": "INTEGER"},
        {"value": 1},
        {1: "INTEGER"},
        {"Value": "INTEGER", "value": "BIGINT"},
    ),
)
def test_schema_hint_rejects_invalid_or_ambiguous_mappings(schema: object) -> None:
    """Invalid boundaries and case collisions must not create unstable columns."""

    schema_module = importlib.import_module("csvql.json_schema")

    with pytest.raises(schema_module.JSONSchemaHintError):
        schema_module.parse_json_schema_hint(schema)
