"""Node.js / Fastify backend toolchain.

Install wraps ``npm install`` so the lockfile is baked into the Docker
image at build time. When the generated project ships a workspace root
(``<project>/package.json`` with ``workspaces``), we install at that
root with ``--workspaces --include-workspace-root`` so each workspace
member's ``prepare`` hook runs — that's how the in-tree SDKs (e.g.
``sdks/platform-auth-node``) get their ``dist/`` artifacts built before
the consumer's ``tsc --noEmit`` resolves their type declarations.

Verify mirrors the pre-Epic-S flow: ``biome check --write`` +
``tsc --noEmit`` + ``vitest run``, run inside the service dir.
"""

from __future__ import annotations

import json
from pathlib import Path

from forge.toolchains import Check
from forge.toolchains._runner import run_backend_cmd


def _find_npm_workspace_root(backend_dir: Path, *, max_levels: int = 4) -> Path | None:
    """Walk up from ``backend_dir`` looking for a ``package.json`` whose
    top-level ``workspaces`` field includes this backend.

    Bounds the walk to ``max_levels`` so a stray ``package.json`` deep
    in the parent tree (e.g. someone's home dir) can't redirect the
    install. Returns the workspace root path, or ``None`` if no
    matching workspace is found.
    """
    backend_dir = backend_dir.resolve()
    current = backend_dir.parent
    for _ in range(max_levels):
        candidate = current / "package.json"
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            else:
                if isinstance(data, dict) and data.get("workspaces"):
                    return current
        if current.parent == current:
            return None
        current = current.parent
    return None


class NodeToolchain:
    name = "node"

    def install(self, backend_dir: Path, *, quiet: bool = False) -> None:
        # When the generated project is an npm workspace, install at the
        # workspace root: --workspaces runs each member's install +
        # prepare hooks (so the SDK's tsc emits dist/ before this
        # service's tsc tries to resolve its types) and
        # --include-workspace-root installs the root's own devDependencies
        # if it ever declares any.
        workspace_root = _find_npm_workspace_root(backend_dir)
        if workspace_root is not None:
            run_backend_cmd(
                workspace_root,
                ["npm", "install", "--workspaces", "--include-workspace-root"],
                "Install dependencies",
                quiet=quiet,
                required=True,
            )
        else:
            # Standalone fallback for plugin-authored Node services
            # without a workspace root. The lockfile it produces is
            # baked into the Docker image at build time, so skipping it
            # would leave the generated project un-dockerable.
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
            # ``--passWithNoTests`` keeps the lane green on fresh-from-template
            # services that haven't authored any *.test.ts files yet. Vitest
            # 4.x exits 1 on an empty suite by default; the matrix verify lane
            # is checking that the toolchain itself works, not that tests
            # exist (the e2e + nightly smoke lanes assert real behavior).
            run_backend_cmd(
                backend_dir,
                ["npx", "vitest", "run", "--passWithNoTests"],
                "Tests",
                quiet=quiet,
            ),
        ]

    def post_generate(self, backend_dir: Path, *, quiet: bool = False) -> None:
        return None


NODE_TOOLCHAIN = NodeToolchain()
