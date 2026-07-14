from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import scripts.install_git_safety as install_git_safety  # noqa: E402

CANONICAL_REPOSITORY = "highlordleonas/csvql"
CANONICAL_FETCH_URL = "https://github.com/highlordleonas/csvql.git"


def isolated_git_environment(repo: Path) -> dict[str, str]:
    home = repo.parent / "home"
    xdg_config_home = repo.parent / "xdg"
    home.mkdir(exist_ok=True)
    xdg_config_home.mkdir(exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(xdg_config_home),
        }
    )
    return environment


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        text=True,
        capture_output=True,
        env=isolated_git_environment(repo),
    )


def run_installer(repo: Path, command: str, *extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.install_git_safety",
            command,
            "--repo",
            str(repo),
            *extra_args,
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
        env=isolated_git_environment(repo),
    )


def resolved_git_common_dir(repo: Path) -> Path:
    common_dir = Path(git(repo, "rev-parse", "--git-common-dir").stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo / common_dir
    return common_dir.resolve()


def read_exclude(repo: Path) -> str:
    return (resolved_git_common_dir(repo) / "info/exclude").read_text(encoding="utf-8")


def use_isolated_git_environment(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    for key, value in isolated_git_environment(repo).items():
        monkeypatch.setenv(key, value)


def commit_seed(repo: Path) -> None:
    git(repo, "config", "--local", "user.name", "LocalQL Test")
    git(repo, "config", "--local", "user.email", "localql@example.invalid")
    seed = repo / "seed.txt"
    seed.write_text("seed\n", encoding="utf-8")
    git(repo, "add", "seed.txt")
    git(repo, "commit", "-m", "seed")


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "clone"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "--local", "remote.origin.url", CANONICAL_FETCH_URL)
    return repo


def test_check_reports_uninstalled_maintainer_clone(git_repo: Path) -> None:
    result = run_installer(git_repo, "check")

    assert result.returncode == 1
    assert "origin fetch URL: canonical" in result.stdout
    assert "push.default: missing" in result.stdout
    assert "hook checksum: missing" in result.stdout


def test_apply_refuses_contributor_fork_origin(git_repo: Path) -> None:
    git(git_repo, "config", "remote.origin.url", "git@github.com:contributor/csvql.git")

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2
    assert "refusing to change a non-canonical origin" in result.stderr


@pytest.mark.parametrize(
    ("key", "value", "expected_label"),
    [
        (
            "remote.origin.push",
            "refs/heads/main:refs/heads/main",
            "remote push refspec configuration",
        ),
        ("remote.pushDefault", "origin", "remote push-default configuration"),
        (
            "branch.release/v1.0.2.pushRemote",
            "origin",
            "branch push-remote configuration",
        ),
        (
            "url.ssh://git@github.com/.pushInsteadOf",
            "https://github.com/",
            "url rewrite configuration",
        ),
        ("core.hooksPath", "/tmp/other-hooks", "core hooks-path configuration"),
    ],
)
def test_apply_stops_on_ambiguous_push_configuration_with_safe_labels(
    git_repo: Path, key: str, value: str, expected_label: str
) -> None:
    git(git_repo, "config", "--local", key, value)

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2
    assert expected_label.lower() in result.stderr.lower()


def test_apply_requires_exact_confirmation(git_repo: Path) -> None:
    result = run_installer(git_repo, "apply")

    assert result.returncode == 2
    assert "confirmation" in result.stderr.lower()


def test_apply_refuses_preexisting_origin_push_url(git_repo: Path) -> None:
    git(
        git_repo,
        "config",
        "--local",
        "remote.origin.pushurl",
        "https://github.com/highlordleonas/csvql.git",
    )

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2
    assert "origin push configuration" in result.stderr


def test_apply_refuses_another_canonical_write_remote(git_repo: Path) -> None:
    git(git_repo, "remote", "add", "backup", "git@github.com:highlordleonas/csvql.git")

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2
    assert "another remote" in result.stderr
    assert "backup" not in result.stderr


def test_apply_refuses_a_dotted_remote_that_can_write_to_canonical(
    git_repo: Path,
) -> None:
    git(
        git_repo,
        "remote",
        "add",
        "backup.release",
        "git@github.com:highlordleonas/csvql.git",
    )

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2
    assert "another remote" in result.stderr
    assert "backup.release" not in result.stderr


def test_apply_refuses_a_pushurl_only_remote_that_can_write_to_canonical(
    git_repo: Path,
) -> None:
    git(
        git_repo,
        "config",
        "--local",
        "remote.shadow.pushurl",
        "git@github.com:highlordleonas/csvql.git",
    )

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2
    assert "another remote" in result.stderr
    assert "shadow" not in result.stderr


def test_effective_included_remote_is_enumerated_without_printing_its_name(
    git_repo: Path,
) -> None:
    marker = "ARBITRARYALPHANUMERICREMOTE123"
    included_config = git_repo.parent / "included-remotes.config"
    included_config.write_text(
        f'[remote "{marker}"]\n\turl = {CANONICAL_FETCH_URL}\n',
        encoding="utf-8",
    )
    git(
        git_repo,
        "config",
        "--global",
        "include.path",
        str(included_config),
    )
    assert marker in git(git_repo, "remote").stdout.splitlines()

    check_result = run_installer(git_repo, "check")
    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)
    output = check_result.stdout + check_result.stderr + result.stdout + result.stderr

    assert check_result.returncode == 2
    assert "canonical write remotes: present" in check_result.stdout
    assert result.returncode == 2
    assert marker not in output
    assert "another remote" in result.stderr


def test_remote_enumeration_failure_is_fixed_and_redacted(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_isolated_git_environment(monkeypatch, git_repo)
    marker = "ARBITRARYALPHANUMERICREMOTE123"
    real_run_git = install_git_safety.run_git

    def failing_run_git(
        repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        if args == ("remote",):
            return subprocess.CompletedProcess([], 2, "", marker)
        return real_run_git(repo, *args, check=check)

    monkeypatch.setattr(install_git_safety, "run_git", failing_run_git)

    with pytest.raises(install_git_safety.InstallError) as captured:
        install_git_safety.inspect_repository(git_repo)

    assert "enumerate effective Git remotes" in str(captured.value)
    assert marker not in str(captured.value)


def test_remote_resolution_failure_is_fixed_and_redacted(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_isolated_git_environment(monkeypatch, git_repo)
    marker = "ARBITRARYALPHANUMERICREMOTE123"
    git(git_repo, "remote", "add", marker, "https://example.invalid/repository.git")
    real_run_git = install_git_safety.run_git

    def failing_run_git(
        repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        if args == ("remote", "get-url", "--push", "--all", marker):
            return subprocess.CompletedProcess([], 2, "", marker)
        return real_run_git(repo, *args, check=check)

    monkeypatch.setattr(install_git_safety, "run_git", failing_run_git)

    inspection = install_git_safety.inspect_repository(git_repo)
    categories = install_git_safety._conflict_categories(inspection.conflicts)

    assert "effective remote push destination" in categories
    assert marker not in ", ".join(categories)


def test_origin_resolution_failure_is_fixed_and_redacted(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_isolated_git_environment(monkeypatch, git_repo)
    marker = "ARBITRARYALPHANUMERICORIGIN123"
    real_run_git = install_git_safety.run_git

    def failing_run_git(
        repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        if args == ("remote", "get-url", "--push", "--all", "origin"):
            return subprocess.CompletedProcess([], 2, "", marker)
        return real_run_git(repo, *args, check=check)

    monkeypatch.setattr(install_git_safety, "run_git", failing_run_git)

    inspection = install_git_safety.inspect_repository(git_repo)
    categories = install_git_safety._conflict_categories(inspection.conflicts)

    assert "effective origin push destination" in categories
    assert marker not in ", ".join(categories)


def test_installer_uses_exact_direct_guard_import() -> None:
    source = (REPO_ROOT / "scripts/install_git_safety.py").read_text(encoding="utf-8")

    assert "from scripts.git_public_push_guard import normalize_public_repository" in source
    assert "importlib" not in source


def test_local_instead_of_cannot_rewrite_inert_origin_to_public(
    git_repo: Path,
) -> None:
    assert run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY).returncode == 0
    inert_url = (resolved_git_common_dir(git_repo) / "localql-public-push-disabled").as_uri()
    git(
        git_repo,
        "config",
        "--local",
        f"url.{CANONICAL_FETCH_URL}.insteadOf",
        inert_url,
    )
    effective_url = git(git_repo, "remote", "get-url", "--push", "origin").stdout.strip()
    assert effective_url == CANONICAL_FETCH_URL

    check_result = run_installer(git_repo, "check")
    apply_result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert check_result.returncode == 2
    assert apply_result.returncode == 2


def test_local_instead_of_cannot_rewrite_dotted_remote_to_public(
    git_repo: Path,
) -> None:
    benign_url = (git_repo.parent / "benign-remote").as_uri()
    git(git_repo, "remote", "add", "backup.release", benign_url)
    git(
        git_repo,
        "config",
        "--local",
        f"url.{CANONICAL_FETCH_URL}.insteadOf",
        benign_url,
    )
    effective_url = git(git_repo, "remote", "get-url", "--push", "backup.release").stdout.strip()
    assert effective_url == CANONICAL_FETCH_URL

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2


def test_isolated_global_rewrite_is_detected_without_global_mutation(
    git_repo: Path,
) -> None:
    assert run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY).returncode == 0
    inert_url = (resolved_git_common_dir(git_repo) / "localql-public-push-disabled").as_uri()
    git(
        git_repo,
        "config",
        "--global",
        f"url.{CANONICAL_FETCH_URL}.insteadOf",
        inert_url,
    )
    global_config = Path(isolated_git_environment(git_repo)["GIT_CONFIG_GLOBAL"])
    original = global_config.read_bytes()
    assert git(git_repo, "remote", "get-url", "--push", "origin").stdout.strip() == (
        CANONICAL_FETCH_URL
    )

    result = run_installer(git_repo, "check")

    assert result.returncode == 2
    assert global_config.read_bytes() == original


def test_apply_requires_the_exact_case_sensitive_origin_remote(git_repo: Path) -> None:
    git(git_repo, "config", "--local", "--unset-all", "remote.origin.url")
    git(git_repo, "config", "--local", "remote.Origin.url", CANONICAL_FETCH_URL)

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2
    assert "non-canonical origin" in result.stderr


def test_apply_refuses_non_sample_default_pre_push_hook(git_repo: Path) -> None:
    hook = resolved_git_common_dir(git_repo) / "hooks/pre-push"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2
    assert "pre-push hook" in result.stderr


def test_apply_refuses_occupied_inert_target(git_repo: Path) -> None:
    inert_target = resolved_git_common_dir(git_repo) / "localql-public-push-disabled"
    inert_target.write_text("occupied\n", encoding="utf-8")

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2
    assert "inert push target" in result.stderr


def test_apply_refuses_broken_symlink_at_inert_target(git_repo: Path) -> None:
    inert_target = resolved_git_common_dir(git_repo) / "localql-public-push-disabled"
    inert_target.symlink_to(git_repo / "missing-target")

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2
    assert "inert push target" in result.stderr


def test_apply_refuses_symlinked_installed_hook_directory(git_repo: Path) -> None:
    external_directory = git_repo.parent / "external-hooks"
    external_directory.mkdir()
    installed_hook_dir = resolved_git_common_dir(git_repo) / "localql-hooks"
    installed_hook_dir.symlink_to(external_directory, target_is_directory=True)

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2
    assert "installed hook directory" in result.stderr
    assert list(external_directory.iterdir()) == []


def test_apply_does_not_print_hostile_configuration_values(git_repo: Path) -> None:
    secret = "https://credential-value@example.invalid/hooks"
    git(git_repo, "config", "--local", "core.hooksPath", secret)

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2
    assert secret not in result.stdout
    assert secret not in result.stderr


@pytest.mark.parametrize("config_kind", ["branch", "remote"])
def test_output_redacts_hostile_config_and_remote_identifiers(
    git_repo: Path, config_kind: str
) -> None:
    marker = "CREDENTIAL_MARKER_SHOULD_NOT_APPEAR"
    hostile_identifier = f"{marker}@\x1b[31m"
    if config_kind == "branch":
        git(
            git_repo,
            "config",
            "--local",
            f"branch.{hostile_identifier}.pushRemote",
            "origin",
        )
    else:
        git(
            git_repo,
            "config",
            "--local",
            f"remote.{hostile_identifier}.url",
            CANONICAL_FETCH_URL,
        )

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)
    output = result.stdout + result.stderr

    assert result.returncode == 2
    assert marker not in output
    assert "\x1b" not in output


def test_output_redacts_credential_shaped_url_rewrite_identifier(
    git_repo: Path,
) -> None:
    marker = "CREDENTIAL_MARKER_SHOULD_NOT_APPEAR"
    git(
        git_repo,
        "config",
        "--local",
        f"url.https://{marker}@example.invalid/.insteadOf",
        "https://example.invalid/",
    )

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)
    output = result.stdout + result.stderr

    assert result.returncode == 2
    assert marker not in output


def test_output_never_prints_arbitrary_alphanumeric_identifiers(git_repo: Path) -> None:
    marker = "ARBITRARYALPHANUMERICBRANCH123"
    git(
        git_repo,
        "config",
        "--local",
        f"branch.{marker}.pushRemote",
        "origin",
    )

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)
    output = result.stdout + result.stderr

    assert result.returncode == 2
    assert marker not in output
    assert "branch push-remote configuration" in result.stderr


def test_git_query_failure_does_not_echo_a_hostile_configuration_value(
    git_repo: Path,
) -> None:
    secret = "credential-value-that-must-not-appear"
    git(git_repo, "config", "--local", "push.default", secret)

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 2
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_apply_installs_branch_independent_guardrails(git_repo: Path) -> None:
    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 0, result.stderr
    git_common_dir = resolved_git_common_dir(git_repo)
    installed = git_common_dir / "localql-hooks"
    assert stat.S_IMODE((installed / "pre-push").lstat().st_mode) == 0o755
    assert (installed / "git_public_push_guard.py").is_file()
    assert stat.S_IMODE((installed / "git_public_push_guard.py").lstat().st_mode) == 0o644
    assert (installed / "SHA256SUMS").is_file()
    assert stat.S_IMODE((installed / "SHA256SUMS").lstat().st_mode) == 0o600
    assert git(git_repo, "config", "--local", "--get", "core.hooksPath").stdout.strip() == str(
        installed
    )
    assert git(git_repo, "config", "--local", "--get", "push.default").stdout.strip() == "nothing"
    push_url = git(git_repo, "config", "--local", "--get", "remote.origin.pushurl").stdout.strip()
    assert push_url == (git_common_dir / "localql-public-push-disabled").as_uri()
    assert read_exclude(git_repo).splitlines().count("docs/superpowers/") == 1


def test_apply_writes_exact_source_checksums(git_repo: Path) -> None:
    assert run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY).returncode == 0
    installed = resolved_git_common_dir(git_repo) / "localql-hooks"
    expected = "".join(
        f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {source.name}\n"
        for source in (
            REPO_ROOT / ".githooks/pre-push",
            REPO_ROOT / "scripts/git_public_push_guard.py",
        )
    )

    assert (installed / "SHA256SUMS").read_text(encoding="utf-8") == expected


def test_apply_is_idempotent_and_check_detects_tampering(git_repo: Path) -> None:
    assert run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY).returncode == 0
    assert run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY).returncode == 0
    installed_guard = resolved_git_common_dir(git_repo) / "localql-hooks/git_public_push_guard.py"
    installed_guard.write_text("tampered\n", encoding="utf-8")

    result = run_installer(git_repo, "check")

    assert result.returncode == 1
    assert "hook checksum: mismatch" in result.stdout


def test_check_detects_a_nonexecutable_installed_hook(git_repo: Path) -> None:
    assert run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY).returncode == 0
    installed_hook = resolved_git_common_dir(git_repo) / "localql-hooks/pre-push"
    installed_hook.chmod(0o644)

    result = run_installer(git_repo, "check")

    assert result.returncode == 2
    assert "hook checksum: mismatch" in result.stdout


@pytest.mark.parametrize(
    ("payload_name", "expected_mode"),
    [
        ("pre-push", 0o755),
        ("git_public_push_guard.py", 0o644),
        ("SHA256SUMS", 0o600),
    ],
)
def test_check_and_apply_refuse_symlinked_installed_payloads(
    git_repo: Path, payload_name: str, expected_mode: int
) -> None:
    assert run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY).returncode == 0
    payload = resolved_git_common_dir(git_repo) / "localql-hooks" / payload_name
    external = git_repo.parent / f"external-{payload_name}"
    external.write_bytes(payload.read_bytes())
    external.chmod(expected_mode)
    payload.unlink()
    payload.symlink_to(external)

    check_result = run_installer(git_repo, "check")
    apply_result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert check_result.returncode == 2
    assert apply_result.returncode == 2


@pytest.mark.parametrize(
    ("payload_name", "wrong_mode"),
    [
        ("pre-push", 0o644),
        ("git_public_push_guard.py", 0o600),
        ("SHA256SUMS", 0o644),
    ],
)
def test_check_and_apply_refuse_incorrect_installed_payload_modes(
    git_repo: Path, payload_name: str, wrong_mode: int
) -> None:
    assert run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY).returncode == 0
    payload = resolved_git_common_dir(git_repo) / "localql-hooks" / payload_name
    payload.chmod(wrong_mode)

    check_result = run_installer(git_repo, "check")
    apply_result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert check_result.returncode == 2
    assert apply_result.returncode == 2


def test_apply_preserves_unrelated_exclusions(git_repo: Path) -> None:
    exclude_path = resolved_git_common_dir(git_repo) / "info/exclude"
    original = "# local exclusions\nprivate-notes/\n"
    exclude_path.write_text(original, encoding="utf-8")

    assert run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY).returncode == 0

    assert read_exclude(git_repo) == original + "docs/superpowers/\n"


def test_apply_atomically_replaces_payloads_and_exclusion(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_isolated_git_environment(monkeypatch, git_repo)
    real_replace = install_git_safety.os.replace
    replaced_destinations: list[Path] = []

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        replaced_destinations.append(Path(destination).resolve())
        real_replace(source, destination)

    monkeypatch.setattr(install_git_safety.os, "replace", recording_replace)

    install_git_safety.apply_repository(git_repo, CANONICAL_REPOSITORY)

    common_dir = resolved_git_common_dir(git_repo)
    installed = common_dir / "localql-hooks"
    assert {
        (installed / "pre-push").resolve(),
        (installed / "git_public_push_guard.py").resolve(),
        (installed / "SHA256SUMS").resolve(),
        (common_dir / "info/exclude").resolve(),
    }.issubset(set(replaced_destinations))


def test_apply_leaves_isolated_global_config_byte_for_byte_unchanged(
    git_repo: Path,
) -> None:
    global_config = Path(isolated_git_environment(git_repo)["GIT_CONFIG_GLOBAL"])
    original = b"[user]\n\tname = Isolated User\n[credential]\n\thelper = disabled\n"
    global_config.write_bytes(original)

    result = run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 0, result.stderr
    assert global_config.read_bytes() == original


def test_apply_rolls_back_local_config_and_exclusion_after_mid_apply_failure(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_isolated_git_environment(monkeypatch, git_repo)
    git(git_repo, "config", "--local", "push.default", "simple")
    exclude_path = resolved_git_common_dir(git_repo) / "info/exclude"
    original_exclude = exclude_path.read_bytes()
    real_run_git = install_git_safety.run_git

    def failing_run_git(
        repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        if args[:3] == ("config", "--local", "core.hooksPath"):
            raise subprocess.CalledProcessError(1, ["git", *args])
        return real_run_git(repo, *args, check=check)

    monkeypatch.setattr(install_git_safety, "run_git", failing_run_git)

    with pytest.raises(
        install_git_safety.InstallError,
        match="installation failed; local configuration was restored",
    ):
        install_git_safety.apply_repository(git_repo, CANONICAL_REPOSITORY)

    assert git(git_repo, "config", "--local", "--get", "push.default").stdout.strip() == "simple"
    assert (
        git(
            git_repo,
            "config",
            "--local",
            "--get",
            "core.hooksPath",
            check=False,
        ).returncode
        == 1
    )
    assert (
        git(
            git_repo,
            "config",
            "--local",
            "--get",
            "remote.origin.pushurl",
            check=False,
        ).returncode
        == 1
    )
    assert exclude_path.read_bytes() == original_exclude


@pytest.mark.parametrize("preexisting_payloads", [False, True])
def test_apply_rolls_back_managed_hook_payloads_after_mid_apply_failure(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, preexisting_payloads: bool
) -> None:
    use_isolated_git_environment(monkeypatch, git_repo)
    installed = resolved_git_common_dir(git_repo) / "localql-hooks"
    original_files: dict[str, tuple[bytes, int]] = {}
    if preexisting_payloads:
        installed.mkdir()
        (installed / "keep-me").write_bytes(b"unrelated\n")
        for name, mode in install_git_safety.INSTALLED_PAYLOAD_MODES.items():
            path = installed / name
            path.write_bytes(f"preexisting {name}\n".encode())
            path.chmod(mode)
            original_files[name] = (path.read_bytes(), mode)

    real_run_git = install_git_safety.run_git

    def failing_run_git(
        repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        if args == ("config", "--local", "push.default", "nothing"):
            raise subprocess.CalledProcessError(1, ["git", *args])
        return real_run_git(repo, *args, check=check)

    monkeypatch.setattr(install_git_safety, "run_git", failing_run_git)

    with pytest.raises(
        install_git_safety.InstallError,
        match="installation failed; local configuration was restored",
    ):
        install_git_safety.apply_repository(git_repo, install_git_safety.CANONICAL_REPOSITORY)

    if preexisting_payloads:
        assert installed.is_dir()
        assert (installed / "keep-me").read_bytes() == b"unrelated\n"
        for name, (content, mode) in original_files.items():
            path = installed / name
            assert path.read_bytes() == content
            assert stat.S_IMODE(path.lstat().st_mode) == mode
    else:
        assert not installed.exists()


def test_apply_reports_incomplete_rollback_without_configuration_values(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_isolated_git_environment(monkeypatch, git_repo)
    prior_value = "upstream"
    git(git_repo, "config", "--local", "push.default", prior_value)
    real_run_git = install_git_safety.run_git

    def failing_run_git(
        repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        if args[:3] == ("config", "--local", "core.hooksPath"):
            raise subprocess.CalledProcessError(1, ["git", *args])
        if args == ("config", "--local", "--unset-all", "push.default"):
            return subprocess.CompletedProcess([], 2, "", "")
        return real_run_git(repo, *args, check=check)

    monkeypatch.setattr(install_git_safety, "run_git", failing_run_git)

    with pytest.raises(install_git_safety.InstallError) as captured:
        install_git_safety.apply_repository(git_repo, CANONICAL_REPOSITORY)

    message = str(captured.value)
    assert "rollback was incomplete" in message
    assert "push.default" in message
    assert "core.hooksPath" in message
    assert "remote.origin.pushurl" in message
    assert prior_value not in message


def test_installed_hook_survives_local_branch_switch(git_repo: Path) -> None:
    commit_seed(git_repo)
    assert run_installer(git_repo, "apply", "--confirm", CANONICAL_REPOSITORY).returncode == 0
    installed_hook = resolved_git_common_dir(git_repo) / "localql-hooks/pre-push"
    original_contents = installed_hook.read_bytes()

    git(git_repo, "switch", "-c", "other-local-branch")

    assert installed_hook.read_bytes() == original_contents
    assert run_installer(git_repo, "check").returncode == 0


def test_installation_uses_shared_common_directory_for_linked_worktree(
    git_repo: Path,
) -> None:
    commit_seed(git_repo)
    linked_worktree = git_repo.parent / "linked"
    git(git_repo, "worktree", "add", "-b", "linked-branch", str(linked_worktree))

    result = run_installer(linked_worktree, "apply", "--confirm", CANONICAL_REPOSITORY)

    assert result.returncode == 0, result.stderr
    assert resolved_git_common_dir(linked_worktree) == resolved_git_common_dir(git_repo)
    assert run_installer(linked_worktree, "check").returncode == 0
    assert run_installer(git_repo, "check").returncode == 0
