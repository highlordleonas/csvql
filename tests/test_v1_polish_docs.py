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


def test_docs_warn_catalog_paths_can_reveal_local_locations() -> None:
    docs = "\n".join([read_doc("README.md"), read_doc("docs/tui-guide.md")])
    normalized_docs = normalized_markdown_text(docs)

    assert "external absolute paths and symlink-resolved paths outside the" in normalized_docs
    assert "machine-specific locations" in normalized_docs


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
    assert "Expected: `F12` or `Ctrl+B` records one History row per statement, preserves" in matrix
    assert "keep or select the intended active result" in matrix
    assert "save the last tabular result" not in matrix
    assert "save it with `Ctrl+S`" in matrix


def test_tui_workbench_svg_matches_repaired_run_buffer_and_active_result_labels() -> None:
    workbench_svg = read_doc("docs/assets/localql-tui-workbench.svg")

    assert "F12/Ctrl+B&#160;buffer" in workbench_svg
    assert "standalone&#160;CSV&#160;path&#160;adds&#160;source" in workbench_svg
    assert "Export&#160;active" in workbench_svg
    assert "&#160;F3&#160;" in workbench_svg
    for stale_text in (
        "F12&#160;all",
        "paste&#160;CSV&#160;path&#160;to&#160;add&#160;source",
        "Export&#160;result",
        "&#160;f3&#160;",
    ):
        assert stale_text not in workbench_svg


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


def test_tui_qol_docs_record_scope_closeout_without_release_eligibility() -> None:
    matrix = read_doc("docs/tui-qol-qa.md")
    normalized_matrix = normalized_markdown_text(matrix)

    assert "## Current Closeout Status" in matrix
    assert "macOS Terminal is the verified local pass row for this lane." in matrix
    assert "output/tui-qol-qa/20260706-c604a46/macos-terminal/" in matrix
    assert "VS Code integrated terminal is out of scope for this closeout." in matrix
    assert "recorded a keybinding failure" in matrix
    assert "iTerm2 is blocked locally because the app was unavailable." in matrix
    assert "Linux terminal and Windows Terminal were not run locally." in matrix
    assert "tmux/SSH is blocked locally because `tmux` was unavailable." in matrix
    assert "This closeout does not make the project `release-candidate eligible`." in matrix
    assert (
        "A future complete TUI QoL run used for release-candidate eligibility must cover:"
        in normalized_matrix
    )


def test_release_docs_keep_tui_qol_closeout_out_of_candidate_eligibility() -> None:
    manual_qa = read_doc("docs/v1-manual-qa.md")
    readiness = read_doc("docs/release-readiness.md")
    release_notes = read_doc("docs/release-notes/v1.md")

    assert (
        "The current TUI QoL scope closeout records macOS Terminal evidence and "
        "terminal gaps only; it does not satisfy the full TUI QoL terminal matrix." in manual_qa
    )

    required_release_wording = (
        "A local TUI QoL scope closeout that records only macOS Terminal evidence "
        "and terminal gaps is not enough for `release-candidate eligible`; the "
        "full required terminal matrix must pass with media evidence."
    )
    assert required_release_wording in readiness
    assert required_release_wording in release_notes


def test_public_docs_do_not_advertise_rejected_vscode_alt_fallbacks() -> None:
    public_docs = "\n".join(
        [
            read_doc("README.md"),
            read_doc("docs/getting-started.md"),
            read_doc("docs/tui-guide.md"),
            read_doc("docs/troubleshooting.md"),
            read_doc("docs/tui-qol-qa.md"),
            read_doc("docs/v1-manual-qa.md"),
            read_doc("docs/release-readiness.md"),
            read_doc("docs/release-notes/v1.md"),
        ]
    )

    for rejected_claim in (
        "`Alt+H`",
        "`Alt+R`",
        "`Alt+U`",
        "VS Code-friendly",
        "VS Code fallback",
    ):
        assert rejected_claim not in public_docs


def test_closed_vscode_fallback_spec_and_plan_remain_non_executable() -> None:
    spec = read_doc("docs/superpowers/specs/2026-07-07-vscode-alt-keybinding-fallback-design.md")
    plan = read_doc("docs/superpowers/plans/2026-07-07-vscode-alt-keybinding-fallback.md")

    assert "Superseded after failed pre-churn reachability evidence and user rescope." in spec
    assert "The lane is now closed. Do not implement this VS Code-specific fallback design" in spec
    assert "**Closed plan:** Do not execute this plan." in plan
    assert "VS Code integrated-terminal compatibility is now out of scope." in plan


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


def test_docs_describe_tui_active_result_not_last_successful_result() -> None:
    docs = "\n".join(
        [
            read_doc("README.md"),
            read_doc("docs/tui-guide.md"),
            read_doc("docs/release-notes/v1.md"),
        ]
    )
    normalized_docs = normalized_markdown_text(docs)

    assert "active result" in normalized_docs
    assert "last successful tabular query result" not in normalized_docs
    assert "last successful tabular result" not in normalized_docs
    assert ".markdown" in docs
    assert (
        "When Results is focused, `[` and `]` step through the buffer results." in normalized_docs
    )
    assert "The full workbench needs at least 100 columns by 30 rows." in normalized_docs


def test_docs_distinguish_f4_and_run_buffer_sessions() -> None:
    guide = read_doc("docs/tui-guide.md")

    assert "F4" in guide
    assert "fresh DuckDB session" in guide
    assert "Run Buffer" in guide
    assert "one shared DuckDB session" in guide


def test_docs_limit_csv_path_ingestion_to_paste_or_drop() -> None:
    docs = "\n".join([read_doc("docs/tui-guide.md"), read_doc("docs/tui-qol-qa.md")])

    assert "Pasted standalone `.csv` path text" in docs
    assert "ordinary editor text leaves it" in docs
    assert "file drop as pasted path text" in docs


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
        "The full workbench needs at least 100 columns by 30 rows.",
    )
    for boundary in required_boundaries:
        assert boundary in public_docs
