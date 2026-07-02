.PHONY: install format format-check lint typecheck test ci

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
