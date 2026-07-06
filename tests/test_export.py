import json
from pathlib import Path

import pytest

from csvql.exceptions import ExportError
from csvql.export import (
    ExportFormat,
    format_query_result_for_export,
    resolve_export_path,
    write_export_file,
)
from csvql.models import QueryResult


def _result() -> QueryResult:
    return QueryResult(
        columns=("name", "note", "amount"),
        rows=(("Alex", "pipe | value", 20.5), ("Blair", "line\nbreak", None)),
        elapsed_ms=1.234,
    )


def test_format_query_result_for_csv_export() -> None:
    output = format_query_result_for_export(_result(), ExportFormat.csv)

    assert output == ('name,note,amount\r\nAlex,pipe | value,20.5\r\nBlair,"line\nbreak",\r\n')


def test_format_query_result_for_json_export_matches_query_json_shape() -> None:
    output = format_query_result_for_export(_result(), ExportFormat.json)

    payload = json.loads(output)
    assert payload["columns"] == ["name", "note", "amount"]
    assert payload["row_count"] == 2
    assert payload["rows"][0] == {"name": "Alex", "note": "pipe | value", "amount": 20.5}


def test_format_query_result_for_markdown_export_escapes_cells() -> None:
    output = format_query_result_for_export(_result(), ExportFormat.markdown)

    assert output == (
        "| name | note | amount |\n"
        "| --- | --- | --- |\n"
        "| Alex | pipe \\| value | 20.5 |\n"
        "| Blair | line<br>break |  |\n"
    )


def test_format_query_result_for_text_export_matches_table_output() -> None:
    output = format_query_result_for_export(_result(), ExportFormat.text)

    assert "name" in output
    assert "Alex" in output
    assert "2 row(s) in 1.23 ms" in output


def test_resolve_export_path_refuses_existing_file_without_force(tmp_path: Path) -> None:
    output_path = tmp_path / "result.csv"
    output_path.write_text("existing", encoding="utf-8")

    with pytest.raises(ExportError) as exc_info:
        resolve_export_path("result.csv", base_dir=tmp_path, force=False)

    assert "Export output already exists" in exc_info.value.message


def test_resolve_export_path_requires_existing_parent_directory(tmp_path: Path) -> None:
    with pytest.raises(ExportError) as exc_info:
        resolve_export_path("missing/result.csv", base_dir=tmp_path, force=False)

    assert "Export output directory does not exist" in exc_info.value.message


def test_write_export_file_writes_utf8_text(tmp_path: Path) -> None:
    output_path = tmp_path / "result.md"

    write_export_file(output_path, "hello\n")

    assert output_path.read_text(encoding="utf-8") == "hello\n"


def test_write_export_file_requires_existing_parent_directory(tmp_path: Path) -> None:
    output_path = tmp_path / "missing" / "result.csv"

    with pytest.raises(ExportError) as exc_info:
        write_export_file(output_path, "hello\n")

    assert "Failed to write export output" in exc_info.value.message
    assert not output_path.parent.exists()
