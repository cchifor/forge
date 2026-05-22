"""Tests for the pluggable ApplierRegistry (Pillar A.1).

The registry replaces the hardcoded ``if/elif`` suffix dispatch that
used to live at ``forge/appliers/injection.py:236-256``. These tests
cover:

* Built-in injectors resolve by suffix (``.py`` / ``.pyi`` → Python,
  ``.ts`` / ``.tsx`` / ``.js`` / ``.jsx`` / ``.mjs`` / ``.cjs`` → TS).
* Plugin-registered suffixes resolve correctly
  (``register_injector(".go", ...)`` → ``lookup_injector("foo.go")``).
* Wildcard fallback covers unknown suffixes (``.xyz`` →
  sentinel-based text injector).
* :meth:`ForgeAPI.add_injector` round-trips: plugin registers, the
  applier picks the plugin's injector when dispatching to the
  matching suffix.

The registry is module-level and mutated globally; every test that
registers a new suffix snapshots + restores via the ``_isolate_registry``
autouse fixture so the order tests run in doesn't matter.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.api import ForgeAPI, PluginRegistration
from forge.appliers.injection import _dispatch_injector
from forge.errors import PluginError
from forge.injectors._registry import (
    _REGISTRY,
    WILDCARD_SUFFIX,
    _inject_python_adapter,
    _inject_text_adapter,
    _inject_ts_adapter,
    _registry_snapshot,
    lookup_injector,
    register_injector,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Snapshot + restore the per-suffix injector registry around a test.

    Tests below mutate ``_REGISTRY`` (the module-level dict) directly
    via :func:`register_injector` or via :meth:`ForgeAPI.add_injector`.
    Without isolation, a test that registers ``".go"`` leaks the entry
    into the next test, which would break the
    ``test_unknown_suffix_falls_back_to_wildcard`` assertion that
    ``.xyz`` resolves to the text fallback (because by then ``.go``
    is registered and ``.xyz`` still falls back, but the snapshot
    of "built-ins only" no longer holds).
    """
    saved = _registry_snapshot()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)


class TestBuiltinResolution:
    """Built-in suffixes match the pre-registry hardcoded dispatch."""

    @pytest.mark.parametrize("suffix", [".py", ".pyi"])
    def test_python_suffixes_resolve_to_python_adapter(self, suffix: str) -> None:
        injector = lookup_injector(f"foo{suffix}")
        assert injector is _inject_python_adapter

    @pytest.mark.parametrize("suffix", [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"])
    def test_ts_family_resolves_to_ts_adapter(self, suffix: str) -> None:
        injector = lookup_injector(f"foo{suffix}")
        assert injector is _inject_ts_adapter

    @pytest.mark.parametrize("filename", ["foo.PY", "Foo.Ts", "BAR.JSX"])
    def test_lookup_is_case_insensitive(self, filename: str) -> None:
        """Plugins on case-insensitive filesystems (macOS, Windows) might
        ship template files with mixed-case suffixes; the lookup must
        not care."""
        injector = lookup_injector(filename)
        assert injector is not _inject_text_adapter
        assert injector is not None

    def test_lookup_accepts_path_object(self) -> None:
        """``lookup_injector`` accepts ``str | Path`` — both must work
        identically for the applier call site."""
        from_str = lookup_injector("foo.py")
        from_path = lookup_injector(Path("subdir") / "foo.py")
        assert from_str is from_path is _inject_python_adapter


class TestWildcardFallback:
    """Unknown suffixes route to the seeded wildcard text injector."""

    @pytest.mark.parametrize("filename", ["foo.xyz", "foo.rs", "foo.toml", "noext"])
    def test_unknown_suffix_falls_back_to_wildcard(self, filename: str) -> None:
        assert lookup_injector(filename) is _inject_text_adapter

    def test_wildcard_can_be_overridden(self) -> None:
        """Plugins that want a smarter catch-all can register ``"*"``;
        last-write wins."""
        called: list[Path] = []

        def fancy_text_injector(
            file: Path,
            feature_key: str,
            marker: str,
            snippet: str,
            position: str,
        ) -> None:
            called.append(file)

        register_injector(WILDCARD_SUFFIX, fancy_text_injector)
        assert lookup_injector("foo.unknown") is fancy_text_injector

    def test_lookup_returns_none_when_wildcard_purged(self) -> None:
        """``lookup_injector`` is documented to return ``None`` if the
        wildcard has been removed. Verify the contract — even though
        production code never removes the entry."""
        _REGISTRY.pop(WILDCARD_SUFFIX)
        assert lookup_injector("foo.unknown") is None


class TestRegisterInjector:
    """Direct ``register_injector`` calls (the low-level API plugins use
    indirectly via :meth:`ForgeAPI.add_injector`)."""

    def test_register_then_lookup_roundtrip(self) -> None:
        def go_injector(
            file: Path,
            feature_key: str,
            marker: str,
            snippet: str,
            position: str,
        ) -> None:
            pass

        register_injector(".go", go_injector)
        assert lookup_injector("foo.go") is go_injector
        # Unrelated suffixes still resolve to their built-ins.
        assert lookup_injector("foo.py") is _inject_python_adapter

    def test_register_is_case_insensitive(self) -> None:
        """``register_injector('.GO', ...)`` is stored as ``.go`` so both
        ``foo.GO`` and ``foo.go`` resolve."""

        def go_injector(
            file: Path,
            feature_key: str,
            marker: str,
            snippet: str,
            position: str,
        ) -> None:
            pass

        register_injector(".GO", go_injector)
        assert lookup_injector("foo.go") is go_injector
        assert lookup_injector("foo.GO") is go_injector

    def test_register_overrides_existing_suffix(self) -> None:
        """Last-write wins — a plugin can override a built-in."""

        def wrapped_python(
            file: Path,
            feature_key: str,
            marker: str,
            snippet: str,
            position: str,
        ) -> None:
            pass

        register_injector(".py", wrapped_python)
        assert lookup_injector("foo.py") is wrapped_python

    @pytest.mark.parametrize(
        "bad_suffix",
        [
            "",
            "go",  # missing dot
            ".go bar",  # whitespace
            "./go",  # path separator
            ".g\\o",  # backslash
        ],
    )
    def test_register_rejects_invalid_suffix(self, bad_suffix: str) -> None:
        def noop(
            file: Path,
            feature_key: str,
            marker: str,
            snippet: str,
            position: str,
        ) -> None:
            pass

        with pytest.raises(ValueError):
            register_injector(bad_suffix, noop)

    def test_register_rejects_non_callable_injector(self) -> None:
        with pytest.raises(ValueError):
            register_injector(".go", "not-a-callable")  # type: ignore[arg-type]


class TestForgeAPIAddInjector:
    """``ForgeAPI.add_injector`` (the public plugin SDK surface, SDK 1.2)."""

    def _api(self, name: str = "test_plugin") -> ForgeAPI:
        return ForgeAPI(PluginRegistration(name=name, module="test"))

    def test_add_injector_registers_in_registry(self) -> None:
        api = self._api()

        def kotlin_injector(
            file: Path,
            feature_key: str,
            marker: str,
            snippet: str,
            position: str,
        ) -> None:
            pass

        api.add_injector(".kt", kotlin_injector)
        assert lookup_injector("foo.kt") is kotlin_injector

    def test_add_injector_wraps_value_errors_in_plugin_error(self) -> None:
        """Invalid suffixes coming from a plugin must surface as
        ``PluginError`` (plugin-coded) rather than a bare ``ValueError``
        — keeps the error envelope consistent with the rest of the
        plugin surface."""
        api = self._api(name="naughty_plugin")

        def noop(
            file: Path,
            feature_key: str,
            marker: str,
            snippet: str,
            position: str,
        ) -> None:
            pass

        with pytest.raises(PluginError) as excinfo:
            api.add_injector("go", noop)  # missing dot
        assert "naughty_plugin" in str(excinfo.value)
        assert excinfo.value.context["kind"] == "injector"
        assert excinfo.value.context["value"] == "go"

    def test_plugin_injector_used_by_dispatch(self, tmp_path: Path) -> None:
        """End-to-end round-trip: plugin registers a ``.go`` injector;
        the applier's ``_dispatch_injector`` picks it up when handed a
        ``.go`` target. This is the contract that justifies the whole
        registry — plugins land new file-type support without touching
        ``forge/appliers/injection.py``."""
        api = self._api(name="go_plugin")
        captured: dict[str, object] = {}

        def go_injector(
            file: Path,
            feature_key: str,
            marker: str,
            snippet: str,
            position: str,
        ) -> None:
            captured["file"] = file
            captured["feature_key"] = feature_key
            captured["marker"] = marker
            captured["snippet"] = snippet
            captured["position"] = position

        api.add_injector(".go", go_injector)

        target = tmp_path / "service.go"
        target.write_text("// placeholder\n", encoding="utf-8")

        # Build a minimal _Injection-shaped object. The applier only
        # reads .feature_key / .marker / .snippet / .position, so we
        # avoid the full dataclass construction (which would pull in
        # the wider FragmentPlan machinery).
        class _StubInjection:
            feature_key = "my_feature"
            marker = "MY_MARKER"
            snippet = 'fmt.Println("hi")'
            position = "after"

        _dispatch_injector(target, _StubInjection())  # type: ignore[arg-type]

        assert captured["file"] == target
        assert captured["feature_key"] == "my_feature"
        assert captured["marker"] == "MY_MARKER"
        assert captured["snippet"] == 'fmt.Println("hi")'
        assert captured["position"] == "after"


class TestDispatchWildcardSafety:
    """``_dispatch_injector`` defends against a torn-down wildcard."""

    def test_dispatch_raises_when_no_injector_resolves(self, tmp_path: Path) -> None:
        """If a misbehaving plugin / test purges the wildcard, the
        applier surfaces a clear RuntimeError rather than silently
        dropping the injection."""
        _REGISTRY.pop(WILDCARD_SUFFIX)
        target = tmp_path / "foo.unknownext"
        target.write_text("anchor\n", encoding="utf-8")

        class _StubInjection:
            feature_key = "f"
            marker = "M"
            snippet = "x"
            position = "after"

        with pytest.raises(RuntimeError, match="No injector registered"):
            _dispatch_injector(target, _StubInjection())  # type: ignore[arg-type]
