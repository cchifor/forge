"""Tests for the ``--platform`` preset system (Phase 4, P4.4).

Three layers:

* (a) UNIT — the :mod:`forge.platform_templates` registry: discovery of the
  three shipped presets, lookup, sorted listing, parsed structure, and the
  :meth:`PlatformTemplate.as_config_dict` round-trip shape.
* (b) INTEGRATION — the real CLI builder (``_build_config``) applied with a
  ``--platform`` Namespace + empty cfg, then validated and dry-run generated.
  Asserts cross-artifact coherence (S2S registry, compose env, init-db event
  db, frontend presence) for microservices / headless-api / monolithic.
* (c) PRECEDENCE — the preset is the lowest config layer: user cfg
  (project_name, options, whole backends list, include_keycloak) overrides it.
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from forge.cli.builder import _build_config
from forge.generator import generate
from forge.platform_templates import (
    PLATFORM_TEMPLATES,
    PlatformTemplate,
    available_platform_templates,
    get_platform_template,
)

# --------------------------------------------------------------------------- #
# (a) UNIT — registry + manifest parsing + as_config_dict round-trip
# --------------------------------------------------------------------------- #


class TestPlatformRegistry:
    def test_three_builtin_presets_discovered(self) -> None:
        names = available_platform_templates()
        assert "monolithic" in names
        assert "microservices" in names
        assert "headless-api" in names

    def test_available_is_sorted(self) -> None:
        names = available_platform_templates()
        assert list(names) == sorted(names)

    def test_get_returns_each_preset(self) -> None:
        for name in ("monolithic", "microservices", "headless-api"):
            preset = get_platform_template(name)
            assert isinstance(preset, PlatformTemplate)
            assert preset.name == name

    def test_get_unknown_returns_none(self) -> None:
        assert get_platform_template("does-not-exist") is None

    def test_registry_keyed_by_name(self) -> None:
        for name in ("monolithic", "microservices", "headless-api"):
            assert PLATFORM_TEMPLATES[name].name == name


class TestMonolithicStructure:
    def test_single_backend_no_discovery_no_keycloak(self) -> None:
        p = get_platform_template("monolithic")
        assert p is not None
        assert len(p.backends) == 1
        assert p.backends[0]["name"] == "backend"
        assert p.backends[0]["app_template"] == "crud-service"
        assert p.include_keycloak is False
        assert p.options.get("auth.service_discovery") is False
        assert p.frontend is not None
        assert p.frontend["framework"] == "vue"


class TestMicroservicesStructure:
    def test_three_backends_gateway_and_crud(self) -> None:
        p = get_platform_template("microservices")
        assert p is not None
        assert len(p.backends) == 3
        by_name = {b["name"]: b for b in p.backends}
        assert by_name["gateway"]["app_template"] == "api-gateway"
        assert by_name["gateway"]["depends_on"] == ["orders", "inventory"]
        assert by_name["orders"]["app_template"] == "crud-service"
        assert by_name["inventory"]["app_template"] == "crud-service"

    def test_service_discovery_and_event_bus_options(self) -> None:
        p = get_platform_template("microservices")
        assert p is not None
        assert p.options["auth.service_discovery"] is True
        assert p.options["infrastructure.event_bus"] == "postgres_notify"

    def test_keycloak_and_frontend(self) -> None:
        p = get_platform_template("microservices")
        assert p is not None
        assert p.include_keycloak is True
        assert p.frontend is not None
        assert p.frontend["framework"] == "vue"
        assert p.frontend["layout"] == "sidebar"


class TestHeadlessApiStructure:
    def test_two_backends_no_frontend_no_event_bus(self) -> None:
        p = get_platform_template("headless-api")
        assert p is not None
        assert len(p.backends) == 2
        by_name = {b["name"]: b for b in p.backends}
        assert by_name["gateway"]["app_template"] == "api-gateway"
        assert by_name["gateway"]["depends_on"] == ["orders"]
        assert by_name["orders"]["app_template"] == "crud-service"
        # No frontend block at all (headless).
        assert p.frontend is None
        # Service discovery on, but NO event bus.
        assert p.options["auth.service_discovery"] is True
        assert "infrastructure.event_bus" not in p.options
        assert p.include_keycloak is True


class TestAsConfigDictRoundTrip:
    def test_microservices_shape(self) -> None:
        p = get_platform_template("microservices")
        assert p is not None
        cfg = p.as_config_dict()
        assert cfg["include_keycloak"] is True
        assert cfg["options"]["auth.service_discovery"] is True
        assert cfg["options"]["infrastructure.event_bus"] == "postgres_notify"
        assert [b["name"] for b in cfg["backends"]] == ["gateway", "orders", "inventory"]
        assert cfg["frontend"]["framework"] == "vue"

    def test_headless_omits_frontend_key(self) -> None:
        p = get_platform_template("headless-api")
        assert p is not None
        cfg = p.as_config_dict()
        # A headless preset omits the frontend key entirely so the builder's
        # frontend.framework default (none) governs.
        assert "frontend" not in cfg

    def test_as_config_dict_returns_fresh_mutable_copies(self) -> None:
        """The dict is safe to mutate without corrupting the frozen preset."""
        p = get_platform_template("microservices")
        assert p is not None
        cfg = p.as_config_dict()
        cfg["options"]["auth.service_discovery"] = False
        cfg["backends"].append({"name": "extra"})
        # The frozen preset is untouched.
        assert p.options["auth.service_discovery"] is True
        assert len(p.backends) == 3

    def test_database_mode_rides_in_options(self) -> None:
        """A preset's database_mode override surfaces under options.database.mode."""
        custom = PlatformTemplate(
            name="x",
            display_label="X",
            description="",
            database_mode="none",
        )
        cfg = custom.as_config_dict()
        assert cfg["options"]["database.mode"] == "none"


# --------------------------------------------------------------------------- #
# (b) INTEGRATION — real builder + validate + dry-run generation
# --------------------------------------------------------------------------- #


def _args(**overrides: object) -> Namespace:
    """A fully-defaulted CLI Namespace (all flags None) with `platform` set."""
    base = dict(
        platform=None,
        project_name=None,
        description=None,
        output_dir=".",
        backend_language=None,
        backend_name=None,
        backend_port=None,
        python_version=None,
        node_version=None,
        rust_edition=None,
        features=None,
        frontend=None,
        author_name=None,
        package_manager=None,
        include_auth=None,
        include_chat=None,
        include_openapi=None,
        frontend_port=None,
        color_scheme=None,
        org_name=None,
        generate_e2e_tests=None,
        keycloak_port=None,
        keycloak_realm=None,
        keycloak_client_id=None,
        layout=None,
        api_base_url=None,
        api_proxy_target=None,
        include_keycloak=None,
        set_options=[],
        yes=True,
        no_docker=True,
        quiet=True,
        json_output=False,
        config=None,
    )
    base.update(overrides)
    return Namespace(**base)


class TestMicroservicesIntegration:
    def test_build_and_validate(self) -> None:
        config = _build_config(_args(platform="microservices"), {})
        config.validate()  # must not raise

        assert config.platform_template == "microservices"
        assert config.include_keycloak is True
        assert len(config.backends) == 3

        by_name = {b.name: b for b in config.backends}
        assert by_name["gateway"].app_template == "api-gateway"
        assert by_name["gateway"].depends_on == ["orders", "inventory"]

        assert config.options["auth.service_discovery"] is True
        assert config.options["infrastructure.event_bus"] == "postgres_notify"

    def test_dry_run_synthesizes_registry_and_env(self) -> None:
        config = _build_config(_args(platform="microservices"), {"project_name": "Acme MS"})
        config.validate()
        root = generate(config, quiet=True, dry_run=True)

        registry = root / "infra" / "gatekeeper" / "secrets" / "service_registry.yaml"
        assert registry.is_file()
        registry_text = registry.read_text(encoding="utf-8")
        for client_id in ("svc-gateway", "svc-orders", "svc-inventory"):
            assert client_id in registry_text

        compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
        assert "INTERNAL_SERVICE_URL_" in compose

        # The platform preset is persisted to forge.toml.
        forge_toml = (root / "forge.toml").read_text(encoding="utf-8")
        assert 'platform_template = "microservices"' in forge_toml

        # postgres_notify ⇒ a shared events db in init-db.sh.
        init_db = (root / "init-db.sh").read_text(encoding="utf-8")
        assert "events" in init_db


class TestHeadlessApiIntegration:
    def test_build_validate_no_frontend(self) -> None:
        config = _build_config(_args(platform="headless-api"), {})
        config.validate()  # must not raise

        assert config.platform_template == "headless-api"
        assert config.frontend is None
        assert config.include_keycloak is True
        assert config.options["auth.service_discovery"] is True
        assert "infrastructure.event_bus" not in config.options

    def test_dry_run_registry_present_no_events_db(self) -> None:
        config = _build_config(_args(platform="headless-api"), {"project_name": "Acme HL"})
        config.validate()
        root = generate(config, quiet=True, dry_run=True)

        registry = root / "infra" / "gatekeeper" / "secrets" / "service_registry.yaml"
        assert registry.is_file()
        registry_text = registry.read_text(encoding="utf-8")
        assert "svc-gateway" in registry_text
        assert "svc-orders" in registry_text

        # No event bus ⇒ no `events` database line in init-db.sh. Match the
        # exact createdb token so the literal word in comments can't false-trip.
        init_db = (root / "init-db.sh").read_text(encoding="utf-8")
        created = {
            line.strip().strip("\"'")
            for line in init_db.splitlines()
            if "CREATE DATABASE" in line.upper() or line.strip().strip("\"'") == "events"
        }
        assert "events" not in created

        # Headless ⇒ no frontend app was generated.
        assert not (root / "apps").exists()


class TestMonolithicIntegration:
    def test_build_validate_single_backend(self) -> None:
        config = _build_config(_args(platform="monolithic"), {})
        config.validate()  # must not raise

        assert config.platform_template == "monolithic"
        assert len(config.backends) == 1
        assert config.backends[0].name == "backend"
        # No service discovery for the single-service shape.
        assert config.options.get("auth.service_discovery") is False
        assert config.include_keycloak is False

    def test_dry_run_clean_no_synthesized_registry(self) -> None:
        config = _build_config(_args(platform="monolithic"), {"project_name": "Acme Mono"})
        config.validate()
        root = generate(config, quiet=True, dry_run=True)

        # Single service + no keycloak ⇒ synthesis is a no-op; no S2S registry.
        registry = root / "infra" / "gatekeeper" / "secrets" / "service_registry.yaml"
        assert not registry.exists()

        # Exactly one backend service tree.
        services = root / "services"
        assert services.is_dir()
        assert [p.name for p in sorted(services.iterdir()) if p.is_dir()] == ["backend"]


class TestMultitenantSaasIntegration:
    def test_build_and_validate(self) -> None:
        config = _build_config(_args(platform="multitenant-saas"), {})
        config.validate()  # must not raise

        assert config.platform_template == "multitenant-saas"
        assert config.include_keycloak is True
        # The multitenant wiring: gatekeeper edge auth + shared-RLS by JWT claim.
        assert config.options["auth.provider"] == "gatekeeper"
        assert config.options["database.multitenancy"] == "shared_rls"
        assert config.options["database.tenant_resolution"] == "token_claim"

        by_name = {b.name: b for b in config.backends}
        assert by_name["tms"].app_template == "tenant-management-service"
        assert by_name["app"].app_template == "crud-service"
        # RLS rides on the app workload only; TMS isolates by realm, not schema.
        assert "multitenancy" in by_name["app"].features
        assert "multitenancy" not in by_name["tms"].features

    def test_dry_run_stands_up_full_topology(self) -> None:
        config = _build_config(
            _args(platform="multitenant-saas"), {"project_name": "Acme SaaS"}
        )
        config.validate()
        root = generate(config, quiet=True, dry_run=True)

        # TMS control plane (the variant overlay + its hardening doc).
        assert (root / "services/tms/src/app/services/tenant_service.py").is_file()
        assert (root / "services/tms/HARDENING.md").is_file()
        # App workload carries the RLS enablement migration.
        assert (root / "services/app/alembic/versions/0002_enable_rls.py").is_file()
        # Gatekeeper edge auth + the corrected Keycloak realm + the realm-sync
        # sidecar (auto-bundled with the gatekeeper provider).
        assert (root / "infra/keycloak-realm.json").is_file()
        assert (root / "infra/gatekeeper/scripts/realm_sync.py").is_file()
        # The realm mints the tenant claim the app's RLS reads.
        realm = (root / "infra/keycloak-realm.json").read_text(encoding="utf-8")
        assert "tenant_id" in realm
        # Vue frontend present (not headless).
        assert (root / "apps/frontend/package.json").is_file()
        # Compose wires every tier of the topology.
        compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
        for svc in ("keycloak", "redis", "gatekeeper", "tms", "app"):
            assert f"{svc}:" in compose, f"compose missing service: {svc}"

    def test_persisted_in_forge_toml(self) -> None:
        config = _build_config(
            _args(platform="multitenant-saas"), {"project_name": "Acme SaaS"}
        )
        config.validate()
        root = generate(config, quiet=True, dry_run=True)
        forge_toml = (root / "forge.toml").read_text(encoding="utf-8")
        assert 'platform_template = "multitenant-saas"' in forge_toml


# --------------------------------------------------------------------------- #
# (c) PRECEDENCE — preset is the lowest config layer; user cfg overrides it
# --------------------------------------------------------------------------- #


class TestUserOverridePrecedence:
    def test_user_project_name_wins(self) -> None:
        config = _build_config(_args(platform="microservices"), {"project_name": "User Chosen"})
        assert config.project_name == "User Chosen"

    def test_user_option_overrides_preset_option(self) -> None:
        # User turns OFF a preset-enabled option; the other preset option stays.
        config = _build_config(
            _args(platform="microservices"),
            {
                "project_name": "P",
                "include_keycloak": False,
                "options": {"auth.service_discovery": False},
            },
        )
        assert config.options["auth.service_discovery"] is False
        # The preset's other option is preserved (deep-merge of options).
        assert config.options["infrastructure.event_bus"] == "postgres_notify"

    def test_user_backends_list_wins_whole_list(self) -> None:
        config = _build_config(
            _args(platform="microservices"),
            {"backends": [{"name": "solo", "language": "python"}]},
        )
        assert [b.name for b in config.backends] == ["solo"]

    def test_user_include_keycloak_wins(self) -> None:
        config = _build_config(_args(platform="monolithic"), {"include_keycloak": True})
        assert config.include_keycloak is True

    def test_cli_set_option_overrides_preset(self) -> None:
        # --set is the user CLI surface; it must beat the preset.
        config = _build_config(
            _args(
                platform="microservices",
                include_keycloak=False,
                set_options=["auth.service_discovery=false"],
            ),
            {},
        )
        assert config.options["auth.service_discovery"] is False


class TestPlatformErrors:
    def test_unknown_platform_raises_with_available(self) -> None:
        with pytest.raises(ValueError, match="Unknown platform preset"):
            _build_config(_args(platform="nope"), {})

    def test_no_platform_is_noop(self) -> None:
        # No --platform and no persisted platform_template ⇒ untouched config.
        config = _build_config(_args(platform=None), {})
        assert config.platform_template is None

    def test_persisted_platform_template_in_cfg_applies(self) -> None:
        # A forge.toml-persisted platform_template (no CLI flag) still applies.
        config = _build_config(_args(platform=None), {"platform_template": "monolithic"})
        assert config.platform_template == "monolithic"
        assert config.backends[0].name == "backend"


def test_golden_preset_dir_layout() -> None:
    """Each shipped preset ships a platform.toml under templates/platforms/."""
    root = Path(__file__).resolve().parent.parent / "forge" / "templates" / "platforms"
    for name in ("monolithic", "microservices", "headless-api", "multitenant-saas"):
        assert (root / name / "platform.toml").is_file()
