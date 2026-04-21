"""Tests for Epic G's option-alias + rename-codemod machinery."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.capability_resolver import _apply_option_defaults
from forge.errors import OPTIONS_UNKNOWN_PATH, OptionsError
from forge.options import (
    OPTION_ALIAS_INDEX,
    OPTION_REGISTRY,
    FeatureCategory,
    Option,
    OptionType,
    register_option,
    resolve_alias,
)


def _mk_opt(path: str, aliases: tuple[str, ...] = (), **extras: object) -> Option:
    return Option(
        path=path,
        type=OptionType.BOOL,
        default=False,
        summary=f"option {path}",
        description=f"option {path}",
        category=FeatureCategory.RELIABILITY,
        aliases=aliases,
        **extras,  # type: ignore[arg-type]
    )


@pytest.fixture
def isolated_registry() -> None:
    """Swap OPTION_REGISTRY + OPTION_ALIAS_INDEX for empty dicts per test."""
    with patch.dict(OPTION_REGISTRY, clear=True), patch.dict(
        OPTION_ALIAS_INDEX, clear=True
    ):
        yield


# ---------------------------------------------------------------------------
# Option.__post_init__ validation of aliases
# ---------------------------------------------------------------------------


class TestOptionAliasValidation:
    def test_valid_aliases_accepted(self) -> None:
        opt = _mk_opt("new.path", aliases=("old.path", "older.path"))
        assert opt.aliases == ("old.path", "older.path")

    def test_alias_equal_to_canonical_rejected(self) -> None:
        with pytest.raises(ValueError, match="equals the canonical path"):
            _mk_opt("foo.bar", aliases=("foo.bar",))

    def test_duplicate_aliases_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate entries in aliases"):
            _mk_opt("new.path", aliases=("old.path", "old.path"))

    def test_invalid_alias_path_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid option path"):
            _mk_opt("new.path", aliases=("bad path with spaces",))

    def test_deprecated_since_without_aliases_rejected(self) -> None:
        with pytest.raises(ValueError, match="deprecated_since set but no aliases"):
            _mk_opt("new.path", deprecated_since="1.1.0")

    def test_deprecated_since_with_aliases_accepted(self) -> None:
        opt = _mk_opt("new.path", aliases=("old.path",), deprecated_since="1.1.0")
        assert opt.deprecated_since == "1.1.0"


# ---------------------------------------------------------------------------
# register_option alias collision checks
# ---------------------------------------------------------------------------


class TestRegisterOptionAliasCollisions:
    def test_alias_collides_with_canonical_path_rejected(
        self, isolated_registry: None
    ) -> None:
        register_option(_mk_opt("already.there"))
        with pytest.raises(ValueError, match="already registered as a canonical"):
            register_option(_mk_opt("new.path", aliases=("already.there",)))

    def test_alias_collides_with_another_alias_rejected(
        self, isolated_registry: None
    ) -> None:
        register_option(_mk_opt("first.new", aliases=("shared.alias",)))
        with pytest.raises(ValueError, match="already aliased to"):
            register_option(_mk_opt("second.new", aliases=("shared.alias",)))

    def test_canonical_path_collides_with_existing_alias_rejected(
        self, isolated_registry: None
    ) -> None:
        register_option(_mk_opt("owner.path", aliases=("someone.else",)))
        with pytest.raises(ValueError, match="path collides with an existing alias"):
            register_option(_mk_opt("someone.else"))

    def test_alias_index_populated(self, isolated_registry: None) -> None:
        register_option(_mk_opt("new.name", aliases=("old.name", "older.name")))
        assert OPTION_ALIAS_INDEX["old.name"] == "new.name"
        assert OPTION_ALIAS_INDEX["older.name"] == "new.name"
        assert resolve_alias("old.name") == "new.name"
        assert resolve_alias("not.an.alias") is None


# ---------------------------------------------------------------------------
# Resolver rewrite + deprecation warning
# ---------------------------------------------------------------------------


class TestResolverAliasRewrite:
    def test_user_alias_path_rewritten_to_canonical(
        self, isolated_registry: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        register_option(_mk_opt("rag.backend_name", aliases=("rag.backend",)))

        with caplog.at_level(logging.WARNING, logger="forge.capability_resolver"):
            resolved = _apply_option_defaults({"rag.backend": True})

        # User set the old name; resolver moved the value to the canonical key.
        assert resolved["rag.backend_name"] is True
        # A deprecation warning fired pointing at the codemod.
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("deprecated alias" in w for w in warnings)
        assert any("migrate-rename-options" in w for w in warnings)

    def test_user_sets_both_alias_and_canonical_raises(
        self, isolated_registry: None
    ) -> None:
        register_option(_mk_opt("new.flag", aliases=("old.flag",)))

        with pytest.raises(OptionsError) as excinfo:
            _apply_option_defaults({"new.flag": True, "old.flag": False})

        assert excinfo.value.code == OPTIONS_UNKNOWN_PATH
        assert excinfo.value.context["alias"] == "old.flag"
        assert excinfo.value.context["canonical"] == "new.flag"

    def test_unknown_path_still_raises(self, isolated_registry: None) -> None:
        register_option(_mk_opt("known.option"))

        with pytest.raises(OptionsError) as excinfo:
            _apply_option_defaults({"completely.made.up": True})
        assert "Unknown option 'completely.made.up'" in excinfo.value.message


# ---------------------------------------------------------------------------
# migrate-rename-options codemod
# ---------------------------------------------------------------------------


class TestRenameCodemod:
    def _write_forge_toml(self, project_root: Path, options_table: str) -> None:
        (project_root / "forge.toml").write_text(
            "[forge]\n"
            'version = "1.0.0"\n'
            'project_name = "test"\n'
            "\n"
            f"[forge.options]\n{options_table}\n"
            "\n"
            "[forge.provenance]\n",
            encoding="utf-8",
        )

    def test_rewrites_aliased_keys(
        self, tmp_path: Path, isolated_registry: None
    ) -> None:
        from forge.migrations.migrate_rename_options import run

        register_option(_mk_opt("new.name", aliases=("old.name",)))
        self._write_forge_toml(tmp_path, '"old.name" = true')

        report = run(tmp_path, dry_run=False, quiet=True)

        assert report.applied
        assert len(report.changes) == 1
        assert "'old.name' → 'new.name'" in report.changes[0]

        body = (tmp_path / "forge.toml").read_text(encoding="utf-8")
        assert "new.name" in body
        assert "old.name" not in body

    def test_dry_run_leaves_forge_toml_unchanged(
        self, tmp_path: Path, isolated_registry: None
    ) -> None:
        from forge.migrations.migrate_rename_options import run

        register_option(_mk_opt("new.name", aliases=("old.name",)))
        self._write_forge_toml(tmp_path, '"old.name" = true')
        before = (tmp_path / "forge.toml").read_text(encoding="utf-8")

        report = run(tmp_path, dry_run=True, quiet=True)

        assert not report.applied
        assert len(report.changes) == 1
        after = (tmp_path / "forge.toml").read_text(encoding="utf-8")
        assert before == after

    def test_idempotent_second_run_is_noop(
        self, tmp_path: Path, isolated_registry: None
    ) -> None:
        from forge.migrations.migrate_rename_options import run

        register_option(_mk_opt("new.name", aliases=("old.name",)))
        self._write_forge_toml(tmp_path, '"old.name" = true')

        run(tmp_path, dry_run=False, quiet=True)
        second = run(tmp_path, dry_run=False, quiet=True)

        assert not second.applied
        assert second.skipped_reason == "No aliased option keys found in forge.toml"

    def test_skips_when_canonical_already_set(
        self, tmp_path: Path, isolated_registry: None
    ) -> None:
        from forge.migrations.migrate_rename_options import run

        register_option(_mk_opt("new.name", aliases=("old.name",)))
        # User set both — resolver would have raised, but codemod handles
        # gracefully by leaving both so the resolver surfaces the conflict.
        self._write_forge_toml(tmp_path, '"old.name" = true\n"new.name" = false')

        report = run(tmp_path, dry_run=False, quiet=True)

        # Nothing rewrote → no changes, skipped_reason gives the signal.
        assert report.skipped_reason == "No aliased option keys found in forge.toml"

    def test_missing_forge_toml(self, tmp_path: Path, isolated_registry: None) -> None:
        from forge.migrations.migrate_rename_options import run

        report = run(tmp_path, dry_run=False, quiet=True)
        assert not report.applied
        assert "No forge.toml" in report.skipped_reason

    def test_no_options_table(self, tmp_path: Path, isolated_registry: None) -> None:
        from forge.migrations.migrate_rename_options import run

        (tmp_path / "forge.toml").write_text(
            '[forge]\nversion = "1.0.0"\n', encoding="utf-8"
        )

        report = run(tmp_path, dry_run=False, quiet=True)
        assert not report.applied
        assert "no [forge.options]" in report.skipped_reason


# ---------------------------------------------------------------------------
# Migration discovery registration
# ---------------------------------------------------------------------------


def test_migrate_rename_options_is_discoverable() -> None:
    from forge.migrations.base import discover_migrations

    names = [m.name for m in discover_migrations()]
    assert "rename-options" in names
