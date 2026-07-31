from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

import csvql.engine as engine_module
import csvql.result_export as result_export_module
from csvql.cli import app
from csvql.engine import CSVQLEngine
from csvql.exceptions import ExportError
from csvql.export import ExportFormat
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.query_workflow import QueryRequest
from csvql.result_codec import encode_row_payload
from csvql.result_export import write_query_request_export
from csvql.source_adapter import EngineDependencyState
from csvql.streaming_export import ExportSummary
from csvql.tui_result_store import TUIResultStore
from csvql.tui_workflows import export_last_result

_EXTENSION_DIRECTORY_ENV = "LOCALQL_TEST_DUCKDB_EXTENSION_DIRECTORY"
_REQUIRE_EXTENSION_ENV = "LOCALQL_REQUIRE_PROVISIONED_EXCEL"
_DUCKDB_SAFETY_CONFIG = {
    "autoinstall_known_extensions": "false",
    "autoload_known_extensions": "false",
}
_RUNNER = CliRunner()


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


def _query_request() -> QueryRequest:
    return QueryRequest(
        sql=(
            "SELECT "
            "1::INTEGER AS id, "
            "DATE '2026-07-30' AS day, "
            "12.34::DECIMAL(10,2) AS amount, "
            "true AS active, "
            "'alpha'::VARCHAR AS label"
        ),
        required_sources=(),
        fallback_sources=(),
    )


def _write_query_export(
    path: Path,
    *,
    export_format: ExportFormat,
    overwrite: bool = False,
) -> ExportSummary:
    operation = OperationContext(OperationToken())
    with CSVQLEngine(operation=operation) as engine:
        return write_query_request_export(
            engine,
            _query_request(),
            path,
            export_format=export_format,
            overwrite=overwrite,
            operation=operation,
        )


def test_query_export_writes_round_trip_ndjson(tmp_path: Path) -> None:
    output_path = tmp_path / "rows.ndjson"

    summary = _write_query_export(output_path, export_format=ExportFormat.ndjson)

    assert summary.row_count == 1
    assert [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()] == [
        {
            "active": True,
            "amount": "12.34",
            "day": "2026-07-30",
            "id": 1,
            "label": "alpha",
        }
    ]


def test_query_export_writes_typed_round_trip_parquet(tmp_path: Path) -> None:
    output_path = tmp_path / "rows.parquet"

    summary = _write_query_export(output_path, export_format=ExportFormat.parquet)

    assert summary.row_count == 1
    connection = duckdb.connect()
    try:
        row = connection.execute(
            """
            SELECT
                id,
                day,
                amount,
                active,
                label,
                typeof(id),
                typeof(day),
                typeof(amount),
                typeof(active),
                typeof(label)
            FROM read_parquet(?)
            """,
            [str(output_path)],
        ).fetchone()
    finally:
        connection.close()
    assert row == (
        1,
        row[1],
        Decimal("12.34"),
        True,
        "alpha",
        "INTEGER",
        "DATE",
        "DECIMAL(10,2)",
        "BOOLEAN",
        "VARCHAR",
    )
    assert str(row[1]) == "2026-07-30"


def test_query_export_writes_round_trip_excel(
    tmp_path: Path,
    configured_excel_extension_directory: None,
) -> None:
    del configured_excel_extension_directory
    _require_excel_extension()
    output_path = tmp_path / "rows.xlsx"

    summary = _write_query_export(output_path, export_format=ExportFormat.excel)

    assert summary.row_count == 1
    connection = duckdb.connect(database=":memory:", config=_DUCKDB_SAFETY_CONFIG)
    try:
        connection.load_extension("excel")
        row = connection.execute(
            "SELECT * FROM read_xlsx(?, header=true)",
            [str(output_path)],
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    assert row[0] == 1.0
    assert str(row[1]) == "2026-07-30"
    assert row[2:] == (12.34, True, "alpha")


@pytest.mark.parametrize(
    ("export_format", "suffix"),
    (
        (ExportFormat.parquet, ".parquet"),
        (ExportFormat.excel, ".xlsx"),
    ),
)
def test_query_export_writes_readable_empty_native_result(
    tmp_path: Path,
    configured_excel_extension_directory: None,
    export_format: ExportFormat,
    suffix: str,
) -> None:
    del configured_excel_extension_directory
    if export_format is ExportFormat.excel:
        _require_excel_extension()
    output_path = tmp_path / f"empty{suffix}"
    request = QueryRequest(
        sql="SELECT 1::INTEGER AS id, 'alpha'::VARCHAR AS label WHERE false",
        required_sources=(),
        fallback_sources=(),
    )
    operation = OperationContext(OperationToken())

    with CSVQLEngine(operation=operation) as engine:
        summary = write_query_request_export(
            engine,
            request,
            output_path,
            export_format=export_format,
            overwrite=False,
            operation=operation,
        )

    assert summary.row_count == 0
    connection = duckdb.connect(database=":memory:", config=_DUCKDB_SAFETY_CONFIG)
    try:
        if export_format is ExportFormat.parquet:
            rows = connection.execute(
                "SELECT id, label FROM read_parquet(?)",
                [str(output_path)],
            ).fetchall()
        else:
            connection.load_extension("excel")
            rows = connection.execute(
                "SELECT id, label FROM read_xlsx(?, header=true)",
                [str(output_path)],
            ).fetchall()
    finally:
        connection.close()
    assert rows == []


@pytest.mark.parametrize(
    ("export_format", "suffix"),
    (
        (ExportFormat.ndjson, "ndjson"),
        (ExportFormat.parquet, "parquet"),
        (ExportFormat.excel, "xlsx"),
    ),
)
def test_cli_surface_exports_csv_query_to_each_structured_format(
    tmp_path: Path,
    configured_excel_extension_directory: None,
    monkeypatch: pytest.MonkeyPatch,
    export_format: ExportFormat,
    suffix: str,
) -> None:
    del configured_excel_extension_directory
    if export_format is ExportFormat.excel:
        _require_excel_extension()
    (tmp_path / "records.csv").write_text(
        "id,value\n1,alpha\n2,beta\n",
        encoding="utf-8",
    )
    (tmp_path / "records.sql").write_text(
        "SELECT CAST(id AS INTEGER) AS id, value FROM records ORDER BY id",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = _RUNNER.invoke(
        app,
        [
            "export",
            "records.sql",
            "--format",
            export_format.value,
            "--out",
            f"result.{suffix}",
            "--source",
            "records=records.csv",
            "--source-type",
            "records=csv",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    output_path = tmp_path / f"result.{suffix}"
    if export_format is ExportFormat.ndjson:
        assert [
            json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()
        ] == [{"id": 1, "value": "alpha"}, {"id": 2, "value": "beta"}]
        return

    connection = duckdb.connect(database=":memory:", config=_DUCKDB_SAFETY_CONFIG)
    try:
        if export_format is ExportFormat.parquet:
            rows = connection.execute(
                "SELECT id, value FROM read_parquet(?) ORDER BY id",
                [str(output_path)],
            ).fetchall()
        else:
            connection.load_extension("excel")
            rows = connection.execute(
                "SELECT id, value FROM read_xlsx(?, header=true) ORDER BY id",
                [str(output_path)],
            ).fetchall()
    finally:
        connection.close()
    assert [(int(row[0]), row[1]) for row in rows] == [
        (1, "alpha"),
        (2, "beta"),
    ]


def test_preserved_result_ndjson_export_uses_tui_workflow(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    writer = store.begin_complete(
        sequence=1,
        columns=("id", "value"),
        column_types=("INTEGER", "VARCHAR"),
    )
    writer.append_payload(encode_row_payload((1, "alpha")))
    writer.append_payload(encode_row_payload((2, "beta")))
    stored = writer.commit(elapsed_ms=1.0)

    try:
        output_path = export_last_result(
            store,
            stored.handle,
            "result.ndjson",
            columns=stored.columns,
            elapsed_ms=stored.elapsed_ms,
            export_format=ExportFormat.ndjson,
            base_dir=tmp_path,
        )

        assert [
            json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()
        ] == [{"id": 1, "value": "alpha"}, {"id": 2, "value": "beta"}]
    finally:
        store.cleanup()


@pytest.mark.parametrize(
    ("export_format", "suffix"),
    (
        (ExportFormat.parquet, ".parquet"),
        (ExportFormat.excel, ".xlsx"),
    ),
)
def test_preserved_result_native_export_uses_recorded_duckdb_types(
    tmp_path: Path,
    configured_excel_extension_directory: None,
    export_format: ExportFormat,
    suffix: str,
) -> None:
    del configured_excel_extension_directory
    if export_format is ExportFormat.excel:
        _require_excel_extension()
    store = TUIResultStore(temp_root=tmp_path)
    writer = store.begin_complete(
        sequence=1,
        columns=("id", "amount"),
        column_types=("INTEGER", "DECIMAL(10,2)"),
    )
    writer.append_payload(encode_row_payload((1, Decimal("12.34"))))
    stored = writer.commit(elapsed_ms=1.0)

    output_path = export_last_result(
        store,
        stored.handle,
        f"result{suffix}",
        columns=stored.columns,
        elapsed_ms=stored.elapsed_ms,
        export_format=export_format,
        base_dir=tmp_path,
    )

    connection = duckdb.connect(database=":memory:", config=_DUCKDB_SAFETY_CONFIG)
    try:
        if export_format is ExportFormat.parquet:
            row = connection.execute(
                "SELECT id, amount, typeof(id), typeof(amount) FROM read_parquet(?)",
                [str(output_path)],
            ).fetchone()
            assert row == (1, Decimal("12.34"), "INTEGER", "DECIMAL(10,2)")
        else:
            connection.load_extension("excel")
            row = connection.execute(
                "SELECT * FROM read_xlsx(?, header=true)",
                [str(output_path)],
            ).fetchone()
            assert row == (1.0, 12.34)
    finally:
        connection.close()
        store.cleanup()


def test_excel_export_missing_dependency_fails_closed_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "rows.xlsx"
    load_calls: list[str] = []

    monkeypatch.setattr(
        CSVQLEngine,
        "inspect_dependency",
        lambda *args, **kwargs: EngineDependencyState(
            dependency_key="duckdb.extension.excel",
            available=False,
            dependency_version=None,
            duckdb_version=duckdb.__version__,
        ),
    )
    monkeypatch.setattr(
        CSVQLEngine,
        "load_installed_extension",
        lambda dependency_key, **kwargs: load_calls.append(dependency_key),
    )

    with pytest.raises(ExportError, match="requires a provisioned") as error:
        _write_query_export(output_path, export_format=ExportFormat.excel)

    assert "never installs extensions automatically" in str(error.value.suggestion)
    assert load_calls == []
    assert not output_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_native_export_refuses_overwrite_and_preserves_existing_bytes(tmp_path: Path) -> None:
    output_path = tmp_path / "rows.parquet"
    output_path.write_bytes(b"existing")

    with pytest.raises(ExportError, match="already exists"):
        _write_query_export(output_path, export_format=ExportFormat.parquet)

    assert output_path.read_bytes() == b"existing"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["rows.parquet"]


def test_native_preserved_export_rejects_missing_type_metadata(tmp_path: Path) -> None:
    output_path = tmp_path / "rows.parquet"

    class UntypedSource:
        columns = ("id",)
        elapsed_ms = 1.0

        def iter_rows(self):
            yield (1,)

    with pytest.raises(ExportError, match="does not include") as error:
        result_export_module.write_row_source_export(
            UntypedSource(),
            output_path,
            export_format=ExportFormat.parquet,
            overwrite=False,
        )

    assert "Rerun the query" in str(error.value.suggestion)
    assert not output_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_native_export_cancellation_before_publish_removes_staged_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "rows.parquet"
    operation = OperationContext(OperationToken())
    request = _query_request()

    def cancel_after_write(
        engine: CSVQLEngine,
        sql: str,
        path: Path,
        *,
        export_format: ExportFormat,
    ) -> ExportSummary:
        del engine, sql, export_format
        path.write_bytes(b"partial")
        operation.token.cancel()
        return ExportSummary(row_count=1, elapsed_ms=1.0)

    monkeypatch.setattr(result_export_module, "_copy_query_to_path", cancel_after_write)

    with CSVQLEngine(operation=operation) as engine:
        with pytest.raises(OperationCancelled):
            write_query_request_export(
                engine,
                request,
                output_path,
                export_format=ExportFormat.parquet,
                overwrite=False,
                operation=operation,
            )

    assert not output_path.exists()
    assert list(tmp_path.iterdir()) == []
