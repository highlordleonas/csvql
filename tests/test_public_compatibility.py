"""Characterization tests for the stable v1 public compatibility boundary."""

from __future__ import annotations

import inspect
import json
import tomllib
from datetime import date, datetime
from pathlib import Path
from textwrap import dedent

import pytest

import csvql
from csvql import CSVQLEngine, CSVQLSession, QueryResult, TableSource
from csvql.doctor import run_doctor
from csvql.exceptions import CSVQLError, ProjectConfigError, QueryExecutionError


def _write_project(root: Path) -> Path:
    data_dir = root / "data"
    data_dir.mkdir(parents=True)
    csv_path = data_dir / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-001,paid\nORD-002,pending\n",
        encoding="utf-8",
    )
    (root / ".csvql.yml").write_text(
        dedent(
            """
            version: 1
            tables:
              orders:
                path: data/orders.csv
                checks:
                  - name: order_id_required
                    type: not_null
                    column: order_id
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return csv_path


def _source_snapshot(path: Path) -> tuple[bytes, int, int]:
    stat = path.stat()
    content = path.read_bytes()
    return (content, stat.st_size, stat.st_mtime_ns)


def _assert_source_snapshot_unchanged(
    path: Path,
    expected: tuple[bytes, int, int],
) -> None:
    content, size_bytes, modified_ns = _source_snapshot(path)
    expected_content, expected_size_bytes, expected_modified_ns = expected

    assert content == expected_content
    assert size_bytes == expected_size_bytes
    assert modified_ns == expected_modified_ns


def _run_and_assert_source_unchanged(
    path: Path,
    expected: tuple[bytes, int, int],
    operation,
):
    result = operation()
    _assert_source_snapshot_unchanged(path, expected)
    return result


def test_public_exports_are_exact_and_exclude_private_source_foundations() -> None:
    assert csvql.__all__ == [
        "CSVQLEngine",
        "CSVQLSession",
        "CheckRunResult",
        "ExportFormat",
        "InspectResult",
        "ProfileResult",
        "ProjectTablesResult",
        "QueryResult",
        "SampleResult",
        "TableSource",
    ]
    assert not {
        "SourceSpec",
        "SourceAdapter",
        "SourceRegistry",
        "PreparedBinding",
        "ResultStream",
    }.intersection(csvql.__all__)


def test_public_session_and_engine_signatures_are_unchanged() -> None:
    assert str(inspect.signature(CSVQLSession.query)) == "(self, sql: 'str') -> 'QueryResult'"
    assert (
        str(inspect.signature(CSVQLSession.run_file))
        == "(self, path: 'str | Path') -> 'QueryResult'"
    )
    assert str(inspect.signature(CSVQLSession.inspect)) == (
        "(self, table: 'str', *, exact: 'bool' = False) -> 'InspectResult'"
    )
    assert str(inspect.signature(CSVQLSession.sample)) == (
        "(self, table: 'str', *, limit: 'int' = 10) -> 'SampleResult'"
    )
    assert str(inspect.signature(CSVQLSession.profile)) == "(self, table: 'str') -> 'ProfileResult'"
    assert str(inspect.signature(CSVQLSession.check)) == (
        "(self, table: 'str | None' = None, *, show_failures: 'bool' = False, "
        "failure_limit: 'int' = 5) -> 'CheckRunResult'"
    )
    assert str(inspect.signature(CSVQLSession.export)) == (
        "(self, sql_file: 'str | Path', out: 'str | Path', *, "
        "format: 'ExportFormat | str' = <ExportFormat.json: 'json'>, force: 'bool' = False) "
        "-> 'Path'"
    )
    assert str(inspect.signature(CSVQLEngine.register_tables)) == (
        "(self, table_sources: collections.abc.Iterable[csvql.models.TableSource]) -> None"
    )
    assert str(inspect.signature(CSVQLEngine.query)) == (
        "(self, sql: str, params: collections.abc.Sequence[object] | None = None) "
        "-> csvql.models.QueryResult"
    )


def test_python_query_preserves_complete_rows_column_order_and_scalar_values(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "orders.csv"
    source_path.write_text(
        "id,amount,ordered_on\n1,12.34,2024-01-02\n2,45.67,2024-02-03\n",
        encoding="utf-8",
    )

    with CSVQLEngine() as engine:
        engine.register_tables((TableSource(name="orders", path=source_path),))
        result = engine.query(
            "SELECT id, amount, ordered_on, "
            "CAST('2024-01-02 03:04:05' AS TIMESTAMP) AS happened_at FROM orders"
        )

    assert isinstance(result, QueryResult)
    assert result.columns == ("id", "amount", "ordered_on", "happened_at")
    assert result.rows == (
        (1, 12.34, date(2024, 1, 2), datetime(2024, 1, 2, 3, 4, 5)),
        (2, 45.67, date(2024, 2, 3), datetime(2024, 1, 2, 3, 4, 5)),
    )
    assert result.row_count == 2


def test_public_query_and_project_exceptions_remain_typed(tmp_path: Path) -> None:
    with CSVQLEngine() as engine:
        with pytest.raises(QueryExecutionError) as query_error:
            engine.query("SELECT * FROM missing_table")

    assert isinstance(query_error.value, CSVQLError)
    with pytest.raises(ProjectConfigError):
        CSVQLSession.from_config(tmp_path)


def test_public_command_and_import_names_remain_csvql_only() -> None:
    pyproject_path = Path(__file__).parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"] == {"csvql": "csvql.cli:main"}
    assert csvql.__name__ == "csvql"


def test_public_session_operations_do_not_mutate_managed_source_bytes_or_metadata(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    csv_path = _write_project(project_root)
    session = CSVQLSession.from_config(project_root)
    expected_snapshot = _source_snapshot(csv_path)

    query_result = _run_and_assert_source_unchanged(
        csv_path,
        expected_snapshot,
        lambda: session.query("SELECT order_id, status FROM orders ORDER BY order_id"),
    )
    inspect_result = _run_and_assert_source_unchanged(
        csv_path,
        expected_snapshot,
        lambda: session.inspect("orders", exact=True),
    )
    sample_result = _run_and_assert_source_unchanged(
        csv_path,
        expected_snapshot,
        lambda: session.sample("orders", limit=1),
    )
    profile_result = _run_and_assert_source_unchanged(
        csv_path,
        expected_snapshot,
        lambda: session.profile("orders"),
    )
    check_result = _run_and_assert_source_unchanged(
        csv_path,
        expected_snapshot,
        lambda: session.check(show_failures=True, failure_limit=1),
    )
    doctor_result = _run_and_assert_source_unchanged(
        csv_path,
        expected_snapshot,
        lambda: run_doctor(start_dir=project_root),
    )

    assert query_result.rows == (("ORD-001", "paid"), ("ORD-002", "pending"))
    assert inspect_result.row_count.value == 2
    assert sample_result.rows == (("ORD-001", "paid"),)
    assert profile_result.row_count == 2
    assert check_result.failed_count == 0
    assert doctor_result.status == "passed"
    _assert_source_snapshot_unchanged(csv_path, expected_snapshot)


def test_source_snapshot_helper_catches_temporary_mutation_before_later_restore(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-001,paid\nORD-002,pending\n",
        encoding="utf-8",
    )
    expected_snapshot = _source_snapshot(csv_path)
    original_content, _, _ = expected_snapshot

    def mutate_source() -> str:
        csv_path.write_text(
            "order_id,status\nORD-001,mutated\nORD-002,pending\n",
            encoding="utf-8",
        )
        return "mutated"

    def restore_source() -> str:
        csv_path.write_bytes(original_content)
        return "restored"

    with pytest.raises(AssertionError):
        _run_and_assert_source_unchanged(
            csv_path,
            expected_snapshot,
            mutate_source,
        )

    restored = restore_source()

    assert restored == "restored"
    assert csv_path.read_bytes() == original_content


def test_public_json_and_project_config_exclude_private_source_types(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project(project_root)
    session = CSVQLSession.from_config(project_root)

    payload = json.dumps(
        {
            "inspect": session.inspect("orders").as_dict(),
            "sample": session.sample("orders", limit=1).as_dict(),
            "profile": session.profile("orders").as_dict(),
        },
        sort_keys=True,
        default=str,
    )
    config_text = (project_root / ".csvql.yml").read_text(encoding="utf-8")

    for forbidden in (
        "SourceSpec",
        "ResolvedSource",
        "SourceAdapter",
        "SourceAdapterRegistry",
        "PreparedBinding",
    ):
        assert forbidden not in payload
        assert forbidden not in config_text
