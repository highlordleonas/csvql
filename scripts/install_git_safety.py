from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts.git_public_push_guard import normalize_public_repository

CANONICAL_REPOSITORY = "highlordleonas/csvql"
CANONICAL_FETCH_URL = "https://github.com/highlordleonas/csvql.git"
HOOK_DIRECTORY_NAME = "localql-hooks"
PLANNING_EXCLUSION = "docs/superpowers/"
SOURCE_ROOT = Path(__file__).resolve().parents[1]
CONFLICTING_CONFIG_RE = (
    r"^(remote\..*\.push|remote\.pushDefault|branch\..*\.pushRemote|"
    r"url\..*\.(?:pushInsteadOf|insteadOf)|core\.hooksPath)$"
)
INSTALLED_PAYLOAD_MODES = {
    "pre-push": 0o755,
    "git_public_push_guard.py": 0o644,
    "SHA256SUMS": 0o600,
}


class InstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class Inspection:
    repository_root: Path
    git_common_dir: Path
    origin_fetch_url: str
    inert_push_url: str
    configured_push_url: str | None
    hooks_path: str | None
    push_default: str | None
    hook_checksums_valid: bool
    planning_excluded: bool
    conflicts: tuple[str, ...]
    canonical_write_remotes: tuple[str, ...]


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        text=True,
        capture_output=True,
    )


def git_value(repo: Path, *args: str) -> str | None:
    result = run_git(repo, *args, check=False)
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise InstallError("git configuration query failed")
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_copy(source: Path, destination: Path, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}."
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        temporary.chmod(mode)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def append_exclusion_atomically(exclude_path: Path) -> None:
    existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    lines = existing.splitlines()
    if PLANNING_EXCLUSION not in lines:
        lines.append(PLANNING_EXCLUSION)
    content = "\n".join(lines) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(dir=exclude_path.parent, prefix=".exclude.")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, exclude_path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def restore_file(path: Path, existed: bool, content: bytes) -> None:
    if existed:
        atomic_write_bytes(path, content)
    else:
        path.unlink(missing_ok=True)


def local_values(repo: Path, key: str) -> tuple[str, ...]:
    result = run_git(repo, "config", "--local", "--null", "--get-all", key, check=False)
    if result.returncode == 1:
        return ()
    if result.returncode != 0:
        raise InstallError(f"could not snapshot local key {key}")
    return tuple(value for value in result.stdout.split("\0") if value)


def restore_local_values(repo: Path, key: str, values: tuple[str, ...]) -> None:
    removal = run_git(repo, "config", "--local", "--unset-all", key, check=False)
    if removal.returncode not in (0, 1, 5):
        raise InstallError(f"could not clear local key {key} during rollback")
    for value in values:
        run_git(repo, "config", "--local", "--add", key, value)


def _repository_paths(repo: Path) -> tuple[Path, Path]:
    repository_value = git_value(repo, "rev-parse", "--show-toplevel")
    if repository_value is None:
        raise InstallError("repository path is not a Git worktree")
    repository_root = Path(repository_value).resolve()
    common_value = git_value(repository_root, "rev-parse", "--git-common-dir")
    if common_value is None:
        raise InstallError("could not resolve Git common directory")
    common_path = Path(common_value)
    if not common_path.is_absolute():
        common_path = repository_root / common_path
    return repository_root, common_path.resolve()


def _local_config(repo: Path) -> dict[str, tuple[str, ...]]:
    result = run_git(repo, "config", "--local", "--null", "--list", check=False)
    if result.returncode != 0:
        raise InstallError("could not inspect local Git configuration")
    values: dict[str, list[str]] = {}
    for record in result.stdout.split("\0"):
        if not record:
            continue
        key, separator, value = record.partition("\n")
        if not separator:
            raise InstallError("local Git configuration has an invalid record")
        values.setdefault(key, []).append(value)
    return {key: tuple(entries) for key, entries in values.items()}


def _config_values(config: dict[str, tuple[str, ...]], key: str) -> tuple[str, ...]:
    normalized_key = key.lower()
    return tuple(
        value
        for configured_key, values in config.items()
        if configured_key.lower() == normalized_key
        for value in values
    )


def _conflict_category(key: str) -> str:
    lowered = key.lower()
    if re.fullmatch(r"remote\..*\.push", lowered):
        return "remote push refspec configuration"
    if lowered == "remote.pushdefault":
        return "remote push-default configuration"
    if re.fullmatch(r"branch\..*\.pushremote", lowered):
        return "branch push-remote configuration"
    if re.fullmatch(r"url\..*\.(?:pushinsteadof|insteadof)", lowered):
        return "url rewrite configuration"
    categories = {
        "core.hookspath": "core hooks-path configuration",
        "default pre-push hook": "default pre-push hook",
        "effective origin push destination": "effective origin push destination",
        "effective remote push destination": "effective remote push destination",
        "installed hook directory": "installed hook directory",
        "installed hook payload": "installed hook payload",
        "push.default": "push-default configuration",
        "remote.origin.pushurl": "origin push configuration",
        "remote.origin.url": "origin fetch configuration",
    }
    return categories.get(lowered, "local Git configuration conflict")


def _conflict_categories(conflicts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({_conflict_category(conflict) for conflict in conflicts}))


def _remote_key_parts(key: str) -> tuple[str, str] | None:
    if not key.lower().startswith("remote."):
        return None
    subsection_and_name = key[len("remote.") :]
    remote_name, separator, variable_name = subsection_and_name.rpartition(".")
    if not separator or not remote_name:
        return None
    return remote_name, variable_name.lower()


def _remote_values(
    config: dict[str, tuple[str, ...]], remote_name: str, variable_name: str
) -> tuple[str, ...]:
    return tuple(
        value
        for key, values in config.items()
        if _remote_key_parts(key) == (remote_name, variable_name.lower())
        for value in values
    )


def _active_default_hook(git_common_dir: Path) -> bool:
    hook_path = git_common_dir / "hooks/pre-push"
    return hook_path.is_file() and os.access(hook_path, os.X_OK)


def _path_occupied(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _installed_payload_shape_unsafe(installed_hook_dir: Path) -> bool:
    for name, expected_mode in INSTALLED_PAYLOAD_MODES.items():
        payload = installed_hook_dir / name
        if not _path_occupied(payload):
            continue
        try:
            metadata = payload.lstat()
        except OSError:
            return True
        if not stat.S_ISREG(metadata.st_mode):
            return True
        if stat.S_IMODE(metadata.st_mode) != expected_mode:
            return True
    return False


def _installed_payload_status(installed_hook_dir: Path) -> str:
    if installed_hook_dir.is_symlink() or (
        installed_hook_dir.exists() and not installed_hook_dir.is_dir()
    ):
        return "mismatch"
    if _installed_payload_shape_unsafe(installed_hook_dir):
        return "mismatch"
    sources = {
        "pre-push": SOURCE_ROOT / ".githooks/pre-push",
        "git_public_push_guard.py": SOURCE_ROOT / "scripts/git_public_push_guard.py",
    }
    manifest = installed_hook_dir / "SHA256SUMS"
    installed = {name: installed_hook_dir / name for name in sources}
    if not _path_occupied(manifest) or any(not _path_occupied(path) for path in installed.values()):
        return "missing"
    try:
        expected_manifest = "".join(
            f"{sha256(source)}  {name}\n" for name, source in sources.items()
        ).encode()
        if manifest.read_bytes() != expected_manifest:
            return "mismatch"
        if any(sha256(installed[name]) != sha256(source) for name, source in sources.items()):
            return "mismatch"
    except OSError:
        return "mismatch"
    return "valid"


def _effective_remote_names(repo: Path) -> tuple[str, ...]:
    result = run_git(repo, "remote", check=False)
    if result.returncode != 0:
        raise InstallError("could not enumerate effective Git remotes")
    return tuple(name for name in result.stdout.splitlines() if name)


def _effective_push_urls(repo: Path, remote_name: str) -> tuple[str, ...] | None:
    result = run_git(
        repo,
        "remote",
        "get-url",
        "--push",
        "--all",
        remote_name,
        check=False,
    )
    if result.returncode != 0:
        return None
    urls = tuple(result.stdout.splitlines())
    return urls or None


def _configured_push_urls(repo: Path, remote_name: str) -> tuple[str, ...] | None:
    for variable_name in ("pushurl", "url"):
        result = run_git(
            repo,
            "config",
            "--get-all",
            f"remote.{remote_name}.{variable_name}",
            check=False,
        )
        if result.returncode == 0:
            urls = tuple(result.stdout.splitlines())
            return urls or None
        if result.returncode != 1:
            return None
    return None


def _canonical_write_remotes(
    repo: Path, remote_names: tuple[str, ...]
) -> tuple[tuple[str, ...], bool]:
    canonical: list[str] = []
    resolution_failed = False
    for remote_name in remote_names:
        if remote_name == "origin":
            continue
        effective_urls = _effective_push_urls(repo, remote_name)
        if effective_urls is None:
            resolution_failed = True
            configured_urls = _configured_push_urls(repo, remote_name)
            if configured_urls is not None and any(
                normalize_public_repository(url) == CANONICAL_REPOSITORY for url in configured_urls
            ):
                canonical.append(remote_name)
            continue
        if any(normalize_public_repository(url) == CANONICAL_REPOSITORY for url in effective_urls):
            canonical.append(remote_name)
    return tuple(canonical), resolution_failed


def inspect_repository(repo: Path) -> Inspection:
    repository_root, git_common_dir = _repository_paths(repo)
    config = _local_config(repository_root)
    installed_hook_dir = git_common_dir / HOOK_DIRECTORY_NAME
    inert_target = git_common_dir / "localql-public-push-disabled"
    inert_push_url = inert_target.as_uri()

    origin_values = _remote_values(config, "origin", "url")
    origin_fetch_url = origin_values[0] if len(origin_values) == 1 else ""
    push_url_values = _remote_values(config, "origin", "pushurl")
    configured_push_url = push_url_values[0] if len(push_url_values) == 1 else None
    hooks_values = _config_values(config, "core.hooksPath")
    hooks_path = hooks_values[0] if len(hooks_values) == 1 else None
    push_default_values = _config_values(config, "push.default")
    push_default = push_default_values[0] if len(push_default_values) == 1 else None
    effective_origin_push_urls = _effective_push_urls(repository_root, "origin")
    remote_names = _effective_remote_names(repository_root)
    canonical_write_remotes, remote_resolution_failed = _canonical_write_remotes(
        repository_root, remote_names
    )

    conflict_pattern = re.compile(CONFLICTING_CONFIG_RE, flags=re.IGNORECASE)
    conflicts: set[str] = set()
    for key in config:
        if not conflict_pattern.fullmatch(key):
            continue
        if key.lower() == "core.hookspath" and hooks_path == str(installed_hook_dir):
            continue
        conflicts.add(key)
    if len(origin_values) != 1:
        conflicts.add("remote.origin.url")
    if len(push_url_values) > 1:
        conflicts.add("remote.origin.pushurl")
    if len(hooks_values) > 1:
        conflicts.add("core.hooksPath")
    if len(push_default_values) > 1:
        conflicts.add("push.default")
    if _active_default_hook(git_common_dir):
        conflicts.add("default pre-push hook")
    if remote_resolution_failed:
        conflicts.add("effective remote push destination")
    if effective_origin_push_urls is None or (
        configured_push_url == inert_push_url and effective_origin_push_urls != (inert_push_url,)
    ):
        conflicts.add("effective origin push destination")
    unsafe_hook_directory = installed_hook_dir.is_symlink() or (
        installed_hook_dir.exists() and not installed_hook_dir.is_dir()
    )
    if unsafe_hook_directory:
        conflicts.add("installed hook directory")
    unsafe_payload_shape = _installed_payload_shape_unsafe(installed_hook_dir)
    if unsafe_payload_shape:
        conflicts.add("installed hook payload")

    exclude_path = git_common_dir / "info/exclude"
    try:
        exclude_lines = (
            exclude_path.read_text(encoding="utf-8").splitlines() if exclude_path.exists() else []
        )
    except OSError as error:
        raise InstallError("could not inspect local Git exclusion file") from error

    return Inspection(
        repository_root=repository_root,
        git_common_dir=git_common_dir,
        origin_fetch_url=origin_fetch_url,
        inert_push_url=inert_push_url,
        configured_push_url=configured_push_url,
        hooks_path=hooks_path,
        push_default=push_default,
        hook_checksums_valid=(
            not unsafe_hook_directory
            and not unsafe_payload_shape
            and _installed_payload_status(installed_hook_dir) == "valid"
        ),
        planning_excluded=PLANNING_EXCLUSION in exclude_lines,
        conflicts=tuple(sorted(conflicts, key=str.lower)),
        canonical_write_remotes=canonical_write_remotes,
    )


def _payload_status(inspection: Inspection) -> str:
    return _installed_payload_status(inspection.git_common_dir / HOOK_DIRECTORY_NAME)


def _inspection_is_unsafe(inspection: Inspection) -> bool:
    inert_target = inspection.git_common_dir / "localql-public-push-disabled"
    return bool(
        inspection.origin_fetch_url != CANONICAL_FETCH_URL
        or inspection.conflicts
        or inspection.canonical_write_remotes
        or _path_occupied(inert_target)
        or (
            inspection.configured_push_url is not None
            and inspection.configured_push_url != inspection.inert_push_url
        )
    )


def _inspection_is_complete(inspection: Inspection) -> bool:
    installed_hook_dir = inspection.git_common_dir / HOOK_DIRECTORY_NAME
    return bool(
        not _inspection_is_unsafe(inspection)
        and inspection.configured_push_url == inspection.inert_push_url
        and inspection.hooks_path == str(installed_hook_dir)
        and inspection.push_default == "nothing"
        and inspection.hook_checksums_valid
        and inspection.planning_excluded
    )


def _print_inspection(inspection: Inspection) -> None:
    installed_hook_dir = inspection.git_common_dir / HOOK_DIRECTORY_NAME
    inert_target = inspection.git_common_dir / "localql-public-push-disabled"
    origin_status = (
        "canonical"
        if inspection.origin_fetch_url == CANONICAL_FETCH_URL
        else ("missing" if not inspection.origin_fetch_url else "non-canonical")
    )
    push_url_status = (
        "inert"
        if inspection.configured_push_url == inspection.inert_push_url
        else ("missing" if inspection.configured_push_url is None else "unexpected")
    )
    hooks_status = (
        "installed"
        if inspection.hooks_path == str(installed_hook_dir)
        else ("missing" if inspection.hooks_path is None else "conflicting")
    )
    push_default_status = (
        "nothing"
        if inspection.push_default == "nothing"
        else ("missing" if inspection.push_default is None else "unexpected")
    )
    print(f"repository root: {inspection.repository_root}")
    print(f"Git common directory: {inspection.git_common_dir}")
    print(f"origin fetch URL: {origin_status}")
    print(f"inert push target: {'occupied' if _path_occupied(inert_target) else 'clear'}")
    print(f"origin push URL: {push_url_status}")
    print(f"core.hooksPath: {hooks_status}")
    print(f"push.default: {push_default_status}")
    print(f"hook checksum: {_payload_status(inspection)}")
    print(f"planning exclusion: {'present' if inspection.planning_excluded else 'missing'}")
    conflict_categories = _conflict_categories(inspection.conflicts)
    print(f"conflicts: {', '.join(conflict_categories) if conflict_categories else 'none'}")
    print(
        "canonical write remotes: " + ("present" if inspection.canonical_write_remotes else "none")
    )


def apply_repository(repo: Path, confirmation: str) -> Inspection:
    if confirmation != CANONICAL_REPOSITORY:
        raise InstallError(f"confirmation must be exactly {CANONICAL_REPOSITORY}")
    inspection = inspect_repository(repo)
    if inspection.origin_fetch_url != CANONICAL_FETCH_URL:
        raise InstallError("refusing to change a non-canonical origin")
    if inspection.canonical_write_remotes:
        raise InstallError("another remote can write to the canonical repository")
    if inspection.conflicts:
        conflict_categories = _conflict_categories(inspection.conflicts)
        raise InstallError("conflicting local Git configuration: " + ", ".join(conflict_categories))
    if (
        inspection.configured_push_url is not None
        and inspection.configured_push_url != inspection.inert_push_url
    ):
        raise InstallError("origin push configuration is already present")
    if _path_occupied(inspection.git_common_dir / "localql-public-push-disabled"):
        raise InstallError("inert push target path already exists")

    installed_hook_dir = inspection.git_common_dir / HOOK_DIRECTORY_NAME
    exclude_path = inspection.git_common_dir / "info/exclude"
    managed_keys = (
        "push.default",
        "core.hooksPath",
        "remote.origin.pushurl",
    )
    snapshots = {key: local_values(inspection.repository_root, key) for key in managed_keys}
    exclude_existed = exclude_path.exists()
    try:
        exclude_content = exclude_path.read_bytes() if exclude_existed else b""
    except OSError as error:
        raise InstallError("could not snapshot local Git exclusion file") from error

    source_hook = SOURCE_ROOT / ".githooks/pre-push"
    source_guard = SOURCE_ROOT / "scripts/git_public_push_guard.py"
    manifest = (
        f"{sha256(source_hook)}  pre-push\n{sha256(source_guard)}  git_public_push_guard.py\n"
    ).encode()

    try:
        atomic_copy(source_hook, installed_hook_dir / "pre-push", 0o755)
        atomic_copy(
            source_guard,
            installed_hook_dir / "git_public_push_guard.py",
            0o644,
        )
        atomic_write_bytes(installed_hook_dir / "SHA256SUMS", manifest)
        run_git(inspection.repository_root, "config", "--local", "push.default", "nothing")
        run_git(
            inspection.repository_root,
            "config",
            "--local",
            "core.hooksPath",
            str(installed_hook_dir),
        )
        run_git(
            inspection.repository_root,
            "config",
            "--local",
            "--replace-all",
            "remote.origin.pushurl",
            inspection.inert_push_url,
        )
        append_exclusion_atomically(exclude_path)
        installed = inspect_repository(inspection.repository_root)
        if not _inspection_is_complete(installed):
            raise InstallError("post-install verification failed")
        return installed
    except (InstallError, OSError, subprocess.SubprocessError):
        rollback_failed = False
        for key in managed_keys:
            try:
                restore_local_values(inspection.repository_root, key, snapshots[key])
            except (InstallError, OSError, subprocess.SubprocessError):
                rollback_failed = True
        try:
            restore_file(exclude_path, exclude_existed, exclude_content)
        except OSError:
            rollback_failed = True
        if rollback_failed:
            affected = ", ".join(managed_keys)
            raise InstallError(
                "installation failed and rollback was incomplete; inspect local Git config "
                f"before continuing; affected keys: {affected}"
            ) from None
        raise InstallError("installation failed; local configuration was restored") from None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="install_git_safety")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("--repo", type=Path, default=Path("."))
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--repo", type=Path, default=Path("."))
    apply_parser.add_argument("--confirm", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        if arguments.command == "check":
            inspection = inspect_repository(arguments.repo)
            _print_inspection(inspection)
            if _inspection_is_unsafe(inspection):
                return 2
            return 0 if _inspection_is_complete(inspection) else 1
        inspection = apply_repository(arguments.repo, arguments.confirm)
        _print_inspection(inspection)
        return 0
    except InstallError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
