from __future__ import annotations

import ast
from pathlib import Path

import duckdb
import pytest

from csvql.engine import CSVQLEngine
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.source import (
    ResolvedSource,
    build_source_request,
)
from csvql.source_operations import SourceOperations
from csvql.source_runtime import resolve_source_request


def _resolved_csv(path: Path, *, alias: str = "orders") -> ResolvedSource:
    resolved = resolve_source_request(
        build_source_request(
            alias=alias,
            locator=path.name,
            anchor=path.parent,
            explicit_type="csv",
        ),
        operation=OperationContext(OperationToken()),
    )
    assert isinstance(resolved, ResolvedSource)
    return resolved


def _resolved_parquet(path: Path, *, alias: str = "orders") -> ResolvedSource:
    resolved = resolve_source_request(
        build_source_request(
            alias=alias,
            locator=path.name,
            anchor=path.parent,
        ),
        operation=OperationContext(OperationToken()),
    )
    assert isinstance(resolved, ResolvedSource)
    return resolved


def _resolved_json_family(
    path: Path,
    *,
    provider_key: str,
    alias: str = "orders",
) -> ResolvedSource:
    resolved = resolve_source_request(
        build_source_request(
            alias=alias,
            locator=path.name,
            anchor=path.parent,
            explicit_type=provider_key,
        ),
        operation=OperationContext(OperationToken()),
    )
    assert isinstance(resolved, ResolvedSource)
    return resolved


def test_csv_inspect_sample_and_profile_preserve_relational_behavior(
    tmp_path: Path,
) -> None:
    """Moving operations outward must not change existing CSV results."""

    path = tmp_path / "orders.csv"
    path.write_text(
        "id,value\n1,alpha\n2,beta\n2,beta\n",
        encoding="utf-8",
    )
    source = _resolved_csv(path)

    with CSVQLEngine() as engine:
        operations = SourceOperations(engine, source)
        inspected = operations.inspect(exact=True)
        sampled = operations.sample(limit=2)
        profiled = operations.profile()

        assert engine.registered_aliases == ("orders",)

    assert [column.name for column in inspected.columns] == ["id", "value"]
    assert inspected.row_count.value == 3
    assert inspected.dialect.delimiter == ","
    assert sampled.rows == ((1, "alpha"), (2, "beta"))
    assert profiled.row_count == 3
    assert profiled.duplicate_row_count == 1


def test_parquet_inspect_sample_and_profile_match_relational_behavior(
    tmp_path: Path,
) -> None:
    """Source operations must depend on relational binding, not CSV parsing."""

    path = tmp_path / "orders.parquet"
    connection = duckdb.connect(database=":memory:")
    try:
        connection.sql(
            """
            SELECT *
            FROM (VALUES (1, 'alpha'), (2, 'beta'), (2, 'beta'))
                AS rows(id, value)
            """
        ).write_parquet(str(path))
    finally:
        connection.close()
    source = _resolved_parquet(path)

    with CSVQLEngine() as engine:
        operations = SourceOperations(engine, source)
        inspected = operations.inspect(exact=True)
        sampled = operations.sample(limit=2)
        profiled = operations.profile()

    assert [column.name for column in inspected.columns] == ["id", "value"]
    assert inspected.row_count.value == 3
    assert inspected.dialect.delimiter is None
    assert sampled.rows == ((1, "alpha"), (2, "beta"))
    assert profiled.row_count == 3
    assert profiled.duplicate_row_count == 1


@pytest.mark.parametrize(
    ("provider_key", "filename", "content"),
    (
        (
            "json",
            "orders.json",
            ('[{"id":1,"value":"alpha"},{"id":2,"value":"beta"},{"id":2,"value":"beta"}]'),
        ),
        (
            "ndjson",
            "orders.ndjson",
            ('{"id":1,"value":"alpha"}\n{"id":2,"value":"beta"}\n{"id":2,"value":"beta"}\n'),
        ),
    ),
)
def test_json_family_inspect_sample_and_profile_match_relational_behavior(
    provider_key: str,
    filename: str,
    content: str,
    tmp_path: Path,
) -> None:
    """JSON-family operations must use the same relational binding boundary."""

    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    source = _resolved_json_family(path, provider_key=provider_key)

    with CSVQLEngine() as engine:
        operations = SourceOperations(engine, source)
        inspected = operations.inspect(exact=True)
        sampled = operations.sample(limit=2)
        profiled = operations.profile()

    assert [column.name for column in inspected.columns] == ["id", "value"]
    assert inspected.row_count.value == 3
    assert inspected.dialect.delimiter is None
    assert sampled.rows == ((1, "alpha"), (2, "beta"))
    assert profiled.row_count == 3
    assert profiled.duplicate_row_count == 1


def test_sample_rejects_nonpositive_limit_before_preparation(tmp_path: Path) -> None:
    """Invalid presentation bounds must not allocate an engine registration."""

    path = tmp_path / "orders.csv"
    path.write_text("id\n1\n", encoding="utf-8")
    source = _resolved_csv(path)

    with CSVQLEngine() as engine:
        with pytest.raises(ValueError, match="greater than zero"):
            SourceOperations(engine, source).sample(limit=0)
        assert engine.registered_aliases == ()


def test_cancelled_source_operation_stops_before_binding(tmp_path: Path) -> None:
    """A pre-cancelled operation must not open DuckDB or register a source."""

    path = tmp_path / "orders.csv"
    path.write_text("id\n1\n", encoding="utf-8")
    source = _resolved_csv(path)
    operation = OperationContext(OperationToken())
    operation.request_cancel()

    with CSVQLEngine(operation=operation) as engine:
        with pytest.raises(OperationCancelled):
            SourceOperations(engine, source).sample()
        assert engine.registered_aliases == ()


def test_source_operations_use_only_public_engine_and_resolved_source_contracts() -> None:
    """Private engine reach-through would couple operations back to source runtime state."""

    module_path = Path(__file__).resolve().parents[1] / "src" / "csvql" / "source_operations.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    private_engine_attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "self"
        and node.value.attr == "_engine"
        and node.attr.startswith("_")
    }
    imported_modules = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }

    assert private_engine_attributes == set()
    assert "csvql.csv_adapter" not in imported_modules
    assert "csvql.source_adapter" not in imported_modules
