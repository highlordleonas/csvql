from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED_ACTION_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")


def read_text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def load_public_release_audit() -> ModuleType:
    script = REPO_ROOT / "scripts" / "audit_public_release.py"
    spec = importlib.util.spec_from_file_location("open_source_launch_audit", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def tracked_paths() -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.splitlines()


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


def test_tracked_public_files_match_the_release_contract() -> None:
    observed_paths = frozenset(tracked_paths())
    audit = load_public_release_audit()
    categories = audit.classify_tracked_paths(observed_paths)

    assert audit.PUBLIC_PATHS == observed_paths
    assert frozenset().union(*categories.values()) == observed_paths
    assert sum(len(paths) for paths in categories.values()) == len(observed_paths)
    for path in (
        "README.md",
        "LICENSE",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "SUPPORT.md",
        "docs/ARCHITECTURE.md",
        "docs/cli-reference.md",
        "docs/development.md",
        "docs/faq.md",
        "docs/getting-started.md",
        "docs/json-contracts.md",
        "docs/release-notes/v1.md",
        "docs/troubleshooting.md",
        "docs/tui-guide.md",
    ):
        assert path in observed_paths


def test_security_and_faq_state_trusted_local_sql_boundary() -> None:
    combined = "\n".join([read_text("SECURITY.md"), read_text("docs/faq.md")])

    assert "trusted local DuckDB SQL" in combined
    assert "does not sandbox DuckDB" in combined
    assert "Do not report sensitive vulnerabilities in public issues" in combined


def test_github_templates_exist() -> None:
    for path in (
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/ISSUE_TEMPLATE/docs_issue.yml",
        ".github/pull_request_template.md",
        ".github/workflows/publish.yml",
    ):
        assert (REPO_ROOT / path).is_file(), path


def test_contributor_templates_collect_user_facing_change_context() -> None:
    feature_request = yaml.safe_load(read_text(".github/ISSUE_TEMPLATE/feature_request.yml"))
    feature_fields = {
        field["id"]: field["attributes"]["label"]
        for field in feature_request["body"]
        if "id" in field
    }

    assert feature_fields == {
        "problem": "Problem",
        "users": "User impact",
        "proposal": "Proposed scope",
        "compatibility": "Compatibility",
        "tests": "Tests",
        "docs": "Documentation",
        "screenshots": "Screenshots",
    }

    pull_request_template = read_text(".github/pull_request_template.md")
    for heading in (
        "## User impact",
        "## Scope",
        "## Compatibility",
        "## Validation",
        "## Documentation",
        "## Screenshots",
    ):
        assert heading in pull_request_template


def test_pyproject_public_metadata_is_consistent() -> None:
    payload = tomllib.loads(read_text("pyproject.toml"))
    project = payload["project"]

    assert project["name"] == "localql"
    assert project["version"] == "1.0.3"
    assert project["readme"] == "README.md"
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


def test_current_package_version_has_user_facing_release_entries() -> None:
    version = tomllib.loads(read_text("pyproject.toml"))["project"]["version"]

    assert re.search(
        rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$",
        read_text("CHANGELOG.md"),
        flags=re.MULTILINE,
    )
    assert re.search(
        rf"^## {re.escape(version)}$",
        read_text("docs/release-notes/v1.md"),
        flags=re.MULTILINE,
    )


def test_publish_workflow_is_manual_with_exact_identity_inputs() -> None:
    workflow = read_text(".github/workflows/publish.yml")
    payload = yaml.safe_load(workflow)

    assert "on:\n  workflow_dispatch:\n    inputs:" in workflow
    for input_name in (
        "version",
        "tag_object_oid",
        "peeled_commit_oid",
        "tag_ci_workflow_id",
        "tag_ci_run_id",
        "tag_ci_run_attempt",
    ):
        assert f"      {input_name}:" in workflow
        assert "        required: true" in workflow
    assert payload["permissions"] == {"contents": "read"}
    assert "push:" not in workflow


def test_publish_workflow_uses_identity_bound_trusted_publishing() -> None:
    workflow = read_text(".github/workflows/publish.yml")
    payload = yaml.safe_load(workflow)
    jobs = payload["jobs"]
    build_job = jobs["build-and-capture"]
    captured_verification_job = jobs["verify-captured-artifacts"]
    publish_job = jobs["publish"]
    verification_job = jobs["post-publish-verification"]

    assert build_job["permissions"] == {"contents": "read", "actions": "read"}
    assert captured_verification_job["needs"] == "build-and-capture"
    assert captured_verification_job["permissions"] == {"contents": "read"}
    assert publish_job["needs"] == "verify-captured-artifacts"
    assert publish_job["environment"] == "pypi"
    assert publish_job["permissions"] == {"contents": "read", "id-token": "write"}
    assert verification_job["needs"] == "publish"
    assert verification_job["permissions"] == {"contents": "read"}
    assert verification_job["timeout-minutes"] == 10

    build_runs = "\n".join(str(step.get("run", "")) for step in build_job["steps"])
    captured_verification_runs = "\n".join(
        str(step.get("run", "")) for step in captured_verification_job["steps"]
    )
    captured_verification_text = "\n".join(str(step) for step in captured_verification_job["steps"])
    publish_runs = "\n".join(str(step.get("run", "")) for step in publish_job["steps"])
    publish_uses = "\n".join(str(step.get("uses", "")) for step in publish_job["steps"])
    publish_text = "\n".join(str(step) for step in publish_job["steps"])
    verification_runs = "\n".join(str(step.get("run", "")) for step in verification_job["steps"])

    for required in (
        "git cat-file -t",
        "git rev-parse",
        "tag-ci-jobs.json",
        "uv sync --all-extras --all-groups --frozen",
        "scripts/release-build-constraints.txt",
        "--require-hashes",
        "scripts/audit_package_contents.py",
        "--expected-version",
        "scripts/verify_release_artifacts.py",
        "artifact-manifest.json",
        "localql-1.0.3-publish-bundle",
    ):
        assert required in build_runs or required in workflow

    assert "scripts/verify_dependency_audit.py" not in build_runs
    assert "scripts/verify_installed_artifacts.py" not in build_runs
    for required in (
        "scripts/verify_dependency_audit.py",
        "scripts/verify_installed_artifacts.py",
        "scripts/release-audit-tool-requirements.txt",
        "localql-1.0.3-publish-bundle",
        "localql-1.0.3-verification-evidence",
    ):
        assert required in captured_verification_runs or required in captured_verification_text

    assert "localql-1.0.3-publish-bundle" in publish_text
    assert "localql-1.0.3-verification-evidence" not in publish_text
    assert "pypa/gh-action-pypi-publish@" in publish_uses
    assert "PYPI_TOKEN" not in publish_runs
    assert "twine upload" not in publish_runs
    assert "packages-dir: dist/" in workflow
    assert "attestations: true" in workflow
    assert "id-token: write" in workflow
    assert "shasum -a 256 -c SHA256SUMS.txt" in publish_runs

    for required in (
        "localql-1.0.3-pypi-verification",
        "https://pypi.org/pypi/{project}/json",
        "https://pypi.org/integrity/{project}/{version}",
        "verification-status.txt",
        "--public-index",
        "--allow-published-version-check",
    ):
        assert required in verification_runs or required in workflow


def test_publish_build_job_uses_the_action_installed_uv_runtime() -> None:
    workflow = read_text(".github/workflows/publish.yml")
    payload = yaml.safe_load(workflow)
    build_job = payload["jobs"]["build-and-capture"]
    build_runs = "\n".join(str(step.get("run", "")) for step in build_job["steps"])

    assert "uvx --from uv==" not in build_runs
    assert 'uv build --python "${ARTIFACT_PYTHON}"' in build_runs
    assert "uv --version > dist/uv-version.txt" in build_runs
    assert 'uv run --python "${ARTIFACT_PYTHON}" python --version' in build_runs
