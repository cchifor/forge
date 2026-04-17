# Unix/macOS convenience wrapper — delegates to the cross-platform Python script.
# On Windows, run:  python sync_templates.py

.PHONY: sync-templates install-dev clean test test-cov lint format typecheck check e2e

sync-templates:
	python sync_templates.py

install-dev: sync-templates
	uv sync

clean:
	python sync_templates.py --clean

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
