from __future__ import annotations

import importlib
import sys
from types import ModuleType

import duckdb
import pytest

from csvql.source import (
    AmbiguousSource,
    DiagnosticCode,
    DiagnosticStage,
    RequiredAction,
    SelectedSource,
    SourceDiagnostic,
    build_source_request,
)
from csvql.source_registry import (
    DependencyRequirement,
    DescriptorRegistry,
    DescriptorView,
    SourceDescriptor,
)


def _factory_module():
    return importlib.import_module("csvql.adapter_factory")


def _selected(
    provider_key: str,
    *,
    factory_key: str,
    dependency: DependencyRequirement | None = None,
) -> SelectedSource:
    request = build_source_request(
        alias="orders",
        locator="orders.data",
        explicit_type=provider_key,
    )
    return SelectedSource(
        request=request,
        provider_key=provider_key,
        source_kind=provider_key,
        descriptor=DescriptorView(
            provider_key=provider_key,
            source_kind=provider_key,
            factory_key=factory_key,
            provider_interpretation_version="1",
            dependency=dependency,
        ),
        selection_reason="explicit_type",
        extension_evidence=None,
        options=(),
    )


def _install_provider_module(
    module_name: str,
    *,
    provider_key: str,
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> ModuleType:
    module = ModuleType(module_name)
    module.__version__ = "7.3"

    class Adapter:
        implementation_version = "7.3"

        def __init__(self, activation_facts) -> None:
            self.provider_key = provider_key
            self.activation_facts = activation_facts

        def resolve(self, selected, operation):
            raise NotImplementedError

        def bind(self, resolved, engine_session, binding_context):
            raise NotImplementedError

    def create_adapter(*, activation_facts):
        events.append(f"construct:{provider_key}")
        return Adapter(activation_facts)

    module.create_adapter = create_adapter
    monkeypatch.setitem(sys.modules, module_name, module)
    return module


def test_builtin_factory_registrations_compose_without_importing_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_module = importlib.import_module("csvql.source_registry")
    for module_name in (
        "csvql.csv_adapter",
        "csvql.parquet_adapter",
        "csvql.json_adapter",
        "csvql.ndjson_adapter",
        "csvql.excel_adapter",
    ):
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    table = _factory_module().build_builtin_lazy_adapter_table()
    registry = registry_module.build_builtin_descriptor_registry()
    _factory_module().AdapterFactory(registry, table)

    assert table.provider_keys == ("csv", "excel", "json", "ndjson", "parquet")
    assert table.registration("json").import_module == "csvql.json_adapter"
    assert table.registration("json").constructor_symbol == "_create_json_adapter"
    assert table.registration("ndjson").import_module == "csvql.json_adapter"
    assert table.registration("ndjson").constructor_symbol == "_create_ndjson_adapter"
    assert not any(
        module_name in sys.modules
        for module_name in (
            "csvql.csv_adapter",
            "csvql.parquet_adapter",
            "csvql.json_adapter",
            "csvql.ndjson_adapter",
            "csvql.excel_adapter",
        )
    )


def test_default_activation_context_reports_statically_linked_json_support() -> None:
    """JSON activation must use installed runtime facts without auto-installing."""

    from csvql.source_runtime import default_activation_context

    context = default_activation_context()

    assert "duckdb.extension.json" in context.available_dependencies
    assert dict(context.dependency_versions)["duckdb.extension.json"] == "v1.5.4"


def test_activation_metadata_connection_isolated_from_engine_connect_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Engine failure injection must not replace dependency metadata inspection."""

    from csvql.source_runtime import default_activation_context

    def reject_engine_connection(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("engine connection injection reached activation metadata")

    monkeypatch.setattr(duckdb, "connect", reject_engine_connection)

    context = default_activation_context()

    assert "duckdb.extension.json" in context.available_dependencies


def test_builtin_json_dependency_failure_precedes_provider_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing JSON support must remain a selected-provider activation outcome."""

    module = _factory_module()
    registry_module = importlib.import_module("csvql.source_registry")
    from csvql.exceptions import SourceActivationError

    registry = registry_module.build_builtin_descriptor_registry()
    table = module.build_builtin_lazy_adapter_table()
    imported: list[str] = []
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: imported.append(name),
    )

    with pytest.raises(SourceActivationError) as captured:
        module.AdapterFactory(registry, table).activate(
            _selected(
                "json",
                factory_key=registry.descriptor("json").factory_key,
                dependency=registry.descriptor("json").dependency,
            ),
            module.ActivationContext(duckdb_version="1.5.4"),
        )

    assert captured.value.code == "source.activation_dependency_missing"
    assert captured.value.provider_key == "json"
    assert captured.value.dependency_key == "duckdb.extension.json"
    assert imported == []


def test_factory_imports_and_constructs_only_selected_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _factory_module()
    events: list[str] = []
    alpha_module = "localql_test_provider_alpha"
    beta_module = "localql_test_provider_beta"
    _install_provider_module(
        alpha_module,
        provider_key="alpha",
        events=events,
        monkeypatch=monkeypatch,
    )
    _install_provider_module(
        beta_module,
        provider_key="beta",
        events=events,
        monkeypatch=monkeypatch,
    )
    registrations = module.LazyAdapterTable(
        (
            module.LazyAdapterRegistration(
                "alpha",
                "test.alpha",
                alpha_module,
                "create_adapter",
                None,
            ),
            module.LazyAdapterRegistration(
                "beta",
                "test.beta",
                beta_module,
                "create_adapter",
                "runtime.beta",
            ),
        )
    )
    registry = DescriptorRegistry.build(
        (
            SourceDescriptor("alpha", "alpha", factory_key="test.alpha"),
            SourceDescriptor(
                "beta",
                "beta",
                dependency=DependencyRequirement("runtime.beta", "python_module"),
                factory_key="test.beta",
            ),
        )
    )
    imported: list[str] = []
    real_import = importlib.import_module

    def recording_import(name: str):
        imported.append(name)
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", recording_import)
    factory = module.AdapterFactory(registry, registrations)

    adapter = factory.activate(
        _selected("alpha", factory_key="test.alpha"),
        module.ActivationContext(duckdb_version="1.5.0"),
    )

    assert adapter.provider_key == "alpha"
    assert adapter.activation_facts.provider_key == "alpha"
    assert adapter.activation_facts.adapter_implementation_version == "7.3"
    assert adapter.activation_facts.duckdb_version == "1.5.0"
    assert imported == [alpha_module]
    assert events == ["construct:alpha"]


def test_missing_selected_dependency_fails_before_provider_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _factory_module()
    from csvql.exceptions import SourceActivationError

    provider_module = "localql_missing_dependency_provider"
    registration = module.LazyAdapterRegistration(
        "future",
        "test.future",
        provider_module,
        "create_adapter",
        "runtime.future",
    )
    registry = DescriptorRegistry.build(
        (
            SourceDescriptor(
                "future",
                "future",
                dependency=DependencyRequirement(
                    "runtime.future",
                    "python_module",
                    extra="future",
                    guidance="Install the future source extra.",
                ),
                factory_key="test.future",
            ),
        )
    )
    imported: list[str] = []
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: imported.append(name),
    )
    factory = module.AdapterFactory(registry, module.LazyAdapterTable((registration,)))

    with pytest.raises(SourceActivationError) as captured:
        factory.activate(
            _selected(
                "future",
                factory_key="test.future",
                dependency=registry.descriptor("future").dependency,
            ),
            module.ActivationContext(),
        )

    assert captured.value.code == "source.activation_dependency_missing"
    assert captured.value.provider_key == "future"
    assert captured.value.dependency_key == "runtime.future"
    assert captured.value.suggestion == "Install the future source extra."
    assert imported == []


def test_unselected_dependencies_are_never_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _factory_module()
    events: list[str] = []
    alpha_module = "localql_selected_dependency_provider"
    _install_provider_module(
        alpha_module,
        provider_key="alpha",
        events=events,
        monkeypatch=monkeypatch,
    )
    registry = DescriptorRegistry.build(
        (
            SourceDescriptor(
                "alpha",
                "alpha",
                dependency=DependencyRequirement("runtime.alpha", "python_module"),
                factory_key="test.alpha",
            ),
            SourceDescriptor(
                "beta",
                "beta",
                dependency=DependencyRequirement("runtime.beta", "python_module"),
                factory_key="test.beta",
            ),
        )
    )
    table = module.LazyAdapterTable(
        (
            module.LazyAdapterRegistration(
                "alpha",
                "test.alpha",
                alpha_module,
                "create_adapter",
                "runtime.alpha",
            ),
            module.LazyAdapterRegistration(
                "beta",
                "test.beta",
                "unused.beta",
                "create_adapter",
                "runtime.beta",
            ),
        )
    )
    context = module.ActivationContext(
        available_dependencies=frozenset({"runtime.alpha"}),
        dependency_versions=(("runtime.alpha", "2.0"),),
    )

    adapter = module.AdapterFactory(registry, table).activate(
        _selected(
            "alpha",
            factory_key="test.alpha",
            dependency=registry.descriptor("alpha").dependency,
        ),
        context,
    )

    assert adapter.activation_facts.dependency_versions == (("runtime.alpha", "2.0"),)
    assert events == ["construct:alpha"]


def test_factory_runtime_rejects_non_selected_outcomes_before_import() -> None:
    module = _factory_module()
    request = build_source_request(alias="orders", locator="orders.data")
    action = RequiredAction("specify_type", ("future",))
    ambiguous = AmbiguousSource(
        request=request,
        diagnostic=SourceDiagnostic(
            code=DiagnosticCode.SOURCE_AMBIGUOUS,
            stage=DiagnosticStage.DETECTION,
            message="Explicit type required.",
            safe_source_reference="orders.data",
            required_action=action,
        ),
        candidates=("future",),
        required_action=action,
    )
    factory = module.AdapterFactory(DescriptorRegistry.build(()), module.LazyAdapterTable(()))

    with pytest.raises(TypeError, match="SelectedSource"):
        factory.activate(ambiguous, module.ActivationContext())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("missing_module", "source.activation_failed"),
        ("missing_symbol", "source.activation_failed"),
        ("constructor_failure", "source.activation_failed"),
        ("bad_contract", "source.provider_contract_invalid"),
    ],
)
def test_activation_failures_are_sanitized(
    failure_kind: str,
    expected_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _factory_module()
    from csvql.exceptions import SourceActivationError

    module_name = f"localql_broken_provider_{failure_kind}"
    provider_module = ModuleType(module_name)
    provider_module.__version__ = "1"
    if failure_kind == "constructor_failure":

        def create_adapter(*, activation_facts):
            raise RuntimeError("sensitive constructor detail")

        provider_module.create_adapter = create_adapter
    elif failure_kind == "bad_contract":
        provider_module.create_adapter = lambda *, activation_facts: object()
    elif failure_kind != "missing_symbol":
        monkeypatch.delitem(sys.modules, module_name, raising=False)
    if failure_kind in {"missing_symbol", "constructor_failure", "bad_contract"}:
        monkeypatch.setitem(sys.modules, module_name, provider_module)

    registry = DescriptorRegistry.build(
        (SourceDescriptor("future", "future", factory_key="test.future"),)
    )
    table = module.LazyAdapterTable(
        (
            module.LazyAdapterRegistration(
                "future",
                "test.future",
                module_name,
                "create_adapter",
                None,
            ),
        )
    )

    with pytest.raises(SourceActivationError) as captured:
        module.AdapterFactory(registry, table).activate(
            _selected("future", factory_key="test.future"),
            module.ActivationContext(),
        )

    assert captured.value.code == expected_code
    assert captured.value.provider_key == "future"
    assert "sensitive constructor detail" not in captured.value.message


def test_factory_rejects_descriptor_registration_dependency_mismatch() -> None:
    module = _factory_module()
    from csvql.exceptions import ConfigurationFailure

    registry = DescriptorRegistry.build(
        (
            SourceDescriptor(
                "future",
                "future",
                dependency=DependencyRequirement("runtime.expected", "python_module"),
                factory_key="test.future",
            ),
        )
    )
    table = module.LazyAdapterTable(
        (
            module.LazyAdapterRegistration(
                "future",
                "test.future",
                "future.module",
                "create_adapter",
                "runtime.different",
            ),
        )
    )

    with pytest.raises(ConfigurationFailure) as captured:
        module.AdapterFactory(registry, table)

    assert tuple(finding.code for finding in captured.value.findings) == (
        "factory_dependency_mismatch",
    )
