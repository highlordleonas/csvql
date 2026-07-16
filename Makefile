.PHONY: install format format-check lint typecheck test ci public-release-audit

install:
	uv sync --all-extras

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

typecheck:
	uv run --all-extras mypy src

test:
	uv run --all-extras pytest

ci: format-check lint typecheck test

public-release-audit:
	@set -eu; \
	test -n "$(PUBLIC_REPOSITORY)" || { echo "PUBLIC_REPOSITORY is required" >&2; exit 2; }; \
	test -n "$(PUBLIC_BASE)" || { echo "PUBLIC_BASE is required" >&2; exit 2; }; \
	test -n "$(PUBLIC_AUTHOR_NAME)" || { echo "PUBLIC_AUTHOR_NAME is required" >&2; exit 2; }; \
	test -n "$(PUBLIC_AUTHOR_EMAIL)" || { echo "PUBLIC_AUTHOR_EMAIL is required" >&2; exit 2; }; \
	uv run --frozen --no-sync python scripts/audit_public_release.py \
		--repo . \
		--expected-repository "$(PUBLIC_REPOSITORY)" \
		--base "$(PUBLIC_BASE)" \
		--candidate HEAD \
		--expected-author-name "$(PUBLIC_AUTHOR_NAME)" \
		--expected-author-email "$(PUBLIC_AUTHOR_EMAIL)" \
		--require-clean-worktree
