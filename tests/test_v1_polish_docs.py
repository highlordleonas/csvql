from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def read_doc(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


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
    assert "- [ ] TUI derived save and query" in matrix
    assert "- [ ] Bad SQL" in matrix
    assert "- [ ] TUI DDL metadata result" in matrix
    assert "CREATE OR REPLACE TABLE scratch AS SELECT 1 AS value;" in matrix
    assert "`Count` metadata" in matrix
    assert "- [ ] Export overwrite refusal and force" in matrix
    assert "- [ ] Missing file behavior" in matrix
    assert "- [ ] Quit path" in matrix
    assert "- [ ] Mac keybinding path" in matrix


def test_release_readiness_links_manual_qa_matrix() -> None:
    readiness = read_doc("docs/release-readiness.md")

    assert "[Manual v1 QA matrix](v1-manual-qa.md)" in readiness
    assert "Run the manual v1 QA matrix" in readiness
