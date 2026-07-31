from __future__ import annotations

import ast
from pathlib import Path

from csvql.operation import OperationContext, OperationToken


def test_source_adapter_module_contains_only_the_narrow_behavioral_contracts() -> None:
    """Reintroducing registry or capability classes would duplicate descriptor policy."""

    import csvql.source_adapter as module

    assert {
        "BindingContext",
        "EngineDependencyState",
        "EngineSession",
        "RelationalBinding",
        "SourceAdapter",
        "SourceIdentifier",
    }.issubset(module.__dict__)
    assert {
        "AdapterInspectionMetadata",
        "PreparedBinding",
        "SourceAdapterDescriptor",
        "SourceAdapterRegistry",
        "require_capability",
    }.isdisjoint(module.__dict__)


def test_source_adapter_contract_does_not_import_duckdb_or_concrete_providers() -> None:
    """Core adapter contracts must not acquire runtime or format dependencies."""

    module_path = Path(__file__).resolve().parents[1] / "src" / "csvql" / "source_adapter.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )

    assert "duckdb" not in imported_modules
    assert not any(module.endswith("_adapter") for module in imported_modules)


def test_binding_context_carries_only_the_shared_operation_context() -> None:
    """Adding provider options to binding context would leak normalization outward."""

    from csvql.source_adapter import BindingContext

    operation = OperationContext(OperationToken())

    context = BindingContext(operation=operation)

    assert context.operation is operation
    assert tuple(context.__dataclass_fields__) == ("operation",)


def test_engine_dependency_state_carries_one_selected_runtime_observation() -> None:
    """A global dependency inventory would probe providers that were never selected."""

    from csvql.source_adapter import EngineDependencyState

    state = EngineDependencyState(
        dependency_key="duckdb.extension.excel",
        available=True,
        dependency_version="excel-v1",
        duckdb_version="1.5.4",
    )

    assert state.dependency_key == "duckdb.extension.excel"
    assert state.available is True
    assert state.dependency_version == "excel-v1"
