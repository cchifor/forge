"""Regression guard: generated feature routers that expose sensitive
operations must require authentication.

Several generated routers (MCP, agent tools, chat-file upload, webhooks)
historically shipped as ``APIRouter()`` with no auth dependency, leaving tool
invocation, file upload/download, and outbound webhook test-fire reachable
without a token. The behaviour was verified end-to-end (auth enabled + no
token -> 401) against the real weld SDK over docker; this test locks the gate
into the templates so it cannot silently regress.

NOTE: ``weld.fastapi.security.auth.oauth2_scheme`` is ``auto_error=False`` and
does NOT gate on its own — ``get_current_user`` is the enforcing dependency
(it raises 401 when no valid bearer token is present, and yields the dev user
when auth is disabled).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_BASE = Path(__file__).resolve().parent.parent

# Routers that expose sensitive operations and must be gated.
_GATED_ROUTERS = [
    "forge/features/platform/templates/mcp_server/python/files/src/app/mcp/router.py",
    "forge/features/agent/templates/agent_tools/python/files/src/app/api/v1/endpoints/tools.py",
    "forge/features/conversation/templates/file_upload/python/files/src/app/api/v1/endpoints/chat_files.py",
    "forge/features/platform/templates/webhooks/python/files/src/app/api/v1/endpoints/webhooks.py",
]


@pytest.mark.parametrize("rel", _GATED_ROUTERS)
def test_feature_router_requires_auth(rel: str) -> None:
    src = (_BASE / rel).read_text(encoding="utf-8")
    assert "from weld.fastapi.security.auth import get_current_user" in src, (
        f"{rel} must import the enforcing auth dependency"
    )
    assert "dependencies=[Depends(get_current_user)]" in src, (
        f"{rel} must gate its APIRouter with Depends(get_current_user)"
    )
