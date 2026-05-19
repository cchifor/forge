"""Phase C — OBJECT type promotion + ``agent.mode`` placeholder tests.

Covers:

* ``OptionType.OBJECT`` accepts dict defaults/values, rejects non-dicts,
  and requires ``stability="experimental"`` at registration time.
* ``agent.mode`` is registered with the same ENUM shape as
  ``backend.mode`` / ``database.mode`` / ``frontend.mode`` — pattern
  parity across all four layers.

Phase C scope is deliberately conservative: the OBJECT validator checks
outer shape only. Nested-shape (TypedDict-style) validation is behind
the ``experimental`` gate and expected to evolve before any OBJECT
option ships as stable.
"""

from __future__ import annotations

import pytest

from forge.options import (
    OPTION_REGISTRY,
    FeatureCategory,
    Option,
    OptionType,
)


# -- OBJECT type --------------------------------------------------------------


class TestObjectTypeRegistration:
    def test_object_default_must_be_dict(self):
        with pytest.raises(ValueError, match=r"OBJECT default must be dict"):
            Option(
                path="test.obj_bad_default",
                type=OptionType.OBJECT,
                default="not-a-dict",
                summary="x",
                description="x",
                category=FeatureCategory.PLATFORM,
                stability="experimental",
            )

    def test_object_default_accepts_empty_dict(self):
        opt = Option(
            path="test.obj_empty",
            type=OptionType.OBJECT,
            default={},
            summary="x",
            description="x",
            category=FeatureCategory.PLATFORM,
            stability="experimental",
        )
        assert opt.default == {}

    def test_object_default_accepts_populated_dict(self):
        opt = Option(
            path="test.obj_full",
            type=OptionType.OBJECT,
            default={"type": "local", "url": ""},
            summary="x",
            description="x",
            category=FeatureCategory.PLATFORM,
            stability="experimental",
        )
        assert opt.default == {"type": "local", "url": ""}

    def test_object_requires_experimental_stability(self):
        """The nested-shape contract isn't stable yet — registering an
        OBJECT Option without ``stability="experimental"`` must fail so
        operators don't accidentally ship an option whose shape may
        change in the next release."""
        with pytest.raises(ValueError, match=r"stability=.experimental"):
            Option(
                path="test.obj_not_experimental",
                type=OptionType.OBJECT,
                default={},
                summary="x",
                description="x",
                category=FeatureCategory.PLATFORM,
            )


class TestObjectValidateValue:
    def _make_opt(self, default: dict) -> Option:
        return Option(
            path="test.obj_v",
            type=OptionType.OBJECT,
            default=default,
            summary="x",
            description="x",
            category=FeatureCategory.PLATFORM,
            stability="experimental",
        )

    def test_accepts_dict(self):
        opt = self._make_opt({})
        opt.validate_value({"a": 1})  # no raise

    def test_rejects_non_dict(self):
        opt = self._make_opt({})
        with pytest.raises(ValueError, match=r"expected dict"):
            opt.validate_value("nope")

    def test_rejects_list(self):
        opt = self._make_opt({})
        with pytest.raises(ValueError, match=r"expected dict"):
            opt.validate_value([1, 2, 3])


# -- agent.mode placeholder ---------------------------------------------------


class TestAgentModePlaceholder:
    """Theme 2A — ``agent.mode`` is no longer a placeholder. The legacy
    placeholder assertions in this class were rewritten when the
    discriminator went live; the full Theme 2A surface (four enum
    values, fragment bundles, cross-layer rule) is covered by
    ``tests/test_agent_mode.py``. These two cases survive as a smoke
    check that the registration is still present + shaped like an enum.
    """

    def test_agent_mode_registered(self):
        assert "agent.mode" in OPTION_REGISTRY

    def test_agent_mode_is_layer_mode_enum(self):
        """``agent.mode`` is an ENUM, defaults to ``none``, and offers
        the same ``none`` escape hatch the other layer modes do. The
        full value list + the fragment bundles live in
        ``tests/test_agent_mode.py``."""
        agent = OPTION_REGISTRY["agent.mode"]
        assert agent.type == OptionType.ENUM
        assert agent.default == "none"
        assert "none" in agent.options


class TestLayerModeParity:
    """All four layer discriminators — backend.mode, database.mode,
    frontend.mode, agent.mode — register as ENUM Options whose ``none``
    value carries no fragment bundle. ``agent.mode`` (Theme 2A) fans out
    to ``conversational_ai`` fragments for its non-``none`` values; the
    other three modes orchestrate generation without enabling per-value
    bundles. The shared invariant is "``none`` is the empty bundle"."""

    @pytest.mark.parametrize(
        "path",
        ["backend.mode", "database.mode", "frontend.mode", "agent.mode"],
    )
    def test_layer_mode_is_enum(self, path):
        opt = OPTION_REGISTRY[path]
        assert opt.type == OptionType.ENUM

    @pytest.mark.parametrize(
        "path",
        ["backend.mode", "database.mode", "frontend.mode", "agent.mode"],
    )
    def test_layer_mode_none_is_empty_bundle(self, path):
        """``mode="none"`` enables no fragments — this is the shared
        "no-op layer" contract across all four discriminators."""
        opt = OPTION_REGISTRY[path]
        # ``none`` is always a valid value, and if the option declares an
        # ``enables`` map at all, the ``none`` entry must be empty.
        assert "none" in opt.options
        if opt.enables:
            assert opt.enables.get("none", ()) == ()

    @pytest.mark.parametrize(
        "path",
        ["backend.mode", "database.mode", "frontend.mode", "agent.mode"],
    )
    def test_layer_mode_includes_none_option(self, path):
        opt = OPTION_REGISTRY[path]
        assert "none" in opt.options
