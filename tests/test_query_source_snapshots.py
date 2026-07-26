from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from csvql import query_workflow
from csvql.csv_adapter import CSVSourceAdapter
from csvql.engine import CSVQLEngine
from csvql.exceptions import FileMissingError, QueryExecutionError, SourceError
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.query_workflow import (
    QueryRequest,
    build_inline_query_request,
    build_saved_sql_query_request,
    execute_query_request,
)
from csvql.source import ResolvedSource, SourceSpec


def _write_csv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_catalog(project_root: Path, path: str = "customers.csv") -> None:
    (project_root / ".csvql.yml").write_text(
        f"version: 1\ntables:\n  customers:\n    path: {path}\n",
        encoding="utf-8",
    )


def test_query_snapshot_values_have_the_exact_frozen_shapes(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    _write_csv(orders, "order_id\nORD-001\n")
    request = build_inline_query_request(
        "SELECT * FROM orders",
        None,
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=OperationContext(token=OperationToken()),
    )

    assert [field.name for field in fields(QueryRequest)] == [
        "sql",
        "required_sources",
        "fallback_sources",
    ]
    assert [field.name for field in fields(query_workflow.SourceCandidate)] == [
        "spec",
        "expected_fingerprint",
        "submission_error",
    ]
    with pytest.raises(FrozenInstanceError):
        request.sql = "SELECT 1"  # type: ignore[misc]


@pytest.mark.parametrize("builder", ["inline", "saved"])
def test_explicit_builders_snapshot_required_and_fallback_sources_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    builder: str,
) -> None:
    project_root = tmp_path / "project"
    outside = tmp_path / "outside"
    project_root.mkdir()
    outside.mkdir()
    _write_catalog(project_root)
    orders = project_root / "orders.csv"
    customers = project_root / "customers.csv"
    redirected = project_root / "redirected.csv"
    _write_csv(orders, "id\n1\n")
    _write_csv(customers, "id\n1\n")
    _write_csv(redirected, "id\n999\n")

    operation = OperationContext(token=OperationToken())
    if builder == "inline":
        request = build_inline_query_request(
            "SELECT orders.id FROM orders",
            None,
            ["orders=orders.csv"],
            base_dir=project_root,
            operation=operation,
        )
    else:
        request = build_saved_sql_query_request(
            "SELECT orders.id FROM orders",
            ["orders=orders.csv"],
            base_dir=project_root,
            operation=operation,
        )

    assert request.required_sources[0].canonical_locator == str(orders.resolve())
    assert request.fallback_sources[0].spec.locator == "customers.csv"
    assert request.fallback_sources[0].expected_fingerprint is not None
    (project_root / ".csvql.yml").write_text(
        "version: 1\ntables:\n  customers:\n    path: redirected.csv\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(outside)

    with CSVQLEngine(operation=operation) as engine:
        result = execute_query_request(engine, request, operation=operation)

    assert result.rows == ((1,),)


def test_builder_resolves_each_required_and_fallback_identity_once_at_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_catalog(tmp_path)
    _write_csv(tmp_path / "orders.csv", "id\n1\n")
    _write_csv(tmp_path / "customers.csv", "id\n1\n")
    resolved_aliases: list[str] = []
    original_resolve = CSVSourceAdapter.resolve

    def record_resolve(
        self: CSVSourceAdapter,
        spec: SourceSpec,
        context: OperationContext,
    ) -> ResolvedSource:
        resolved_aliases.append(spec.alias)
        return original_resolve(self, spec, context)

    monkeypatch.setattr(CSVSourceAdapter, "resolve", record_resolve)

    operation = OperationContext(token=OperationToken())
    build_saved_sql_query_request(
        "SELECT * FROM orders",
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=operation,
    )

    assert resolved_aliases == ["orders", "customers"]


def test_explicit_query_ignores_non_utf8_optional_catalog(
    tmp_path: Path,
) -> None:
    (tmp_path / ".csvql.yml").write_bytes(b"\xff\xfe\x00")
    orders = tmp_path / "orders.csv"
    _write_csv(orders, "id\n1\n")

    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "SELECT * FROM orders",
        None,
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=operation,
    )

    assert request.fallback_sources == ()
    with CSVQLEngine(operation=operation) as engine:
        result = execute_query_request(engine, request, operation=operation)
    assert result.rows == ((1,),)


def test_single_file_query_ignores_optional_catalog_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".csvql.yml").write_text(
        "version: 1\ntables: {}\n",
        encoding="utf-8",
    )
    orders = tmp_path / "orders.csv"
    _write_csv(orders, "id\n1\n")
    original_read_text = Path.read_text

    def fail_catalog_read(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        if path.name == ".csvql.yml":
            raise OSError("catalog read denied")
        return original_read_text(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", fail_catalog_read)

    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "orders.csv",
        "SELECT * FROM orders",
        [],
        base_dir=tmp_path,
        operation=operation,
    )

    assert request.fallback_sources == ()
    with CSVQLEngine(operation=operation) as engine:
        result = execute_query_request(engine, request, operation=operation)
    assert result.rows == ((1,),)


def test_catalog_only_query_preserves_non_utf8_catalog_failure(
    tmp_path: Path,
) -> None:
    (tmp_path / ".csvql.yml").write_bytes(b"\xff\xfe\x00")

    with pytest.raises(UnicodeDecodeError):
        build_inline_query_request(
            "SELECT 1",
            None,
            [],
            base_dir=tmp_path,
            operation=OperationContext(token=OperationToken()),
        )


def test_catalog_only_query_preserves_catalog_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".csvql.yml").write_text(
        "version: 1\ntables: {}\n",
        encoding="utf-8",
    )

    def fail_read(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        del path, encoding, errors
        raise OSError("catalog read denied")

    monkeypatch.setattr(Path, "read_text", fail_read)

    with pytest.raises(OSError, match="catalog read denied"):
        build_inline_query_request(
            "SELECT 1",
            None,
            [],
            base_dir=tmp_path,
            operation=OperationContext(token=OperationToken()),
        )


def test_required_source_changed_after_submission_fails_before_user_sql(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    _write_csv(orders, "id\n1\n")
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "SELECT * FROM orders",
        None,
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=operation,
    )
    _write_csv(orders, "id\n999999\n")

    with CSVQLEngine(operation=operation) as engine, pytest.raises(SourceError) as exc_info:
        execute_query_request(engine, request, operation=operation)

    assert exc_info.value.code == "source_changed"


def test_fallback_source_changed_after_submission_fails_when_selected(
    tmp_path: Path,
) -> None:
    _write_catalog(tmp_path)
    orders = tmp_path / "orders.csv"
    customers = tmp_path / "customers.csv"
    _write_csv(orders, "id\n1\n")
    _write_csv(customers, "id\n1\n")
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "SELECT * FROM customers",
        None,
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=operation,
    )
    _write_csv(customers, "id\n999999\n")

    with CSVQLEngine(operation=operation) as engine, pytest.raises(SourceError) as exc_info:
        execute_query_request(engine, request, operation=operation)

    assert exc_info.value.code == "source_changed"


def test_catalog_mutation_after_submission_cannot_redirect_selected_fallback(
    tmp_path: Path,
) -> None:
    _write_catalog(tmp_path, "customers-original.csv")
    orders = tmp_path / "orders.csv"
    original_customers = tmp_path / "customers-original.csv"
    redirected_customers = tmp_path / "customers-redirected.csv"
    _write_csv(orders, "id\n1\n")
    _write_csv(original_customers, "id,email\n1,original@example.com\n")
    _write_csv(redirected_customers, "id,email\n1,redirected@example.com\n")
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "SELECT email FROM customers",
        None,
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=operation,
    )
    _write_catalog(tmp_path, "customers-redirected.csv")

    with CSVQLEngine(operation=operation) as engine:
        result = execute_query_request(engine, request, operation=operation)

    assert result.rows == (("original@example.com",),)


def test_default_invocation_cwd_is_captured_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    outside = tmp_path / "outside"
    project_root.mkdir()
    outside.mkdir()
    _write_csv(project_root / "orders.csv", "id\n1\n")
    _write_csv(outside / "orders.csv", "id\n999\n")
    monkeypatch.chdir(project_root)
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "SELECT * FROM orders",
        None,
        ["orders=orders.csv"],
        operation=operation,
    )
    monkeypatch.chdir(outside)

    with CSVQLEngine(operation=operation) as engine:
        result = execute_query_request(engine, request, operation=operation)

    assert result.rows == ((1,),)


def test_single_file_submission_rejects_later_source_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    orders = tmp_path / "orders.csv"
    _write_csv(orders, "id\n1\n")
    monkeypatch.chdir(tmp_path)
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "orders.csv",
        "SELECT * FROM orders",
        [],
        operation=operation,
    )
    monkeypatch.chdir(outside)
    _write_csv(orders, "id\n999999\n")

    with CSVQLEngine(operation=operation) as engine, pytest.raises(SourceError) as exc_info:
        execute_query_request(engine, request, operation=operation)

    assert exc_info.value.code == "source_changed"


def test_unused_missing_catalog_candidate_does_not_fail_explicit_query(
    tmp_path: Path,
) -> None:
    _write_catalog(tmp_path, "missing.csv")
    orders = tmp_path / "orders.csv"
    _write_csv(orders, "id\n1\n")

    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "SELECT * FROM orders",
        None,
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=operation,
    )

    assert request.fallback_sources[0].submission_error is not None
    assert request.fallback_sources[0].submission_error.code == "source_missing"
    with CSVQLEngine(operation=operation) as engine:
        result = execute_query_request(engine, request, operation=operation)
    assert result.rows == ((1,),)


def test_selected_missing_catalog_candidate_raises_public_file_missing_error(
    tmp_path: Path,
) -> None:
    _write_catalog(tmp_path, "private/location/missing.csv")
    orders = tmp_path / "orders.csv"
    _write_csv(orders, "id\n1\n")
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "SELECT * FROM orders JOIN customers USING (id)",
        None,
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=operation,
    )

    with CSVQLEngine(operation=operation) as engine, pytest.raises(FileMissingError) as exc_info:
        execute_query_request(engine, request, operation=operation)

    assert exc_info.value.message == (
        "CSV file not found for project catalog table 'customers': private/location/missing.csv"
    )
    assert exc_info.value.suggestion == (
        "Update .csvql.yml, run csvql add customers <path> --replace, or restore the CSV file."
    )
    assert isinstance(exc_info.value.__cause__, SourceError)
    assert exc_info.value.__cause__.code == "source_missing"


def test_selected_catalog_candidate_deleted_after_snapshot_raises_public_file_missing_error(
    tmp_path: Path,
) -> None:
    _write_catalog(tmp_path)
    orders = tmp_path / "orders.csv"
    customers = tmp_path / "customers.csv"
    _write_csv(orders, "id\n1\n")
    _write_csv(customers, "id,email\n1,alex@example.com\n")
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "SELECT email FROM customers",
        None,
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=operation,
    )
    customers.unlink()

    with CSVQLEngine(operation=operation) as engine, pytest.raises(FileMissingError) as exc_info:
        execute_query_request(engine, request, operation=operation)

    assert exc_info.value.exit_code == 4
    assert exc_info.value.message == (
        "CSV file not found for project catalog table 'customers': customers.csv"
    )
    assert exc_info.value.suggestion == (
        "Update .csvql.yml, run csvql add customers <path> --replace, or restore the CSV file."
    )
    assert isinstance(exc_info.value.__cause__, SourceError)
    assert exc_info.value.__cause__.code == "source_missing"


def test_no_explicit_source_preserves_missing_catalog_source_error(
    tmp_path: Path,
) -> None:
    _write_catalog(tmp_path, "missing.csv")

    with pytest.raises(FileMissingError, match="customers"):
        build_inline_query_request(
            "SELECT * FROM customers",
            None,
            [],
            base_dir=tmp_path,
            operation=OperationContext(token=OperationToken()),
        )


def test_lazy_fallback_uses_submission_fingerprint_and_case_insensitive_alias(
    tmp_path: Path,
) -> None:
    _write_catalog(tmp_path)
    orders = tmp_path / "orders.csv"
    customers = tmp_path / "customers.csv"
    _write_csv(orders, "id\n1\n")
    _write_csv(customers, "id\n1\n")
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "SELECT Customers.id FROM Customers",
        None,
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=operation,
    )

    with CSVQLEngine(operation=operation) as engine:
        result = execute_query_request(engine, request, operation=operation)

    assert result.rows == ((1,),)


def test_fallback_alias_is_attempted_at_most_once(
    tmp_path: Path,
) -> None:
    _write_catalog(tmp_path)
    orders = tmp_path / "orders.csv"
    customers = tmp_path / "customers.csv"
    _write_csv(orders, "id\n1\n")
    _write_csv(customers, "id\n1\n")
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "SELECT * FROM customers",
        None,
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=operation,
    )
    candidate = request.fallback_sources[0]
    duplicate_request = QueryRequest(
        sql=request.sql,
        required_sources=request.required_sources,
        fallback_sources=(candidate, candidate),
    )

    class RepeatingMissingEngine:
        def __init__(self, operation: OperationContext) -> None:
            self._operation = operation
            self.prepared: list[str] = []
            self.error = QueryExecutionError(
                "DuckDB query failed: Catalog Error: Table with name CUSTOMERS does not exist!"
            )

        def prepare_sources(self, sources: object) -> None:
            self.prepared.extend(source.spec.alias for source in sources)  # type: ignore[union-attr]

        def stream(self, sql: str, params=None) -> None:
            del sql, params
            raise self.error

    engine = RepeatingMissingEngine(operation)
    with pytest.raises(QueryExecutionError) as exc_info:
        execute_query_request(
            engine,  # type: ignore[arg-type]
            duplicate_request,
            operation=operation,
        )

    assert exc_info.value is engine.error
    assert engine.prepared == ["orders", "customers"]


def test_build_saved_sql_query_request_uses_one_context_for_required_and_fallback_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_catalog(tmp_path)
    _write_csv(tmp_path / "orders.csv", "id\n1\n")
    _write_csv(tmp_path / "customers.csv", "id\n1\n")
    operation = OperationContext(token=OperationToken())
    contexts: list[OperationContext] = []
    original_resolve = CSVSourceAdapter.resolve

    def record_resolve(
        self: CSVSourceAdapter,
        spec: SourceSpec,
        context: OperationContext,
    ) -> ResolvedSource:
        contexts.append(context)
        return original_resolve(self, spec, context)

    monkeypatch.setattr(CSVSourceAdapter, "resolve", record_resolve)

    build_saved_sql_query_request(
        "SELECT * FROM orders",
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=operation,
    )

    assert contexts == [operation, operation]


def test_execute_query_request_uses_one_context_for_fallback_resolution_and_engine_bind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_catalog(tmp_path)
    _write_csv(tmp_path / "orders.csv", "id\n1\n")
    _write_csv(tmp_path / "customers.csv", "id\n1\n")
    operation = OperationContext(token=OperationToken())
    contexts: list[OperationContext] = []
    original_resolve = CSVSourceAdapter.resolve
    original_prepare_sources = CSVQLEngine.prepare_sources

    def record_resolve(
        self: CSVSourceAdapter,
        spec: SourceSpec,
        context: OperationContext,
    ) -> ResolvedSource:
        contexts.append(context)
        return original_resolve(self, spec, context)

    def record_prepare_sources(
        self: CSVQLEngine,
        sources: tuple[ResolvedSource, ...],
    ) -> None:
        contexts.append(self._operation)
        return original_prepare_sources(self, sources)

    monkeypatch.setattr(CSVSourceAdapter, "resolve", record_resolve)
    monkeypatch.setattr(CSVQLEngine, "prepare_sources", record_prepare_sources)

    request = build_inline_query_request(
        "SELECT * FROM customers",
        None,
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=operation,
    )

    with CSVQLEngine(operation=operation) as engine:
        result = execute_query_request(engine, request, operation=operation)

    assert result.rows == ((1,),)
    assert all(context is operation for context in contexts)


def test_cancelled_operation_stops_before_fallback_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_catalog(tmp_path)
    _write_csv(tmp_path / "orders.csv", "id\n1\n")
    _write_csv(tmp_path / "customers.csv", "id\n1\n")
    operation = OperationContext(token=OperationToken())
    resolve_calls: list[str] = []
    original_resolve = CSVSourceAdapter.resolve

    def cancelling_resolve(
        self: CSVSourceAdapter,
        spec: SourceSpec,
        context: OperationContext,
    ) -> ResolvedSource:
        resolve_calls.append(spec.alias)
        if spec.alias == "customers":
            context.request_cancel()
        return original_resolve(self, spec, context)

    monkeypatch.setattr(CSVSourceAdapter, "resolve", cancelling_resolve)
    with pytest.raises(OperationCancelled):
        build_inline_query_request(
            "SELECT * FROM customers",
            None,
            ["orders=orders.csv"],
            base_dir=tmp_path,
            operation=operation,
        )

    assert resolve_calls == ["orders", "customers"]


def test_cancelled_operation_before_execution_skips_bind_and_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_csv(tmp_path / "orders.csv", "id\n1\n")
    operation = OperationContext(token=OperationToken())
    request = build_inline_query_request(
        "SELECT * FROM orders",
        None,
        ["orders=orders.csv"],
        base_dir=tmp_path,
        operation=operation,
    )
    operation.request_cancel()
    prepare_calls = 0
    query_calls = 0

    def fail_prepare(self: CSVQLEngine, sources: tuple[ResolvedSource, ...]) -> None:
        nonlocal prepare_calls
        prepare_calls += 1
        return None

    def fail_query(self: CSVQLEngine, sql: str) -> None:
        nonlocal query_calls
        del sql
        query_calls += 1
        return None

    monkeypatch.setattr(CSVQLEngine, "prepare_sources", fail_prepare)
    monkeypatch.setattr(CSVQLEngine, "query", fail_query)

    with CSVQLEngine(operation=operation) as engine, pytest.raises(OperationCancelled):
        execute_query_request(engine, request, operation=operation)

    assert prepare_calls == 0
    assert query_calls == 0
