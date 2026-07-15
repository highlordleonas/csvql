from __future__ import annotations

import io
import json
import re
import shlex
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from importlib.metadata import version as installed_distribution_version
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.git_public_push_guard import parse_approval

REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED_ACTION_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")
OID_RE = re.compile(r"^[0-9a-f]{40}$")


def read_text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def markdown_section(document: str, heading: str) -> str:
    lines = document.splitlines()
    marker = f"## {heading}"
    assert marker in lines, heading
    start = lines.index(marker) + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def normalized_markdown(document: str) -> str:
    return " ".join(document.split())


def fenced_blocks(document: str, language: str) -> tuple[str, ...]:
    return tuple(
        re.findall(
            rf"^```{re.escape(language)}\n(.*?)\n```$",
            document,
            flags=re.MULTILINE | re.DOTALL,
        )
    )


def assert_ordered(document: str, phrases: tuple[str, ...]) -> None:
    cursor = -1
    for phrase in phrases:
        cursor = document.find(phrase, cursor + 1)
        assert cursor >= 0, phrase


def heredoc_block(script: str, marker: str) -> str:
    matches = re.findall(rf"<<'{re.escape(marker)}'\n(.*?)\n{re.escape(marker)}", script, re.DOTALL)
    assert len(matches) == 1, marker
    return matches[0]


def test_open_source_trust_files_exist() -> None:
    for path in (
        "AGENTS.md",
        "LICENSE",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "SUPPORT.md",
        "docs/development.md",
        "docs/faq.md",
        "docs/releasing.md",
        "docs/v2-point-and-query-design.md",
    ):
        assert (REPO_ROOT / path).is_file(), path


def git_tracked_paths(path: str) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--", path],
        check=True,
        text=True,
        capture_output=True,
    )
    return tuple(line for line in result.stdout.splitlines() if line)


def test_internal_operator_material_is_not_tracked_for_publication() -> None:
    assert not (REPO_ROOT / "docs" / "CODEX_CAPABILITY_REVIEW.md").exists()
    assert not list((REPO_ROOT / "docs").glob("release-candidate-proof-*.md"))
    assert git_tracked_paths("docs/superpowers") == ()


def test_public_git_and_release_authority_is_explicit() -> None:
    agents = normalized_markdown(read_text("AGENTS.md"))
    releasing = normalized_markdown(read_text("docs/releasing.md"))
    contributing = normalized_markdown(read_text("CONTRIBUTING.md"))
    pull_request = normalized_markdown(read_text(".github/pull_request_template.md"))

    for phrase in (
        "Local `main` mirrors live public `main`",
        "remain local by default",
        "public push",
        "pull-request merge",
        "version tag",
        "GitHub Release",
        "PyPI publication",
        "separate explicit approval",
    ):
        assert phrase in agents
    for phrase in (
        "LOCALQL_PUBLIC_PUSH_APPROVAL",
        "create_branch",
        "update_branch",
        "create_annotated_tag",
        "--no-verify",
        "hosted rules are authoritative",
        "make ci-fresh",
        "never retarget or reuse a version tag",
        "never replace a PyPI version",
    ):
        assert phrase in releasing
    assert "External contributors push branches to their own forks" in contributing
    assert "Maintainer development branches remain local by default" in contributing
    assert "Public release boundary" in pull_request


def test_release_runbook_examples_are_machine_valid_without_pushing() -> None:
    releasing = read_text("docs/releasing.md")
    json_blocks = fenced_blocks(releasing, "json")
    bash_blocks = fenced_blocks(releasing, "bash")

    assert len(json_blocks) == 3
    approvals = tuple(parse_approval(block) for block in json_blocks)
    assert tuple(approval.operation for approval in approvals) == (
        "create_branch",
        "update_branch",
        "create_annotated_tag",
    )

    push_block = next(block for block in bash_blocks if "LOCALQL_PUBLIC_PUSH_APPROVAL=" in block)
    continued_push_block = re.sub(r"\\\n[ \t]*", " ", push_block)
    assignment, *push_argv = shlex.split(continued_push_block)
    variable, separator, inline_manifest = assignment.partition("=")
    assert (variable, separator) == ("LOCALQL_PUBLIC_PUSH_APPROVAL", "=")
    assert inline_manifest == json_blocks[0]
    expected_refspec = "1111111111111111111111111111111111111111:refs/heads/release/v1.0.2"
    assert push_argv == [
        "git",
        "push",
        "https://github.com/highlordleonas/csvql.git",
        expected_refspec,
    ]
    assert len(push_argv[3:]) == 1
    source_oid, destination_ref = push_argv[3].split(":", maxsplit=1)
    assert OID_RE.fullmatch(source_oid)
    assert source_oid == approvals[0].new_oid
    assert destination_ref == approvals[0].destination_ref

    for block in bash_blocks:
        subprocess.run(
            ["bash", "-n", "-c", block],
            check=True,
            capture_output=True,
        )


def test_release_runbook_candidate_evidence_fails_closed(tmp_path: Path) -> None:
    releasing = read_text("docs/releasing.md")
    candidate_section = normalized_markdown(markdown_section(releasing, "Candidate Evidence"))
    candidate = next(
        block for block in fenced_blocks(releasing, "bash") if "evidence_dir=" in block
    )

    assert "Any failure stops the evidence run" in candidate_section
    assert (
        "Only failures after the evidence directory is claimed leave that directory for diagnosis"
        in candidate_section
    )
    candidate_lines = candidate.splitlines()
    assert candidate_lines[0] == "set -euo pipefail"
    assert "||" not in candidate
    assert '[[ "${release_version}" =~ ^v[0-9]+\\.[0-9]+\\.[0-9]+$ ]]' in candidate
    assert 'expected_version="${release_version#v}"' in candidate
    assert 'mkdir -- "${evidence_dir}"' in candidate
    assert 'test ! -e "${evidence_dir}"' not in candidate
    assert 'git cat-file -t "${candidate_oid}"' in candidate
    assert candidate_lines.count("git diff --quiet --exit-code --") == 2
    assert candidate_lines.count("git diff --cached --quiet --exit-code --") == 2
    assert [line for line in candidate_lines if line.startswith("git diff --quiet")] == [
        "git diff --quiet --exit-code --",
        "git diff --quiet --exit-code --",
    ]
    assert [line for line in candidate_lines if line.startswith("git diff --cached")] == [
        "git diff --cached --quiet --exit-code --",
        "git diff --cached --quiet --exit-code --",
    ]
    assert (
        candidate_lines.count('initial_status="$(git status --porcelain=v1 --untracked-files=all)"')
        == 1
    )
    assert (
        candidate_lines.count('final_status="$(git status --porcelain=v1 --untracked-files=all)"')
        == 1
    )
    assert 'test -z "${initial_status}"' in candidate_lines
    assert 'test -z "${final_status}"' in candidate_lines
    assert "localql-untracked" not in candidate
    assert "git ls-files --others --exclude-standard" not in candidate
    assert "shopt -s nullglob" in candidate
    assert 'wheels=("${evidence_dir}"/dist/*.whl)' in candidate_lines
    assert 'sdists=("${evidence_dir}"/dist/*.tar.gz)' in candidate_lines
    assert "if (( ${#wheels[@]} != 1 )); then" in candidate
    assert "if (( ${#sdists[@]} != 1 )); then" in candidate
    assert candidate_lines.count("  exit 1") == 2

    metadata_validation = heredoc_block(candidate, "PY_METADATA")
    assert "zipfile.ZipFile(wheel_path)" in metadata_validation
    assert 'tarfile.open(sdist_path, "r:*")' in metadata_validation
    assert 'metadata["Name"]' in metadata_validation
    assert 'metadata["Version"]' in metadata_validation
    assert '("localql", expected_version)' in metadata_validation

    smoke_validation = heredoc_block(candidate, "PY_SMOKE")
    assert "from importlib.metadata import version" in smoke_validation
    assert 'version("localql")' in smoke_validation
    assert '"columns": ["order_count"]' in smoke_validation
    assert '"rows": [{"order_count": 1}]' in smoke_validation
    assert '"row_count": 1' in smoke_validation
    assert "observed_result != expected_result" in smoke_validation
    assert 'cli_version="$(' in candidate
    assert 'test "${cli_version}" = "${expected_version}"' in candidate_lines
    assert 'query_json="$(' in candidate
    assert "query-smoke.json" in candidate
    assert_ordered(
        candidate,
        (
            '[[ "${release_version}" =~ ^v[0-9]+\\.[0-9]+\\.[0-9]+$ ]]',
            'expected_version="${release_version#v}"',
            'candidate_oid="$(git rev-parse --verify HEAD^{commit})"',
            'git cat-file -t "${candidate_oid}"',
            "git diff --quiet --exit-code --",
            "git diff --cached --quiet --exit-code --",
            'initial_status="$(git status --porcelain=v1 --untracked-files=all)"',
            'test -z "${initial_status}"',
            'mkdir -- "${evidence_dir}"',
            "make ci-fresh",
            "uv build --sdist --wheel",
            "shopt -s nullglob",
            'wheels=("${evidence_dir}"/dist/*.whl)',
            'sdists=("${evidence_dir}"/dist/*.tar.gz)',
            "if (( ${#wheels[@]} != 1 )); then",
            "if (( ${#sdists[@]} != 1 )); then",
            "scripts/audit_package_contents.py",
            "PY_METADATA",
            'test "${cli_version}" = "${expected_version}"',
            '"${smoke_root}/venv/bin/csvql" query',
            "PY_SMOKE",
            'test "$(git rev-parse --verify HEAD^{commit})" = "${candidate_oid}"',
            'final_status="$(git status --porcelain=v1 --untracked-files=all)"',
            'test -z "${final_status}"',
        ),
    )
    final_head_check = candidate.index(
        'test "$(git rev-parse --verify HEAD^{commit})" = "${candidate_oid}"'
    )
    assert candidate.rfind("git diff --quiet --exit-code --") > final_head_check
    assert candidate.rfind("git diff --cached --quiet --exit-code --") > final_head_check
    final_diff = candidate.rfind("git diff --quiet --exit-code --")
    final_cached_diff = candidate.rfind("git diff --cached --quiet --exit-code --")
    final_status = candidate.index(
        'final_status="$(git status --porcelain=v1 --untracked-files=all)"'
    )
    final_empty_check = candidate.index('test -z "${final_status}"')
    assert final_head_check < final_diff < final_cached_diff < final_status < final_empty_check

    def write_wheel(path: Path, version: str) -> None:
        metadata = f"Metadata-Version: 2.4\nName: localql\nVersion: {version}\n\n"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"localql-{version}.dist-info/METADATA", metadata)

    def write_sdist(path: Path, version: str) -> None:
        metadata = f"Metadata-Version: 2.4\nName: localql\nVersion: {version}\n\n".encode()
        member = tarfile.TarInfo(f"localql-{version}/PKG-INFO")
        member.size = len(metadata)
        with tarfile.open(path, "w:gz") as archive:
            archive.addfile(member, io.BytesIO(metadata))

    wheel = tmp_path / "localql.whl"
    sdist = tmp_path / "localql.tar.gz"
    write_wheel(wheel, "1.2.3")
    write_sdist(sdist, "1.2.3")
    matching_metadata = subprocess.run(
        [sys.executable, "-c", metadata_validation, "1.2.3", str(wheel), str(sdist)],
        text=True,
        capture_output=True,
    )
    assert matching_metadata.returncode == 0, matching_metadata.stderr

    write_wheel(wheel, "9.9.9")
    wheel_mismatch = subprocess.run(
        [sys.executable, "-c", metadata_validation, "1.2.3", str(wheel), str(sdist)],
        text=True,
        capture_output=True,
    )
    assert wheel_mismatch.returncode != 0

    write_wheel(wheel, "1.2.3")
    write_sdist(sdist, "9.9.9")
    sdist_mismatch = subprocess.run(
        [sys.executable, "-c", metadata_validation, "1.2.3", str(wheel), str(sdist)],
        text=True,
        capture_output=True,
    )
    assert sdist_mismatch.returncode != 0

    query_path = tmp_path / "query.json"
    query_path.write_text(
        json.dumps(
            {
                "columns": ["order_count"],
                "elapsed_ms": 0.1,
                "row_count": 1,
                "rows": [{"order_count": 1}],
            }
        ),
        encoding="utf-8",
    )
    current_version = installed_distribution_version("localql")
    matching_smoke = subprocess.run(
        [sys.executable, "-c", smoke_validation, current_version, str(query_path)],
        text=True,
        capture_output=True,
    )
    assert matching_smoke.returncode == 0, matching_smoke.stderr

    version_mismatch = subprocess.run(
        [sys.executable, "-c", smoke_validation, "0.0.0", str(query_path)],
        text=True,
        capture_output=True,
    )
    assert version_mismatch.returncode != 0

    query_path.write_text(
        json.dumps(
            {
                "columns": ["wrong_column"],
                "row_count": 2,
                "rows": [{"order_count": 2}],
            }
        ),
        encoding="utf-8",
    )
    query_mismatch = subprocess.run(
        [sys.executable, "-c", smoke_validation, current_version, str(query_path)],
        text=True,
        capture_output=True,
    )
    assert query_mismatch.returncode != 0


def test_release_runbook_reconciliation_validates_before_cas() -> None:
    releasing = read_text("docs/releasing.md")
    reconciliation = next(
        block for block in fenced_blocks(releasing, "bash") if "git update-ref" in block
    )

    reconciliation_lines = reconciliation.splitlines()
    assert reconciliation_lines[0] == "set -euo pipefail"
    assert "||" not in reconciliation
    assert '[[ "${current_local_main_oid}" =~ ${oid_re} ]]' in reconciliation
    assert '[[ "${verified_public_main_oid}" =~ ${oid_re} ]]' in reconciliation
    assert 'git cat-file -t "${current_local_main_oid}"' in reconciliation
    assert 'git cat-file -t "${verified_public_main_oid}"' in reconciliation
    assert 'git merge-base --is-ancestor "${current_local_main_oid}"' in reconciliation
    assert "git for-each-ref --format='%(worktreepath)' refs/heads/main" in reconciliation
    for critical_line in (
        '[[ "${current_local_main_oid}" =~ ${oid_re} ]]',
        '[[ "${verified_public_main_oid}" =~ ${oid_re} ]]',
        'test "$(git cat-file -t "${current_local_main_oid}")" = "commit"',
        'test "$(git cat-file -t "${verified_public_main_oid}")" = "commit"',
        'test "$(git rev-parse --verify refs/heads/main)" = "${current_local_main_oid}"',
        'test -z "${main_worktree_path}"',
    ):
        assert reconciliation_lines.count(critical_line) == 1
    origin_index = reconciliation_lines.index(
        'test "$(git rev-parse --verify refs/remotes/origin/main)" = \\'
    )
    assert reconciliation_lines[origin_index : origin_index + 2] == [
        'test "$(git rev-parse --verify refs/remotes/origin/main)" = \\',
        '  "${verified_public_main_oid}"',
    ]
    ancestry_index = reconciliation_lines.index(
        'git merge-base --is-ancestor "${current_local_main_oid}" \\'
    )
    assert reconciliation_lines[ancestry_index : ancestry_index + 2] == [
        'git merge-base --is-ancestor "${current_local_main_oid}" \\',
        '  "${verified_public_main_oid}"',
    ]
    worktree_index = reconciliation_lines.index('main_worktree_path="$(')
    assert reconciliation_lines[worktree_index : worktree_index + 3] == [
        'main_worktree_path="$(',
        "  git for-each-ref --format='%(worktreepath)' refs/heads/main",
        ')"',
    ]
    assert_ordered(
        reconciliation,
        (
            'current_local_main_oid="CURRENT_LOCAL_MAIN_OID"',
            'verified_public_main_oid="VERIFIED_PUBLIC_MAIN_OID"',
            '[[ "${current_local_main_oid}" =~ ${oid_re} ]]',
            '[[ "${verified_public_main_oid}" =~ ${oid_re} ]]',
            'git cat-file -t "${current_local_main_oid}"',
            'git cat-file -t "${verified_public_main_oid}"',
            "git rev-parse --verify refs/heads/main",
            "git rev-parse --verify refs/remotes/origin/main",
            'git merge-base --is-ancestor "${current_local_main_oid}"',
            "git for-each-ref --format='%(worktreepath)' refs/heads/main",
            "git update-ref refs/heads/main",
        ),
    )
    update_index = reconciliation_lines.index("git update-ref refs/heads/main \\")
    assert reconciliation_lines[update_index : update_index + 3] == [
        "git update-ref refs/heads/main \\",
        '  "${verified_public_main_oid}" \\',
        '  "${current_local_main_oid}"',
    ]


def test_public_agents_file_does_not_restore_internal_launch_material() -> None:
    agents = read_text("AGENTS.md")

    assert len(agents.splitlines()) <= 100
    assert "make ci" in agents
    assert "make ci-fresh" in agents
    assert "trusted local input" in agents
    for internal_reference in (
        "docs/CODEX_CAPABILITY_REVIEW.md",
        "docs/superpowers",
        "release-candidate-proof-",
    ):
        assert internal_reference not in agents


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


def test_contribution_surfaces_preserve_v1_scope_and_allow_approved_roadmap_work() -> None:
    contributing = read_text("CONTRIBUTING.md")
    normalized_contributing = normalized_markdown(contributing)
    feature_request = read_text(".github/ISSUE_TEMPLATE/feature_request.yml")
    pull_request = read_text(".github/pull_request_template.md")

    assert "Current v1 contributions should focus on local CSV files" in contributing
    assert "maintainer-approved direction" in contributing
    assert "repository-adopted roadmap milestone" in feature_request
    assert "repository-adopted roadmap implementation lane" in pull_request
    assert "make ci" in contributing
    assert "make ci-fresh" in contributing
    assert "make ci-fresh" in pull_request
    assert "conventional commit-style subjects" in contributing
    assert "docs: update terminal menu guide" in normalized_contributing
    assert "fix: restore recalled TUI result export" in normalized_contributing


def test_make_targets_separate_sync_from_current_environment_checks() -> None:
    makefile = read_text("Makefile")

    assert "sync:\n\tuv sync --all-extras --frozen" in makefile
    assert "ci: format-check lint typecheck test" in makefile
    assert "ci-fresh: sync\n\t$(MAKE) ci" in makefile
    assert "ci-fresh: sync ci" not in makefile
    assert "ci: sync" not in makefile
    for command in (
        "uv run --frozen --no-sync ruff format --check .",
        "uv run --frozen --no-sync ruff check .",
        "uv run --frozen --no-sync --all-extras mypy src",
        "uv run --frozen --no-sync --all-extras pytest",
    ):
        assert command in makefile


def test_canonical_authority_metadata_avoids_transient_working_tree_status() -> None:
    agents = read_text("AGENTS.md")
    roadmap = read_text("docs/ROADMAP.md")
    design = read_text("docs/v2-point-and-query-design.md")
    authority_metadata = {
        "AGENTS.md": "\n".join(
            (
                markdown_section(agents, "Project Contract"),
                markdown_section(agents, "Authority And Structure"),
            )
        ),
        "docs/ROADMAP.md": "\n".join(
            (
                roadmap.split("\n## ", maxsplit=1)[0],
                markdown_section(roadmap, "Maintainer Disposition"),
            )
        ),
        "docs/v2-point-and-query-design.md": design.split("\n## ", maxsplit=1)[0],
    }

    for path, metadata in authority_metadata.items():
        for transient_phrase in (
            "Revised candidate",
            "working-tree",
            "uncommitted",
            "repository adoption",
            "awaiting hostile review",
        ):
            assert transient_phrase not in metadata, f"{path}: {transient_phrase}"


def test_v2_scope_carries_v1_formats_without_double_booking_them() -> None:
    roadmap = read_text("docs/ROADMAP.md")
    design = read_text("docs/v2-point-and-query-design.md")
    roadmap_v2x = markdown_section(roadmap, "v2.x Evolution")
    design_v2x = markdown_section(design, "Target v2.x Ecosystem")
    initial_coverage = normalized_markdown(markdown_section(design, "Initial Source Coverage"))
    experience = normalized_markdown(markdown_section(design, "Experience"))

    for required_concept in ("v1.x", "local-format baseline", "Parquet", "reuse"):
        assert required_concept in initial_coverage
    for required_concept in ("S3", "target v2.x", "not part", "v2.0"):
        assert required_concept in experience
    for v1_format in ("JSON", "NDJSON", "Excel"):
        assert v1_format not in roadmap_v2x
        assert v1_format not in design_v2x


def test_v2_release_gate_applies_only_to_v2_supported_sources() -> None:
    design = read_text("docs/v2-point-and-query-design.md")
    release_gates = normalized_markdown(markdown_section(design, "v2.0 Release Gates"))

    assert "v2.0 release" in release_gates
    assert "shared connector contract" in release_gates
    assert "Every advertised source" not in release_gates


def test_v2_planning_implementation_and_release_gates_are_separate() -> None:
    design = read_text("docs/v2-point-and-query-design.md")
    planning = normalized_markdown(markdown_section(design, "Planning Authorization"))
    plan_approval = normalized_markdown(markdown_section(design, "Plan Approval"))
    implementation = normalized_markdown(
        markdown_section(design, "Slice Implementation Authorization")
    )
    release = normalized_markdown(markdown_section(design, "v2.0 Release Approval"))

    assert "explicitly authorizes preparation of a plan" in planning
    assert "does not authorize" in planning
    assert "Plan approval does not authorize implementation" in plan_approval
    for required_concept in ("plan is approved", "separately authorizes", "verified v1.1"):
        assert required_concept in implementation
    assert "Verified v1.2 is not required before every v2 connector implementation" in (
        implementation
    )
    for required_concept in ("v1.2 local-format baseline", "exact release artifacts"):
        assert required_concept in release


def test_pyproject_public_metadata_is_consistent() -> None:
    payload = tomllib.loads(read_text("pyproject.toml"))
    project = payload["project"]

    assert payload["build-system"] == {
        "requires": ["hatchling"],
        "build-backend": "hatchling.build",
    }
    assert project["name"] == "localql"
    assert project["version"] == "1.0.2"
    assert project["description"] == (
        "Local-first CSV analytics with a CLI, optional terminal workbench, "
        "and automation-friendly Python and JSON interfaces."
    )
    assert project["readme"] == "README.md"
    assert project["license"] == "MIT"
    assert "LICENSE" in payload["project"]["license-files"]
    assert "License :: OSI Approved :: MIT License" in project["classifiers"]
    assert "Operating System :: OS Independent" in project["classifiers"]
    assert set(project["keywords"]) == {
        "automation",
        "cli",
        "csv",
        "data-engineering",
        "data-quality",
        "duckdb",
        "local-analytics",
        "sql",
        "terminal",
        "tui",
    }
    assert project["urls"] == {
        "Repository": "https://github.com/highlordleonas/csvql",
        "Documentation": (
            "https://github.com/highlordleonas/csvql/blob/main/docs/getting-started.md"
        ),
        "Issues": "https://github.com/highlordleonas/csvql/issues",
        "Security": "https://github.com/highlordleonas/csvql/blob/main/SECURITY.md",
        "Changelog": "https://github.com/highlordleonas/csvql/blob/main/CHANGELOG.md",
        "Release notes": (
            "https://github.com/highlordleonas/csvql/blob/main/docs/release-notes/v1.md"
        ),
    }
    assert "textual>=8.2.8" in project["optional-dependencies"]["tui"]
    assert project["requires-python"] == ">=3.11,<3.15"
    for classifier in (
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    ):
        assert classifier in project["classifiers"]


def test_v1_0_2_release_copy_covers_sharpening_without_contract_drift() -> None:
    changelog = markdown_section(read_text("CHANGELOG.md"), "[1.0.2] - 2026-07-15")
    notes = markdown_section(read_text("docs/release-notes/v1.md"), "1.0.2")
    for phrase in (
        "installed-user documentation",
        "reproducible release evidence",
        "wheel and source distribution",
        "core and optional TUI",
    ):
        assert phrase in changelog
        assert phrase in notes
    for document in (changelog, notes):
        assert (
            "v1 CSV CLI, Python, catalog, JSON, exit-code, and export contracts are unchanged"
            in normalized_markdown(document)
        )


def test_publish_workflow_is_manual_only() -> None:
    workflow = read_text(".github/workflows/publish.yml")
    payload = yaml.safe_load(workflow)

    assert set(payload[True]) == {"workflow_dispatch"}
    assert payload["permissions"] == {"contents": "read"}
    assert "workflow_dispatch:" in workflow


def test_publish_dispatch_binds_exact_release_identity() -> None:
    payload = yaml.safe_load(read_text(".github/workflows/publish.yml"))
    dispatch = payload[True]["workflow_dispatch"]

    assert dispatch["inputs"] == {
        "version": {
            "description": "Exact package version approved for publication",
            "required": True,
            "type": "string",
        },
        "tag_object_oid": {
            "description": "Exact annotated tag object ID approved for publication",
            "required": True,
            "type": "string",
        },
        "peeled_commit_oid": {
            "description": "Exact commit ID peeled from the annotated tag",
            "required": True,
            "type": "string",
        },
        "tag_ci_workflow_id": {
            "description": "Exact successful tag-CI workflow ID",
            "required": True,
            "type": "string",
        },
        "tag_ci_run_id": {
            "description": "Exact successful tag-CI run ID",
            "required": True,
            "type": "string",
        },
        "tag_ci_run_attempt": {
            "description": "Exact successful tag-CI run attempt",
            "required": True,
            "type": "string",
        },
    }
    assert payload["concurrency"] == {
        "group": "publish-${{ github.ref }}",
        "cancel-in-progress": False,
    }


def test_publish_build_gate_reads_one_exact_tag_ci_attempt() -> None:
    payload = yaml.safe_load(read_text(".github/workflows/publish.yml"))
    build = payload["jobs"]["build-and-verify"]
    runs = "\n".join(str(step.get("run", "")) for step in build["steps"])

    assert build["permissions"] == {"contents": "read", "actions": "read"}
    for required in (
        "APPROVED_TAG_OBJECT_OID",
        "APPROVED_PEELED_COMMIT_OID",
        "APPROVED_TAG_CI_WORKFLOW_ID",
        "APPROVED_TAG_CI_RUN_ID",
        "APPROVED_TAG_CI_RUN_ATTEMPT",
        "git cat-file -t",
        "git merge-base --is-ancestor",
        "/actions/runs/${APPROVED_TAG_CI_RUN_ID}",
        "/actions/workflows/${APPROVED_TAG_CI_WORKFLOW_ID}",
        "/attempts/${APPROVED_TAG_CI_RUN_ATTEMPT}/jobs?per_page=100",
        '".github/workflows/ci.yml"',
        '"test (ubuntu-latest, 3.11)"',
        '"test (windows-latest, 3.12)"',
    ):
        assert required in runs
    assert "gh run list" not in runs


def test_publish_high_risk_proof_shells_fail_closed() -> None:
    payload = yaml.safe_load(read_text(".github/workflows/publish.yml"))
    proof_steps = {
        "Verify release and tag-CI identity": payload["jobs"]["build-and-verify"]["steps"],
        "Install exact public release and run core and TUI smoke": payload["jobs"][
            "post-publish-verification"
        ]["steps"],
    }
    observed_first_lines = {
        step_name: str(
            next(step for step in steps if step.get("name") == step_name).get("run", "")
        ).splitlines()[0]
        for step_name, steps in proof_steps.items()
    }

    assert observed_first_lines == dict.fromkeys(proof_steps, "set -euo pipefail")


def test_publish_verifies_exact_publisher_and_public_index_install() -> None:
    payload = yaml.safe_load(read_text(".github/workflows/publish.yml"))
    publish_steps = payload["jobs"]["publish"]["steps"]
    verification = payload["jobs"]["post-publish-verification"]
    verification_runs = "\n".join(str(step.get("run", "")) for step in verification["steps"])
    publish_index = next(
        index
        for index, step in enumerate(publish_steps)
        if str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish@")
    )

    assert publish_steps[publish_index - 1]["name"] == "Require version to be absent from PyPI"
    for required in (
        '"kind": "GitHub"',
        '"repository": "highlordleonas/csvql"',
        '"workflow": "publish.yml"',
        '"environment": "pypi"',
        'bundle.get("publisher")',
        '"published_files"',
        '"publication_run_id"',
        "UV_NO_CACHE=1",
        "https://pypi.org/simple",
        "localql==${EXPECTED_VERSION}",
        "localql[tui]==${EXPECTED_VERSION}",
        'csvql" query',
        'csvql" menu --help',
    ):
        assert required in verification_runs


def test_release_runbook_names_strict_publication_recovery() -> None:
    releasing = normalized_markdown(read_text("docs/releasing.md"))
    for required in (
        "rerun-failed-jobs",
        "whole-run rerun is not authorized",
        "public-but-unreleased",
        "never top up",
        "consumer impact",
        "verified PyPI filenames",
        "draft Release",
        "body SHA-256",
    ):
        assert required in releasing


def test_v102_documents_match_implemented_but_unreleased_truth() -> None:
    roadmap = normalized_markdown(read_text("docs/ROADMAP.md"))
    spill_design = normalized_markdown(read_text("docs/v1.0.2-tui-spill-reliability-design.md"))

    assert "Status: Implemented locally; release preparation in progress" in roadmap
    assert "TUI spill reliability and portable navigation fallbacks are implemented" in roadmap
    assert "bounded query execution remains deferred to v1.1" in roadmap
    assert "release-version source refactor remains deferred" in roadmap
    assert "Implemented and locally verified; unreleased" in spill_design
    assert "implementation not approved" not in spill_design
    assert "fully materializes" in roadmap


def test_v102_candidate_identity_is_machine_consistent() -> None:
    workflow = read_text(".github/workflows/publish.yml")
    package_init = read_text("src/csvql/__init__.py")
    changelog = read_text("CHANGELOG.md")
    release_notes = read_text("docs/release-notes/v1.md")

    assert "EXPECTED_TAG: v1.0.2" in workflow
    assert 'EXPECTED_VERSION: "1.0.2"' in workflow
    assert "pypi-release-1.0.2.json" in workflow
    assert '__version__ = "1.0.2"' in package_init
    assert changelog.index("## [1.0.2]") < changelog.index("## [1.0.1]")
    assert release_notes.index("## 1.0.2") < release_notes.index("## 1.0.1")


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

    assert "post-publish-verification" in jobs
    verification_job = jobs["post-publish-verification"]

    assert "id-token" not in (build_job.get("permissions") or {})
    assert publish_job["needs"] == "build-and-verify"
    assert publish_job["environment"] == "pypi"
    assert publish_job["permissions"] == {"contents": "read", "id-token": "write"}
    assert verification_job["needs"] == "publish"
    assert verification_job["permissions"] == {"contents": "read"}
    assert "id-token" not in verification_job["permissions"]
    assert "environment" not in verification_job
    assert verification_job["timeout-minutes"] == 10

    verification_step_ids = [step.get("id") for step in verification_job["steps"]]
    assert "verify_pypi_release" in verification_step_ids
    verification_step = next(
        step for step in verification_job["steps"] if step.get("id") == "verify_pypi_release"
    )
    assert verification_step["timeout-minutes"] == 7
    assert verification_step["timeout-minutes"] < verification_job["timeout-minutes"]

    build_runs = "\n".join(str(step.get("run", "")) for step in build_job["steps"])
    publish_runs = "\n".join(str(step.get("run", "")) for step in publish_job["steps"])
    publish_uses = "\n".join(str(step.get("uses", "")) for step in publish_job["steps"])
    verification_runs = "\n".join(str(step.get("run", "")) for step in verification_job["steps"])
    verification_uses = "\n".join(str(step.get("uses", "")) for step in verification_job["steps"])

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

    download_step = next(
        step
        for step in verification_job["steps"]
        if str(step.get("uses", "")).startswith("actions/download-artifact@")
    )
    upload_step = next(
        step
        for step in verification_job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    step_names = [step.get("name") for step in verification_job["steps"]]
    assert "Record failed verification outcome" in step_names
    failure_step = next(
        step
        for step in verification_job["steps"]
        if step.get("name") == "Record failed verification outcome"
    )
    assert download_step["with"] == {
        "name": "localql-1.0.2-dist",
        "path": "release-artifacts",
    }
    assert upload_step["uses"] == (
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
    )
    assert upload_step["with"] == {
        "name": "localql-1.0.2-pypi-verification",
        "path": "pypi-verification",
        "if-no-files-found": "error",
    }
    assert upload_step["if"] == "always()"
    assert verification_job["steps"].index(verification_step) < verification_job["steps"].index(
        failure_step
    )
    assert verification_job["steps"].index(failure_step) < verification_job["steps"].index(
        upload_step
    )
    assert failure_step["if"] == "always() && steps.verify_pypi_release.outcome != 'success'"
    failure_run = str(failure_step["run"])
    assert "verification-outcome.txt" in failure_run
    assert "verification-status.txt" in failure_run
    assert "failed, timed out, or skipped" in failure_run
    assert "actions/download-artifact@" in verification_uses
    assert "actions/upload-artifact@" in verification_uses

    for required in (
        "SHA256SUMS.txt",
        "MAX_ATTEMPTS = 8",
        "REQUEST_TIMEOUT_SECONDS = 10",
        "POLL_SECONDS = 10",
        "for attempt in range(1, MAX_ATTEMPTS + 1)",
        "urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS)",
        "time.sleep(POLL_SECONDS)",
        "https://pypi.org/pypi/{project}/json",
        "https://pypi.org/pypi/{project}/{version}/json",
        "https://pypi.org/integrity/{project}/{version}",
        "{quoted_filename}/provenance",
        "application/vnd.pypi.integrity.v1+json",
        'release_metadata.get("urls")',
        "published_file_records",
        'provenance.get("attestation_bundles")',
        'bundle.get("attestations")',
        "pypi-project.json",
        "pypi-release-1.0.2.json",
        "pypi-verification",
        "release metadata and digests verified",
        "provenance and non-empty attestation receipts captured",
        "No cryptographic attestation verification was performed",
    ):
        assert required in verification_runs

    max_attempts = int(re.search(r"MAX_ATTEMPTS = (\d+)", verification_runs).group(1))
    request_timeout = int(re.search(r"REQUEST_TIMEOUT_SECONDS = (\d+)", verification_runs).group(1))
    poll_seconds = int(re.search(r"POLL_SECONDS = (\d+)", verification_runs).group(1))
    worst_case_seconds = max_attempts * 4 * request_timeout + (max_attempts - 1) * poll_seconds
    assert worst_case_seconds < verification_step["timeout-minutes"] * 60

    for forbidden in (
        "uv sync",
        "uv build",
        "uv run",
        "python -m csvql",
        "scripts/",
        "gh-action-pypi-publish",
    ):
        assert forbidden not in verification_runs

    assert "gh-action-pypi-publish@" not in verification_uses
    assert "attestations verified" not in workflow.lower()
