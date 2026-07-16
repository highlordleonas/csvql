from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "audit_public_release.py"
EXPECTED_REPOSITORY = "highlordleonas/csvql"
EXPECTED_AUTHOR_NAME = "highlordleonas"
EXPECTED_AUTHOR_EMAIL = "richarddemke@gmail.com"


@pytest.fixture(scope="module")
def audit_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_public_release", AUDIT_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def tracked_paths(repo_root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.splitlines()


def run_git(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def commit_file(repo_root: Path, relative_path: str, contents: str) -> str:
    path = repo_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    run_git(repo_root, "add", relative_path)
    run_git(repo_root, "commit", "-m", f"Add {relative_path}")
    return run_git(repo_root, "rev-parse", "HEAD")


def initialize_repository(tmp_path: Path) -> tuple[Path, str]:
    repo_root = tmp_path / "release-audit"
    repo_root.mkdir()
    run_git(repo_root, "init", "--initial-branch=main")
    run_git(repo_root, "config", "user.name", EXPECTED_AUTHOR_NAME)
    run_git(repo_root, "config", "user.email", EXPECTED_AUTHOR_EMAIL)
    run_git(
        repo_root,
        "remote",
        "add",
        "origin",
        "git@github.com:highlordleonas/csvql.git",
    )
    commit_file(repo_root, "README.md", "Initial public file.\n")
    base = commit_file(repo_root, "docs/faq.md", "Initial documentation.\n")
    return repo_root, base


def run_audit(
    audit_module: ModuleType,
    repo_root: Path,
    base: str | None,
    candidate: str = "HEAD",
    *,
    require_clean_worktree: bool = False,
    tree_only: bool = False,
) -> None:
    audit_module.audit_public_release(
        repo=repo_root,
        expected_repository=EXPECTED_REPOSITORY,
        base=base,
        candidate=candidate,
        expected_author_name=EXPECTED_AUTHOR_NAME,
        expected_author_email=EXPECTED_AUTHOR_EMAIL,
        require_clean_worktree=require_clean_worktree,
        tree_only=tree_only,
    )


def test_current_tracked_paths_fit_positive_public_categories(audit_module: ModuleType) -> None:
    observed_paths = frozenset(tracked_paths(REPO_ROOT))

    categories = audit_module.classify_tracked_paths(observed_paths)

    assert audit_module.PUBLIC_PATHS == observed_paths
    assert frozenset().union(*categories.values()) == observed_paths
    assert sum(len(paths) for paths in categories.values()) == len(observed_paths)


def test_each_allowed_public_path_has_a_positive_category(
    audit_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_paths = frozenset(tracked_paths(REPO_ROOT))
    extra_path = "future-public-file.md"
    monkeypatch.setattr(
        audit_module,
        "PUBLIC_PATHS",
        audit_module.PUBLIC_PATHS | frozenset({extra_path}),
    )

    with pytest.raises(audit_module.AuditError, match="unclassified"):
        audit_module.classify_tracked_paths([*observed_paths, extra_path])


def test_unmatched_tracked_path_is_rejected(audit_module: ModuleType) -> None:
    with pytest.raises(audit_module.AuditError, match="unclassified"):
        audit_module.classify_tracked_paths(["README.md", "unmatched/path.txt"])


def test_clean_single_commit_with_expected_author_passes(
    audit_module: ModuleType, tmp_path: Path
) -> None:
    repo_root, base = initialize_repository(tmp_path)
    run_git(repo_root, "config", "remote.origin.url", "https://github.com/highlordleonas/csvql.git")
    commit_file(repo_root, "docs/development.md", "Candidate documentation.\n")

    run_audit(audit_module, repo_root, base)


def test_repository_identity_mismatch_is_rejected(audit_module: ModuleType, tmp_path: Path) -> None:
    repo_root, base = initialize_repository(tmp_path)
    commit_file(repo_root, "docs/development.md", "Development documentation.\n")

    with pytest.raises(audit_module.AuditError, match="repository identity"):
        audit_module.audit_public_release(
            repo=repo_root,
            expected_repository="example/repository",
            base=base,
            candidate="HEAD",
            expected_author_name=EXPECTED_AUTHOR_NAME,
            expected_author_email=EXPECTED_AUTHOR_EMAIL,
            require_clean_worktree=False,
            tree_only=False,
        )


def test_base_mismatch_is_rejected(audit_module: ModuleType, tmp_path: Path) -> None:
    repo_root, _base = initialize_repository(tmp_path)
    run_git(repo_root, "checkout", "-b", "other")
    other_base = commit_file(repo_root, "docs/development.md", "Other history.\n")
    run_git(repo_root, "checkout", "main")
    commit_file(repo_root, "docs/getting-started.md", "Candidate history.\n")

    with pytest.raises(audit_module.AuditError, match="declared base"):
        run_audit(audit_module, repo_root, other_base)


def test_zero_or_multiple_commits_above_base_are_rejected(
    audit_module: ModuleType, tmp_path: Path
) -> None:
    repo_root, base = initialize_repository(tmp_path)

    with pytest.raises(audit_module.AuditError, match="exactly one commit"):
        run_audit(audit_module, repo_root, base, candidate=base)

    commit_file(repo_root, "docs/development.md", "First candidate change.\n")
    commit_file(repo_root, "docs/getting-started.md", "Second candidate change.\n")

    with pytest.raises(audit_module.AuditError, match="exactly one commit"):
        run_audit(audit_module, repo_root, base)


def test_merge_commit_is_rejected_even_when_one_commit_is_above_base(
    audit_module: ModuleType, tmp_path: Path
) -> None:
    repo_root, base = initialize_repository(tmp_path)
    tree = run_git(repo_root, "write-tree")
    merge_commit = run_git(
        repo_root,
        "commit-tree",
        tree,
        "-p",
        base,
        "-p",
        f"{base}^",
        "-m",
        "Synthetic merge",
    )

    with pytest.raises(audit_module.AuditError, match="one parent"):
        run_audit(audit_module, repo_root, base, candidate=merge_commit)

    run_audit(audit_module, repo_root, None, candidate=merge_commit, tree_only=True)


def test_different_author_is_rejected(audit_module: ModuleType, tmp_path: Path) -> None:
    repo_root, base = initialize_repository(tmp_path)
    run_git(repo_root, "config", "user.name", "another-author")
    run_git(repo_root, "config", "user.email", "another-author@example.com")
    commit_file(repo_root, "docs/development.md", "Candidate documentation.\n")

    with pytest.raises(audit_module.AuditError, match="author identity"):
        run_audit(audit_module, repo_root, base)


def test_dirty_tracked_worktree_is_rejected(audit_module: ModuleType, tmp_path: Path) -> None:
    repo_root, base = initialize_repository(tmp_path)
    commit_file(repo_root, "docs/development.md", "Candidate documentation.\n")
    (repo_root / "README.md").write_text("Modified after commit.\n", encoding="utf-8")

    with pytest.raises(audit_module.AuditError, match="clean tracked worktree"):
        run_audit(audit_module, repo_root, base, require_clean_worktree=True)


def test_unexpected_tracked_path_is_rejected_without_echoing_its_name(
    audit_module: ModuleType, tmp_path: Path
) -> None:
    repo_root, base = initialize_repository(tmp_path)
    candidate_path = "unmatched/path.txt"
    commit_file(repo_root, candidate_path, "Not part of the public contract.\n")

    with pytest.raises(audit_module.AuditError, match="unclassified") as error:
        run_audit(audit_module, repo_root, base)

    assert candidate_path not in str(error.value)


def test_non_regular_public_entry_is_rejected(audit_module: ModuleType, tmp_path: Path) -> None:
    repo_root, base = initialize_repository(tmp_path)
    link_path = repo_root / "docs" / "development.md"
    link_path.symlink_to("../README.md")
    run_git(repo_root, "add", "docs/development.md")
    run_git(repo_root, "commit", "-m", "Add symbolic documentation link")

    with pytest.raises(audit_module.AuditError, match="regular files"):
        run_audit(audit_module, repo_root, base)
