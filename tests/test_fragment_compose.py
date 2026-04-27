"""Tests for the fragment-shipped compose.yaml loader (P1.3, 1.1.0-alpha.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.services import registry as svc_registry
from forge.services.fragment_compose import (
    FragmentComposeError,
    load_fragment_compose,
    register_fragment_services,
)
from forge.services.registry import ServiceTemplate


@pytest.fixture(autouse=True)
def _reset_registry():
    svc_registry.SERVICE_REGISTRY.clear()
    yield
    svc_registry.SERVICE_REGISTRY.clear()


class TestLoadFragmentCompose:
    def test_returns_none_when_compose_yaml_absent(self, tmp_path: Path) -> None:
        assert load_fragment_compose(tmp_path) is None

    def test_loads_minimal_service(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").write_text(
            "capability: redis_minimal\n"
            "service:\n"
            "  name: redis\n"
            "  image: redis:7-alpine\n",
            encoding="utf-8",
        )
        result = load_fragment_compose(tmp_path)
        assert result is not None
        capability, template = result
        assert capability == "redis_minimal"
        assert template.name == "redis"
        assert template.image == "redis:7-alpine"
        # Defaults survive when keys are omitted.
        assert template.networks == ("app-network",)
        assert template.restart == "unless-stopped"
        assert template.ports == []

    def test_loads_full_service(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").write_text(
            """
capability: queue_redis
service:
  name: redis
  image: redis:7-alpine
  command: ["redis-server", "--appendonly", "yes"]
  environment:
    REDIS_PASSWORD: secret
  ports:
    - "6379:6379"
  volumes:
    - redis-data:/data
  named_volumes:
    - redis-data
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 10s
    timeout: 3s
    retries: 5
  depends_on:
    postgres:
      condition: service_healthy
  networks:
    - app-network
    - data-network
  restart: always
""",
            encoding="utf-8",
        )
        result = load_fragment_compose(tmp_path)
        assert result is not None
        capability, template = result
        assert capability == "queue_redis"
        assert template.command == ["redis-server", "--appendonly", "yes"]
        assert template.environment == {"REDIS_PASSWORD": "secret"}
        assert template.ports == ["6379:6379"]
        assert template.named_volumes == ("redis-data",)
        assert template.healthcheck is not None
        assert template.healthcheck["interval"] == "10s"
        assert "postgres" in template.depends_on
        assert template.networks == ("app-network", "data-network")
        assert template.restart == "always"

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").write_text("not: valid: yaml: : :", encoding="utf-8")
        with pytest.raises(FragmentComposeError, match="invalid YAML"):
            load_fragment_compose(tmp_path)

    def test_top_level_must_be_mapping(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").write_text("- just: a list\n", encoding="utf-8")
        with pytest.raises(FragmentComposeError, match="top-level mapping"):
            load_fragment_compose(tmp_path)

    def test_missing_capability_raises(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").write_text(
            "service:\n  name: x\n  image: y:1\n", encoding="utf-8"
        )
        with pytest.raises(FragmentComposeError, match="capability"):
            load_fragment_compose(tmp_path)

    def test_missing_service_block_raises(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").write_text("capability: foo\n", encoding="utf-8")
        with pytest.raises(FragmentComposeError, match="service"):
            load_fragment_compose(tmp_path)

    def test_missing_service_name_raises(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").write_text(
            "capability: foo\nservice:\n  image: y:1\n", encoding="utf-8"
        )
        with pytest.raises(FragmentComposeError, match="service.name"):
            load_fragment_compose(tmp_path)

    def test_missing_service_image_raises(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").write_text(
            "capability: foo\nservice:\n  name: x\n", encoding="utf-8"
        )
        with pytest.raises(FragmentComposeError, match="service.image"):
            load_fragment_compose(tmp_path)


class TestRegisterFragmentServices:
    def test_registers_each_unique_root(self, tmp_path: Path) -> None:
        first = tmp_path / "frag_a"
        second = tmp_path / "frag_b"
        first.mkdir()
        second.mkdir()
        for path, cap in [(first, "cap_a"), (second, "cap_b")]:
            (path / "compose.yaml").write_text(
                f"capability: {cap}\nservice:\n  name: {cap}\n  image: example:1\n",
                encoding="utf-8",
            )

        registered = register_fragment_services([first, second])
        assert {cap for cap, _ in registered} == {"cap_a", "cap_b"}
        assert "cap_a" in svc_registry.SERVICE_REGISTRY
        assert "cap_b" in svc_registry.SERVICE_REGISTRY

    def test_skips_dirs_without_compose_yaml(self, tmp_path: Path) -> None:
        d = tmp_path / "no_compose"
        d.mkdir()
        registered = register_fragment_services([d])
        assert registered == []
        assert svc_registry.SERVICE_REGISTRY == {}

    def test_dedupes_repeated_roots(self, tmp_path: Path) -> None:
        d = tmp_path / "frag"
        d.mkdir()
        (d / "compose.yaml").write_text(
            "capability: only_once\nservice:\n  name: x\n  image: y:1\n",
            encoding="utf-8",
        )
        registered = register_fragment_services([d, d, d])
        # Three repeated calls register once each (the second-and-third
        # paths are deduped by ``seen_roots``).
        assert len(registered) == 1

    def test_idempotent_for_identical_template(self, tmp_path: Path) -> None:
        d = tmp_path / "frag"
        d.mkdir()
        (d / "compose.yaml").write_text(
            "capability: idempotent\nservice:\n  name: x\n  image: y:1\n",
            encoding="utf-8",
        )
        # Pre-seed the registry with the same template, then re-register.
        svc_registry.register_service(
            "idempotent", ServiceTemplate(name="x", image="y:1")
        )
        register_fragment_services([d])  # Must not raise.
        assert svc_registry.SERVICE_REGISTRY["idempotent"].name == "x"

    def test_conflicting_template_raises(self, tmp_path: Path) -> None:
        d = tmp_path / "frag"
        d.mkdir()
        (d / "compose.yaml").write_text(
            "capability: conflict\nservice:\n  name: a\n  image: imageA:1\n",
            encoding="utf-8",
        )
        # Pre-seed with a different template under the same capability.
        svc_registry.register_service(
            "conflict", ServiceTemplate(name="b", image="imageB:1")
        )
        with pytest.raises(ValueError, match="already registered"):
            register_fragment_services([d])
