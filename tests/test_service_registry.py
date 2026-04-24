"""Tests for the capability → docker-compose service registry (P0.4)."""

from __future__ import annotations

import pytest

from forge.services import ServiceTemplate, register_service
from forge.services.registry import (
    SERVICE_REGISTRY,
    get_services_for_capabilities,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_for_tests()
    yield
    reset_for_tests()


class TestServiceTemplate:
    def test_minimal_template(self):
        svc = ServiceTemplate(name="s", image="redis:7-alpine")
        block = svc.as_compose_dict()
        assert block == {
            "image": "redis:7-alpine",
            "networks": ["app-network"],
            "restart": "unless-stopped",
        }

    def test_full_template(self):
        svc = ServiceTemplate(
            name="qd",
            image="qdrant/qdrant:latest",
            command=["--config-path", "/c"],
            environment={"Q_HOST": "0.0.0.0"},
            ports=['"6333:6333"'],
            volumes=["q_data:/data"],
            healthcheck={"test": ["CMD", "curl", "/ready"], "interval": "10s"},
            depends_on={"postgres": {"condition": "service_healthy"}},
            named_volumes=("q_data",),
        )
        block = svc.as_compose_dict()
        assert block["image"] == "qdrant/qdrant:latest"
        assert block["command"] == ["--config-path", "/c"]
        assert block["environment"] == {"Q_HOST": "0.0.0.0"}
        assert block["ports"] == ['"6333:6333"']
        assert block["volumes"] == ["q_data:/data"]
        assert block["healthcheck"]["interval"] == "10s"
        assert block["depends_on"] == {"postgres": {"condition": "service_healthy"}}


class TestRegisterService:
    def test_adds_to_registry(self):
        svc = ServiceTemplate(name="s", image="r:1")
        register_service("cap_a", svc)
        assert SERVICE_REGISTRY["cap_a"] == svc

    def test_idempotent_identical_registration(self):
        svc = ServiceTemplate(name="s", image="r:1")
        register_service("cap_a", svc)
        register_service("cap_a", svc)

    def test_rejects_conflicting_registration(self):
        register_service("cap_a", ServiceTemplate(name="s", image="r:1"))
        with pytest.raises(ValueError, match="already registered"):
            register_service("cap_a", ServiceTemplate(name="s", image="r:2"))


class TestGetServicesForCapabilities:
    def test_returns_matching_services_in_input_order(self):
        a = ServiceTemplate(name="a", image="img_a")
        b = ServiceTemplate(name="b", image="img_b")
        register_service("cap_a", a)
        register_service("cap_b", b)

        out = get_services_for_capabilities(["cap_b", "cap_a"])
        assert [s.name for s in out] == ["b", "a"]

    def test_skips_unknown_capabilities(self):
        a = ServiceTemplate(name="a", image="img_a")
        register_service("cap_a", a)
        out = get_services_for_capabilities(["unknown", "cap_a", "also_unknown"])
        assert [s.name for s in out] == ["a"]

    def test_deduplicates_by_service_name(self):
        shared = ServiceTemplate(name="shared", image="x")
        register_service("cap_a", shared)
        register_service("cap_b", shared)
        out = get_services_for_capabilities(["cap_a", "cap_b"])
        assert [s.name for s in out] == ["shared"]

    def test_empty_input(self):
        assert get_services_for_capabilities([]) == []
