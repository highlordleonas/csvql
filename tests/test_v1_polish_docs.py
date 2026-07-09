from pathlib import Path

import yaml

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
    assert "/private/tmp/uv-cache-csvql-localql" in matrix
    assert "UV_CACHE_DIR=/private/tmp/uv-cache uv run" not in matrix


def test_tui_workbench_svg_matches_repaired_run_buffer_and_active_result_labels() -> None:
    workbench_svg = read_doc("docs/assets/localql-tui-workbench.svg")

    assert "ACTIVE&#160;RESULT:&#160;query&#160;1" in workbench_svg
    assert "Result&#160;target:&#160;active&#160;result" in workbench_svg
    assert "Showing&#160;5&#160;returned&#160;row(s)." in workbench_svg
    assert "Export&#160;active" in workbench_svg
    assert "Ctrl+S/Alt+S" in workbench_svg
    assert "Save&#160;active" in workbench_svg
    assert "examples/saas_rev" in workbench_svg
    for stale_text in (
        "F12&#160;all",
        "paste&#160;CSV&#160;path&#160;to&#160;add&#160;source",
        "Export&#160;result",
        "/Users/",
        "richard",
        "Dropbox",
        "&#160;f3&#160;",
    ):
        assert stale_text not in workbench_svg


def test_tui_qol_qa_gate_is_blocking_and_records_rescoped_terminal_evidence() -> None:
    matrix = read_doc("docs/tui-qol-qa.md")
    normalized_matrix = normalized_markdown_text(matrix)
    required_scope = matrix.split("## Out-of-Scope Rows", 1)[0]

    assert "# TUI QoL QA Gate" in matrix
    assert "Any failed required item blocks `release-candidate eligible`." in matrix
    assert "| macOS Terminal | `output/tui-qol-qa/<run-id>/macos-terminal/` |" in required_scope
    assert "`output/tui-qol-qa/<run-id>/windows-terminal/`" in matrix
    assert "`output/tui-qol-qa/<run-id>/linux-terminal/`" in matrix
    for stale_required_row in (
        "| Windows Terminal |",
        "| GNOME Terminal or equivalent normal Linux desktop terminal |",
        "| iTerm2 |",
        "| VS Code terminal |",
        "| VS Code integrated terminal |",
        "| Linux terminal |",
        "| tmux/SSH |",
    ):
        assert stale_required_row not in required_scope
    for out_of_scope_terminal in (
        "VS Code integrated terminal",
        "iTerm2",
        "tmux/SSH",
    ):
        assert out_of_scope_terminal in matrix
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
    assert "media evidence is required for every terminal run" not in matrix
    assert (
        "Windows and Linux screenshots or manual terminal media are not required"
        in normalized_matrix
    )
    assert "Windows and Linux manual runs are optional context" in normalized_matrix
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

    assert "## Approved Cross-OS Automated Release-Proof Scope" in matrix
    assert "Historical local evidence remains useful context:" in matrix
    assert (
        "The approved release-proof target now uses same-`HEAD` automated support proof"
        in normalized_matrix
    )
    assert "on macOS, native Windows, and Linux" in normalized_matrix
    assert (
        "Windows and Linux manual terminal screenshots are no longer required" in normalized_matrix
    )
    assert "output/tui-qol-qa/20260707-0a946cc-three-os-tui/macos-terminal/" in matrix
    assert "VS Code integrated terminal is out of scope for this release lane after the" in matrix
    assert "keybinding spike showed default macOS Option-key behavior did not" in matrix
    assert "iTerm2 and tmux/SSH are out of scope for this release lane." in matrix
    assert "screenshots are not required for those OS rows" in matrix
    assert "This approved scope does not make the project `release-candidate eligible`." in matrix
    assert (
        "This is a rescoped release-proof lane, not a claim that the project is already"
        in normalized_matrix
    )


def test_tui_qol_gate_uses_approved_cross_os_automated_release_scope() -> None:
    matrix = read_doc("docs/tui-qol-qa.md")
    normalized_matrix = normalized_markdown_text(matrix)

    assert "## Approved Cross-OS Automated Release-Proof Scope" in matrix
    assert (
        "same-`HEAD` automated support proof on macOS, native Windows, and Linux"
        in normalized_matrix
    )
    assert "## Out-of-Scope Rows" in matrix
    required_scope = matrix.split("## Out-of-Scope Rows", 1)[0]
    assert "| macOS Terminal | `output/tui-qol-qa/<run-id>/macos-terminal/` |" in required_scope
    assert (
        "| Windows Terminal | `output/tui-qol-qa/<run-id>/windows-terminal/` |"
        not in required_scope
    )
    assert "| GNOME Terminal or equivalent normal Linux desktop terminal |" not in required_scope
    assert "Optional Windows or Linux manual terminal evidence may be recorded" in normalized_matrix
    assert (
        "those media paths are not required for `release-candidate eligible`" in normalized_matrix
    )
    for old_required_row in (
        "| iTerm2 |",
        "| VS Code terminal |",
        "| tmux/SSH |",
    ):
        assert old_required_row not in required_scope
    for out_of_scope in (
        "VS Code integrated terminal",
        "iTerm2",
        "tmux/SSH",
    ):
        assert out_of_scope in matrix
    assert "native Windows environment and native Windows Python/`uv` setup" in normalized_matrix
    assert "A Windows Terminal tab running WSL counts as Linux/WSL context" in normalized_matrix
    assert "not native Windows proof" in matrix
    assert "default terminal settings" in matrix


def test_tui_qol_gate_defines_automated_support_and_result_packet() -> None:
    matrix = read_doc("docs/tui-qol-qa.md")
    normalized_matrix = normalized_markdown_text(matrix)

    for required_text in (
        "## Required Automated Support Proof",
        "one run on macOS, one run on native Windows, and one run on Linux",
        "Python 3.12 on each OS",
        "uv sync --all-extras --frozen",
        "uv run ruff format --check .",
        "uv run ruff check .",
        "uv run --all-extras mypy src",
        "uv run --all-extras pytest",
        "uv --version",
        "uv run python --version",
        "uv run --all-extras csvql --version",
        "Plain `csvql --version` is not sufficient for source-checkout proof",
        "commands/automated-macos.*",
        "commands/automated-windows.*",
        "commands/automated-linux.*",
        "source access method",
        "commit verification command",
        "local or observer-provided",
        "A local `pass` result from this lane is evidence only",
        "## Classification Rules",
    ):
        assert required_text in matrix
    assert "observer timestamp" in normalized_matrix
    for required_text in (
        "`pass`: all three automated support rows pass",
        "`fail`: a required automated command runs and fails, or a cited required",
        "`blocked`: required evidence is missing, stale, untrusted, lacks approved",
    ):
        assert required_text in normalized_matrix


def test_release_docs_keep_tui_qol_closeout_out_of_candidate_eligibility() -> None:
    manual_qa = read_doc("docs/v1-manual-qa.md")
    readiness = read_doc("docs/release-readiness.md")
    release_notes = read_doc("docs/release-notes/v1.md")
    normalized_manual_qa = normalized_markdown_text(manual_qa)

    assert (
        "The approved TUI release-proof target now requires same-`HEAD` automated "
        "support proof on macOS, native Windows, and Linux." in normalized_manual_qa
    )
    assert (
        "Windows and Linux screenshots or manual terminal media are no longer required"
        in normalized_manual_qa
    )
    assert "A local `pass` result from this lane is evidence only." in readiness
    assert "A local `pass` result from this lane is evidence only." in release_notes
    assert "Changing any release label" in readiness
    assert "Changing any release label" in release_notes


def test_release_docs_require_approved_cross_os_automated_tui_proof_gate() -> None:
    manual_qa = read_doc("docs/v1-manual-qa.md")
    readiness = read_doc("docs/release-readiness.md")
    release_notes = read_doc("docs/release-notes/v1.md")
    combined = "\n".join([manual_qa, readiness, release_notes])
    normalized_combined = normalized_markdown_text(combined)

    assert (
        "same-`HEAD` automated support proof on macOS, native Windows, and Linux"
        in normalized_combined
    )
    assert "three-OS automated support proof" in combined
    assert (
        "Windows and Linux screenshots or manual terminal media are no longer required"
        in normalized_combined
    )
    assert "uv sync --all-extras --frozen" in combined
    assert "uv run --all-extras csvql --version" in combined
    assert "Plain `csvql --version` is not sufficient for source-checkout proof" in combined
    assert "A local `pass` result from this lane is evidence only" in combined
    assert "Changing any release label" in combined
    assert "VS Code integrated terminal, iTerm2, and tmux/SSH are out of scope" in combined
    for stale_required_row in (
        "the older six-row matrix",
        "macOS Terminal, Windows Terminal, and one normal Linux desktop terminal",
        "iTerm2 | `output/tui-qol-qa/<run-id>/iterm2/`",
        "VS Code terminal | `output/tui-qol-qa/<run-id>/vscode-terminal/`",
        "tmux/SSH | `output/tui-qol-qa/<run-id>/tmux-ssh/`",
    ):
        assert stale_required_row not in normalized_combined


def test_cross_os_proof_docs_record_prior_proof_without_current_head_claim() -> None:
    tui_qol = read_doc("docs/tui-qol-qa.md")
    readiness = read_doc("docs/release-readiness.md")
    release_notes = read_doc("docs/release-notes/v1.md")
    combined = "\n".join([tui_qol, readiness, release_notes])
    normalized_combined = normalized_markdown_text(combined)

    for required_text in (
        "b118a2c",
        "blocked `b118a2c`",
        "superseded",
        "d8ec3df",
        "28965686605",
        "historical prior proof context",
        "not final proof for later implementation commits",
        "ignored proof packet `RESULT.md` and final execution response",
        "must not require a self-referential run id",
    ):
        assert required_text in normalized_combined

    assert "Windows and Linux screenshots or manual terminal media are not required" in (
        normalized_combined
    )
    assert "automated proof does not prove manual terminal UX" in normalized_combined
    assert "`v1-stable`" in combined


def test_ci_workflow_collects_three_os_automated_support_gate() -> None:
    ci = read_doc(".github/workflows/ci.yml")
    workflow = yaml.safe_load(ci)
    test_job = workflow["jobs"]["test"]
    matrix_rows = test_job["strategy"]["matrix"]["include"]
    matrix_pairs = {(str(row["os"]), str(row["python-version"])) for row in matrix_rows}

    assert {
        ("ubuntu-latest", "3.11"),
        ("ubuntu-latest", "3.12"),
        ("ubuntu-latest", "3.13"),
        ("ubuntu-latest", "3.14"),
        ("macos-latest", "3.12"),
        ("windows-latest", "3.12"),
    } <= matrix_pairs

    job_env = test_job.get("env", {}) or {}
    steps = test_job["steps"]
    step_runs = "\n".join(str(step.get("run", "")) for step in steps if isinstance(step, dict))
    forced_by_env = job_env.get("UV_PYTHON") == "${{ matrix.python-version }}"
    forced_by_run_arg = "--python ${{ matrix.python-version }}" in step_runs

    assert forced_by_env or forced_by_run_arg

    for required_text in (
        "ubuntu-latest",
        "macos-latest",
        "windows-latest",
        "uv python install ${{ matrix.python-version }}",
        "uv sync --all-extras --frozen",
        "pwd -P",
        "git status --short --branch",
        "git log -1 --oneline",
        "git remote -v",
        "git tag --points-at HEAD",
        "uv --version",
        "uv run python --version",
        "uv run --all-extras csvql --version",
        "fetch-depth: 0",
        "uv run ruff format --check .",
        "uv run ruff check .",
        "uv run --all-extras mypy src",
        "uv run --all-extras pytest",
        "shell: bash",
    ):
        assert required_text in ci


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
    normalized_readiness = normalized_markdown_text(readiness)

    assert "[Manual v1 QA matrix](v1-manual-qa.md)" in readiness
    assert "[TUI QoL QA gate](tui-qol-qa.md)" in readiness
    assert "Run the manual v1 QA matrix" in readiness
    assert "Run the TUI QoL QA gate" in readiness
    assert "TUI QoL run id" in readiness
    assert "docs/v1-manual-qa.md" in readiness
    assert "docs/tui-qol-qa.md" in readiness
    assert "approved cross-OS automated TUI proof gate" in normalized_readiness
    assert "three-OS automated support proof" in readiness
    assert "Plain `csvql --version` is not sufficient for source-checkout proof" in readiness
    assert "A local `pass` result from this lane is evidence only." in readiness
    local_candidate_workflow = readiness.split("## Local Candidate Workflow", 1)[1]
    for required_text in (
        "pwd -P",
        "git status --short --branch",
        "git log -1 --oneline",
        "git remote -v",
        "git tag --points-at HEAD",
        "uv --version",
        "uv run python --version",
        "uv run --all-extras csvql --version",
    ):
        assert required_text in local_candidate_workflow
    for required_text in (
        "baseline transcripts",
        "source access method",
        "commit verification command",
        "no failed or missing required checks",
        "same-`HEAD` three-OS automated support proof passes",
    ):
        assert required_text in normalized_readiness


def test_release_notes_require_manual_qa_and_tui_qol_gates() -> None:
    release_notes = read_doc("docs/release-notes/v1.md")
    normalized_release_notes = normalized_markdown_text(release_notes)

    assert "[Manual v1 QA matrix](../v1-manual-qa.md)" in release_notes
    assert "[TUI QoL QA gate](../tui-qol-qa.md)" in release_notes
    assert "docs/v1-manual-qa.md" in release_notes
    assert "docs/tui-qol-qa.md" in release_notes
    assert "TUI QoL run id" in release_notes
    assert "required automated proof outputs" in release_notes
    assert "manual v1 QA matrix is recorded for the candidate state" in release_notes
    assert "three-OS automated support proof" in release_notes
    assert "Python 3.11 through Python 3.14 support proof passes" in release_notes
    assert (
        "Windows and Linux screenshots or manual terminal media are no longer required"
        in normalized_release_notes
    )
    assert "A local `pass` result from this lane is evidence only." in release_notes
    assert "baseline transcripts" in release_notes
    assert "source access method" in release_notes
    assert "commit verification command" in release_notes
    assert (
        "the TUI QoL QA gate records the required automated proof outputs and any cited"
        in release_notes
    )
    assert "no failed or missing required checks" in normalized_release_notes
    assert "same candidate `HEAD`" in release_notes


def test_public_docs_record_pre_release_hardening_without_stable_claim() -> None:
    public_docs = "\n".join(
        [
            read_doc("README.md"),
            read_doc("CHANGELOG.md"),
            read_doc("docs/PRODUCT_DIRECTION.md"),
            read_doc("docs/ROADMAP.md"),
            read_doc("docs/release-notes/v1.md"),
        ]
    )

    for required_text in (
        "`v1-hardening`",
        "final hardening `HEAD`",
        "Python 3.13 and Python 3.14 support proof",
        "PyPI upload",
        "GitHub release",
        "`v1-stable`",
    ):
        assert required_text in public_docs
    assert "`v1.0.0-rc1` at `74b193e` is `release-candidate eligible`" not in public_docs
    assert "`74b193e` classified as `release-candidate eligible`" not in public_docs


def test_docs_describe_tui_active_result_not_last_successful_result() -> None:
    docs = "\n".join(
        [
            read_doc("README.md"),
            read_doc("CHANGELOG.md"),
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
