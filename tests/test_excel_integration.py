"""Provisioned DuckDB Excel extension integration contract."""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import duckdb
import pytest
from typer.testing import CliRunner

import csvql.engine as engine_module
import csvql.source_runtime as source_runtime_module
from csvql.api import CSVQLSession
from csvql.cli import app
from csvql.engine import CSVQLEngine
from csvql.export import ExportFormat
from csvql.models import SourceDefinition
from csvql.project_config import add_project_table, initialize_project, load_project
from csvql.source import PreparedSources, SourcePreparationFailure, build_source_request
from csvql.source_runtime import default_source_components, prepare_source_requests
from csvql.tui_state import TUISource
from csvql.tui_workflows import inspect_source, query_sources

_EXTENSION_DIRECTORY_ENV = "LOCALQL_TEST_DUCKDB_EXTENSION_DIRECTORY"
_REQUIRE_EXTENSION_ENV = "LOCALQL_REQUIRE_PROVISIONED_EXCEL"
_DUCKDB_SAFETY_CONFIG = {
    "autoinstall_known_extensions": "false",
    "autoload_known_extensions": "false",
}
_RUNNER = CliRunner()


@pytest.fixture
def configured_extension_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route DuckDB connections to an explicitly isolated test directory when supplied."""

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
    monkeypatch.setattr(
        source_runtime_module,
        "_connect_activation_metadata",
        connect_with_test_extensions,
    )


def _require_excel_extension() -> str:
    required_value = os.environ.get(_REQUIRE_EXTENSION_ENV)
    if required_value not in {None, "0", "1"}:
        pytest.fail(f"{_REQUIRE_EXTENSION_ENV} must be 0, 1, or unset.")

    connection = duckdb.connect(database=":memory:", config=_DUCKDB_SAFETY_CONFIG)
    try:
        state = connection.execute(
            """
            SELECT installed, loaded, extension_version, install_mode
            FROM duckdb_extensions()
            WHERE extension_name = ?
            """,
            ["excel"],
        ).fetchone()
    finally:
        connection.close()

    if state is None or not (state[0] or state[1]):
        if required_value == "1":
            pytest.fail("The required DuckDB Excel extension is not provisioned.")
        pytest.skip("DuckDB Excel extension is not provisioned.")
    return str(state[2] or state[3] or "available")


def _worksheet_cell(reference: str, value: str | int | float) -> str:
    if isinstance(value, int | float):
        return f'<c r="{reference}"><v>{value}</v></c>'
    return f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'


def _write_excel_fixture(
    path: Path,
    *,
    sheet: str,
    headers: tuple[str, str],
    rows: tuple[tuple[str | int | float, str | int | float], ...],
) -> None:
    worksheet_rows: list[str] = []
    for row_number, values in enumerate((headers, *rows), start=1):
        cells = "".join(
            _worksheet_cell(f"{column}{row_number}", value)
            for column, value in zip(("A", "B"), values, strict=True)
        )
        worksheet_rows.append(f'<row r="{row_number}">{cells}</row>')

    spreadsheet_namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    office_relationship_namespace = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    )
    package_relationship_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    workbook_xml = (
        f'<workbook xmlns="{spreadsheet_namespace}" '
        f'xmlns:r="{office_relationship_namespace}"><sheets>'
        f'<sheet name={quoteattr(sheet)} sheetId="1" r:id="rId1"/>'
        "</sheets></workbook>"
    )
    workbook_relationships_xml = (
        f'<Relationships xmlns="{package_relationship_namespace}">'
        f'<Relationship Id="rId1" Type="{office_relationship_namespace}/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    package_relationships_xml = (
        f'<Relationships xmlns="{package_relationship_namespace}">'
        f'<Relationship Id="rId1" Type="{office_relationship_namespace}/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    content_types_xml = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    worksheet_xml = (
        f'<worksheet xmlns="{spreadsheet_namespace}"><dimension ref="A1:B3"/>'
        f"<sheetData>{''.join(worksheet_rows)}</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", package_relationships_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships_xml)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)


def test_provisioned_excel_extension_runs_cross_format_contract(
    tmp_path: Path,
    configured_extension_directory: None,
) -> None:
    """Exercise real Excel loading, schemas, paths, joins, identity, and cleanup."""

    extension_version = _require_excel_extension()
    sheet_name = "O'Brien Δ"
    text_workbook = tmp_path / "orders.xlsx"
    numeric_workbook = tmp_path / "metrics.xlsx"
    extensionless_workbook = tmp_path / "metrics_blob"
    lookup_csv = tmp_path / "lookup.csv"

    _write_excel_fixture(
        text_workbook,
        sheet=sheet_name,
        headers=("id", "name"),
        rows=(("1", "alpha"), ("2", "beta")),
    )
    _write_excel_fixture(
        numeric_workbook,
        sheet="Metrics",
        headers=("id", "amount"),
        rows=((1, 10.5), (2, 20.25)),
    )
    shutil.copyfile(numeric_workbook, extensionless_workbook)
    lookup_csv.write_text("id,category\n1,first\n2,second\n", encoding="utf-8")

    excel_request = build_source_request(
        alias="orders",
        locator=text_workbook.name,
        anchor=text_workbook.parent,
        options=(
            ("sheet", sheet_name),
            ("range", "'O''Brien Δ'!$A$1:$B$3"),
            ("type_mode", "text"),
        ),
    )
    csv_request = build_source_request(
        alias="lookup",
        locator=lookup_csv.name,
        anchor=lookup_csv.parent,
    )
    with CSVQLEngine() as engine:
        prepared = prepare_source_requests(
            (excel_request, csv_request),
            engine_session=engine,
            operation=engine.operation_context,
        )
        assert isinstance(prepared, PreparedSources), prepared
        assert not isinstance(prepared, SourcePreparationFailure)
        try:
            joined_rows = engine.query(
                """
                SELECT orders.name, lookup.category
                FROM orders
                JOIN lookup USING (id)
                ORDER BY orders.id
                """
            ).rows
            excel_schema = prepared.bindings[0].runtime_schema
            resolved_excel = prepared.resolved_sources[0]
        finally:
            cleanup = default_source_components().coordinator.release(prepared)

        assert joined_rows == (("alpha", "first"), ("beta", "second"))
        assert excel_schema == (("id", "VARCHAR"), ("name", "VARCHAR"))
        assert resolved_excel.semantic_options == (
            ("header", True),
            ("range", "A1:B3"),
            ("sheet", sheet_name),
            ("stop_at_empty", False),
            ("type_mode", "text"),
        )
        assert resolved_excel.dependency_versions == (
            ("duckdb.extension.excel", extension_version),
        )
        assert cleanup.succeeded
        assert engine.registered_aliases == ()

    extensionless_request = build_source_request(
        alias="metrics",
        locator=extensionless_workbook.name,
        anchor=extensionless_workbook.parent,
        explicit_type="excel",
        options=(("range", "A1:B3"), ("type_mode", "infer")),
    )
    with CSVQLEngine() as engine:
        prepared = prepare_source_requests(
            (extensionless_request,),
            engine_session=engine,
            operation=engine.operation_context,
        )
        assert isinstance(prepared, PreparedSources), prepared
        assert not isinstance(prepared, SourcePreparationFailure)
        try:
            inferred_rows = engine.query("SELECT id, amount FROM metrics ORDER BY id").rows
            inferred_schema = prepared.bindings[0].runtime_schema
        finally:
            cleanup = default_source_components().coordinator.release(prepared)

        assert inferred_rows == ((1.0, 10.5), (2.0, 20.25))
        assert inferred_schema == (("id", "DOUBLE"), ("amount", "DOUBLE"))
        assert cleanup.succeeded
        assert engine.registered_aliases == ()


def test_provisioned_excel_extension_executes_across_public_surfaces(
    tmp_path: Path,
    configured_extension_directory: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove CLI, Python, TUI, and catalog execution use one Excel source contract."""

    _require_excel_extension()
    workbook = tmp_path / "records.xlsx"
    _write_excel_fixture(
        workbook,
        sheet="Records",
        headers=("id", "name"),
        rows=((1, "alpha"), (2, "beta")),
    )
    initialize_project(tmp_path)
    options = {
        "range": "A1:B3",
        "sheet": "Records",
        "type_mode": "text",
    }
    sql = "SELECT count(*) AS row_count FROM records"

    monkeypatch.chdir(tmp_path)
    cli_result = _RUNNER.invoke(
        app,
        [
            "query",
            workbook.name,
            sql,
            "--type",
            "excel",
            "--option",
            "range=A1:B3",
            "--option",
            "sheet=Records",
            "--option",
            "type_mode=text",
            "--output",
            "json",
        ],
        catch_exceptions=False,
    )
    assert cli_result.exit_code == 0, cli_result.output
    assert json.loads(cli_result.output)["rows"] == [{"row_count": 2}]

    definition = SourceDefinition(
        "records",
        workbook.name,
        source_type="excel",
        options=options,
        base_dir=tmp_path,
    )
    session = CSVQLSession.from_config(tmp_path)
    assert session.query(sql, sources=(definition,)).rows == ((2,),)

    tui_source = TUISource(
        name="records",
        locator=workbook.name,
        anchor=tmp_path,
        source_type="excel",
        options=options,
        origin="session",
    )
    assert query_sources((tui_source,), sql).rows == ((2,),)
    assert tuple(
        (column.name, column.duckdb_type) for column in inspect_source(tui_source).columns
    ) == (
        ("id", "VARCHAR"),
        ("name", "VARCHAR"),
    )

    add_project_table(
        load_project(tmp_path),
        "records",
        workbook.name,
        source_type="excel",
        options=options,
        invocation_dir=tmp_path,
    )
    assert CSVQLSession.from_config(tmp_path).query(sql).rows == ((2,),)


@pytest.mark.parametrize(
    ("export_format", "suffix"),
    (
        (ExportFormat.ndjson, "ndjson"),
        (ExportFormat.parquet, "parquet"),
        (ExportFormat.excel, "xlsx"),
    ),
)
def test_excel_source_exports_to_each_structured_result_format(
    tmp_path: Path,
    configured_extension_directory: None,
    export_format: ExportFormat,
    suffix: str,
) -> None:
    del configured_extension_directory
    _require_excel_extension()
    workbook = tmp_path / "records.xlsx"
    _write_excel_fixture(
        workbook,
        sheet="Records",
        headers=("id", "name"),
        rows=((1, "alpha"), (2, "beta")),
    )
    initialize_project(tmp_path)
    (tmp_path / "queries").mkdir(exist_ok=True)
    (tmp_path / "output").mkdir(exist_ok=True)
    (tmp_path / "queries" / "records.sql").write_text(
        """
        SELECT CAST(id AS INTEGER) AS id, CAST(name AS VARCHAR) AS name
        FROM records
        ORDER BY id
        """,
        encoding="utf-8",
    )
    definition = SourceDefinition(
        "records",
        workbook.name,
        source_type="excel",
        options={"range": "A1:B3", "sheet": "Records", "type_mode": "text"},
        base_dir=tmp_path,
    )
    session = CSVQLSession.from_config(tmp_path)

    output_path = session.export(
        "queries/records.sql",
        f"output/excel-to-{suffix}.{suffix}",
        format=export_format,
        sources=(definition,),
    )

    if export_format is ExportFormat.ndjson:
        assert [
            json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()
        ] == [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]
        return

    connection = duckdb.connect(database=":memory:", config=_DUCKDB_SAFETY_CONFIG)
    try:
        if export_format is ExportFormat.parquet:
            rows = connection.execute(
                "SELECT id, name FROM read_parquet(?) ORDER BY id",
                [str(output_path)],
            ).fetchall()
        else:
            connection.load_extension("excel")
            rows = connection.execute(
                "SELECT id, name FROM read_xlsx(?, header=true) ORDER BY id",
                [str(output_path)],
            ).fetchall()
    finally:
        connection.close()
    assert [(int(row[0]), row[1]) for row in rows] == [
        (1, "alpha"),
        (2, "beta"),
    ]
