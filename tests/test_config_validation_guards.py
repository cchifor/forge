"""Regression: config-validation guards (audit #4, #9, #16, #19, #20, #21).

Each case constructs a configuration that *should* be rejected but was silently
accepted, then crashed generation, produced a broken stack, or shipped a no-op.
"""

from __future__ import annotations

import pytest

from forge.capability_resolver import resolve
from forge.config import BackendConfig, BackendLanguage, ProjectConfig


def _cfg(*, backends, **kw) -> ProjectConfig:
    return ProjectConfig(project_name="guard", backends=backends, **kw)


def _be(name="api", *, language=BackendLanguage.PYTHON, port=5000, **kw) -> BackendConfig:
    return BackendConfig(name=name, project_name="guard", language=language, server_port=port, **kw)


# --- #4: database.mode=none is Python-only (no node/rust stripper) -----------
@pytest.mark.parametrize("lang", [BackendLanguage.NODE, BackendLanguage.RUST])
def test_database_mode_none_rejected_for_non_python(lang) -> None:
    cfg = _cfg(backends=[_be(language=lang)], options={"database.mode": "none"})
    with pytest.raises(ValueError) as exc:
        cfg.validate()
    assert "database.mode" in str(exc.value).lower() or "stateless" in str(exc.value).lower()


# --- #9: connectors.enabled requires a database -------------------------------
def test_connectors_enabled_rejected_in_stateless_mode() -> None:
    cfg = _cfg(
        backends=[_be()],
        options={"database.mode": "none", "connectors.enabled": True},
    )
    with pytest.raises(ValueError, match="connectors.enabled"):
        cfg.validate()


# --- #16: agent.mode is Python-only -------------------------------------------
@pytest.mark.parametrize("lang", [BackendLanguage.NODE, BackendLanguage.RUST])
def test_agent_mode_rejected_on_non_python_only_project(lang) -> None:
    cfg = _cfg(backends=[_be(language=lang)], options={"agent.mode": "tool_calling"})
    with pytest.raises(Exception) as exc:  # OptionsError at resolve time
        resolve(cfg)
    assert "python" in str(exc.value).lower()


# --- #19: backend name must not collide with a reserved infra service ---------
@pytest.mark.parametrize("reserved", ["postgres", "keycloak", "gatekeeper", "traefik"])
def test_backend_name_rejected_when_reserved_infra_name(reserved) -> None:
    cfg = _cfg(backends=[_be(name=reserved)])
    with pytest.raises(ValueError, match="reserved"):
        cfg.validate()


# --- #20: derived db_name must be unique --------------------------------------
def test_distinct_backend_names_with_colliding_db_name_rejected() -> None:
    # "my-svc" and "my_svc" both derive db_name "my_svc".
    cfg = _cfg(backends=[_be(name="my-svc", port=5001), _be(name="my_svc", port=5002)])
    with pytest.raises(ValueError) as exc:
        cfg.validate()
    assert "database" in str(exc.value).lower() or "db" in str(exc.value).lower()


# --- #21: keycloak_port must not collide with a fixed infra host port ---------
def test_keycloak_port_collision_with_infra_rejected() -> None:
    # 5000 is the Gatekeeper host port (rendered under include_keycloak).
    cfg = _cfg(backends=[_be(port=5001)], include_keycloak=True, keycloak_port=5000)
    with pytest.raises(ValueError) as exc:
        cfg.validate()
    msg = str(exc.value).lower()
    assert "keycloak" in msg or "gatekeeper" in msg
