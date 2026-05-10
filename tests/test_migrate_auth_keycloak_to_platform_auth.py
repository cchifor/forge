"""Behavioural tests for the auth-keycloak-to-platform-auth codemod (Phase 10).

The codemod is the atomic ship-it bundle for the 1.1 → 1.2 cutover.
These tests build a synthetic legacy project tree in a tempdir, run
the codemod, and assert the right files were rewritten / removed /
added with the right env-var renames.

Cross-reference: implementation plan at
``~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md``
(Phase 10 deliverables); user-facing migration playbook at
``UPGRADING.md`` §"1.1 → 1.2 — auth-stack rebuild".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.migrations.base import discover_migrations
from forge.migrations.migrate_auth_keycloak_to_platform_auth import (
    DESCRIPTION,
    ENV_ADDITIONS,
    ENV_REMOVALS,
    ENV_RENAMES,
    FROM,
    LEGACY_PYTHON_DEPS,
    LEGACY_PYTHON_FILES,
    NAME,
    TO,
    run,
)


# ---------------------------------------------------------------- registration


def test_codemod_registered_in_discover() -> None:
    """The codemod is reachable via ``forge --migrate <NAME>``.

    Without this, the codemod is dead code regardless of its
    behaviour. Pin via discover_migrations() — that's the function
    the CLI calls.
    """
    migrations = {m.name: m for m in discover_migrations()}
    assert NAME in migrations, (
        f"codemod {NAME!r} not in discover_migrations() — CLI can't reach it"
    )
    entry = migrations[NAME]
    assert entry.from_version == FROM
    assert entry.to_version == TO
    assert entry.description == DESCRIPTION


def test_codemod_runs_after_baseline_adoption() -> None:
    """Order matters: the auth codemod must run AFTER
    ``migrate_adopt_baseline`` so prior migrations have brought the
    project to the 1.1 canonical baseline first."""
    order = [m.name for m in discover_migrations()]
    assert "adopt-baseline" in order, "adopt-baseline must be registered"
    assert NAME in order
    assert order.index(NAME) > order.index("adopt-baseline"), (
        "auth-keycloak-to-platform-auth must run after adopt-baseline"
    )


# ---------------------------------------------------------------- detection


def test_codemod_skips_when_no_legacy_signals(tmp_path: Path) -> None:
    """A clean project with no legacy auth artifacts is a no-op."""
    # Empty project — nothing to migrate.
    report = run(tmp_path, dry_run=False, quiet=True)
    assert not report.applied
    assert report.skipped_reason is not None
    assert "no legacy" in report.skipped_reason.lower()


def test_codemod_skips_when_already_migrated(tmp_path: Path) -> None:
    """Re-running on a post-migrated project is idempotent."""
    # Drop a marker that the SDK fragment already shipped.
    (tmp_path / "sdks" / "platform-auth").mkdir(parents=True)
    (tmp_path / "sdks" / "platform-auth" / "pyproject.toml").write_text(
        '[project]\nname = "platform-auth"\n', encoding="utf-8"
    )
    report = run(tmp_path, dry_run=False, quiet=True)
    assert not report.applied
    assert "already applied" in (report.skipped_reason or "")


# ---------------------------------------------------------------- env vars


def test_env_renames_load_bearing_keys() -> None:
    """The rename table must cover the load-bearing renames.

    Adding new renames is fine; removing one would silently leave
    old env keys in place post-migration.
    """
    rename_dict = dict(ENV_RENAMES)
    must_rename = {
        "APP__SECURITY__AUTH__SERVER_URL": "GATEKEEPER_ISSUER",
        "KEYCLOAK_CLIENT_ID": "GATEKEEPER_CLIENT_ID",
        "KEYCLOAK_CLIENT_SECRET": "GATEKEEPER_CLIENT_SECRET",
    }
    for old, new in must_rename.items():
        assert rename_dict.get(old) == new, (
            f"ENV_RENAMES must rename {old} → {new}"
        )


def test_env_removals_drop_obsolete_keys() -> None:
    """Keys that no longer have an owner must be in ENV_REMOVALS."""
    must_remove = {"KEYCLOAK_REALM", "APP__SECURITY__AUTH__REALM"}
    missing = must_remove - set(ENV_REMOVALS)
    assert not missing, f"ENV_REMOVALS missing: {sorted(missing)}"


def test_env_additions_include_session_and_signing_config() -> None:
    """The new SESSION_* / KEY_* / INTERNAL_TOKEN_* / SERVICE_REGISTRY
    env vars must be added with safe defaults."""
    addition_keys = {key for key, _, _ in ENV_ADDITIONS}
    must_add = {
        "INTERNAL_TOKEN_AUDIENCE",
        "DEFAULT_IDLE_TIMEOUT_SECONDS",
        "DEFAULT_ABSOLUTE_TIMEOUT_SECONDS",
        "SESSION_WARN_AT_SECONDS",
        "KEY_BACKEND",
        "SIGNING_KEY_DIR",
        "SERVICE_REGISTRY_PATH",
        "SVC_AUTH_BACKEND",
        "SESSION_TIMEOUT_ENABLED",
    }
    missing = must_add - addition_keys
    assert not missing, f"ENV_ADDITIONS missing: {sorted(missing)}"


def _legacy_env_text() -> str:
    return (
        "# Comment line\n"
        "DATABASE_URL=postgres://x\n"
        "KEYCLOAK_CLIENT_ID=multi-tenant-gateway\n"
        "KEYCLOAK_CLIENT_SECRET=secret-value\n"
        "KEYCLOAK_REALM=app\n"
        "APP__SECURITY__AUTH__SERVER_URL=http://keycloak:8080\n"
        "APP__SECURITY__AUTH__REALM=app\n"
        "OTHER_VAR=keep-me\n"
    )


def test_env_renames_applied_to_dot_env(tmp_path: Path) -> None:
    """Running on a project with a .env containing legacy keys
    rewrites them in place."""
    env_path = tmp_path / ".env"
    env_path.write_text(_legacy_env_text(), encoding="utf-8")

    report = run(tmp_path, dry_run=False, quiet=True)
    assert report.applied

    new_text = env_path.read_text(encoding="utf-8")
    # Renames.
    assert "GATEKEEPER_CLIENT_ID=multi-tenant-gateway" in new_text
    assert "GATEKEEPER_CLIENT_SECRET=secret-value" in new_text
    assert "GATEKEEPER_ISSUER=http://keycloak:8080" in new_text
    assert "KEYCLOAK_CLIENT_ID=" not in new_text  # gone
    assert "APP__SECURITY__AUTH__SERVER_URL=" not in new_text
    # Removals.
    assert "KEYCLOAK_REALM=" not in new_text
    assert "APP__SECURITY__AUTH__REALM=" not in new_text
    # Untouched.
    assert "DATABASE_URL=postgres://x" in new_text
    assert "OTHER_VAR=keep-me" in new_text
    # Comment preserved.
    assert "# Comment line" in new_text
    # Additions appended.
    for key, default, _ in ENV_ADDITIONS:
        assert f"{key}={default}" in new_text, f"missing addition: {key}"

    # Report mentions every rename + removal + addition.
    rename_changes = [c for c in report.changes if "renamed" in c]
    drop_changes = [c for c in report.changes if "dropped" in c]
    add_changes = [c for c in report.changes if "added" in c]
    assert len(rename_changes) >= 3
    assert len(drop_changes) >= 2
    assert len(add_changes) >= len(ENV_ADDITIONS)


def test_env_dry_run_does_not_modify(tmp_path: Path) -> None:
    """``dry_run=True`` reports changes without writing."""
    env_path = tmp_path / ".env"
    legacy = _legacy_env_text()
    env_path.write_text(legacy, encoding="utf-8")

    report = run(tmp_path, dry_run=True, quiet=True)
    # Report says applied=False under dry-run AND lists the changes
    # the caller would otherwise see.
    assert not report.applied, "dry_run must report applied=False"
    assert len(report.changes) > 0, "dry_run must still list intended changes"
    # File is byte-for-byte unchanged.
    assert env_path.read_text(encoding="utf-8") == legacy


def test_env_addition_does_not_overwrite_existing(tmp_path: Path) -> None:
    """If the user already set an addition's key, don't overwrite."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "KEYCLOAK_CLIENT_ID=old-value\nINTERNAL_TOKEN_AUDIENCE=my-custom-aud\n",
        encoding="utf-8",
    )
    run(tmp_path, dry_run=False, quiet=True)
    new_text = env_path.read_text(encoding="utf-8")
    # User's customization preserved.
    assert "INTERNAL_TOKEN_AUDIENCE=my-custom-aud" in new_text
    # The codemod's default value not duplicated.
    assert new_text.count("INTERNAL_TOKEN_AUDIENCE=") == 1


def test_env_rename_skips_when_canonical_already_set(tmp_path: Path) -> None:
    """If both old and new keys are present, the codemod drops the
    old without overwriting the new (user already migrated this key
    by hand)."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "KEYCLOAK_CLIENT_ID=legacy\nGATEKEEPER_CLIENT_ID=already-set\n",
        encoding="utf-8",
    )
    report = run(tmp_path, dry_run=False, quiet=True)
    assert report.applied
    new_text = env_path.read_text(encoding="utf-8")
    assert "KEYCLOAK_CLIENT_ID=" not in new_text
    assert "GATEKEEPER_CLIENT_ID=already-set" in new_text
    drop_msg = next(
        (c for c in report.changes if "dropped" in c and "canonical" in c),
        None,
    )
    assert drop_msg is not None, (
        "codemod should report dropping the alias when canonical is set"
    )


# ---------------------------------------------------------------- python deps


def test_legacy_python_deps_includes_keycloak() -> None:
    """python-keycloak is the load-bearing legacy dep that must be removed.
    Adding others is fine; removing this one would leave the dep tree
    polluted post-migration."""
    assert "python-keycloak" in LEGACY_PYTHON_DEPS


def test_python_keycloak_dep_stripped(tmp_path: Path) -> None:
    """A Python service's pyproject.toml has python-keycloak removed."""
    services = tmp_path / "services"
    svc = services / "myservice"
    svc.mkdir(parents=True)
    pyproject = svc / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'name = "myservice"\n'
        'dependencies = [\n'
        '    "fastapi>=0.115",\n'
        '    "python-keycloak>=5.0",\n'
        '    "httpx>=0.27",\n'
        ']\n',
        encoding="utf-8",
    )
    # Also drop a marker .env so detection fires.
    (tmp_path / ".env").write_text(
        "KEYCLOAK_CLIENT_ID=foo\n", encoding="utf-8"
    )
    report = run(tmp_path, dry_run=False, quiet=True)
    assert report.applied
    new_text = pyproject.read_text(encoding="utf-8")
    assert "python-keycloak" not in new_text
    assert "fastapi" in new_text  # other deps untouched
    assert "httpx" in new_text


# ---------------------------------------------------------------- legacy files


def test_legacy_python_files_removed(tmp_path: Path) -> None:
    """The legacy provider modules are deleted so the new
    platform_auth_python_middleware fragment can ship its replacements
    without a name collision."""
    services = tmp_path / "services"
    svc = services / "myservice"
    providers = svc / "src" / "service" / "security" / "providers"
    providers.mkdir(parents=True)
    (providers / "keycloak.py").write_text("# legacy\n", encoding="utf-8")
    (providers / "dev.py").write_text("# legacy\n", encoding="utf-8")
    # Trigger detection.
    (tmp_path / ".env").write_text(
        "KEYCLOAK_CLIENT_ID=foo\n", encoding="utf-8"
    )

    report = run(tmp_path, dry_run=False, quiet=True)
    assert report.applied
    assert not (providers / "keycloak.py").exists()
    assert not (providers / "dev.py").exists()
    # The empty providers/ directory itself is also removed.
    assert not providers.exists()


def test_legacy_python_files_paths_match_constant() -> None:
    """LEGACY_PYTHON_FILES must include both keycloak.py and dev.py."""
    expected = {
        "src/service/security/providers/keycloak.py",
        "src/service/security/providers/dev.py",
    }
    actual = set(LEGACY_PYTHON_FILES)
    assert expected.issubset(actual), (
        f"LEGACY_PYTHON_FILES missing: {sorted(expected - actual)}"
    )


# ---------------------------------------------------------------- end-to-end


def test_full_migration_flow(tmp_path: Path) -> None:
    """End-to-end sanity check on a synthetic legacy project tree.

    Builds a project that has all three legacy signals (env, dep,
    provider file), runs the codemod, asserts every signal cleared.
    """
    # 1. Legacy env.
    (tmp_path / ".env").write_text(
        _legacy_env_text(), encoding="utf-8"
    )
    # 2. Legacy Python service with python-keycloak dep + provider file.
    services = tmp_path / "services"
    svc = services / "api"
    svc.mkdir(parents=True)
    (svc / "pyproject.toml").write_text(
        '[project]\n'
        'name = "api"\n'
        'dependencies = ["python-keycloak>=5.0"]\n',
        encoding="utf-8",
    )
    providers = svc / "src" / "service" / "security" / "providers"
    providers.mkdir(parents=True)
    (providers / "keycloak.py").write_text("# legacy\n", encoding="utf-8")

    # Run the codemod.
    report = run(tmp_path, dry_run=False, quiet=True)
    assert report.applied
    assert report.changes, "codemod must report at least one change"

    # All three signals cleared.
    new_env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "KEYCLOAK_CLIENT_ID=" not in new_env
    assert "GATEKEEPER_CLIENT_ID=" in new_env

    new_pyproject = (svc / "pyproject.toml").read_text(encoding="utf-8")
    assert "python-keycloak" not in new_pyproject

    assert not (providers / "keycloak.py").exists()

    # Re-running is a no-op (idempotent).
    second = run(tmp_path, dry_run=False, quiet=True)
    # Either skipped (no legacy detected post-migration) OR applied
    # with zero changes — both are valid idempotent outcomes.
    assert not second.applied or len(second.changes) == 0, (
        f"second run should be idempotent; got applied={second.applied} "
        f"changes={second.changes}"
    )
