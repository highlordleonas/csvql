## Task 6 Fix Report

- Repo: `/Users/richarddemke/Documents/csvql`
- Branch: `main`
- Base HEAD before fix: `ba9e0e51d46551e82e1b0ed7ea4719c687267060`

### Scope

Minimal docs-only fix in `docs/tui-qol-qa.md` to restore the exact guard phrase
`screenshots are not required for those OS rows` in the historical evidence
section while preserving the updated historical-proof wording and release-proof
contract.

### Change Made

- Rejoined the sentence in `docs/tui-qol-qa.md` so the exact guard phrase
  appears contiguously in the relevant historical evidence bullet.

### Verification

1. `UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_tui_qol_docs_record_scope_closeout_without_release_eligibility -q`
   - Result: `1 passed in 0.03s`
2. `UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py -q`
   - Result: `22 passed in 0.05s`

### Boundaries Kept

- No runtime source, CI, tests, package metadata, or lockfiles edited.
- No push, tag, publish, release creation, artifact upload, version change, or
  `v1-stable` claim.
