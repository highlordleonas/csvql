"""Cross-surface source request, diagnostic, and execution parity."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import duckdb
import pytest
from source_surface_vectors import DETECTION_VECTORS, SEMANTIC_REQUEST_VECTORS
from typer.testing import CliRunner

from csvql.api import CSVQLSession
from csvql.cli import app
from csvql.exceptions import CSVQLError, ProjectConfigError, SourceError
from csvql.models import SourceDefinition
from csvql.project_config import (
    CONFIG_FILENAME,
    CURRENT_VERSION,
    CatalogSourceDefinition,
    ProjectConfigV2,
    ProjectContext,
    ProjectTableV2,
    add_project_table,
    initialize_project,
    load_project,
    project_tables_to_source_specs,
    save_project,
)
from csvql.query_workflow import _requests_from_cli_sources
from csvql.source import (
    AmbiguousSource,
    InvalidSource,
    SelectedSource,
    SourceRequest,
    UnsupportedSource,
    build_source_request,
    canonical_source_request_bytes,
    source_request_from_definition,
)
from csvql.source_detection import SourceDetectionService
from csvql.source_identifiers import build_builtin_identifier_table
from csvql.source_registry import build_builtin_descriptor_registry
from csvql.table_mapping import parse_source_options
from csvql.tui_state import TUISource
from csvql.tui_workflows import (
    build_tui_source_preview,
    inspect_source,
    query_sources,
    save_sources_to_project_catalog,
)

runner = CliRunner()


def _detector() -> SourceDetectionService:
    return SourceDetectionService(
        build_builtin_descriptor_registry(),
        build_builtin_identifier_table(),
    )


def _write_fixture(path: Path, fixture_kind: str) -> None:
    if fixture_kind == "directory":
        path.mkdir()
        return
    if fixture_kind == "csv":
        path.write_text("id,value\n1,alpha\n2,beta\n", encoding="utf-8")
        return
    if fixture_kind == "json":
        path.write_text('[{"id":1,"value":"alpha"},{"id":2,"value":"beta"}]', encoding="utf-8")
        return
    if fixture_kind == "ndjson":
        path.write_text(
            '{"id":1,"value":"alpha"}\n{"id":2,"value":"beta"}\n',
            encoding="utf-8",
        )
        return
    if fixture_kind == "parquet":
        connection = duckdb.connect()
        try:
            connection.sql(
                "SELECT * FROM (VALUES (1, 'alpha'), (2, 'beta')) AS rows(id, value)"
            ).write_parquet(str(path))
        finally:
            connection.close()
        return
    if fixture_kind == "xlsx_container":
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("xl/workbook.xml", "<workbook/>")
        return
    path.write_bytes(b"opaque fixture")


def _request_from_catalog(context: ProjectContext) -> SourceRequest:
    spec = project_tables_to_source_specs(context)[0]
    return build_source_request(
        alias=spec.alias,
        locator=spec.locator,
        anchor=spec.anchor,
        explicit_type=spec.kind,
        options=spec.options,
    )


@pytest.mark.parametrize("vector", SEMANTIC_REQUEST_VECTORS, ids=lambda vector: vector.name)
def test_explicit_source_request_is_byte_identical_across_all_boundaries(
    vector,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / vector.name
    project_root.mkdir()
    locator = project_root / vector.locator_name
    _write_fixture(locator, vector.fixture_kind)
    options = parse_source_options(vector.option_mappings)

    direct = build_source_request(
        alias="records",
        locator=vector.locator_name,
        anchor=project_root,
        explicit_type=vector.explicit_type,
        options=options.items(),
    )
    cli = _requests_from_cli_sources(
        (),
        source_mappings=(f"records={vector.locator_name}",),
        source_type_mappings=(f"records={vector.explicit_type}",),
        source_option_mappings=tuple(f"records.{mapping}" for mapping in vector.option_mappings),
        base_dir=project_root,
    )[0]
    python_api = source_request_from_definition(
        SourceDefinition(
            "records",
            vector.locator_name,
            source_type=vector.explicit_type,
            options=options,
            base_dir=project_root,
        )
    )
    tui_preview = build_tui_source_preview(
        alias="records",
        locator=vector.locator_name,
        source_type=vector.explicit_type,
        option_mappings=vector.option_mappings,
        existing_sources=(),
        start_dir=project_root,
    )
    tui = source_request_from_definition(tui_preview.source.as_source_definition())
    context = ProjectContext(
        project_root=project_root,
        config_path=project_root / CONFIG_FILENAME,
        config=ProjectConfigV2(
            version=CURRENT_VERSION,
            tables=(
                ProjectTableV2(
                    name="records",
                    source=CatalogSourceDefinition(
                        source_type=vector.explicit_type or "",
                        locator=vector.locator_name,
                        options=direct.options,
                    ),
                ),
            ),
        ),
    )
    save_project(context)
    catalog = _request_from_catalog(load_project(project_root))

    encoded = {
        canonical_source_request_bytes(request)
        for request in (direct, cli, python_api, tui, catalog)
    }
    assert len(encoded) == 1
    assert canonical_source_request_bytes(direct, redaction="safe") == (
        b'{"alias":"records","anchor":null,"explicit_type":"'
        + vector.explicit_type.encode()
        + b'","locator":"'
        + vector.locator_name.encode()
        + b'","options":'
        + json.dumps(options, separators=(",", ":"), sort_keys=True).encode()
        + b',"version":1}'
    )


@pytest.mark.parametrize("vector", DETECTION_VECTORS, ids=lambda vector: vector.name)
def test_detection_vectors_produce_declared_provider_or_diagnostic(
    vector,
    tmp_path: Path,
) -> None:
    locator = tmp_path / vector.locator_name
    _write_fixture(locator, vector.fixture_kind)
    request = build_source_request(
        alias="records",
        locator=vector.locator_name,
        anchor=tmp_path,
        explicit_type=vector.explicit_type,
        options=parse_source_options(vector.option_mappings).items(),
    )

    outcome = _detector().detect(request)

    if vector.expected_variant == "selected":
        assert isinstance(outcome, SelectedSource)
        assert outcome.provider_key == vector.expected_provider
        return
    expected_type = {
        "ambiguous": AmbiguousSource,
        "unsupported": UnsupportedSource,
        "invalid": InvalidSource,
    }[vector.expected_variant]
    assert isinstance(outcome, expected_type)
    assert outcome.diagnostic.code.value == vector.expected_code
    assert outcome.required_action.kind == vector.expected_action


@pytest.mark.parametrize(
    ("locator_name", "fixture_kind", "explicit_type", "option_mappings"),
    (
        ("future.bin", "opaque", "avro", ()),
        ("warehouse", "directory", "csv", ()),
        ("records.json", "json", "json", ("sample_size=ten",)),
    ),
)
def test_diagnostic_semantics_match_cli_python_and_tui(
    locator_name: str,
    fixture_kind: str,
    explicit_type: str,
    option_mappings: tuple[str, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locator = tmp_path / locator_name
    _write_fixture(locator, fixture_kind)
    initialize_project(tmp_path)
    direct_request = build_source_request(
        alias=Path(locator_name).stem,
        locator=locator_name,
        anchor=tmp_path,
        explicit_type=explicit_type,
        options=parse_source_options(option_mappings).items(),
    )
    direct = _detector().detect(direct_request)
    assert not isinstance(direct, SelectedSource)
    expected = direct.diagnostic.as_dict()

    monkeypatch.chdir(tmp_path)
    cli_args = ["inspect", locator_name, "--type", explicit_type, "--output", "json"]
    for mapping in option_mappings:
        cli_args.extend(("--option", mapping))
    cli_result = runner.invoke(app, cli_args, catch_exceptions=False)
    assert cli_result.exit_code != 0
    cli_diagnostic = json.loads(cli_result.output)["diagnostic"]
    assert cli_diagnostic == {"version": 1, **expected}

    session = CSVQLSession.from_config(tmp_path)
    with pytest.raises(CSVQLError) as api_error:
        session.inspect(
            SourceDefinition(
                Path(locator_name).stem,
                locator_name,
                source_type=explicit_type,
                options=parse_source_options(option_mappings),
                base_dir=tmp_path,
            )
        )
    assert api_error.value.diagnostic is not None
    assert api_error.value.diagnostic.as_dict() == expected

    with pytest.raises(SourceError) as tui_error:
        build_tui_source_preview(
            alias=Path(locator_name).stem,
            locator=locator_name,
            source_type=explicit_type,
            option_mappings=option_mappings,
            existing_sources=(),
            start_dir=tmp_path,
        )
    assert tui_error.value.diagnostic is not None
    assert tui_error.value.diagnostic.as_dict() == expected


@pytest.mark.parametrize("source_type", ("csv", "parquet", "json", "ndjson"))
def test_cli_python_tui_and_v2_catalog_execute_each_source_type(
    source_type: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extension = {
        "csv": ".csv",
        "parquet": ".parquet",
        "json": ".json",
        "ndjson": ".ndjson",
    }[source_type]
    locator = tmp_path / f"records{extension}"
    _write_fixture(locator, source_type)
    initialize_project(tmp_path)
    sql = "SELECT count(*) AS row_count FROM records"

    monkeypatch.chdir(tmp_path)
    extension_cli_result = runner.invoke(
        app,
        [
            "query",
            locator.name,
            sql,
            "--output",
            "json",
        ],
        catch_exceptions=False,
    )
    assert extension_cli_result.exit_code == 0, extension_cli_result.output
    assert json.loads(extension_cli_result.output)["rows"] == [{"row_count": 2}]

    cli_result = runner.invoke(
        app,
        [
            "query",
            locator.name,
            sql,
            "--type",
            source_type,
            "--output",
            "json",
        ],
        catch_exceptions=False,
    )
    assert cli_result.exit_code == 0, cli_result.output
    assert json.loads(cli_result.output)["rows"] == [{"row_count": 2}]

    definition = SourceDefinition(
        "records",
        locator.name,
        source_type=source_type,
        base_dir=tmp_path,
    )
    session = CSVQLSession.from_config(tmp_path)
    assert session.query(sql, sources=(definition,)).rows == ((2,),)

    tui_source = TUISource(
        name="records",
        locator=locator.name,
        anchor=tmp_path,
        source_type=source_type,
        origin="session",
    )
    assert query_sources((tui_source,), sql).rows == ((2,),)
    assert inspect_source(tui_source).columns

    context = add_project_table(
        load_project(tmp_path),
        "records",
        locator.name,
        invocation_dir=tmp_path,
    )
    assert context.config.version == CURRENT_VERSION
    assert isinstance(context.config, ProjectConfigV2)
    assert context.config.tables[0].source.source_type == source_type
    assert CSVQLSession.from_config(tmp_path).query(sql).rows == ((2,),)


@pytest.mark.parametrize("command", ("inspect", "sample", "profile"))
def test_cli_source_operations_detect_parquet_extension_without_type(
    command: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locator = tmp_path / "records.parquet"
    _write_fixture(locator, "parquet")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        [command, locator.name, "--output", "json"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["source"]["display_path"] == locator.name


def test_catalog_v1_rejects_provider_intent_and_v2_rejects_untyped_tui_save(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "records.csv"
    parquet_path = tmp_path / "records.parquet"
    _write_fixture(csv_path, "csv")
    _write_fixture(parquet_path, "parquet")
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables: {}\n", encoding="utf-8")
    before = config_path.read_bytes()
    parquet_source = TUISource(
        name="records",
        locator=parquet_path.name,
        anchor=tmp_path,
        source_type="parquet",
        origin="session",
    )

    with pytest.raises(ProjectConfigError) as migration_error:
        save_sources_to_project_catalog(
            (parquet_source,),
            start_dir=tmp_path,
            replace=False,
        )
    assert migration_error.value.code == "catalog.v1_migration_required"
    assert config_path.read_bytes() == before

    config_path.write_text("version: 2\ntables: {}\n", encoding="utf-8")
    untyped_source = TUISource(
        name="records",
        locator=csv_path.name,
        anchor=tmp_path,
        source_type=None,
        origin="session",
    )
    before = config_path.read_bytes()
    with pytest.raises(ProjectConfigError) as explicit_type_error:
        save_sources_to_project_catalog(
            (untyped_source,),
            start_dir=tmp_path,
            replace=False,
        )
    assert explicit_type_error.value.code == "catalog.source_type_required"
    assert config_path.read_bytes() == before
