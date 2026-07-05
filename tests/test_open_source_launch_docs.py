from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_open_source_trust_files_exist() -> None:
    for path in (
        "LICENSE",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "SUPPORT.md",
        "docs/development.md",
        "docs/faq.md",
    ):
        assert (REPO_ROOT / path).is_file(), path


def test_removed_internal_operator_material_is_not_on_public_branch() -> None:
    for path in (
        "AGENTS.md",
        "docs/CODEX_CAPABILITY_REVIEW.md",
    ):
        assert not (REPO_ROOT / path).exists(), path
    assert not list((REPO_ROOT / "docs").glob("release-candidate-proof-*.md"))


def test_readme_links_public_launch_docs() -> None:
    readme = read_text("README.md")

    for expected in (
        "[FAQ](docs/faq.md)",
        "[Contributing](CONTRIBUTING.md)",
        "[Security](SECURITY.md)",
        "[Development](docs/development.md)",
        "[Support](SUPPORT.md)",
    ):
        assert expected in readme


def test_public_docs_do_not_reference_removed_internal_material() -> None:
    public_docs = "\n".join(
        [
            read_text("README.md"),
            read_text("CHANGELOG.md"),
            read_text("docs/development.md"),
            read_text("docs/PRODUCT_DIRECTION.md"),
            read_text("docs/ROADMAP.md"),
            read_text("docs/ARCHITECTURE.md"),
            read_text("docs/json-contracts.md"),
            read_text("docs/benchmarking.md"),
            read_text("docs/failure-gallery.md"),
            read_text("docs/v1-manual-qa.md"),
            read_text("docs/tui-qol-qa.md"),
            read_text("docs/release-readiness.md"),
            read_text("docs/release-notes/v1.md"),
            read_text("docs/faq.md"),
        ]
    )

    for removed_reference in (
        "AGENTS.md",
        "docs/superpowers",
        "CODEX_CAPABILITY_REVIEW",
        "release-candidate-proof-",
    ):
        assert removed_reference not in public_docs


def test_security_and_faq_state_trusted_local_sql_boundary() -> None:
    combined = "\n".join([read_text("SECURITY.md"), read_text("docs/faq.md")])

    assert "trusted local DuckDB SQL" in combined
    assert "does not sandbox DuckDB" in combined
    assert "Do not report sensitive vulnerabilities in public issues" in combined


def test_contributing_sets_solo_maintainer_posture() -> None:
    contributing = read_text("CONTRIBUTING.md")

    assert "solo-maintained" in contributing
    assert "Issues are welcome" in contributing
    assert "Pull requests are reviewed selectively" in contributing
    assert "roadmap remains maintainer-owned" in contributing


def test_github_templates_exist() -> None:
    for path in (
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/ISSUE_TEMPLATE/docs_issue.yml",
        ".github/pull_request_template.md",
        ".github/workflows/publish.yml",
    ):
        assert (REPO_ROOT / path).is_file(), path


def test_pyproject_public_metadata_is_consistent() -> None:
    payload = tomllib.loads(read_text("pyproject.toml"))
    project = payload["project"]

    assert project["name"] == "localql"
    assert project["license"] == "MIT"
    assert "LICENSE" in payload["project"]["license-files"]
    assert "License :: OSI Approved :: MIT License" in project["classifiers"]
    assert "Operating System :: OS Independent" in project["classifiers"]
    assert "csv" in project["keywords"]
    assert "duckdb" in project["keywords"]
    assert "local-analytics" in project["keywords"]


def test_publish_workflow_is_manual_only() -> None:
    workflow = read_text(".github/workflows/publish.yml")
    workflow_lines = workflow.splitlines()
    on_index = workflow_lines.index("on:")
    permissions_index = workflow_lines.index("permissions:")
    trigger_lines = [
        line
        for line in workflow_lines[on_index + 1 : permissions_index]
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert trigger_lines == ["  workflow_dispatch:"]
    assert "id-token: write" in workflow
    assert "pypa/gh-action-pypi-publish" in workflow
    assert "environment: pypi" in workflow
