"""Regression guard: every generated MAIN-app router must declare auth.

Several generated routers (MCP, agent tools, chat-file upload, webhooks, the
agent WebSocket, the CloudEvent stream) historically shipped as bare
``APIRouter()`` with no auth dependency, leaving sensitive operations
reachable without a token.

This test is the GENERALIZED form of the former fixed 4-router allowlist
(which was blind to ``/ws/agent`` and every newly added router). It
DISCOVERS every router under the main service templates and requires each to
either match a recognized auth pattern or appear in an explicit PUBLIC
allowlist with a documented reason. A new router that is neither fails this
test — forcing an auth decision at review time.

Recognized enforcing patterns (NOT ``oauth2_scheme``, which is
``auto_error=False`` and only paints the OpenAPI lock icon):
  * ``Depends(get_current_user)`` — the HTTP enforcing dependency;
  * ``authenticate_websocket`` — the WS handshake verifier (closes 1008);
  * ``FromDishka[AuthUnitOfWork]`` — the tenant-bound unit of work, which
    fails closed (401) when there is no authenticated account (rag_pipeline);
  * ``FromDishka[User]`` — the request-scoped User provider, whose
    ``SecurityProvider.get_current_user`` raises 401 when unauthenticated
    (the vector-store RAG routers).

The separate gatekeeper sub-app (``infra/gatekeeper/``) is its own auth
domain (it IS the token authority) and is excluded here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_BASE = Path(__file__).resolve().parent.parent
_FEATURES = _BASE / "forge" / "features"

# Routers that are intentionally public, each with a reason. A router may be
# listed here ONLY with a justification a reviewer accepts.
_PUBLIC_ALLOWLIST: dict[str, str] = {
    "observability/templates/enhanced_health/python/files/src/app/api/v1/endpoints/health_deep.py": (
        "readiness/liveness probe — must be reachable by orchestrators "
        "(k8s, docker healthcheck) without a token"
    ),
    "auth/templates/platform_auth_in_memory/python/files/src/app/api/v1/endpoints/dev_auth.py": (
        "dev-only token minting; install_in_memory_auth refuses to boot under "
        "a production posture, so these routes never ship to prod"
    ),
}

_ENFORCING_PATTERNS = (
    "Depends(get_current_user)",
    "authenticate_websocket",
    "FromDishka[AuthUnitOfWork]",
    "FromDishka[User]",
)

_ROUTER_RE = re.compile(r"^\s*router\s*=\s*APIRouter\(", re.MULTILINE)


def _discover_main_app_routers() -> list[Path]:
    routers: list[Path] = []
    for path in _FEATURES.rglob("*.py"):
        rel = path.as_posix()
        if "/files/" not in rel:
            continue
        # Exclude the gatekeeper sub-app (separate auth domain).
        if "/infra/gatekeeper/" in rel:
            continue
        text = path.read_text(encoding="utf-8")
        if _ROUTER_RE.search(text):
            routers.append(path)
    return sorted(routers)


_ROUTERS = _discover_main_app_routers()


def test_discovery_found_routers() -> None:
    # Guard against a glob/path mistake silently turning this into a no-op.
    assert len(_ROUTERS) >= 8, f"expected to discover the known routers, got {_ROUTERS}"


@pytest.mark.parametrize("path", _ROUTERS, ids=lambda p: p.relative_to(_FEATURES).as_posix())
def test_router_is_gated_or_explicitly_public(path: Path) -> None:
    rel = path.relative_to(_FEATURES).as_posix()
    src = path.read_text(encoding="utf-8")

    gated = any(pat in src for pat in _ENFORCING_PATTERNS)
    public = rel in _PUBLIC_ALLOWLIST

    if public and gated:
        # Fine — defense in depth. Nothing to assert.
        return
    if public:
        assert _PUBLIC_ALLOWLIST[rel], f"{rel} public allowlist entry needs a reason"
        return
    assert gated, (
        f"{rel} defines an APIRouter but declares no recognized auth pattern "
        f"({', '.join(_ENFORCING_PATTERNS)}). Gate it, or add it to "
        f"_PUBLIC_ALLOWLIST with a documented reason."
    )


def test_oauth2_scheme_alone_is_not_counted_as_gated() -> None:
    # Document the invariant: oauth2_scheme is auto_error=False and does NOT
    # enforce. A router relying ONLY on it (no get_current_user / AuthUnitOfWork)
    # would be treated as ungated by this test. The RAG routers pair it with
    # FromDishka[AuthUnitOfWork], which is the real gate.
    assert "oauth2_scheme" not in _ENFORCING_PATTERNS
