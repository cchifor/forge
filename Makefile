.PHONY: install-dev test test-cov lint format typecheck check e2e

install-dev:
	uv sync --all-extras --dev
	uv run pre-commit install

test:
	uv run pytest -m "not e2e"

test-cov:
	uv run pytest -m "not e2e" --cov-report=html

lint:
	uv run ruff check forge/

format:
	uv run ruff format forge/

typecheck:
	uv run ty check forge/

check: lint typecheck test

e2e:
	uv run pytest -m e2e -v
