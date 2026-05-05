"""Node.js / Fastify backend toolchain.

Wraps the pre-Epic-S flow: ``npm install`` (required, always runs so
Docker gets a lockfile) followed by ``biome check`` + ``tsc --noEmit`` +
``vitest run`` verification when not quiet.
"""

from __future__ import annotations

from pathlib import Path

from forge.toolchains import Check
from forge.toolchains._runner import run_backend_cmd


class NodeToolchain:
    name = "node"

    def install(self, backend_dir: Path, *, quiet: bool = False) -> None:
        # npm install is mandatory — the lockfile it produces is baked
        # into the Docker image at build time, so skipping it would
        # leave the generated project un-dockerable. Marked required=True
        # so a missing npm surfaces immediately rather than silently.
        run_backend_cmd(
            backend_dir,
            ["npm", "install"],
            "Install dependencies",
            quiet=quiet,
            required=True,
        )
        # Generate the Prisma client; without this, ``tsc --noEmit`` can't
        # resolve ``Item`` / ``Prisma.<Model>WhereInput`` types and fails
        # with TS2305 / TS2694. ``prisma generate`` is idempotent so it's
        # safe to re-invoke on every install.
        if (backend_dir / "prisma" / "schema.prisma").exists():
            run_backend_cmd(
                backend_dir,
                ["npx", "prisma", "generate"],
                "Generate Prisma client",
                quiet=quiet,
            )

    def verify(self, backend_dir: Path, *, quiet: bool = False) -> list[Check]:
        # ``biome check --write`` mirrors the python toolchain's ``ruff check
        # --fix`` — fix what biome can fix (organize imports, formatting,
        # safe lint suggestions), surface the rest as errors. Without
        # ``--write`` every newly-emitted file fails CI on import-order
        # diff alone, which is mechanical noise.
        return [
            run_backend_cmd(
                backend_dir,
                ["npx", "biome", "check", "--write", "src/"],
                "Lint check",
                quiet=quiet,
            ),
            run_backend_cmd(backend_dir, ["npx", "tsc", "--noEmit"], "Type check", quiet=quiet),
            run_backend_cmd(backend_dir, ["npx", "vitest", "run"], "Tests", quiet=quiet),
        ]

    def post_generate(self, backend_dir: Path, *, quiet: bool = False) -> None:
        return None


NODE_TOOLCHAIN = NodeToolchain()
