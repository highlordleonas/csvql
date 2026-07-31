from __future__ import annotations

import ast
import dataclasses
from pathlib import Path


def test_managed_read_csv_calls_are_owned_only_by_csv_adapter() -> None:
    src_root = Path(__file__).resolve().parents[1] / "src" / "csvql"
    owners: dict[str, list[int]] = {}

    for module_path in sorted(src_root.rglob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        read_csv_lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "read_csv"
        ]
        if read_csv_lines:
            owners[module_path.relative_to(src_root.parents[1]).as_posix()] = read_csv_lines

    assert set(owners) == {"src/csvql/csv_adapter.py"}
    assert owners["src/csvql/csv_adapter.py"]


def test_legacy_runtime_capability_types_are_retired() -> None:
    """Platform operations must not return as provider capability flags."""

    import csvql.source as source

    assert {
        "SOURCE_CAPABILITY_OPERATIONS",
        "SourceCapabilities",
        "SourceCapability",
        "SourceCapabilityStatus",
    }.isdisjoint(source.__dict__)


def test_resolved_source_is_resource_free_progressive_data() -> None:
    """Resolution must not leak adapters, bindings, cursors, or cleanup callbacks."""

    from csvql.source import ResolvedSource

    field_names = {field.name for field in dataclasses.fields(ResolvedSource)}

    assert {
        "adapter",
        "binding",
        "connection",
        "cursor",
        "cleanup",
    }.isdisjoint(field_names)


def test_source_coordinator_has_only_application_layer_dependencies() -> None:
    """The coordinator must remain thin and format neutral."""

    module_path = Path(__file__).resolve().parents[1] / "src" / "csvql" / "source_coordinator.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert "duckdb" not in imports
    assert not any(
        module.endswith("_adapter") and module != "csvql.source_adapter" for module in imports
    )
    assert not any(
        module.startswith(
            (
                "csvql.api",
                "csvql.cli",
                "csvql.csv_adapter",
                "csvql.export",
                "csvql.result_",
                "csvql.tui",
            )
        )
        for module in imports
    )
