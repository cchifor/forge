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
    def test_agent_mode_registered(self):
        assert "agent.mode" in OPTION_REGISTRY

    def test_agent_mode_matches_other_layer_modes(self):
        """All four layer discriminators share the same shape:
        ENUM, default None-or-generate, generate/none options with
        optional external. This test locks in pattern parity."""
        agent = OPTION_REGISTRY["agent.mode"]
        assert agent.type == OptionType.ENUM
        assert set(agent.options) >= {"generate", "none"}
        assert agent.default == "none"
        assert agent.enables == {}  # placeholder — no fragments yet


class TestLayerModeParity:
    """All four layer discriminators — backend.mode, database.mode,
    frontend.mode, agent.mode — register as ENUM Options with no
    ``enables`` map. The discriminator orchestrates generation; it
    doesn't enable a fragment bundle. If that ever drifts (e.g. someone
    adds enables={}-with-fragments), the layering gets confused."""

    @pytest.mark.parametrize(
        "path",
        ["backend.mode", "database.mode", "frontend.mode", "agent.mode"],
    )
    def test_layer_mode_is_enum_with_empty_enables(self, path):
        opt = OPTION_REGISTRY[path]
        assert opt.type == OptionType.ENUM
        assert opt.enables == {}

    @pytest.mark.parametrize(
        "path",
        ["backend.mode", "database.mode", "frontend.mode", "agent.mode"],
    )
    def test_layer_mode_includes_none_option(self, path):
        opt = OPTION_REGISTRY[path]
        assert "none" in opt.options
