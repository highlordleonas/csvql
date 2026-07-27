import csv
import json
from datetime import date
from pathlib import Path

import pytest

import csvql.api as api_module
import csvql.query_workflow as query_workflow
from csvql import (
    CSVQLSession,
    ExportFormat,
    InspectResult,
    ProfileResult,
    ProjectTablesResult,
    QueryResult,
    SampleResult,
)
from csvql.csv_adapter import CSVSourceAdapter
from csvql.engine import CSVQLEngine
from csvql.exceptions import (
    CSVQLError,
    ExportError,
    ProjectConfigError,
    QueryExecutionError,
    SQLFileError,
)
from csvql.operation import OperationCancelled
from csvql.quality import CheckRunResult
from csvql.result_stream import ResultBatch
from csvql.streaming_export import write_streaming_export


def _write_project(
    root: Path,
    *,
    rows: str = "ORD-001,paid\nORD-002,pending\n",
) -> None:
    (root / "data").mkdir(parents=True)
    (root / "queries").mkdir(parents=True)
    (root / "nested" / "child").mkdir(parents=True)
    (root / "output").mkdir(parents=True)
    (root / "data" / "orders.csv").write_text(
        "order_id,status\n" + rows,
        encoding="utf-8",
    )
    (root / "queries" / "count_orders.sql").write_text(
        "SELECT COUNT(*) AS order_count FROM orders",
        encoding="utf-8",
    )
    (root / "queries" / "list_orders.sql").write_text(
        "SELECT order_id, status FROM orders ORDER BY order_id",
        encoding="utf-8",
    )
    (root / ".csvql.yml").write_text(
        (
            "version: 1\n"
            "tables:\n"
            "  orders:\n"
            "    path: data/orders.csv\n"
            "    checks:\n"
            "      - name: order_id_required\n"
            "        type: not_null\n"
            "        column: order_id\n"
        ),
        encoding="utf-8",
    )


def test_session_query_uses_nearest_project_context(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)

    session = CSVQLSession.from_config(project_root / "nested" / "child")
    result = session.query("SELECT COUNT(*) AS order_count FROM orders")

    assert isinstance(result, QueryResult)
    assert result.columns == ("order_count",)
    assert result.rows == ((2,),)


@pytest.mark.parametrize("operation_name", ["inspect", "sample", "profile"])
def test_session_source_operation_shares_context_from_resolve_through_bind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation_name: str,
) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)
    resolve_operations: list[object] = []
    bind_operations: list[object] = []
    real_resolve = CSVSourceAdapter.resolve
    real_bind = CSVSourceAdapter.bind

    def recording_resolve(self, spec, operation):
        resolve_operations.append(operation)
        return real_resolve(self, spec, operation)

    def recording_bind(self, source, engine_session, binding_context):
        bind_operations.append(binding_context.operation)
        return real_bind(self, source, engine_session, binding_context)

    monkeypatch.setattr(CSVSourceAdapter, "resolve", recording_resolve)
    monkeypatch.setattr(CSVSourceAdapter, "bind", recording_bind)

    method = getattr(session, operation_name)
    method("orders")

    assert len(resolve_operations) == 1
    assert bind_operations == resolve_operations


def test_session_query_does_not_use_legacy_table_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    def reject_legacy_registration(self: CSVQLEngine, sources: object) -> None:
        del self, sources
        raise AssertionError("legacy register_tables path used")

    monkeypatch.setattr(CSVQLEngine, "register_tables", reject_legacy_registration)

    result = session.query("SELECT COUNT(*) AS order_count FROM orders")

    assert result.rows == ((2,),)


def test_session_query_preserves_public_registration_error_for_unreadable_csv(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    csv_path = project_root / "data" / "orders.csv"
    csv_path.write_bytes(b"order_id,status\n\xff,paid\n")
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(CSVQLError) as exc_info:
        session.query("SELECT * FROM orders")

    assert type(exc_info.value) is CSVQLError
    assert exc_info.value.message == (
        f"Failed to register CSV table 'orders' from {csv_path.resolve()}."
    )


def test_session_query_attributes_same_basename_bind_failure_to_exact_alias(
    tmp_path: Path,
) -> None:
    """Sanitized basenames must not make multi-source diagnostics ambiguous."""

    project_root = tmp_path / "project"
    first_path = project_root / "first" / "data.csv"
    second_path = project_root / "second" / "data.csv"
    first_path.parent.mkdir(parents=True)
    second_path.parent.mkdir(parents=True)
    first_path.write_text("id\n1\n", encoding="utf-8")
    second_path.write_bytes(b"id\n\xff\n")
    (project_root / ".csvql.yml").write_text(
        (
            "version: 1\n"
            "tables:\n"
            "  first:\n"
            "    path: first/data.csv\n"
            "  second:\n"
            "    path: second/data.csv\n"
        ),
        encoding="utf-8",
    )
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(CSVQLError) as exc_info:
        session.query("SELECT * FROM first")

    assert type(exc_info.value) is CSVQLError
    assert exc_info.value.message == (
        f"Failed to register CSV table 'second' from {second_path.resolve()}."
    )


def test_zero_argument_engine_preserves_complete_query_result() -> None:
    with CSVQLEngine() as engine:
        result = engine.query("SELECT 1 AS first, DATE '2026-07-22' AS observed_on")

    assert result.columns == ("first", "observed_on")
    assert result.rows == ((1, date(2026, 7, 22)),)
    assert result.row_count == 1


def test_session_run_file_resolves_paths_from_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    _write_project(project_root)

    monkeypatch.chdir(outside_dir)
    session = CSVQLSession.from_config(project_root)
    result = session.run_file("queries/count_orders.sql")

    assert result.columns == ("order_count",)
    assert result.rows == ((2,),)


def test_session_query_and_run_file_keep_engine_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)
    real_query = CSVQLEngine.query
    materialized_sql: list[str] = []

    def recording_query(
        self: CSVQLEngine,
        sql: str,
        params: object = None,
    ) -> QueryResult:
        materialized_sql.append(sql)
        return real_query(self, sql, params)

    monkeypatch.setattr(CSVQLEngine, "query", recording_query)

    session.query("SELECT COUNT(*) AS order_count FROM orders")
    session.run_file("queries/count_orders.sql")

    assert materialized_sql == [
        "SELECT COUNT(*) AS order_count FROM orders",
        "SELECT COUNT(*) AS order_count FROM orders",
    ]


def test_session_tables_returns_project_table_listing(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    result = session.tables()

    assert isinstance(result, ProjectTablesResult)
    assert result.project_root == project_root.resolve()
    assert [table.name for table in result.tables] == ["orders"]
    assert result.tables[0].path == "data/orders.csv"
    assert result.tables[0].resolved_path == (project_root / "data" / "orders.csv").resolve()


def test_session_inspect_returns_inspect_result_for_catalog_alias(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    result = session.inspect("orders")

    assert isinstance(result, InspectResult)
    assert result.source["display_path"] == "orders"
    assert [column.name for column in result.columns] == ["order_id", "status"]
    assert result.row_count.mode == "not_counted"
    assert result.row_count.value is None


def test_session_inspect_exact_returns_exact_row_count(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    result = session.inspect("orders", exact=True)

    assert result.row_count.mode == "exact"
    assert result.row_count.value == 2
    assert result.row_count.exact is True


def test_session_sample_returns_sample_result_for_catalog_alias(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    result = session.sample("orders", limit=1)

    assert isinstance(result, SampleResult)
    assert result.source["display_path"] == "orders"
    assert result.limit == 1
    assert result.columns == ("order_id", "status")
    assert result.rows == (("ORD-001", "paid"),)


def test_session_sample_preserves_positive_limit_rule(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(ValueError, match="Sample limit must be greater than zero"):
        session.sample("orders", limit=0)


def test_session_profile_returns_profile_result_for_catalog_alias(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    result = session.profile("orders")

    assert isinstance(result, ProfileResult)
    assert result.source["display_path"] == "orders"
    assert result.row_count == 2
    assert result.column_count == 2


def test_session_export_writes_csv_and_returns_resolved_path(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    output_path = session.export(
        "queries/count_orders.sql",
        "output/count-orders.csv",
        format=ExportFormat.csv,
    )

    assert output_path == (project_root / "output" / "count-orders.csv").resolve()
    assert output_path.read_bytes() == b"order_count\r\n2\r\n"


def test_session_export_streams_without_calling_query_materializer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)
    output_path = project_root / "output" / "orders.csv"
    writer_calls: list[tuple[Path, ExportFormat, bool]] = []

    def reject_materialization(*args: object, **kwargs: object) -> QueryResult:
        del args, kwargs
        raise AssertionError("CSVQLSession.export must not materialize a QueryResult.")

    def recording_streaming_writer(
        source: object,
        path: Path,
        *,
        export_format: ExportFormat,
        overwrite: bool,
        token: object = None,
    ) -> object:
        writer_calls.append((path, export_format, overwrite))
        return write_streaming_export(
            source,
            path,
            export_format=export_format,
            overwrite=overwrite,
            token=token,
        )

    monkeypatch.setattr(CSVQLEngine, "query", reject_materialization)
    monkeypatch.setattr(
        api_module,
        "write_streaming_export",
        recording_streaming_writer,
        raising=False,
    )

    result_path = session.export(
        "queries/list_orders.sql",
        "output/orders.csv",
        format=ExportFormat.csv,
    )

    assert result_path == output_path.resolve()
    assert writer_calls == [(output_path.resolve(), ExportFormat.csv, False)]
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "order_id,status",
        "ORD-001,paid",
        "ORD-002,pending",
    ]


def test_export_row_source_is_concrete_one_shot_and_fetches_bounded_batches() -> None:
    events: list[str] = []
    fetch_sizes: list[int] = []
    rows = tuple((index,) for index in range(257))

    class RecordingStream:
        columns = ("value",)
        elapsed_ms = 1.0

        def __init__(self) -> None:
            self.offset = 0

        def fetch_rows(self, max_rows: int) -> ResultBatch:
            fetch_sizes.append(max_rows)
            batch = rows[self.offset : self.offset + max_rows]
            self.offset += len(batch)
            self.elapsed_ms += 1.0
            return ResultBatch(rows=batch, exhausted=not batch)

        def request_interrupt(self) -> None:
            events.append("interrupt")

        def close(self) -> None:
            events.append("close")

    stream = RecordingStream()
    source = query_workflow._adapt_result_stream_for_export(stream)
    iterator = source.iter_rows()

    assert iter(iterator) is iterator
    assert list(iterator) == list(rows)
    assert fetch_sizes == [256, 256, 256]
    assert events == ["close"]
    assert source.elapsed_ms == 4.0
    with pytest.raises(RuntimeError, match="already been consumed"):
        source.iter_rows()


def test_export_row_source_interrupts_when_closed_with_buffered_exhausted_rows() -> None:
    events: list[str] = []

    class RecordingStream:
        columns = ("value",)
        elapsed_ms = 1.0

        def fetch_rows(self, max_rows: int) -> ResultBatch:
            assert max_rows == 256
            events.append("fetch")
            return ResultBatch(rows=((1,), (2,)), exhausted=True)

        def request_interrupt(self) -> None:
            events.append("interrupt")

        def close(self) -> None:
            events.append("close")

    source = query_workflow._adapt_result_stream_for_export(RecordingStream())
    iterator = source.iter_rows()

    assert next(iterator) == (1,)

    iterator.close()

    assert events == ["fetch", "interrupt", "close"]


def test_session_export_writes_json_with_query_result_shape(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    output_path = session.export(
        "queries/count_orders.sql",
        "output/count-orders.json",
        format="json",
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert set(payload) == {"columns", "elapsed_ms", "row_count", "rows"}
    assert payload["columns"] == ["order_count"]
    assert payload["rows"] == [{"order_count": 2}]
    assert payload["row_count"] == 1
    assert isinstance(payload["elapsed_ms"], float)


def test_session_export_defaults_to_json(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    output_path = session.export("queries/count_orders.sql", "output/count-orders.json")

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["columns"] == ["order_count"]
    assert payload["rows"] == [{"order_count": 2}]


def test_session_export_writes_markdown(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    output_path = session.export(
        "queries/count_orders.sql",
        "output/count-orders.md",
        format=ExportFormat.markdown,
    )

    assert output_path.read_text(encoding="utf-8") == "| order_count |\n| --- |\n| 2 |\n"


def test_session_export_refuses_overwrite_without_force(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    output_path = project_root / "output" / "count-orders.csv"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text("existing", encoding="utf-8")
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(ExportError, match="Export output already exists"):
        session.export("queries/count_orders.sql", "output/count-orders.csv", format="csv")

    assert output_path.read_text(encoding="utf-8") == "existing"


@pytest.mark.parametrize("force", [False, True])
def test_session_export_forwards_force_to_atomic_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    force: bool,
) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)
    writes: list[tuple[Path, ExportFormat, bool, list[tuple[object, ...]]]] = []

    def fake_write_streaming_export(
        source: object,
        path: Path,
        *,
        export_format: ExportFormat,
        overwrite: bool,
        token: object,
    ) -> object:
        writes.append((path, export_format, overwrite, list(source.iter_rows())))
        return object()

    monkeypatch.setattr("csvql.api.write_streaming_export", fake_write_streaming_export)

    output_path = session.export(
        "queries/count_orders.sql",
        "output/count-orders.csv",
        format="csv",
        force=force,
    )

    assert writes == [
        (output_path, ExportFormat.csv, force, [(2,)]),
    ]


def test_session_export_force_overwrites_existing_file(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    output_path = project_root / "output" / "count-orders.csv"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text("existing", encoding="utf-8")
    session = CSVQLSession.from_config(project_root)

    result_path = session.export(
        "queries/count_orders.sql",
        "output/count-orders.csv",
        format="csv",
        force=True,
    )

    assert result_path == output_path.resolve()
    assert output_path.read_bytes() == b"order_count\r\n2\r\n"


@pytest.mark.parametrize(
    ("export_format", "suffix"),
    [
        (ExportFormat.csv, "csv"),
        (ExportFormat.json, "json"),
        (ExportFormat.markdown, "md"),
        (ExportFormat.text, "txt"),
    ],
)
def test_session_export_keeps_all_rows_beyond_interactive_default(
    tmp_path: Path,
    export_format: ExportFormat,
    suffix: str,
) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    query_path = project_root / "queries" / "all_rows.sql"
    query_path.write_text(
        "SELECT range AS row_id FROM range(1005)",
        encoding="utf-8",
    )
    session = CSVQLSession.from_config(project_root)

    output_path = session.export(
        "queries/all_rows.sql",
        f"output/all-rows.{suffix}",
        format=export_format,
    )

    if export_format is ExportFormat.csv:
        with output_path.open(newline="", encoding="utf-8") as output:
            exported_rows = list(csv.reader(output))
        assert len(exported_rows) == 1_006
        assert exported_rows[-1] == ["1004"]
    elif export_format is ExportFormat.json:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload["row_count"] == 1_005
        assert payload["rows"][-1] == {"row_id": 1_004}
    elif export_format is ExportFormat.markdown:
        lines = output_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1_007
        assert lines[-1] == "| 1004 |"
    else:
        text = output_path.read_text(encoding="utf-8")
        assert "1005 row(s)" in text
        assert "1004" in text

    materialized = session.run_file("queries/all_rows.sql")
    assert materialized.row_count == 1_005
    assert materialized.rows[-1] == (1_004,)


def test_session_text_export_cancellation_cleans_row_stage_before_engine_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)
    output_path = project_root / "output" / "cancelled.txt"
    events: list[str] = []
    operation_holder: list[object] = []

    class FakeStream:
        columns = ("value",)
        elapsed_ms = 1.0

        def fetch_rows(self, max_rows: int) -> ResultBatch:
            assert max_rows == 256
            events.append("fetch")
            operation = operation_holder[0]
            operation.token.cancel()
            return ResultBatch(rows=((1,),), exhausted=False)

        def request_interrupt(self) -> None:
            events.append("interrupt")

        def close(self) -> None:
            events.append("cursor.close")

    class FakeEngine:
        def __init__(self, *, operation: object) -> None:
            operation_holder.append(operation)

        def __enter__(self) -> "FakeEngine":
            return self

        def __exit__(self, *exc_info: object) -> None:
            assert not list(output_path.parent.glob(".cancelled.txt.*.stream.tmp"))
            events.extend(
                [
                    "row-stage.rollback",
                    "binding.second.close",
                    "binding.first.close",
                    "connection.close",
                ]
            )

    monkeypatch.setattr(api_module, "CSVQLEngine", FakeEngine)
    monkeypatch.setattr(
        api_module,
        "execute_query_request_stream",
        lambda *args, **kwargs: FakeStream(),
    )

    with pytest.raises(OperationCancelled) as exc_info:
        session.export(
            "queries/count_orders.sql",
            "output/cancelled.txt",
            format=ExportFormat.text,
        )

    assert str(exc_info.value) == "Operation cancelled."
    assert events == [
        "fetch",
        "interrupt",
        "cursor.close",
        "row-stage.rollback",
        "binding.second.close",
        "binding.first.close",
        "connection.close",
    ]
    assert not output_path.exists()
    assert not list(output_path.parent.glob(".cancelled.txt.*"))


def test_session_export_rejects_unknown_format(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(ExportError, match="Unsupported export format"):
        session.export("queries/missing.sql", "output/missing.csv", format="txt")


def test_session_export_anchors_output_to_project_root_from_outside_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    _write_project(project_root)

    monkeypatch.chdir(outside_dir)
    session = CSVQLSession.from_config(project_root)

    output_path = session.export(
        "queries/count_orders.sql",
        "output/from-outside.json",
        format="json",
    )

    assert output_path == (project_root / "output" / "from-outside.json").resolve()
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["columns"] == ["order_count"]
    assert payload["rows"] == [{"order_count": 2}]
    assert payload["row_count"] == 1


def test_session_from_config_propagates_missing_project_error(tmp_path: Path) -> None:
    with pytest.raises(ProjectConfigError):
        CSVQLSession.from_config(tmp_path)


def test_session_query_propagates_query_execution_error(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(QueryExecutionError):
        session.query("SELECT missing_column FROM orders")


def test_session_run_file_propagates_missing_sql_file_error(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(SQLFileError):
        session.run_file("queries/missing.sql")


def test_session_alias_methods_propagate_invalid_table_alias_error(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    with pytest.raises(ProjectConfigError):
        session.inspect("missing")
    with pytest.raises(ProjectConfigError):
        session.sample("missing")
    with pytest.raises(ProjectConfigError):
        session.profile("missing")


def test_session_check_returns_failed_result_without_raising(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root, rows="ORD-001,paid\n,pending\n")
    session = CSVQLSession.from_config(project_root)

    result = session.check(show_failures=True, failure_limit=1)

    assert isinstance(result, CheckRunResult)
    assert result.status == "failed"
    assert result.check_count == 1
    assert result.failed_count == 1
    assert result.checks[0].failed_count == 1
    assert len(result.checks[0].failures) == 1
