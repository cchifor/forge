"""Verify that the gatekeeper config template ships secure defaults.

The config.py template runs in generated projects (not in forge's test
env), so we verify template content rather than importing it.  Behavioral
validation happens in e2e/smoke tests that actually start the gatekeeper.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "forge"
    / "features"
    / "auth"
    / "templates"
    / "platform_auth_gatekeeper"
    / "all"
    / "files"
    / "infra"
    / "gatekeeper"
    / "src"
    / "app"
    / "gatekeeper"
    / "config.py"
)


def _read() -> str:
    return _CONFIG_PATH.read_text(encoding="utf-8")


class TestSecureDefaults:
    """1A/1C: template ships with secure-by-default values."""

    def test_no_hardcoded_client_secret(self):
        src = _read()
        # The field must default to empty (no baked-in secret). Check the field
        # default precisely rather than scanning for the substring anywhere — the
        # WS-2.4 dev-secret guard legitimately *names* the insecure placeholders
        # in a denylist to REJECT them, which a broad substring scan would
        # mistake for a hardcoded default.
        assert 'gatekeeper_client_secret: str = ""' in src
        assert 'gatekeeper_client_secret: str = "super-secret-string"' not in src
        assert 'gatekeeper_client_secret: str = "gatekeeper-dev-secret"' not in src

    def test_cookie_secure_defaults_true(self):
        src = _read()
        assert "cookie_secure: bool = True" in src


class TestStartupGuards:
    """1A/2B: get_settings() validates secrets and signing keys at boot."""

    def test_client_secret_guard_present(self):
        src = _read()
        fn = src.split("def get_settings")[1]
        assert "sys.exit(1)" in fn or "_sys.exit(1)" in fn
        assert "GATEKEEPER_CLIENT_SECRET" in fn
        assert "super-secret-string" in fn

    def test_signing_key_dir_guard_present(self):
        src = _read()
        fn = src.split("def get_settings")[1]
        assert "signing_key_dir" in fn
        assert ".pem" in fn
        assert "sys.exit(1)" in fn or "_sys.exit(1)" in fn

    def test_session_fernet_key_warning_present(self):
        src = _read()
        fn = src.split("def get_settings")[1]
        assert "session_fernet_key" in fn
        assert "warning" in fn.lower() or ".warning(" in fn


class TestDevSecretProdGuard:
    """WS-2.4: a production-like env must refuse to boot with the dev sentinels
    the dev compose ships (client secret, both Fernet keys, COOKIE_SECURE=false,
    the preshared S2S backend). Mirrors the python-service prod secret guard.

    config.py runs in generated projects, not forge CI, so we assert on the
    template source (same idiom as the rest of this file)."""

    def test_dev_secret_sentinels_include_shipped_compose_values(self):
        src = _read()
        # The exact values shipped in platform_auth_gatekeeper/compose.yaml.
        assert "gatekeeper-dev-secret" in src
        assert "L9dXzDhHXxIbDpzmUrNSCMUgCl0rYmQ6j6lwtWXH_A4=" in src
        assert "UVEc0SmYvD9UcwKTlz_fMTusqFVVTNLliJ96ChlPDCI=" in src

    def test_guard_is_env_gated_with_prod_fallback_and_exemptions(self):
        fn = _read().split("def get_settings")[1]
        # Resolve env the same way the python-service guard does.
        assert 'getenv("ENV"' in fn and 'getenv("ENVIRONMENT"' in fn
        assert '"production"' in fn  # fail-closed default when unset
        for env in ("development", "dev", "local", "test", "testing"):
            assert env in _read(), f"exempt env {env!r} missing from the guard"

    def test_guard_rejects_insecure_cookie_and_preshared_in_prod(self):
        fn = _read().split("def get_settings")[1]
        assert "cookie_secure" in fn
        assert "preshared" in fn
        # The dev-secret guard must fail closed (process exit), not just warn.
        assert fn.count("_sys.exit(1)") >= 3, (
            "the prod dev-secret guard must exit on bad secret / cookie / backend"
        )

    def _dev_compose(self):
        feature_root = next(
            p
            for p in _CONFIG_PATH.parents
            if p.name == "platform_auth_gatekeeper"
        )
        compose = feature_root / "compose.yaml"
        assert compose.is_file(), compose
        return compose.read_text(encoding="utf-8")

    def test_compose_still_ships_dev_values_for_local_use(self):
        # Sanity: the dev compose intentionally keeps the dev values (the guard
        # only rejects them in prod), so the two stay in sync.
        assert "gatekeeper-dev-secret" in self._dev_compose()

    def test_dev_compose_pins_env_development(self):
        # CRITICAL: the gatekeeper image bakes ENV=production (Dockerfile), and
        # the guard treats an unset env as production. The dev compose ships the
        # dev sentinels, so it MUST pin ENV=development or `docker compose up`
        # would hit the prod guard and refuse to boot. (Parity with the Rust
        # service compose, which pins ENV=development for the same reason.)
        text = self._dev_compose()
        assert ('ENV: "development"' in text) or ("ENV: development" in text), (
            "gatekeeper dev compose must set ENV=development so the prod "
            "dev-secret guard does not break local `docker compose up`"
        )


class TestRealmSyncSidecarProdGuard:
    """The keycloak-realm-sync one-shot reuses the gatekeeper image (which
    bakes ENV=production) and realm_sync.py fails closed when env is a prod
    posture and KC_ADMIN_PASSWORD is the shipped dev default. Every sidecar
    compose template that ships the dev password must therefore also pin a
    dev ENV, or every generated Keycloak stack refuses `docker compose up`
    out of the box (the 2026-06-09/10 nightly regression)."""

    def _sidecar_compose(self) -> str:
        templates_root = next(
            p for p in _CONFIG_PATH.parents if p.name == "templates"
        )
        compose = (
            templates_root / "platform_auth_gatekeeper_realm_sync" / "compose.yaml"
        )
        assert compose.is_file(), compose
        return compose.read_text(encoding="utf-8")

    def test_sidecar_ships_dev_password_for_local_use(self):
        # Sanity: the sidecar intentionally keeps the dev admin password (the
        # guard only rejects it in prod), so the two must stay in sync.
        assert 'KC_ADMIN_PASSWORD: "admin"' in self._sidecar_compose()

    def test_sidecar_pins_env_development(self):
        text = self._sidecar_compose()
        assert ('ENV: "development"' in text) or ("ENV: development" in text), (
            "keycloak-realm-sync compose must pin ENV=development: the "
            "gatekeeper image bakes ENV=production, so without the pin the "
            "realm_sync.py fail-closed guard rejects the shipped dev "
            "KC_ADMIN_PASSWORD and every generated Keycloak stack fails "
            "`docker compose up`"
        )

    def test_guard_env_pin_satisfies_dev_envs(self):
        # Tie the compose pin to the guard's own allow-list so a rename of
        # either side fails this test instead of regressing compose-up.
        gatekeeper_root = next(
            p
            for p in _CONFIG_PATH.parents
            if p.name == "gatekeeper" and (p / "scripts").is_dir()
        )
        script = (gatekeeper_root / "scripts" / "realm_sync.py").read_text(
            encoding="utf-8"
        )
        dev_envs_literal = script.split("_DEV_ENVS")[1].split("})")[0]
        assert '"development"' in dev_envs_literal, (
            "realm_sync.py _DEV_ENVS must include 'development' (the value "
            "pinned by the realm-sync sidecar compose template)"
        )


class TestGatekeeperCorsProdGuard:
    """The gatekeeper IS the auth/BFF edge, so a reflected-origin + credentials
    CORS posture is especially dangerous here. The CorsConfig must refuse
    allow_origins=['*'] + allow_credentials=True in production (parity with the
    generated service guard)."""

    def _load_domain(self):
        import importlib.util

        domain = (
            next(
                p
                for p in _CONFIG_PATH.parents
                if p.name == "gatekeeper" and p.parent.name == "infra"
            )
            / "src"
            / "app"
            / "core"
            / "config"
            / "domain.py"
        )
        spec = importlib.util.spec_from_file_location("_gk_domain_under_test", domain)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _cors(self, mod, **over):
        kwargs = dict(
            enabled=True,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            max_age=600,
        )
        kwargs.update(over)
        return mod.CorsConfig(**kwargs)

    def test_wildcard_credentials_rejected_in_prod(self, monkeypatch):
        mod = self._load_domain()
        monkeypatch.setenv("ENV", "production")
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            self._cors(mod)

    def test_wildcard_credentials_allowed_in_dev(self, monkeypatch):
        mod = self._load_domain()
        monkeypatch.setenv("ENV", "development")
        self._cors(mod)  # no raise

    def test_disabled_cors_is_never_rejected(self, monkeypatch):
        mod = self._load_domain()
        monkeypatch.setenv("ENV", "production")
        self._cors(mod, enabled=False)  # no raise

    def test_explicit_origins_allowed_in_prod(self, monkeypatch):
        mod = self._load_domain()
        monkeypatch.setenv("ENV", "production")
        self._cors(mod, allow_origins=["https://app.example.com"])  # no raise
