from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def read_doc(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def normalized_markdown_text(text: str) -> str:
    return " ".join(text.split())


def test_readme_documents_cli_reusable_result_sources() -> None:
    readme = read_doc("README.md")

    assert "## Reusable Result Sources" in readme
    assert "mkdir -p .csvql/results" in readme
    assert "csvql export queries/revenue_health.sql" in readme
    assert "--out .csvql/results/revenue_health.csv" in readme
    assert "csvql add revenue_health_result .csvql/results/revenue_health.csv" in readme
    assert "--table revenue_health_result=.csvql/results/revenue_health.csv" in readme
    assert "normal CSV reuse" in readme
    assert "not a typed derived-source catalog feature" in readme


def test_public_onboarding_uses_installed_cli_command() -> None:
    public_docs = "\n".join(
        [
            read_doc("README.md"),
            read_doc("docs/getting-started.md"),
            read_doc("docs/troubleshooting.md"),
            read_doc("examples/saas_revenue/README.md"),
        ]
    )

    assert "Using LocalQL" in public_docs
    assert "csvql query examples/saas_revenue/data/revenue_movements.csv" in public_docs
    for command in (
        "query",
        "export",
        "check",
        "doctor",
        "inspect",
        "profile",
        "sample",
        "run",
        "add",
        "tables",
        "init",
    ):
        assert f"uv run csvql {command}" not in public_docs


def test_manual_qa_matrix_covers_cli_and_tui_release_paths() -> None:
    matrix = read_doc("docs/v1-manual-qa.md")

    assert "# CSVQL V1 Manual QA Matrix" in matrix
    assert "- [ ] CLI single-file query" in matrix
    assert "- [ ] CLI project catalog query" in matrix
    assert "- [ ] CLI export and reuse as CSV source" in matrix
    assert "- [ ] TUI launch" in matrix
    assert "- [ ] TUI repeated query" in matrix
    assert "- [ ] TUI Run Buffer exercise" in matrix
    assert "- [ ] TUI derived save and query" in matrix
    assert "- [ ] Bad SQL" in matrix
    assert "- [ ] TUI DDL metadata result" in matrix
    assert "CREATE OR REPLACE TABLE scratch AS SELECT 1 AS value;" in matrix
    assert "`Count` metadata" in matrix
    assert "- [ ] Export overwrite refusal and force" in matrix
    assert "- [ ] Missing file behavior" in matrix
    assert "- [ ] Quit path" in matrix
    assert "- [ ] Mac keybinding path" in matrix
    assert "CREATE TEMP TABLE movement_counts AS" in matrix
    assert "FROM revenue_movements" in matrix
    assert "FROM enerflo_payloads" not in matrix
    assert (
        "Expected: `F12` or `Ctrl+B` records one History row per statement, preserves"
        in matrix
    )


def test_tui_qol_qa_gate_is_blocking_and_records_terminal_evidence() -> None:
    matrix = read_doc("docs/tui-qol-qa.md")
    normalized_matrix = normalized_markdown_text(matrix)

    assert "# TUI QoL QA Gate" in matrix
    assert "Any failed item blocks `release-candidate eligible`." in matrix
    for terminal in (
        "macOS Terminal",
        "iTerm2",
        "VS Code terminal",
        "Linux terminal",
        "Windows Terminal",
        "tmux/SSH",
    ):
        assert terminal in matrix
    for flow in (
        "Launch empty",
        "Launch with one CSV",
        "Launch from a project catalog",
        "Add a source with `F3` or `Ctrl+O`",
        "Add a source through the Add Source prompt",
        "Add source by pasted standalone path",
        "Run selected SQL",
        "Run the current statement",
        "Run Buffer with `F12` or `Ctrl+B`",
        "Select multi-result output from Run Buffer",
        "Rerun History rows",
        "Export active result",
        "Save active result as a derived source",
        "Save a derived source from a recalled History result",
        "Open and close help repeatedly from every pane",
        "Try every documented key from every pane",
        "Resize the terminal while using each pane",
        "Run invalid SQL",
        "Run SQL against a missing source or missing file path",
        "Run DDL or no-result SQL",
        "Run batch SQL where a middle statement fails",
    ):
        assert flow in matrix
    assert "output/tui-qol-qa/<run-id>/<terminal-id>/" in matrix
    assert "media evidence is required for every terminal run" in matrix
    assert "Which pane is active?" in matrix
    assert (
        "Which source, query, History row, result, export, or derived-source target is affected?"
        in matrix
    )
    for required_text in (
        "multi-result selection",
        "active result",
        "CSV paths inside SQL strings, comments, or expressions",
    ):
        assert required_text in matrix
    assert "Run Buffer with `F12` or `Ctrl+B`" in normalized_matrix
    stale_wording_scan = "\n".join(
        [
            matrix,
            read_doc("docs/v1-manual-qa.md"),
            read_doc("docs/getting-started.md"),
        ]
    )
    assert "Run full-buffer multi-statement SQL with `F12`" not in stale_wording_scan


def test_manual_qa_matrix_links_tui_qol_gate() -> None:
    matrix = read_doc("docs/v1-manual-qa.md")

    assert "[TUI QoL QA gate](tui-qol-qa.md)" in matrix
    assert "The TUI QoL QA gate is blocking for `release-candidate eligible`." in matrix


def test_release_readiness_links_manual_qa_matrix() -> None:
    readiness = read_doc("docs/release-readiness.md")

    assert "[Manual v1 QA matrix](v1-manual-qa.md)" in readiness
    assert "[TUI QoL QA gate](tui-qol-qa.md)" in readiness
    assert "Run the manual v1 QA matrix" in readiness
    assert "Run the TUI QoL QA gate" in readiness
    assert "Any failed TUI QoL matrix item blocks `release-candidate eligible`." in readiness
    assert "TUI QoL run id" in readiness
    assert "docs/v1-manual-qa.md" in readiness
    assert "docs/tui-qol-qa.md" in readiness


def test_release_notes_require_manual_qa_and_tui_qol_gates() -> None:
    release_notes = read_doc("docs/release-notes/v1.md")
    normalized_release_notes = normalized_markdown_text(release_notes)

    assert "[Manual v1 QA matrix](../v1-manual-qa.md)" in release_notes
    assert "[TUI QoL QA gate](../tui-qol-qa.md)" in release_notes
    assert (
        "Any failed TUI QoL matrix item blocks `release-candidate eligible`."
        in normalized_release_notes
    )
    assert (
        "Any untested or missing-media TUI QoL item also blocks `release-candidate eligible`."
        in normalized_release_notes
    )
    assert "docs/v1-manual-qa.md" in release_notes
    assert "docs/tui-qol-qa.md" in release_notes
    assert "TUI QoL run id" in release_notes
    assert "media artifact paths" in release_notes
    assert "manual v1 QA matrix is recorded for the candidate state" in release_notes
    assert (
        "the TUI QoL QA gate passes on every required terminal with a recorded run id,"
        in release_notes
    )
    assert "no failed, untested, or missing-media items" in release_notes


def test_public_launch_docs_state_security_and_release_boundaries() -> None:
    public_docs = "\n".join(
        [
            read_doc("README.md"),
            read_doc("docs/getting-started.md"),
            read_doc("docs/troubleshooting.md"),
            read_doc("docs/tui-guide.md"),
            read_doc("docs/tui-qol-qa.md"),
            read_doc("docs/faq.md"),
            read_doc("docs/development.md"),
            read_doc("SECURITY.md"),
            read_doc("CONTRIBUTING.md"),
        ]
    )

    required_boundaries = (
        "does not sandbox DuckDB",
        "trusted local DuckDB SQL",
        "Do not create a tag",
        "publish to PyPI",
        "create a GitHub release",
        "explicit exports",
        "claim `v1-stable`",
        "production readiness",
        "broad large-file proof",
    )
    for boundary in required_boundaries:
        assert boundary in public_docs
