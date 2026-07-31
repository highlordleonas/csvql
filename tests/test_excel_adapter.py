"""Excel adapter resolution, binding, and missing-dependency tests."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import duckdb
import pytest

import csvql.adapter_factory as factory_module
import csvql.engine as engine_module
from csvql.adapter_factory import ProviderActivationFacts
from csvql.engine import CSVQLEngine
from csvql.excel_adapter import ExcelSourceAdapter
from csvql.exceptions import SourceBindingError, SourceError
from csvql.operation import OperationContext, OperationToken
from csvql.source import (
    IdentityRequirement,
    IdentityStrength,
    IdentityValidationStatus,
    PreparedSources,
    ResolvedSource,
    SelectedSource,
    SourcePreparationFailure,
    build_source_request,
)
from csvql.source_adapter import BindingContext
from csvql.source_runtime import (
    build_default_source_components,
    prepare_source_requests,
    raise_preparation_failure,
)

_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOCUMENT_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _operation() -> OperationContext:
    return OperationContext(OperationToken())


def _write_workbook(
    path: Path,
    *,
    sheet_name: str = "Orders",
    dimension: str = "A1:B3",
) -> None:
    workbook_xml = (
        f'<workbook xmlns="{_SPREADSHEET_NS}" xmlns:r="{_DOCUMENT_REL_NS}">'
        f'<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/>'
        "</sheets></workbook>"
    ).encode()
    relationships_xml = (
        f'<Relationships xmlns="{_PACKAGE_REL_NS}">'
        f'<Relationship Id="rId1" Type="{_DOCUMENT_REL_NS}/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    ).encode()
    worksheet_xml = (
        f'<worksheet xmlns="{_SPREADSHEET_NS}"><dimension ref="{dimension}"/>'
        "<sheetData/></worksheet>"
    ).encode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            (b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'),
        )
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships_xml)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)


def _selected(
    path: Path,
    *,
    explicit_type: str | None = None,
    options: tuple[tuple[str, object], ...] = (),
) -> SelectedSource:
    request = build_source_request(
        alias="orders",
        locator=path.name,
        anchor=path.parent,
        explicit_type=explicit_type,
        options=options,
    )
    detected = build_default_source_components().detection.detect(
        request,
        operation=_operation(),
    )
    assert isinstance(detected, SelectedSource)
    return detected


def _adapter(*, type_version: str = "excel-test-v1") -> ExcelSourceAdapter:
    return ExcelSourceAdapter(
        activation_facts=ProviderActivationFacts(
            provider_key="excel",
            adapter_implementation_version="1",
            duckdb_version="1.5.4",
            dependency_versions=(("duckdb.extension.excel", type_version),),
        )
    )


def test_resolution_records_exact_sheet_range_options_and_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.xlsx"
    _write_workbook(path)
    selected = _selected(path)
    adapter = _adapter()

    first = adapter.resolve(selected, _operation())
    second = adapter.resolve(selected, _operation())

    assert isinstance(first, ResolvedSource)
    assert first.semantic_options == (
        ("header", True),
        ("range", "A1:B3"),
        ("sheet", "Orders"),
        ("stop_at_empty", False),
        ("type_mode", "text"),
    )
    assert first.dependency_versions == (("duckdb.extension.excel", "excel-test-v1"),)
    assert first.identity == second.identity
    facts = dict(first.provider_facts.items)
    assert facts["selected_sheet"] == "Orders"
    assert facts["resolved_range"] == "A1:B3"
    assert facts["sheet_source"] == "workbook_order"
    assert facts["range_source"] == "worksheet_dimension"
    assert facts["worksheet_part"] == "xl/worksheets/sheet1.xml"


def test_explicit_excel_type_accepts_extensionless_workbook(tmp_path: Path) -> None:
    path = tmp_path / "workbook"
    _write_workbook(path)

    resolved = _adapter().resolve(
        _selected(path, explicit_type="excel"),
        _operation(),
    )

    assert resolved.canonical_locator == str(path)
    assert resolved.selection_reason == "explicit_type"


class _FakeRelation:
    columns = ("id", "value")
    types = ("VARCHAR", "VARCHAR")

    def __init__(self, events: list[object]) -> None:
        self._events = events

    def create_view(self, alias: str, *, replace: bool) -> None:
        self._events.append(("create_view", alias, replace))


class _FakeConnection:
    def __init__(
        self,
        events: list[object],
        *,
        query_failure: duckdb.Error | None = None,
    ) -> None:
        self.events = events
        self.query_failure = query_failure

    def sql(self, query: str, *, params: list[object]) -> _FakeRelation:
        self.events.append(("sql", query, params))
        if self.query_failure is not None:
            raise self.query_failure
        return _FakeRelation(self.events)

    def execute(self, query: str) -> None:
        self.events.append(("execute", query))


class _FakeEngine:
    session_id = "excel-engine"
    has_active_execution = False
    is_tainted = False

    def __init__(
        self,
        *,
        query_failure: duckdb.Error | None = None,
    ) -> None:
        self.events: list[object] = []
        self.connection = _FakeConnection(
            self.events,
            query_failure=query_failure,
        )
        self._registered = False

    def assert_session_access(self) -> None:
        self.events.append("assert_session_access")

    def load_installed_extension(
        self,
        dependency_key: str,
        *,
        operation: OperationContext,
    ) -> None:
        operation.checkpoint()
        self.events.append(("load", dependency_key))

    def register_relation(
        self,
        *,
        alias: str,
        register,
        unregister,
        operation: OperationContext,
    ) -> object:
        operation.checkpoint()
        self.events.append(("register", alias))
        register(self.connection)
        self.unregister = unregister
        self._registered = True
        return "registration-token"

    def unregister_relation(
        self,
        registration_token: object,
        *,
        operation: OperationContext,
    ) -> None:
        operation.checkpoint()
        assert registration_token == "registration-token"
        if self._registered:
            self.unregister(self.connection)
            self._registered = False
            self.events.append(("unregister", registration_token))


def test_binding_uses_native_load_and_parameterized_static_read_xlsx(
    tmp_path: Path,
) -> None:
    path = tmp_path / "quoted.xlsx"
    sheet_name = "O'Brien Δ"
    _write_workbook(path, sheet_name=sheet_name, dimension="A1:D8")
    selected = _selected(
        path,
        options=(
            ("sheet", sheet_name),
            ("range", "'O''Brien Δ'!$B$2:$C$3"),
        ),
    )
    resolved = _adapter().resolve(selected, _operation())
    engine = _FakeEngine()

    binding = _adapter().bind(
        resolved,
        engine,
        BindingContext(_operation()),
    )

    load_index = engine.events.index(("load", "duckdb.extension.excel"))
    register_index = engine.events.index(("register", "orders"))
    sql_event = next(
        event for event in engine.events if isinstance(event, tuple) and event[0] == "sql"
    )
    assert load_index < register_index
    assert str(path) not in sql_event[1]
    assert sheet_name not in sql_event[1]
    assert sql_event[2] == [
        str(path),
        True,
        False,
        True,
        "B2:C3",
        False,
        sheet_name,
        False,
    ]
    assert "ignore_errors=?" in sql_event[1]
    assert "empty_as_varchar=?" in sql_event[1]
    assert binding.runtime_schema == (
        ("id", "VARCHAR"),
        ("value", "VARCHAR"),
    )

    binding.close(_operation())
    binding.close(_operation())
    assert engine.events.count(("unregister", "registration-token")) == 1


def test_infer_mode_failure_is_typed_and_never_falls_back_to_text(
    tmp_path: Path,
) -> None:
    path = tmp_path / "infer.xlsx"
    _write_workbook(path)
    resolved = _adapter().resolve(
        _selected(path, options=(("type_mode", "infer"),)),
        _operation(),
    )
    engine = _FakeEngine(query_failure=duckdb.InvalidInputException("cast failed"))

    with pytest.raises(SourceBindingError) as captured:
        _adapter().bind(
            resolved,
            engine,
            BindingContext(_operation()),
        )

    assert getattr(captured.value, "code", None) == ("source.excel_schema_inference_failed")
    sql_event = next(
        event for event in engine.events if isinstance(event, tuple) and event[0] == "sql"
    )
    assert sql_event[2][3] is False
    assert (
        len([event for event in engine.events if isinstance(event, tuple) and event[0] == "sql"])
        == 1
    )


def test_binding_revalidation_supports_observational_and_exact_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identity.xlsx"
    _write_workbook(path)
    resolved = _adapter().resolve(_selected(path), _operation())
    binding = _adapter().bind(
        resolved,
        _FakeEngine(),
        BindingContext(_operation()),
    )

    observational = binding.revalidate(
        IdentityRequirement(IdentityStrength.OBSERVATIONAL),
        _operation(),
    )
    exact = binding.revalidate(
        IdentityRequirement(IdentityStrength.EXACT),
        _operation(),
    )

    assert observational.status is IdentityValidationStatus.CONFIRMED
    assert exact.status is IdentityValidationStatus.CONFIRMED
    assert exact.evidence_digest is not None

    path.write_bytes(path.read_bytes() + b"changed")
    changed = binding.revalidate(
        IdentityRequirement(IdentityStrength.OBSERVATIONAL),
        _operation(),
    )
    assert changed.status is IdentityValidationStatus.CHANGED
    binding.close(_operation())


def test_missing_excel_extension_fails_after_selection_before_provider_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "orders.xlsx"
    _write_workbook(path)
    extension_directory = tmp_path / "isolated-extensions"
    extension_directory.mkdir()
    real_connect = duckdb.connect

    def isolated_connect(*args: object, **kwargs: object):
        config = dict(kwargs.get("config", {}))
        config["extension_directory"] = str(extension_directory)
        kwargs["config"] = config
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(engine_module.duckdb, "connect", isolated_connect)
    imported: list[str] = []
    real_import = factory_module.importlib.import_module

    def recording_import(name: str):
        imported.append(name)
        return real_import(name)

    monkeypatch.setattr(factory_module.importlib, "import_module", recording_import)
    monkeypatch.delitem(sys.modules, "csvql.excel_adapter", raising=False)
    request = build_source_request(
        alias="orders",
        locator=path.name,
        anchor=path.parent,
    )

    with CSVQLEngine(operation=_operation()) as engine:
        outcome = prepare_source_requests(
            (request,),
            engine_session=engine,
            operation=engine.operation_context,
        )

    assert isinstance(outcome, SourcePreparationFailure)
    assert not isinstance(outcome, PreparedSources)
    assert outcome.diagnostics[0].code.value == ("source.activation_dependency_missing")
    assert outcome.diagnostics[0].stage.value == "activation"
    assert any(
        evidence.evidence_kind == "dependency_key"
        and evidence.stable_detail == "duckdb.extension.excel"
        for evidence in outcome.diagnostics[0].evidence
    )
    assert any(
        evidence.evidence_kind == "dependency_guidance"
        and "separate networked action" in evidence.stable_detail
        for evidence in outcome.diagnostics[0].evidence
    )
    with pytest.raises(SourceError) as legacy:
        raise_preparation_failure(outcome, requests=(request,))
    assert legacy.value.code == "missing_optional_dependency"
    assert "separate networked action" in (legacy.value.suggestion or "")
    assert "csvql.excel_adapter" not in imported
    assert not tuple(extension_directory.rglob("*.duckdb_extension"))
