from csvql.models import (
    ColumnInfo,
    ColumnProfile,
    DialectInfo,
    InspectResult,
    ProfileResult,
    RowCountInfo,
    SampleResult,
)


def test_row_count_not_counted_contract() -> None:
    row_count = RowCountInfo.not_counted()

    assert row_count.as_dict() == {
        "mode": "not_counted",
        "value": None,
        "exact": False,
    }


def test_row_count_exact_contract() -> None:
    row_count = RowCountInfo.exact_count(3)

    assert row_count.as_dict() == {
        "mode": "exact",
        "value": 3,
        "exact": True,
    }


def test_inspect_result_payload_contract() -> None:
    source = {"display_path": "orders.csv"}
    result = InspectResult(
        source=source,
        dialect=DialectInfo(
            delimiter=",",
            quote='"',
            escape=None,
            header=True,
            encoding="utf-8",
        ),
        columns=(ColumnInfo(name="order_id", duckdb_type="VARCHAR"),),
        row_count=RowCountInfo.not_counted(),
        warnings=("dialect warning",),
    )

    assert result.as_dict() == {
        "source": {"display_path": "orders.csv"},
        "dialect": {
            "delimiter": ",",
            "quote": '"',
            "escape": None,
            "header": True,
            "encoding": "utf-8",
        },
        "columns": [{"name": "order_id", "duckdb_type": "VARCHAR"}],
        "row_count": {"mode": "not_counted", "value": None, "exact": False},
        "warnings": ["dialect warning"],
    }
    assert result.as_dict()["source"] is source


def test_inspect_result_allows_nullable_dialect_fields() -> None:
    result = InspectResult(
        source={"display_path": "orders.csv"},
        dialect=DialectInfo(
            delimiter=None,
            quote=None,
            escape=None,
            header=None,
            encoding=None,
        ),
        columns=(),
        row_count=RowCountInfo.not_counted(),
        warnings=(),
    )

    assert result.as_dict()["dialect"] == {
        "delimiter": None,
        "quote": None,
        "escape": None,
        "header": None,
        "encoding": None,
    }


def test_sample_result_payload_contract() -> None:
    source = {"display_path": "orders.csv"}
    result = SampleResult(
        source=source,
        limit=2,
        columns=("order_id", "status"),
        rows=(("ORD-1", "paid"),),
        warnings=(),
    )

    assert result.as_dict() == {
        "source": {"display_path": "orders.csv"},
        "limit": 2,
        "columns": ["order_id", "status"],
        "rows": [{"order_id": "ORD-1", "status": "paid"}],
        "warnings": [],
    }
    assert result.as_dict()["source"] is source


def test_profile_result_payload_contract() -> None:
    source = {"display_path": "orders.csv"}
    result = ProfileResult(
        source=source,
        row_count=3,
        column_count=1,
        duplicate_row_count=1,
        columns=(
            ColumnProfile(
                name="status",
                duckdb_type="VARCHAR",
                non_null_count=2,
                null_count=1,
                null_percentage=33.333,
                distinct_count=2,
                min="paid",
                max="pending",
            ),
        ),
        warnings=("profile warning",),
    )

    assert result.as_dict() == {
        "source": {"display_path": "orders.csv"},
        "row_count": 3,
        "column_count": 1,
        "duplicate_row_count": 1,
        "columns": [
            {
                "name": "status",
                "duckdb_type": "VARCHAR",
                "non_null_count": 2,
                "null_count": 1,
                "null_percentage": 33.333,
                "distinct_count": 2,
                "min": "paid",
                "max": "pending",
            }
        ],
        "warnings": ["profile warning"],
    }
    assert result.as_dict()["source"] is source
