"""Behavioural tests for the Gatekeeper authorization primitive (``authz.py``).

The module under test is a **pure, stdlib-only** decision helper that holds
the security-critical role-authorization logic for the ``/api/v1/api-keys``
admin gate. It is deliberately free of fastapi / redis / weld /
opentelemetry so it can be imported and exercised directly in forge CI,
which does not install the gatekeeper's runtime dependencies.

We load it straight from the template path (mirroring
``tests/test_mcp_audit.py``'s importlib loader) so the test validates what
forge actually ships into generated projects.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_authz_module():
    path = (
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
        / "authz.py"
    )
    spec = importlib.util.spec_from_file_location("gatekeeper_authz_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["gatekeeper_authz_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def authz():
    return _load_authz_module()


class TestIsAuthorized:
    def test_true_when_role_present(self, authz) -> None:
        assert authz.is_authorized(["user", "admin", "auditor"], "admin") is True

    def test_false_when_role_absent(self, authz) -> None:
        assert authz.is_authorized(["user", "auditor"], "admin") is False

    def test_false_on_empty_roles(self, authz) -> None:
        assert authz.is_authorized([], "admin") is False

    def test_exact_match_only_no_substring(self, authz) -> None:
        # ``superadmin`` must not satisfy a requirement for ``admin``.
        assert authz.is_authorized(["superadmin"], "admin") is False

    def test_case_sensitive(self, authz) -> None:
        assert authz.is_authorized(["Admin"], "admin") is False


class TestExtractRealmRoles:
    def test_normal_payload(self, authz) -> None:
        payload = {"realm_access": {"roles": ["admin", "user"]}}
        assert authz.extract_realm_roles(payload) == ["admin", "user"]

    def test_missing_realm_access(self, authz) -> None:
        assert authz.extract_realm_roles({"sub": "u1"}) == []

    def test_missing_roles_key(self, authz) -> None:
        assert authz.extract_realm_roles({"realm_access": {}}) == []

    def test_realm_access_is_none(self, authz) -> None:
        assert authz.extract_realm_roles({"realm_access": None}) == []

    def test_roles_is_none(self, authz) -> None:
        assert authz.extract_realm_roles({"realm_access": {"roles": None}}) == []

    def test_roles_not_a_list(self, authz) -> None:
        # A string is iterable but is NOT a valid roles list — fail closed
        # to an empty list rather than iterating characters.
        assert authz.extract_realm_roles({"realm_access": {"roles": "admin"}}) == []

    def test_realm_access_not_a_mapping(self, authz) -> None:
        assert authz.extract_realm_roles({"realm_access": ["admin"]}) == []

    def test_empty_payload(self, authz) -> None:
        assert authz.extract_realm_roles({}) == []

    def test_coerces_role_entries_to_str(self, authz) -> None:
        # Defensive: mixed-type entries are normalised so downstream
        # exact-string comparison is well-defined.
        assert authz.extract_realm_roles(
            {"realm_access": {"roles": ["admin", 123]}}
        ) == ["admin", "123"]


class TestEndToEndDecision:
    """The two helpers compose into the gate the api-keys router applies."""

    def test_admin_payload_authorized(self, authz) -> None:
        payload = {"realm_access": {"roles": ["default-roles-app", "admin"]}}
        roles = authz.extract_realm_roles(payload)
        assert authz.is_authorized(roles, "admin") is True

    def test_non_admin_payload_denied(self, authz) -> None:
        payload = {"realm_access": {"roles": ["default-roles-app", "user"]}}
        roles = authz.extract_realm_roles(payload)
        assert authz.is_authorized(roles, "admin") is False

    def test_payload_without_roles_denied(self, authz) -> None:
        roles = authz.extract_realm_roles({"sub": "u1"})
        assert authz.is_authorized(roles, "admin") is False
