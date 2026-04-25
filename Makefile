.PHONY: install-dev test test-fast test-serial test-cov lint format typecheck check e2e fuzz \
        snapshots validate-matrix validate-matrix-quick validate-matrix-scenario \
        validate-matrix-list validate-matrix-e2e

install-dev:
	uv sync --all-extras --dev
	uv run pre-commit install

test:
	uv run pytest -m "not e2e and not fuzz" -n auto

# Excludes golden snapshots (~6 min for 5 presets) for fast iteration.
# Keep `make test` as the full sign-off run before push.
test-fast:
	uv run pytest -m "not e2e and not fuzz and not golden_snapshot" -n auto

# Serial fallback for diagnosing xdist-induced flakes. If `make test`
# fails and `make test-serial` passes, the failure is a real
# parallel-isolation bug to fix in the test that owns it.
test-serial:
	uv run pytest -m "not e2e and not fuzz" -p no:xdist

test-cov:
	uv run pytest -m "not e2e and not fuzz" -n auto --cov-report=html

fuzz:
	uv run pytest -m fuzz -v

snapshots:
	# Snapshots are I/O-bound on Copier rendering. With only 5 tests,
	# `-n auto` saves no wall-clock and adds worker-spawn + disk-
	# contention overhead (~15s pessimization on Windows NTFS). Run
	# serially when iterating on the generator. The coverage CI cell
	# still gets parallelism by mixing snapshots with the rest of the
	# suite — workers there have plenty of other tests to chew through.
	uv run pytest -m golden_snapshot -v

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
