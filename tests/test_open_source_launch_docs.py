from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED_ACTION_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")


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
    assert project["urls"] == {
        "Repository": "https://github.com/highlordleonas/csvql",
        "Issues": "https://github.com/highlordleonas/csvql/issues",
        "Changelog": "https://github.com/highlordleonas/csvql/blob/main/CHANGELOG.md",
        "Release notes": (
            "https://github.com/highlordleonas/csvql/blob/main/docs/release-notes/v1.md"
        ),
    }
    assert project["requires-python"] == ">=3.11,<3.15"
    for classifier in (
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    ):
        assert classifier in project["classifiers"]


def test_support_docs_define_post_release_response_policy() -> None:
    support = read_text("SUPPORT.md")

    for expected in (
        "Post-Release Response",
        "triaged by reproducibility",
        "patch releases",
        "Published tags are immutable",
        "PyPI release may be yanked",
        "supported Python/runtime contract",
    ):
        assert expected in support


def test_publish_workflow_is_manual_only() -> None:
    workflow = read_text(".github/workflows/publish.yml")
    payload = yaml.safe_load(workflow)
    workflow_lines = workflow.splitlines()
    on_index = workflow_lines.index("on:")
    permissions_index = workflow_lines.index("permissions:")
    trigger_lines = [
        line
        for line in workflow_lines[on_index + 1 : permissions_index]
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert trigger_lines == ["  workflow_dispatch:"]
    assert payload["permissions"] == {"contents": "read"}
    assert "workflow_dispatch:" in workflow


def test_github_actions_are_pinned_by_commit_sha() -> None:
    for path in (".github/workflows/ci.yml", ".github/workflows/publish.yml"):
        payload = yaml.safe_load(read_text(path))
        for job in payload["jobs"].values():
            for step in job["steps"]:
                uses = step.get("uses")
                if uses is None:
                    continue
                assert PINNED_ACTION_RE.fullmatch(uses), f"{path}: {uses}"


def test_publish_workflow_splits_build_from_oidc_publish() -> None:
    workflow = read_text(".github/workflows/publish.yml")
    payload = yaml.safe_load(workflow)
    jobs = payload["jobs"]
    build_job = jobs["build-and-verify"]
    publish_job = jobs["publish"]

    assert "id-token" not in (build_job.get("permissions") or {})
    assert publish_job["needs"] == "build-and-verify"
    assert publish_job["environment"] == "pypi"
    assert publish_job["permissions"] == {"contents": "read", "id-token": "write"}

    build_runs = "\n".join(str(step.get("run", "")) for step in build_job["steps"])
    publish_runs = "\n".join(str(step.get("run", "")) for step in publish_job["steps"])
    publish_uses = "\n".join(str(step.get("uses", "")) for step in publish_job["steps"])

    for required in (
        "uv sync --all-extras --frozen",
        "uv run ruff format --check .",
        "uv run ruff check .",
        "uv run --all-extras mypy src",
        "uv run --all-extras pytest",
        "uv build --sdist --wheel --out-dir dist",
        "scripts/audit_package_contents.py dist",
        "SHA256SUMS.txt",
        'csvql" query',
        "unset PYTHONPATH",
    ):
        assert required in build_runs

    for forbidden in (
        "uv sync",
        "uv build",
        "uv run",
        "csvql query",
        "scripts/audit_package_contents.py",
    ):
        assert forbidden not in publish_runs

    assert "actions/upload-artifact@" in workflow
    assert "actions/download-artifact@" in publish_uses
    assert "pypa/gh-action-pypi-publish@" in publish_uses
    assert "shasum -a 256 -c SHA256SUMS.txt" in publish_runs
    assert "cp release-artifacts/*.whl release-artifacts/*.tar.gz dist/" in publish_runs
    assert "packages-dir: dist/" in workflow
    assert "print-hash: true" in workflow
    assert "attestations: true" in workflow
    assert "id-token: write" in workflow
