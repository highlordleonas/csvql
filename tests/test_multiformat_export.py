"""End-to-end source-to-export compatibility matrix."""

from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import pytest

import csvql.engine as engine_module
from csvql.api import CSVQLSession
from csvql.export import ExportFormat
from csvql.models import SourceDefinition
from csvql.project_config import initialize_project

_EXTENSION_DIRECTORY_ENV = "LOCALQL_TEST_DUCKDB_EXTENSION_DIRECTORY"
_REQUIRE_EXTENSION_ENV = "LOCALQL_REQUIRE_PROVISIONED_EXCEL"
_DUCKDB_SAFETY_CONFIG = {
    "autoinstall_known_extensions": "false",
    "autoload_known_extensions": "false",
}


@pytest.fixture
def configured_excel_extension_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_directory = os.environ.get(_EXTENSION_DIRECTORY_ENV)
    if raw_directory is None:
        return
    extension_directory = Path(raw_directory)
    if not extension_directory.is_absolute() or not extension_directory.is_dir():
        pytest.fail(f"{_EXTENSION_DIRECTORY_ENV} must name an existing absolute directory.")

    original_connect = duckdb.connect

    def connect_with_test_extensions(
        database: str = ":memory:",
        *,
        config: dict[str, str] | None = None,
        **kwargs: object,
    ) -> duckdb.DuckDBPyConnection:
        merged_config = dict(config or {})
        merged_config["extension_directory"] = str(extension_directory)
        return original_connect(database=database, config=merged_config, **kwargs)

    monkeypatch.setattr(engine_module.duckdb, "connect", connect_with_test_extensions)


def _require_excel_extension() -> None:
    required_value = os.environ.get(_REQUIRE_EXTENSION_ENV)
    if required_value not in {None, "0", "1"}:
        pytest.fail(f"{_REQUIRE_EXTENSION_ENV} must be 0, 1, or unset.")
    connection = duckdb.connect(database=":memory:", config=_DUCKDB_SAFETY_CONFIG)
    try:
        state = connection.execute(
            """
            SELECT installed OR loaded
            FROM duckdb_extensions()
            WHERE extension_name = ?
            """,
            ["excel"],
        ).fetchone()
    finally:
        connection.close()
    if state is None or not state[0]:
        if required_value == "1":
            pytest.fail("The required DuckDB Excel extension is not provisioned.")
        pytest.skip("DuckDB Excel extension is not provisioned.")


def _write_source(path: Path, source_type: str) -> None:
    if source_type == "csv":
        path.write_text("id,value\n1,alpha\n2,beta\n", encoding="utf-8")
        return
    if source_type == "json":
        path.write_text(
            '[{"id":1,"value":"alpha"},{"id":2,"value":"beta"}]\n',
            encoding="utf-8",
        )
        return
    if source_type == "ndjson":
        path.write_text(
            '{"id":1,"value":"alpha"}\n{"id":2,"value":"beta"}\n',
            encoding="utf-8",
        )
        return
    if source_type == "parquet":
        connection = duckdb.connect()
        try:
            connection.execute(
                """
                COPY (
                    SELECT *
                    FROM (VALUES (1, 'alpha'), (2, 'beta')) AS rows(id, value)
                ) TO ? (FORMAT PARQUET)
                """,
                [str(path)],
            )
        finally:
            connection.close()
        return
    raise AssertionError(f"Unexpected source type: {source_type}")


def _assert_export_rows(path: Path, export_format: ExportFormat) -> None:
    if export_format is ExportFormat.ndjson:
        assert [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] == [
            {"id": 1, "value": "alpha"},
            {"id": 2, "value": "beta"},
        ]
        return

    connection = duckdb.connect(database=":memory:", config=_DUCKDB_SAFETY_CONFIG)
    try:
        if export_format is ExportFormat.parquet:
            rows = connection.execute(
                "SELECT id, value FROM read_parquet(?) ORDER BY id",
                [str(path)],
            ).fetchall()
        elif export_format is ExportFormat.excel:
            connection.load_extension("excel")
            rows = connection.execute(
                "SELECT id, value FROM read_xlsx(?, header=true) ORDER BY id",
                [str(path)],
            ).fetchall()
        else:
            raise AssertionError(f"Unexpected export format: {export_format}")
    finally:
        connection.close()
    assert [(int(row[0]), row[1]) for row in rows] == [
        (1, "alpha"),
        (2, "beta"),
    ]


@pytest.mark.parametrize(
    ("source_type", "source_name"),
    (
        ("csv", "records.csv"),
        ("json", "records.json"),
        ("ndjson", "records.ndjson"),
        ("parquet", "records.parquet"),
    ),
)
@pytest.mark.parametrize(
    ("export_format", "suffix"),
    (
        (ExportFormat.ndjson, "ndjson"),
        (ExportFormat.parquet, "parquet"),
        (ExportFormat.excel, "xlsx"),
    ),
)
def test_python_api_queries_each_source_format_and_exports_each_structured_format(
    tmp_path: Path,
    configured_excel_extension_directory: None,
    source_type: str,
    source_name: str,
    export_format: ExportFormat,
    suffix: str,
) -> None:
    del configured_excel_extension_directory
    if export_format is ExportFormat.excel:
        _require_excel_extension()
    initialize_project(tmp_path)
    (tmp_path / "queries").mkdir(exist_ok=True)
    (tmp_path / "output").mkdir(exist_ok=True)
    source_path = tmp_path / source_name
    _write_source(source_path, source_type)
    (tmp_path / "queries" / "records.sql").write_text(
        """
        SELECT CAST(id AS INTEGER) AS id, CAST(value AS VARCHAR) AS value
        FROM records
        ORDER BY id
        """,
        encoding="utf-8",
    )
    session = CSVQLSession.from_config(tmp_path)
    source = SourceDefinition(
        "records",
        source_name,
        source_type=source_type,
        base_dir=tmp_path,
    )

    output_path = session.export(
        "queries/records.sql",
        f"output/{source_type}-to-{suffix}.{suffix}",
        format=export_format,
        sources=(source,),
    )

    _assert_export_rows(output_path, export_format)
