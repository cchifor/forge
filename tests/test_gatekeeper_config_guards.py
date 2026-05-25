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
        assert 'gatekeeper_client_secret: str = ""' in src
        assert "super-secret-string" not in src.split("get_settings")[0]

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
