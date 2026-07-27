import ast
from pathlib import Path
from textwrap import dedent

import duckdb
import pytest

from csvql.csv_adapter import CSVSourceAdapter
from csvql.doctor import (
    DoctorProbeResult,
    DoctorRunResult,
    _run_table_readiness_probes,
    run_doctor,
)
from csvql.engine import CSVQLEngine
from csvql.exceptions import SourceError
from csvql.project_config import ProjectConfig, ProjectContext, ProjectTable
from csvql.source_adapter import RelationalBinding
from csvql.source_operations import SourceOperations


def test_doctor_module_has_no_managed_direct_csv_read() -> None:
    module_path = Path(__file__).resolve().parents[1] / "src" / "csvql" / "doctor.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read_csv"
        for node in ast.walk(tree)
    )


def test_doctor_has_no_direct_connection_binding_or_query_ownership() -> None:
    module_path = Path(__file__).resolve().parents[1] / "src" / "csvql" / "doctor.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    forbidden_calls = {
        "duckdb.connect",
        "adapter.bind",
        "connection.execute",
    }
    observed = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}

    assert forbidden_calls.isdisjoint(observed)


def test_table_readiness_isolates_each_adapter_owned_probe(tmp_path: Path) -> None:
    (tmp_path / "first.csv").write_text("id\n1\n", encoding="utf-8")
    (tmp_path / "third.csv").write_text("id\n3\n", encoding="utf-8")
    context = ProjectContext(
        project_root=tmp_path,
        config_path=tmp_path / ".csvql.yml",
        config=ProjectConfig(
            version=1,
            tables=(
                ProjectTable(name="first", path="first.csv"),
                ProjectTable(name="missing", path="missing.csv"),
                ProjectTable(name="third", path="third.csv"),
            ),
        ),
    )

    probes, columns = _run_table_readiness_probes(context, context.config.tables)

    assert [(probe.table, probe.status) for probe in probes] == [
        ("first", "passed"),
        ("missing", "failed"),
        ("third", "passed"),
    ]
    assert columns == {"first": ("id",), "third": ("id",)}
    missing_probe = probes[1]
    assert missing_probe.message == (
        "CSV file not found for project catalog table 'missing': missing.csv"
    )


def test_table_readiness_resolves_binds_and_queries_once_per_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for alias in ("first", "second"):
        (tmp_path / f"{alias}.csv").write_text("id\n1\n", encoding="utf-8")
    context = ProjectContext(
        project_root=tmp_path,
        config_path=tmp_path / ".csvql.yml",
        config=ProjectConfig(
            version=1,
            tables=tuple(
                ProjectTable(name=alias, path=f"{alias}.csv") for alias in ("first", "second")
            ),
        ),
    )
    resolves: list[tuple[str, object]] = []
    binds: list[tuple[str, object]] = []
    queries: list[str] = []
    real_resolve = CSVSourceAdapter.resolve
    real_bind = CSVSourceAdapter.bind
    real_query = CSVQLEngine.query

    def recording_resolve(self, selected, operation):
        resolves.append((selected.request.alias, operation))
        return real_resolve(self, selected, operation)

    def recording_bind(self, source, engine_session, binding_context):
        binds.append((source.alias, binding_context.operation))
        return real_bind(self, source, engine_session, binding_context)

    def recording_query(self, sql: str, params=None):
        queries.append(sql)
        return real_query(self, sql, params)

    monkeypatch.setattr(CSVSourceAdapter, "resolve", recording_resolve)
    monkeypatch.setattr(CSVSourceAdapter, "bind", recording_bind)
    monkeypatch.setattr(CSVQLEngine, "query", recording_query)

    probes, columns = _run_table_readiness_probes(context, context.config.tables)

    assert [probe.status for probe in probes] == ["passed", "passed"]
    assert columns == {"first": ("id",), "second": ("id",)}
    assert [alias for alias, _ in resolves] == ["first", "second"]
    assert [alias for alias, _ in binds] == ["first", "second"]
    for (_alias, resolve_operation), (_, bind_operation) in zip(
        resolves,
        binds,
        strict=True,
    ):
        assert resolve_operation is bind_operation
    assert len(queries) == 2
    assert all("LIMIT ?" in query for query in queries)


def test_table_readiness_reports_cleanup_failure_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "first.csv").write_text("id\n1\n", encoding="utf-8")
    (tmp_path / "second.csv").write_text("id\n2\n", encoding="utf-8")
    context = ProjectContext(
        project_root=tmp_path,
        config_path=tmp_path / ".csvql.yml",
        config=ProjectConfig(
            version=1,
            tables=(
                ProjectTable(name="first", path="first.csv"),
                ProjectTable(name="second", path="second.csv"),
            ),
        ),
    )
    real_bind = CSVSourceAdapter.bind

    class CleanupFailingBinding:
        def __init__(self, binding: RelationalBinding) -> None:
            self._binding = binding

        @property
        def alias(self) -> str:
            return self._binding.alias

        @property
        def resolved_source(self):
            return self._binding.resolved_source

        @property
        def engine_session_id(self) -> str:
            return self._binding.engine_session_id

        @property
        def state(self):
            return self._binding.state

        def revalidate(self, requirement, operation):
            return self._binding.revalidate(requirement, operation)

        def close(self, operation) -> None:
            self._binding.close(operation)
            raise SourceError(
                "source_bind_failed",
                "Failed to clean up CSV source binding.",
                alias=self.alias,
            )

    def bind_with_first_cleanup_failure(
        self: CSVSourceAdapter,
        source,
        engine_session,
        binding_context,
    ):
        binding = real_bind(self, source, engine_session, binding_context)
        if source.alias == "first":
            return CleanupFailingBinding(binding)
        return binding

    monkeypatch.setattr(CSVSourceAdapter, "bind", bind_with_first_cleanup_failure)

    probes, columns = _run_table_readiness_probes(context, context.config.tables)

    assert [(probe.table, probe.status) for probe in probes] == [
        ("first", "failed"),
        ("second", "passed"),
    ]
    assert "cleanup" in probes[0].message.lower()
    assert columns == {"second": ("id",)}


def test_table_readiness_preserves_primary_failure_and_cleanup_uncertainty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "orders.csv").write_text("id\n1\n", encoding="utf-8")
    context = ProjectContext(
        project_root=tmp_path,
        config_path=tmp_path / ".csvql.yml",
        config=ProjectConfig(
            version=1,
            tables=(ProjectTable(name="orders", path="orders.csv"),),
        ),
    )
    real_bind = CSVSourceAdapter.bind

    class CleanupFailingBinding:
        def __init__(self, binding: RelationalBinding) -> None:
            self._binding = binding

        @property
        def alias(self) -> str:
            return self._binding.alias

        @property
        def resolved_source(self):
            return self._binding.resolved_source

        @property
        def engine_session_id(self) -> str:
            return self._binding.engine_session_id

        @property
        def state(self):
            return self._binding.state

        def revalidate(self, requirement, operation):
            return self._binding.revalidate(requirement, operation)

        def close(self, operation) -> None:
            self._binding.close(operation)
            raise RuntimeError("private cleanup detail")

    def failing_bind(self, source, engine_session, binding_context):
        return CleanupFailingBinding(real_bind(self, source, engine_session, binding_context))

    def failing_sample(self: SourceOperations, *, limit: int = 10):
        del limit
        self._prepare()
        raise SourceError(
            "source_bind_failed",
            "simulated readiness failure",
            alias="orders",
        )

    monkeypatch.setattr(CSVSourceAdapter, "bind", failing_bind)
    monkeypatch.setattr(SourceOperations, "sample", failing_sample)

    probes, columns = _run_table_readiness_probes(context, context.config.tables)

    assert columns == {}
    assert len(probes) == 1
    assert probes[0].status == "failed"
    assert "simulated readiness failure" in probes[0].message
    assert "Cleanup uncertainty:" in probes[0].message
    assert "private cleanup detail" not in probes[0].message


def test_table_readiness_propagates_unexpected_readiness_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "orders.csv").write_text("id\n1\n", encoding="utf-8")
    context = ProjectContext(
        project_root=tmp_path,
        config_path=tmp_path / ".csvql.yml",
        config=ProjectConfig(
            version=1,
            tables=(ProjectTable(name="orders", path="orders.csv"),),
        ),
    )

    def fail_unexpectedly(self: SourceOperations, *, limit: int = 10):
        del self, limit
        raise RuntimeError("unexpected readiness invariant")

    monkeypatch.setattr(SourceOperations, "sample", fail_unexpectedly)

    with pytest.raises(RuntimeError, match="unexpected readiness invariant"):
        _run_table_readiness_probes(context, context.config.tables)


def test_table_readiness_only_bounds_missing_interrupt_attribute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "orders.csv").write_text("id\n1\n", encoding="utf-8")
    context = ProjectContext(
        project_root=tmp_path,
        config_path=tmp_path / ".csvql.yml",
        config=ProjectConfig(
            version=1,
            tables=(ProjectTable(name="orders", path="orders.csv"),),
        ),
    )

    class ConnectionWithoutInterrupt:
        def close(self) -> None:
            return None

    monkeypatch.setattr(duckdb, "connect", lambda **kwargs: ConnectionWithoutInterrupt())

    probes, columns = _run_table_readiness_probes(context, context.config.tables)

    assert columns == {}
    assert len(probes) == 1
    assert probes[0].status == "failed"
    assert "interrupt" in probes[0].message


def test_table_readiness_propagates_unrelated_attribute_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "orders.csv").write_text("id\n1\n", encoding="utf-8")
    context = ProjectContext(
        project_root=tmp_path,
        config_path=tmp_path / ".csvql.yml",
        config=ProjectConfig(
            version=1,
            tables=(ProjectTable(name="orders", path="orders.csv"),),
        ),
    )

    def fail_with_unrelated_attribute(self: SourceOperations, *, limit: int = 10):
        del self, limit
        raise AttributeError("missing unrelated attribute", name="unrelated")

    monkeypatch.setattr(SourceOperations, "sample", fail_with_unrelated_attribute)

    with pytest.raises(AttributeError, match="unrelated"):
        _run_table_readiness_probes(context, context.config.tables)


def test_table_readiness_propagates_same_name_interrupt_attribute_after_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "orders.csv").write_text("id\n1\n", encoding="utf-8")
    context = ProjectContext(
        project_root=tmp_path,
        config_path=tmp_path / ".csvql.yml",
        config=ProjectConfig(
            version=1,
            tables=(ProjectTable(name="orders", path="orders.csv"),),
        ),
    )

    def fail_after_prepare(self: SourceOperations, *, limit: int = 10):
        del limit
        self._prepare()
        raise AttributeError(
            "adapter metadata lacks interrupt",
            name="interrupt",
        )

    monkeypatch.setattr(SourceOperations, "sample", fail_after_prepare)

    with pytest.raises(AttributeError, match="adapter metadata lacks interrupt"):
        _run_table_readiness_probes(context, context.config.tables)


def test_doctor_run_result_derives_warning_counts_and_json_shape() -> None:
    result = DoctorRunResult(
        project_root=None,
        config_path=None,
        probes=(
            DoctorProbeResult(
                name="project_discovery",
                scope="project",
                status="warning",
                message="No .csvql.yml project catalog found.",
            ),
        ),
    )

    assert result.status == "warning"
    assert result.probe_count == 1
    assert result.passed_count == 0
    assert result.warning_count == 1
    assert result.failed_count == 0
    assert result.as_dict() == {
        "status": "warning",
        "probe_count": 1,
        "passed_count": 0,
        "warning_count": 1,
        "failed_count": 0,
        "project": {
            "config_path": None,
            "project_root": None,
        },
        "probes": [
            {
                "name": "project_discovery",
                "scope": "project",
                "status": "warning",
                "message": "No .csvql.yml project catalog found.",
            }
        ],
    }


def test_table_readiness_propagates_internal_duckdb_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    context = ProjectContext(
        project_root=tmp_path,
        config_path=tmp_path / ".csvql.yml",
        config=ProjectConfig(
            version=1,
            tables=(ProjectTable(name="orders", path="orders.csv"),),
        ),
    )

    class FakeRelation:
        columns = ("order_id", "status")

        def create_view(self, name: str, *, replace: bool) -> None:
            return None

    class FakeCursor:
        description = ()

        def __init__(self, error: BaseException | None = None) -> None:
            self._error = error

        def execute(self, query: str, params: object = None) -> "FakeCursor":
            del query, params
            if self._error is not None:
                raise self._error
            return self

        def fetchmany(self, size: int) -> list[object]:
            del size
            return []

        def fetchall(self) -> list[object]:
            return []

        def close(self) -> None:
            return None

        def interrupt(self) -> None:
            return None

    class FakeConnection:
        def interrupt(self) -> None:
            return None

        def cursor(self) -> FakeCursor:
            return FakeCursor(duckdb.InternalException("simulated internal failure"))

        def read_csv(self, path: str, *, auto_detect: bool, header: bool) -> FakeRelation:
            return FakeRelation()

        def execute(self, query: str, params: object = None) -> FakeCursor:
            del params
            if query.startswith("DROP VIEW"):
                return FakeCursor()
            raise duckdb.InternalException("simulated internal failure")

        def close(self) -> None:
            return None

    monkeypatch.setattr(duckdb, "connect", lambda **kwargs: FakeConnection())

    with pytest.raises(duckdb.InternalException, match="simulated internal failure"):
        _run_table_readiness_probes(context, context.config.tables)


def test_run_doctor_omits_check_probes_when_table_readiness_failed(tmp_path: Path) -> None:
    (tmp_path / ".csvql.yml").write_text(
        dedent(
            """
            version: 1
            tables:
              orders:
                path: missing.csv
                checks:
                  - name: order_id_required
                    type: not_null
                    column: order_id
            """
        ).lstrip(),
        encoding="utf-8",
    )

    result = run_doctor(start_dir=tmp_path)

    assert result.status == "failed"
    assert [probe.name for probe in result.probes] == [
        "project_discovery",
        "config_load",
        "catalog_tables_present",
        "table_readiness",
    ]
    assert all(probe.scope != "check" for probe in result.probes)


def test_run_doctor_omits_check_probes_when_readiness_fails_after_column_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    (tmp_path / ".csvql.yml").write_text(
        dedent(
            """
            version: 1
            tables:
              orders:
                path: orders.csv
                checks:
                  - name: order_id_required
                    type: not_null
                    column: order_id
            """
        ).lstrip(),
        encoding="utf-8",
    )

    class FakeRelation:
        columns = ("order_id", "status")

        def create_view(self, name: str, *, replace: bool) -> None:
            return None

    class FakeCursor:
        description = ()

        def __init__(self, error: BaseException | None = None) -> None:
            self._error = error

        def execute(self, query: str, params: object = None) -> "FakeCursor":
            del query, params
            if self._error is not None:
                raise self._error
            return self

        def fetchmany(self, size: int) -> list[object]:
            del size
            return []

        def close(self) -> None:
            return None

        def interrupt(self) -> None:
            return None

    class FakeConnection:
        def interrupt(self) -> None:
            return None

        def cursor(self) -> FakeCursor:
            return FakeCursor(duckdb.InvalidInputException("simulated readiness failure"))

        def read_csv(self, path: str, *, auto_detect: bool, header: bool) -> FakeRelation:
            return FakeRelation()

        def execute(self, query: str, params: object = None) -> None:
            del params
            if query.startswith("DROP VIEW"):
                return None
            raise duckdb.InvalidInputException("simulated readiness failure")

        def close(self) -> None:
            return None

    monkeypatch.setattr(duckdb, "connect", lambda **kwargs: FakeConnection())

    result = run_doctor(start_dir=tmp_path)

    assert result.status == "failed"
    assert any(
        probe.name == "table_readiness"
        and probe.status == "failed"
        and probe.table == "orders"
        and "simulated readiness failure" in probe.message
        for probe in result.probes
    )
    assert all(probe.scope != "check" for probe in result.probes)
