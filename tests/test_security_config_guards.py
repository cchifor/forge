"""Verify that MCP audit and domain config templates ship secure defaults.

Template files run in generated projects, so we verify template content
rather than importing them.
"""

from __future__ import annotations

from pathlib import Path

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
