"""Python / FastAPI backend toolchain.

Mirrors the pre-Epic-S ``generator._setup_backend`` behavior byte-for-
byte: ``uv sync`` + ``ruff --fix`` + ``ruff format`` + ``ty check`` +
``pytest``. The split between :meth:`install` (no-op) and :meth:`verify`
(everything) preserves how the generator drove it — everything ran
only when ``not quiet and not dry_run``.
"""

from __future__ import annotations

from pathlib import Path

from forge.toolchains import Check
from forge.toolchains._runner import run_backend_cmd


class PythonToolchain:
    name = "python"

    def install(self, backend_dir: Path, *, quiet: bool = False) -> None:
        # uv sync happens as part of verify() so it stays inside the
        # `not quiet` gate the generator used before the refactor;
        # splitting it out would make install() run in environments
        # where uv isn't available (e.g. early matrix lane-A generate
        # checks) and fail needlessly.
        return None

    def verify(self, backend_dir: Path, *, quiet: bool = False) -> list[Check]:
        checks: list[Check] = [
            run_backend_cmd(backend_dir, ["uv", "sync"], "Install dependencies", quiet=quiet),
            run_backend_cmd(
                backend_dir,
                ["uv", "run", "ruff", "check", "--fix", "src/", "tests/"],
                "Lint fix",
                quiet=quiet,
            ),
            run_backend_cmd(
                backend_dir,
                ["uv", "run", "ruff", "format", "src/", "tests/"],
                "Format",
                quiet=quiet,
            ),
            run_backend_cmd(
                backend_dir, ["uv", "run", "ty", "check", "src/"], "Type check", quiet=quiet
            ),
            # Skip ``-m docker`` — those tests use testcontainers to spin up
            # postgres / redis / etc. and need a vector-aware image plus
            # ``CREATE EXTENSION`` migrations. Matrix CI doesn't pre-pull
            # those images and the conftest's session-scoped fixtures fail
            # cascade-style. Docker-tagged tests run in the dedicated
            # nightly compose-up lane (``matrix-nightly.yml``) instead.
            run_backend_cmd(
                backend_dir,
                ["uv", "run", "pytest", "-v", "-m", "not docker"],
                "Tests",
                quiet=quiet,
            ),
        ]
        return checks

    def post_generate(self, backend_dir: Path, *, quiet: bool = False) -> None:
        return None


PYTHON_TOOLCHAIN = PythonToolchain()
