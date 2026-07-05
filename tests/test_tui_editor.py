from csvql.tui_editor import (
    all_sql_statements,
    current_statement_at_offset,
    selected_or_current_sql,
)


def test_selected_sql_wins_over_current_statement() -> None:
    sql = "SELECT * FROM missing;\nSELECT COUNT(*) FROM customers;"

    assert (
        selected_or_current_sql(
            sql,
            cursor_location=(0, 8),
            selected_text="  SELECT COUNT(*) FROM customers;  ",
        )
        == "SELECT COUNT(*) FROM customers;"
    )


def test_current_statement_uses_cursor_location_between_semicolons() -> None:
    sql = "SELECT * FROM missing;\nSELECT COUNT(*) FROM customers;\nSELECT * FROM also_missing;"

    assert (
        selected_or_current_sql(sql, cursor_location=(1, 8), selected_text="")
        == "SELECT COUNT(*) FROM customers"
    )


def test_current_statement_uses_first_statement_for_leading_document_whitespace() -> None:
    sql = "  SELECT 1;\nSELECT 2;"

    assert selected_or_current_sql(sql, cursor_location=(0, 0), selected_text="") == "SELECT 1"


def test_current_statement_uses_previous_statement_in_whitespace_after_semicolon() -> None:
    sql = "SELECT 1;   \nSELECT 2;"

    assert selected_or_current_sql(sql, cursor_location=(0, 10), selected_text="") == "SELECT 1"


def test_current_statement_does_not_split_on_semicolon_inside_single_quotes() -> None:
    sql = "SELECT 'a;b' AS value;\nSELECT 2 AS value;"

    assert current_statement_at_offset(sql, 10) == "SELECT 'a;b' AS value"


def test_current_statement_does_not_split_on_semicolon_inside_double_quotes() -> None:
    sql = 'SELECT "a;b" AS value;\nSELECT 2 AS value;'

    assert current_statement_at_offset(sql, 10) == 'SELECT "a;b" AS value'


def test_current_statement_does_not_split_on_semicolon_inside_line_comment() -> None:
    sql = "SELECT 1 -- keep ; inside comment\n;\nSELECT 2 AS value;"

    assert current_statement_at_offset(sql, 8) == "SELECT 1 -- keep ; inside comment"


def test_current_statement_does_not_split_on_semicolon_inside_block_comment() -> None:
    sql = "SELECT /* keep ; inside comment */ 1 AS value;\nSELECT 2 AS value;"

    assert current_statement_at_offset(sql, 12) == ("SELECT /* keep ; inside comment */ 1 AS value")


def test_current_statement_at_end_after_trailing_semicolon_uses_previous_statement() -> None:
    sql = "SELECT COUNT(*) FROM customers;  "

    assert current_statement_at_offset(sql, len(sql)) == "SELECT COUNT(*) FROM customers"


def test_all_sql_statements_returns_ordered_non_empty_statements() -> None:
    sql = " SELECT 1; \n\nSELECT 'a;b' AS value; -- comment ;\n SELECT 3 "

    assert all_sql_statements(sql) == (
        "SELECT 1",
        "SELECT 'a;b' AS value",
        "-- comment ;\n SELECT 3",
    )
