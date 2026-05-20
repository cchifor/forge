"""Tests for plugin extractor composition in the harvester pipeline.

Initiative #1 sub-task 4 made plugin extractors first-class:

* :meth:`forge.api.ForgeAPI.add_extractor` retains the extractor
  instance on
  :attr:`forge.api.PluginRegistration.extractor_registrations`.
* :func:`forge.sync.project_to_forge.harvester._orchestrator._make_pipeline`
  reads ``LOADED_PLUGINS`` and composes global plugin overrides
  (``fragment=None``) over the built-in pipeline.

This file pins those two contracts at the orchestrator boundary.
Fragment-scoped overrides (``fragment="name"``) are tracked but not
invoked — that's a documented carve-out and we assert it stays
true so a future change doesn't silently start applying them
without per-fragment pipeline plumbing.
"""

from __future__ import annotations

import pytest

from forge import plugins as plugins_module
from forge.api import PluginExtractorRegistration, PluginRegistration
from forge.extractors.pipeline import ExtractorKind
from forge.sync.project_to_forge.harvester._orchestrator import _make_pipeline


class _StubExtractor:
    """Minimal ExtractorProtocol implementation that just records its tag."""

    def __init__(self, kind: ExtractorKind, tag: str) -> None:
        self.kind = kind
        self.tag = tag

    def extract(self, ctx, plan):  # noqa: ARG002 — tests don't run extract
        return []


@pytest.fixture(autouse=True)
def _isolate_loaded_plugins():
    """Snapshot + restore the loaded-plugins registry around each test."""
    saved = list(plugins_module.LOADED_PLUGINS)
    plugins_module.LOADED_PLUGINS.clear()
    try:
        yield
    finally:
        plugins_module.LOADED_PLUGINS.clear()
        plugins_module.LOADED_PLUGINS.extend(saved)


def _register_plugin_with_extractor(
    name: str,
    kind: ExtractorKind,
    extractor: _StubExtractor,
    *,
    fragment: str | None = None,
) -> PluginRegistration:
    reg = PluginRegistration(
        name=name,
        module=f"{name}.module",
        extractor_registrations=(
            PluginExtractorRegistration(kind=kind, fragment=fragment, extractor=extractor),
        ),
    )
    plugins_module.LOADED_PLUGINS.append(reg)
    return reg


class TestGlobalPluginExtractorReplacesBuiltin:
    """``fragment=None`` registrations replace the built-in extractor of
    the matching kind in the assembled pipeline."""

    def test_files_override_replaces_builtin_files_extractor(self) -> None:
        stub = _StubExtractor(kind="files", tag="plugin-files")
        _register_plugin_with_extractor("p_files", "files", stub)

        pipeline = _make_pipeline({"files", "block", "deps", "env"})
        files_handlers = [e for e in pipeline.extractors if e.kind == "files"]

        assert len(files_handlers) == 1, "expected exactly one files handler"
        assert files_handlers[0] is stub, (
            "plugin extractor did not replace the built-in files extractor"
        )

    def test_other_kinds_remain_builtin(self) -> None:
        # Register an override for files only; block/deps/env must still
        # use the built-in extractors so the pipeline keeps its
        # default coverage where no plugin spoke up.
        stub = _StubExtractor(kind="files", tag="plugin-files")
        _register_plugin_with_extractor("p_files", "files", stub)

        pipeline = _make_pipeline({"files", "block", "deps", "env"})
        non_files = [e for e in pipeline.extractors if e.kind != "files"]

        for ext in non_files:
            assert ext is not stub
        # And the built-in modules are still in the pipeline for the
        # non-overridden kinds.
        kinds = {ext.kind for ext in pipeline.extractors}
        assert kinds == {"files", "block", "deps", "env"}

    def test_last_loaded_plugin_wins_on_collision(self) -> None:
        first = _StubExtractor(kind="block", tag="first")
        second = _StubExtractor(kind="block", tag="second")
        _register_plugin_with_extractor("p_first", "block", first)
        _register_plugin_with_extractor("p_second", "block", second)

        pipeline = _make_pipeline({"block"})
        block_handlers = [e for e in pipeline.extractors if e.kind == "block"]

        assert len(block_handlers) == 1
        assert block_handlers[0] is second, "last-loaded plugin should win on collision"


class TestFragmentScopedOverrideIsDeferred:
    """Fragment-scoped overrides are recorded on PluginRegistration but
    intentionally NOT composed into the global pipeline — they need
    per-fragment construction and the current ``_make_pipeline`` signature
    can't accept a fragment name. The assertion is the contract: a future
    change that starts applying them must update this test."""

    def test_fragment_scoped_override_does_not_replace_builtin(self) -> None:
        stub = _StubExtractor(kind="block", tag="scoped")
        _register_plugin_with_extractor(
            "p_scoped", "block", stub, fragment="auth_jwt"
        )

        pipeline = _make_pipeline({"block"})
        block_handlers = [e for e in pipeline.extractors if e.kind == "block"]

        assert len(block_handlers) == 1
        assert block_handlers[0] is not stub, (
            "fragment-scoped plugin extractor leaked into the global pipeline; "
            "_make_pipeline still has no way to consume the scope, so a future "
            "PR that applies them must also wire per-fragment construction."
        )


class TestSelectedKindsFiltering:
    """Independent of plugin overrides: ``selected_kinds`` still filters
    the assembled pipeline to just the requested kinds."""

    def test_empty_selection_yields_empty_pipeline(self) -> None:
        stub = _StubExtractor(kind="files", tag="plugin-files")
        _register_plugin_with_extractor("p_files", "files", stub)

        pipeline = _make_pipeline(set())
        assert pipeline.extractors == ()

    def test_partial_selection_returns_only_matching_kinds(self) -> None:
        pipeline = _make_pipeline({"files", "deps"})
        kinds = {ext.kind for ext in pipeline.extractors}
        assert kinds == {"files", "deps"}

    def test_override_for_unselected_kind_is_excluded(self) -> None:
        """If a plugin overrides ``files`` but the operator only asked
        for ``deps``, the override must NOT leak into the pipeline."""
        stub = _StubExtractor(kind="files", tag="plugin-files")
        _register_plugin_with_extractor("p_files", "files", stub)

        pipeline = _make_pipeline({"deps"})
        kinds = {ext.kind for ext in pipeline.extractors}
        assert kinds == {"deps"}
        assert stub not in pipeline.extractors


class TestApiToHarvesterBridge:
    """End-to-end: register a plugin extractor via the real
    :meth:`forge.api.ForgeAPI.add_extractor` and confirm the
    harvester picks it up. Catches regressions in the api->harvester
    seam where the prior tests construct ``PluginExtractorRegistration``
    directly and skip the API layer entirely.
    """

    def test_add_extractor_via_api_reaches_harvester_pipeline(self) -> None:
        from forge.api import ForgeAPI, PluginRegistration  # noqa: PLC0415

        class _ApiStubExtractor:
            kind: ExtractorKind = "block"

            def extract(self, ctx, plan):  # noqa: ARG002
                return []

        registration = PluginRegistration(name="bridge", module="bridge.module")
        api = ForgeAPI(registration)
        extractor = _ApiStubExtractor()
        api.add_extractor("block", extractor)

        # Push the registration into LOADED_PLUGINS the way
        # ``forge.plugins.load_all`` would.
        plugins_module.LOADED_PLUGINS.append(registration)

        pipeline = _make_pipeline({"block"})
        block_handlers = [e for e in pipeline.extractors if e.kind == "block"]

        assert len(block_handlers) == 1
        assert block_handlers[0] is extractor, (
            "extractor registered via ForgeAPI.add_extractor did not survive "
            "the api -> harvester bridge"
        )
        # Both representations should be populated symmetrically.
        assert len(registration.extractor_registrations) == 1
        assert registration.extractors_added == (("block", None),)
