import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql.bounded_result import BoundedQueryResult, PreviewPolicy
from csvql.cli import app
from csvql.exceptions import CSVQLError
from csvql.models import QueryResult

runner = CliRunner()


def _write_csv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output


def test_run_sql_file_uses_catalog_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\nORD-002,10.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(app, ["run", "queries/count_orders.sql", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [{"order_count": 2}]


def test_run_json_contract_matches_query_result_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\nORD-002,10.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(app, ["run", "queries/count_orders.sql", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert list(payload) == ["columns", "elapsed_ms", "row_count", "rows"]
    assert payload["columns"] == ["order_count"]
    assert payload["rows"] == [{"order_count": 2}]
    assert payload["row_count"] == 1
    assert isinstance(payload["elapsed_ms"], float)


def test_run_sql_file_with_explicit_table_works_without_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "orders.csv"
    query = tmp_path / "count_orders.sql"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "count_orders.sql",
            "--table",
            "orders=orders.csv",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [{"order_count": 1}]


def test_run_sql_file_rejects_empty_sql_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    query = tmp_path / "empty.sql"
    query.write_text("   \n", encoding="utf-8")

    result = runner.invoke(app, ["run", "empty.sql"])

    assert result.exit_code == 9
    assert "SQL file is empty" in result.output


def test_export_sql_file_writes_csv(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.csv"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\nORD-002,10.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "queries/count_orders.sql", "--format", "csv", "--out", "result.csv"],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_bytes() == b"order_count\r\n2\r\n"
    assert "Wrote export" in result.output


def test_export_success_output_encodes_terminal_controls_in_output_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "orders.csv"
    query = tmp_path / "count_orders.sql"
    unsafe_output_path = tmp_path / "result\x1b]0;spoof\x07\x7f\x85\x9b31m.csv"
    written_exports: list[tuple[Path, str, bool]] = []
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")

    def fake_resolve_export_path(
        path_value: str,
        *,
        base_dir: Path | None = None,
        force: bool = False,
    ) -> Path:
        assert path_value == "result.csv"
        assert base_dir == tmp_path
        assert force is False
        return unsafe_output_path

    def fake_write_export_file(path: Path, content: str, *, overwrite: bool) -> None:
        written_exports.append((path, content, overwrite))

    monkeypatch.setattr("csvql.cli.resolve_export_path", fake_resolve_export_path)
    monkeypatch.setattr("csvql.cli.write_export_file", fake_write_export_file)

    result = runner.invoke(
        app,
        [
            "export",
            "count_orders.sql",
            "--format",
            "csv",
            "--out",
            "result.csv",
            "--table",
            "orders=orders.csv",
        ],
    )

    assert result.exit_code == 0, result.output
    assert written_exports == [(unsafe_output_path, "order_count\r\n1\r\n", False)]
    assert all(control not in result.output for control in "\x1b\x07\x7f\x85\x9b")
    assert r"result\x1b]0;spoof\x07\x7f\x85\x9b31m.csv" in result.output


def test_export_sql_file_writes_json(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.json"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "queries/count_orders.sql", "--format", "json", "--out", "result.json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["rows"] == [{"order_count": 1}]


def test_export_json_contract_matches_query_result_shape_on_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.json"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "queries/count_orders.sql", "--format", "json", "--out", "result.json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert list(payload) == ["columns", "elapsed_ms", "row_count", "rows"]
    assert payload["columns"] == ["order_count"]
    assert payload["rows"] == [{"order_count": 1}]
    assert payload["row_count"] == 1
    assert isinstance(payload["elapsed_ms"], float)


def test_export_sql_file_writes_markdown(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.md"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        [
            "export",
            "queries/count_orders.sql",
            "--format",
            "markdown",
            "--out",
            "result.md",
        ],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_text(encoding="utf-8") == ("| order_count |\n| --- |\n| 1 |\n")


def test_export_sql_file_writes_text(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "queries" / "count_orders.sql"
    output_path = tmp_path / "result.txt"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.parent.mkdir()
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "queries/count_orders.sql", "--format", "text", "--out", "result.txt"],
    )

    assert result.exit_code == 0, result.output
    content = output_path.read_text(encoding="utf-8")
    assert "order_count" in content
    assert "1 row(s)" in content


def test_export_refuses_overwrite_without_force(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "count_orders.sql"
    output_path = tmp_path / "result.csv"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    output_path.write_text("existing", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "count_orders.sql", "--format", "csv", "--out", "result.csv"],
    )

    assert result.exit_code == 10
    assert "Export output already exists" in result.output
    assert output_path.read_text(encoding="utf-8") == "existing"


def test_export_force_overwrites_existing_file(tmp_path: Path, monkeypatch) -> None:
    _init_catalog(tmp_path, monkeypatch)
    orders = tmp_path / "data" / "orders.csv"
    query = tmp_path / "count_orders.sql"
    output_path = tmp_path / "result.csv"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    query.write_text("SELECT COUNT(*) AS order_count FROM orders", encoding="utf-8")
    output_path.write_text("existing", encoding="utf-8")
    assert runner.invoke(app, ["add", "orders", "data/orders.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        ["export", "count_orders.sql", "--format", "csv", "--out", "result.csv", "--force"],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_bytes() == b"order_count\r\n1\r\n"


def test_run_and_export_cli_use_one_operation_context_across_builder_engine_and_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    sql_file = tmp_path / "count_orders.sql"
    sql_file.write_text("SELECT 1 AS one", encoding="utf-8")
    seen: list[object] = []
    write_calls: list[tuple[Path, str, bool]] = []

    class FakeEngine:
        def __init__(self, *, operation: object) -> None:
            seen.append(operation)

        def __enter__(self) -> "FakeEngine":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    def fake_load_sql_file(path: str, *, base_dir: Path | None = None):
        assert path == "count_orders.sql"
        assert base_dir == tmp_path
        return type("LoadedSQL", (), {"sql": "SELECT 1 AS one"})()

    def fake_build_saved_sql_query_request(
        sql: str,
        table: list[str],
        *,
        base_dir: Path | None = None,
        operation: object,
    ) -> object:
        assert sql == "SELECT 1 AS one"
        assert table == []
        assert base_dir == tmp_path
        seen.append(operation)
        return object()

    def fake_execute_query_request(
        engine: object,
        request: object,
        *,
        operation: object,
    ) -> QueryResult:
        seen.append(operation)
        assert engine is not None
        assert request is not None
        return QueryResult(columns=("one",), rows=((1,),), elapsed_ms=1.0)

    def fake_write_export_file(path: Path, content: str, *, overwrite: bool) -> None:
        write_calls.append((path, content, overwrite))

    monkeypatch.setattr("csvql.cli.CSVQLEngine", FakeEngine)
    monkeypatch.setattr("csvql.cli.load_sql_file", fake_load_sql_file)
    monkeypatch.setattr(
        "csvql.cli.build_saved_sql_query_request",
        fake_build_saved_sql_query_request,
    )
    monkeypatch.setattr("csvql.cli.execute_query_request", fake_execute_query_request)
    monkeypatch.setattr("csvql.cli.write_export_file", fake_write_export_file)

    run_result = runner.invoke(app, ["run", "count_orders.sql", "--output", "json"])
    assert run_result.exit_code == 0, run_result.output
    assert json.loads(run_result.output)["rows"] == [{"one": 1}]
    assert seen[0] is seen[1] is seen[2]

    seen.clear()
    export_result = runner.invoke(
        app,
        ["export", "count_orders.sql", "--format", "json", "--out", "result.json"],
    )
    assert export_result.exit_code == 0, export_result.output
    assert seen[0] is seen[1] is seen[2]
    assert len(write_calls) == 1
    path, content, overwrite = write_calls[0]
    assert path == tmp_path / "result.json"
    assert overwrite is False
    assert json.loads(content) == {
        "columns": ["one"],
        "rows": [{"one": 1}],
        "row_count": 1,
        "elapsed_ms": 1.0,
    }


def test_run_table_output_uses_explicit_preview_limit_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    sql_file = tmp_path / "count_orders.sql"
    sql_file.write_text("SELECT 1 AS one", encoding="utf-8")
    seen: dict[str, object] = {}

    class FakeEngine:
        def __init__(self, *, operation: object) -> None:
            seen["engine_operation"] = operation

        def __enter__(self) -> "FakeEngine":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    class FakeStream:
        columns = ("one",)
        elapsed_ms = 2.0

    monkeypatch.setattr(
        "csvql.cli.load_sql_file",
        lambda path, *, base_dir=None: type("LoadedSQL", (), {"sql": "SELECT 1 AS one"})(),
    )
    monkeypatch.setattr("csvql.cli.CSVQLEngine", FakeEngine)
    monkeypatch.setattr(
        "csvql.cli.build_saved_sql_query_request",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "csvql.cli.execute_query_request_stream",
        lambda *args, **kwargs: FakeStream(),
    )

    def fake_collect_bounded_preview(
        stream: object,
        *,
        policy: PreviewPolicy,
        fetch_batch_size: int = 256,
    ) -> BoundedQueryResult:
        seen["policy"] = policy
        return BoundedQueryResult(
            columns=("one",),
            rows=((1,),),
            elapsed_ms=2.0,
            preview_payload_bytes=8,
            has_more_rows=False,
            truncation_reason=None,
        )

    monkeypatch.setattr("csvql.cli.collect_bounded_preview", fake_collect_bounded_preview)

    result = runner.invoke(app, ["run", "--limit", "9", "count_orders.sql"])

    assert result.exit_code == 0, result.output
    assert "1 row(s) in 2.00 ms" in result.output
    assert seen["policy"] == PreviewPolicy(row_limit=9)


def test_run_table_output_uses_default_preview_limit_when_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    sql_file = tmp_path / "count_orders.sql"
    sql_file.write_text("SELECT 1 AS one", encoding="utf-8")
    seen: dict[str, object] = {}

    class FakeEngine:
        def __init__(self, *, operation: object) -> None:
            seen["engine_operation"] = operation

        def __enter__(self) -> "FakeEngine":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    class FakeStream:
        columns = ("one",)
        elapsed_ms = 6.0

    monkeypatch.setattr(
        "csvql.cli.load_sql_file",
        lambda path, *, base_dir=None: type("LoadedSQL", (), {"sql": "SELECT 1 AS one"})(),
    )
    monkeypatch.setattr("csvql.cli.CSVQLEngine", FakeEngine)
    monkeypatch.setattr(
        "csvql.cli.build_saved_sql_query_request",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "csvql.cli.execute_query_request_stream",
        lambda *args, **kwargs: FakeStream(),
    )

    def fake_collect_bounded_preview(
        stream: object,
        *,
        policy: PreviewPolicy,
        fetch_batch_size: int = 256,
    ) -> BoundedQueryResult:
        seen["policy"] = policy
        return BoundedQueryResult(
            columns=("one",),
            rows=((1,),),
            elapsed_ms=6.0,
            preview_payload_bytes=8,
            has_more_rows=False,
            truncation_reason=None,
        )

    monkeypatch.setattr("csvql.cli.collect_bounded_preview", fake_collect_bounded_preview)

    result = runner.invoke(app, ["run", "count_orders.sql"])

    assert result.exit_code == 0, result.output
    assert "1 row(s) in 6.00 ms" in result.output
    assert seen["policy"] == PreviewPolicy(row_limit=1_000)


@pytest.mark.parametrize("bad_limit", ["0", "-1"])
def test_run_limit_rejects_non_positive_values_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_limit: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    sql_file = tmp_path / "count_orders.sql"
    sql_file.write_text("SELECT 1 AS one", encoding="utf-8")

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("CLI should reject invalid --limit before execution.")

    monkeypatch.setattr("csvql.cli.load_sql_file", fail)
    monkeypatch.setattr("csvql.cli.CSVQLEngine", fail)

    result = runner.invoke(app, ["run", "--limit", bad_limit, "count_orders.sql"])

    assert result.exit_code != 0
    assert "--limit" in result.output


def test_run_json_limit_rejects_before_request_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    sql_file = tmp_path / "count_orders.sql"
    sql_file.write_text("SELECT 1 AS one", encoding="utf-8")

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("JSON + --limit must fail before saved-query request construction.")

    monkeypatch.setattr("csvql.cli.load_sql_file", fail)
    monkeypatch.setattr("csvql.cli.build_saved_sql_query_request", fail)
    monkeypatch.setattr("csvql.cli.CSVQLEngine", fail)

    result = runner.invoke(
        app,
        ["run", "--output", "json", "--limit", "2", "count_orders.sql"],
        catch_exceptions=False,
    )

    assert result.exit_code == CSVQLError.exit_code
    assert "JSON output remains" in result.output
    assert "complete in v1.1" in result.output
    assert "--limit" in result.output
    assert "Traceback" not in result.output


def test_run_json_without_limit_keeps_full_materialization_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    sql_file = tmp_path / "count_orders.sql"
    sql_file.write_text("SELECT 1 AS one", encoding="utf-8")
    seen: dict[str, object] = {}

    class FakeEngine:
        def __init__(self, *, operation: object) -> None:
            seen["operation"] = operation

        def __enter__(self) -> "FakeEngine":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    monkeypatch.setattr(
        "csvql.cli.load_sql_file",
        lambda path, *, base_dir=None: type("LoadedSQL", (), {"sql": "SELECT 1 AS one"})(),
    )
    monkeypatch.setattr("csvql.cli.CSVQLEngine", FakeEngine)

    def fake_build_saved_sql_query_request(
        sql: str,
        table: list[str],
        *,
        base_dir: Path | None = None,
        operation: object,
    ) -> object:
        seen["build_operation"] = operation
        return object()

    def fake_execute_query_request(
        engine: object,
        request: object,
        *,
        operation: object,
    ) -> QueryResult:
        seen["execute_operation"] = operation
        return QueryResult(columns=("one",), rows=((1,), (2,)), elapsed_ms=1.0)

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("JSON without --limit must not use preview streaming.")

    monkeypatch.setattr(
        "csvql.cli.build_saved_sql_query_request",
        fake_build_saved_sql_query_request,
    )
    monkeypatch.setattr("csvql.cli.execute_query_request", fake_execute_query_request)
    monkeypatch.setattr("csvql.cli.execute_query_request_stream", fail)
    monkeypatch.setattr("csvql.cli.collect_bounded_preview", fail)

    result = runner.invoke(app, ["run", "--output", "json", "count_orders.sql"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["rows"] == [{"one": 1}, {"one": 2}]
    assert seen["operation"] is seen["build_operation"] is seen["execute_operation"]


def test_run_table_keyboard_interrupt_closes_engine_and_reports_public_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    sql_file = tmp_path / "count_orders.sql"
    sql_file.write_text("SELECT 1 AS one", encoding="utf-8")
    events: list[str] = []

    class FakeEngine:
        def __init__(self, *, operation: object) -> None:
            events.append("init")

        def __enter__(self) -> "FakeEngine":
            events.append("enter")
            return self

        def __exit__(self, *exc_info: object) -> None:
            events.append("exit")
            return None

    class FakeStream:
        columns = ("one",)
        elapsed_ms = 0.0

        def fetch_rows(self, max_rows: int) -> object:
            events.append("fetch")
            raise KeyboardInterrupt()

        def close(self) -> None:
            events.append("stream.close")

        def request_interrupt(self) -> None:
            events.append("stream.interrupt")

    monkeypatch.setattr(
        "csvql.cli.load_sql_file",
        lambda path, *, base_dir=None: type("LoadedSQL", (), {"sql": "SELECT 1 AS one"})(),
    )
    monkeypatch.setattr("csvql.cli.CSVQLEngine", FakeEngine)
    monkeypatch.setattr(
        "csvql.cli.build_saved_sql_query_request",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "csvql.cli.execute_query_request_stream",
        lambda *args, **kwargs: FakeStream(),
    )

    result = runner.invoke(app, ["run", "count_orders.sql"], catch_exceptions=False)

    assert result.exit_code == CSVQLError.exit_code
    assert events == ["init", "enter", "fetch", "stream.close", "exit"]
    assert "Traceback" not in result.output
    assert "Cleanup uncertainty" not in result.output


def test_run_help_describes_limit_as_table_output_only() -> None:
    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0, result.output
    assert "Maximum rows to display" in result.output
    assert "display in table" in result.output
    assert "output." in result.output


def test_run_table_output_reports_byte_limit_truncation_truthfully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    sql_file = tmp_path / "count_orders.sql"
    sql_file.write_text("SELECT 1 AS one", encoding="utf-8")

    class FakeEngine:
        def __init__(self, *, operation: object) -> None:
            pass

        def __enter__(self) -> "FakeEngine":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    class FakeStream:
        columns = ("one",)
        elapsed_ms = 7.0

    monkeypatch.setattr(
        "csvql.cli.load_sql_file",
        lambda path, *, base_dir=None: type("LoadedSQL", (), {"sql": "SELECT 1 AS one"})(),
    )
    monkeypatch.setattr("csvql.cli.CSVQLEngine", FakeEngine)
    monkeypatch.setattr(
        "csvql.cli.build_saved_sql_query_request",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "csvql.cli.execute_query_request_stream",
        lambda *args, **kwargs: FakeStream(),
    )
    monkeypatch.setattr(
        "csvql.cli.collect_bounded_preview",
        lambda *args, **kwargs: BoundedQueryResult(
            columns=("one",),
            rows=((1,),),
            elapsed_ms=7.0,
            preview_payload_bytes=8,
            has_more_rows=True,
            truncation_reason="byte_limit",
        ),
    )

    result = runner.invoke(app, ["run", "count_orders.sql"])

    assert result.exit_code == 0, result.output
    assert "more rows exist" in result.output
    assert "16 MiB preview payload ceiling" in result.output
