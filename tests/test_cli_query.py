import json
from pathlib import Path

import pytest
from rich.text import Text
from typer.main import get_command
from typer.testing import CliRunner

import csvql.cli as cli_module
from csvql.bounded_result import BoundedQueryResult, PreviewPolicy
from csvql.cli import app
from csvql.exceptions import CSVQLError
from csvql.models import QueryResult

runner = CliRunner()


def _write_csv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    return tmp_path


def test_query_multiple_tables_as_json(tmp_path: Path) -> None:
    customers = tmp_path / "customers.csv"
    customers.write_text(
        "customer_id,email\nCUST-001,alex@example.com\nCUST-002,blair@example.com\n",
        encoding="utf-8",
    )
    orders = tmp_path / "orders.csv"
    orders.write_text(
        "order_id,customer_id,total_amount\nORD-001,CUST-001,120.50\nORD-002,CUST-001,80.00\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            f"customers={customers}",
            "--table",
            f"orders={orders}",
            "--output",
            "json",
            (
                "SELECT c.email, SUM(o.total_amount) AS revenue "
                "FROM customers c JOIN orders o USING (customer_id) "
                "GROUP BY c.email"
            ),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["columns"] == ["email", "revenue"]
    assert payload["row_count"] == 1
    assert payload["rows"][0]["email"] == "alex@example.com"
    assert payload["rows"][0]["revenue"] == 200.5


def test_query_json_contract_includes_query_result_fields(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text(
        "order_id,total_amount\nORD-001,20.00\nORD-002,10.00\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            f"orders={orders}",
            "--output",
            "json",
            "SELECT COUNT(*) AS order_count FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert list(payload) == ["columns", "elapsed_ms", "row_count", "rows"]
    assert payload["columns"] == ["order_count"]
    assert payload["rows"] == [{"order_count": 2}]
    assert payload["row_count"] == 1
    assert isinstance(payload["elapsed_ms"], float)


def test_query_explicit_table_mapping_resolves_relative_path_from_invocation_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invocation_dir = tmp_path / "invocation"
    orders = invocation_dir / "data" / "orders.csv"
    _write_csv(orders, "order_id,total_amount\nORD-001,20.00\n")
    monkeypatch.chdir(invocation_dir)

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            "orders=data/orders.csv",
            "--output",
            "json",
            "SELECT order_id, total_amount FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [{"order_id": "ORD-001", "total_amount": 20.0}]


def test_query_inline_sql_uses_catalog_tables_from_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _create_catalog(tmp_path, monkeypatch)
    orders = project_root / "data" / "orders.csv"
    _write_csv(
        orders,
        "order_id,status,total_amount\nORD-001,paid,120.50\nORD-002,pending,80.00\n",
    )
    result = runner.invoke(
        app,
        [
            "add",
            "orders",
            "data/orders.csv",
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "query",
            "--output",
            "json",
            "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status ORDER BY status",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["columns"] == ["status", "order_count"]
    assert payload["row_count"] == 2
    assert payload["rows"] == [
        {"status": "paid", "order_count": 1},
        {"status": "pending", "order_count": 1},
    ]


def test_query_inline_sql_uses_catalog_tables_from_subdirectory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _create_catalog(tmp_path, monkeypatch)
    nested_dir = project_root / "nested" / "child"
    nested_dir.mkdir(parents=True)
    orders = project_root / "data" / "orders.csv"
    _write_csv(
        orders,
        "order_id,status,total_amount\nORD-001,paid,120.50\nORD-002,pending,80.00\n",
    )
    result = runner.invoke(app, ["add", "orders", "data/orders.csv"])
    assert result.exit_code == 0, result.output

    monkeypatch.chdir(nested_dir)
    result = runner.invoke(
        app,
        [
            "query",
            "--output",
            "json",
            "SELECT COUNT(*) AS order_count FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == 1
    assert payload["rows"][0]["order_count"] == 2


def test_query_inline_sql_explicit_table_overrides_catalog_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _create_catalog(tmp_path, monkeypatch)
    catalog_orders = project_root / "data" / "catalog_orders.csv"
    explicit_orders = project_root / "data" / "explicit_orders.csv"
    _write_csv(
        catalog_orders,
        "order_id,total_amount\nORD-001,10.00\n",
    )
    _write_csv(
        explicit_orders,
        "order_id,total_amount\nORD-001,20.00\n",
    )
    result = runner.invoke(app, ["add", "orders", "data/catalog_orders.csv"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            "orders=data/explicit_orders.csv",
            "--output",
            "json",
            "SELECT SUM(total_amount) AS total_amount FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == 1
    assert payload["rows"][0]["total_amount"] == 20.0


def test_query_inline_sql_explicit_table_still_uses_referenced_catalog_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _create_catalog(tmp_path, monkeypatch)
    catalog_orders = project_root / "data" / "catalog_orders.csv"
    explicit_orders = project_root / "data" / "explicit_orders.csv"
    customers = project_root / "data" / "customers.csv"
    _write_csv(
        catalog_orders,
        "order_id,customer_id,total_amount\nORD-001,CUST-001,10.00\n",
    )
    _write_csv(
        explicit_orders,
        "order_id,customer_id,total_amount\nORD-001,CUST-001,20.00\n",
    )
    _write_csv(customers, "customer_id,email\nCUST-001,alex@example.com\n")
    assert runner.invoke(app, ["add", "orders", "data/catalog_orders.csv"]).exit_code == 0
    assert runner.invoke(app, ["add", "customers", "data/customers.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            "orders=data/explicit_orders.csv",
            "--output",
            "json",
            (
                "SELECT c.email, SUM(o.total_amount) AS total_amount "
                "FROM orders o JOIN customers c USING (customer_id) "
                "GROUP BY c.email"
            ),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == 1
    assert payload["rows"][0] == {"email": "alex@example.com", "total_amount": 20.0}


def test_query_inline_sql_explicit_table_uses_catalog_alias_case_insensitively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _create_catalog(tmp_path, monkeypatch)
    explicit_orders = project_root / "data" / "orders.csv"
    customers = project_root / "data" / "customers.csv"
    _write_csv(
        explicit_orders,
        "order_id,customer_id,total_amount\nORD-001,CUST-001,20.00\n",
    )
    _write_csv(customers, "customer_id,email\nCUST-001,alex@example.com\n")
    assert runner.invoke(app, ["add", "Customers", "data/customers.csv"]).exit_code == 0

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            "orders=data/orders.csv",
            "--output",
            "json",
            (
                "SELECT c.email, SUM(o.total_amount) AS total_amount "
                "FROM orders o JOIN customers c USING (customer_id) "
                "GROUP BY c.email"
            ),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == 1
    assert payload["rows"][0] == {"email": "alex@example.com", "total_amount": 20.0}


def test_query_inline_sql_explicit_table_ignores_missing_catalog_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / ".csvql.yml"
    config_path.write_text(
        "version: 1\ntables:\n  orders:\n    path: missing.csv\n",
        encoding="utf-8",
    )
    explicit_orders = tmp_path / "good.csv"
    _write_csv(
        explicit_orders,
        "order_id,total_amount\nORD-001,20.00\n",
    )

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            f"orders={explicit_orders}",
            "--output",
            "json",
            "SELECT SUM(total_amount) AS total_amount FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == 1
    assert payload["rows"][0]["total_amount"] == 20.0


def test_query_inline_sql_explicit_table_ignores_unrelated_missing_catalog_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / ".csvql.yml"
    config_path.write_text(
        "version: 1\ntables:\n  customers:\n    path: missing_customers.csv\n",
        encoding="utf-8",
    )
    explicit_orders = tmp_path / "orders.csv"
    _write_csv(
        explicit_orders,
        "order_id,total_amount\nORD-001,20.00\n",
    )

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            f"orders={explicit_orders}",
            "--output",
            "json",
            "SELECT SUM(total_amount) AS total_amount FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == 1
    assert payload["rows"][0]["total_amount"] == 20.0


def test_query_inline_sql_explicit_table_selected_missing_catalog_table_returns_public_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / ".csvql.yml"
    config_path.write_text(
        "version: 1\ntables:\n  customers:\n    path: private/location/missing_customers.csv\n",
        encoding="utf-8",
    )
    explicit_orders = tmp_path / "orders.csv"
    _write_csv(
        explicit_orders,
        "order_id,customer_id,total_amount\nORD-001,CUST-001,20.00\n",
    )

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            f"orders={explicit_orders}",
            "--output",
            "json",
            (
                "SELECT c.email, SUM(o.total_amount) AS total_amount "
                "FROM orders o JOIN customers c USING (customer_id) "
                "GROUP BY c.email"
            ),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 4
    payload = json.loads(result.output)
    assert payload["message"] == (
        "CSV file not found for project catalog table 'customers': "
        "private/location/missing_customers.csv"
    )
    assert payload["suggestion"] == (
        "Update .csvql.yml, run csvql add customers <path> --replace, or restore the CSV file."
    )
    assert payload["diagnostic"]["code"] == "source.locator_shape_invalid"
    assert payload["diagnostic"]["required_action"]["kind"] == "correct_locator"
    assert "SourceError" not in result.output
    assert "Traceback" not in result.output


def test_query_inline_sql_deleted_catalog_fallback_returns_public_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / ".csvql.yml"
    config_path.write_text(
        "version: 1\ntables:\n  customers:\n    path: customers.csv\n",
        encoding="utf-8",
    )
    explicit_orders = tmp_path / "orders.csv"
    customers = tmp_path / "customers.csv"
    _write_csv(
        explicit_orders,
        "order_id,customer_id,total_amount\nORD-001,CUST-001,20.00\n",
    )
    _write_csv(
        customers,
        "customer_id,email\nCUST-001,alex@example.com\n",
    )
    real_build_inline_query_request = cli_module.build_inline_query_request

    def build_then_delete(*args: object, **kwargs: object) -> object:
        request = real_build_inline_query_request(*args, **kwargs)
        customers.unlink()
        return request

    monkeypatch.setattr(cli_module, "build_inline_query_request", build_then_delete)

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            f"orders={explicit_orders}",
            "--output",
            "json",
            (
                "SELECT c.email, SUM(o.total_amount) AS total_amount "
                "FROM orders o JOIN customers c USING (customer_id) "
                "GROUP BY c.email"
            ),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 4
    payload = json.loads(result.output)
    assert payload == {
        "message": "CSV file not found for project catalog table 'customers': customers.csv",
        "suggestion": (
            "Update .csvql.yml, run csvql add customers <path> --replace, or restore the CSV file."
        ),
    }
    assert "SourceError" not in result.output
    assert "Traceback" not in result.output


def test_query_inline_sql_explicit_table_ignores_malformed_catalog_when_unused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / ".csvql.yml"
    config_path.write_text("version: [1\n", encoding="utf-8")
    explicit_orders = tmp_path / "orders.csv"
    _write_csv(
        explicit_orders,
        "order_id,total_amount\nORD-001,20.00\n",
    )

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            f"orders={explicit_orders}",
            "--output",
            "json",
            "SELECT SUM(total_amount) AS total_amount FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == 1
    assert payload["rows"][0]["total_amount"] == 20.0


def test_query_inline_sql_explicit_table_ignores_catalog_name_in_string_literal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / ".csvql.yml"
    config_path.write_text(
        "version: 1\ntables:\n  customers:\n    path: missing_customers.csv\n",
        encoding="utf-8",
    )
    explicit_orders = tmp_path / "orders.csv"
    _write_csv(
        explicit_orders,
        "order_id,total_amount\nORD-001,20.00\n",
    )

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            f"orders={explicit_orders}",
            "--output",
            "json",
            "SELECT 'customers' AS label, SUM(total_amount) AS total_amount FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == 1
    assert payload["rows"][0] == {"label": "customers", "total_amount": 20.0}


def test_query_inline_sql_explicit_table_succeeds_without_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    orders = tmp_path / "orders.csv"
    _write_csv(
        orders,
        "order_id,status,total_amount\nORD-001,paid,120.50\nORD-002,pending,80.00\n",
    )

    result = runner.invoke(
        app,
        [
            "query",
            "--table",
            f"orders={orders}",
            "--output",
            "json",
            "SELECT COUNT(*) AS order_count FROM orders",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == 1
    assert payload["rows"][0]["order_count"] == 2


def test_query_inline_sql_without_catalog_returns_project_config_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["query", "SELECT 1"], catch_exceptions=False)

    assert result.exit_code == 8
    assert "No .csvql.yml project catalog found" in result.output
    assert "Run project init/add or pass --table mappings explicitly." in result.output


def test_query_single_file_shortcut_outputs_table(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text(
        "order_id,status,total_amount\nORD-001,paid,120.50\nORD-002,pending,80.00\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "query",
            str(orders),
            "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status ORDER BY status",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "paid" in result.output
    assert "pending" in result.output
    assert "2 row(s)" in result.output


def test_query_single_file_shortcut_accepts_leading_underscore_filename(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "__localql_orders.csv"
    orders.write_text(
        "order_id,status,total_amount\nORD-001,paid,120.50\nORD-002,pending,80.00\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "query",
            str(orders),
            (
                "SELECT status, COUNT(*) AS order_count "
                "FROM localql_orders GROUP BY status ORDER BY status"
            ),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "paid" in result.output


def test_query_cli_uses_one_operation_context_for_builder_engine_and_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    seen: dict[str, object] = {}

    class FakeEngine:
        def __init__(self, *, operation: object) -> None:
            seen["engine"] = operation

        def __enter__(self) -> "FakeEngine":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    def fake_build_inline_query_request(
        sql_or_csv: str,
        sql: str | None,
        table: list[str],
        *,
        base_dir: Path | None = None,
        operation: object,
    ) -> object:
        assert sql_or_csv == "SELECT 1 AS one"
        assert sql is None
        assert table == []
        assert base_dir == tmp_path
        seen["builder"] = operation
        return object()

    def fake_execute_query_request(
        engine: object,
        request: object,
        *,
        operation: object,
    ) -> QueryResult:
        seen["executor"] = operation
        assert engine is not None
        assert request is not None
        return QueryResult(columns=("one",), rows=((1,),), elapsed_ms=1.0)

    monkeypatch.setattr("csvql.cli.CSVQLEngine", FakeEngine)
    monkeypatch.setattr("csvql.cli.build_inline_query_request", fake_build_inline_query_request)
    monkeypatch.setattr("csvql.cli.execute_query_request", fake_execute_query_request)

    result = runner.invoke(app, ["query", "--output", "json", "SELECT 1 AS one"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [{"one": 1}]
    assert seen["builder"] is seen["engine"] is seen["executor"]


def test_query_single_file_shortcut_rejects_table_mappings(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    other = tmp_path / "other.csv"
    orders.write_text(
        "order_id,status,total_amount\nORD-001,paid,120.50\nORD-002,pending,80.00\n",
        encoding="utf-8",
    )
    other.write_text("id,value\n1,2\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "query",
            str(orders),
            "SELECT status FROM orders",
            "--table",
            f"something={other}",
        ],
    )

    assert result.exit_code == 6
    assert "Single-file shortcut mode cannot be combined with --table mappings" in result.output


def test_query_table_output_uses_default_preview_limit_when_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    seen: dict[str, object] = {}

    class FakeEngine:
        def __init__(self, *, operation: object) -> None:
            seen["engine_operation"] = operation

        def __enter__(self) -> "FakeEngine":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    class FakeStream:
        columns = ("value",)
        elapsed_ms = 4.0

    def fake_build_inline_query_request(*args: object, **kwargs: object) -> object:
        seen["build_operation"] = kwargs["operation"]
        return object()

    def fake_execute_query_request_stream(
        engine: object,
        request: object,
        *,
        operation: object,
    ) -> FakeStream:
        seen["stream_operation"] = operation
        seen["request"] = request
        return FakeStream()

    def fake_collect_bounded_preview(
        stream: object,
        *,
        policy: PreviewPolicy,
        fetch_batch_size: int = 256,
    ) -> BoundedQueryResult:
        seen["stream"] = stream
        seen["policy"] = policy
        seen["fetch_batch_size"] = fetch_batch_size
        return BoundedQueryResult(
            columns=("value",),
            rows=((1,), (2,)),
            elapsed_ms=4.0,
            preview_payload_bytes=8,
            has_more_rows=False,
            truncation_reason=None,
        )

    monkeypatch.setattr("csvql.cli.CSVQLEngine", FakeEngine)
    monkeypatch.setattr("csvql.cli.build_inline_query_request", fake_build_inline_query_request)
    monkeypatch.setattr(
        "csvql.cli.execute_query_request_stream",
        fake_execute_query_request_stream,
    )
    monkeypatch.setattr("csvql.cli.collect_bounded_preview", fake_collect_bounded_preview)

    result = runner.invoke(app, ["query", "SELECT 1 AS value"])

    assert result.exit_code == 0, result.output
    assert "2 row(s) in 4.00 ms" in result.output
    assert "more rows exist" not in result.output
    assert seen["engine_operation"] is seen["build_operation"] is seen["stream_operation"]
    assert seen["stream"] is not None
    assert seen["request"] is not None
    assert seen["policy"] == PreviewPolicy(row_limit=1_000)
    assert seen["fetch_batch_size"] == 256


def test_query_table_output_uses_explicit_preview_limit_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    seen: dict[str, object] = {}

    class FakeEngine:
        def __init__(self, *, operation: object) -> None:
            seen["operation"] = operation

        def __enter__(self) -> "FakeEngine":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    class FakeStream:
        columns = ("value",)
        elapsed_ms = 5.0

    def fake_collect_bounded_preview(
        stream: object,
        *,
        policy: PreviewPolicy,
        fetch_batch_size: int = 256,
    ) -> BoundedQueryResult:
        seen["policy"] = policy
        return BoundedQueryResult(
            columns=("value",),
            rows=((1,), (2,)),
            elapsed_ms=5.0,
            preview_payload_bytes=16,
            has_more_rows=True,
            truncation_reason="row_limit",
        )

    monkeypatch.setattr("csvql.cli.CSVQLEngine", FakeEngine)
    monkeypatch.setattr("csvql.cli.build_inline_query_request", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        "csvql.cli.execute_query_request_stream",
        lambda *args, **kwargs: FakeStream(),
    )
    monkeypatch.setattr("csvql.cli.collect_bounded_preview", fake_collect_bounded_preview)

    result = runner.invoke(app, ["query", "--limit", "7", "SELECT 1 AS value"])

    assert result.exit_code == 0, result.output
    assert "more rows exist" in result.output
    assert "2-row limit" in result.output
    assert seen["policy"] == PreviewPolicy(row_limit=7)


@pytest.mark.parametrize("bad_limit", ["0", "-1"])
def test_query_limit_rejects_non_positive_values_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_limit: str,
) -> None:
    monkeypatch.chdir(tmp_path)

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("CLI should reject invalid --limit before execution.")

    monkeypatch.setattr("csvql.cli.CSVQLEngine", fail)
    monkeypatch.setattr("csvql.cli.build_inline_query_request", fail)

    result = runner.invoke(app, ["query", "--limit", bad_limit, "SELECT 1 AS value"])

    assert result.exit_code != 0
    assert "--limit" in Text.from_ansi(result.output).plain


def test_query_json_limit_rejects_before_request_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("JSON + --limit must fail before request construction.")

    monkeypatch.setattr("csvql.cli.build_inline_query_request", fail)
    monkeypatch.setattr("csvql.cli.CSVQLEngine", fail)

    result = runner.invoke(
        app,
        ["query", "--output", "json", "--limit", "3", "SELECT 1 AS value"],
        catch_exceptions=False,
    )

    assert result.exit_code == CSVQLError.exit_code
    assert "JSON output remains" in result.output
    assert "complete in v1.1" in result.output
    assert "--limit" in result.output
    assert "Traceback" not in result.output


def test_query_json_without_limit_keeps_full_materialization_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    seen: dict[str, object] = {}

    class FakeEngine:
        def __init__(self, *, operation: object) -> None:
            seen["operation"] = operation

        def __enter__(self) -> "FakeEngine":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    def fake_build_inline_query_request(*args: object, **kwargs: object) -> object:
        seen["build_operation"] = kwargs["operation"]
        return object()

    def fake_execute_query_request(
        engine: object,
        request: object,
        *,
        operation: object,
    ) -> QueryResult:
        seen["execute_operation"] = operation
        return QueryResult(columns=("value",), rows=((1,), (2,)), elapsed_ms=1.0)

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("JSON without --limit must not use preview streaming.")

    monkeypatch.setattr("csvql.cli.CSVQLEngine", FakeEngine)
    monkeypatch.setattr("csvql.cli.build_inline_query_request", fake_build_inline_query_request)
    monkeypatch.setattr("csvql.cli.execute_query_request", fake_execute_query_request)
    monkeypatch.setattr("csvql.cli.execute_query_request_stream", fail)
    monkeypatch.setattr("csvql.cli.collect_bounded_preview", fail)

    result = runner.invoke(app, ["query", "--output", "json", "SELECT 1 AS value"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["rows"] == [{"value": 1}, {"value": 2}]
    assert seen["operation"] is seen["build_operation"] is seen["execute_operation"]


def test_query_table_keyboard_interrupt_closes_engine_and_reports_public_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
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
        columns = ("value",)
        elapsed_ms = 0.0

        def fetch_rows(self, max_rows: int) -> object:
            events.append("fetch")
            raise KeyboardInterrupt()

        def close(self) -> None:
            events.append("stream.close")

        def request_interrupt(self) -> None:
            events.append("stream.interrupt")

    monkeypatch.setattr("csvql.cli.CSVQLEngine", FakeEngine)
    monkeypatch.setattr("csvql.cli.build_inline_query_request", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        "csvql.cli.execute_query_request_stream",
        lambda *args, **kwargs: FakeStream(),
    )

    result = runner.invoke(app, ["query", "SELECT 1 AS value"], catch_exceptions=False)

    assert result.exit_code == CSVQLError.exit_code
    assert events == ["init", "enter", "fetch", "stream.close", "exit"]
    assert "Traceback" not in result.output
    assert "Cleanup uncertainty" not in result.output


def test_query_help_describes_limit_as_table_output_only() -> None:
    result = runner.invoke(app, ["query", "--help"], terminal_width=200)
    output = " ".join(Text.from_ansi(result.output).plain.split())
    command = get_command(app).commands["query"]
    limit_help = next(parameter.help for parameter in command.params if parameter.name == "limit")

    assert result.exit_code == 0, result.output
    assert "local source locator" in output
    assert "CSV compatibility mapping in" in output
    assert "NAME=PATH" in output
    assert "use --source" in output
    assert "other providers" in output
    assert "Maximum rows to display" in output
    assert "display in table" in output
    assert limit_help == "Maximum rows to display; display in table output only."
