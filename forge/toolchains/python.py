"""Python / FastAPI backend toolchain.

Verify dependencies, lint, formatting, types and tests. Generation canonicalizes
Python before recording ownership; verification must not mutate protected code.
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
                ["uv", "run", "ruff", "check", "src/", "tests/"],
                "Lint check",
                quiet=quiet,
            ),
            run_backend_cmd(
                backend_dir,
                ["uv", "run", "ruff", "format", "--check", "src/", "tests/"],
                "Format",
                quiet=quiet,
            ),
            run_backend_cmd(
                backend_dir, ["uv", "run", "ty", "check", "src/"], "Type check", quiet=quiet
            ),
            # Generation verifies unit tests without external services. The
            # native quality gate runs integration and E2E with their fixtures.
            run_backend_cmd(
                backend_dir,
                ["uv", "run", "pytest", "tests/unit", "-v", "-m", "not docker"],
                "Tests",
                quiet=quiet,
            ),
        ]
        return checks

    def post_generate(self, backend_dir: Path, *, quiet: bool = False) -> None:
        return None


PYTHON_TOOLCHAIN = PythonToolchain()
