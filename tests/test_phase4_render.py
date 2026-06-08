"""Phase 4 (P4.2) — multi-service platform-synthesis RENDER coherence.

P4.1 computed the cross-service S2S graph; P4.2 wires it into the renderers so a
``auth.service_discovery=true`` multi-service project emits real artifacts: the
gatekeeper ``service_registry.yaml`` (argon2id-hashed S2S secrets + audiences),
per-service Keycloak realm clients, and per-backend compose env
(``GATEKEEPER_CLIENT_*`` + ``INTERNAL_SERVICE_URL_*`` + optional event-bus URL).

These tests generate a real 3-backend project (gateway -> {orders, inventory})
through the actual generator and assert the rendered artifacts are coherent —
crucially the in-process hash<->plaintext S2S proof: the plaintext forge injects
into a caller's compose ``GATEKEEPER_CLIENT_SECRET`` verifies against the
argon2id ``secret_hash`` forge writes to the gatekeeper registry. Full
cross-LANGUAGE / live-docker S2S smoke is deferred to P4.5.

The byte-identity contract (synthesis OFF == today) is the golden snapshots'
job (``tests/test_golden_snapshots.py``); this file pins the synthesis-ON shape.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml
from argon2 import PasswordHasher

from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.generator import generate


def _shop_config(*, output_dir: str, event_bus: str = "none") -> ProjectConfig:
    """A 3-backend shop with S2S synthesis on: gateway -> {orders, inventory}."""
    options: dict[str, object] = {"auth.service_discovery": True}
    if event_bus != "none":
        options["infrastructure.event_bus"] = event_bus
    return ProjectConfig(
        project_name="Shop",
        output_dir=output_dir,
        backends=[
            BackendConfig(
                name="gateway",
                project_name="Shop",
                language=BackendLanguage.PYTHON,
                server_port=5010,
                depends_on=["orders", "inventory"],
            ),
            BackendConfig(
                name="orders",
                project_name="Shop",
                language=BackendLanguage.PYTHON,
                server_port=5020,
            ),
            BackendConfig(
                name="inventory",
                project_name="Shop",
                language=BackendLanguage.PYTHON,
                server_port=5030,
            ),
        ],
        include_keycloak=True,
        options=options,
    )


def _generate_shop(tmp_path: Path, *, event_bus: str = "none") -> Path:
    cfg = _shop_config(output_dir=str(tmp_path), event_bus=event_bus)
    cfg.validate()
    return Path(generate(cfg, quiet=True, dry_run=True))


def _load_vendored_registry_model(project_root: Path):
    """Import the ``ServiceRegistry`` pydantic model from the GENERATED tree.

    The gatekeeper fragment ships its own registry schema at
    ``infra/gatekeeper/src/app/gatekeeper/service_registry.py`` with
    ``extra='forbid'``. Importing it from the generated project (rather than
    duplicating the model here) is the honest conformance check: the YAML forge
    emits must validate against the very model the running gatekeeper loads it
    with. The module is registered in ``sys.modules`` so pydantic can resolve
    the ``ServiceClient`` forward reference during ``model_rebuild()``.
    """
    schema = project_root / "infra" / "gatekeeper" / "src" / "app" / "gatekeeper"
    schema = schema / "service_registry.py"
    spec = importlib.util.spec_from_file_location("forge_test_gk_registry", schema)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["forge_test_gk_registry"] = module
    try:
        spec.loader.exec_module(module)
        module.ServiceRegistry.model_rebuild()
        return module.ServiceRegistry
    finally:
        sys.modules.pop("forge_test_gk_registry", None)


def _gateway_compose_secret(compose_text: str) -> str:
    """Extract gateway's plaintext GATEKEEPER_CLIENT_SECRET from compose.

    The gateway backend is the first service rendered, so the FIRST
    ``GATEKEEPER_CLIENT_SECRET`` (paired with ``svc-gateway``) is its own. The
    realm's confidential ``gatekeeper`` client uses a different literal
    (``gatekeeper-dev-secret``), and is matched defensively by anchoring on the
    preceding ``svc-gateway`` client id.
    """
    block = compose_text.split('GATEKEEPER_CLIENT_ID: "svc-gateway"', 1)[1]
    match = re.search(r'GATEKEEPER_CLIENT_SECRET: "([^"]+)"', block)
    assert match is not None, "gateway GATEKEEPER_CLIENT_SECRET not found in compose"
    return match.group(1)


# -- (a) the gatekeeper S2S service registry ---------------------------------


def test_service_registry_exists_and_validates_against_vendored_model(tmp_path: Path) -> None:
    root = _generate_shop(tmp_path)
    registry_path = root / "infra" / "gatekeeper" / "secrets" / "service_registry.yaml"
    assert registry_path.is_file(), "synthesized service_registry.yaml not rendered"

    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert raw is not None

    ServiceRegistry = _load_vendored_registry_model(root)
    registry = ServiceRegistry.model_validate(raw)

    # client_ids == one svc-<name> per backend.
    assert set(registry.client_ids) == {"svc-gateway", "svc-orders", "svc-inventory"}

    # gateway's audiences mirror its depends_on edges, scopes sorted.
    gateway = registry.lookup("svc-gateway")
    assert gateway is not None
    assert {aud: cfg.scopes for aud, cfg in gateway.audiences.items()} == {
        "svc-orders": ["orders:read", "orders:write"],
        "svc-inventory": ["inventory:read", "inventory:write"],
    }
    # Leaf services declare no edges -> empty audiences.
    orders = registry.lookup("svc-orders")
    assert orders is not None
    assert orders.audiences == {}

    # k8s_subject uses the project slug + backend name.
    assert gateway.k8s_subject == "system:serviceaccount:shop:gateway"
    # No plaintext leaks into the registry — only the argon2id hash.
    assert gateway.secret_hash is not None
    assert gateway.secret_hash.startswith("$argon2id$")


def test_service_registry_loud_dev_header(tmp_path: Path) -> None:
    root = _generate_shop(tmp_path)
    text = (root / "infra" / "gatekeeper" / "secrets" / "service_registry.yaml").read_text(
        encoding="utf-8"
    )
    assert text.startswith(
        "# DEV-ONLY synthesized S2S secrets — rotate before any non-local deployment."
    )
    # Per-service plaintext documented for onboarding (mirrors baseline style).
    assert "DEV SECRETS DOCUMENTED HERE FOR ONBOARDING" in text
    assert "svc-gateway" in text


# -- (b) the Keycloak realm svc clients --------------------------------------


def test_keycloak_realm_has_service_clients(tmp_path: Path) -> None:
    root = _generate_shop(tmp_path)
    realm = json.loads((root / "infra" / "keycloak-realm.json").read_text(encoding="utf-8"))

    by_id = {c["clientId"]: c for c in realm["clients"]}
    assert {"svc-gateway", "svc-orders", "svc-inventory"} <= set(by_id)
    for cid in ("svc-gateway", "svc-orders", "svc-inventory"):
        client = by_id[cid]
        assert client["serviceAccountsEnabled"] is True
        assert client["publicClient"] is False
        assert client["standardFlowEnabled"] is False
        assert client["clientAuthenticatorType"] == "client-secret"
        assert client["secret"]  # plaintext S2S secret for the realm client


# -- (c) per-backend compose env ---------------------------------------------


def test_compose_injects_s2s_env_per_backend(tmp_path: Path) -> None:
    root = _generate_shop(tmp_path)
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    # Each backend has its own client id.
    for name in ("gateway", "orders", "inventory"):
        assert f'GATEKEEPER_CLIENT_ID: "svc-{name}"' in compose

    # gateway reaches its two dependencies via INTERNAL_SERVICE_URL_*.
    assert 'INTERNAL_SERVICE_URL_ORDERS: "http://orders:5020"' in compose
    assert 'INTERNAL_SERVICE_URL_INVENTORY: "http://inventory:5030"' in compose

    # Shared token endpoint on every backend.
    assert compose.count('GATEKEEPER_TOKEN_ENDPOINT: "http://gatekeeper:5000/auth/token"') >= 3


# -- (d) in-process hash<->plaintext S2S coherence ---------------------------


def test_hash_plaintext_coherence(tmp_path: Path) -> None:
    """The honest in-process S2S mint/verify proof for P4.2 (no docker).

    gateway's compose plaintext GATEKEEPER_CLIENT_SECRET must verify against
    svc-gateway's argon2id secret_hash in the registry — exactly what the
    gatekeeper does on a token request.
    """
    root = _generate_shop(tmp_path)

    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    plaintext = _gateway_compose_secret(compose)

    raw = yaml.safe_load(
        (root / "infra" / "gatekeeper" / "secrets" / "service_registry.yaml").read_text(
            encoding="utf-8"
        )
    )
    secret_hash = next(s["secret_hash"] for s in raw["services"] if s["client_id"] == "svc-gateway")

    # PasswordHasher.verify raises on mismatch; returns True on match.
    assert PasswordHasher().verify(secret_hash, plaintext) is True


# -- (e) event bus wiring ----------------------------------------------------


def test_event_bus_postgres_notify_wires_db_and_env(tmp_path: Path) -> None:
    root = _generate_shop(tmp_path, event_bus="postgres_notify")

    # init-db.sh provisions the shared events database.
    init_db = (root / "init-db.sh").read_text(encoding="utf-8")
    assert "events" in init_db
    assert "CREATE DATABASE events" in init_db

    # Every backend gets the bus URL.
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    bus_url = 'APP__EVENTS__BUS_URL: "postgresql://postgres:postgres@postgres:5432/events"'
    assert compose.count(bus_url) >= 3


def test_event_bus_off_emits_no_bus_url(tmp_path: Path) -> None:
    root = _generate_shop(tmp_path, event_bus="none")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "APP__EVENTS__BUS_URL" not in compose
    init_db = (root / "init-db.sh").read_text(encoding="utf-8")
    assert "CREATE DATABASE events" not in init_db


# -- (f) validation: service_discovery requires the gatekeeper provider ------


@pytest.mark.parametrize("provider", ["in_memory", "oidc_generic", "none"])
def test_validate_requires_gatekeeper_provider(provider: str) -> None:
    cfg = ProjectConfig(
        project_name="Shop",
        backends=[
            BackendConfig(
                name="gateway",
                project_name="Shop",
                language=BackendLanguage.PYTHON,
                server_port=5010,
                depends_on=["orders"],
            ),
            BackendConfig(
                name="orders",
                project_name="Shop",
                language=BackendLanguage.PYTHON,
                server_port=5020,
            ),
        ],
        include_keycloak=True,
        options={"auth.service_discovery": True, "auth.provider": provider},
    )
    with pytest.raises(ValueError, match="requires auth.provider=gatekeeper"):
        cfg.validate()


def test_validate_passes_with_default_gatekeeper_provider() -> None:
    # No explicit auth.provider -> defaults to gatekeeper -> valid.
    cfg = ProjectConfig(
        project_name="Shop",
        backends=[
            BackendConfig(
                name="gateway",
                project_name="Shop",
                language=BackendLanguage.PYTHON,
                server_port=5010,
                depends_on=["orders"],
            ),
            BackendConfig(
                name="orders",
                project_name="Shop",
                language=BackendLanguage.PYTHON,
                server_port=5020,
            ),
        ],
        include_keycloak=True,
        options={"auth.service_discovery": True},
    )
    cfg.validate()  # must not raise
