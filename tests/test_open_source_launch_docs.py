from __future__ import annotations

import ast
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


def module_string_constant(path: str, name: str) -> str:
    module = ast.parse(read_text(path), filename=path)
    for statement in module.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if isinstance(target, ast.Name) and target.id == name:
            value = statement.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    raise AssertionError(f"{path} missing string constant {name!r}")


def root_lock_localql_version() -> str:
    payload = tomllib.loads(read_text("uv.lock"))
    packages = payload["package"]
    assert isinstance(packages, list)
    for package in packages:
        if package["name"] == "localql" and package["source"] == {"editable": "."}:
            return str(package["version"])
    raise AssertionError("uv.lock missing editable localql package entry")


def markdown_section(text: str, heading: str) -> str:
    pattern = rf"(?ms)^## {re.escape(heading)}\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, text)
    assert match is not None, f"missing section {heading!r}"
    return match.group(1).strip()


def workflow_payload(path: str) -> dict[str, object]:
    payload = yaml.safe_load(read_text(path))
    assert isinstance(payload, dict)
    return payload


def workflow_jobs(path: str) -> dict[str, object]:
    jobs = workflow_payload(path)["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def workflow_job_steps(path: str, job_name: str) -> list[dict[str, object]]:
    job = workflow_jobs(path)[job_name]
    assert isinstance(job, dict)
    steps = job["steps"]
    assert isinstance(steps, list)
    assert all(isinstance(step, dict) for step in steps)
    return steps


def step_name(step: dict[str, object]) -> str:
    return str(step.get("name", step.get("uses", "")))


def step_run(step: dict[str, object]) -> str:
    return str(step.get("run", ""))


def named_step(path: str, job_name: str, name: str) -> dict[str, object]:
    for step in workflow_job_steps(path, job_name):
        if step_name(step) == name:
            return step
    raise AssertionError(f"{path} missing {job_name!r} step {name!r}")


def step_index(path: str, job_name: str, name: str) -> int:
    for index, step in enumerate(workflow_job_steps(path, job_name)):
        if step_name(step) == name:
            return index
    raise AssertionError(f"{path} missing {job_name!r} step {name!r}")


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


def test_private_engineering_artifacts_are_ignored_and_never_public() -> None:
    ignored_roots = set(read_text(".gitignore").splitlines())
    audit = load_public_release_audit()
    protected_paths = {
        "/AGENTS.md": "AGENTS.md",
        "/AGENTS.override.md": "AGENTS.override.md",
        "/.agents/": ".agents/instructions.md",
        "/.codex/": ".codex/session.json",
        "/.internal/": ".internal/release-proof.md",
        "/docs/superpowers/": "docs/superpowers/design.md",
        "/docs/CODEX_CAPABILITY_REVIEW.md": "docs/CODEX_CAPABILITY_REVIEW.md",
        "/docs/release-candidate-proof-*.md": ("docs/release-candidate-proof-2026-07-03.md"),
    }

    assert protected_paths.keys() <= ignored_roots
    assert all(audit.is_immutable_forbidden_path(path) for path in protected_paths.values())


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
    assert project["version"] == "1.0.5"
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


def test_current_release_version_surfaces_are_atomic_and_explicit() -> None:
    publish_workflow = workflow_payload(".github/workflows/publish.yml")
    publish_env = publish_workflow["env"]
    assert isinstance(publish_env, dict)
    ci_release_run = step_run(
        named_step(".github/workflows/ci.yml", "test", "Verify exact release artifacts")
    )

    observed = {
        "pyproject": tomllib.loads(read_text("pyproject.toml"))["project"]["version"],
        "uv_lock": root_lock_localql_version(),
        "__version__": module_string_constant("src/csvql/__init__.py", "__version__"),
        "verifier_expected_version": module_string_constant(
            "scripts/verify_release_artifacts.py", "EXPECTED_VERSION"
        ),
        "verifier_expected_wheel": module_string_constant(
            "scripts/verify_release_artifacts.py", "EXPECTED_WHEEL"
        ),
        "verifier_expected_sdist": module_string_constant(
            "scripts/verify_release_artifacts.py", "EXPECTED_SDIST"
        ),
        "publish_expected_tag": str(publish_env["EXPECTED_TAG"]),
        "publish_expected_version": str(publish_env["EXPECTED_VERSION"]),
        "constraints_comment": read_text("scripts/release-build-constraints.txt").splitlines()[0],
        "changelog_heading": re.search(
            r"^## \[(?P<version>[^\]]+)\] - (?P<date>\d{4}-\d{2}-\d{2})$",
            read_text("CHANGELOG.md"),
            flags=re.MULTILINE,
        ).groupdict(),
        "release_notes_heading": re.search(
            r"^## (?P<version>\d+\.\d+\.\d+)$",
            read_text("docs/release-notes/v1.md"),
            flags=re.MULTILINE,
        ).group("version"),
        "ci_expected_version_arg": re.search(
            r"--expected-version (?P<version>\d+\.\d+\.\d+)",
            ci_release_run,
        ).group("version"),
    }

    assert observed == {
        "pyproject": "1.0.5",
        "uv_lock": "1.0.5",
        "__version__": "1.0.5",
        "verifier_expected_version": "1.0.5",
        "verifier_expected_wheel": "localql-1.0.5-py3-none-any.whl",
        "verifier_expected_sdist": "localql-1.0.5.tar.gz",
        "publish_expected_tag": "v1.0.5",
        "publish_expected_version": "1.0.5",
        "constraints_comment": "# Python 3.12 build closure for LocalQL 1.0.5 artifacts.",
        "changelog_heading": {"version": "1.0.5", "date": "2026-07-21"},
        "release_notes_heading": "1.0.5",
        "ci_expected_version_arg": "1.0.5",
    }


def test_current_release_wording_is_user_facing_and_behavior_preserving() -> None:
    changelog_section = markdown_section(read_text("CHANGELOG.md"), "[1.0.5] - 2026-07-21")
    release_notes_section = markdown_section(read_text("docs/release-notes/v1.md"), "1.0.5")
    expected_changelog = (
        "### Changed - Package and release verification now checks the wheel and source "
        "distribution as one exact release bundle before publication. - Version-reporting "
        "surfaces now report 1.0.5. Query behavior, supported formats, and the SQL safety "
        "boundary remain unchanged."
    )
    expected_release_notes = (
        "LocalQL 1.0.5 strengthens package and release verification by checking the wheel "
        "and source distribution as one exact release bundle before publication. "
        "Version-reporting surfaces, including `csvql --version` and `csvql.__version__`, "
        "now report 1.0.5. Query behavior, supported formats, and the SQL safety boundary "
        "remain unchanged."
    )

    assert " ".join(changelog_section.split()) == expected_changelog
    assert " ".join(release_notes_section.split()) == expected_release_notes


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
    pre_publish_verification_job = jobs["pre-publish-verification"]
    publish_job = jobs["publish"]
    verification_job = jobs["post-publish-verification"]

    assert build_job["permissions"] == {"contents": "read", "actions": "read"}
    assert captured_verification_job["needs"] == "build-and-capture"
    assert captured_verification_job["permissions"] == {"contents": "read"}
    assert pre_publish_verification_job["needs"] == "verify-captured-artifacts"
    assert pre_publish_verification_job["permissions"] == {"contents": "read"}
    assert "environment" not in pre_publish_verification_job
    assert publish_job["needs"] == "pre-publish-verification"
    assert publish_job["environment"] == "pypi"
    assert publish_job["permissions"] == {"id-token": "write"}
    assert {
        job_name
        for job_name, job in jobs.items()
        if isinstance(job, dict)
        and isinstance(job.get("permissions"), dict)
        and job["permissions"].get("id-token") == "write"
    } == {"publish"}
    assert set(publish_job) == {"needs", "runs-on", "environment", "permissions", "steps"}
    assert verification_job["needs"] == "publish"
    assert verification_job["permissions"] == {"contents": "read"}
    assert verification_job["timeout-minutes"] == 10

    build_runs = "\n".join(str(step.get("run", "")) for step in build_job["steps"])
    captured_verification_runs = "\n".join(
        str(step.get("run", "")) for step in captured_verification_job["steps"]
    )
    captured_verification_text = "\n".join(str(step) for step in captured_verification_job["steps"])
    pre_publish_verification_runs = "\n".join(
        str(step.get("run", "")) for step in pre_publish_verification_job["steps"]
    )
    publish_runs = "\n".join(str(step.get("run", "")) for step in publish_job["steps"])
    publish_uses = "\n".join(str(step.get("uses", "")) for step in publish_job["steps"])
    publish_text = "\n".join(str(step) for step in publish_job["steps"])
    verification_runs = "\n".join(str(step.get("run", "")) for step in verification_job["steps"])

    for required in (
        "git cat-file -t",
        "git rev-parse",
        "refs/tags/${EXPECTED_TAG}:refs/localql/verified-tags/${EXPECTED_TAG}",
        'VERIFIED_TAG_REF="refs/localql/verified-tags/${EXPECTED_TAG}"',
        "tag-ci-jobs.json",
        "uv sync --all-extras --all-groups --frozen",
        "scripts/release-build-constraints.txt",
        "--require-hashes",
        "scripts/audit_package_contents.py",
        "--expected-version",
        "scripts/verify_release_artifacts.py",
        "artifact-manifest.json",
        "localql-1.0.5-publish-bundle",
    ):
        assert required in build_runs or required in workflow

    assert "scripts/verify_dependency_audit.py" not in build_runs
    assert "scripts/verify_installed_artifacts.py" not in build_runs
    for required in (
        "scripts/verify_dependency_audit.py",
        "scripts/verify_installed_artifacts.py",
        "localql-1.0.5-publish-bundle",
        "localql-1.0.5-verification-evidence",
    ):
        assert required in captured_verification_runs or required in captured_verification_text

    assert "localql-1.0.5-publish-bundle" in publish_text
    assert "localql-1.0.5-verification-evidence" not in publish_text
    assert "verify-manifest release-bundle/artifacts --expected-version" in (
        pre_publish_verification_runs
    )
    assert "https://pypi.org/pypi/localql/" in pre_publish_verification_runs
    assert "--sdist" in captured_verification_runs
    assert "localql-1.0.5.tar.gz" in captured_verification_runs
    assert "pypa/gh-action-pypi-publish@" in publish_uses
    assert "PYPI_TOKEN" not in publish_runs
    assert "twine upload" not in publish_runs
    assert "packages-dir: release-bundle/artifacts/" in workflow
    assert "attestations: true" in workflow
    assert "id-token: write" in workflow
    assert not publish_runs.strip()
    assert all("run" not in step for step in publish_job["steps"])
    assert len(publish_job["steps"]) == 2
    assert publish_job["steps"] == [
        {
            "name": "Download immutable publication bundle",
            "uses": "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
            "with": {
                "name": "localql-1.0.5-publish-bundle",
                "path": "release-bundle",
            },
        },
        {
            "name": "Publish to PyPI",
            "uses": "pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b",
            "with": {
                "packages-dir": "release-bundle/artifacts/",
                "print-hash": True,
                "attestations": True,
            },
        },
    ]

    for required in (
        "localql-1.0.5-pypi-verification",
        'project_url = f"https://pypi.org/pypi/{PROJECT}/json"',
        "https://pypi.org/integrity/{PROJECT}/{VERSION}/",
        "verification-status.txt",
        "--sdist",
    ):
        assert required in verification_runs or required in workflow


def test_publish_build_job_uses_the_action_installed_uv_runtime() -> None:
    build_runs = "\n".join(
        step_run(step)
        for step in workflow_job_steps(".github/workflows/publish.yml", "build-and-capture")
    )

    assert "uvx --from uv==" not in build_runs
    assert 'uv build --python "${ARTIFACT_PYTHON}"' in build_runs
    assert "uv --version > release-bundle/evidence/uv-version.txt" in build_runs
    assert 'uv run --python "${ARTIFACT_PYTHON}" --no-sync python --version' in build_runs


def test_release_build_workflows_audit_the_exact_checked_out_candidate_first() -> None:
    ci_workflow = read_text(".github/workflows/ci.yml")
    publish_workflow = read_text(".github/workflows/publish.yml")

    for workflow in (ci_workflow, publish_workflow):
        audit_command = (
            "scripts/audit_public_release.py --repo . "
            '--expected-repository "${GITHUB_REPOSITORY}" '
            '--candidate "${GITHUB_SHA}" --tree-only'
        )
        assert audit_command in workflow
        assert workflow.index(audit_command) < workflow.index("uv build")


def test_release_builds_do_not_add_metadata_to_exact_artifact_directories() -> None:
    ci_release_run = step_run(
        named_step(".github/workflows/ci.yml", "test", "Verify exact release artifacts")
    )
    publish_build_run = step_run(
        named_step(
            ".github/workflows/publish.yml", "build-and-capture", "Build exact release bundle"
        )
    )

    assert ci_release_run.count("--no-create-gitignore") == 1
    assert publish_build_run.count("--no-create-gitignore") == 2


def test_ci_release_check_uses_pair_inspection_without_manifest_custody_inputs() -> None:
    release_step = named_step(".github/workflows/ci.yml", "test", "Verify exact release artifacts")
    release_run = step_run(release_step)

    assert (
        "uv run --frozen --no-sync python scripts/verify_release_artifacts.py \\\n"
        "            output/ci-release-dist --expected-version 1.0.5"
    ) not in release_run
    assert "scripts/verify_release_artifacts.py" in release_run
    assert "inspect output/ci-release-dist --expected-version 1.0.5" in release_run
    for forbidden in (
        "create-manifest",
        "verify-manifest",
        "--manifest",
        "--sha256sums",
        "--source-commit",
        "--tag-name",
        "--tag-object",
        "--peeled-commit",
        "--python-identity-file",
        "--uv-identity-file",
        "--build-constraints-digest-file",
    ):
        assert forbidden not in release_run


def test_publish_build_job_requires_one_constrained_semantic_rebuild_before_manifest() -> None:
    workflow_path = ".github/workflows/publish.yml"
    build_steps = workflow_job_steps(workflow_path, "build-and-capture")
    build_runs = "\n".join(step_run(step) for step in build_steps)
    upload_step = named_step(
        workflow_path,
        "build-and-capture",
        "Capture immutable publication bundle",
    )
    upload_path = upload_step.get("with", {}).get("path")
    build_step = named_step(
        workflow_path,
        "build-and-capture",
        "Build exact release bundle",
    )

    assert build_runs.count("create-manifest") == 1
    assert "verify-manifest" not in build_runs
    assert build_runs.count("verify-rebuild") == 1
    assert build_runs.count("--build-constraints scripts/release-build-constraints.txt") == 2
    assert build_runs.count("--require-hashes") == 2
    assert 'REBUILD_DIR="${RUNNER_TEMP}/localql-constrained-rebuild"' in build_runs
    assert "release-bundle/artifacts/localql-1.0.5.tar.gz" in build_runs
    assert '"${REBUILD_DIR}/localql-1.0.5-py3-none-any.whl"' in build_runs
    assert "rebuild-consumer" not in build_runs
    assert "release-bundle/artifacts" in build_runs
    assert "release-bundle/evidence" in build_runs
    assert '"${EVIDENCE_DIR}/dist"' not in build_runs
    assert "path: release-bundle" in str(upload_step) or upload_path == "release-bundle"
    assert step_index(
        workflow_path, "build-and-capture", "Verify release and tag-CI identity"
    ) < step_index(workflow_path, "build-and-capture", "Build exact release bundle")
    assert "create-manifest" in step_run(build_step)
    assert step_run(build_step).index("verify-rebuild") < step_run(build_step).index(
        "create-manifest"
    )
    assert step_index(
        workflow_path, "build-and-capture", "Build exact release bundle"
    ) < step_index(
        workflow_path,
        "build-and-capture",
        "Capture immutable publication bundle",
    )


def test_release_consumers_verify_manifest_with_fresh_context_before_artifact_use() -> None:
    workflow_path = ".github/workflows/publish.yml"

    captured_runs = "\n".join(
        step_run(step) for step in workflow_job_steps(workflow_path, "verify-captured-artifacts")
    )
    assert "captured-bundle/artifacts" in captured_runs
    assert "captured-bundle/evidence" in captured_runs
    assert "scripts/audit_package_contents.py" in captured_runs
    assert "scripts/verify_release_artifacts.py" in captured_runs
    assert "verify-manifest captured-bundle/artifacts --expected-version" in captured_runs
    assert "scripts/verify_dependency_audit.py" in captured_runs
    assert "localql-1.0.5.tar.gz" in captured_runs
    assert '--work-dir "${RUNNER_TEMP}/localql-installed-smokes"' in captured_runs
    assert '--work-dir "${VERIFICATION_DIR}/installed-smokes"' not in captured_runs
    assert "${VERIFICATION_DIR}/python-identity.txt" in captured_runs
    assert "${VERIFICATION_DIR}/uv-identity.txt" in captured_runs
    assert "${VERIFICATION_DIR}/release-build-constraints.sha256" in captured_runs
    assert "captured-bundle/evidence/python-identity.txt" not in captured_runs
    assert "captured-bundle/evidence/uv-version.txt" not in captured_runs
    assert captured_runs.index("scripts/verify_dependency_audit.py") < captured_runs.index(
        "scripts/verify_installed_artifacts.py"
    )
    assert captured_runs.index(
        "verify-manifest captured-bundle/artifacts --expected-version"
    ) < captured_runs.index("twine check")
    assert captured_runs.index(
        "verify-manifest captured-bundle/artifacts --expected-version"
    ) < captured_runs.index("scripts/verify_installed_artifacts.py")
    assert '--work-dir "${RUNNER_TEMP}/localql-installed-smokes"' in captured_runs

    pre_publish_runs = "\n".join(
        step_run(step) for step in workflow_job_steps(workflow_path, "pre-publish-verification")
    )
    publish_uses = "\n".join(
        str(step.get("uses", "")) for step in workflow_job_steps(workflow_path, "publish")
    )
    assert "release-bundle/artifacts" in pre_publish_runs
    assert "release-bundle/evidence" in pre_publish_runs
    assert "scripts/audit_package_contents.py" in pre_publish_runs
    assert "scripts/verify_release_artifacts.py" in pre_publish_runs
    assert "verify-manifest release-bundle/artifacts --expected-version" in pre_publish_runs
    assert "${PUBLISH_VERIFICATION_DIR}/python-identity.txt" in pre_publish_runs
    assert "${PUBLISH_VERIFICATION_DIR}/uv-identity.txt" in pre_publish_runs
    assert "${PUBLISH_VERIFICATION_DIR}/release-build-constraints.sha256" in pre_publish_runs
    for forbidden in (
        "shasum -a 256 -c SHA256SUMS.txt",
        "tarfile",
        "zipfile",
        "glob(",
        "cp release-artifacts/dist/*.whl",
        "cp release-artifacts/dist/*.tar.gz",
    ):
        assert forbidden not in pre_publish_runs
    assert pre_publish_runs.index(
        "verify-manifest release-bundle/artifacts --expected-version"
    ) < pre_publish_runs.index("https://pypi.org/pypi/localql/")
    publish_step = named_step(workflow_path, "publish", "Publish to PyPI")
    assert publish_step.get("with", {}).get("packages-dir") == "release-bundle/artifacts/"
    assert "pypa/gh-action-pypi-publish@" in publish_uses
    assert all("run" not in step for step in workflow_job_steps(workflow_path, "publish"))


def test_post_publish_readback_uses_exact_public_files_and_original_manifest() -> None:
    workflow_path = ".github/workflows/publish.yml"
    verification_runs = "\n".join(
        step_run(step) for step in workflow_job_steps(workflow_path, "post-publish-verification")
    )

    assert "path: original-custody" in read_text(workflow_path)
    assert "public-readback-artifacts" in verification_runs
    assert "https://files.pythonhosted.org/" in verification_runs
    assert "scripts/verify_release_artifacts.py" in verification_runs
    assert "verify-manifest public-readback-artifacts --expected-version" in verification_runs
    assert "original-custody/evidence/artifact-manifest.json" in verification_runs
    assert "original-custody/evidence/SHA256SUMS.txt" in verification_runs
    assert "scripts/verify_dependency_audit.py" in verification_runs
    assert "localql-1.0.5.tar.gz" in verification_runs
    assert '--work-dir "${RUNNER_TEMP}/localql-post-publish-smoke"' in verification_runs
    assert "--work-dir post-publish-smoke" not in verification_runs
    assert "${PUBLIC_READBACK_VERIFICATION_DIR}/python-identity.txt" in verification_runs
    assert "${PUBLIC_READBACK_VERIFICATION_DIR}/uv-identity.txt" in verification_runs
    assert (
        "${PUBLIC_READBACK_VERIFICATION_DIR}/release-build-constraints.sha256" in verification_runs
    )
    assert "shasum -a 256 -c SHA256SUMS.txt" not in verification_runs
    assert verification_runs.index(
        "verify-manifest public-readback-artifacts --expected-version"
    ) < verification_runs.index("scripts/verify_installed_artifacts.py")
    assert "--public-index" not in verification_runs
    assert "scripts/verify_dependency_audit.py" in verification_runs
    assert "localql-1.0.5.tar.gz" in verification_runs
    assert "--sdist public-readback-artifacts/localql-1.0.5.tar.gz" in verification_runs
    assert '--work-dir "${RUNNER_TEMP}/localql-post-publish-smoke"' in verification_runs
    assert '"exact_release_json_filenames_and_urls_verified": True' in verification_runs
    assert '"exact_release_json_verified": True' not in verification_runs
    assert "PyPI release metadata and filenames verified" not in verification_runs


def test_post_publish_provenance_requires_non_empty_attestation_bundles() -> None:
    verification_runs = "\n".join(
        step_run(step)
        for step in workflow_job_steps(".github/workflows/publish.yml", "post-publish-verification")
    )

    assert 'attestations = bundle.get("attestations")' in verification_runs
    assert "if not isinstance(attestations, list) or not attestations:" in verification_runs
    assert 'last_issue = f"an attestation bundle is empty for {filename}"' in verification_runs


def test_post_publish_readback_directory_is_fresh_and_fail_closed() -> None:
    verification_runs = "\n".join(
        step_run(step)
        for step in workflow_job_steps(".github/workflows/publish.yml", "post-publish-verification")
    )

    assert "READBACK_DIR.mkdir(parents=True, exist_ok=False)" in verification_runs
    assert "if path.is_file():" not in verification_runs


def test_post_publish_readback_downloads_complete_via_temp_file_fsync_replace_and_cleanup() -> None:
    verification_runs = "\n".join(
        step_run(step)
        for step in workflow_job_steps(".github/workflows/publish.yml", "post-publish-verification")
    )

    assert "MAX_COMPRESSED_ARTIFACT_BYTES" in verification_runs
    assert (
        "with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:" in verification_runs
    )
    assert "while True:" in verification_runs
    assert "chunk = response.read(64 * 1024)" in verification_runs
    assert "if observed_size > MAX_COMPRESSED_ARTIFACT_BYTES:" in verification_runs
    assert "destination = READBACK_DIR / filename" in verification_runs
    assert 'temp_path = READBACK_DIR / f".{filename}.partial"' in verification_runs
    assert 'with temp_path.open("xb") as handle:' in verification_runs
    assert "handle.flush()" in verification_runs
    assert "os.fsync(handle.fileno())" in verification_runs
    assert "os.replace(temp_path, destination)" in verification_runs
    assert "temp_path.unlink()" in verification_runs
    assert "response.read()" not in verification_runs
