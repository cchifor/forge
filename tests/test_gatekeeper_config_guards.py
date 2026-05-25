"""Unit tests for gatekeeper config.py startup security guards.

Validates that the template-shipped ``get_settings()`` rejects insecure
defaults at boot time and emits warnings for missing optional secrets.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Load config.py directly from the template tree — it is not part of
# the ``forge`` package, so we import by file path.
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


@pytest.fixture(autouse=True)
def _fresh_module(monkeypatch, tmp_path):
    """Load a fresh copy of the config module for each test.

    Each test gets an isolated module instance so the module-level
    ``_instance`` singleton does not leak between tests.
    """
    # Create a valid signing key dir with a dummy PEM by default so
    # tests focusing on other guards don't trip the signing-key check.
    key_dir = tmp_path / "signing-keys"
    key_dir.mkdir()
    (key_dir / "dev.pem").write_text("-----BEGIN EC PRIVATE KEY-----\nfake\n")

    # Base env: provide a valid secret and point to our tmp key dir.
    monkeypatch.setenv("GATEKEEPER_CLIENT_SECRET", "test-valid-secret-value")
    monkeypatch.setenv("SIGNING_KEY_DIR", str(key_dir))
    monkeypatch.setenv("KEY_BACKEND", "file")


def _load_config_module():
    """Return a freshly-loaded config module (resets singleton).

    Each call produces a fresh module so the module-level ``_instance``
    singleton starts as None. We also call ``model_rebuild()`` because
    the module uses ``from __future__ import annotations`` which defers
    annotation evaluation — pydantic needs an explicit rebuild when
    loaded via importlib outside its original package context.
    """
    from typing import Literal

    spec = importlib.util.spec_from_file_location(
        "_gatekeeper_config_under_test", _CONFIG_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules so pydantic's namespace resolution works.
    mod_name = "_gatekeeper_config_under_test"
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
        # pydantic resolves annotations against sys.modules[cls.__module__]
        # — ensure deferred names are present.
        module.Literal = Literal
        module.Path = Path
        module.GatekeeperSettings.model_rebuild()
    finally:
        sys.modules.pop(mod_name, None)
    return module


class TestClientSecretGuard:
    """1A: get_settings() must reject empty or default client secrets."""

    def test_empty_secret_exits(self, monkeypatch):
        monkeypatch.setenv("GATEKEEPER_CLIENT_SECRET", "")
        mod = _load_config_module()
        with pytest.raises(SystemExit) as exc_info:
            mod.get_settings()
        assert exc_info.value.code == 1

    def test_default_secret_exits(self, monkeypatch):
        monkeypatch.setenv("GATEKEEPER_CLIENT_SECRET", "super-secret-string")
        mod = _load_config_module()
        with pytest.raises(SystemExit) as exc_info:
            mod.get_settings()
        assert exc_info.value.code == 1

    def test_valid_secret_passes(self, monkeypatch):
        monkeypatch.setenv("GATEKEEPER_CLIENT_SECRET", "a-proper-secret-for-prod")
        mod = _load_config_module()
        settings = mod.get_settings()
        assert settings.gatekeeper_client_secret == "a-proper-secret-for-prod"


class TestSigningKeyDirGuard:
    """2B: get_settings() must validate signing key directory."""

    def test_missing_dir_exits(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SIGNING_KEY_DIR", str(tmp_path / "nonexistent"))
        mod = _load_config_module()
        with pytest.raises(SystemExit) as exc_info:
            mod.get_settings()
        assert exc_info.value.code == 1

    def test_empty_dir_exits(self, monkeypatch, tmp_path):
        empty_dir = tmp_path / "empty-keys"
        empty_dir.mkdir()
        monkeypatch.setenv("SIGNING_KEY_DIR", str(empty_dir))
        mod = _load_config_module()
        with pytest.raises(SystemExit) as exc_info:
            mod.get_settings()
        assert exc_info.value.code == 1

    def test_dir_with_pem_passes(self, monkeypatch, tmp_path):
        key_dir = tmp_path / "good-keys"
        key_dir.mkdir()
        (key_dir / "key.pem").write_text("-----BEGIN EC PRIVATE KEY-----\nfake\n")
        monkeypatch.setenv("SIGNING_KEY_DIR", str(key_dir))
        mod = _load_config_module()
        settings = mod.get_settings()
        assert settings.signing_key_dir == key_dir

    def test_kms_backend_skips_dir_check(self, monkeypatch, tmp_path):
        """When key_backend=kms, signing_key_dir is irrelevant."""
        monkeypatch.setenv("KEY_BACKEND", "kms")
        monkeypatch.setenv("SIGNING_KEY_DIR", str(tmp_path / "nonexistent"))
        mod = _load_config_module()
        # Should not exit — kms backend does not check the directory.
        settings = mod.get_settings()
        assert settings.key_backend == "kms"


class TestSessionFernetKeyWarning:
    """2B: get_settings() warns when session_fernet_key is unset."""

    def test_none_fernet_key_warns(self, monkeypatch, caplog):
        monkeypatch.delenv("SESSION_FERNET_KEY", raising=False)
        import logging

        with caplog.at_level(logging.WARNING):
            mod = _load_config_module()
            mod.get_settings()
        assert any("SESSION_FERNET_KEY" in r.message for r in caplog.records)

    def test_set_fernet_key_no_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("SESSION_FERNET_KEY", "dGVzdC1rZXktdmFsdWU=")
        import logging

        with caplog.at_level(logging.WARNING):
            mod = _load_config_module()
            mod.get_settings()
        fernet_warnings = [
            r for r in caplog.records if "SESSION_FERNET_KEY" in r.message
        ]
        assert not fernet_warnings


class TestCookieSecureDefault:
    """1C: cookie_secure defaults to True in the template."""

    def test_cookie_secure_default_true(self, monkeypatch):
        mod = _load_config_module()
        settings = mod.get_settings()
        # Without COOKIE_SECURE env override, the model default is True.
        assert settings.cookie_secure is True
