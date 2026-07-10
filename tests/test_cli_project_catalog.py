import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql.cli import app
from csvql.project_config import CONFIG_FILENAME, ProjectConfig, ProjectContext

runner = CliRunner()


def test_init_creates_catalog_in_current_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0, result.output
    config_path = tmp_path / CONFIG_FILENAME
    assert config_path.exists()
    assert config_path.read_text(encoding="utf-8") == "version: 1\ntables: {}\n"
    assert CONFIG_FILENAME in result.output


def test_init_success_output_encodes_terminal_controls_in_catalog_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsafe_directory = "project\x1b]0;spoof\x07\x7f\x85\x9b31m"
    display_project_root = tmp_path / unsafe_directory
    display_context = ProjectContext(
        project_root=display_project_root,
        config_path=display_project_root / CONFIG_FILENAME,
        config=ProjectConfig(version=1, tables=()),
    )
    monkeypatch.chdir(tmp_path)

    def fake_initialize_project(project_root: Path, *, force: bool = False) -> ProjectContext:
        assert project_root == tmp_path
        assert force is False
        return display_context

    monkeypatch.setattr("csvql.cli.initialize_project", fake_initialize_project)

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0, result.output
    assert all(control not in result.output for control in "\x1b\x07\x7f\x85\x9b")
    assert r"project\x1b]0;spoof\x07\x7f\x85\x9b31m" in result.output
    assert CONFIG_FILENAME in result.output


def test_init_refuses_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 8
    assert "already exists" in result.output
    assert "Pass --force" in result.output
    assert config_path.read_text(encoding="utf-8") == (
        "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n"
    )


def test_init_force_rewrites_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables:\n  orders:\n    path: old.csv\n", encoding="utf-8")

    result = runner.invoke(app, ["init", "--force"])

    assert result.exit_code == 0, result.output
    assert config_path.read_text(encoding="utf-8") == "version: 1\ntables: {}\n"
    assert "Created project catalog" in result.output


def test_add_writes_nested_table_entry_from_subdirectory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    nested_invocation_dir = project_root / "nested" / "invocation"
    csv_path = project_root / "data" / "orders.csv"
    nested_invocation_dir.mkdir(parents=True)
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")

    monkeypatch.chdir(project_root)
    runner.invoke(app, ["init"])

    monkeypatch.chdir(nested_invocation_dir)
    result = runner.invoke(app, ["add", "orders", "../../data/orders.csv"])

    assert result.exit_code == 0, result.output
    assert "orders" in result.output
    assert (project_root / CONFIG_FILENAME).read_text(encoding="utf-8") == (
        "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n"
    )


def test_add_success_output_encodes_terminal_controls_in_catalog_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsafe_directory = "project\x1b]0;spoof\x07\x7f\x85\x9b31m"
    display_project_root = tmp_path / unsafe_directory
    display_context = ProjectContext(
        project_root=display_project_root,
        config_path=display_project_root / CONFIG_FILENAME,
        config=ProjectConfig(version=1, tables=()),
    )
    monkeypatch.chdir(tmp_path)

    def fake_add_project_table(
        context: ProjectContext,
        name: str,
        path_value: str,
        *,
        replace: bool = False,
        invocation_dir: Path | None = None,
    ) -> ProjectContext:
        assert context is display_context
        assert name == "orders"
        assert path_value == "orders.csv"
        assert replace is False
        assert invocation_dir == tmp_path
        return display_context

    monkeypatch.setattr("csvql.cli.load_project", lambda: display_context)
    monkeypatch.setattr("csvql.cli.add_project_table", fake_add_project_table)

    result = runner.invoke(app, ["add", "orders", "orders.csv"])

    assert result.exit_code == 0, result.output
    assert all(control not in result.output for control in "\x1b\x07\x7f\x85\x9b")
    assert r"project\x1b]0;spoof\x07\x7f\x85\x9b31m" in result.output
    assert CONFIG_FILENAME in result.output


def test_add_rejects_duplicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    csv_path = tmp_path / "data" / "orders.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    runner.invoke(app, ["add", "orders", "data/orders.csv"])

    result = runner.invoke(app, ["add", "orders", "data/orders.csv"])

    assert result.exit_code == 8
    assert "already exists" in result.output
    assert "Pass --replace" in result.output


def test_add_replace_updates_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    orders_v1 = tmp_path / "data" / "orders.csv"
    orders_v2 = tmp_path / "data" / "orders_v2.csv"
    orders_v1.parent.mkdir(parents=True)
    orders_v1.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    orders_v2.write_text("order_id,total_amount\nORD-1,56.78\n", encoding="utf-8")
    runner.invoke(app, ["add", "orders", "data/orders.csv"])

    result = runner.invoke(app, ["add", "orders", "data/orders_v2.csv", "--replace"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / CONFIG_FILENAME).read_text(encoding="utf-8") == (
        "version: 1\ntables:\n  orders:\n    path: data/orders_v2.csv\n"
    )


def test_tables_table_output_contains_table_name_path_and_resolved_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    csv_path = tmp_path / "data" / "orders.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    runner.invoke(app, ["add", "orders", "data/orders.csv"])

    result = runner.invoke(app, ["tables"])

    assert result.exit_code == 0, result.output
    assert "orders" in result.output
    assert "data/orders.csv" in result.output
    assert "resolved_path" in result.output


def test_tables_json_output_is_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    alpha_path = tmp_path / "alpha.csv"
    orders_path = tmp_path / "data" / "orders.csv"
    orders_path.parent.mkdir(parents=True)
    alpha_path.write_text("id,value\n1,2\n", encoding="utf-8")
    orders_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    runner.invoke(app, ["add", "orders", "data/orders.csv"])
    runner.invoke(app, ["add", "alpha", "alpha.csv"])

    result = runner.invoke(app, ["tables", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "config_path": (tmp_path / CONFIG_FILENAME).resolve().as_posix(),
        "project_root": tmp_path.resolve().as_posix(),
        "tables": [
            {
                "name": "alpha",
                "path": "alpha.csv",
                "resolved_path": alpha_path.resolve().as_posix(),
            },
            {
                "name": "orders",
                "path": "data/orders.csv",
                "resolved_path": orders_path.resolve().as_posix(),
            },
        ],
    }


def test_missing_catalog_for_add_returns_project_config_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["add", "orders", "data/orders.csv"])

    assert result.exit_code == 8
    assert "No .csvql.yml project catalog found" in result.output


def test_missing_catalog_for_tables_returns_project_config_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["tables"])

    assert result.exit_code == 8
    assert "No .csvql.yml project catalog found" in result.output
