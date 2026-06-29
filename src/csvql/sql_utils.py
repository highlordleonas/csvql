"""Small SQL-generation helpers for CSVQL-controlled DuckDB queries."""


def quote_identifier(identifier: str) -> str:
    """Return a DuckDB identifier quoted for generated CSVQL SQL."""

    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'
