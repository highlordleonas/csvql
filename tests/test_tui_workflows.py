import json
from pathlib import Path

import pytest

from csvql import tui_workflows
from csvql.exceptions import ExportError, ProjectConfigError, TableMappingError
from csvql.export import ExportFormat
from csvql.models import InspectResult, ProfileResult, QueryResult, SampleResult
from csvql.project_config import CONFIG_FILENAME, initialize_project, load_project
from csvql.tui_state import TUISessionState, TUISource, TUISourceColumn
from csvql.tui_workflows import (
    build_initial_state,
    export_last_result,
    external_catalog_source_paths,
    inspect_source,
    inspect_source_columns,
    profile_source,
    query_sources,
    render_duckdb_identifier,
    run_buffer_for_tui,
    run_query_for_tui,
    sample_source,
    save_derived_result_source,
    save_sources_to_project_catalog,
    sources_from_csv_path_text,
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


def test_sources_from_csv_path_text_adds_pasted_paths_with_derived_aliases(
    tmp_path: Path,
) -> None:
    customers_csv = _write_csv(tmp_path / "new customers.csv")
    orders_csv = _write_csv(tmp_path / "orders.csv")

    sources = sources_from_csv_path_text(
        f"'{customers_csv}' {orders_csv}",
        existing_sources=(),
        start_dir=tmp_path,
    )

    assert sources == (
        TUISource(name="new_customers", path=customers_csv.resolve(), origin="session"),
        TUISource(name="orders", path=orders_csv.resolve(), origin="session"),
    )


def test_sources_from_csv_path_text_suffixes_duplicate_aliases(tmp_path: Path) -> None:
    existing_csv = _write_csv(tmp_path / "existing" / "orders.csv")
    pasted_csv = _write_csv(tmp_path / "pasted" / "orders.csv")
    existing_source = TUISource(name="orders", path=existing_csv.resolve(), origin="argument")

    sources = sources_from_csv_path_text(
        str(pasted_csv),
        existing_sources=(existing_source,),
        start_dir=tmp_path,
    )

    assert sources == (TUISource(name="orders_2", path=pasted_csv.resolve(), origin="session"),)


def test_sources_from_csv_path_text_preserves_backslash_path_text(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "pasted\\orders.csv")

    sources = sources_from_csv_path_text(
        str(csv_path),
        existing_sources=(),
        start_dir=tmp_path,
    )

    assert len(sources) == 1
    assert sources[0].path == csv_path.resolve()
    assert sources[0].origin == "session"


def test_sources_from_csv_path_text_accepts_file_urls(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "customers.csv")

    sources = sources_from_csv_path_text(
        csv_path.as_uri(),
        existing_sources=(),
        start_dir=tmp_path,
    )

    assert sources == (TUISource(name="customers", path=csv_path.resolve(), origin="session"),)


def test_path_value_from_terminal_token_accepts_windows_file_urls() -> None:
    assert (
        tui_workflows._path_value_from_terminal_token(
            "file:///C:/Users/runneradmin/orders.csv",
            os_name="nt",
        )
        == "C:/Users/runneradmin/orders.csv"
    )


def test_sources_from_csv_path_text_ignores_non_path_sql_paste(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv")

    sources = sources_from_csv_path_text(
        f"SELECT * FROM read_csv('{csv_path}')",
        existing_sources=(),
        start_dir=tmp_path,
    )

    assert sources == ()


def test_external_catalog_source_paths_detects_absolute_external_path(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    project_root.mkdir()
    external_root.mkdir()
    external_csv = _write_csv(external_root / "orders.csv")
    source = TUISource(name="orders", path=external_csv.resolve(), origin="session")

    paths = external_catalog_source_paths((source,), start_dir=project_root)

    assert paths == (external_csv.resolve(),)


def test_external_catalog_source_paths_resolves_symlinked_external_path(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    project_root.mkdir()
    external_root.mkdir()
    external_csv = _write_csv(external_root / "orders.csv")
    linked_csv = project_root / "linked-orders.csv"
    linked_csv.symlink_to(external_csv)
    source = TUISource(name="orders", path=linked_csv, origin="session")

    paths = external_catalog_source_paths((source,), start_dir=project_root)

    assert paths == (external_csv.resolve(),)


def test_external_catalog_source_paths_ignores_relative_project_path_when_cwd_differs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    project_root.mkdir()
    external_root.mkdir()
    _write_csv(project_root / "orders.csv")
    monkeypatch.chdir(external_root)
    source = TUISource(name="orders", path=Path("orders.csv"), origin="session")

    paths = external_catalog_source_paths((source,), start_dir=project_root)

    assert paths == ()


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


def test_inspect_source_columns_returns_names_and_duckdb_types(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "orders.csv",
        "Customer ID,select,total\nC-1,paid,12.5\n",
    )
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    columns = inspect_source_columns(source)

    assert columns == (
        TUISourceColumn(name="Customer ID", duckdb_type="VARCHAR"),
        TUISourceColumn(name="select", duckdb_type="VARCHAR"),
        TUISourceColumn(name="total", duckdb_type="DOUBLE"),
    )


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("orders", '"orders"'),
        ("Customer ID", '"Customer ID"'),
        ("select", '"select"'),
        ('a"b', '"a""b"'),
    ],
)
def test_render_duckdb_identifier_quotes_generated_sql_identifiers(
    identifier: str,
    expected: str,
) -> None:
    assert render_duckdb_identifier(identifier) == expected


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


def test_run_buffer_for_tui_shares_duckdb_session_across_statements(
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv", "id,value\n1,alpha\n")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    outcomes = run_buffer_for_tui(
        (source,),
        (
            "CREATE TEMP TABLE scratch AS SELECT * FROM orders",
            "SELECT COUNT(*) AS row_count FROM scratch",
        ),
        sequences=(1, 2),
    )

    assert [outcome.status for outcome in outcomes] == ["success", "success"]
    assert outcomes[0].result is not None
    assert outcomes[0].result.columns == ("Count",)
    assert outcomes[1].result is not None
    assert outcomes[1].result.rows == ((1,),)


def test_run_buffer_for_tui_stops_after_first_failure(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv", "id,value\n1,alpha\n")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    outcomes = run_buffer_for_tui(
        (source,),
        (
            "SELECT COUNT(*) AS row_count FROM orders",
            "SELECT * FROM missing_table",
            "SELECT 3 AS should_not_run",
        ),
        sequences=(1, 2, 3),
    )

    assert [outcome.sequence for outcome in outcomes] == [1, 2]
    assert [outcome.status for outcome in outcomes] == ["success", "error"]
    assert outcomes[1].error_message is not None
    assert "missing_table" in outcomes[1].error_message


def test_run_buffer_for_tui_rejects_sequence_length_mismatch(
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv", "id,value\n1,alpha\n")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    with pytest.raises(
        ValueError,
        match=r"Run Buffer statements and sequences must have the same length\.",
    ):
        run_buffer_for_tui((source,), ("SELECT 1", "SELECT 2"), sequences=(1,))


def test_run_buffer_for_tui_returns_no_result_for_empty_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCSVQLEngine:
        def __enter__(self) -> "FakeCSVQLEngine":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def register_tables(self, table_sources: object) -> None:
            del table_sources

        def query(self, sql: str) -> QueryResult:
            del sql
            return QueryResult(columns=(), rows=(), elapsed_ms=3.25)

    monkeypatch.setattr("csvql.tui_workflows.CSVQLEngine", FakeCSVQLEngine)

    outcome = run_buffer_for_tui((), ("CREATE TABLE scratch(id INTEGER)",), sequences=(8,))

    assert len(outcome) == 1
    assert outcome[0].sequence == 8
    assert outcome[0].status == "no_result"
    assert outcome[0].result is None
    assert outcome[0].elapsed_ms == 3.25


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


@pytest.mark.parametrize("force", [False, True])
def test_export_last_result_forwards_force_to_atomic_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    force: bool,
) -> None:
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)
    writes: list[tuple[Path, bool]] = []

    def fake_write_export_file(
        path: Path,
        content: str,
        *,
        overwrite: bool,
        token: object | None = None,
    ) -> None:
        assert content.endswith("\n")
        assert token is None
        writes.append((path, overwrite))

    monkeypatch.setattr("csvql.tui_workflows.write_export_file", fake_write_export_file)

    output_path = export_last_result(
        result,
        "result.csv",
        export_format=ExportFormat.csv,
        base_dir=tmp_path,
        force=force,
    )

    assert writes == [(output_path, force)]


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


def test_save_derived_result_source_writes_project_local_csv_and_returns_source(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    initialize_project(project_root)
    result = QueryResult(
        columns=("id", "name"),
        rows=((1, "Ada"), (2, "Bea")),
        elapsed_ms=1.0,
    )

    source = save_derived_result_source(
        result,
        "order_names",
        existing_sources=(),
        start_dir=project_root,
    )

    output_path = project_root / ".csvql" / "results" / "order_names.csv"
    assert output_path.read_text(encoding="utf-8") == "id,name\n1,Ada\n2,Bea\n"
    assert source == TUISource(
        name="order_names",
        path=output_path.resolve(),
        origin="session",
        kind="derived",
    )


def test_save_derived_result_source_uses_start_dir_without_project_catalog(
    tmp_path: Path,
) -> None:
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)

    source = save_derived_result_source(
        result,
        "scratch_ids",
        existing_sources=(),
        start_dir=tmp_path,
    )

    output_path = tmp_path / ".csvql" / "results" / "scratch_ids.csv"
    assert output_path.exists()
    assert source.path == output_path.resolve()
    assert source.kind == "derived"


def test_save_derived_result_source_preserves_empty_result_headers(tmp_path: Path) -> None:
    result = QueryResult(columns=("id", "name"), rows=(), elapsed_ms=1.0)

    source = save_derived_result_source(
        result,
        "empty_names",
        existing_sources=(),
        start_dir=tmp_path,
    )

    assert source.kind == "derived"
    assert (tmp_path / ".csvql" / "results" / "empty_names.csv").read_text(
        encoding="utf-8"
    ) == "id,name\n"


def test_save_derived_result_source_refuses_duplicate_session_alias(tmp_path: Path) -> None:
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)
    existing = (TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"),)

    with pytest.raises(TableMappingError, match=r"Source alias 'ORDERS' is already loaded"):
        save_derived_result_source(
            result,
            "ORDERS",
            existing_sources=existing,
            start_dir=tmp_path,
        )

    assert not (tmp_path / ".csvql" / "results").exists()


def test_save_derived_result_source_refuses_existing_output_file(tmp_path: Path) -> None:
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)
    output_dir = tmp_path / ".csvql" / "results"
    output_dir.mkdir(parents=True)
    output_path = output_dir / "orders.csv"
    output_path.write_text("id\nexisting\n", encoding="utf-8")

    with pytest.raises(ExportError, match=r"Derived result already exists"):
        save_derived_result_source(
            result,
            "orders",
            existing_sources=(),
            start_dir=tmp_path,
        )

    assert output_path.read_text(encoding="utf-8") == "id\nexisting\n"


def test_save_derived_result_source_refuses_file_created_during_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)
    output_dir = tmp_path / ".csvql" / "results"
    output_dir.mkdir(parents=True)
    output_path = output_dir / "race.csv"
    output_path.write_text("id\nexisting\n", encoding="utf-8")

    def racing_existing_derived_result_path(result_dir: Path, source_name: str) -> None:
        del source_name
        assert result_dir == output_dir.resolve()

    def racing_link(source: Path, target: Path) -> None:
        del source
        target.write_text("id\nexisting\n", encoding="utf-8")
        raise FileExistsError(target)

    monkeypatch.setattr(
        "csvql.tui_workflows._existing_derived_result_path",
        racing_existing_derived_result_path,
    )
    monkeypatch.setattr("csvql.atomic_write.os.link", racing_link)

    with pytest.raises(ExportError, match=r"Derived result already exists"):
        save_derived_result_source(
            result,
            "race",
            existing_sources=(),
            start_dir=tmp_path,
        )

    assert output_path.read_text(encoding="utf-8") == "id\nexisting\n"
    assert not tuple(output_dir.glob(".race.csv.*.tmp"))


def test_save_derived_result_source_refuses_case_variant_output_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)
    output_dir = tmp_path / ".csvql" / "results"
    output_dir.mkdir(parents=True)
    output_path = output_dir / "orders.csv"
    output_path.write_text("id\nexisting\n", encoding="utf-8")
    uppercase_output_path = output_dir.resolve() / "ORDERS.csv"
    original_exists = Path.exists
    write_attempts: list[Path] = []

    def case_sensitive_exists(path: Path) -> bool:
        if path == uppercase_output_path:
            return False
        return original_exists(path)

    def fake_write_derived_result_file(
        path: Path,
        content: str,
        *,
        token: object | None = None,
    ) -> None:
        del content
        assert token is None
        write_attempts.append(path)

    monkeypatch.setattr(Path, "exists", case_sensitive_exists)
    monkeypatch.setattr(
        "csvql.tui_workflows._write_derived_result_file",
        fake_write_derived_result_file,
    )

    with pytest.raises(ExportError, match=r"Derived result already exists"):
        save_derived_result_source(
            result,
            "ORDERS",
            existing_sources=(),
            start_dir=tmp_path,
        )

    assert output_path.read_text(encoding="utf-8") == "id\nexisting\n"
    assert write_attempts == []


def test_save_derived_result_source_uses_project_root_from_nested_start_dir(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    nested = project_root / "nested"
    nested.mkdir(parents=True)
    initialize_project(project_root)
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)

    source = save_derived_result_source(
        result,
        "nested_ids",
        existing_sources=(),
        start_dir=nested,
    )

    output_path = project_root / ".csvql" / "results" / "nested_ids.csv"
    assert output_path.read_text(encoding="utf-8") == "id\n1\n"
    assert source.path == output_path.resolve()
    assert not (nested / ".csvql" / "results" / "nested_ids.csv").exists()


def test_save_derived_result_source_refuses_symlinked_csvql_dir_before_mkdir(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (project_root / ".csvql").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)

    with pytest.raises(ExportError, match="Derived results directory escapes"):
        save_derived_result_source(
            result,
            "leak",
            existing_sources=(),
            start_dir=project_root,
        )

    assert not (outside / "results").exists()
    assert not (outside / "leak.csv").exists()


def test_save_derived_result_source_rejects_csvql_escape_before_existing_file_check(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_results = outside / "results"
    outside_results.mkdir()
    external_file = outside_results / "leak.csv"
    external_file.write_text("id\nexisting\n", encoding="utf-8")
    try:
        (project_root / ".csvql").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)

    with pytest.raises(ExportError, match="Derived results directory escapes"):
        save_derived_result_source(
            result,
            "leak",
            existing_sources=(),
            start_dir=project_root,
        )

    assert external_file.read_text(encoding="utf-8") == "id\nexisting\n"


def test_save_derived_result_source_refuses_symlinked_results_dir_escape(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    csvql_dir = project_root / ".csvql"
    csvql_dir.mkdir()
    try:
        (csvql_dir / "results").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)

    with pytest.raises(ExportError, match="Derived results directory escapes"):
        save_derived_result_source(
            result,
            "leak",
            existing_sources=(),
            start_dir=project_root,
        )

    assert not (outside / "leak.csv").exists()


def test_save_derived_result_source_refuses_file_created_during_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)
    output_path = tmp_path / ".csvql" / "results" / "race.csv"
    created_during_check = False

    def racing_existing_derived_result_path(result_dir: Path, source_name: str) -> None:
        nonlocal created_during_check
        assert result_dir == output_path.parent.resolve()
        assert source_name == "race"
        if not created_during_check:
            output_path.write_text("id\nexisting\n", encoding="utf-8")
            created_during_check = True

    monkeypatch.setattr(
        "csvql.tui_workflows._existing_derived_result_path",
        racing_existing_derived_result_path,
    )

    with pytest.raises(ExportError, match="Derived result already exists"):
        save_derived_result_source(
            result,
            "race",
            existing_sources=(),
            start_dir=tmp_path,
        )

    assert output_path.read_text(encoding="utf-8") == "id\nexisting\n"


def test_build_initial_state_does_not_create_results_directory(tmp_path: Path) -> None:
    state = build_initial_state(csv_path=None, table_mappings=(), start_dir=tmp_path)

    assert state == TUISessionState()
    assert not (tmp_path / ".csvql" / "results").exists()


def test_query_sources_can_join_derived_csv_source(tmp_path: Path) -> None:
    orders_csv = _write_csv(
        tmp_path / "orders.csv",
        "id,total\n1,10\n2,20\n",
    )
    result = QueryResult(
        columns=("id", "name"),
        rows=((1, "Ada"), (2, "Bea")),
        elapsed_ms=1.0,
    )
    derived = save_derived_result_source(
        result,
        "order_names",
        existing_sources=(),
        start_dir=tmp_path,
    )
    orders = TUISource(name="orders", path=orders_csv.resolve(), origin="argument")

    joined = query_sources(
        (orders, derived),
        """
        SELECT orders.id, order_names.name, orders.total
        FROM orders
        JOIN order_names ON order_names.id = orders.id
        ORDER BY orders.id
        """,
    )

    assert joined.columns == ("id", "name", "total")
    assert joined.rows == ((1, "Ada", 10), (2, "Bea", 20))


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


def test_run_query_for_tui_treats_duckdb_ddl_metadata_as_result(
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv", "id,value\n1,alpha\n")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    outcome = run_query_for_tui(
        (source,),
        "CREATE OR REPLACE TABLE scratch AS SELECT 1 AS value;",
        sequence=11,
    )

    assert outcome.sequence == 11
    assert outcome.status == "success"
    assert outcome.result is not None
    assert outcome.result.columns == ("Count",)
    assert outcome.result.rows == ((1,),)


def test_run_query_for_tui_returns_error_outcome(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv", "id,value\n1,alpha\n")
    source = TUISource(name="orders", path=csv_path.resolve(), origin="argument")

    outcome = run_query_for_tui((source,), "SELECT * FROM missing_alias", sequence=9)

    assert outcome.sequence == 9
    assert outcome.status == "error"
    assert outcome.result is None
    assert "DuckDB query failed" in (outcome.error_message or "")
    assert outcome.suggestion == "Check table names, column names, and SQL syntax."
