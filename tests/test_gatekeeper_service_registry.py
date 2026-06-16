"""Structural tests for the Gatekeeper service-to-service client registry.

The token-exchange guard in ``service_token.py`` rejects service-account
``subject_token``s by checking ``azp.startswith("svc-")``. Client-credentials
mints set ``azp = entry.client_id``, so that guard is only sound if *every*
registered service ``client_id`` carries the ``svc-`` prefix. The registry
schema must therefore enforce that prefix at load / model-validation time —
otherwise a hand-edited registry client without the prefix silently defeats
the guard.

We load the registry module straight from the template path (mirroring
``tests/test_gatekeeper_authz.py``'s importlib loader) so the test validates
what forge actually ships into generated projects.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_TEMPLATE_ROOT = (
    Path(__file__).resolve().parent.parent
    / "forge"
    / "features"
    / "auth"
    / "templates"
    / "platform_auth_gatekeeper"
    / "all"
    / "files"
    / "deploy"
    / "infra"
    / "gatekeeper"
)


def _load_registry_module():
    path = _TEMPLATE_ROOT / "src" / "app" / "gatekeeper" / "service_registry.py"
    spec = importlib.util.spec_from_file_location(
        "gatekeeper_service_registry_under_test", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["gatekeeper_service_registry_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def registry_mod():
    return _load_registry_module()


class TestServiceClientPrefix:
    def test_prefixed_client_id_accepted(self, registry_mod) -> None:
        client = registry_mod.ServiceClient(client_id="svc-workflow")
        assert client.client_id == "svc-workflow"

    def test_unprefixed_client_id_rejected(self, registry_mod) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            registry_mod.ServiceClient(client_id="workflow")


class TestLoadRegistry:
    def test_unprefixed_client_rejected_at_load(self, registry_mod, tmp_path) -> None:
        bad = tmp_path / "registry.yaml"
        bad.write_text(
            "services:\n"
            "  - client_id: workflow\n"
            "    audiences: {}\n",
            encoding="utf-8",
        )
        with pytest.raises(registry_mod.RegistryError):
            registry_mod.load_registry(bad)

    def test_prefixed_client_loads(self, registry_mod, tmp_path) -> None:
        good = tmp_path / "registry.yaml"
        good.write_text(
            "services:\n"
            "  - client_id: svc-workflow\n"
            "    audiences: {}\n",
            encoding="utf-8",
        )
        reg = registry_mod.load_registry(good)
        assert reg.client_ids == frozenset({"svc-workflow"})

    def test_shipped_seed_registry_still_loads(self, registry_mod) -> None:
        seed = _TEMPLATE_ROOT / "secrets" / "service_registry.yaml"
        reg = registry_mod.load_registry(seed)
        assert "svc-workflow" in reg.client_ids
        assert all(cid.startswith("svc-") for cid in reg.client_ids)
