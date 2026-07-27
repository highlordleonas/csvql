import ast
from pathlib import Path

import duckdb
import pytest

from csvql.checks import run_configured_checks
from csvql.csv_adapter import CSVSourceAdapter
from csvql.exceptions import CSVInspectionError, FileMissingError, ProjectConfigError
from csvql.project_config import (
    CONFIG_FILENAME,
    ProjectConfig,
    ProjectContext,
    ProjectTable,
    load_project,
)
from csvql.quality import ConfiguredCheck, ForeignKeyReference
from csvql.source_adapter import RelationalBinding


def test_checks_module_has_no_managed_direct_csv_read() -> None:
    module_path = Path(__file__).resolve().parents[1] / "src" / "csvql" / "checks.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read_csv"
        for node in ast.walk(tree)
    )


def _context(project_root: Path, tables: tuple[ProjectTable, ...]) -> ProjectContext:
    return ProjectContext(
        project_root=project_root.resolve(),
        config_path=(project_root / CONFIG_FILENAME).resolve(),
        config=ProjectConfig(version=1, tables=tables),
    )


def _check(
    name: str,
    table: str,
    type_value: str,
    *,
    column: str | None = None,
    values: tuple[object, ...] = (),
    value: object | None = None,
    min_value: object | None = None,
    max_value: object | None = None,
    references: ForeignKeyReference | None = None,
) -> ConfiguredCheck:
    return ConfiguredCheck(
        name=name,
        table=table,
        type=type_value,  # type: ignore[arg-type]
        column=column,
        values=values,
        value=value,
        min_value=min_value,
        max_value=max_value,
        references=references,
    )


def test_run_configured_checks_returns_global_warning_for_zero_checks(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(tmp_path, (ProjectTable("orders", "orders.csv"),))

    result = run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    assert result.status == "passed"
    assert result.check_count == 0
    assert result.warnings == ("No data quality checks configured.",)


def test_checks_share_one_operation_context_from_resolve_through_bind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(_check("required", "orders", "not_null", column="order_id"),),
            ),
        ),
    )
    resolve_operations: list[object] = []
    bind_operations: list[object] = []
    real_resolve = CSVSourceAdapter.resolve
    real_bind = CSVSourceAdapter.bind

    def recording_resolve(self, selected, operation):
        resolve_operations.append(operation)
        return real_resolve(self, selected, operation)

    def recording_bind(self, source, engine_session, binding_context):
        bind_operations.append(binding_context.operation)
        return real_bind(self, source, engine_session, binding_context)

    monkeypatch.setattr(CSVSourceAdapter, "resolve", recording_resolve)
    monkeypatch.setattr(CSVSourceAdapter, "bind", recording_bind)

    run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    assert len(resolve_operations) == 1
    assert len(bind_operations) == 1
    assert all(
        context is resolve_operations[0] for context in (*resolve_operations, *bind_operations)
    )


def test_run_configured_checks_returns_table_specific_warning_for_zero_checks(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(tmp_path, (ProjectTable("orders", "orders.csv"),))

    result = run_configured_checks(
        context, table_name="orders", show_failures=False, failure_limit=5
    )

    assert result.status == "passed"
    assert result.check_count == 0
    assert result.warnings == ("No data quality checks configured for table 'orders'.",)


def test_run_configured_checks_resolves_table_filter_case_insensitively(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "Orders",
                "orders.csv",
                checks=(_check("order_id_required", "Orders", "not_null", column="order_id"),),
            ),
        ),
    )

    result = run_configured_checks(
        context, table_name="orders", show_failures=False, failure_limit=5
    )

    assert result.status == "passed"
    assert result.check_count == 1
    assert result.checks[0].name == "order_id_required"


def test_run_configured_checks_rejects_case_colliding_table_aliases(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable("Orders", "orders.csv"),
            ProjectTable("orders", "orders.csv"),
        ),
    )

    with pytest.raises(ProjectConfigError):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)


def test_run_configured_checks_validates_core_semantics_and_identifier_quoting(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text(
        '"order id",select,"total-amount"\nORD-1,paid,10\nORD-2,unknown,20\nORD-2,,30\n,paid,40\n',
        encoding="utf-8",
    )
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check("order_id_required", "orders", "not_null", column="order id"),
                    _check("order_id_unique", "orders", "unique", column="order id"),
                    _check(
                        "status_known",
                        "orders",
                        "accepted_values",
                        column="select",
                        values=("paid", "pending"),
                    ),
                    _check(
                        "total_non_negative",
                        "orders",
                        "min",
                        column="total-amount",
                        value=15,
                    ),
                    _check(
                        "total_under_limit",
                        "orders",
                        "max",
                        column="total-amount",
                        value=25,
                    ),
                    _check(
                        "expected_rows",
                        "orders",
                        "row_count_between",
                        min_value=5,
                        max_value=10,
                    ),
                ),
            ),
        ),
    )

    result = run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    failures = {check.name: check.failed_count for check in result.checks}
    assert result.status == "failed"
    assert failures == {
        "order_id_required": 1,
        "order_id_unique": 1,
        "status_known": 1,
        "total_non_negative": 1,
        "total_under_limit": 2,
        "expected_rows": 1,
    }


def test_run_configured_checks_handles_whitespace_header_names(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text(
        '" total amount ",order_id\n10,ORD-1\n,ORD-2\n',
        encoding="utf-8",
    )
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "total_amount_required",
                        "orders",
                        "not_null",
                        column=" total amount ",
                    ),
                ),
            ),
        ),
    )

    result = run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    assert result.status == "failed"
    assert result.checks[0].failed_count == 1


def test_run_configured_checks_includes_capped_failure_samples(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text(
        "order_id,status\nORD-1,paid\n,unknown\n,paid\n",
        encoding="utf-8",
    )
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(_check("order_id_required", "orders", "not_null", column="order_id"),),
            ),
        ),
    )

    result = run_configured_checks(context, table_name=None, show_failures=True, failure_limit=1)

    assert result.checks[0].failed_count == 2
    assert len(result.checks[0].failures) == 1
    assert result.checks[0].failures[0].row_number == 2
    assert result.checks[0].failures[0].value is None
    assert result.checks[0].failures[0].row == {"order_id": None, "status": "unknown"}


def test_run_configured_checks_reports_row_count_between_sample(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\nORD-2\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "expected_rows",
                        "orders",
                        "row_count_between",
                        min_value=4,
                        max_value=6,
                    ),
                ),
            ),
        ),
    )

    result = run_configured_checks(context, table_name=None, show_failures=True, failure_limit=3)

    assert result.checks[0].failed_count == 2
    assert result.checks[0].failures[0].observed == 2
    assert result.checks[0].failures[0].min_value == 4
    assert result.checks[0].failures[0].max_value == 6


def test_run_configured_checks_accepts_date_scalars_from_yaml(tmp_path: Path) -> None:
    (tmp_path / "orders.csv").write_text(
        "ordered_at\n2024-01-01\n2024-01-02\n",
        encoding="utf-8",
    )
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: orders.csv\n"
        "    checks:\n"
        "      - name: ordered_at_min\n"
        "        type: min\n"
        "        column: ordered_at\n"
        "        value: 2024-01-01\n"
        "      - name: ordered_at_max\n"
        "        type: max\n"
        "        column: ordered_at\n"
        "        value: 2024-01-02\n"
        "      - name: ordered_at_known\n"
        "        type: accepted_values\n"
        "        column: ordered_at\n"
        "        values: [2024-01-01, 2024-01-02]\n",
        encoding="utf-8",
    )

    context = load_project(tmp_path)

    result = run_configured_checks(context, table_name=None, show_failures=False, failure_limit=3)

    assert result.status == "passed"
    assert [check.failed_count for check in result.checks] == [0, 0, 0]


@pytest.mark.parametrize(
    ("min_value", "max_value"),
    [
        (None, None),
        (10, 1),
    ],
)
def test_run_configured_checks_rejects_invalid_row_count_between_bounds(
    tmp_path: Path,
    min_value: object | None,
    max_value: object | None,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "expected_rows",
                        "orders",
                        "row_count_between",
                        min_value=min_value,
                        max_value=max_value,
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ProjectConfigError):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)


@pytest.mark.parametrize("bad_value", [2.9, -0.5, "3", True])
def test_run_configured_checks_rejects_non_integer_row_count_between_min(
    tmp_path: Path,
    bad_value: object,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "expected_rows",
                        "orders",
                        "row_count_between",
                        min_value=bad_value,
                        max_value=10,
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ProjectConfigError):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)


@pytest.mark.parametrize("bad_value", [2.9, -0.5, "3", True])
def test_run_configured_checks_rejects_non_integer_row_count_between_max(
    tmp_path: Path,
    bad_value: object,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "expected_rows",
                        "orders",
                        "row_count_between",
                        min_value=0,
                        max_value=bad_value,
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ProjectConfigError):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)


def test_run_configured_checks_rejects_unsupported_direct_model_check_type(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    ConfiguredCheck(
                        name="made_up_check",
                        table="orders",
                        type="made_up",  # type: ignore[arg-type]
                        column=None,
                        values=(),
                        value=None,
                        min_value=None,
                        max_value=None,
                        references=None,
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ProjectConfigError):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)


@pytest.mark.parametrize("min_value", [-1, -5])
def test_run_configured_checks_rejects_negative_row_count_between_min(
    tmp_path: Path,
    min_value: int,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "expected_rows",
                        "orders",
                        "row_count_between",
                        min_value=min_value,
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ProjectConfigError):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)


@pytest.mark.parametrize("max_value", [-1, -5])
def test_run_configured_checks_rejects_negative_row_count_between_max(
    tmp_path: Path,
    max_value: int,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "expected_rows",
                        "orders",
                        "row_count_between",
                        max_value=max_value,
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ProjectConfigError):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)


def test_run_configured_checks_reports_foreign_key_failures_and_null_child_passes(
    tmp_path: Path,
) -> None:
    (tmp_path / "orders.csv").write_text(
        "order_id,customer_id\nORD-1,CUST-1\nORD-2,CUST-MISSING\nORD-3,\n",
        encoding="utf-8",
    )
    (tmp_path / "customers.csv").write_text("customer_id\nCUST-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "customer_exists",
                        "orders",
                        "foreign_key",
                        column="customer_id",
                        references=ForeignKeyReference("customers", "customer_id"),
                    ),
                ),
            ),
            ProjectTable("customers", "customers.csv"),
        ),
    )

    result = run_configured_checks(context, table_name=None, show_failures=True, failure_limit=5)

    assert result.checks[0].failed_count == 1
    failure = result.checks[0].failures[0]
    assert failure.row_number == 2
    assert failure.value == "CUST-MISSING"
    assert failure.row == {"order_id": "ORD-2", "customer_id": "CUST-MISSING"}
    assert failure.reference_table == "customers"
    assert failure.reference_column == "customer_id"


def test_run_configured_checks_rejects_unknown_table_filter(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(tmp_path, (ProjectTable("orders", "orders.csv"),))

    with pytest.raises(ProjectConfigError):
        run_configured_checks(context, table_name="missing", show_failures=False, failure_limit=5)


def test_run_configured_checks_rejects_null_min_threshold(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("total_amount\n10\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "total_non_negative", "orders", "min", column="total_amount", value=None
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ProjectConfigError):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)


def test_run_configured_checks_wraps_missing_csv_for_catalog_table(tmp_path: Path) -> None:
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "missing.csv",
                checks=(_check("order_id_required", "orders", "not_null", column="order_id"),),
            ),
        ),
    )

    with pytest.raises(FileMissingError):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)


def test_required_source_failure_happens_before_any_check_sql(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "missing.csv",
                checks=(_check("order_id_required", "orders", "not_null", column="order_id"),),
            ),
        ),
    )
    executed_sql: list[str] = []

    def unexpected_query(self: object, sql: str, params: object = None) -> object:
        del self, params
        executed_sql.append(sql)
        raise AssertionError("check SQL ran before required-source preflight")

    monkeypatch.setattr("csvql.engine.CSVQLEngine.query", unexpected_query)

    with pytest.raises(FileMissingError):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    assert executed_sql == []


@pytest.mark.parametrize(
    ("failing_alias", "expected_bind_attempts", "expected_cleanup"),
    [
        ("customers", ["customers"], []),
        ("orders", ["customers", "orders"], ["customers"]),
    ],
)
def test_required_bind_failure_prevents_all_check_sql_and_cleans_reverse_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_alias: str,
    expected_bind_attempts: list[str],
    expected_cleanup: list[str],
) -> None:
    for alias in ("customers", "orders"):
        path = tmp_path / f"{alias}.csv"
        if alias == failing_alias:
            path.write_bytes(b"id\n\xff\n")
        else:
            path.write_text("id\n1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "customer_exists",
                        "orders",
                        "foreign_key",
                        column="id",
                        references=ForeignKeyReference("customers", "id"),
                    ),
                ),
            ),
            ProjectTable("customers", "customers.csv"),
        ),
    )
    bind_attempts: list[str] = []
    cleanup_order: list[str] = []
    check_sql: list[str] = []
    real_bind = CSVSourceAdapter.bind

    class RecordingBinding:
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
            cleanup_order.append(self.alias)
            self._binding.close(operation)

    def recording_bind(self, source, engine_session, binding_context):
        bind_attempts.append(source.alias)
        binding = real_bind(self, source, engine_session, binding_context)
        return RecordingBinding(binding)

    def unexpected_query(self, sql: str, params: object = None):
        del self, params
        check_sql.append(sql)
        raise AssertionError("check SQL ran after required-source bind failure")

    monkeypatch.setattr(CSVSourceAdapter, "bind", recording_bind)
    monkeypatch.setattr("csvql.engine.CSVQLEngine.query", unexpected_query)

    with pytest.raises(CSVInspectionError, match="Failed to run data quality checks"):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    assert bind_attempts == expected_bind_attempts
    assert cleanup_order == expected_cleanup
    assert check_sql == []


def test_checks_preserve_csv_inspection_error_for_duckdb_connection_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "orders.csv").write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(_check("order_id_required", "orders", "not_null", column="order_id"),),
            ),
        ),
    )
    monkeypatch.setattr(
        duckdb,
        "connect",
        lambda **kwargs: (_ for _ in ()).throw(duckdb.IOException("simulated connection failure")),
    )

    with pytest.raises(CSVInspectionError, match="Failed to run data quality checks"):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)
