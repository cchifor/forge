"""Invariants for the ``forge.features.auth`` Gatekeeper fragment (Phase 2).

Verifies that the platform Gatekeeper port wires through forge's fragment
registry and that the template tree contains the modules required for
Gatekeeper to function as a token authority (ES256 minting, two-key
Redis BFF sessions, /auth/jwks, /auth/token, /auth/session GET+POST,
service registry, key store, multi-issuer JWKS).

This is the "did we ship the right files" gate. Behavioural verification
(docker compose up gatekeeper-keygen + gatekeeper, curl /auth/jwks) lives
in a follow-up smoke test under ``tests/test_e2e_platform_auth.py`` once
the migration codemod (Phase 10) cuts over from the legacy gatekeeper.

Cross-reference: implementation plan at
``~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md``
(Phase 2 deliverables).
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY


# The 25 modules under src/app/gatekeeper/ that make Gatekeeper a token
# authority rather than just a ForwardAuth proxy. Phase 10 documents which
# ones are load-bearing for which subsystems.
TOKEN_AUTHORITY_MODULES = (
    "__init__.py",
    "apikeys.py",
    "apikeys_api.py",
    "config.py",
    "delegation_grant.py",
    "helpers.py",
    "http_client.py",
    "internal_token.py",
    "internal_token_cache.py",
    "jwks.py",
    "key_store.py",
    "keycloak_admin.py",
    "metrics.py",
    "oidc.py",
    "ratelimit.py",
    "redis.py",
    "routes.py",
    "routes_jwks.py",
    "routes_session.py",
    "scopes.py",
    "server_session.py",
    "service_registry.py",
    "service_token.py",
    "service_verifier.py",
    "tenant_config.py",
)


def _gatekeeper_root() -> Path:
    frag = FRAGMENT_REGISTRY["platform_auth_gatekeeper"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    return Path(impl.fragment_dir) / "files" / "infra" / "gatekeeper"


def test_platform_auth_gatekeeper_fragment_registered() -> None:
    assert "platform_auth_gatekeeper" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["platform_auth_gatekeeper"]
    # Same impl across all 3 backend languages — project-scoped, language-
    # agnostic (Gatekeeper is a self-contained Python container).
    for backend in (BackendLanguage.PYTHON, BackendLanguage.NODE, BackendLanguage.RUST):
        assert backend in frag.implementations, f"missing {backend} impl"
        assert frag.implementations[backend].scope == "project"
    # Redis is required for BFF session store + extension rate limit.
    assert "redis" in frag.capabilities


def test_gatekeeper_token_authority_modules_present() -> None:
    """All 25 src/app/gatekeeper/*.py modules from platform must be shipped."""
    gk_dir = _gatekeeper_root() / "src" / "app" / "gatekeeper"
    assert gk_dir.is_dir(), f"gatekeeper module dir missing: {gk_dir}"
    shipped = {p.name for p in gk_dir.glob("*.py")}
    missing = set(TOKEN_AUTHORITY_MODULES) - shipped
    assert not missing, f"gatekeeper modules not shipped: {sorted(missing)}"


def test_gatekeeper_keygen_script_shipped() -> None:
    """The gatekeeper-keygen init service runs scripts/keygen.py."""
    keygen = _gatekeeper_root() / "scripts" / "keygen.py"
    assert keygen.is_file(), f"scripts/keygen.py missing — gatekeeper-keygen will fail: {keygen}"


def test_gatekeeper_dockerfile_shipped() -> None:
    dockerfile = _gatekeeper_root() / "Dockerfile"
    assert dockerfile.is_file()
    text = dockerfile.read_text(encoding="utf-8")
    assert "FROM python:" in text, "Dockerfile must base on a python image"


def test_gatekeeper_config_files_shipped() -> None:
    config_dir = _gatekeeper_root() / "config"
    assert config_dir.is_dir()
    expected = {
        "default.yaml",
        "development.yaml",
        "production.yaml",
        "staging.yaml",
        "secrets.production.yaml.example",
    }
    shipped = {p.name for p in config_dir.iterdir()}
    missing = expected - shipped
    assert not missing, f"config files missing: {sorted(missing)}"


def test_gatekeeper_service_registry_seed_shipped() -> None:
    """Phase 3 will append per-backend entries; the file itself must exist."""
    registry_path = _gatekeeper_root() / "secrets" / "service_registry.yaml"
    assert registry_path.is_file(), f"service_registry.yaml seed missing: {registry_path}"


def test_gatekeeper_pyproject_targets_supported_pythons() -> None:
    """pyproject must require Python 3.11+ (forge's CI matrix floor).

    Note: the Dockerfile pins ``python:3.13-slim`` for the runtime image,
    which is independent — the container brings its own Python. This
    assertion only governs local-development pyproject + ty type-check.
    """
    pyproject = _gatekeeper_root() / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert 'requires-python = ">=3.11"' in text, (
        "pyproject must lower the >=3.13 floor from the upstream platform "
        "Gatekeeper to >=3.11 to match forge's CI matrix."
    )


def test_gatekeeper_fragments_wired_to_auth_mode() -> None:
    """Phase 2 Wave 2 cutover landed — both gatekeeper fragments are
    in ``auth.mode=generate``'s enables tuple.

    Cutover: removed the imperative gatekeeper service block from
    ``forge/templates/deploy/docker-compose.yml.j2`` and the entire
    legacy ``forge/templates/infra/gatekeeper/`` source tree. The
    gatekeeper + gatekeeper-keygen sidecars now ship via the
    declarative ``compose.yaml`` entries on these two fragments
    (registered through ``forge.services.fragment_compose``).

    Pinning the wiring here so a future regression that drops either
    fragment from ``auth.mode``'s enables map gets caught.
    """
    from forge.options import OPTION_REGISTRY

    auth_mode = OPTION_REGISTRY["auth.mode"]
    enabled = auth_mode.enables.get("generate", ())
    assert "platform_auth_gatekeeper" in enabled, (
        "platform_auth_gatekeeper fragment must be in auth.mode=generate's "
        "enables tuple after the Phase 2 Wave 2 cutover — without it, a "
        "generated project gets no gatekeeper sidecar."
    )
    assert "platform_auth_gatekeeper_keygen" in enabled, (
        "platform_auth_gatekeeper_keygen fragment must be in "
        "auth.mode=generate's enables tuple — gatekeeper depends on it "
        "(gatekeeper-keygen runs first to produce the ECDSA signing keys)."
    )


def test_gatekeeper_keygen_fragment_registered() -> None:
    """The init container that generates ECDSA P-256 signing keys.

    Same parity-tier-1 / project-scoped shape as the main fragment so
    they enter the plan together.
    """
    assert "platform_auth_gatekeeper_keygen" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["platform_auth_gatekeeper_keygen"]
    for backend in (BackendLanguage.PYTHON, BackendLanguage.NODE, BackendLanguage.RUST):
        assert backend in frag.implementations
        assert frag.implementations[backend].scope == "project"


def test_gatekeeper_main_depends_on_keygen() -> None:
    """The main service must wait on keygen so signing keys exist at boot."""
    main = FRAGMENT_REGISTRY["platform_auth_gatekeeper"]
    assert "platform_auth_gatekeeper_keygen" in main.depends_on, (
        "gatekeeper main fragment must depend on platform_auth_gatekeeper_keygen "
        "or the main process will boot before signing keys exist."
    )


def test_gatekeeper_compose_yaml_parses() -> None:
    """The declarative compose.yaml at the fragment root must load cleanly.

    Verifies the env block carries the Phase 4 invariants (gatekeeper
    sole-issuer ES256 minting) AND platform's BFF + session-timeout
    config — issuer URL, internal-token audience, key backend, idle/
    absolute timeouts, Fernet keys, service-registry path, BFF cookie.
    """
    from forge.services.fragment_compose import load_fragment_compose

    main = FRAGMENT_REGISTRY["platform_auth_gatekeeper"]
    impl = main.implementations[BackendLanguage.PYTHON]
    fragment_root = Path(impl.fragment_dir).parent
    result = load_fragment_compose(fragment_root)
    assert result is not None, f"compose.yaml missing at {fragment_root}"
    capability, tpl = result
    assert capability == "gatekeeper"
    assert tpl.name == "gatekeeper"

    # Phase 4 sole-issuer invariants — these env vars are load-bearing.
    required_env_keys = {
        "GATEKEEPER_ISSUER",
        "INTERNAL_TOKEN_AUDIENCE",
        "INTERNAL_TOKEN_TTL_SECONDS",
        "KEY_BACKEND",
        "SIGNING_KEY_DIR",
        # BFF + session-timeout invariants per platform RFC.
        "SESSION_ID_COOKIE_NAME",
        "SESSION_TIMEOUT_ENABLED",
        "DEFAULT_IDLE_TIMEOUT_SECONDS",
        "DEFAULT_ABSOLUTE_TIMEOUT_SECONDS",
        "SESSION_WARN_AT_SECONDS",
        "SESSION_FERNET_KEY",
        # Tenant claim — must be forge-namespaced, NOT platform-namespaced.
        "TENANT_ID_CLAIM",
        # /auth/token (S2S).
        "SERVICE_REGISTRY_PATH",
        "SVC_AUTH_BACKEND",
    }
    missing = required_env_keys - set(tpl.environment.keys())
    assert not missing, f"compose.yaml env missing required keys: {sorted(missing)}"
    assert tpl.environment["TENANT_ID_CLAIM"] == "https://forge/tenant_id", (
        "TENANT_ID_CLAIM must be the forge-namespaced URL, not the platform default."
    )

    # Dependencies wire keygen + redis + keycloak.
    assert "redis" in tpl.depends_on
    assert "keycloak" in tpl.depends_on
    assert "gatekeeper-keygen" in tpl.depends_on


def test_keycloak_realm_template_has_forge_tenant_id_mapper() -> None:
    """Realm template must ship the forge-namespaced tenant_id claim mapper.

    Both clients (the public SPA and the confidential gatekeeper) need
    this mapper so the access tokens they issue carry
    ``https://forge/tenant_id``. Without it, the new gatekeeper fails
    closed at AuthGuard.verify time with ``InvalidToken: missing tenant
    claim``.

    The realm template still lives at the legacy location
    (``forge/templates/infra/keycloak-realm.json.j2``) — Phase 10 relocates
    it under ``forge/features/auth/``. Until then, this test gates the
    additive change in place.
    """
    realm_template = (
        Path(__file__).resolve().parent.parent
        / "forge"
        / "templates"
        / "infra"
        / "keycloak-realm.json.j2"
    )
    assert realm_template.is_file()
    text = realm_template.read_text(encoding="utf-8")

    # The forge-namespaced claim must appear (NOT the platform default).
    assert '"https://forge/tenant_id"' in text, (
        "realm template missing the forge-namespaced tenant_id claim mapper"
    )
    assert '"https://platform/tenant_id"' not in text, (
        "realm template still uses the platform-namespaced tenant_id claim"
    )

    # Gatekeeper client must enable service accounts for S2S.
    # Find the gatekeeper client block specifically.
    gatekeeper_block_start = text.find('"clientId": "gatekeeper"')
    assert gatekeeper_block_start > 0, "gatekeeper client missing from realm"
    gatekeeper_block_end = text.find("}", text.find("]", gatekeeper_block_start))
    gatekeeper_block = text[gatekeeper_block_start:gatekeeper_block_end]
    assert '"serviceAccountsEnabled": true' in gatekeeper_block, (
        "gatekeeper client must enable service accounts (S2S)"
    )

    # Dev user must carry tenant_id attribute, otherwise tokens issued
    # to dev@localhost lack the new claim.
    assert '"tenant_id":' in text, (
        "dev user attributes must carry tenant_id so issued tokens carry "
        "the https://forge/tenant_id claim"
    )


def test_gatekeeper_keygen_compose_yaml_parses() -> None:
    """The keygen init service registers via its own compose.yaml."""
    from forge.services.fragment_compose import load_fragment_compose

    keygen = FRAGMENT_REGISTRY["platform_auth_gatekeeper_keygen"]
    impl = keygen.implementations[BackendLanguage.PYTHON]
    fragment_root = Path(impl.fragment_dir).parent
    result = load_fragment_compose(fragment_root)
    assert result is not None, f"compose.yaml missing at {fragment_root}"
    capability, tpl = result
    assert capability == "gatekeeper-keygen"
    assert tpl.name == "gatekeeper-keygen"
    assert tpl.command == ["python", "scripts/keygen.py"], (
        "keygen service must run scripts/keygen.py (the only thing it does)."
    )
    # Must mount the same signing-keys volume that the main service
    # later mounts read-only.
    assert any("gatekeeper_signing_keys" in v for v in tpl.volumes), (
        "keygen service must mount gatekeeper_signing_keys to write keys "
        "into the shared named volume."
    )
