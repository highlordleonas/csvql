from pathlib import Path

import pytest

from csvql.exceptions import SQLFileError
from csvql.sql_file import SQLFile, load_sql_file


def test_load_sql_file_reads_utf8_sql_from_invocation_directory(tmp_path: Path) -> None:
    query_path = tmp_path / "queries" / "revenue.sql"
    query_path.parent.mkdir()
    query_path.write_text("SELECT COUNT(*) AS order_count FROM orders;\n", encoding="utf-8")

    loaded = load_sql_file("queries/revenue.sql", base_dir=tmp_path)

    assert loaded == SQLFile(
        display_path="queries/revenue.sql",
        path=query_path.resolve(),
        sql="SELECT COUNT(*) AS order_count FROM orders;\n",
    )


def test_load_sql_file_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SQLFileError) as exc_info:
        load_sql_file("missing.sql", base_dir=tmp_path)

    assert exc_info.value.exit_code == 9
    assert "SQL file not found" in exc_info.value.message


def test_load_sql_file_rejects_directory(tmp_path: Path) -> None:
    query_dir = tmp_path / "queries"
    query_dir.mkdir()

    with pytest.raises(SQLFileError) as exc_info:
        load_sql_file("queries", base_dir=tmp_path)

    assert "SQL file path is a directory" in exc_info.value.message


def test_load_sql_file_rejects_invalid_utf8_bytes(tmp_path: Path) -> None:
    query_path = tmp_path / "invalid.sql"
    query_path.write_bytes(b"\xff\xfeSELECT 1;\n")

    with pytest.raises(SQLFileError) as exc_info:
        load_sql_file("invalid.sql", base_dir=tmp_path)

    assert "Failed to read SQL file" in exc_info.value.message


@pytest.mark.parametrize("content", ["", "   \n\t"])
def test_load_sql_file_rejects_empty_or_whitespace_only_sql(
    tmp_path: Path,
    content: str,
) -> None:
    query_path = tmp_path / "empty.sql"
    query_path.write_text(content, encoding="utf-8")

    with pytest.raises(SQLFileError) as exc_info:
        load_sql_file("empty.sql", base_dir=tmp_path)

    assert "SQL file is empty" in exc_info.value.message
