"""Rust / Axum backend toolchain.

Mirrors the pre-Epic-S ``generator._setup_rust_backend`` flow: ``cargo
build`` + ``cargo fmt --check`` + ``cargo clippy -D warnings`` +
``cargo test``. Install is a no-op because cargo resolves dependencies
during ``build``; there's no separate lockfile-only step needed.
"""

from __future__ import annotations

from pathlib import Path

from forge.toolchains import Check
from forge.toolchains._runner import run_backend_cmd


class RustToolchain:
    name = "rust"

    def install(self, backend_dir: Path, *, quiet: bool = False) -> None:
        return None

    def verify(self, backend_dir: Path, *, quiet: bool = False) -> list[Check]:
        return [
            run_backend_cmd(backend_dir, ["cargo", "build"], "Build", quiet=quiet),
            run_backend_cmd(
                backend_dir, ["cargo", "fmt", "--check"], "Format check", quiet=quiet
            ),
            run_backend_cmd(
                backend_dir,
                ["cargo", "clippy", "--all-targets", "--", "-D", "warnings"],
                "Lint",
                quiet=quiet,
            ),
            run_backend_cmd(backend_dir, ["cargo", "test"], "Tests", quiet=quiet),
        ]

    def post_generate(self, backend_dir: Path, *, quiet: bool = False) -> None:
        return None


RUST_TOOLCHAIN = RustToolchain()
