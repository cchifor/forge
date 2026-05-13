"""Migration runner infrastructure."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MigrationReport:
    """Result of one migration pass."""

    name: str
    applied: bool
    changes: list[str] = field(default_factory=list)
    skipped_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "applied": self.applied,
            "changes": list(self.changes),
            "skipped_reason": self.skipped_reason,
        }


@dataclass(frozen=True)
class AvailableMigration:
    """Metadata for a codemod registered under ``forge.migrations``."""

    name: str
    from_version: str
    to_version: str
    description: str
    runner: Callable[[Path, bool, bool], MigrationReport]


def discover_migrations() -> list[AvailableMigration]:
    """Return every registered migration in application order."""
    # Import-side registrations — each migration module registers at import.
    from forge.migrations import (  # noqa: F401, PLC0415
        migrate_adapters,
        migrate_adopt_baseline,
        migrate_auth_keycloak_to_platform_auth,
        migrate_entities,
        migrate_layer_modes,
        migrate_provenance_v2,
        migrate_rename_options,
        migrate_ui_protocol,
    )

    return [
        AvailableMigration(
            name=migrate_ui_protocol.NAME,
            from_version=migrate_ui_protocol.FROM,
            to_version=migrate_ui_protocol.TO,
            description=migrate_ui_protocol.DESCRIPTION,
            runner=migrate_ui_protocol.run,
        ),
        AvailableMigration(
            name=migrate_entities.NAME,
            from_version=migrate_entities.FROM,
            to_version=migrate_entities.TO,
            description=migrate_entities.DESCRIPTION,
            runner=migrate_entities.run,
        ),
        AvailableMigration(
            name=migrate_adapters.NAME,
            from_version=migrate_adapters.FROM,
            to_version=migrate_adapters.TO,
            description=migrate_adapters.DESCRIPTION,
            runner=migrate_adapters.run,
        ),
        AvailableMigration(
            name=migrate_rename_options.NAME,
            from_version=migrate_rename_options.FROM,
            to_version=migrate_rename_options.TO,
            description=migrate_rename_options.DESCRIPTION,
            runner=migrate_rename_options.run,
        ),
        AvailableMigration(
            name=migrate_layer_modes.NAME,
            from_version=migrate_layer_modes.FROM,
            to_version=migrate_layer_modes.TO,
            description=migrate_layer_modes.DESCRIPTION,
            runner=migrate_layer_modes.run,
        ),
        # P0.1 (1.1.0-alpha.2): opt-in baseline adoption for projects
        # upgrading from pre-merge-mode forge. Order matters — runs after
        # rename-options so the canonical paths are already in place.
        AvailableMigration(
            name=migrate_adopt_baseline.NAME,
            from_version=migrate_adopt_baseline.FROM,
            to_version=migrate_adopt_baseline.TO,
            description=migrate_adopt_baseline.DESCRIPTION,
            runner=migrate_adopt_baseline.run,
        ),
        # 1.1.x → 1.2.0 (provenance schema v2): enrich pre-1.2 manifests
        # with fragment_version, fragment_name, template_versions, and
        # add fp:<hex8> fingerprints to BEGIN sentinels. Runs after
        # adopt-baseline so any newly-stamped records also get
        # version enrichment in this single pass.
        AvailableMigration(
            name=migrate_provenance_v2.NAME,
            from_version=migrate_provenance_v2.FROM,
            to_version=migrate_provenance_v2.TO,
            description=migrate_provenance_v2.DESCRIPTION,
            runner=migrate_provenance_v2.run,
        ),
        # 1.1 → 1.2 (auth-stack rebuild): swap legacy Keycloak-direct
        # for the platform-auth model. Order: runs LAST so prior
        # migrations have already brought the project to the 1.1
        # canonical baseline before this pass starts the auth swap.
        AvailableMigration(
            name=migrate_auth_keycloak_to_platform_auth.NAME,
            from_version=migrate_auth_keycloak_to_platform_auth.FROM,
            to_version=migrate_auth_keycloak_to_platform_auth.TO,
            description=migrate_auth_keycloak_to_platform_auth.DESCRIPTION,
            runner=migrate_auth_keycloak_to_platform_auth.run,
        ),
    ]


def apply_migrations(
    project_root: Path,
    *,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    dry_run: bool = False,
    quiet: bool = False,
) -> list[MigrationReport]:
    """Run every registered migration in order, honouring only/skip filters."""
    only_set = set(only) if only else None
    skip_set = set(skip) if skip else set()

    reports: list[MigrationReport] = []
    for m in discover_migrations():
        if only_set and m.name not in only_set:
            continue
        if m.name in skip_set:
            continue
        if not quiet:
            label = "[dry-run]" if dry_run else "[apply]"
            print(f"  {label} forge migrate-{m.name}: {m.description}")
        report = m.runner(project_root, dry_run, quiet)
        reports.append(report)
    return reports
