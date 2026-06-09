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

import re
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
    "realm_invariants.py",
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
    """All src/app/gatekeeper/*.py modules from platform must be shipped."""
    gk_dir = _gatekeeper_root() / "src" / "app" / "gatekeeper"
    assert gk_dir.is_dir(), f"gatekeeper module dir missing: {gk_dir}"
    shipped = {p.name for p in gk_dir.glob("*.py")}
    missing = set(TOKEN_AUTHORITY_MODULES) - shipped
    assert not missing, f"gatekeeper modules not shipped: {sorted(missing)}"


def test_gatekeeper_realm_invariant_probe_wired() -> None:
    """The boot-time realm-invariant probe must be shipped and wired.

    ``realm_invariants.verify_user_profile_active`` converts a User-Profile
    schema drift (which would otherwise surface as a 502 on first
    self-registration) into a loud boot-time crash. It must be imported and
    invoked from the ASGI lifespan, guarded by ``gatekeeper_skip_realm_invariant``
    so offline unit/test contexts can opt out, and the supporting admin
    credentials must exist on the settings.
    """
    gk_src = _gatekeeper_root() / "src" / "app"
    probe = gk_src / "gatekeeper" / "realm_invariants.py"
    assert probe.is_file(), "realm_invariants.py not shipped"
    assert "async def verify_user_profile_active" in probe.read_text(encoding="utf-8")

    lifecycle = (gk_src / "core" / "lifecycle.py").read_text(encoding="utf-8")
    assert "verify_user_profile_active" in lifecycle, "probe not imported in lifespan"
    assert "gatekeeper_skip_realm_invariant" in lifecycle, "probe not guarded by skip flag"

    config = (gk_src / "gatekeeper" / "config.py").read_text(encoding="utf-8")
    for field in ("kc_admin_user", "kc_admin_password", "gatekeeper_skip_realm_invariant"):
        assert field in config, f"settings missing {field}"


def test_gatekeeper_keygen_script_shipped() -> None:
    """The gatekeeper-keygen init service runs scripts/keygen.py."""
    keygen = _gatekeeper_root() / "scripts" / "keygen.py"
    assert keygen.is_file(), f"scripts/keygen.py missing — gatekeeper-keygen will fail: {keygen}"


def test_keycloak_realm_sync_sidecar_wired() -> None:
    """The keycloak-realm-sync one-shot reconciles the User-Profile schema on
    every boot (Keycloak only imports once), so the gatekeeper's realm-invariant
    probe finds it present instead of crash-looping on stale pgdata."""
    from forge.options._registry import OPTION_REGISTRY

    script = _gatekeeper_root() / "scripts" / "realm_sync.py"
    assert script.is_file(), "scripts/realm_sync.py missing — realm-sync sidecar will fail"
    src = script.read_text(encoding="utf-8")
    assert "users/profile" in src and "extract_user_profile_config" in src
    # Fragment registered + pulled in whenever the gatekeeper provider is chosen.
    assert "platform_auth_gatekeeper_realm_sync" in FRAGMENT_REGISTRY
    enables = OPTION_REGISTRY["auth.provider"].enables["gatekeeper"]
    assert "platform_auth_gatekeeper_realm_sync" in enables
    # Gatekeeper waits for the sync to complete before booting.
    gk_compose = (
        Path(FRAGMENT_REGISTRY["platform_auth_gatekeeper"].implementations[BackendLanguage.PYTHON].fragment_dir).parent
        / "compose.yaml"
    ).read_text(encoding="utf-8")
    assert "keycloak-realm-sync" in gk_compose


def test_apikeys_endpoints_derive_tenant_from_verified_session() -> None:
    """The ``/api/v1/api-keys`` endpoints must derive the tenant from the
    verified server-side session (cookie -> Redis), NOT a client-supplied
    ``X-Gatekeeper-Tenant`` request header.

    The Gatekeeper is reachable directly (``compose.yaml`` maps ``5000:5000``)
    and nothing strips inbound ``X-Gatekeeper-*`` headers, so a raw header is
    trivially spoofable: a request carrying ``X-Gatekeeper-Tenant: victim``
    straight to ``:5000/api/v1/api-keys`` would mint / list / revoke keys for
    an arbitrary tenant. Tenant identity must come from a verified credential,
    matching how downstream
    services consume the verified bearer JWT (the legacy plain-header trust
    path is gone everywhere else)."""
    src = (
        _gatekeeper_root() / "src" / "app" / "gatekeeper" / "apikeys_api.py"
    ).read_text(encoding="utf-8")

    # Positive: tenant comes from the verified session store.
    assert "server_session" in src and "check_validity" in src, (
        "api-keys must resolve tenant from the verified session store "
        "(request.app.state.server_session.check_validity)"
    )
    # Negative: no endpoint accepts the spoofable tenant header as a parameter.
    assert "x_gatekeeper_tenant" not in src, (
        "api-keys must not read tenant from the client-supplied "
        "X-Gatekeeper-Tenant header (spoofable on the directly-exposed :5000)"
    )


def _apikeys_api_src() -> str:
    return (
        _gatekeeper_root() / "src" / "app" / "gatekeeper" / "apikeys_api.py"
    ).read_text(encoding="utf-8")


def test_apikeys_endpoints_enforce_admin_role() -> None:
    """The ``/api/v1/api-keys`` endpoints must require an ADMIN realm role,
    not merely an authenticated session.

    Minting / listing / revoking API keys yields tenant-wide credentials, so
    any authenticated tenant user being able to do it is a privilege-
    escalation hole. The gate reads the role set from the verified Keycloak
    access token (``realm_access.roles``, exactly as ``/auth/userinfo`` does),
    checks it against the operator-configurable ``admin_role`` setting, and
    returns 403 when the role is absent. It must FAIL CLOSED: a missing /
    expired / invalid access token denies access rather than allowing it.

    ``apikeys_api.py`` cannot be imported in forge CI (heavy runtime deps),
    so we assert on the source text, matching the sibling
    ``test_apikeys_endpoints_derive_tenant_from_verified_session``.
    """
    src = _apikeys_api_src()

    # Roles come from the verified access token, via the pure authz helper.
    assert "authz" in src and "extract_realm_roles" in src, (
        "api-keys must extract roles via the authz.extract_realm_roles helper"
    )
    assert "is_authorized" in src, (
        "api-keys must decide access via authz.is_authorized"
    )
    assert "verify_token" in src and "realm_access" in src.lower() or (
        "verify_token" in src and "extract_realm_roles" in src
    ), (
        "api-keys must verify the session access token and read realm roles "
        "(mirroring /auth/userinfo) to determine admin authorization"
    )

    # The required role is the operator-configurable admin_role setting.
    assert "admin_role" in src, (
        "api-keys must gate on the operator-configurable settings.admin_role"
    )

    # An unauthorized caller is rejected with 403.
    assert "403" in src, (
        "api-keys must return HTTP 403 when the caller lacks the admin role"
    )


def test_apikeys_state_changing_endpoints_check_origin() -> None:
    """The state-changing API-key endpoints (POST create, DELETE revoke) must
    apply a CSRF Origin/Referer check.

    The session cookie is ``SameSite=Lax`` (so deep-links keep a session),
    which still permits some cross-site state-changing requests; OWASP / the
    OAuth BCP require an explicit Origin/Referer second factor on unsafe
    methods. ``check_origin`` already exists in ``helpers.py`` and is used by
    ``GET /auth``; the api-keys POST + DELETE must reuse it and reject
    mismatches with 403.

    Read-only ``GET /api/v1/api-keys`` (list) is not state-changing and is
    not required to carry the check.
    """
    src = _apikeys_api_src()

    # The CSRF primitive must be imported from helpers and actually invoked.
    assert "check_origin" in src, (
        "api-keys must use helpers.check_origin for CSRF defense"
    )
    assert "check_origin(" in src, (
        "check_origin must be CALLED, not merely imported"
    )

    def _handler_body(decorator: str, signature: str) -> str:
        start = src.index(decorator)
        body_start = src.index(signature, start)
        nxt = src.find("@router.", body_start + 1)
        return src[body_start : nxt if nxt != -1 else len(src)]

    # Identify the name of the CSRF guard helper that wraps check_origin (the
    # implementation factors the call out of the handlers into one place).
    # Find the `def <name>(...)` whose body contains `check_origin(`.
    csrf_guards: list[str] = []
    for m in re.finditer(r"^(async )?def (\w+)\(", src, flags=re.MULTILINE):
        name = m.group(2)
        nxt = re.search(
            r"^(async )?def ", src[m.end():], flags=re.MULTILINE
        )
        fn_body = src[m.end():][: nxt.start()] if nxt else src[m.end():]
        if "check_origin(" in fn_body:
            csrf_guards.append(name)

    def _has_csrf(body: str) -> bool:
        if "check_origin(" in body:
            return True
        return any(f"{g}(" in body for g in csrf_guards)

    create_body = _handler_body('@router.post(""', "async def create_key(")
    revoke_body = _handler_body("@router.delete(", "async def revoke_key(")

    assert _has_csrf(create_body), (
        "POST create_key must run the CSRF Origin/Referer check "
        "(directly or via a guard wrapping check_origin)"
    )
    assert _has_csrf(revoke_body), (
        "DELETE revoke_key must run the CSRF Origin/Referer check "
        "(directly or via a guard wrapping check_origin)"
    )


def test_apikeys_create_bounds_role_delegation_to_admin_roles() -> None:
    """``POST /api/v1/api-keys`` must reject (422) a key whose requested roles
    exceed the creating admin's own realm roles.

    Minted-key roles become effective identity on the machine ``/auth`` track,
    so without this bound a tenant admin could escalate by issuing a key
    carrying a higher-privileged role than their own. The handler captures the
    admin's verified roles from ``_require_admin`` and gates ``body.roles``
    through ``authz.is_subset_of_roles`` before persisting.

    ``apikeys_api.py`` can't be imported in forge CI, so assert on the source
    (matching the sibling api-keys structural tests)."""
    src = _apikeys_api_src()

    # _require_admin must hand back the verified roles so create_key can bound.
    assert "admin_roles = await _require_admin(" in src, (
        "create_key must capture the admin's verified roles from _require_admin"
    )
    assert (
        "async def _require_admin(request: Request, session: ServerSession) -> list[str]:"
        in src
    ), "_require_admin must return the verified role list"

    # The delegation bound + its 422 rejection.
    assert "authz.is_subset_of_roles(body.roles, admin_roles)" in src, (
        "create_key must reject roles that exceed the admin's own via "
        "authz.is_subset_of_roles"
    )
    assert "status_code=422" in src, (
        "an over-broad role delegation must be rejected with HTTP 422"
    )


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


def test_gatekeeper_fragments_wired_to_auth_provider() -> None:
    """Both gatekeeper fragments are wired to ``auth.provider=gatekeeper``.

    The provider-discriminator split moved the token-issuer fragments out of
    ``auth.mode=generate``'s bundle (which now ships only the issuer-agnostic
    SDK + middleware) into ``auth.provider``'s enables map. ``auth.provider``
    defaults to ``gatekeeper``, so a project with ``auth.mode=generate`` (and
    no explicit provider) still gets the gatekeeper sidecars — verified to be
    byte-identical by the golden snapshots.

    Pinning the wiring here so a regression that drops either fragment from
    ``auth.provider=gatekeeper``'s enables map gets caught.
    """
    from forge.options import OPTION_REGISTRY

    auth_provider = OPTION_REGISTRY["auth.provider"]
    assert auth_provider.default == "gatekeeper", (
        "auth.provider must default to gatekeeper during the compat window so "
        "auth.mode=generate reproduces today's behaviour."
    )
    enabled = auth_provider.enables.get("gatekeeper", ())
    assert "platform_auth_gatekeeper" in enabled, (
        "platform_auth_gatekeeper fragment must be in auth.provider=gatekeeper's "
        "enables tuple — without it, a generated project gets no gatekeeper sidecar."
    )
    assert "platform_auth_gatekeeper_keygen" in enabled, (
        "platform_auth_gatekeeper_keygen fragment must be in "
        "auth.provider=gatekeeper's enables tuple — gatekeeper depends on it "
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


# ── WS-2.5: OIDC PKCE + nonce + bound state ──────────────────────────────────
#
# These are source-assertion (structural) tests — the gatekeeper modules carry
# heavy runtime deps (fastapi / redis / PyJWT) that forge CI does not install,
# so we assert on the shipped template text, exactly like the sibling
# ``test_apikeys_*`` tests above. Behavioural coverage of the pure crypto
# helpers lives in ``tests/test_gatekeeper_oidc_pkce.py`` (importlib-loaded).


def _gk_src(module: str) -> str:
    return (
        _gatekeeper_root() / "src" / "app" / "gatekeeper" / module
    ).read_text(encoding="utf-8")


def test_oidc_pkce_pure_helper_module_shipped() -> None:
    """The stdlib-only PKCE/nonce helper module must ship and stay dep-free.

    It is importlib-loaded by forge CI without fastapi/redis/PyJWT, so any
    heavy import would break the behavioural test suite.
    """
    src = _gk_src("oidc_pkce.py")
    for fn in (
        "def generate_pkce_verifier(",
        "def pkce_challenge_s256(",
        "def generate_state(",
        "def generate_nonce(",
        "def nonces_equal(",
    ):
        assert fn in src, f"oidc_pkce.py missing {fn!r}"
    # S256 must be computed from sha256 + urlsafe base64 with padding stripped.
    assert "sha256" in src and "urlsafe_b64encode" in src and 'rstrip(b"="' in src
    # Dependency-free: no heavy runtime imports.
    for forbidden in ("import fastapi", "import redis", "import jwt", "from app."):
        assert forbidden not in src, (
            f"oidc_pkce.py must stay stdlib-only — found {forbidden!r}"
        )


def test_config_has_oidc_state_envelope_ttl() -> None:
    """A configurable TTL bounds the PKCE/nonce/state envelope lifetime."""
    src = _gk_src("config.py")
    assert "oidc_state_envelope_ttl_seconds" in src, (
        "config must expose oidc_state_envelope_ttl_seconds for the bound-"
        "state envelope TTL"
    )


def test_build_login_url_accepts_pkce_and_nonce_params() -> None:
    """``build_login_url`` must forward nonce + S256 challenge to Keycloak."""
    src = _gk_src("helpers.py")
    assert "def build_login_url(" in src
    sig = src.split("def build_login_url(")[1].split(")")[0]
    assert "nonce" in sig, "build_login_url must accept a nonce parameter"
    assert "code_challenge" in sig, (
        "build_login_url must accept a code_challenge parameter"
    )
    assert "code_challenge_method" in sig, (
        "build_login_url must accept a code_challenge_method parameter"
    )
    # The challenge method must be sent as S256 (not 'plain').
    assert "S256" in src, "build_login_url must default the method to S256"


def test_exchange_code_accepts_code_verifier() -> None:
    """``exchange_code`` must send the PKCE ``code_verifier`` on token POST."""
    src = _gk_src("oidc.py")
    sig = src.split("def exchange_code(")[1].split(") -> dict")[0]
    assert "code_verifier" in sig, "exchange_code must accept a code_verifier param"
    # And it must actually be added to the token-endpoint payload.
    assert 'payload["code_verifier"]' in src or "payload['code_verifier']" in src, (
        "exchange_code must inject code_verifier into the token POST payload"
    )


def test_routes_define_bound_state_envelope_store() -> None:
    """The module must define a server-side envelope store keyed by state,
    persisted via atomic set-with-TTL using the configurable lifetime."""
    src = _gk_src("routes.py")
    # The bound-state key prefix + the Redis client are wired at module level.
    assert "gk:auth-state:" in src, (
        "routes must persist the envelope under a gk:auth-state:{state} key"
    )
    assert "get_redis" in src, "routes must use the redis client for the envelope"
    # Atomic set-with-TTL using the configurable lifetime.
    assert "oidc_state_envelope_ttl_seconds" in src
    assert "setex(" in src or "ex=" in src, (
        "envelope must be stored with a TTL (setex / ex=)"
    )
    # Single-use: the envelope is popped with an ATOMIC get-and-delete
    # (GETDEL) — never a get-then-delete TOCTOU pair.
    assert "getdel(" in src, (
        "the envelope pop must use an atomic getdel (single-use, no TOCTOU)"
    )


def test_login_handler_stores_envelope_and_sends_pkce_nonce() -> None:
    """``/auth/login`` must mint + store the bound-state envelope and send
    the S256 challenge + nonce on the authorization request.

    The minting now lives in the shared :func:`_begin_oidc_login` helper
    (WS-2.5 review fix F1) so both /auth/login and the session-expiry
    redirect share one path; we assert that path exists and does the work.
    """
    src = _gk_src("routes.py")
    # /auth/login delegates to the shared minting helper.
    login = src.split("async def auth_login(")[1].split("\nasync def ")[0]
    assert "_begin_oidc_login(" in login, (
        "/auth/login must delegate to the shared _begin_oidc_login helper"
    )

    # The shared helper mints state/nonce/verifier, stores the envelope, and
    # forwards PKCE S256 + nonce through build_login_url.
    begin = src.split("async def _begin_oidc_login(")[1].split("\n@router")[0]
    begin = begin.split("\nasync def ")[0]
    for helper in (
        "generate_state(",
        "generate_nonce(",
        "generate_pkce_verifier(",
        "pkce_challenge_s256(",
    ):
        assert helper in begin, f"_begin_oidc_login must call {helper!r}"
    assert "_store_auth_state(" in begin, (
        "_begin_oidc_login must store the bound-state envelope"
    )
    assert "code_challenge" in begin
    assert "code_challenge_method" in begin and "S256" in begin
    assert "nonce" in begin


def test_callback_pops_envelope_verifies_nonce_passes_verifier() -> None:
    """``/callback`` must pop the envelope (single-use), pass the verifier to
    the token exchange, verify the id_token nonce, and fail closed on any
    missing/expired/mismatched piece."""
    src = _gk_src("routes.py")
    cb = src.split("async def callback(")[1]

    # Looks the envelope up + deletes it (single-use) via the pop helper.
    assert "_pop_auth_state(" in cb, (
        "/callback must pop (get-then-delete) the bound-state envelope"
    )

    # Fails closed when the envelope is missing/expired.
    assert "400" in cb or "401" in cb, (
        "/callback must reject (400/401) when the envelope is missing/expired"
    )

    # The PKCE verifier from the envelope is passed to the token exchange.
    assert "code_verifier" in cb, (
        "/callback must pass the envelope's code_verifier to exchange_code"
    )

    # The id_token nonce is read and compared against the stored nonce.
    assert "id_token" in cb, "/callback must read the id_token to verify the nonce"
    assert "nonces_equal(" in cb, (
        "/callback must verify the id_token nonce against the envelope nonce"
    )


# ── WS-2.5 review fixes (structural) ─────────────────────────────────────────


def _routes_func(name: str) -> str:
    """Return the body of the top-level ``async def``/``def`` *name* in
    routes.py (up to the next top-level def/decorator)."""
    src = _gk_src("routes.py")
    marker = f"def {name}("
    body = src.split(marker, 1)[1]
    # Cut at the next top-level definition or router decorator.
    cut = len(body)
    for sep in ("\n@router", "\nasync def ", "\ndef "):
        idx = body.find(sep)
        if idx != -1:
            cut = min(cut, idx)
    return body[:cut]


def test_shared_begin_login_helper_exists() -> None:
    """F1: a single shared helper mints+stores the envelope and 302s to KC."""
    src = _gk_src("routes.py")
    assert "async def _begin_oidc_login(" in src, (
        "a shared _begin_oidc_login helper must own the envelope-minting path"
    )
    begin = _routes_func("_begin_oidc_login")
    # The helper actually mints + stores + sends the PKCE/nonce/state.
    assert "_store_auth_state(" in begin
    assert "generate_state(" in begin
    assert "generate_nonce(" in begin
    assert "generate_pkce_verifier(" in begin
    assert "code_challenge" in begin


def test_session_expiry_redirect_mints_envelope() -> None:
    """F1 CRITICAL: the session-miss/expiry redirect must funnel through the
    shared minting helper so /callback's envelope requirement is satisfied —
    it must NOT build a bare login URL that bypasses _store_auth_state."""
    src = _gk_src("routes.py")
    redirect = _routes_func("_redirect_to_login")
    assert "_begin_oidc_login(" in redirect, (
        "_redirect_to_login must delegate to _begin_oidc_login (envelope mint)"
    )
    # It must be async (it awaits the minting helper) ...
    assert "async def _redirect_to_login(" in src
    # ... and every caller must await it.
    assert "_redirect_to_login(request" in src
    non_await = src.count(
        "return _redirect_to_login(request, tenant, forwarded_host, tc=tc)"
    )
    assert non_await == 0, "all _redirect_to_login call sites must be awaited"
    await_calls = src.count(
        "await _redirect_to_login(request, tenant, forwarded_host, tc=tc)"
    )
    assert await_calls >= 5, "expected the auth/refresh call sites to be awaited"


def test_no_bare_login_url_bypasses_envelope() -> None:
    """No caller may build a login URL keyed on the raw return URI — that was
    the pre-WS-2.5 bypass that skipped the bound-state envelope."""
    src = _gk_src("routes.py")
    assert "state=original_uri" not in src
    assert "state=return_uri" not in src
    assert "state=safe_redirect" not in src


def test_begin_login_store_failure_returns_503() -> None:
    """F5: a store/redis failure while persisting auth state must surface as a
    503, never a leaked 500."""
    begin = _routes_func("_begin_oidc_login")
    assert "try:" in begin and "except" in begin, (
        "_begin_oidc_login must guard _store_auth_state with try/except"
    )
    assert "503" in begin, "store failure must return 503"


def test_pop_auth_state_is_atomic_single_use() -> None:
    """F2 HIGH: the pop must use an atomic getdel, not get-then-delete."""
    pop = _routes_func("_pop_auth_state")
    assert "getdel(" in pop, "_pop_auth_state must use atomic getdel"
    assert "redis.get(" not in pop or "getdel" in pop
    assert "redis.delete(" not in pop, (
        "_pop_auth_state must not do a separate delete (TOCTOU)"
    )


def test_callback_rejects_empty_code_verifier_and_nonce() -> None:
    """F3 + F4: missing/empty code_verifier or nonce must fail closed — no
    empty-string defaults reaching exchange_code / nonces_equal."""
    src = _gk_src("routes.py")
    assert 'envelope.get("code_verifier", "")' not in src
    assert 'envelope.get("nonce", "")' not in src
    assert "envelope_code_verifier(" in src
    assert "envelope_nonce(" in src


def test_corrupt_envelope_log_includes_state_and_exc() -> None:
    """F7: the corrupt-envelope warning must include the state and exception."""
    pop = _routes_func("_pop_auth_state")
    assert "Corrupt auth-state envelope for state=%s" in pop
    # state + exc are interpolated into the message.
    tail = pop.split("Corrupt auth-state envelope", 1)[1]
    assert "state" in tail and "exc" in tail


def test_build_login_url_method_default_none() -> None:
    """F6: code_challenge_method defaults to None and is only emitted when both
    the challenge and the method are provided."""
    src = _gk_src("helpers.py")
    assert "code_challenge_method: str | None = None" in src
    assert (
        "if code_challenge is not None and code_challenge_method is not None:" in src
    ), "build_login_url must require BOTH challenge and method before appending"


def test_oidc_pkce_envelope_extractors_shipped() -> None:
    """F3/F4: the fail-closed envelope extractors ship in the pure module."""
    src = _gk_src("oidc_pkce.py")
    assert "def envelope_code_verifier(" in src
    assert "def envelope_nonce(" in src
    # nonces_equal must reject empty/empty (not just None).
    eq = src.split("def nonces_equal(", 1)[1].split("\ndef ", 1)[0]
    assert "if not expected or not actual:" in eq, (
        "nonces_equal must fail closed on empty strings, not only None"
    )


def test_redis_client_exposes_atomic_getdel() -> None:
    """F2: the resilient client + in-memory fallback + pipelines expose an
    atomic getdel so single-use semantics hold across all backends."""
    src = _gk_src("redis.py")
    # InMemoryStore + ResilientRedis both define async getdel.
    assert src.count("async def getdel(") >= 2, (
        "both InMemoryStore and ResilientRedis must define async getdel"
    )
    # Pipelines (sync command builders) expose getdel too.
    assert "def getdel(self, key: str) -> InMemoryPipeline:" in src
    assert "def getdel(self, key: str) -> ResilientPipeline:" in src
