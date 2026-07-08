status: DONE

files changed
- `.github/workflows/ci.yml`
- `tests/test_v1_polish_docs.py`

commit(s) created
- `d8bfe47` `ci: add three-os automated support gate`

tests run with pass/fail results
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_ci_workflow_collects_three_os_automated_support_gate -q`
  - expected red-phase result against restored Ubuntu-only workflow: `FAIL`
  - green-phase result after workflow replacement: `PASS`

self-review notes
- Kept the diff scoped to the requested workflow gate and its regression test.
- Preserved Ubuntu `3.11` and `3.12` while adding macOS and Windows on Python `3.12`.
- Added the baseline-truth commands and `shell: bash` exactly as required by the brief.
- Did not push, trigger hosted CI, or claim hosted CI output.

concerns, if any
- No hosted GitHub Actions run was performed in this task by design; proof production remains for a later approved push or workflow run.

fix follow-up: review finding for Ubuntu 3.11 guard

files changed
- `tests/test_v1_polish_docs.py`

what changed
- Strengthened `test_ci_workflow_collects_three_os_automated_support_gate` to assert the exact current matrix include rows for:
  - Ubuntu Python 3.11
  - Ubuntu Python 3.12
  - macOS Python 3.12
  - Windows Python 3.12
- Kept the existing broader OS and command assertions intact.

tests run with pass/fail results
- `env UV_CACHE_DIR=/private/tmp/uv-cache-csvql-localql uv run --all-extras pytest tests/test_v1_polish_docs.py::test_ci_workflow_collects_three_os_automated_support_gate -q`
  - expected result after fix: `PASS`
