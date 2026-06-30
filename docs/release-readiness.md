# Release Readiness

CSVQL v0.7 adds repo-local proof that the package can be built and installed from a wheel.

## Run It

Run `uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness`.

This workflow verifies:

- `pyproject.toml`, `src/csvql/__init__.py`, and `csvql --version` agree
- `uv build --sdist --wheel` succeeds
- an isolated wheel install can run `csvql --version`
- the installed wheel can run a tiny `inspect` command

This does not publish anything and does not create a release candidate claim.
