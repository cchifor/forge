"""Security regression tests for the webhooks template.

Confirmed by the audit (and a verifier):
  * cross-tenant IDOR — list/delete/test-fire used PublicUnitOfWork with no
    tenant filter and create hardcoded customer_id=_ANON;
  * unrestricted SSRF — test-fire POSTed to any stored URL.

``webhook_service.validate_outbound_url`` is pure stdlib but the module
top-imports ``app.*`` packages absent from forge's env, so we stub those in
``sys.modules`` and exercise the REAL SSRF guard. The endpoint's tenant
scoping (generated-only forge_core imports) is asserted on source.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_BASE = Path(__file__).resolve().parent.parent
_SERVICE = (
    _BASE
    / "forge/features/platform/templates/webhooks/python/files/src/app/services/webhook_service.py"
)
_ENDPOINT = (
    _BASE
    / "forge/features/platform/templates/webhooks/python/files/src/app/api/v1/endpoints/webhooks.py"
)


def _load_service():
    """Load the real webhook_service module with its ``app.*`` imports stubbed."""
    for name in (
        "app",
        "app.data",
        "app.data.models",
        "app.data.models.webhook",
        "app.domain",
        "app.domain.webhook",
    ):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["app.data.models.webhook"].Webhook = object
    sys.modules["app.domain.webhook"].WebhookDeliveryResult = object
    spec = importlib.util.spec_from_file_location("_webhook_service_under_test", _SERVICE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    return _load_service()


class TestSsrfGuard:
    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
            "https://127.0.0.1/internal",  # loopback
            "https://localhost/internal",  # loopback by name
            "https://10.0.0.5/admin",  # RFC1918
            "https://192.168.1.1/",  # RFC1918
            "https://172.16.0.1/",  # RFC1918
            "https://[::1]/",  # IPv6 loopback
            "https://0.0.0.0/",  # unspecified
        ],
    )
    def test_internal_targets_rejected(self, svc, url):
        with pytest.raises(svc.WebhookUrlError):
            svc.validate_outbound_url(url)

    def test_ipv4_mapped_ipv6_loopback_rejected(self, svc):
        with pytest.raises(svc.WebhookUrlError):
            svc.validate_outbound_url("https://[::ffff:127.0.0.1]/")

    def test_non_http_scheme_rejected(self, svc):
        for url in ("file:///etc/passwd", "gopher://x/", "ftp://host/"):
            with pytest.raises(svc.WebhookUrlError):
                svc.validate_outbound_url(url)

    def test_http_rejected_in_production(self, svc):
        with pytest.raises(svc.WebhookUrlError):
            svc.validate_outbound_url("http://example.com/hook")

    @staticmethod
    def _stub_public_dns(monkeypatch, svc):
        # Resolve any host to a public IP so the test never depends on real DNS.
        monkeypatch.setattr(
            svc.socket,
            "getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
        )

    def test_http_allowed_in_dev(self, monkeypatch):
        monkeypatch.setenv("ENV", "development")
        svc = _load_service()
        self._stub_public_dns(monkeypatch, svc)
        # A public host over http is fine in dev (no raise).
        svc.validate_outbound_url("http://example.com/hook")

    def test_public_https_target_allowed(self, svc, monkeypatch):
        self._stub_public_dns(monkeypatch, svc)
        # A public host must pass (resolves to a routable address).
        svc.validate_outbound_url("https://example.com/hook")

    def test_dns_rebinding_to_internal_rejected(self, svc, monkeypatch):
        # Even if a public-looking host resolves to an internal IP, block it.
        monkeypatch.setattr(
            svc.socket,
            "getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("10.1.2.3", 443))],
        )
        with pytest.raises(svc.WebhookUrlError):
            svc.validate_outbound_url("https://totally-public.example/hook")


class TestEndpointTenantScoping:
    def _src(self) -> str:
        return _ENDPOINT.read_text(encoding="utf-8")

    def test_uses_tenant_bound_uow_not_public(self):
        src = self._src()
        assert "PublicUnitOfWork" not in src
        assert "AuthUnitOfWork" in src

    def test_no_anon_customer_on_create(self):
        src = self._src()
        assert "_ANON" not in src
        assert "customer_id=_tenant_id(user)" in src

    def test_queries_filter_by_verified_tenant(self):
        src = self._src()
        # Every read/delete/test-fire must filter by the caller's tenant.
        assert src.count("WebhookModel.customer_id == cid") >= 3

    def test_create_validates_url(self):
        src = self._src()
        assert "validate_outbound_url(str(data.url))" in src

    def test_router_still_auth_gated(self):
        src = self._src()
        assert "from forge_core.security.auth import get_current_user" in src
        assert "dependencies=[Depends(get_current_user)]" in src


class TestDeliveryHardening:
    def test_deliver_validates_before_post(self, svc):
        src = _SERVICE.read_text(encoding="utf-8")
        body = src.split("async def deliver")[1]
        assert "validate_outbound_url(webhook.url)" in body
        assert "follow_redirects=False" in body
