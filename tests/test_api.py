from pathlib import Path

import pytest

from csvql.api import CSVQLSession
from csvql.exceptions import ProjectConfigError, QueryExecutionError, SQLFileError
from csvql.models import QueryResult


def _write_project(root: Path, *, rows: str = "ORD-001,paid\nORD-002,pending\n") -> None:
    (root / "data").mkdir(parents=True)
    (root / "queries").mkdir(parents=True)
    (root / "nested" / "child").mkdir(parents=True)
    (root / "data" / "orders.csv").write_text(
        "order_id,status\n" + rows,
        encoding="utf-8",
    )
    (root / "queries" / "count_orders.sql").write_text(
        "SELECT COUNT(*) AS order_count FROM orders",
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
