from __future__ import annotations

import json
import os
import posixpath
import re
import string
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol, TextIO
from urllib.parse import urlsplit

CANONICAL_REPOSITORY = "highlordleonas/csvql"
CANONICAL_HTTPS_URL = "https://github.com/highlordleonas/csvql.git"
ZERO_OID = "0" * 40
OID_RE = re.compile(r"[0-9a-f]{40}")
PERCENT_ESCAPE_RE = re.compile(r"%([0-9a-f]{2})", flags=re.IGNORECASE)
URL_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")
CANONICAL_GITHUB_HOSTS = frozenset({"github.com", "ssh.github.com"})
ALLOWED_OPERATIONS = {"create_branch", "update_branch", "create_annotated_tag"}
BASE_APPROVAL_KEYS = {
    "schema",
    "repository",
    "operation",
    "destination_ref",
    "new_oid",
    "expected_remote_oid",
}
TAG_APPROVAL_KEYS = BASE_APPROVAL_KEYS | {"tag_object_oid", "peeled_commit_oid"}


class GuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class RefUpdate:
    source_ref: str
    source_oid: str
    destination_ref: str
    remote_oid: str


@dataclass(frozen=True)
class Approval:
    schema: int
    repository: str
    operation: str
    destination_ref: str
    new_oid: str
    expected_remote_oid: str
    tag_object_oid: str | None = None
    peeled_commit_oid: str | None = None


class GitRunner(Protocol):
    def run(self, *args: str) -> str: ...


class _RemoteClassification(Enum):
    PUBLIC = auto()
    CANONICAL_FORBIDDEN = auto()
    NON_PUBLIC = auto()
    MALFORMED = auto()


class SubprocessGitRunner:
    def run(self, *args: str) -> str:
        command = ("git", *args)
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise GuardError(f"git command failed: {' '.join(command)}") from error
        return completed.stdout.strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GuardError(message)


def is_canonical_path(path: str) -> bool:
    normalized = path.strip("/")
    if normalized.lower().endswith(".git"):
        normalized = normalized[:-4]
    return normalized.lower() == CANONICAL_REPOSITORY


def _decode_unreserved_path(path: str) -> str:
    def replace_escape(match: re.Match[str]) -> str:
        decoded = chr(int(match.group(1), 16))
        return decoded if decoded in URL_UNRESERVED else match.group(0)

    return PERCENT_ESCAPE_RE.sub(replace_escape, path)


def _is_canonical_path_candidate(path: str) -> bool:
    normalized = posixpath.normpath(_decode_unreserved_path(path))
    return is_canonical_path(normalized)


def _classify_remote_url(url: str) -> _RemoteClassification:
    scp_match = None
    if "://" not in url:
        scp_match = re.fullmatch(
            r"(?:(?P<user>[^@\s:]+)@)?(?P<host>[^:/\s]+):(?P<path>.+)",
            url,
        )
    if scp_match is not None:
        scp_hostname = scp_match.group("host").lower()
        scp_path = scp_match.group("path")
        canonical_target = scp_hostname.rstrip(
            "."
        ) in CANONICAL_GITHUB_HOSTS and _is_canonical_path_candidate(scp_path)
        if not canonical_target:
            return _RemoteClassification.NON_PUBLIC
        scp_user = scp_match.group("user")
        if (
            scp_hostname == "github.com"
            and scp_user is not None
            and scp_user.lower() == "git"
            and is_canonical_path(scp_path)
        ):
            return _RemoteClassification.PUBLIC
        return _RemoteClassification.CANONICAL_FORBIDDEN

    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        username = (parsed.username or "").lower()
        port = parsed.port
    except ValueError:
        return _RemoteClassification.MALFORMED

    scheme = parsed.scheme.lower()
    if scheme in {"git", "http", "https", "ssh"} and not hostname:
        return _RemoteClassification.MALFORMED
    if hostname.rstrip(".") not in CANONICAL_GITHUB_HOSTS or not _is_canonical_path_candidate(
        parsed.path
    ):
        return _RemoteClassification.NON_PUBLIC
    if parsed.query or parsed.fragment:
        return _RemoteClassification.CANONICAL_FORBIDDEN
    if not is_canonical_path(parsed.path):
        return _RemoteClassification.CANONICAL_FORBIDDEN
    if scheme == "https":
        valid_authority = hostname == "github.com" and port in (None, 443)
    elif scheme == "ssh":
        valid_authority = hostname == "github.com" and username == "git" and port in (None, 22)
    else:
        valid_authority = False
    if valid_authority:
        return _RemoteClassification.PUBLIC
    return _RemoteClassification.CANONICAL_FORBIDDEN


def normalize_public_repository(url: str) -> str | None:
    if _classify_remote_url(url) is _RemoteClassification.PUBLIC:
        return CANONICAL_REPOSITORY
    return None


def parse_updates(stream: TextIO) -> tuple[RefUpdate, ...]:
    updates: list[RefUpdate] = []
    for line_number, raw_line in enumerate(stream, start=1):
        fields = raw_line.rstrip("\n").split()
        if len(fields) != 4:
            raise GuardError(f"pre-push line {line_number}: expected four fields")
        source_ref, source_oid, destination_ref, remote_oid = fields
        for label, oid in (("source", source_oid), ("remote", remote_oid)):
            if OID_RE.fullmatch(oid) is None:
                raise GuardError(f"pre-push line {line_number}: invalid {label} object ID")
        updates.append(RefUpdate(source_ref, source_oid, destination_ref, remote_oid))
    return tuple(updates)


def _reject_duplicate_approval_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise GuardError(f"duplicate approval key: {key}")
        payload[key] = value
    return payload


def _validate_approval_invariants(approval: Approval) -> None:
    require(
        type(approval.schema) is int and approval.schema == 1,
        "approval schema must be integer 1",
    )
    require(
        isinstance(approval.repository, str) and approval.repository == CANONICAL_REPOSITORY,
        "approval schema or repository does not match LocalQL public push policy",
    )
    require(
        isinstance(approval.operation, str) and approval.operation in ALLOWED_OPERATIONS,
        "approval operation is not supported",
    )
    require(
        isinstance(approval.destination_ref, str),
        "approval destination_ref must be a string",
    )
    for key, value in (
        ("new_oid", approval.new_oid),
        ("expected_remote_oid", approval.expected_remote_oid),
    ):
        require(
            isinstance(value, str) and OID_RE.fullmatch(value) is not None,
            f"approval {key} must be a lowercase 40-character object ID",
        )

    if approval.operation == "create_annotated_tag":
        for key, value in (
            ("tag_object_oid", approval.tag_object_oid),
            ("peeled_commit_oid", approval.peeled_commit_oid),
        ):
            require(
                isinstance(value, str) and OID_RE.fullmatch(value) is not None,
                f"approval {key} must be a lowercase 40-character object ID",
            )
    else:
        require(
            approval.tag_object_oid is None and approval.peeled_commit_oid is None,
            "branch approvals must not include tag object fields",
        )


def parse_approval(raw: str | None) -> Approval:
    if raw is None:
        raise GuardError("public push requires inline LOCALQL_PUBLIC_PUSH_APPROVAL JSON")
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_approval_keys)
    except json.JSONDecodeError as error:
        raise GuardError("LOCALQL_PUBLIC_PUSH_APPROVAL is not valid JSON") from error
    if not isinstance(payload, dict):
        raise GuardError("LOCALQL_PUBLIC_PUSH_APPROVAL must be a JSON object")
    operation = payload.get("operation")
    expected_keys = TAG_APPROVAL_KEYS if operation == "create_annotated_tag" else BASE_APPROVAL_KEYS
    if set(payload) != expected_keys:
        raise GuardError(f"approval keys must be exactly {sorted(expected_keys)}")
    tag_object_oid = payload.get("tag_object_oid")
    peeled_commit_oid = payload.get("peeled_commit_oid")
    approval = Approval(
        schema=payload["schema"],
        repository=payload["repository"],
        operation=operation,
        destination_ref=payload["destination_ref"],
        new_oid=payload["new_oid"],
        expected_remote_oid=payload["expected_remote_oid"],
        tag_object_oid=tag_object_oid,
        peeled_commit_oid=peeled_commit_oid,
    )
    _validate_approval_invariants(approval)
    return approval


def validate_public_push(
    remote_url: str,
    updates: tuple[RefUpdate, ...],
    approval: Approval | None,
    git: GitRunner,
) -> None:
    remote_classification = _classify_remote_url(remote_url)
    if remote_classification is _RemoteClassification.NON_PUBLIC:
        return
    require(
        remote_classification is not _RemoteClassification.MALFORMED,
        "malformed remote URL is prohibited by public push policy",
    )
    require(
        remote_classification is not _RemoteClassification.CANONICAL_FORBIDDEN,
        "canonical public repository URL is not approved by public push policy",
    )

    require(len(updates) == 1, "public push approval permits exactly one ref transition")
    update = updates[0]
    require(
        update.destination_ref != "refs/heads/main",
        "direct pushes to public main are prohibited",
    )
    require(update.source_oid != ZERO_OID, "public ref deletions are prohibited")
    require(approval is not None, "public push requires inline LOCALQL_PUBLIC_PUSH_APPROVAL JSON")
    _validate_approval_invariants(approval)

    require(
        update.destination_ref == approval.destination_ref,
        "approval destination ref does not match the public push",
    )
    require(
        update.source_oid == approval.new_oid, "approval new object does not match the public push"
    )
    require(
        update.remote_oid == approval.expected_remote_oid,
        "approval remote object does not match the public push",
    )

    if approval.operation == "create_branch":
        require(
            update.destination_ref.startswith("refs/heads/"),
            "branch creation requires a branch destination",
        )
        require(update.remote_oid == ZERO_OID, "branch creation requires a zero remote object")
    elif approval.operation == "update_branch":
        require(
            update.destination_ref.startswith("refs/heads/"),
            "branch update requires a branch destination",
        )
        require(update.remote_oid != ZERO_OID, "branch update requires a nonzero remote object")
    else:
        require(
            update.destination_ref.startswith("refs/tags/v"),
            "annotated tag creation requires a version tag destination",
        )
        require(update.remote_oid == ZERO_OID, "tag creation requires a zero remote object")
        require(approval.tag_object_oid == update.source_oid, "approval tag object does not match")
        require(
            git.run("cat-file", "-t", update.source_oid) == "tag",
            "push object is not an annotated tag object",
        )
        require(
            git.run("rev-parse", f"{update.source_oid}^{{commit}}") == approval.peeled_commit_oid,
            "approval peeled commit does not match the tag",
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    updates: tuple[RefUpdate, ...] = ()
    try:
        require(len(arguments) == 2, "expected pre-push remote name and remote URL arguments")
        _remote_name, remote_url = arguments
        updates = parse_updates(sys.stdin)
        approval = None
        if normalize_public_repository(remote_url) is not None:
            approval = parse_approval(os.environ.get("LOCALQL_PUBLIC_PUSH_APPROVAL"))
        validate_public_push(remote_url, updates, approval, SubprocessGitRunner())
    except GuardError as error:
        destinations = ", ".join(update.destination_ref for update in updates) or "(unavailable)"
        print(
            f"LocalQL public push rejected for destination refs {destinations}: {error}",
            file=sys.stderr,
        )
        print(
            "Local hooks can be bypassed; GitHub hosted rules are authoritative.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
