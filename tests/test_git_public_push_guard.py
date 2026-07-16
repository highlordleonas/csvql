from __future__ import annotations

import io
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.git_public_push_guard import (
    CANONICAL_HTTPS_URL,
    ZERO_OID,
    Authorization,
    GuardError,
    RefUpdate,
    SubprocessGitRunner,
    normalize_public_repository,
    parse_authorization,
    parse_updates,
    validate_public_push,
)


class FakeGitRunner:
    def __init__(self, responses: dict[tuple[str, ...], str] | None = None) -> None:
        self.responses = responses or {}

    def run(self, *args: str) -> str:
        key = tuple(args)
        if key not in self.responses:
            raise AssertionError(f"unexpected git call: {key}")
        return self.responses[key]


def branch_authorization(operation: str, destination_ref: str, new_oid: str, old_oid: str) -> str:
    return json.dumps(
        {
            "schema": 1,
            "repository": "highlordleonas/csvql",
            "operation": operation,
            "destination_ref": destination_ref,
            "new_oid": new_oid,
            "expected_remote_oid": old_oid,
        },
        separators=(",", ":"),
    )


def annotated_tag_authorization(
    destination_ref: str,
    tag_oid: str,
    old_oid: str,
    peeled_commit_oid: str,
    *,
    tag_object_oid: str | None = None,
) -> str:
    return json.dumps(
        {
            "schema": 1,
            "repository": "highlordleonas/csvql",
            "operation": "create_annotated_tag",
            "destination_ref": destination_ref,
            "new_oid": tag_oid,
            "expected_remote_oid": old_oid,
            "tag_object_oid": tag_oid if tag_object_oid is None else tag_object_oid,
            "peeled_commit_oid": peeled_commit_oid,
        },
        separators=(",", ":"),
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/highlordleonas/csvql",
        "https://github.com/highlordleonas/csvql.git",
        "https://build-user@github.com/HighLordLeonas/CSVQL.git",
        "git@github.com:highlordleonas/csvql.git",
        "ssh://git@github.com/highlordleonas/csvql.git",
        "ssh://git@github.com:22/highlordleonas/csvql.git",
    ],
)
def test_normalize_public_repository_accepts_only_canonical_forms(url: str) -> None:
    assert normalize_public_repository(url) == "highlordleonas/csvql"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/other/csvql.git",
        "https://github.example/highlordleonas/csvql.git",
        "https://github.com/highlordleonas/csvql-extra.git",
        "http://github.com/highlordleonas/csvql.git",
        "https://github.com/highlordleonas/csvql.git?unexpected=1",
        "ssh://other@github.com/highlordleonas/csvql.git",
        "file:///tmp/csvql.git",
    ],
)
def test_normalize_public_repository_rejects_forks_and_lookalikes(url: str) -> None:
    assert normalize_public_repository(url) is None


def test_parse_updates_rejects_malformed_protocol_lines() -> None:
    with pytest.raises(GuardError, match="expected four fields"):
        parse_updates(io.StringIO("refs/heads/x abc refs/heads/y\n"))


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (
            f"refs/heads/x {'A' * 40} refs/heads/x {ZERO_OID}\n",
            "invalid source object ID",
        ),
        (
            f"refs/heads/x {'1' * 40} refs/heads/x {'g' * 40}\n",
            "invalid remote object ID",
        ),
    ],
)
def test_parse_updates_rejects_invalid_four_field_object_ids(line: str, message: str) -> None:
    with pytest.raises(GuardError, match=message):
        parse_updates(io.StringIO(line))


def test_public_branch_creation_requires_one_exact_transition() -> None:
    new_oid = "1" * 40
    update = RefUpdate("refs/heads/release/v1.0.2", new_oid, "refs/heads/release/v1.0.2", ZERO_OID)
    authorization = parse_authorization(
        branch_authorization("create_branch", update.destination_ref, new_oid, ZERO_OID)
    )
    validate_public_push(CANONICAL_HTTPS_URL, (update,), authorization, FakeGitRunner())


def test_public_branch_update_requires_the_exact_remote_object() -> None:
    old_oid = "1" * 40
    new_oid = "2" * 40
    update = RefUpdate("refs/heads/release/v1.0.2", new_oid, "refs/heads/release/v1.0.2", old_oid)
    authorization = parse_authorization(
        branch_authorization("update_branch", update.destination_ref, new_oid, old_oid)
    )
    validate_public_push(CANONICAL_HTTPS_URL, (update,), authorization, FakeGitRunner())


def test_annotated_tag_creation_binds_tag_object_and_peeled_commit() -> None:
    tag_oid = "3" * 40
    commit_oid = "2" * 40
    update = RefUpdate("refs/tags/v1.0.2", tag_oid, "refs/tags/v1.0.2", ZERO_OID)
    authorization = parse_authorization(
        json.dumps(
            {
                "schema": 1,
                "repository": "highlordleonas/csvql",
                "operation": "create_annotated_tag",
                "destination_ref": "refs/tags/v1.0.2",
                "new_oid": tag_oid,
                "expected_remote_oid": ZERO_OID,
                "tag_object_oid": tag_oid,
                "peeled_commit_oid": commit_oid,
            },
            separators=(",", ":"),
        )
    )
    git = FakeGitRunner(
        {
            ("cat-file", "-t", tag_oid): "tag",
            ("rev-parse", f"{tag_oid}^{{commit}}"): commit_oid,
        }
    )
    validate_public_push(CANONICAL_HTTPS_URL, (update,), authorization, git)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            (RefUpdate("refs/heads/main", "1" * 40, "refs/heads/main", "2" * 40),),
            "direct pushes to public main",
        ),
        (
            (RefUpdate("(delete)", ZERO_OID, "refs/heads/release/v1.0.2", "2" * 40),),
            "deletions are prohibited",
        ),
        (
            (
                RefUpdate("refs/heads/a", "1" * 40, "refs/heads/a", ZERO_OID),
                RefUpdate("refs/heads/b", "2" * 40, "refs/heads/b", ZERO_OID),
            ),
            "exactly one ref transition",
        ),
    ],
)
def test_public_push_rejects_main_deletion_and_expanded_multi_ref_updates(
    updates: tuple[RefUpdate, ...], message: str
) -> None:
    with pytest.raises(GuardError, match=message):
        validate_public_push(CANONICAL_HTTPS_URL, updates, None, FakeGitRunner())


def test_public_push_requires_inline_authorization() -> None:
    update = RefUpdate("refs/heads/release/x", "1" * 40, "refs/heads/release/x", ZERO_OID)

    with pytest.raises(GuardError, match="requires inline"):
        validate_public_push(CANONICAL_HTTPS_URL, (update,), None, FakeGitRunner())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update(extra="value"), "authorization keys must be exactly"),
        (lambda payload: payload.pop("new_oid"), "authorization keys must be exactly"),
        (lambda payload: payload.update(schema=2), "schema must be integer 1"),
        (lambda payload: payload.update(schema=True), "schema must be integer 1"),
        (lambda payload: payload.update(repository="other/csvql"), "repository does not match"),
    ],
)
def test_parse_authorization_rejects_unknown_missing_or_mismatched_schema_fields(
    mutate: Callable[[dict[str, object]], None], message: str
) -> None:
    payload = json.loads(
        branch_authorization("create_branch", "refs/heads/release/x", "1" * 40, ZERO_OID)
    )
    assert isinstance(payload, dict)
    mutate(payload)

    with pytest.raises(GuardError, match=message):
        parse_authorization(json.dumps(payload))


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (None, "requires inline"),
        ("not-json", "not valid JSON"),
        ("[]", "must be a JSON object"),
    ],
)
def test_parse_authorization_rejects_missing_or_malformed_json(
    raw: str | None, message: str
) -> None:
    with pytest.raises(GuardError, match=message):
        parse_authorization(raw)


def test_parse_authorization_rejects_duplicate_json_keys() -> None:
    raw = (
        '{"schema":1,"schema":1,"repository":"highlordleonas/csvql",'
        '"operation":"create_branch","destination_ref":"refs/heads/release/x",'
        f'"new_oid":"{"1" * 40}","expected_remote_oid":"{ZERO_OID}"}}'
    )

    with pytest.raises(GuardError, match="duplicate authorization key: schema"):
        parse_authorization(raw)


@pytest.mark.parametrize("null_key", ["tag_object_oid", "peeled_commit_oid"])
def test_parse_authorization_rejects_null_annotated_tag_object_ids(null_key: str) -> None:
    payload = json.loads(
        annotated_tag_authorization("refs/tags/v1.0.2", "3" * 40, ZERO_OID, "2" * 40)
    )
    payload[null_key] = None

    with pytest.raises(GuardError, match=rf"authorization {null_key} must be a lowercase"):
        parse_authorization(json.dumps(payload))


@pytest.mark.parametrize(
    ("authorization_raw", "message"),
    [
        (
            branch_authorization("create_branch", "refs/heads/release/other", "1" * 40, ZERO_OID),
            "destination ref does not match",
        ),
        (
            branch_authorization("create_branch", "refs/heads/release/x", "2" * 40, ZERO_OID),
            "new object does not match",
        ),
        (
            branch_authorization("create_branch", "refs/heads/release/x", "1" * 40, "2" * 40),
            "remote object does not match",
        ),
    ],
)
def test_public_push_rejects_manifest_transition_mismatches(
    authorization_raw: str, message: str
) -> None:
    update = RefUpdate("refs/heads/release/x", "1" * 40, "refs/heads/release/x", ZERO_OID)

    with pytest.raises(GuardError, match=message):
        validate_public_push(
            CANONICAL_HTTPS_URL, (update,), parse_authorization(authorization_raw), FakeGitRunner()
        )


@pytest.mark.parametrize(
    ("operation", "remote_oid", "message"),
    [
        ("create_branch", "2" * 40, "branch creation requires a zero remote object"),
        ("update_branch", ZERO_OID, "branch update requires a nonzero remote object"),
    ],
)
def test_public_branch_operation_must_match_create_or_update_state(
    operation: str, remote_oid: str, message: str
) -> None:
    new_oid = "1" * 40
    update = RefUpdate("refs/heads/release/x", new_oid, "refs/heads/release/x", remote_oid)
    authorization = parse_authorization(
        branch_authorization(operation, update.destination_ref, new_oid, remote_oid)
    )

    with pytest.raises(GuardError, match=message):
        validate_public_push(CANONICAL_HTTPS_URL, (update,), authorization, FakeGitRunner())


def test_public_tag_update_is_prohibited() -> None:
    tag_oid = "3" * 40
    old_oid = "4" * 40
    update = RefUpdate("refs/tags/v1.0.2", tag_oid, "refs/tags/v1.0.2", old_oid)
    authorization = parse_authorization(
        annotated_tag_authorization(update.destination_ref, tag_oid, old_oid, "2" * 40)
    )

    with pytest.raises(GuardError, match="tag creation requires a zero remote object"):
        validate_public_push(CANONICAL_HTTPS_URL, (update,), authorization, FakeGitRunner())


def test_public_lightweight_tag_is_prohibited() -> None:
    tag_oid = "3" * 40
    commit_oid = "2" * 40
    update = RefUpdate("refs/tags/v1.0.2", tag_oid, "refs/tags/v1.0.2", ZERO_OID)
    authorization = parse_authorization(
        annotated_tag_authorization(update.destination_ref, tag_oid, ZERO_OID, commit_oid)
    )
    git = FakeGitRunner({("cat-file", "-t", tag_oid): "commit"})

    with pytest.raises(GuardError, match="annotated tag object"):
        validate_public_push(CANONICAL_HTTPS_URL, (update,), authorization, git)


def test_public_tag_object_must_match_manifest() -> None:
    tag_oid = "3" * 40
    update = RefUpdate("refs/tags/v1.0.2", tag_oid, "refs/tags/v1.0.2", ZERO_OID)
    authorization = parse_authorization(
        annotated_tag_authorization(
            update.destination_ref,
            tag_oid,
            ZERO_OID,
            "2" * 40,
            tag_object_oid="4" * 40,
        )
    )

    with pytest.raises(GuardError, match="tag object does not match"):
        validate_public_push(CANONICAL_HTTPS_URL, (update,), authorization, FakeGitRunner())


def test_public_tag_peeled_commit_must_match_manifest() -> None:
    tag_oid = "3" * 40
    update = RefUpdate("refs/tags/v1.0.2", tag_oid, "refs/tags/v1.0.2", ZERO_OID)
    authorization = parse_authorization(
        annotated_tag_authorization(update.destination_ref, tag_oid, ZERO_OID, "2" * 40)
    )
    git = FakeGitRunner(
        {
            ("cat-file", "-t", tag_oid): "tag",
            ("rev-parse", f"{tag_oid}^{{commit}}"): "5" * 40,
        }
    )

    with pytest.raises(GuardError, match="peeled commit does not match"):
        validate_public_push(CANONICAL_HTTPS_URL, (update,), authorization, git)


def test_wildcard_expansion_cannot_authorize_two_ref_transitions() -> None:
    updates = (
        RefUpdate("refs/heads/release/a", "1" * 40, "refs/heads/release/a", ZERO_OID),
        RefUpdate("refs/heads/release/b", "2" * 40, "refs/heads/release/b", ZERO_OID),
    )
    authorization = parse_authorization(
        branch_authorization(
            "create_branch", updates[0].destination_ref, updates[0].source_oid, ZERO_OID
        )
    )

    with pytest.raises(GuardError, match="exactly one ref transition"):
        validate_public_push(CANONICAL_HTTPS_URL, updates, authorization, FakeGitRunner())


@pytest.mark.parametrize("possible_original_flag", ["--all", "--mirror"])
def test_single_ref_expansion_is_treated_as_one_exact_transition(
    possible_original_flag: str,
) -> None:
    del possible_original_flag  # pre-push input does not expose original Git flags
    new_oid = "1" * 40
    update = RefUpdate("refs/heads/release/x", new_oid, "refs/heads/release/x", ZERO_OID)
    authorization = parse_authorization(
        branch_authorization("create_branch", update.destination_ref, new_oid, ZERO_OID)
    )

    validate_public_push(CANONICAL_HTTPS_URL, (update,), authorization, FakeGitRunner())


def test_non_public_repository_returns_without_authorization_or_git_calls() -> None:
    update = RefUpdate("refs/heads/main", "1" * 40, "refs/heads/main", "2" * 40)
    validate_public_push("https://github.com/other/csvql.git", (update,), None, FakeGitRunner())


@pytest.mark.parametrize(
    "remote_url",
    [
        f"{CANONICAL_HTTPS_URL}?unexpected=1",
        f"{CANONICAL_HTTPS_URL}#ignored-by-git",
        "http://github.com/highlordleonas/csvql.git",
        "ssh://other@github.com/highlordleonas/csvql.git",
        "https://github.com./highlordleonas/csvql.git",
    ],
)
def test_canonical_but_forbidden_public_url_shapes_fail_closed(remote_url: str) -> None:
    update = RefUpdate("refs/heads/release/x", "1" * 40, "refs/heads/release/x", ZERO_OID)

    assert normalize_public_repository(remote_url) is None
    with pytest.raises(GuardError, match="canonical public repository URL is not approved"):
        validate_public_push(remote_url, (update,), None, FakeGitRunner())


@pytest.mark.parametrize(
    "remote_url",
    [
        "https://github.com/highlordleonas/./csvql.git",
        "https://github.com/junk/../highlordleonas/csvql.git",
        "https://github.com/%68ighlordleonas/csvql.git",
        "https://github.com/highlordleonas/%63svql.git",
        "https://github.com/highlordleonas/%2E/csvql.git",
        "https://github.com/highlordleonas//csvql.git",
        "github.com:highlordleonas/csvql.git",
        "ssh://git@ssh.github.com:443/highlordleonas/csvql.git",
    ],
)
def test_normalized_and_alternate_canonical_targets_fail_closed(remote_url: str) -> None:
    update = RefUpdate("refs/heads/release/x", "1" * 40, "refs/heads/release/x", ZERO_OID)

    assert normalize_public_repository(remote_url) is None
    with pytest.raises(GuardError, match="canonical public repository URL is not approved"):
        validate_public_push(remote_url, (update,), None, FakeGitRunner())


@pytest.mark.parametrize(
    "remote_url",
    [
        "https://github.com/junk/../other/csvql.git",
        "https://github.example/junk/../highlordleonas/csvql.git",
        "github.com:other/csvql.git",
    ],
)
def test_normalized_genuine_non_public_targets_still_pass_through(remote_url: str) -> None:
    update = RefUpdate("refs/heads/main", "1" * 40, "refs/heads/main", "2" * 40)

    assert normalize_public_repository(remote_url) is None
    validate_public_push(remote_url, (update,), None, FakeGitRunner())


@pytest.mark.parametrize("malformed_url", ["https://[", "https://", "ssh://git@"])
def test_malformed_remote_url_fails_closed_without_url_parser_traceback(
    malformed_url: str,
) -> None:
    update = RefUpdate("refs/heads/release/x", "1" * 40, "refs/heads/release/x", ZERO_OID)

    assert normalize_public_repository(malformed_url) is None
    with pytest.raises(GuardError, match="malformed remote URL"):
        validate_public_push(malformed_url, (update,), None, FakeGitRunner())


DIRECT_BRANCH_AUTHORIZATION = Authorization(
    schema=1,
    repository="highlordleonas/csvql",
    operation="create_branch",
    destination_ref="refs/heads/release/x",
    new_oid="1" * 40,
    expected_remote_oid=ZERO_OID,
)


@pytest.mark.parametrize(
    ("authorization", "message"),
    [
        (replace(DIRECT_BRANCH_AUTHORIZATION, schema=2), "authorization schema must be integer 1"),
        (
            replace(DIRECT_BRANCH_AUTHORIZATION, schema=True),
            "authorization schema must be integer 1",
        ),
        (
            replace(DIRECT_BRANCH_AUTHORIZATION, repository="other/csvql"),
            "repository does not match",
        ),
        (
            replace(DIRECT_BRANCH_AUTHORIZATION, operation="unsupported"),
            "authorization operation is not supported",
        ),
        (
            replace(DIRECT_BRANCH_AUTHORIZATION, destination_ref=42),  # type: ignore[arg-type]
            "authorization destination_ref must be a string",
        ),
        (
            replace(DIRECT_BRANCH_AUTHORIZATION, new_oid="A" * 40),
            "authorization new_oid must be a lowercase",
        ),
        (
            replace(DIRECT_BRANCH_AUTHORIZATION, expected_remote_oid="g" * 40),
            "authorization expected_remote_oid must be a lowercase",
        ),
        (
            replace(DIRECT_BRANCH_AUTHORIZATION, tag_object_oid="3" * 40),
            "branch authorizations must not include tag object fields",
        ),
        (
            replace(DIRECT_BRANCH_AUTHORIZATION, peeled_commit_oid="2" * 40),
            "branch authorizations must not include tag object fields",
        ),
    ],
)
def test_validate_public_push_revalidates_direct_branch_authorization_invariants(
    authorization: Authorization, message: str
) -> None:
    update = RefUpdate("refs/heads/release/x", "1" * 40, "refs/heads/release/x", ZERO_OID)

    with pytest.raises(GuardError, match=message):
        validate_public_push(CANONICAL_HTTPS_URL, (update,), authorization, FakeGitRunner())


DIRECT_TAG_AUTHORIZATION = Authorization(
    schema=1,
    repository="highlordleonas/csvql",
    operation="create_annotated_tag",
    destination_ref="refs/tags/v1.0.2",
    new_oid="3" * 40,
    expected_remote_oid=ZERO_OID,
    tag_object_oid="3" * 40,
    peeled_commit_oid="2" * 40,
)


@pytest.mark.parametrize(
    ("authorization", "message"),
    [
        (
            replace(DIRECT_TAG_AUTHORIZATION, tag_object_oid=None),
            "authorization tag_object_oid must be a lowercase",
        ),
        (
            replace(DIRECT_TAG_AUTHORIZATION, peeled_commit_oid=None),
            "authorization peeled_commit_oid must be a lowercase",
        ),
        (
            replace(DIRECT_TAG_AUTHORIZATION, tag_object_oid="A" * 40),
            "authorization tag_object_oid must be a lowercase",
        ),
        (
            replace(DIRECT_TAG_AUTHORIZATION, peeled_commit_oid="g" * 40),
            "authorization peeled_commit_oid must be a lowercase",
        ),
    ],
)
def test_validate_public_push_revalidates_direct_tag_authorization_invariants(
    authorization: Authorization, message: str
) -> None:
    update = RefUpdate("refs/tags/v1.0.2", "3" * 40, "refs/tags/v1.0.2", ZERO_OID)

    with pytest.raises(GuardError, match=message):
        validate_public_push(CANONICAL_HTTPS_URL, (update,), authorization, FakeGitRunner())


def test_subprocess_git_runner_redacts_captured_failure_and_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_manifest = "manifest-secret-must-not-appear"
    monkeypatch.setenv("LOCALQL_PUBLIC_PUSH_AUTHORIZATION", secret_manifest)

    def fail_git(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=args[0],
            stderr=f"git failure leaked {secret_manifest}",
        )

    monkeypatch.setattr(subprocess, "run", fail_git)

    with pytest.raises(GuardError, match="git command failed") as error_info:
        SubprocessGitRunner().run("cat-file", "-t", "3" * 40)

    assert secret_manifest not in str(error_info.value)
    assert "git failure leaked" not in str(error_info.value)


GUARD_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "git_public_push_guard.py"


def run_guard_cli(
    remote_name: str,
    remote_url: str,
    update: RefUpdate,
    *,
    authorization_raw: str | None,
) -> subprocess.CompletedProcess[str]:
    environment = {}
    if authorization_raw is not None:
        environment["LOCALQL_PUBLIC_PUSH_AUTHORIZATION"] = authorization_raw
    protocol_line = (
        f"{update.source_ref} {update.source_oid} {update.destination_ref} {update.remote_oid}\n"
    )
    return subprocess.run(
        [sys.executable, str(GUARD_SCRIPT), remote_name, remote_url],
        input=protocol_line,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def test_cli_allows_one_approved_transition_with_direct_url_arguments() -> None:
    new_oid = "1" * 40
    update = RefUpdate("refs/heads/release/x", new_oid, "refs/heads/release/x", ZERO_OID)
    authorization_raw = branch_authorization(
        "create_branch", update.destination_ref, new_oid, ZERO_OID
    )

    completed = run_guard_cli(
        CANONICAL_HTTPS_URL,
        CANONICAL_HTTPS_URL,
        update,
        authorization_raw=authorization_raw,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""


def test_cli_classifies_canonical_repository_by_url_not_misleading_remote_name() -> None:
    update = RefUpdate("refs/heads/main", "1" * 40, "refs/heads/main", "2" * 40)
    authorization_raw = branch_authorization(
        "update_branch", update.destination_ref, update.source_oid, update.remote_oid
    )

    completed = run_guard_cli(
        "backup",
        CANONICAL_HTTPS_URL,
        update,
        authorization_raw=authorization_raw,
    )

    assert completed.returncode == 1
    assert update.destination_ref in completed.stderr
    assert "Local hooks can be bypassed; GitHub hosted rules are authoritative." in completed.stderr
    assert authorization_raw not in completed.stderr


def test_cli_does_not_classify_non_public_url_by_canonical_remote_name() -> None:
    update = RefUpdate("refs/heads/main", "1" * 40, "refs/heads/main", "2" * 40)

    completed = run_guard_cli(
        "origin",
        "https://github.com/other/csvql.git",
        update,
        authorization_raw=None,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""


def test_cli_rejection_never_prints_the_inline_manifest() -> None:
    update = RefUpdate("refs/heads/release/x", "1" * 40, "refs/heads/release/x", ZERO_OID)
    authorization_raw = branch_authorization(
        "create_branch", update.destination_ref, "2" * 40, ZERO_OID
    )

    completed = run_guard_cli(
        "origin", CANONICAL_HTTPS_URL, update, authorization_raw=authorization_raw
    )

    assert completed.returncode == 1
    assert update.destination_ref in completed.stderr
    assert authorization_raw not in completed.stderr
    assert "Local hooks can be bypassed; GitHub hosted rules are authoritative." in completed.stderr


def test_cli_rejects_public_transition_when_environment_authorization_is_missing() -> None:
    update = RefUpdate("refs/heads/release/x", "1" * 40, "refs/heads/release/x", ZERO_OID)

    completed = run_guard_cli("origin", CANONICAL_HTTPS_URL, update, authorization_raw=None)

    assert completed.returncode == 1
    assert update.destination_ref in completed.stderr
    assert "requires inline LOCALQL_PUBLIC_PUSH_AUTHORIZATION JSON" in completed.stderr
    assert "Local hooks can be bypassed; GitHub hosted rules are authoritative." in completed.stderr


@pytest.mark.parametrize(
    "remote_url",
    [
        f"{CANONICAL_HTTPS_URL}?unexpected=1",
        f"{CANONICAL_HTTPS_URL}#ignored-by-git",
    ],
)
def test_cli_rejects_canonical_query_and_fragment_urls(remote_url: str) -> None:
    update = RefUpdate("refs/heads/release/x", "1" * 40, "refs/heads/release/x", ZERO_OID)

    completed = run_guard_cli("origin", remote_url, update, authorization_raw=None)

    assert completed.returncode == 1
    assert update.destination_ref in completed.stderr
    assert "canonical public repository URL is not approved" in completed.stderr
    assert "Local hooks can be bypassed; GitHub hosted rules are authoritative." in completed.stderr


@pytest.mark.parametrize(
    "remote_url",
    [
        "https://github.com/highlordleonas/./csvql.git",
        "https://github.com/junk/../highlordleonas/csvql.git",
        "github.com:highlordleonas/csvql.git",
        "ssh://git@ssh.github.com:443/highlordleonas/csvql.git",
    ],
)
def test_cli_rejects_normalized_and_alternate_canonical_targets(remote_url: str) -> None:
    update = RefUpdate("refs/heads/release/x", "1" * 40, "refs/heads/release/x", ZERO_OID)

    completed = run_guard_cli("origin", remote_url, update, authorization_raw=None)

    assert completed.returncode == 1
    assert update.destination_ref in completed.stderr
    assert "canonical public repository URL is not approved" in completed.stderr
    assert "Local hooks can be bypassed; GitHub hosted rules are authoritative." in completed.stderr


@pytest.mark.parametrize("malformed_url", ["https://[", "https://", "ssh://git@"])
def test_cli_rejects_malformed_url_without_traceback(malformed_url: str) -> None:
    update = RefUpdate("refs/heads/release/x", "1" * 40, "refs/heads/release/x", ZERO_OID)

    completed = run_guard_cli("origin", malformed_url, update, authorization_raw=None)

    assert completed.returncode == 1
    assert update.destination_ref in completed.stderr
    assert "malformed remote URL" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert "Local hooks can be bypassed; GitHub hosted rules are authoritative." in completed.stderr
