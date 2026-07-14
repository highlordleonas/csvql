# Releasing LocalQL

This is the canonical maintainer runbook for moving LocalQL through public Git
and package release states. It describes release operations, not product scope;
the repository instructions and roadmap remain authoritative for scope.

## Audience And Safety Boundary

Maintainers use the guarded workflow below in a canonical LocalQL clone.
External contributors push branches to their own forks and open pull requests;
they are not expected to install maintainer-only Git settings.

The local push hook is defense in depth, not an authorization system. Hooks are
bypassable with `--no-verify`, so hosted rules are authoritative for protecting
public refs. A passing local guard or check only verifies eligibility for an
approved operation. It never supplies approval, merges a pull request, tags a
version, creates a GitHub Release, or publishes to PyPI.

## Normal Local State

After a separately approved fetch, local `main` equals the freshly fetched live
public `main`. Ordinary work occurs on a local `feature/*`, `fix/*`, `docs/*`,
or `release/vX.Y.Z` branch. These branches remain local unless an exact public
transition is separately approved. The canonical `origin` fetches from the
public repository but has an inert push destination during ordinary work.

Before release work, verify the clone's local safety controls:

```bash
make git-safety-check
```

Stop if the check fails. Repairing or installing clone controls is a separate
local configuration action; it does not authorize any public write.

## Approval Manifest

Every approved public push carries one inline `LOCALQL_PUBLIC_PUSH_APPROVAL`
JSON object and exactly one ref transition. The six base keys are `schema`,
`repository`, `operation`, `destination_ref`, `new_oid`, and
`expected_remote_oid`. An annotated-tag approval also requires
`tag_object_oid` and `peeled_commit_oid`. Object IDs are lowercase, full
40-character Git object IDs. The destination ref and expected remote object
must be verified immediately before requesting approval.

Creating a public branch uses a zero expected remote object:

```json
{"schema":1,"repository":"highlordleonas/csvql","operation":"create_branch","destination_ref":"refs/heads/release/v1.0.2","new_oid":"1111111111111111111111111111111111111111","expected_remote_oid":"0000000000000000000000000000000000000000"}
```

Updating that branch binds approval to its current public object:

```json
{"schema":1,"repository":"highlordleonas/csvql","operation":"update_branch","destination_ref":"refs/heads/release/v1.0.2","new_oid":"2222222222222222222222222222222222222222","expected_remote_oid":"1111111111111111111111111111111111111111"}
```

Creating an annotated version tag binds both the tag object and its peeled
commit:

```json
{"schema":1,"repository":"highlordleonas/csvql","operation":"create_annotated_tag","destination_ref":"refs/tags/v1.0.2","new_oid":"3333333333333333333333333333333333333333","expected_remote_oid":"0000000000000000000000000000000000000000","tag_object_oid":"3333333333333333333333333333333333333333","peeled_commit_oid":"2222222222222222222222222222222222222222"}
```

For example, an approved branch creation uses inline assignment, an explicit
public URL, and one source-to-destination refspec:

```bash
LOCALQL_PUBLIC_PUSH_APPROVAL='{"schema":1,"repository":"highlordleonas/csvql","operation":"create_branch","destination_ref":"refs/heads/release/v1.0.2","new_oid":"1111111111111111111111111111111111111111","expected_remote_oid":"0000000000000000000000000000000000000000"}' \
  git push https://github.com/highlordleonas/csvql.git \
  1111111111111111111111111111111111111111:refs/heads/release/v1.0.2
```

The repeated `1` digits are nonfunctional documentation examples; the repeated
`2` and `3` digits are examples too. An actual approval and command must contain
the exact full object IDs and refs verified for that one transition. Never copy
an example manifest into a real push.

## Release State Machine

Record the version, commit ID, evidence, approval, and outcome for each state.
Passing one state does not authorize the next.

1. **Local development:** changes exist only on a maintainer work branch.
2. **Local candidate:** the exact version and commit pass candidate evidence.
3. **Public branch and pull request:** one approved branch push is followed by
   an intentionally opened pull request; required hosted CI must pass.
4. **Merge:** a separate pull-request merge approval publishes code to public
   `main`. It does not approve a tag or package publication.
5. **Annotated tag and tag CI:** a separate approval creates one immutable
   annotated version tag from the verified merge commit. Tag CI is evidence,
   not permission to publish.
6. **Optional draft GitHub Release:** creating a remote draft is a separate
   approved GitHub write and must reference the immutable tag.
7. **Environment-approved PyPI publish:** the protected `pypi` environment and
   a separate exact approval must both gate publication of the verified artifacts.
8. **Verified public GitHub Release:** after PyPI verification, a separate
   approval publishes or creates the GitHub Release against the same tag.

## Candidate Evidence

Start from a clean candidate commit and record every command, result, commit
ID, version, artifact filename, and SHA-256 digest. Use a new evidence directory
for every attempt. The directory is claimed with one plain `mkdir`, which fails
if that candidate name was already used; do not delete or reuse a failed claim.
Replace `vX.Y.Z` with the exact version, then run the entire block in Bash from
the repository root:

```bash
set -euo pipefail
release_version="vX.Y.Z"
[[ "${release_version}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
expected_version="${release_version#v}"
candidate_oid="$(git rev-parse --verify HEAD^{commit})"
test "$(git cat-file -t "${candidate_oid}")" = "commit"
git diff --quiet --exit-code --
git diff --cached --quiet --exit-code --
initial_status="$(git status --porcelain=v1 --untracked-files=all)"
test -z "${initial_status}"

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}"
evidence_root="${repository_root}/output/release-candidate"
evidence_dir="${evidence_root}/${release_version}-${candidate_oid}"
mkdir -p -- "${evidence_root}"
mkdir -- "${evidence_dir}"
printf '%s\n' "${candidate_oid}" > "${evidence_dir}/candidate-commit.txt"

make ci-fresh
uv build --sdist --wheel --out-dir "${evidence_dir}/dist"

shopt -s nullglob
wheels=("${evidence_dir}"/dist/*.whl)
sdists=("${evidence_dir}"/dist/*.tar.gz)
if (( ${#wheels[@]} != 1 )); then
  printf 'expected exactly one wheel, found %s\n' "${#wheels[@]}" >&2
  exit 1
fi
if (( ${#sdists[@]} != 1 )); then
  printf 'expected exactly one sdist, found %s\n' "${#sdists[@]}" >&2
  exit 1
fi

uv run --frozen --no-sync python scripts/audit_package_contents.py \
  "${evidence_dir}/dist"
uv run --frozen --no-sync python - \
  "${expected_version}" "${wheels[0]}" "${sdists[0]}" <<'PY_METADATA'
from email.parser import BytesParser
from email.policy import default
from pathlib import PurePosixPath
import sys
import tarfile
import zipfile

expected_version, wheel_path, sdist_path = sys.argv[1:]


def validate_metadata(raw: bytes, source: str) -> None:
    metadata = BytesParser(policy=default).parsebytes(raw)
    observed = (metadata["Name"], metadata["Version"])
    if observed != ("localql", expected_version):
        raise SystemExit(f"{source} metadata mismatch: {observed!r}")


with zipfile.ZipFile(wheel_path) as wheel:
    metadata_paths = [
        name
        for name in wheel.namelist()
        if name.endswith(".dist-info/METADATA")
    ]
    if len(metadata_paths) != 1:
        raise SystemExit("wheel must contain exactly one METADATA file")
    validate_metadata(wheel.read(metadata_paths[0]), "wheel")

with tarfile.open(sdist_path, "r:*") as sdist:
    metadata_members = [
        member
        for member in sdist.getmembers()
        if member.isfile()
        and len(PurePosixPath(member.name).parts) == 2
        and PurePosixPath(member.name).name == "PKG-INFO"
    ]
    if len(metadata_members) != 1:
        raise SystemExit("sdist must contain exactly one root PKG-INFO file")
    metadata_file = sdist.extractfile(metadata_members[0])
    if metadata_file is None:
        raise SystemExit("sdist PKG-INFO is unreadable")
    validate_metadata(metadata_file.read(), "sdist")
PY_METADATA

artifacts=("${wheels[@]}" "${sdists[@]}")
shasum -a 256 "${artifacts[@]}" > "${evidence_dir}/SHA256SUMS.txt"

smoke_root="$(mktemp -d)"
uv venv --seed "${smoke_root}/venv"
uv pip install --python "${smoke_root}/venv/bin/python" "${wheels[0]}"
printf 'order_id,status\nORD-1,paid\n' > "${smoke_root}/orders.csv"
unset PYTHONPATH
cli_version="$("${smoke_root}/venv/bin/csvql" --version)"
test "${cli_version}" = "${expected_version}"
query_json="$(
  "${smoke_root}/venv/bin/csvql" query "${smoke_root}/orders.csv" \
    "SELECT COUNT(*) AS order_count FROM orders" --output json
)"
printf '%s\n' "${query_json}" > "${evidence_dir}/query-smoke.json"
"${smoke_root}/venv/bin/python" - \
  "${expected_version}" "${evidence_dir}/query-smoke.json" <<'PY_SMOKE'
from importlib.metadata import version
import json
import sys

expected_version, query_path = sys.argv[1:]
installed_version = version("localql")
if installed_version != expected_version:
    raise SystemExit(
        f"installed localql version mismatch: {installed_version!r}"
    )

with open(query_path, encoding="utf-8") as handle:
    query_result = json.load(handle)
expected_result = {
    "columns": ["order_count"],
    "rows": [{"order_count": 1}],
    "row_count": 1,
}
observed_result = {
    key: query_result.get(key)
    for key in expected_result
}
if observed_result != expected_result:
    raise SystemExit(f"installed query result mismatch: {observed_result!r}")
PY_SMOKE

git status --short --ignored > "${evidence_dir}/git-status-short-ignored.txt"
test "$(git rev-parse --verify HEAD^{commit})" = "${candidate_oid}"
git diff --quiet --exit-code --
git diff --cached --quiet --exit-code --
final_status="$(git status --porcelain=v1 --untracked-files=all)"
test -z "${final_status}"
```

Any failure stops the evidence run. Only failures after the evidence directory
is claimed leave that directory for diagnosis; failures before the claim create
no evidence directory. Require the exact version and an `order_count` of `1`.
Confirm the ignored-file inventory contains nothing unexpectedly public, and
inspect both wheel and source distribution contents. Record an adversarial
review of release claims, compatibility, known limitations, deferred work, and
any skipped check. Evidence must match the exact candidate commit and artifacts;
stale evidence is invalid.

## Failure And Recovery

- Infrastructure-only CI recovery calls the exact `rerun-failed-jobs` endpoint
  and records its `201` response and incremented run attempt; a whole-run rerun
  is not authorized.
- A visible upload-capable PyPI token is not revoked until safe consumer impact,
  affected projects, scope, replacement, and mitigation are established.
  Unknown blast radius stops the release.
- LocalQL treats a partially or fully published version as immutable: never top
  up or replace it, add another file, or redispatch publication.
- The public release branch, merged candidate, and immutable tag can each create
  a public-but-unreleased state. Report that state and resume the exact next safe
  transition or fix forward; never reset, delete, retarget, or hide it.
- After PyPI verification, separately approve updating the exact draft Release
  with verified PyPI filenames, hashes, links, publisher identity, receipt
  status, and the bounded cryptographic-verification statement. Read back its
  body SHA-256 before a later separate publication approval.
- Treat version tags as immutable: never retarget or reuse a version tag. If a
  tagged candidate is wrong, fix forward and issue a new patch version.
- Treat package versions as immutable: never replace a PyPI version. If an
  artifact is broken, stop promotion, make an explicit separately approved yank
  decision when warranted, and publish a corrected patch release.
- If publication succeeds but post-publish verification fails or times out, do
  not publish again. Retry only read-only metadata, digest, provenance, and
  installed-package verification against the already published version. Record
  whether publication was proven separately from the verification failure.
- If GitHub Release creation fails after the tag exists, keep the tag unchanged.
  After verifying the public tag and PyPI state, separately approve creation or
  repair of release metadata against that same immutable tag.
- Never delete a public or local release branch automatically. Branch cleanup is
  a separate decision after release state and recovery evidence are recorded.

## Post-release Reconciliation

After the public release is verified, separately approve a fetch and confirm the
fetched public `main` object. Replace both placeholder tokens below with the
exact recorded 40-character object IDs. Request separate approval for the fully
substituted three-argument `git update-ref` command, then run this whole block.
Its checks fail unless both IDs name commit objects, the refs still match, local
`main` is an ancestor of public `main`, and local `main` is not checked out in
any worktree:

```bash
set -euo pipefail
current_local_main_oid="CURRENT_LOCAL_MAIN_OID"
verified_public_main_oid="VERIFIED_PUBLIC_MAIN_OID"
oid_re='^[0-9a-f]{40}$'

[[ "${current_local_main_oid}" =~ ${oid_re} ]]
[[ "${verified_public_main_oid}" =~ ${oid_re} ]]
test "$(git cat-file -t "${current_local_main_oid}")" = "commit"
test "$(git cat-file -t "${verified_public_main_oid}")" = "commit"
test "$(git rev-parse --verify refs/heads/main)" = "${current_local_main_oid}"
test "$(git rev-parse --verify refs/remotes/origin/main)" = \
  "${verified_public_main_oid}"
git merge-base --is-ancestor "${current_local_main_oid}" \
  "${verified_public_main_oid}"
main_worktree_path="$(
  git for-each-ref --format='%(worktreepath)' refs/heads/main
)"
test -z "${main_worktree_path}"

git update-ref refs/heads/main \
  "${verified_public_main_oid}" \
  "${current_local_main_oid}"
test "$(git rev-parse --verify refs/heads/main)" = \
  "${verified_public_main_oid}"
```

Never infer or shorten the IDs. If any precondition fails, do not move local
`main`; investigate and request a new decision. After the block confirms local
`main` equals the fetched public `main`, run:

```bash
make git-safety-check
```

Report reconciliation independently from publication. Deleting local branches,
artifacts, environments, or evidence requires a later, separate cleanup decision.
