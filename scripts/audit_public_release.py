"""Audit the committed repository tree before a public release."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Final

PUBLIC_ROOT_FILES: Final[frozenset[str]] = frozenset(
    {
        ".gitignore",
        ".python-version",
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "Makefile",
        "README.md",
        "SECURITY.md",
        "SUPPORT.md",
        "pyproject.toml",
        "uv.lock",
    }
)
PUBLIC_DOCUMENT_FILES: Final[frozenset[str]] = frozenset(
    {
        "docs/ARCHITECTURE.md",
        "docs/ROADMAP.md",
        "docs/assets/localql-social-preview.jpg",
        "docs/assets/localql-social-preview.png",
        "docs/assets/localql-terminal-project.svg",
        "docs/assets/localql-terminal-query.svg",
        "docs/assets/localql-tui-workbench.svg",
        "docs/cli-reference.md",
        "docs/development.md",
        "docs/faq.md",
        "docs/getting-started.md",
        "docs/json-contracts.md",
        "docs/release-notes/v1.md",
        "docs/troubleshooting.md",
        "docs/tui-guide.md",
    }
)
PUBLIC_GITHUB_FILES: Final[frozenset[str]] = frozenset(
    {
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/config.yml",
        ".github/ISSUE_TEMPLATE/docs_issue.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/pull_request_template.md",
        ".github/workflows/ci.yml",
        ".github/workflows/publish.yml",
    }
)
PUBLIC_GIT_SAFETY_FILES: Final[frozenset[str]] = frozenset(
    {
        ".githooks/pre-push",
    }
)
PUBLIC_SCRIPT_FILES: Final[frozenset[str]] = frozenset(
    {
        "scripts/audit_package_contents.py",
        "scripts/audit_public_release.py",
        "scripts/benchmark_csvql.py",
        "scripts/git_public_push_guard.py",
        "scripts/install_git_safety.py",
        "scripts/render_benchmark_summary.py",
        "scripts/release-audit-tool.in",
        "scripts/release-audit-tool-requirements.txt",
        "scripts/release-build-constraints.txt",
        "scripts/verify_dependency_audit.py",
        "scripts/verify_installed_artifacts.py",
        "scripts/verify_release_artifacts.py",
        "scripts/verify_release_readiness.py",
    }
)
PUBLIC_EXAMPLE_FILES: Final[frozenset[str]] = frozenset(
    {
        "examples/saas_revenue/.csvql.yml",
        "examples/saas_revenue/README.md",
        "examples/saas_revenue/data/customers.csv",
        "examples/saas_revenue/data/revenue_movements.csv",
        "examples/saas_revenue/data/subscriptions.csv",
        "examples/saas_revenue/queries/revenue_health.sql",
        "examples/saas_revenue/scripts/regenerate_data.py",
        "examples/sales/.csvql.yml",
        "examples/sales/data/customers.csv",
        "examples/sales/data/orders.csv",
        "examples/sales/queries/customer_ltv.sql",
        "examples/sales/queries/revenue_by_month.sql",
    }
)
PUBLIC_SOURCE_FILES: Final[frozenset[str]] = frozenset(
    {
        "src/csvql/__init__.py",
        "src/csvql/__main__.py",
        "src/csvql/adapter_factory.py",
        "src/csvql/api.py",
        "src/csvql/atomic_write.py",
        "src/csvql/benchmark_data.py",
        "src/csvql/benchmark_runner.py",
        "src/csvql/benchmarking.py",
        "src/csvql/bounded_result.py",
        "src/csvql/checks.py",
        "src/csvql/cli.py",
        "src/csvql/csv_adapter.py",
        "src/csvql/doctor.py",
        "src/csvql/engine.py",
        "src/csvql/exceptions.py",
        "src/csvql/export.py",
        "src/csvql/inspection.py",
        "src/csvql/models.py",
        "src/csvql/operation.py",
        "src/csvql/output.py",
        "src/csvql/parquet_adapter.py",
        "src/csvql/profiling.py",
        "src/csvql/project_config.py",
        "src/csvql/quality.py",
        "src/csvql/query_workflow.py",
        "src/csvql/release_readiness.py",
        "src/csvql/result_codec.py",
        "src/csvql/result_spool.py",
        "src/csvql/result_stream.py",
        "src/csvql/source.py",
        "src/csvql/source_adapter.py",
        "src/csvql/source_coordinator.py",
        "src/csvql/source_detection.py",
        "src/csvql/source_identifiers.py",
        "src/csvql/source_manifest.py",
        "src/csvql/source_operations.py",
        "src/csvql/source_registry.py",
        "src/csvql/source_resolver.py",
        "src/csvql/source_runtime.py",
        "src/csvql/sql_file.py",
        "src/csvql/sql_utils.py",
        "src/csvql/streaming_export.py",
        "src/csvql/table_mapping.py",
        "src/csvql/terminal_text.py",
        "src/csvql/tui_app.py",
        "src/csvql/tui_editor.py",
        "src/csvql/tui_help.py",
        "src/csvql/tui_launcher.py",
        "src/csvql/tui_native_picker.py",
        "src/csvql/tui_query_runner.py",
        "src/csvql/tui_result_store.py",
        "src/csvql/tui_results.py",
        "src/csvql/tui_sql_assist.py",
        "src/csvql/tui_state.py",
        "src/csvql/tui_workflows.py",
    }
)
PUBLIC_TEST_FILES: Final[frozenset[str]] = frozenset(
    {
        "tests/test_api.py",
        "tests/test_adapter_contract.py",
        "tests/test_adapter_factory.py",
        "tests/test_atomic_write.py",
        "tests/test_benchmark_data.py",
        "tests/test_benchmark_runner.py",
        "tests/test_benchmarking.py",
        "tests/test_bounded_execution.py",
        "tests/test_bounded_resource_contract.py",
        "tests/test_bounded_result.py",
        "tests/test_checks.py",
        "tests/test_cli_check.py",
        "tests/test_cli_doctor.py",
        "tests/test_cli_inspect_sample.py",
        "tests/test_cli_menu.py",
        "tests/test_cli_profile.py",
        "tests/test_cli_project_catalog.py",
        "tests/test_cli_query.py",
        "tests/test_cli_run_export.py",
        "tests/test_csv_adapter.py",
        "tests/test_doctor.py",
        "tests/test_dependency_audit.py",
        "tests/test_engine_sources.py",
        "tests/test_example_project.py",
        "tests/test_export.py",
        "tests/test_failure_gallery.py",
        "tests/test_inspection.py",
        "tests/test_git_public_push_guard.py",
        "tests/test_install_git_safety.py",
        "tests/test_installed_artifacts.py",
        "tests/test_models.py",
        "tests/test_open_source_launch_docs.py",
        "tests/test_operation.py",
        "tests/test_output.py",
        "tests/test_package_audit.py",
        "tests/test_parquet_adapter.py",
        "tests/test_profiling.py",
        "tests/test_project_config.py",
        "tests/test_public_compatibility.py",
        "tests/test_public_release_audit.py",
        "tests/test_quality.py",
        "tests/test_query_source_snapshots.py",
        "tests/test_query_workflow.py",
        "tests/test_result_codec.py",
        "tests/test_result_spool.py",
        "tests/test_result_stream.py",
        "tests/test_release_readiness.py",
        "tests/test_release_artifacts.py",
        "tests/test_source.py",
        "tests/test_source_adapter.py",
        "tests/test_source_boundary.py",
        "tests/test_source_coordinator.py",
        "tests/test_source_detection.py",
        "tests/test_source_errors.py",
        "tests/test_source_identifiers.py",
        "tests/test_source_manifest.py",
        "tests/test_source_operations.py",
        "tests/test_source_registry.py",
        "tests/test_source_resolver.py",
        "tests/test_sql_file.py",
        "tests/test_sql_utils.py",
        "tests/test_streaming_export.py",
        "tests/test_table_mapping.py",
        "tests/test_terminal_text.py",
        "tests/test_tui_app.py",
        "tests/test_tui_bounded_resource_contract.py",
        "tests/test_tui_editor.py",
        "tests/test_tui_failure_contract.py",
        "tests/test_tui_help.py",
        "tests/test_tui_native_picker.py",
        "tests/test_tui_query_runner.py",
        "tests/test_tui_result_capacity.py",
        "tests/test_tui_result_store.py",
        "tests/test_tui_result_recovery.py",
        "tests/test_tui_results.py",
        "tests/test_tui_sql_assist.py",
        "tests/test_tui_state.py",
        "tests/test_tui_v11_compatibility.py",
        "tests/test_tui_workflows.py",
        "tests/test_user_docs.py",
    }
)

PUBLIC_PATH_CATEGORIES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "root": PUBLIC_ROOT_FILES,
        "documentation": PUBLIC_DOCUMENT_FILES,
        "github": PUBLIC_GITHUB_FILES,
        "git-safety": PUBLIC_GIT_SAFETY_FILES,
        "scripts": PUBLIC_SCRIPT_FILES,
        "examples": PUBLIC_EXAMPLE_FILES,
        "source": PUBLIC_SOURCE_FILES,
        "tests": PUBLIC_TEST_FILES,
    }
)
PUBLIC_PATHS: Final[frozenset[str]] = frozenset().union(*PUBLIC_PATH_CATEGORIES.values())
IMMUTABLE_FORBIDDEN_COMPONENTS: Final[frozenset[str]] = frozenset(
    {".agents", ".codex", ".internal"}
)
IMMUTABLE_FORBIDDEN_PREFIXES: Final[frozenset[str]] = frozenset({"docs/superpowers"})
IMMUTABLE_FORBIDDEN_NAMES: Final[frozenset[str]] = frozenset(
    {"AGENTS.md", "AGENTS.override.md", "CODEX_CAPABILITY_REVIEW.md"}
)
REGULAR_FILE_MODES: Final[frozenset[str]] = frozenset({"100644", "100755"})
RELEASE_STATE_PATHS: Final[frozenset[str]] = frozenset(
    {
        "CHANGELOG.md",
        "docs/release-notes/v1.md",
        "pyproject.toml",
    }
)
UNFINALIZED_RELEASE_MARKERS: Final[tuple[str, ...]] = (
    "unreleased",
    "release candidate",
    "not yet published",
)


class AuditError(RuntimeError):
    """Raised when the public release contract is not satisfied."""


@dataclass(frozen=True, slots=True)
class TreeEntry:
    """A committed Git tree entry needed by the release audit."""

    mode: str
    object_type: str
    object_id: str
    path: str


def canonical_repository_identity(repository: str) -> str:
    """Normalize a GitHub repository URL or owner/repository identity."""

    candidate = repository.strip().rstrip("/")
    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    for prefix in (
        "git@github.com:",
        "ssh://git@github.com/",
        "https://github.com/",
        "http://github.com/",
    ):
        if candidate.startswith(prefix):
            candidate = candidate.removeprefix(prefix)
            break
    parts = candidate.split("/")
    if len(parts) != 2 or not all(parts):
        raise AuditError("repository identity is invalid")
    return "/".join(part.casefold() for part in parts)


def classify_tracked_paths(paths: Iterable[str]) -> Mapping[str, frozenset[str]]:
    """Classify tracked paths against the explicit public release contract."""

    tracked_paths = frozenset(paths)
    if any(is_immutable_forbidden_path(path) for path in tracked_paths):
        raise AuditError("committed tree contains protected paths")
    if tracked_paths - PUBLIC_PATHS:
        raise AuditError("committed tree contains an unclassified tracked path")
    categories = {
        category: files & tracked_paths for category, files in PUBLIC_PATH_CATEGORIES.items()
    }
    if frozenset().union(*categories.values()) != tracked_paths:
        raise AuditError("committed tree contains an unclassified tracked path")
    return MappingProxyType(categories)


def is_immutable_forbidden_path(path: str) -> bool:
    """Return whether a tracked path is always excluded from a public release tree."""

    parts = path.split("/")
    is_release_candidate_proof = (
        len(parts) == 2
        and parts[0] == "docs"
        and parts[1].startswith("release-candidate-proof-")
        and parts[1].endswith(".md")
    )
    return (
        any(part in IMMUTABLE_FORBIDDEN_NAMES for part in parts)
        or any(part in IMMUTABLE_FORBIDDEN_COMPONENTS for part in parts)
        or any(
            path == prefix or path.startswith(f"{prefix}/")
            for prefix in IMMUTABLE_FORBIDDEN_PREFIXES
        )
        or is_release_candidate_proof
    )


def committed_tree_entries(repo: Path, candidate: str) -> tuple[TreeEntry, ...]:
    """Return all recursively tracked entries from a committed Git tree."""

    tree = _resolve_tree(repo, candidate)
    raw_entries = _run_git_bytes(repo, "ls-tree", "--full-tree", "-r", "-z", tree)
    entries: list[TreeEntry] = []
    for raw_entry in raw_entries.split(b"\0"):
        if not raw_entry:
            continue
        metadata, raw_path = raw_entry.split(b"\t", maxsplit=1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ", maxsplit=2)
        entries.append(
            TreeEntry(
                mode=mode,
                object_type=object_type,
                object_id=object_id,
                path=raw_path.decode("utf-8", errors="surrogateescape"),
            )
        )
    return tuple(entries)


def verify_regular_public_files(entries: Iterable[TreeEntry]) -> None:
    """Require every classified public tree entry to be a regular blob."""

    if any(
        entry.object_type != "blob" or entry.mode not in REGULAR_FILE_MODES for entry in entries
    ):
        raise AuditError("public release entries must be regular files")


def verify_finalized_release_state(repo: Path, entries: Iterable[TreeEntry]) -> None:
    """Require committed package release documentation to be finalized."""

    entries_by_path = {entry.path: entry for entry in entries}
    present_paths = RELEASE_STATE_PATHS & entries_by_path.keys()
    if present_paths != RELEASE_STATE_PATHS:
        raise AuditError("release state is not finalized")

    try:
        pyproject = tomllib.loads(
            _read_committed_blob(repo, entries_by_path["pyproject.toml"]).decode("utf-8")
        )
        version = pyproject["project"]["version"]
    except (KeyError, TypeError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise AuditError("release state is not finalized") from error
    if not isinstance(version, str) or not version:
        raise AuditError("release state is not finalized")

    try:
        changelog = _read_committed_blob(repo, entries_by_path["CHANGELOG.md"]).decode("utf-8")
        release_notes = _read_committed_blob(
            repo, entries_by_path["docs/release-notes/v1.md"]
        ).decode("utf-8")
    except UnicodeDecodeError as error:
        raise AuditError("release state is not finalized") from error

    changelog_heading = re.compile(
        rf"^## \[{re.escape(version)}\] - (?P<date>\d{{4}}-\d{{2}}-\d{{2}})$",
        flags=re.MULTILINE,
    )
    changelog_match = changelog_heading.search(changelog)
    release_notes_heading = re.compile(
        rf"^## {re.escape(version)}$",
        flags=re.MULTILINE,
    )
    release_notes_match = release_notes_heading.search(release_notes)
    if changelog_match is None or release_notes_match is None:
        raise AuditError("release state is not finalized")
    first_changelog_heading = re.search(r"^## .+$", changelog, flags=re.MULTILINE)
    first_release_notes_heading = re.search(r"^## .+$", release_notes, flags=re.MULTILINE)
    if (
        first_changelog_heading is None
        or first_changelog_heading.start() != changelog_match.start()
        or first_release_notes_heading is None
        or first_release_notes_heading.start() != release_notes_match.start()
    ):
        raise AuditError("release state is not finalized")
    try:
        date.fromisoformat(changelog_match.group("date"))
    except ValueError as error:
        raise AuditError("release state is not finalized") from error

    if any(
        marker in document.casefold()
        for document in (changelog, release_notes)
        for marker in UNFINALIZED_RELEASE_MARKERS
    ):
        raise AuditError("release state is not finalized")


def verify_single_commit_topology(repo: Path, base: str, candidate: str) -> tuple[str, str]:
    """Require candidate to be a non-merge child commit of the declared base."""

    base_commit = _resolve_commit(repo, base)
    candidate_commit = _resolve_commit(repo, candidate)
    if not _git_succeeds(repo, "merge-base", "--is-ancestor", base_commit, candidate_commit):
        raise AuditError("declared base is not an ancestor of the candidate")
    commit_count = _run_git(repo, "rev-list", "--count", f"{base_commit}..{candidate_commit}")
    if commit_count != "1":
        raise AuditError("candidate must contain exactly one commit above the declared base")
    parents = _run_git(repo, "rev-list", "--parents", "-n", "1", candidate_commit).split()
    if len(parents) != 2:
        raise AuditError("candidate commit must have exactly one parent")
    if parents[1] != base_commit:
        raise AuditError("candidate parent does not match the declared base")
    return base_commit, candidate_commit


def verify_author_identity(
    repo: Path, candidate: str, expected_author_name: str, expected_author_email: str
) -> None:
    """Require the candidate commit to have the exact declared author identity."""

    author = _run_git(repo, "show", "-s", "--format=%an%x00%ae", candidate)
    author_name, separator, author_email = author.partition("\0")
    if not separator or (author_name, author_email) != (
        expected_author_name,
        expected_author_email,
    ):
        raise AuditError("candidate author identity does not match the declared author")


def verify_clean_tracked_state(repo: Path) -> None:
    """Require the repository worktree to have no tracked-file changes."""

    status = _run_git(repo, "status", "--porcelain", "--untracked-files=no")
    if status:
        raise AuditError("repository must have a clean tracked worktree")


def audit_public_release(
    *,
    repo: Path,
    expected_repository: str,
    base: str | None,
    candidate: str = "HEAD",
    expected_author_name: str | None,
    expected_author_email: str | None,
    require_clean_worktree: bool,
    tree_only: bool,
) -> None:
    """Validate the public tree and, unless requested otherwise, commit provenance."""

    repo_path = repo.resolve()
    _verify_repository_identity(repo_path, expected_repository)
    entries = committed_tree_entries(repo_path, candidate)
    classify_tracked_paths(entry.path for entry in entries)
    verify_regular_public_files(entries)
    verify_finalized_release_state(repo_path, entries)
    if require_clean_worktree:
        verify_clean_tracked_state(repo_path)
    if tree_only:
        return
    if base is None:
        raise AuditError("normal audit requires a declared base")
    if expected_author_name is None or expected_author_email is None:
        raise AuditError("normal audit requires a declared author identity")
    _, candidate_commit = verify_single_commit_topology(repo_path, base, candidate)
    verify_author_identity(
        repo_path,
        candidate_commit,
        expected_author_name,
        expected_author_email,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the public release audit from command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--expected-repository", required=True)
    parser.add_argument("--base")
    parser.add_argument("--candidate")
    parser.add_argument("--expected-author-name")
    parser.add_argument("--expected-author-email")
    parser.add_argument("--require-clean-worktree", action="store_true")
    parser.add_argument("--tree-only", action="store_true")
    args = parser.parse_args(argv)

    if args.tree_only and args.candidate is None:
        parser.error("--tree-only requires an explicitly named --candidate")
    if not args.tree_only and args.base is None:
        parser.error("normal audit requires --base")
    if not args.tree_only and (
        args.expected_author_name is None or args.expected_author_email is None
    ):
        parser.error("normal audit requires --expected-author-name and --expected-author-email")

    try:
        audit_public_release(
            repo=args.repo,
            expected_repository=args.expected_repository,
            base=args.base,
            candidate=args.candidate or "HEAD",
            expected_author_name=args.expected_author_name,
            expected_author_email=args.expected_author_email,
            require_clean_worktree=args.require_clean_worktree,
            tree_only=args.tree_only,
        )
    except AuditError as error:
        print(f"public release audit failed: {error}", file=sys.stderr)
        return 1
    print("public release audit passed")
    return 0


def _verify_repository_identity(repo: Path, expected_repository: str) -> None:
    """Verify that origin resolves to the expected canonical repository identity."""

    try:
        actual_repository = canonical_repository_identity(
            _run_git(repo, "config", "--get", "remote.origin.url")
        )
    except AuditError as error:
        raise AuditError("repository identity cannot be verified") from error
    if actual_repository != canonical_repository_identity(expected_repository):
        raise AuditError("repository identity does not match the declared repository")


def _resolve_tree(repo: Path, revision: str) -> str:
    """Resolve a revision to a committed tree object."""

    return _run_git(repo, "rev-parse", "--verify", f"{revision}^{{tree}}")


def _read_committed_blob(repo: Path, entry: TreeEntry) -> bytes:
    """Return one regular file's bytes from the audited committed tree."""

    if entry.object_type != "blob" or entry.mode not in REGULAR_FILE_MODES:
        raise AuditError("release state is not finalized")
    return _run_git_bytes(repo, "cat-file", "blob", entry.object_id)


def _resolve_commit(repo: Path, revision: str) -> str:
    """Resolve a revision to a commit object."""

    return _run_git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}")


def _git_succeeds(repo: Path, *arguments: str) -> bool:
    """Return whether Git completed an expected boolean query successfully."""

    return _execute_git(repo, arguments).returncode == 0


def _run_git(repo: Path, *arguments: str) -> str:
    """Run Git and return text output without exposing command failure output."""

    completed = _execute_git(repo, arguments)
    if completed.returncode != 0:
        raise AuditError("git command failed")
    return completed.stdout.decode("utf-8", errors="replace").strip()


def _run_git_bytes(repo: Path, *arguments: str) -> bytes:
    """Run Git and return byte output without exposing command failure output."""

    completed = _execute_git(repo, arguments)
    if completed.returncode != 0:
        raise AuditError("git command failed")
    return completed.stdout


def _execute_git(repo: Path, arguments: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    """Execute a bounded Git command with captured, sanitized failures."""

    if not repo.is_dir():
        raise AuditError("repository path is unavailable")
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=False,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AuditError("git command could not be completed") from error


if __name__ == "__main__":
    raise SystemExit(main())
