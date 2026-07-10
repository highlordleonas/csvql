import json
from pathlib import Path

import pytest

from csvql import (
    CSVQLSession,
    ExportFormat,
    InspectResult,
    ProfileResult,
    ProjectTablesResult,
    QueryResult,
    SampleResult,
)
from csvql.exceptions import ExportError, ProjectConfigError, QueryExecutionError, SQLFileError
from csvql.quality import CheckRunResult


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
    assert set(payload) == {"columns", "rows", "row_count", "elapsed_ms"}
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
    writes: list[tuple[Path, bool]] = []

    def fake_write_export_file(path: Path, content: str, *, overwrite: bool) -> None:
        assert content == "order_count\r\n2\r\n"
        writes.append((path, overwrite))

    monkeypatch.setattr("csvql.api.write_export_file", fake_write_export_file)

    output_path = session.export(
        "queries/count_orders.sql",
        "output/count-orders.csv",
        format="csv",
        force=force,
    )

    assert writes == [(output_path, force)]


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
