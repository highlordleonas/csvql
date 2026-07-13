.PHONY: install sync format format-check lint typecheck test ci ci-fresh git-safety-check install-git-safety

install:
	uv sync --all-extras

sync:
	uv sync --all-extras --frozen

format:
	uv run --frozen --no-sync ruff format .

format-check:
	uv run --frozen --no-sync ruff format --check .

lint:
	uv run --frozen --no-sync ruff check .

typecheck:
	uv run --frozen --no-sync --all-extras mypy src

test:
	uv run --frozen --no-sync --all-extras pytest

ci: format-check lint typecheck test

ci-fresh: sync
	$(MAKE) ci

git-safety-check:
	uv run --frozen --no-sync python -m scripts.install_git_safety check --repo .

install-git-safety:
	test "$(CONFIRM)" = "highlordleonas/csvql"
	uv run --frozen --no-sync python -m scripts.install_git_safety apply --repo . --confirm "$(CONFIRM)"
