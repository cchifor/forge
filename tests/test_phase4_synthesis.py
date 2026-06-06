"""Phase 4 (P4.0) — multi-service platform-synthesis seam + knobs.

P4.0 ships only the inert foundation: the new options/fields exist and default
to off, and the synthesis pass is a stub returning None — so generation stays
byte-identical (the golden snapshots are the contract; this file pins the
surface). Computation + emitted artifacts land in later Phase-4 sub-steps.
"""

from __future__ import annotations

import pytest

from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.options import OPTION_REGISTRY
from forge.options._registry import OptionType

# --- new option surface -----------------------------------------------------


def test_service_discovery_option_registered() -> None:
    opt = OPTION_REGISTRY["auth.service_discovery"]
    assert opt.type is OptionType.BOOL
    assert opt.default is False
    assert not opt.enables  # inert in P4.0 — no fragments yet


def test_event_bus_option_registered() -> None:
    opt = OPTION_REGISTRY["infrastructure.event_bus"]
    assert opt.type is OptionType.ENUM
    assert opt.default == "none"
    assert opt.options == ("none", "postgres_notify")
    assert not opt.enables  # inert in P4.0


# --- new config fields ------------------------------------------------------


def test_backend_depends_on_defaults_empty() -> None:
    bc = BackendConfig(name="api", project_name="p", language=BackendLanguage.PYTHON)
    assert bc.depends_on == []


def test_backend_depends_on_validates_names() -> None:
    BackendConfig(
        name="gateway",
        project_name="p",
        language=BackendLanguage.PYTHON,
        depends_on=["orders", "inventory"],
    ).validate()
    with pytest.raises(ValueError, match="depends_on entry 'Bad Name'"):
        BackendConfig(
            name="gateway",
            project_name="p",
            language=BackendLanguage.PYTHON,
            depends_on=["Bad Name"],
        ).validate()
    with pytest.raises(ValueError, match="cannot depend on itself"):
        BackendConfig(
            name="gateway",
            project_name="p",
            language=BackendLanguage.PYTHON,
            depends_on=["gateway"],
        ).validate()


def test_project_platform_template_defaults_none() -> None:
    cfg = ProjectConfig(
        project_name="p",
        backends=[BackendConfig(name="api", project_name="p", language=BackendLanguage.PYTHON)],
    )
    assert cfg.platform_template is None


# --- the synthesis seam is a no-op in P4.0 ----------------------------------


def test_synthesize_platform_stub_returns_none() -> None:
    from forge.capability_resolver import resolve
    from forge.generator import _synthesize_platform

    cfg = ProjectConfig(
        project_name="p",
        backends=[
            BackendConfig(
                name="gateway",
                project_name="p",
                language=BackendLanguage.PYTHON,
                depends_on=["orders"],
            ),
            BackendConfig(name="orders", project_name="p", language=BackendLanguage.PYTHON),
        ],
    )
    plan = resolve(cfg)
    # Even with depends_on edges declared, P4.0 synthesis is inert (returns None)
    # because auth.service_discovery defaults off — the byte-identical contract.
    assert _synthesize_platform(cfg, plan, project_root=None, quiet=True) is None  # type: ignore[arg-type]
