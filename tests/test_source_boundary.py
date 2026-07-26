from __future__ import annotations

import ast
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
