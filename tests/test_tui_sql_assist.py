from csvql.tui_sql_assist import (
    CompletionEdit,
    SQLAssistColumn,
    SQLAssistSource,
    build_completion_items,
    build_template_options,
    classify_duckdb_type,
    completion_edit,
    make_output_alias,
    make_range_aliases,
    safe_generated_identifier,
)


def _source(name: str, *columns: SQLAssistColumn) -> SQLAssistSource:
    return SQLAssistSource(name=name, columns=columns)


def test_classify_duckdb_type_splits_date_timestamp_and_time_only() -> None:
    assert classify_duckdb_type("DOUBLE") == "numeric"
    assert classify_duckdb_type("DECIMAL(12,2)") == "numeric"
    assert classify_duckdb_type("DATE") == "date_trend"
    assert classify_duckdb_type("TIMESTAMP") == "date_trend"
    assert classify_duckdb_type("TIME") == "time_only"
    assert classify_duckdb_type("VARCHAR") == "text"
    assert classify_duckdb_type("STRUCT(a INTEGER)") == "unknown"


def test_generated_identifiers_are_safe_and_reserved_words_are_prefixed() -> None:
    assert safe_generated_identifier("Customer ID", reserved_prefix="col_") == "customer_id"
    assert safe_generated_identifier("select", reserved_prefix="col_") == "col_select"
    assert safe_generated_identifier("2026 total", reserved_prefix="col_") == "col_2026_total"


def test_range_aliases_are_deterministic_collision_safe_and_reserved_safe() -> None:
    assert make_range_aliases(("revenue_movements", "revenue_metrics")) == {
        "revenue_movements": "rm",
        "revenue_metrics": "rm_2",
    }
    assert make_range_aliases(("select",)) == {"select": "t_select"}


def test_output_aliases_sanitize_spaced_mixed_case_and_reserved_columns() -> None:
    used: set[str] = set()
    assert make_output_alias("non_null", "Customer ID", used) == "non_null_customer_id"
    assert make_output_alias("sum", "select", used) == "sum_col_select"
    assert make_output_alias("sum", "select", used) == "sum_col_select_2"


def test_templates_include_metadata_free_options_without_columns() -> None:
    options = build_template_options((_source("customers"),), "customers")
    assert [option.key for option in options] == ["preview", "row_count"]
    assert options[0].sql == 'SELECT *\nFROM "customers"\nLIMIT 10;'
    assert options[1].sql == 'SELECT COUNT(*) AS row_count\nFROM "customers";'


def test_templates_use_first_deterministic_eligible_columns() -> None:
    source = _source(
        "revenue_movements",
        SQLAssistColumn("movement_id", "VARCHAR", "text"),
        SQLAssistColumn("mrr_delta", "DOUBLE", "numeric"),
        SQLAssistColumn("movement_month", "DATE", "date_trend"),
        SQLAssistColumn("created_at_time", "TIME", "time_only"),
    )
    sql_by_key = {
        option.key: option.sql for option in build_template_options((source,), source.name)
    }

    assert 'COUNT(rm."mrr_delta") AS non_null_mrr_delta' in sql_by_key["numeric_summary"]
    assert 'rm."movement_id"' in sql_by_key["text_grouping"]
    assert "date_trunc('month', rm.\"movement_month\") AS month" in sql_by_key["date_trend"]
    assert "created_at_time" not in sql_by_key["date_trend"]
    assert 'COUNT(rm."movement_id") AS non_null_movement_id' in sql_by_key["missingness"]


def test_join_template_requires_exact_shared_column() -> None:
    left = _source("orders", SQLAssistColumn("customer_id", "VARCHAR", "text"))
    right = _source("customers", SQLAssistColumn("customer_id", "VARCHAR", "text"))
    no_match = _source("products", SQLAssistColumn("product_id", "VARCHAR", "text"))

    with_join = {
        option.key: option.sql for option in build_template_options((left, right), "orders")
    }
    without_join = {
        option.key: option.sql for option in build_template_options((left, no_match), "orders")
    }

    assert 'JOIN "customers" AS c' in with_join["join_customer_id"]
    assert 'ON o."customer_id" = c."customer_id"' in with_join["join_customer_id"]
    assert not any(key.startswith("join_") for key in without_join)


def test_single_source_completion_uses_bare_columns() -> None:
    source = _source("customers", SQLAssistColumn("customer_id", "VARCHAR", "text"))
    items = build_completion_items((source,), text="SELECT cust", cursor_index=len("SELECT cust"))

    column_items = [item for item in items if item.item_kind == "column"]
    assert len(column_items) == 1
    assert column_items[0].insert_text == "customer_id"


def test_multi_source_completion_uses_source_qualified_columns() -> None:
    customers = _source("customers", SQLAssistColumn("customer_id", "VARCHAR", "text"))
    orders = _source("orders", SQLAssistColumn("customer_id", "VARCHAR", "text"))

    items = build_completion_items((customers, orders), text="SELECT ", cursor_index=len("SELECT "))
    inserts = {item.insert_text for item in items if item.item_kind == "column"}

    assert '"customers"."customer_id"' in inserts
    assert '"orders"."customer_id"' in inserts
    assert not any(insert.startswith("c.") or insert.startswith("o.") for insert in inserts)


def test_multi_source_completion_matches_typed_unquoted_column_prefix() -> None:
    customers = _source("customers", SQLAssistColumn("customer_id", "VARCHAR", "text"))
    orders = _source("orders", SQLAssistColumn("customer_id", "VARCHAR", "text"))

    items = build_completion_items(
        (customers, orders),
        text="SELECT cust",
        cursor_index=len("SELECT cust"),
    )

    inserts = {item.insert_text for item in items if item.item_kind == "column"}

    assert '"customers"."customer_id"' in inserts
    assert '"orders"."customer_id"' in inserts


def test_unknown_qualifier_does_not_infer_range_alias() -> None:
    source = _source("revenue_movements", SQLAssistColumn("mrr_delta", "DOUBLE", "numeric"))
    items = build_completion_items((source,), text="SELECT rm.", cursor_index=len("SELECT rm."))

    assert [item for item in items if item.item_kind == "column"] == []


def test_source_qualified_prefix_returns_source_qualified_columns() -> None:
    source = _source("revenue_movements", SQLAssistColumn("mrr_delta", "DOUBLE", "numeric"))
    text = 'SELECT "revenue_movements".'
    items = build_completion_items((source,), text=text, cursor_index=len(text))

    assert [item.insert_text for item in items if item.item_kind == "column"] == [
        '"revenue_movements"."mrr_delta"'
    ]


def test_source_qualified_member_prefix_matches_unquoted_column_text() -> None:
    source = _source("revenue_movements", SQLAssistColumn("mrr_delta", "DOUBLE", "numeric"))
    text = 'SELECT "revenue_movements".mr'
    items = build_completion_items((source,), text=text, cursor_index=len(text))

    assert [item.insert_text for item in items if item.item_kind == "column"] == [
        '"revenue_movements"."mrr_delta"'
    ]


def test_join_template_keys_remain_unique_across_multiple_join_partners() -> None:
    orders = _source("orders", SQLAssistColumn("customer_id", "VARCHAR", "text"))
    customers = _source("customers", SQLAssistColumn("customer_id", "VARCHAR", "text"))
    invoices = _source("invoices", SQLAssistColumn("customer_id", "VARCHAR", "text"))

    options = build_template_options((orders, customers, invoices), "orders")
    join_keys = [option.key for option in options if option.key.startswith("join_")]

    assert join_keys == ["join_customer_id", "join_customer_id_invoices"]


def test_completion_edit_replaces_selection_or_current_token_prefix() -> None:
    items = build_completion_items(
        (_source("customers", SQLAssistColumn("customer_id", "VARCHAR", "text")),),
        text="SELECT cust",
        cursor_index=len("SELECT cust"),
    )
    column_item = next(item for item in items if item.item_kind == "column")

    prefix_edit = completion_edit(
        "SELECT cust",
        len("SELECT cust"),
        len("SELECT cust"),
        column_item,
    )
    selection_edit = completion_edit("SELECT abc", len("SELECT "), len("SELECT abc"), column_item)

    assert prefix_edit == CompletionEdit(
        start_index=len("SELECT "),
        end_index=len("SELECT cust"),
        replacement=column_item.insert_text,
    )
    assert selection_edit == CompletionEdit(
        start_index=len("SELECT "),
        end_index=len("SELECT abc"),
        replacement=column_item.insert_text,
    )
