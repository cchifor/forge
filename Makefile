.PHONY: install-dev test test-cov lint format typecheck check e2e fuzz \
        validate-matrix validate-matrix-quick validate-matrix-scenario \
        validate-matrix-list validate-matrix-e2e

install-dev:
	uv sync --all-extras --dev
	uv run pre-commit install

test:
	uv run pytest -m "not e2e and not fuzz"

test-cov:
	uv run pytest -m "not e2e and not fuzz" --cov-report=html

fuzz:
	uv run pytest -m fuzz -v

lint:
	uv run ruff check forge/

format:
	uv run ruff format forge/

typecheck:
	uv run ty check forge/

check: lint typecheck test

e2e:
	uv run pytest -m e2e -v

# --- Config-matrix validation (Epic S) --------------------------------------
# `validate-matrix` runs lane A (generate-only) across every scenario in
# `tests/matrix/scenarios.yaml`. Sprint 2 adds lane B (toolchain verify) and
# lane C (compose-up smoke); the LANE variable picks among them. See
# `tests/matrix/runner.py --help` for details.

validate-matrix:
	uv run python tests/matrix/runner.py --all --lane generate

validate-matrix-quick:
	@test -n "$(SCENARIO)" || (echo "Usage: make validate-matrix-quick SCENARIO=<name>"; exit 1)
	uv run python tests/matrix/runner.py --scenario $(SCENARIO) --lane generate

validate-matrix-scenario:
	@test -n "$(SCENARIO)" || (echo "Usage: make validate-matrix-scenario SCENARIO=<name> [LANE=generate|verify|smoke]"; exit 1)
	uv run python tests/matrix/runner.py --scenario $(SCENARIO) --lane $(or $(LANE),generate)

validate-matrix-list:
	uv run python tests/matrix/runner.py --list

validate-matrix-e2e:
	uv run python tests/matrix/runner.py --all --lane smoke
