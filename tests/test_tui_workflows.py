import json
from pathlib import Path

import pytest

from csvql.exceptions import ExportError, ProjectConfigError, TableMappingError
from csvql.export import ExportFormat
from csvql.models import InspectResult, ProfileResult, QueryResult, SampleResult
from csvql.project_config import CONFIG_FILENAME, initialize_project, load_project
from csvql.tui_state import TUISessionState, TUISource
from csvql.tui_workflows import (
    build_initial_state,
    export_last_result,
    inspect_source,
    profile_source,
    query_sources,
    run_query_for_tui,
    sample_source,
    save_sources_to_project_catalog,
)


def _write_csv(path: Path, content: str = "id,value\n1,alpha\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_build_initial_state_without_catalog_or_args_returns_empty_state(
    tmp_path: Path,
) -> None:
    state = build_initial_state(csv_path=None, table_mappings=(), start_dir=tmp_path)

    assert state == TUISessionState()
    assert state.sources == ()
    assert state.selected_alias is None


def test_build_initial_state_loads_catalog_sources_with_resolved_paths(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_csv(project_root / "data" / "orders.csv")
    _write_csv(project_root / "data" / "customers.csv")
    initialize_project(project_root)
    (project_root / CONFIG_FILENAME).write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: data/orders.csv\n"
        "  customers:\n"
        "    path: data/customers.csv\n",
        encoding="utf-8",
    )

    state = build_initial_state(csv_path=None, table_mappings=(), start_dir=project_root)

    assert state.sources == (
        TUISource(
            name="orders",
            path=(project_root / "data" / "orders.csv").resolve(),
            origin="catalog",
        ),
        TUISource(
            name="customers",
            path=(project_root / "data" / "customers.csv").resolve(),
            origin="catalog",
        ),
    )
    assert state.selected_alias == "orders"


def test_build_initial_state_loads_single_csv_argument_with_derived_alias(
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(tmp_path / "sales-2026.csv")

    state = build_initial_state(csv_path=str(csv_path), table_mappings=(), start_dir=tmp_path)

    assert state.sources == (
        TUISource(name="sales_2026", path=csv_path.resolve(), origin="argument"),
    )
    assert state.selected_alias == "sales_2026"


def test_build_initial_state_loads_table_mappings_in_argument_order(
    tmp_path: Path,
) -> None:
    first_csv = _write_csv(tmp_path / "first.csv")
    second_csv = _write_csv(tmp_path / "second.csv")

    state = build_initial_state(
        csv_path=None,
        table_mappings=(f"first={first_csv}", f"second={second_csv}"),
        start_dir=tmp_path,
    )

    assert state.sources == (
        TUISource(name="first", path=first_csv.resolve(), origin="argument"),
        TUISource(name="second", path=second_csv.resolve(), origin="argument"),
    )
    assert state.selected_alias == "first"


def test_build_initial_state_rejects_duplicate_aliases_between_csv_and_mapping(
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv")
    duplicate_csv = _write_csv(tmp_path / "duplicate.csv")

    with pytest.raises(
        TableMappingError,
        match=r"Duplicate table alias 'orders'",
    ):
        build_initial_state(
            csv_path=str(csv_path),
            table_mappings=(f"orders={duplicate_csv}",),
            start_dir=tmp_path,
        )


def test_build_initial_state_propagates_invalid_catalog_yaml(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / CONFIG_FILENAME).write_text("version: [1\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError, match=r"Invalid YAML"):
        build_initial_state(csv_path=None, table_mappings=(), start_dir=project_root)


def test_inspect_sample_profile_wrappers_use_alias_display_path(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "orders.csv",
        "order_id,status\nORD-1,paid\n",
    )
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    inspect_result = inspect_source(source)
    sample_result = sample_source(source, limit=1)
    profile_result = profile_source(source)

    assert isinstance(inspect_result, InspectResult)
    assert isinstance(sample_result, SampleResult)
    assert isinstance(profile_result, ProfileResult)
    assert inspect_result.source["display_path"] == "orders"
    assert sample_result.source["display_path"] == "orders"
    assert profile_result.source["display_path"] == "orders"


def test_query_sources_supports_join_across_tui_aliases(tmp_path: Path) -> None:
    customers_csv = _write_csv(
        tmp_path / "customers.csv",
        "customer_id,name\nC-1,Ada\nC-2,Bea\n",
    )
    orders_csv = _write_csv(
        tmp_path / "orders.csv",
        "order_id,customer_id,total\nO-1,C-1,10\nO-2,C-2,20\n",
    )
    sources = (
        TUISource(name="customers", path=customers_csv.resolve(), origin="argument"),
        TUISource(name="orders", path=orders_csv.resolve(), origin="argument"),
    )

    result = query_sources(
        sources,
        """
        SELECT orders.order_id, customers.name, orders.total
        FROM orders
        JOIN customers ON customers.customer_id = orders.customer_id
        ORDER BY orders.order_id
        """,
    )

    assert isinstance(result, QueryResult)
    assert result.columns == ("order_id", "name", "total")
    assert result.rows == (("O-1", "Ada", 10), ("O-2", "Bea", 20))


def test_export_last_result_writes_json_and_returns_resolved_path(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv", "order_id,status\nORD-1,paid\n")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")
    result = query_sources((source,), "SELECT * FROM orders ORDER BY order_id")
    (tmp_path / "exports").mkdir()

    output_path = export_last_result(
        result,
        "exports/result.json",
        export_format=ExportFormat.json,
        base_dir=tmp_path,
    )

    assert output_path == (tmp_path / "exports" / "result.json").resolve()
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "columns": ["order_id", "status"],
        "elapsed_ms": round(result.elapsed_ms, 3),
        "row_count": 1,
        "rows": [{"order_id": "ORD-1", "status": "paid"}],
    }


def test_save_sources_to_project_catalog_creates_catalog_and_uses_relative_paths(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    csv_path = _write_csv(project_root / "data" / "orders.csv")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="session")

    context = save_sources_to_project_catalog((source,), start_dir=project_root, replace=False)

    assert context.config_path == (project_root / CONFIG_FILENAME).resolve()
    assert context.project_root == project_root.resolve()
    assert context.config.tables[0].path == "data/orders.csv"

    loaded_context = load_project(project_root)
    assert loaded_context.config.tables[0].path == "data/orders.csv"


def test_save_sources_to_project_catalog_rolls_back_failed_batch_without_mutating_file(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_csv(project_root / "data" / "existing.csv")
    _write_csv(project_root / "data" / "first.csv")
    _write_csv(project_root / "data" / "second.csv")
    initialize_project(project_root)
    (project_root / CONFIG_FILENAME).write_text(
        "version: 1\ntables:\n  existing:\n    path: data/existing.csv\n",
        encoding="utf-8",
    )
    original_config = (project_root / CONFIG_FILENAME).read_text(encoding="utf-8")

    first = TUISource(
        name="first", path=(project_root / "data" / "first.csv").resolve(), origin="session"
    )
    duplicate = TUISource(
        name="first",
        path=(project_root / "data" / "second.csv").resolve(),
        origin="session",
    )

    with pytest.raises(ProjectConfigError, match=r"Duplicate project catalog table 'first'"):
        save_sources_to_project_catalog((first, duplicate), start_dir=project_root, replace=False)

    assert (project_root / CONFIG_FILENAME).read_text(encoding="utf-8") == original_config


def test_save_sources_to_project_catalog_missing_project_does_not_create_catalog_on_failed_batch(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_csv(project_root / "first.csv")
    _write_csv(project_root / "second.csv")

    first = TUISource(name="first", path=(project_root / "first.csv").resolve(), origin="session")
    duplicate = TUISource(
        name="first",
        path=(project_root / "second.csv").resolve(),
        origin="session",
    )

    with pytest.raises(ProjectConfigError, match=r"Duplicate project catalog table 'first'"):
        save_sources_to_project_catalog((first, duplicate), start_dir=project_root, replace=False)

    assert not (project_root / CONFIG_FILENAME).exists()


def test_export_last_result_refuses_overwrite_without_force(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv", "order_id,status\nORD-1,paid\n")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")
    result = query_sources((source,), "SELECT * FROM orders ORDER BY order_id")
    (tmp_path / "exports").mkdir()

    output_path = export_last_result(
        result,
        "exports/result.json",
        export_format=ExportFormat.json,
        base_dir=tmp_path,
    )
    first_content = output_path.read_text(encoding="utf-8")

    with pytest.raises(ExportError, match=r"Export output already exists"):
        export_last_result(
            result,
            "exports/result.json",
            export_format=ExportFormat.json,
            base_dir=tmp_path,
        )

    assert output_path.read_text(encoding="utf-8") == first_content


def test_run_query_for_tui_returns_success_outcome(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv", "id,value\n1,alpha\n")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    outcome = run_query_for_tui((source,), "SELECT * FROM orders", sequence=4)

    assert outcome.sequence == 4
    assert outcome.status == "success"
    assert outcome.result is not None
    assert outcome.result.columns == ("id", "value")
    assert outcome.error_message is None


def test_run_query_for_tui_returns_no_result_for_empty_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_query_sources(sources: object, sql: str) -> QueryResult:
        return QueryResult(columns=(), rows=(), elapsed_ms=3.25)

    monkeypatch.setattr("csvql.tui_workflows.query_sources", fake_query_sources)

    outcome = run_query_for_tui((), "CREATE TABLE scratch(id INTEGER)", sequence=8)

    assert outcome.sequence == 8
    assert outcome.status == "no_result"
    assert outcome.result is None
    assert outcome.elapsed_ms == 3.25


def test_run_query_for_tui_returns_success_for_empty_rows_with_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_query_sources(sources: object, sql: str) -> QueryResult:
        return QueryResult(columns=("id",), rows=(), elapsed_ms=4.5)

    monkeypatch.setattr("csvql.tui_workflows.query_sources", fake_query_sources)

    outcome = run_query_for_tui((), "SELECT id FROM orders WHERE 1 = 0", sequence=10)

    assert outcome.sequence == 10
    assert outcome.status == "success"
    assert outcome.result is not None
    assert outcome.result.row_count == 0


def test_run_query_for_tui_returns_error_outcome(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv", "id,value\n1,alpha\n")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    outcome = run_query_for_tui((source,), "SELECT * FROM missing_alias", sequence=9)

    assert outcome.sequence == 9
    assert outcome.status == "error"
    assert outcome.result is None
    assert "DuckDB query failed" in (outcome.error_message or "")
    assert outcome.suggestion == "Check table names, column names, and SQL syntax."
