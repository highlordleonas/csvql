"""Format-neutral engine-session and source-registration tests."""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import duckdb
import pytest

from csvql.engine import CSVQLEngine
from csvql.exceptions import (
    CSVQLError,
    EngineSessionTaintedError,
    QueryExecutionError,
    SourceBindingError,
    SourceError,
)
from csvql.operation import (
    OperationCancelled,
    OperationContext,
    OperationState,
    OperationToken,
)
from csvql.source import PreparedSources, SourcePreparationFailure, build_source_request
from csvql.source_runtime import default_source_components, prepare_source_requests


def _operation() -> OperationContext:
    return OperationContext(OperationToken())


def _register_numbers(engine: CSVQLEngine, *, alias: str = "numbers") -> object:
    def register(connection: object) -> None:
        connection.execute(f"CREATE VIEW {alias} AS SELECT 1 AS value")

    def unregister(connection: object) -> None:
        connection.execute(f"DROP VIEW IF EXISTS {alias}")

    return engine.register_relation(
        alias=alias,
        register=register,
        unregister=unregister,
        operation=engine.operation_context,
    )


def test_engine_session_identity_is_opaque_unique_and_immutable() -> None:
    """Reusing a session identifier would let bindings cross connection ownership."""

    first = CSVQLEngine()
    second = CSVQLEngine()
    try:
        assert first.session_id
        assert second.session_id
        assert first.session_id != second.session_id
        with pytest.raises(AttributeError):
            first.session_id = second.session_id  # type: ignore[misc]
    finally:
        first.close()
        second.close()


def test_engine_disables_duckdb_extension_autoinstall_and_autoload() -> None:
    """Restoring either setting would permit hidden dependency side effects."""

    with CSVQLEngine() as engine:
        result = engine.query(
            """
            SELECT
                current_setting('autoinstall_known_extensions'),
                current_setting('autoload_known_extensions')
            """
        )

    assert result.rows == ((False, False),)


def test_provider_neutral_registration_is_queryable_and_token_owned() -> None:
    """Bypassing registration tokens would let one binding remove another relation."""

    with CSVQLEngine() as engine:
        token = _register_numbers(engine)

        assert engine.registered_aliases == ("numbers",)
        assert engine.query("SELECT value FROM numbers").rows == ((1,),)

        engine.unregister_relation(token, operation=engine.operation_context)
        engine.unregister_relation(token, operation=engine.operation_context)
        assert engine.registered_aliases == ()
        with pytest.raises(QueryExecutionError):
            engine.query("SELECT * FROM numbers")


def test_alias_preflight_rejects_batch_and_session_collisions_before_callback() -> None:
    """Late alias rejection could let a provider partially replace live state."""

    events: list[str] = []
    with CSVQLEngine() as engine:
        _register_numbers(engine, alias="Orders")

        with pytest.raises(SourceBindingError):
            engine.preflight_aliases(("customers", "Customers"))
        with pytest.raises(SourceBindingError):
            engine.preflight_aliases(("orders",))
        with pytest.raises(SourceBindingError):
            engine.register_relation(
                alias="orders",
                register=lambda connection: events.append("register"),
                unregister=lambda connection: events.append("unregister"),
                operation=engine.operation_context,
            )

    assert events == []


def test_registration_token_cannot_cross_engine_sessions() -> None:
    """Cross-session cleanup would corrupt another DuckDB connection."""

    with CSVQLEngine() as owner, CSVQLEngine() as other:
        token = _register_numbers(owner)

        with pytest.raises(SourceBindingError) as error:
            other.unregister_relation(token, operation=other.operation_context)

        assert error.value.code == "source_bind_failed"
        assert owner.query("SELECT * FROM numbers").rows == ((1,),)


def test_unregister_waits_for_active_execution_terminal_barrier() -> None:
    """Dropping a relation while its result stream is live is unsafe."""

    with CSVQLEngine() as engine:
        token = _register_numbers(engine)
        stream = engine.stream("SELECT * FROM numbers")
        assert engine.has_active_execution

        with pytest.raises(SourceBindingError) as error:
            engine.unregister_relation(token, operation=engine.operation_context)

        assert error.value.code == "source_bind_failed"
        stream.close()
        assert not engine.has_active_execution
        engine.unregister_relation(token, operation=engine.operation_context)


def test_result_stream_owns_the_operation_terminal_barrier() -> None:
    """Binding cleanup must not run before the engine marks execution terminal."""

    operation = _operation()
    with CSVQLEngine(operation=operation) as engine:
        stream = engine.stream("SELECT 1")
        assert operation.state is OperationState.EXECUTING

        stream.close()

        assert operation.state is OperationState.TERMINAL
        assert operation.await_terminal(timeout=0)


def test_engine_rejects_cross_thread_session_use() -> None:
    """A binding must not silently move a DuckDB session across threads."""

    engine = CSVQLEngine()
    failures: list[BaseException] = []

    def use_engine() -> None:
        try:
            engine.preflight_aliases(("orders",))
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=use_engine)
    thread.start()
    thread.join(timeout=2)
    try:
        assert len(failures) == 1
        assert isinstance(failures[0], SourceError)
    finally:
        engine.close()


def test_tainted_engine_rejects_structural_work_with_a_typed_failure() -> None:
    """Structural callers need to distinguish taint from ordinary bind defects."""

    with CSVQLEngine() as engine:
        engine._mark_tainted()

        with pytest.raises(EngineSessionTaintedError) as error:
            engine.register_relation(
                alias="orders",
                register=lambda connection: None,
                unregister=lambda connection: None,
                operation=engine.operation_context,
            )

    assert error.value.code == "engine_session_tainted"


def test_engine_source_core_has_no_detection_factory_or_provider_imports() -> None:
    """Engine source changes must remain independent from format selection."""

    module_path = Path(__file__).resolve().parents[1] / "src" / "csvql" / "engine.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )

    assert "csvql.csv_adapter" not in imported_modules
    assert "csvql.source_detection" not in imported_modules
    assert "csvql.source_registry" not in imported_modules
    assert "csvql.adapter_factory" not in imported_modules


def test_engine_rejects_second_active_stream_and_close_is_terminal() -> None:
    """Two live cursors or post-close reconnects would break lifecycle ownership."""

    engine = CSVQLEngine()
    stream = engine.stream("SELECT 1")
    with pytest.raises(QueryExecutionError, match="active"):
        engine.stream("SELECT 2")
    stream.close()
    engine.close()
    engine.close()

    with pytest.raises(CSVQLError, match="closed"):
        engine.preflight_aliases(("orders",))


@pytest.mark.parametrize(
    "table_order", (("csv_rows", "parquet_rows"), ("parquet_rows", "csv_rows"))
)
def test_engine_joins_csv_and_parquet_without_format_branches(
    tmp_path: Path,
    table_order: tuple[str, str],
) -> None:
    """Cross-format joins must be ordinary engine-owned relational operations."""

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("id,value\n1,alpha\n2,beta\n", encoding="utf-8")
    parquet_path = tmp_path / "scores.parquet"
    connection = duckdb.connect(database=":memory:")
    try:
        connection.sql(
            """
            SELECT *
            FROM (VALUES (1, 10), (2, 20), (3, 30))
                AS rows(id, score)
            """
        ).write_parquet(str(parquet_path))
    finally:
        connection.close()
    requests = (
        build_source_request(
            alias="csv_rows",
            locator=csv_path.name,
            anchor=csv_path.parent,
        ),
        build_source_request(
            alias="parquet_rows",
            locator=parquet_path.name,
            anchor=parquet_path.parent,
        ),
    )
    if table_order[0] == "parquet_rows":
        requests = tuple(reversed(requests))

    with CSVQLEngine() as engine:
        prepared = prepare_source_requests(
            requests,
            engine_session=engine,
            operation=engine.operation_context,
        )
        assert isinstance(prepared, PreparedSources)
        assert not isinstance(prepared, SourcePreparationFailure)
        result = engine.query(
            """
            SELECT csv_rows.id, csv_rows.value, parquet_rows.score
            FROM csv_rows
            JOIN parquet_rows USING (id)
            ORDER BY csv_rows.id
            """
        )

    assert result.rows == ((1, "alpha", 10), (2, "beta", 20))


def test_long_parquet_scan_can_be_cancelled_and_cleaned_up(tmp_path: Path) -> None:
    """Parquet execution must retain the engine's interrupt and terminal barriers."""

    parquet_path = tmp_path / "numbers.parquet"
    connection = duckdb.connect(database=":memory:")
    try:
        connection.sql("SELECT range::INTEGER AS id FROM range(250000)").write_parquet(
            str(parquet_path)
        )
    finally:
        connection.close()
    request = build_source_request(
        alias="numbers",
        locator=parquet_path.name,
        anchor=parquet_path.parent,
    )
    operation = _operation()
    with CSVQLEngine(operation=operation) as engine:
        prepared = prepare_source_requests(
            (request,),
            engine_session=engine,
            operation=operation,
        )
        assert isinstance(prepared, PreparedSources)
        cancellation_failures: list[str] = []

        def cancel_during_execution() -> None:
            deadline = time.monotonic() + 2
            while operation.state is not OperationState.EXECUTING:
                if time.monotonic() >= deadline:
                    cancellation_failures.append("execution did not start")
                    return
                time.sleep(0.001)
            engine.interrupt()

        canceller = threading.Thread(target=cancel_during_execution)
        canceller.start()
        with pytest.raises(OperationCancelled):
            engine.query(
                """
                SELECT sum(a.id::HUGEINT * b.id::HUGEINT)
                FROM numbers AS a
                CROSS JOIN numbers AS b
                """
            )
        canceller.join(timeout=2)

        assert not canceller.is_alive()
        assert cancellation_failures == []
        assert operation.state is OperationState.TERMINAL
        assert default_source_components().coordinator.release(prepared).succeeded
