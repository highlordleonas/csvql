from __future__ import annotations

import gzip
import json
from pathlib import Path

import duckdb
import pytest

from csvql.engine import CSVQLEngine
from csvql.exceptions import QueryExecutionError, SourceError
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.source import (
    FrozenJSONObject,
    IdentityRequirement,
    IdentityStrength,
    IdentityValidationStatus,
    PreparedSources,
    ResolvedSource,
    SourcePreparationFailure,
    build_source_request,
)
from csvql.source_coordinator import PreparationContext
from csvql.source_runtime import (
    build_default_source_components,
    default_activation_context,
    raise_preparation_failure,
    resolve_source_request,
)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _prepare_source(
    source: Path,
    *,
    options: tuple[tuple[str, object], ...] = (),
    explicit_type: str | None = None,
) -> tuple[object, CSVQLEngine, PreparedSources | SourcePreparationFailure]:
    request = build_source_request(
        alias="orders",
        locator=source.name,
        anchor=source.parent,
        explicit_type=explicit_type,
        options=options,
    )
    operation = OperationContext(OperationToken())
    components = build_default_source_components()
    engine = CSVQLEngine(operation=operation)
    prepared = components.coordinator.prepare(
        (request,),
        engine,
        PreparationContext(
            operation=operation,
            activation=default_activation_context(),
        ),
    )
    return components, engine, prepared


def _record_path_relation(
    connection: duckdb.DuckDBPyConnection,
    source: Path,
) -> duckdb.DuckDBPyRelation:
    return connection.sql(
        """
        WITH roots AS (
            SELECT
                row_number() OVER () AS root_ordinal,
                json_extract(json, ?) AS selected
            FROM read_json_objects(
                ?,
                format='newline_delimited',
                compression='uncompressed',
                maximum_object_size=16777216,
                ignore_errors=false
            )
        ),
        items AS (
            SELECT
                root_ordinal,
                CAST(entry.key AS UBIGINT) AS item_ordinal,
                entry.value
            FROM roots, LATERAL json_each(selected) AS entry
        )
        SELECT transformed.*
        FROM (
            SELECT
                root_ordinal,
                item_ordinal,
                json_transform_strict(value, ?) AS transformed
            FROM items
        ) AS ordered_rows
        ORDER BY root_ordinal, item_ordinal
        """,
        params=["$.batch.rows", str(source), '{"id":"BIGINT"}'],
    )


def test_duckdb_json_relation_api_supports_explicit_record_formats(
    tmp_path: Path,
) -> None:
    """A DuckDB upgrade must not change the explicit JSON reader contract."""

    json_path = tmp_path / "records.json"
    ndjson_path = tmp_path / "records.ndjson"
    json_path.write_text('[{"id":1},{"id":2}]', encoding="utf-8")
    ndjson_path.write_text('{"id":3}\n{"id":4}\n', encoding="utf-8")
    connection = duckdb.connect(":memory:")
    try:
        shared_options = {
            "columns": {"id": "BIGINT"},
            "sample_size": 20_480,
            "maximum_depth": 10,
            "records": "true",
            "compression": "uncompressed",
            "maximum_object_size": 16_777_216,
            "ignore_errors": False,
            "hive_partitioning": False,
        }

        json_rows = connection.read_json(
            str(json_path),
            format="array",
            **shared_options,
        ).fetchall()
        ndjson_rows = connection.read_json(
            str(ndjson_path),
            format="newline_delimited",
            **shared_options,
        ).fetchall()
    finally:
        connection.close()

    assert json_rows == [(1,), (2,)]
    assert ndjson_rows == [(3,), (4,)]


def test_duckdb_ndjson_blank_lines_are_ignored_in_strict_mode(
    tmp_path: Path,
) -> None:
    """Pin DuckDB's blank-line behavior without reimplementing it in Python."""

    source = tmp_path / "records.ndjson"
    source.write_text('\n{"id":1}\n\n{"id":2}\n\n', encoding="utf-8")
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.read_json(
            str(source),
            columns={"id": "BIGINT"},
            sample_size=20_480,
            maximum_depth=10,
            records="true",
            format="newline_delimited",
            compression="uncompressed",
            maximum_object_size=16_777_216,
            ignore_errors=False,
            hive_partitioning=False,
        ).fetchall()
    finally:
        connection.close()

    assert rows == [(1,), (2,)]


def test_duckdb_record_path_pipeline_expands_records_in_source_order(
    tmp_path: Path,
) -> None:
    """The reviewed functions must preserve root and array-index order."""

    source = tmp_path / "nested.ndjson"
    source.write_text(
        '{"batch":{"rows":[{"id":1}]}}\n{"batch":{"rows":[{"id":2},{"id":3}]}}\n',
        encoding="utf-8",
    )
    connection = duckdb.connect(":memory:")
    try:
        relation = _record_path_relation(connection, source)

        assert relation.columns == ["id"]
        assert relation.fetchall() == [(1,), (2,), (3,)]
    finally:
        connection.close()


def test_duckdb_record_path_pipeline_supports_lazy_sql_view(
    tmp_path: Path,
) -> None:
    """The validated SQL-view fallback must not materialize record-path rows."""

    source = tmp_path / "nested.ndjson"
    source.write_text(
        '{"batch":{"rows":[{"id":1}]}}\n{"batch":{"rows":[{"id":2},{"id":3}]}}\n',
        encoding="utf-8",
    )
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            f"""
            CREATE VIEW records AS
            WITH roots AS (
                SELECT
                    row_number() OVER () AS root_ordinal,
                    json_extract(json, {_sql_literal("$.batch.rows")}) AS selected
                FROM read_json_objects(
                    {_sql_literal(str(source))},
                    format='newline_delimited',
                    compression='uncompressed',
                    maximum_object_size=16777216,
                    ignore_errors=false
                )
            ),
            items AS (
                SELECT
                    root_ordinal,
                    CAST(entry.key AS UBIGINT) AS item_ordinal,
                    entry.value
                FROM roots, LATERAL json_each(selected) AS entry
            )
            SELECT transformed.*
            FROM (
                SELECT
                    root_ordinal,
                    item_ordinal,
                    json_transform_strict(
                        value,
                        {_sql_literal('{"id":"BIGINT"}')}
                    ) AS transformed
                FROM items
            ) AS ordered_rows
            ORDER BY root_ordinal, item_ordinal
            """
        )

        source.write_text("not-json\n", encoding="utf-8")
        with pytest.raises(duckdb.Error):
            connection.execute("SELECT * FROM records").fetchall()
    finally:
        connection.close()


def test_duckdb_direct_json_relation_creates_lazy_view(tmp_path: Path) -> None:
    """Direct JSON views must retain file-backed execution rather than snapshot rows."""

    source = tmp_path / "records.json"
    source.write_text('[{"id":1}]', encoding="utf-8")
    connection = duckdb.connect(":memory:")
    try:
        relation = connection.read_json(
            str(source),
            columns={"id": "BIGINT"},
            sample_size=20_480,
            maximum_depth=10,
            records="true",
            format="array",
            compression="uncompressed",
            maximum_object_size=16_777_216,
            ignore_errors=False,
            hive_partitioning=False,
        )
        relation.create_view("records", replace=False)

        source.write_text("not-json", encoding="utf-8")
        with pytest.raises(duckdb.Error):
            connection.execute("SELECT * FROM records").fetchall()
    finally:
        connection.close()


def test_duckdb_record_path_supports_json_quoted_object_keys(tmp_path: Path) -> None:
    """Lookup-only paths need a safe representation for punctuation and quotes."""

    source = tmp_path / "quoted.json"
    source.write_text(
        '{"weird.key":{"quo\\"te":[{"id":7}]}}',
        encoding="utf-8",
    )
    connection = duckdb.connect(":memory:")
    try:
        selected = connection.execute(
            """
            SELECT json_extract(json, ?)
            FROM read_json_objects(?, format='unstructured')
            """,
            ['$."weird.key"."quo\\"te"', str(source)],
        ).fetchone()
    finally:
        connection.close()

    assert selected == ('[{"id":7}]',)


@pytest.mark.parametrize(
    ("provider_key", "filename", "content"),
    (
        (
            "json",
            "orders.json",
            '[{"id":1,"value":"alpha"},{"id":2,"value":"beta"}]',
        ),
        (
            "ndjson",
            "orders.ndjson",
            '{"id":1,"value":"alpha"}\n{"id":2,"value":"beta"}\n',
        ),
    ),
)
def test_json_family_provider_resolves_and_queries_explicit_record_format(
    provider_key: str,
    filename: str,
    content: str,
    tmp_path: Path,
) -> None:
    """Selecting either provider must bind its fixed non-auto record format."""

    source = tmp_path / filename
    source.write_text(content, encoding="utf-8")
    components, engine, prepared = _prepare_source(source)
    try:
        assert isinstance(prepared, PreparedSources)
        resolved = prepared.resolved_sources[0]
        assert resolved.provider_key == provider_key
        assert resolved.source_kind == provider_key
        assert resolved.locator_shape == "file"
        assert dict(resolved.semantic_options) == {
            "maximum_depth": 10,
            "sample_size": 20_480,
        }
        assert dict(resolved.provider_facts.items)["format"] == (
            "array" if provider_key == "json" else "newline_delimited"
        )
        assert dict(resolved.provider_facts.items)["structural_sample_rows"] == 2_048
        assert engine.query("SELECT id, value FROM orders ORDER BY id").rows == (
            (1, "alpha"),
            (2, "beta"),
        )
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


def test_pretty_json_preserves_nested_values_and_mixed_object_shapes(
    tmp_path: Path,
) -> None:
    """Pretty arrays, nested values, and missing fields must remain relational."""

    source = tmp_path / "nested.json"
    source.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "payload": {
                        "tags": ["alpha", "beta"],
                        "meta": {"active": True},
                    },
                },
                {"id": 2, "other": "present"},
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    components, engine, prepared = _prepare_source(source)
    try:
        assert isinstance(prepared, PreparedSources)
        result = engine.query(
            """
            SELECT id, payload, other
            FROM orders
            ORDER BY id
            """
        )
        assert result.rows == (
            (
                1,
                {
                    "tags": ["alpha", "beta"],
                    "meta": {"active": True},
                },
                None,
            ),
            (2, None, "present"),
        )
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


def test_explicit_schema_is_canonical_and_controls_select_star(tmp_path: Path) -> None:
    """Schema insertion order and aliases must not change relational output."""

    source = tmp_path / "typed.json"
    source.write_text('[{"value":"alpha","id":"1"}]', encoding="utf-8")
    components, engine, prepared = _prepare_source(
        source,
        options=(
            (
                "schema",
                {
                    "value": "text",
                    "id": "int",
                },
            ),
        ),
    )
    try:
        assert isinstance(prepared, PreparedSources)
        resolved = prepared.resolved_sources[0]
        semantic_options = dict(resolved.semantic_options)
        assert semantic_options == {
            "schema": FrozenJSONObject(
                (
                    ("id", "INTEGER"),
                    ("value", "VARCHAR"),
                )
            ),
        }
        assert engine.query("SELECT * FROM orders").columns == ("id", "value")
        assert engine.query("SELECT * FROM orders").rows == ((1, "alpha"),)
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


def test_schema_aliases_and_mapping_order_have_one_reproducibility_identity(
    tmp_path: Path,
) -> None:
    """Equivalent declared schemas must normalize before identity construction."""

    source = tmp_path / "typed.json"
    source.write_text('[{"value":"alpha","id":"1"}]', encoding="utf-8")
    first = resolve_source_request(
        build_source_request(
            alias="orders",
            locator=source.name,
            anchor=source.parent,
            options=(("schema", {"value": "text", "id": "int"}),),
        ),
        operation=OperationContext(OperationToken()),
    )
    second = resolve_source_request(
        build_source_request(
            alias="orders",
            locator=source.name,
            anchor=source.parent,
            options=(("schema", {"id": "INTEGER", "value": "VARCHAR"}),),
        ),
        operation=OperationContext(OperationToken()),
    )

    assert isinstance(first, ResolvedSource)
    assert isinstance(second, ResolvedSource)
    assert first.semantic_options == second.semantic_options
    assert first.identity == second.identity


def test_inference_bounds_are_identity_affecting_and_recorded(tmp_path: Path) -> None:
    """Changing either bounded inference input must change reproducibility identity."""

    source = tmp_path / "records.json"
    source.write_text('[{"id":1}]', encoding="utf-8")

    def resolve_with(
        *,
        sample_size: int,
        maximum_depth: int,
    ) -> ResolvedSource:
        resolved = resolve_source_request(
            build_source_request(
                alias="orders",
                locator=source.name,
                anchor=source.parent,
                options=(
                    ("sample_size", sample_size),
                    ("maximum_depth", maximum_depth),
                ),
            ),
            operation=OperationContext(OperationToken()),
        )
        assert isinstance(resolved, ResolvedSource)
        return resolved

    baseline = resolve_with(sample_size=64, maximum_depth=5)
    larger_sample = resolve_with(sample_size=65, maximum_depth=5)
    deeper = resolve_with(sample_size=64, maximum_depth=6)

    assert (
        len(
            {
                baseline.identity.digest,
                larger_sample.identity.digest,
                deeper.identity.digest,
            }
        )
        == 3
    )
    baseline_facts = dict(baseline.provider_facts.items)
    assert baseline_facts["sample_size"] == 64
    assert baseline_facts["maximum_depth"] == 5


def test_ndjson_inference_sample_boundary_is_enforced(tmp_path: Path) -> None:
    """Values outside the configured inference sample must not be silently nulled."""

    source = tmp_path / "records.ndjson"
    source.write_text(
        "".join(json.dumps({"id": index, "value": 1}) + "\n" for index in range(20))
        + json.dumps({"id": 20, "value": "late"})
        + "\n",
        encoding="utf-8",
    )
    _components, narrow_engine, narrow = _prepare_source(
        source,
        options=(("sample_size", 20),),
    )
    try:
        assert isinstance(narrow, SourcePreparationFailure)
        assert narrow.diagnostics[0].code.value == "source.ndjson_invalid"
        assert narrow_engine.registered_aliases == ()
    finally:
        narrow_engine.close()

    components, complete_engine, complete = _prepare_source(
        source,
        options=(("sample_size", 21),),
    )
    try:
        assert isinstance(complete, PreparedSources)
        assert complete_engine.query("SELECT DISTINCT typeof(value) FROM orders").rows == (
            ("JSON",),
        )
        assert components.coordinator.release(complete).succeeded
    finally:
        complete_engine.close()


def test_json_maximum_depth_bounds_nested_type_inference(tmp_path: Path) -> None:
    """Nested interpretation must change only when the explicit depth bound changes."""

    source = tmp_path / "nested.json"
    source.write_text(
        '[{"payload":{"inner":{"value":1}}}]',
        encoding="utf-8",
    )
    shallow_components, shallow_engine, shallow = _prepare_source(
        source,
        options=(("maximum_depth", 1),),
    )
    try:
        assert isinstance(shallow, PreparedSources)
        assert shallow_engine.query("SELECT typeof(payload) FROM orders").rows == (("JSON",),)
        assert shallow_components.coordinator.release(shallow).succeeded
    finally:
        shallow_engine.close()

    deep_components, deep_engine, deep = _prepare_source(
        source,
        options=(("maximum_depth", 4),),
    )
    try:
        assert isinstance(deep, PreparedSources)
        assert deep_engine.query("SELECT payload.inner.value FROM orders").rows == ((1,),)
        assert deep_components.coordinator.release(deep).succeeded
    finally:
        deep_engine.close()


@pytest.mark.parametrize(
    "record_path",
    (
        "payload.rows",
        "$..rows",
        "$.rows[*]",
        "$.rows[0:2]",
        "$.rows[?(@.id)]",
        "$.rows[-1]",
    ),
)
def test_record_path_rejects_non_lookup_jsonpath(
    record_path: str,
    tmp_path: Path,
) -> None:
    """Wildcards, filters, slices, descent, and malformed roots must stay rejected."""

    source = tmp_path / "nested.json"
    source.write_text('{"payload":{"rows":[{"id":1}]}}', encoding="utf-8")
    _components, engine, prepared = _prepare_source(
        source,
        options=(
            ("record_path", record_path),
            ("schema", {"id": "BIGINT"}),
        ),
    )
    try:
        assert isinstance(prepared, SourcePreparationFailure)
        assert prepared.diagnostics[0].code.value == "source.json_record_path_invalid"
    finally:
        engine.close()


@pytest.mark.parametrize(
    "options",
    (
        (("record_path", "$.payload.rows"),),
        (
            ("record_path", "$.payload.rows"),
            ("schema", {"id": "BIGINT"}),
            ("sample_size", 5),
        ),
        (
            ("record_path", "$.payload.rows"),
            ("schema", {"id": "BIGINT"}),
            ("maximum_depth", 5),
        ),
    ),
)
def test_record_path_requires_schema_without_inference_options(
    options: tuple[tuple[str, object], ...],
    tmp_path: Path,
) -> None:
    """Record-path interpretation must never fall back to schema inference."""

    source = tmp_path / "nested.json"
    source.write_text('{"payload":{"rows":[{"id":1}]}}', encoding="utf-8")
    _components, engine, prepared = _prepare_source(source, options=options)
    try:
        assert isinstance(prepared, SourcePreparationFailure)
        assert prepared.diagnostics[0].code.value == "source.json_schema_invalid"
    finally:
        engine.close()


@pytest.mark.parametrize(
    ("provider_key", "filename", "content"),
    (
        (
            "json",
            "nested.json",
            '{"payload":{"rows":[{"id":2},{"id":1}]}}',
        ),
        (
            "ndjson",
            "nested.ndjson",
            '{"payload":{"rows":[{"id":2}]}}\n{"payload":{"rows":[{"id":1}]}}\n',
        ),
    ),
)
def test_record_path_expands_objects_in_stable_source_order(
    provider_key: str,
    filename: str,
    content: str,
    tmp_path: Path,
) -> None:
    """The lookup path must expand only its selected arrays in root/index order."""

    source = tmp_path / filename
    source.write_text(content, encoding="utf-8")
    components, engine, prepared = _prepare_source(
        source,
        options=(
            ("record_path", "$.payload.rows"),
            ("schema", {"id": "BIGINT"}),
        ),
    )
    try:
        assert isinstance(prepared, PreparedSources)
        resolved = prepared.resolved_sources[0]
        assert resolved.provider_key == provider_key
        assert dict(resolved.semantic_options) == {
            "record_path": '$."payload"."rows"',
            "schema": FrozenJSONObject((("id", "BIGINT"),)),
        }
        assert engine.query("SELECT id FROM orders").rows == ((2,), (1,))
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


@pytest.mark.parametrize(
    ("filename", "content", "expected_code"),
    (
        ("broken.json", '[{"id":1}', "source.json_invalid"),
        ("broken.ndjson", '{"id":1}\nnot-json\n', "source.ndjson_invalid"),
        ("object.json", '{"id":1}', "source.json_record_shape_invalid"),
        ("scalars.json", "[1,2]", "source.json_record_shape_invalid"),
        ("scalar.ndjson", "1\n", "source.json_record_shape_invalid"),
        ("empty.json", "[]", "source.json_record_shape_invalid"),
        ("empty.ndjson", "", "source.json_record_shape_invalid"),
    ),
)
def test_json_family_rejects_invalid_documents_and_record_shapes(
    filename: str,
    content: str,
    expected_code: str,
    tmp_path: Path,
) -> None:
    """Format parse failures and non-record roots need distinct diagnostics."""

    source = tmp_path / filename
    source.write_text(content, encoding="utf-8")
    _components, engine, prepared = _prepare_source(source)
    try:
        assert isinstance(prepared, SourcePreparationFailure)
        assert prepared.diagnostics[0].code.value == expected_code
        assert engine.registered_aliases == ()
    finally:
        engine.close()


@pytest.mark.parametrize(
    ("content", "options", "expected_legacy_code"),
    (
        ('[{"id":1}', (), "source_missing"),
        (
            '{"payload":{"rows":1}}',
            (
                ("record_path", "$.payload.rows"),
                ("schema", {"id": "BIGINT"}),
            ),
            "source_bind_failed",
        ),
    ),
)
def test_json_diagnostics_translate_to_stable_legacy_error_classes(
    content: str,
    options: tuple[tuple[str, object], ...],
    expected_legacy_code: str,
    tmp_path: Path,
) -> None:
    """Legacy entry surfaces must not misclassify JSON failures as unknown types."""

    source = tmp_path / "records.json"
    source.write_text(content, encoding="utf-8")
    _components, engine, prepared = _prepare_source(source, options=options)
    request = build_source_request(
        alias="orders",
        locator=source.name,
        anchor=source.parent,
        options=options,
    )
    try:
        assert isinstance(prepared, SourcePreparationFailure)
        with pytest.raises(SourceError) as captured:
            raise_preparation_failure(prepared, requests=(request,))

        assert captured.value.code == expected_legacy_code
    finally:
        engine.close()


@pytest.mark.parametrize(
    ("filename", "content"),
    (
        ("empty.json", "[]"),
        ("empty.ndjson", ""),
    ),
)
def test_explicit_schema_makes_empty_sources_valid_zero_row_relations(
    filename: str,
    content: str,
    tmp_path: Path,
) -> None:
    """A declared schema must make empty JSON-family sources queryable."""

    source = tmp_path / filename
    source.write_text(content, encoding="utf-8")
    components, engine, prepared = _prepare_source(
        source,
        options=(("schema", {"id": "BIGINT"}),),
    )
    try:
        assert isinstance(prepared, PreparedSources)
        result = engine.query("SELECT * FROM orders")
        assert result.columns == ("id",)
        assert result.rows == ()
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


def test_explicit_schema_reports_strict_cast_failure(tmp_path: Path) -> None:
    """A value outside the declared type must not be silently coerced or nulled."""

    source = tmp_path / "typed.json"
    source.write_text('[{"id":"not-an-integer"}]', encoding="utf-8")
    _components, engine, prepared = _prepare_source(
        source,
        options=(("schema", {"id": "BIGINT"}),),
    )
    try:
        assert isinstance(prepared, SourcePreparationFailure)
        assert prepared.diagnostics[0].code.value == "source.json_schema_cast_failed"
    finally:
        engine.close()


@pytest.mark.parametrize(
    ("selected_value", "expected_code"),
    (
        (None, "source.json_record_path_missing"),
        (1, "source.json_record_path_not_array"),
        ({"id": 1}, "source.json_record_path_not_array"),
        ([1], "source.json_record_not_object"),
        ([{"id": 1}, 2], "source.json_record_not_object"),
    ),
)
def test_record_path_reports_selected_shape_failures(
    selected_value: object,
    expected_code: str,
    tmp_path: Path,
) -> None:
    """Missing, non-array, and non-object selections must remain distinguishable."""

    source = tmp_path / "nested.json"
    source.write_text(
        json.dumps({"payload": {"rows": selected_value}}),
        encoding="utf-8",
    )
    _components, engine, prepared = _prepare_source(
        source,
        options=(
            ("record_path", "$.payload.rows"),
            ("schema", {"id": "BIGINT"}),
        ),
    )
    try:
        assert isinstance(prepared, SourcePreparationFailure)
        assert prepared.diagnostics[0].code.value == expected_code
    finally:
        engine.close()


def test_record_path_allows_an_empty_selected_array(tmp_path: Path) -> None:
    """An existing empty array is a valid zero-row source, unlike a missing path."""

    source = tmp_path / "nested.json"
    source.write_text('{"payload":{"rows":[]}}', encoding="utf-8")
    components, engine, prepared = _prepare_source(
        source,
        options=(
            ("record_path", "$.payload.rows"),
            ("schema", {"id": "BIGINT"}),
        ),
    )
    try:
        assert isinstance(prepared, PreparedSources)
        assert engine.query("SELECT * FROM orders").rows == ()
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


def test_record_path_missing_key_is_not_treated_as_empty_array(tmp_path: Path) -> None:
    """A missing lookup must fail rather than silently becoming zero rows."""

    source = tmp_path / "nested.json"
    source.write_text('{"payload":{}}', encoding="utf-8")
    _components, engine, prepared = _prepare_source(
        source,
        options=(
            ("record_path", "$.payload.rows"),
            ("schema", {"id": "BIGINT"}),
        ),
    )
    try:
        assert isinstance(prepared, SourcePreparationFailure)
        assert prepared.diagnostics[0].code.value == "source.json_record_path_missing"
    finally:
        engine.close()


def test_record_path_supports_fixed_index_and_injection_shaped_quoted_keys(
    tmp_path: Path,
) -> None:
    """Validated path values must remain data even when keys resemble SQL."""

    source = tmp_path / "nested.json"
    source.write_text(
        json.dumps(
            {
                "x'); DROP VIEW orders; --": [
                    {"rows": []},
                    {"rows": [{"id": 7}]},
                ]
            }
        ),
        encoding="utf-8",
    )
    components, engine, prepared = _prepare_source(
        source,
        options=(
            ("record_path", '$."x\'); DROP VIEW orders; --"[1].rows'),
            ("schema", {"id": "BIGINT"}),
        ),
    )
    try:
        assert isinstance(prepared, PreparedSources)
        assert engine.query("SELECT id FROM orders").rows == ((7,),)
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


def test_record_path_supports_unicode_backslash_and_quote_keys(
    tmp_path: Path,
) -> None:
    """Quoted lookup keys must remain data across JSONPath and SQL boundaries."""

    key = '雪\\path"quoted'
    source = tmp_path / "nested.json"
    source.write_text(
        json.dumps({key: [{"id": 9}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    record_path = "$." + json.dumps(key, ensure_ascii=False)
    components, engine, prepared = _prepare_source(
        source,
        options=(
            ("record_path", record_path),
            ("schema", {"id": "BIGINT"}),
        ),
    )
    try:
        assert isinstance(prepared, PreparedSources)
        assert engine.query("SELECT id FROM orders").rows == ((9,),)
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


def test_record_path_remains_lazy_beyond_bounded_structural_sampling(
    tmp_path: Path,
) -> None:
    """A shape failure beyond the sample must surface during execution, not binding."""

    source = tmp_path / "nested.json"
    records: list[object] = [{"id": value} for value in range(2_048)]
    records.append("not-an-object")
    source.write_text(
        json.dumps({"payload": {"rows": records}}),
        encoding="utf-8",
    )
    components, engine, prepared = _prepare_source(
        source,
        options=(
            ("record_path", "$.payload.rows"),
            ("schema", {"id": "BIGINT"}),
        ),
    )
    try:
        assert isinstance(prepared, PreparedSources)
        with pytest.raises(
            QueryExecutionError,
            match=r"source\.json_record_not_object",
        ):
            engine.query("SELECT * FROM orders")
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


def test_json_identity_supports_observational_and_exact_without_strong_claim(
    tmp_path: Path,
) -> None:
    """JSON must hash exact bytes and never relabel unavailable strong evidence."""

    source = tmp_path / "records.json"
    content = '[{"id":1}]'
    source.write_text(content, encoding="utf-8")
    components, engine, prepared = _prepare_source(source)
    try:
        assert isinstance(prepared, PreparedSources)
        binding = prepared.bindings[0]
        observational = binding.revalidate(
            IdentityRequirement(IdentityStrength.OBSERVATIONAL),
            OperationContext(OperationToken()),
        )
        strong = binding.revalidate(
            IdentityRequirement(IdentityStrength.STRONG),
            OperationContext(OperationToken()),
        )
        exact = binding.revalidate(
            IdentityRequirement(IdentityStrength.EXACT),
            OperationContext(OperationToken()),
        )

        assert observational.status is IdentityValidationStatus.CONFIRMED
        assert strong.status is IdentityValidationStatus.UNAVAILABLE
        assert exact.status is IdentityValidationStatus.CONFIRMED
        assert exact.confirmed_strength is IdentityStrength.EXACT
        assert exact.evidence_digest == (
            "bb41eeeedb7789a3482cc74a1ac8d84effb2a508b753948130e3958c39004120"
        )
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


def test_json_exact_identity_honors_pre_cancelled_operation(tmp_path: Path) -> None:
    """Exact hashing must stop before reading when cancellation is already requested."""

    source = tmp_path / "records.json"
    source.write_text('[{"id":1}]', encoding="utf-8")
    components, engine, prepared = _prepare_source(source)
    try:
        assert isinstance(prepared, PreparedSources)
        operation = OperationContext(OperationToken())
        operation.request_cancel()

        with pytest.raises(OperationCancelled):
            prepared.bindings[0].revalidate(
                IdentityRequirement(IdentityStrength.EXACT),
                operation,
            )

        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


def test_json_observational_revalidation_reports_file_change(tmp_path: Path) -> None:
    """A changed JSON file must invalidate an existing binding before reuse."""

    source = tmp_path / "records.json"
    source.write_text('[{"id":1}]', encoding="utf-8")
    components, engine, prepared = _prepare_source(source)
    try:
        assert isinstance(prepared, PreparedSources)
        source.write_text('[{"id":100}]', encoding="utf-8")

        outcome = prepared.bindings[0].revalidate(
            IdentityRequirement(IdentityStrength.OBSERVATIONAL),
            OperationContext(OperationToken()),
        )

        assert outcome.status is IdentityValidationStatus.CHANGED
        assert outcome.diagnostic is not None
        assert outcome.diagnostic.code.value == "source.identity_changed"
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


@pytest.mark.parametrize(
    ("filename", "explicit_type", "content", "expected_provider"),
    (
        ("records.JSON", None, '[{"id":1}]', "json"),
        ("records.JSONL", None, '{"id":1}\n', "ndjson"),
        ("records.ndjson", "json", '[{"id":1}]', "json"),
        ("records.json", "ndjson", '{"id":1}\n', "ndjson"),
    ),
)
def test_json_family_honors_case_insensitive_extensions_and_explicit_override(
    filename: str,
    explicit_type: str | None,
    content: str,
    expected_provider: str,
    tmp_path: Path,
) -> None:
    """Explicit type must win, while known suffixes remain deterministic."""

    source = tmp_path / filename
    source.write_text(content, encoding="utf-8")
    components, engine, prepared = _prepare_source(
        source,
        explicit_type=explicit_type,
    )
    try:
        assert isinstance(prepared, PreparedSources)
        assert prepared.resolved_sources[0].provider_key == expected_provider
        assert engine.query("SELECT id FROM orders").rows == ((1,),)
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


@pytest.mark.parametrize(
    ("filename", "content"),
    (
        ("records.json", b"\xff\xfe[{}]"),
        ("records.ndjson", b"\xff\xfe{}\n"),
    ),
)
def test_json_family_rejects_non_utf8_prefix(
    filename: str,
    content: bytes,
    tmp_path: Path,
) -> None:
    """Invalid UTF-8 must fail during bounded resolution."""

    source = tmp_path / filename
    source.write_bytes(content)
    _components, engine, prepared = _prepare_source(source)
    try:
        assert isinstance(prepared, SourcePreparationFailure)
        assert prepared.diagnostics[0].code.value in {
            "source.json_invalid",
            "source.ndjson_invalid",
        }
    finally:
        engine.close()


def test_explicit_json_rejects_gzip_instead_of_auto_decompressing(
    tmp_path: Path,
) -> None:
    """Compressed JSON must require a future explicit capability and option."""

    source = tmp_path / "records.json.gz"
    with gzip.open(source, "wt", encoding="utf-8") as compressed:
        compressed.write('[{"id":1}]')

    _components, engine, prepared = _prepare_source(
        source,
        explicit_type="json",
    )
    try:
        assert isinstance(prepared, SourcePreparationFailure)
        assert prepared.diagnostics[0].code.value == "source.json_invalid"
        assert engine.registered_aliases == ()
    finally:
        engine.close()


def test_json_family_rejects_symlink_locator(tmp_path: Path) -> None:
    """A symlink must never substitute a different JSON source after selection."""

    target = tmp_path / "target.json"
    target.write_text('[{"id":1}]', encoding="utf-8")
    source = tmp_path / "records.json"
    try:
        source.symlink_to(target)
    except OSError:
        pytest.skip("Symbolic links are unavailable on this platform.")

    _components, engine, prepared = _prepare_source(source)
    try:
        assert isinstance(prepared, SourcePreparationFailure)
        assert prepared.diagnostics[0].code.value == "source.locator_shape_invalid"
    finally:
        engine.close()


@pytest.mark.parametrize(
    "options",
    (
        (("sample_size", 0),),
        (("sample_size", -1),),
        (("maximum_depth", 0),),
        (("maximum_depth", -1),),
    ),
)
def test_json_inference_bounds_must_be_positive(
    options: tuple[tuple[str, object], ...],
    tmp_path: Path,
) -> None:
    """Zero or negative inference limits must fail before DuckDB binding."""

    source = tmp_path / "records.json"
    source.write_text('[{"id":1}]', encoding="utf-8")
    _components, engine, prepared = _prepare_source(source, options=options)
    try:
        assert isinstance(prepared, SourcePreparationFailure)
        assert prepared.diagnostics[0].code.value == "source.json_schema_invalid"
    finally:
        engine.close()
