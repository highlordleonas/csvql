import csv
import json
from io import StringIO
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


def test_csv_export_neutralizes_spreadsheet_formula_cells() -> None:
    result = QueryResult(
        columns=("value",),
        rows=(
            ("=1+1",),
            ("+SUM(A1:A2)",),
            ("-10",),
            ("@command",),
            (" \t=cmd",),
            ("plain text",),
            (-10,),
        ),
        elapsed_ms=1.234,
    )

    output = format_query_result_for_export(result, ExportFormat.csv)

    assert list(csv.reader(StringIO(output))) == [
        ["value"],
        ["'=1+1"],
        ["'+SUM(A1:A2)"],
        ["'-10"],
        ["'@command"],
        ["' \t=cmd"],
        ["plain text"],
        ["-10"],
    ]


def test_csv_export_neutralizes_spreadsheet_formula_headers() -> None:
    result = QueryResult(
        columns=(
            "=1+1",
            "+SUM(A1:A2)",
            "-10",
            "@command",
            " \t=cmd",
            "plain text",
            'comma, and "quote"',
        ),
        rows=(("a", "b", "c", "d", "e", "f", "g"),),
        elapsed_ms=1.234,
    )

    output = format_query_result_for_export(result, ExportFormat.csv)

    assert list(csv.reader(StringIO(output))) == [
        [
            "'=1+1",
            "'+SUM(A1:A2)",
            "'-10",
            "'@command",
            "' \t=cmd",
            "plain text",
            'comma, and "quote"',
        ],
        ["a", "b", "c", "d", "e", "f", "g"],
    ]


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


def test_markdown_export_escapes_raw_html_before_building_table_cells() -> None:
    result = QueryResult(
        columns=("<b>name</b>",),
        rows=(("<img src=x onerror=alert(1)>|line\nbreak&more",),),
        elapsed_ms=1.234,
    )

    output = format_query_result_for_export(result, ExportFormat.markdown)

    assert output == (
        "| &lt;b&gt;name&lt;/b&gt; |\n"
        "| --- |\n"
        "| &lt;img src=x onerror=alert(1)&gt;\\|line<br>break&amp;more |\n"
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


def test_write_export_file_preserves_explicit_export_newlines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_write_text_atomic(
        path: Path,
        content: str,
        *,
        newline: str | None = None,
        token: object | None = None,
    ) -> None:
        captured["path"] = path
        captured["content"] = content
        captured["newline"] = newline
        captured["token"] = token

    monkeypatch.setattr("csvql.export.write_text_atomic", fake_write_text_atomic)

    write_export_file(tmp_path / "result.csv", "a\r\n1\r\n")

    assert captured["newline"] == ""


def test_write_export_file_requires_existing_parent_directory(tmp_path: Path) -> None:
    output_path = tmp_path / "missing" / "result.csv"

    with pytest.raises(ExportError) as exc_info:
        write_export_file(output_path, "hello\n")

    assert "Failed to write export output" in exc_info.value.message
    assert not output_path.parent.exists()
