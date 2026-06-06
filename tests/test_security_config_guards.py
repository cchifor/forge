"""Verify that MCP audit and domain config templates ship secure defaults.

Some checks verify template content (grep). The behavioural checks below
actually load the template ``domain.py`` (with a stubbed ``forge_core``) and
exercise ``SecurityConfig`` so a secret that *looks* overridden but is
really a shipped placeholder is caught — a content grep cannot do that.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_MCP_AUDIT_PATH = (
    Path(__file__).resolve().parent.parent
    / "forge"
    / "features"
    / "platform"
    / "templates"
    / "mcp_server"
    / "python"
    / "files"
    / "src"
    / "app"
    / "mcp"
    / "audit.py"
)

_DOMAIN_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "forge"
    / "templates"
    / "services"
    / "python-service-template"
    / "template"
    / "src"
    / "app"
    / "core"
    / "config"
    / "domain.py"
)


class TestMcpSigningKeyGuard:
    """1B: _secret() must fail in production when key is unset."""

    def test_raises_runtime_error_in_prod(self):
        src = _MCP_AUDIT_PATH.read_text(encoding="utf-8")
        fn = src.split("def _secret")[1].split("\ndef ")[0]
        assert "RuntimeError" in fn
        assert "MCP_APPROVAL_SIGNING_KEY" in fn

    def test_no_otel_service_name_fallback(self):
        src = _MCP_AUDIT_PATH.read_text(encoding="utf-8")
        fn = src.split("def _secret")[1].split("\ndef ")[0]
        assert "OTEL_SERVICE_NAME" not in fn

    def test_no_forge_service_hardcoded_fallback(self):
        src = _MCP_AUDIT_PATH.read_text(encoding="utf-8")
        fn = src.split("def _secret")[1].split("\ndef ")[0]
        assert '"forge-service"' not in fn

    def test_secret_evaluated_eagerly_at_module_scope(self):
        src = _MCP_AUDIT_PATH.read_text(encoding="utf-8")
        assert "_SIGNING_SECRET = _secret()" in src

    def test_defaults_to_production_posture(self):
        src = _MCP_AUDIT_PATH.read_text(encoding="utf-8")
        fn = src.split("def _secret")[1].split("\ndef ")[0]
        assert '"production"' in fn


class TestDomainSecretKeyGuard:
    """1A: SecurityConfig must reject CHANGEME in production."""

    def test_changeme_validator_present(self):
        src = _DOMAIN_CONFIG_PATH.read_text(encoding="utf-8")
        assert "CHANGEME" in src
        assert "model_validator" in src or "field_validator" in src

    def test_env_check_present(self):
        src = _DOMAIN_CONFIG_PATH.read_text(encoding="utf-8")
        cls = src.split("class SecurityConfig")[1].split("\nclass ")[0]
        assert "ENV" in cls or "ENVIRONMENT" in cls
        assert "development" in cls


def _load_domain_module() -> types.ModuleType:
    """Load the template ``domain.py`` with a stubbed ``forge_core`` dependency.

    The template imports ``from forge_core.domain.config import AuthConfig``;
    the vendored ``forge_core`` package only exists in a generated project's
    ``sdks/forge-core/`` tree, so we inject a minimal pydantic stub mirroring
    the generic ``AuthConfig`` (P5 block 1c/1e) — the domain validator only
    reads ``enabled`` and ``client_secret``.
    """
    from pydantic import BaseModel, ConfigDict

    class _AuthConfig(BaseModel):
        model_config = ConfigDict(extra="allow")

        enabled: bool = False
        client_secret: str = ""

    pkg_config = types.ModuleType("forge_core.domain.config")
    pkg_config.AuthConfig = _AuthConfig
    for name in ("forge_core", "forge_core.domain"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["forge_core.domain.config"] = pkg_config

    spec = importlib.util.spec_from_file_location("_forge_template_domain", _DOMAIN_CONFIG_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The exact placeholder shipped by config/default.yaml.jinja:29.
_DEFAULT_YAML_PATH = (
    Path(__file__).resolve().parent.parent
    / "forge"
    / "templates"
    / "services"
    / "python-service-template"
    / "template"
    / "config"
    / "default.yaml.jinja"
)


def _shipped_secret_placeholder() -> str:
    for line in _DEFAULT_YAML_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("secret_key:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    raise AssertionError("secret_key not found in default.yaml.jinja")


class TestDomainSecretKeyBehavioural:
    """2.1: SecurityConfig must fail closed on the ACTUAL shipped placeholder.

    A grep for ``"CHANGEME"`` passes today even though the shipped default is
    ``"CHANGEME-use-a-real-secret-in-production"`` (!= "CHANGEME"), so the
    fail-closed guard is bypassed. These tests exercise the real validator.
    """

    def _security_config(self, module, auth=None, **kwargs):
        if auth is None:
            auth = module.AuthConfig()
        return module.SecurityConfig(auth=auth, **kwargs)

    _STRONG = "b3b1f2c0d4e5a6978899aabbccddeeff00112233445566778899aabbccddeeff"

    def test_rejects_shipped_placeholder_in_prod(self, monkeypatch):
        monkeypatch.setenv("ENV", "production")
        module = _load_domain_module()
        with pytest.raises(ValueError):
            self._security_config(module, secret_key="CHANGEME-use-a-real-secret-in-production")

    def test_default_yaml_placeholder_is_rejected(self, monkeypatch):
        """The value config/default.yaml.jinja actually ships must fail closed."""
        monkeypatch.setenv("ENV", "production")
        module = _load_domain_module()
        with pytest.raises(ValueError):
            self._security_config(module, secret_key=_shipped_secret_placeholder())

    def test_rejects_empty_secret_in_prod(self, monkeypatch):
        monkeypatch.setenv("ENV", "production")
        module = _load_domain_module()
        with pytest.raises(ValueError):
            self._security_config(module, secret_key="")

    def test_accepts_strong_secret_in_prod(self, monkeypatch):
        monkeypatch.setenv("ENV", "production")
        module = _load_domain_module()
        cfg = self._security_config(
            module, secret_key="b3b1f2c0d4e5a6978899aabbccddeeff00112233445566778899aabbccddeeff"
        )
        assert cfg.secret_key.startswith("b3b1")

    def test_allows_placeholder_in_dev(self, monkeypatch):
        """Dev UX must be unaffected — placeholders are fine outside prod."""
        monkeypatch.setenv("ENV", "development")
        module = _load_domain_module()
        cfg = self._security_config(module, secret_key="CHANGEME-use-a-real-secret-in-production")
        assert cfg.secret_key.startswith("CHANGEME")

    def test_allows_placeholder_in_testing_env(self, monkeypatch):
        """The generated test harness sets ENV=testing (conftest.py) — its own
        suite must not break on the shipped placeholder."""
        monkeypatch.setenv("ENV", "testing")
        module = _load_domain_module()
        cfg = self._security_config(module, secret_key="CHANGEME-use-a-real-secret-in-production")
        assert cfg.secret_key.startswith("CHANGEME")

    def test_rejects_too_short_secret_in_prod(self, monkeypatch):
        monkeypatch.setenv("ENV", "production")
        module = _load_domain_module()
        with pytest.raises(ValueError):
            self._security_config(module, secret_key="short-but-not-changeme")

    def test_rejects_whitespace_only_secret_in_prod(self, monkeypatch):
        monkeypatch.setenv("ENV", "production")
        module = _load_domain_module()
        with pytest.raises(ValueError):
            self._security_config(module, secret_key="   ")

    def test_rejects_placeholder_client_secret_when_auth_enabled_in_prod(self, monkeypatch):
        """production.yaml enables auth; default.yaml ships client_secret='changeme'."""
        monkeypatch.setenv("ENV", "production")
        module = _load_domain_module()
        auth = module.AuthConfig(enabled=True, client_secret="changeme")
        with pytest.raises(ValueError):
            self._security_config(module, auth=auth, secret_key=self._STRONG)

    def test_accepts_real_client_secret_when_auth_enabled_in_prod(self, monkeypatch):
        monkeypatch.setenv("ENV", "production")
        module = _load_domain_module()
        auth = module.AuthConfig(enabled=True, client_secret="a-real-issued-client-secret")
        cfg = self._security_config(module, auth=auth, secret_key=self._STRONG)
        assert cfg.auth.client_secret == "a-real-issued-client-secret"

    def test_ignores_placeholder_client_secret_when_auth_disabled(self, monkeypatch):
        """client_secret is irrelevant when auth is off — don't over-reject."""
        monkeypatch.setenv("ENV", "production")
        module = _load_domain_module()
        auth = module.AuthConfig(enabled=False, client_secret="changeme")
        cfg = self._security_config(module, auth=auth, secret_key=self._STRONG)
        assert cfg.auth.enabled is False
