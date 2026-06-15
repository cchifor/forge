"""Behaviour tests for the gatekeeper keycloak-realm-sync sidecar script.

The script ships in the gatekeeper image tree (not an importable package), so we
load it by path and drive ``sync`` through an ``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "forge/features/auth/templates/platform_auth_gatekeeper/all/files"
    / "deploy/infra/gatekeeper/scripts/realm_sync.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("realm_sync", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rs = _load()

_PROFILE = {
    "attributes": [{"name": "tenant_id"}],
    "unmanagedAttributePolicy": "ADMIN_EDIT",
}
_REALM_JSON = {
    "components": {
        "org.keycloak.userprofile.UserProfileProvider": [
            {"config": {"kc.user.profile.config": [json.dumps(_PROFILE)]}}
        ]
    }
}


class TestExtract:
    def test_valid(self) -> None:
        out = rs.extract_user_profile_config(_REALM_JSON)
        assert {a["name"] for a in out["attributes"]} == {"tenant_id"}
        assert out["unmanagedAttributePolicy"] == "ADMIN_EDIT"

    def test_missing_component_raises(self) -> None:
        with pytest.raises(rs.RealmSyncError):
            rs.extract_user_profile_config({"components": {}})

    def test_malformed_config_raises(self) -> None:
        bad = {"components": {"org.keycloak.userprofile.UserProfileProvider": [{"config": {}}]}}
        with pytest.raises(rs.RealmSyncError):
            rs.extract_user_profile_config(bad)


class TestServerRoot:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("http://keycloak:8080/realms", "http://keycloak:8080"),
            ("http://keycloak:8080/realms/app", "http://keycloak:8080"),
            ("http://keycloak:8080/realms/", "http://keycloak:8080"),
            ("http://keycloak:8080", "http://keycloak:8080"),
        ],
    )
    def test_normalizes(self, raw: str, expected: str) -> None:
        assert rs._server_root(raw) == expected


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestSync:
    def test_happy_path(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("/token"):
                return httpx.Response(200, json={"access_token": "tok"})
            if req.method == "PUT":
                return httpx.Response(204)
            return httpx.Response(200, json=_PROFILE)  # read-back

        asyncio.run(
            rs.sync(
                server_url="http://kc:8080",
                realm="app",
                admin_user="admin",
                admin_password="s3cret",
                profile_config=_PROFILE,
                http_client=_client(handler),
            )
        )  # no raise == success

    def test_read_after_write_missing_attr_raises(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("/token"):
                return httpx.Response(200, json={"access_token": "tok"})
            if req.method == "PUT":
                return httpx.Response(204)
            # GET reads back WITHOUT tenant_id — silent-drop the sync must catch.
            return httpx.Response(
                200, json={"attributes": [], "unmanagedAttributePolicy": "ADMIN_EDIT"}
            )

        with pytest.raises(rs.RealmSyncError):
            asyncio.run(
                rs.sync(
                    server_url="http://kc:8080",
                    realm="app",
                    admin_user="admin",
                    admin_password="s3cret",
                    profile_config=_PROFILE,
                    http_client=_client(handler),
                )
            )

    def test_bad_admin_password_is_terminal(self) -> None:
        # A 401 token grant is a config error (not transient) — fail fast,
        # don't retry/backoff.
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="invalid_grant")

        with pytest.raises(rs.RealmSyncError):
            asyncio.run(
                rs.sync(
                    server_url="http://kc:8080",
                    realm="app",
                    admin_user="admin",
                    admin_password="wrong",
                    profile_config=_PROFILE,
                    http_client=_client(handler),
                )
            )
