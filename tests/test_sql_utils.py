from csvql.sql_utils import quote_identifier


def test_quote_identifier_wraps_and_escapes_duckdb_identifier() -> None:
    assert quote_identifier("order id") == '"order id"'
    assert quote_identifier("total-amount") == '"total-amount"'
    assert quote_identifier("select") == '"select"'
    assert quote_identifier('weird"name') == '"weird""name"'
