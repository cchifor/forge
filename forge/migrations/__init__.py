"""Codemods for upgrading forge-generated projects between alpha versions.

Each migration is a module under ``forge.migrations`` exposing:

    def run(project_root: Path, *, dry_run: bool = False, quiet: bool = False) -> MigrationReport
    NAME: str   # short identifier, e.g. "ui-protocol"
    FROM: str   # source version / revision tag
    TO: str     # target version
    DESCRIPTION: str

``forge migrate`` (umbrella) walks the registered migrations in
dependency order and applies the ones that haven't run yet, gated by
the ``forge.version`` recorded in ``forge.toml``.

See ``docs/rfcs/RFC-002-breaking-change-contract.md`` for the contract
every migration must satisfy (idempotent, reversible via git, verbose
by default, ``--dry-run`` supported).
"""

from forge.migrations.base import (
    AvailableMigration,
    MigrationReport,
    apply_migrations,
    discover_migrations,
)

__all__ = [
    "AvailableMigration",
    "MigrationReport",
    "apply_migrations",
    "discover_migrations",
]
