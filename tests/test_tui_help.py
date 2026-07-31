from pathlib import Path

from csvql.tui_help import WORKBENCH_HELP


def _read_doc_text(relative_path: str) -> str:
    return (Path(__file__).resolve().parents[1] / relative_path).read_text(encoding="utf-8")


def _normalized_markdown_text(text: str) -> str:
    return " ".join(text.split())


def test_workbench_help_freezes_current_keymap_and_export_language() -> None:
    assert WORKBENCH_HELP.startswith("LocalQL Workbench")
    assert "F4 / Ctrl+R         Run selected SQL, otherwise current statement" in WORKBENCH_HELP
    assert "F12 / Ctrl+B        Run Buffer" in WORKBENCH_HELP
    assert "F3 / Ctrl+O         Choose local source file(s) or prompt for a path" in WORKBENCH_HELP
    assert "LocalQL displays bounded evidence and never guesses between candidates." in (
        WORKBENCH_HELP
    )
    assert (
        "F7                  Export active result "
        "(.csv, .json, .ndjson, .parquet, .xlsx, .md, .txt)" in WORKBENCH_HELP
    )
    assert "Ctrl+S              Save active result to .csvql/results/{alias}.csv" in WORKBENCH_HELP
    assert "r                   Rerun selected query with current session sources" in WORKBENCH_HELP


def test_workbench_help_keeps_sql_completion_and_source_intelligence_wording() -> None:
    assert "Tab                 Complete SQL if available, otherwise indent" in WORKBENCH_HELP
    assert (
        "Ctrl+Space          Alternate SQL completion where terminal supports it" in WORKBENCH_HELP
    )
    assert "i                   Inspect selected source and load columns" in WORKBENCH_HELP
    assert "c                   Load/show selected source columns" in WORKBENCH_HELP
    assert "x                   Open starter SQL templates" in WORKBENCH_HELP


def test_workbench_help_explains_bounded_preview_and_preservation_lifecycle() -> None:
    assert "bounded preview appears while the same execution preserves" in WORKBENCH_HELP
    assert "rows, logical bytes, elapsed time, and remaining capacity" in WORKBENCH_HELP
    assert "Complete" in WORKBENCH_HELP
    assert "Preview-only" in WORKBENCH_HELP
    assert "does not rerun SQL" in WORKBENCH_HELP
    assert "Esc                 Cancel active execution or preservation" in WORKBENCH_HELP


def test_tui_docs_freeze_run_labels_and_menu_entry_points() -> None:
    guide = _normalized_markdown_text(_read_doc_text("docs/tui-guide.md"))
    troubleshooting = _read_doc_text("docs/troubleshooting.md")

    assert "The History run column labels entries as `current` for F4/Ctrl+R runs," in guide
    assert "`buffer` for F12/Ctrl+B runs" in guide
    assert "`rerun` for History reruns." in guide
    assert "Use `F4` or `Ctrl+R` to run the current SQL." in troubleshooting
    assert "`F3` opens a native source picker on macOS." in troubleshooting
    assert "`F3` or `Ctrl+O` opens the portable path prompt." in troubleshooting
    assert "Press `a` in Sources for the" in troubleshooting
    assert "[Workbench guide](tui-guide.md)" in troubleshooting
