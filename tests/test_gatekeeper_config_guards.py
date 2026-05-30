"""Verify that the gatekeeper config template ships secure defaults.

The config.py template runs in generated projects (not in forge's test
env), so we verify template content rather than importing it.  Behavioral
validation happens in e2e/smoke tests that actually start the gatekeeper.
"""

from __future__ import annotations

from pathlib import Path

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
