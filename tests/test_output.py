import json
from pathlib import Path

from csvql.models import ColumnInfo, DialectInfo, InspectResult, RowCountInfo, SampleResult
from csvql.output import (
    format_inspect_result_json,
    format_inspect_result_table,
    format_project_tables_json,
    format_project_tables_table,
    format_sample_result_json,
    format_sample_result_table,
)
from csvql.project_config import ProjectTableListing, ProjectTablesResult


def _inspect_result() -> InspectResult:
    return InspectResult(
        source={"display_path": "orders.csv"},
        dialect=DialectInfo(
            delimiter=",",
            quote='"',
            escape=None,
            header=True,
            encoding="utf-8",
        ),
        columns=(ColumnInfo(name="order_id", duckdb_type="VARCHAR"),),
        row_count=RowCountInfo.not_counted(),
        warnings=(),
    )


def test_format_inspect_result_json_is_deterministic() -> None:
    payload = json.loads(format_inspect_result_json(_inspect_result()))

    assert payload["columns"] == [{"duckdb_type": "VARCHAR", "name": "order_id"}]
    assert payload["row_count"]["mode"] == "not_counted"


def test_format_inspect_result_table_contains_core_fields() -> None:
    output = format_inspect_result_table(_inspect_result())

    assert "orders.csv" in output
    assert "order_id" in output
    assert "not_counted" in output


def test_format_inspect_result_table_uses_exact_row_count() -> None:
    result = InspectResult(
        source={"display_path": "orders.csv"},
        dialect=DialectInfo(
            delimiter=",",
            quote='"',
            escape=None,
            header=True,
            encoding="utf-8",
        ),
        columns=(ColumnInfo(name="order_id", duckdb_type="VARCHAR"),),
        row_count=RowCountInfo.exact_count(3),
        warnings=(),
    )

    output = format_inspect_result_table(result)

    assert "Rows: 3" in output
    assert "Rows: exact" not in output


def test_format_sample_result_json_is_deterministic() -> None:
    result = SampleResult(
        source={"display_path": "orders.csv"},
        limit=1,
        columns=("order_id", "status"),
        rows=(("ORD-1", "paid"),),
        warnings=(),
    )

    payload = json.loads(format_sample_result_json(result))

    assert payload["limit"] == 1
    assert payload["rows"] == [{"order_id": "ORD-1", "status": "paid"}]


def test_format_sample_result_table_contains_rows() -> None:
    result = SampleResult(
        source={"display_path": "orders.csv"},
        limit=1,
        columns=("order_id", "status"),
        rows=(("ORD-1", "paid"),),
        warnings=(),
    )

    output = format_sample_result_table(result)

    assert "ORD-1" in output
    assert "paid" in output


def test_format_project_tables_json_is_deterministic() -> None:
    result = ProjectTablesResult(
        project_root=Path("/path/to/project"),
        config_path=Path("/path/to/project/.csvql.yml"),
        tables=(
            ProjectTableListing(
                name="orders",
                path="data/orders.csv",
                resolved_path=Path("/path/to/project/data/orders.csv"),
            ),
        ),
    )

    expected = {
        "config_path": "/path/to/project/.csvql.yml",
        "project_root": "/path/to/project",
        "tables": [
            {
                "name": "orders",
                "path": "data/orders.csv",
                "resolved_path": "/path/to/project/data/orders.csv",
            }
        ],
    }

    payload = format_project_tables_json(result)

    assert payload == json.dumps(expected, indent=2, sort_keys=True)


def test_format_project_tables_table_contains_catalog_paths() -> None:
    result = ProjectTablesResult(
        project_root=Path("/path/to/project"),
        config_path=Path("/path/to/project/.csvql.yml"),
        tables=(
            ProjectTableListing(
                name="orders",
                path="data/orders.csv",
                resolved_path=Path("/path/to/project/data/orders.csv"),
            ),
        ),
    )

    output = format_project_tables_table(result)

    assert "orders" in output
    assert "data/orders.csv" in output
    assert "/path/to/project/data/orders.csv" in output
