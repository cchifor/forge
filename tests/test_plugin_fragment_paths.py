"""Tests for plugin-supplied absolute fragment paths (A4-3)."""

from __future__ import annotations

from pathlib import Path

from forge.feature_injector import FRAGMENTS_DIR, _resolve_fragment_dir


class TestResolveFragmentDir:
    def test_relative_path_resolves_under_fragments_dir(self) -> None:
        # Built-in fragment style — "rate_limit/python" under FRAGMENTS_DIR.
        resolved = _resolve_fragment_dir("rate_limit/python")
        assert resolved == FRAGMENTS_DIR / "rate_limit" / "python"

    def test_absolute_path_used_verbatim(self, tmp_path: Path) -> None:
        # Plugin style — the plugin ships fragments inside its own package
        # tree and hands forge an absolute path.
        plugin_fragment = tmp_path / "my_plugin" / "fragments" / "audit_log"
        plugin_fragment.mkdir(parents=True)
        resolved = _resolve_fragment_dir(str(plugin_fragment))
        assert resolved == plugin_fragment

    def test_absolute_path_on_windows_drive(self, tmp_path: Path) -> None:
        # Sanity: the resolution should not prepend FRAGMENTS_DIR to an
        # absolute path even on Windows where drive-letter prefixes apply.
        absolute = tmp_path.resolve()
        resolved = _resolve_fragment_dir(str(absolute))
        assert resolved == absolute
        assert not str(resolved).startswith(str(FRAGMENTS_DIR))


class TestPluginFragmentE2E:
    def test_absolute_fragment_applies_via_apply_fragment(self, tmp_path: Path) -> None:
        """Smoke test: a plugin-style fragment dir on an absolute path
        is handled by _apply_fragment via the resolver."""
        from forge.config import BackendConfig, BackendLanguage
        from forge.feature_injector import _apply_fragment
        from forge.fragments import FragmentImplSpec

        # Set up a plugin fragment dir outside FRAGMENTS_DIR.
        plugin_frag = tmp_path / "plugin_pkg" / "my_fragment" / "python"
        files_dir = plugin_frag / "files"
        files_dir.mkdir(parents=True)
        (files_dir / "hello.py").write_text("# from plugin\n", encoding="utf-8")

        backend_dir = tmp_path / "generated" / "services" / "api"
        backend_dir.mkdir(parents=True)

        impl = FragmentImplSpec(fragment_dir=str(plugin_frag))
        bc = BackendConfig(
            name="api", project_name="demo", language=BackendLanguage.PYTHON
        )
        _apply_fragment(bc, backend_dir, impl, {}, "my_plugin_fragment")

        assert (backend_dir / "hello.py").is_file()
        assert "from plugin" in (backend_dir / "hello.py").read_text(encoding="utf-8")
