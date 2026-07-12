.PHONY: install sync format format-check lint typecheck test ci ci-fresh

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
