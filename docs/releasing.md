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
For the v1.0.2 candidate, run the entire block in Bash from the repository
root. The version, artifact Python, and intended publication date are fixed
inputs; changing any of them requires a new candidate commit and a complete
proof rerun:

```bash
set -euo pipefail
release_version="v1.0.2"
expected_version="1.0.2"
artifact_python="3.12.11"
test "${release_version}" = "v${expected_version}"
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
export UV_CACHE_DIR="${evidence_dir}/uv-cache"
export UV_TOOL_DIR="${evidence_dir}/uv-tools"
export UV_PYTHON_INSTALL_DIR="${evidence_dir}/uv-python"
mkdir -m 700 -- "${UV_CACHE_DIR}"
mkdir -m 700 -- "${UV_TOOL_DIR}"
mkdir -m 700 -- "${UV_PYTHON_INSTALL_DIR}"

make ci-fresh
uvx --from uv==0.11.28 uv build --python "${artifact_python}" \
  --sdist --wheel \
  --out-dir "${evidence_dir}/dist" \
  --build-constraints scripts/release-build-constraints.txt \
  --require-hashes
uvx --from uv==0.11.28 uv --version > "${evidence_dir}/uv-version.txt"
uvx --from uv==0.11.28 uv run --python "${artifact_python}" python --version > "${evidence_dir}/artifact-python-version.txt"
shasum -a 256 scripts/release-build-constraints.txt > "${evidence_dir}/release-build-constraints.sha256"

uv run --frozen --no-sync python scripts/audit_package_contents.py \
  "${evidence_dir}/dist" --expected-version "${expected_version}"

mkdir -- \
  "${evidence_dir}/rebuild-constrained" \
  "${evidence_dir}/rebuild-consumer"
uvx --from uv==0.11.28 uv build --verbose --wheel \
  "${evidence_dir}/dist/localql-1.0.2.tar.gz" \
  --python "${artifact_python}" \
  --out-dir "${evidence_dir}/rebuild-constrained" \
  --build-constraints scripts/release-build-constraints.txt \
  --require-hashes \
  2>&1 | tee "${evidence_dir}/rebuild-constrained.log"
grep -Eo 'hatchling==[0-9]+(\.[0-9]+)+' \
  "${evidence_dir}/rebuild-constrained.log" | sort -u \
  > "${evidence_dir}/rebuild-constrained-backend.txt"
test -s "${evidence_dir}/rebuild-constrained-backend.txt"

date -u +'%Y-%m-%dT%H:%M:%SZ' > "${evidence_dir}/consumer-rebuild-observed-at.txt"
uvx --from uv==0.11.28 uv build --verbose --wheel \
  "${evidence_dir}/dist/localql-1.0.2.tar.gz" \
  --python "${artifact_python}" \
  --out-dir "${evidence_dir}/rebuild-consumer" \
  2>&1 | tee "${evidence_dir}/rebuild-consumer.log"
grep -Eo 'hatchling==[0-9]+(\.[0-9]+)+' \
  "${evidence_dir}/rebuild-consumer.log" | sort -u \
  > "${evidence_dir}/rebuild-consumer-backend.txt"
test -s "${evidence_dir}/rebuild-consumer-backend.txt"

uv run --frozen --no-sync python scripts/verify_release_artifacts.py \
  "${evidence_dir}/dist" --expected-version "${expected_version}" \
  --rebuilt-wheel "${evidence_dir}/rebuild-constrained/localql-1.0.2-py3-none-any.whl" \
  --rebuilt-wheel "${evidence_dir}/rebuild-consumer/localql-1.0.2-py3-none-any.whl" \
  --manifest "${evidence_dir}/artifact-manifest.json"
uvx --from twine==6.2.0 twine check \
  "${evidence_dir}/dist/localql-1.0.2-py3-none-any.whl" \
  "${evidence_dir}/dist/localql-1.0.2.tar.gz"

uv run --frozen --no-sync python scripts/verify_dependency_audit.py \
  --evidence-dir "${evidence_dir}/dependency-audit"
uv run --frozen --no-sync python scripts/verify_installed_artifacts.py \
  --wheel "${evidence_dir}/dist/localql-1.0.2-py3-none-any.whl" \
  --core-requirements "${evidence_dir}/dependency-audit/core-requirements.txt" \
  --tui-requirements "${evidence_dir}/dependency-audit/tui-requirements.txt" \
  --work-dir "${evidence_dir}/installed-smokes" \
  --expected-version "${expected_version}" \
  --python "${artifact_python}" \
  > "${evidence_dir}/installed-smokes.json" \
  2> "${evidence_dir}/installed-smokes.log"

intended_publication_date="2026-07-15"
changelog_date="$(
  sed -n 's/^## \[1\.0\.2\] - \([0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}\)$/\1/p' \
    CHANGELOG.md
)"
test "${changelog_date}" = "${intended_publication_date}"
printf '%s\n' "${intended_publication_date}" \
  > "${evidence_dir}/intended-publication-date.txt"

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
inspect the artifact manifest and both package archives. The current intended
publication date is exactly `2026-07-15`. If the 1.0.2 heading in `CHANGELOG.md`
does not carry that date, stop, update it in a new candidate commit, and rerun
all proof. Do not derive or inject a date dynamically into artifacts that have
already been built. Record an adversarial review of release claims,
compatibility, known limitations, deferred work, and any skipped check. Evidence
must match the exact candidate commit and artifacts; stale evidence is invalid.

## Hosted Pull Request Readiness

After a separately approved public branch push and pull-request creation,
record the exact hosted-readiness identity in this field order:

```text
public_main_base_oid: <40-character lowercase commit OID>
candidate_head_oid: <40-character lowercase commit OID>
pull_request_number: <positive integer>
test_merge_oid: <40-character lowercase commit OID>
ci_workflow_id: <positive integer>
ci_run_id: <positive integer>
ci_run_attempt: <positive integer>
ci_check_suite_id: <positive integer>
ci_actions_integration_id: <positive integer>
expected_job_names:
  - test (ubuntu-latest, 3.11)
  - test (ubuntu-latest, 3.12)
  - test (ubuntu-latest, 3.13)
  - test (ubuntu-latest, 3.14)
  - test (macos-latest, 3.12)
  - test (windows-latest, 3.12)
```

Accept the run only when the workflow identity is `.github/workflows/ci.yml`,
the event is `pull_request`, and all six exact jobs completed successfully on
the recorded attempt. The CI run and check-suite head SHA must equal
candidate_head_oid; the recorded check suite must own all six exact check
runs through the recorded GitHub Actions integration ID.

Separately require `test_merge_oid` to be GitHub's current pull-request
test-merge commit derived from the recorded public_main_base_oid and
candidate_head_oid. The pull-request base and head, both ordered test-merge
parents, and the pull-request merge ref must agree with those recorded objects.
Every job's `Verify pull request test merge` step must succeed; that step binds
the checked-out commit and its ordered parents to the pull-request event even
though GitHub attaches the run and check suite to the candidate head SHA.

This is read-only evidence and does not authorize a branch update, pull request
update, merge, tag, publication, or any other hosted write. Any mismatch stops
readiness and requires a new evidence record rather than reinterpretation.

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
