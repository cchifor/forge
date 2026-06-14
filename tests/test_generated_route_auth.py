"""Regression guard: every generated MAIN-app router must declare auth.

Several generated routers (MCP, agent tools, chat-file upload, webhooks, the
agent WebSocket, the CloudEvent stream) historically shipped as bare
``APIRouter()`` with no auth dependency, leaving sensitive operations
reachable without a token.

This is the GENERALIZED form of the former fixed 4-router allowlist (which was
blind to ``/ws/agent`` and every newly added router). It DISCOVERS every
router under BOTH the feature templates and the base/variant service templates
and requires each to be classified — gated by a recognized pattern, gated via
a named auth-bound Dishka service, or explicitly public with a reason. A new
router that is none of these fails this test, forcing an auth decision at
review time.

This is a COMPLETENESS check, not a soundness proof: it cannot trace the full
Dishka provider graph, so routers gated only through an auth-bound service are
listed explicitly (and covered by their own runtime tenant-isolation tests).
Imports, docstrings, and comments are stripped before matching so a pattern in
an unused import / docstring / comment can't make a router look gated.

Recognized directly-enforcing patterns (NOT ``oauth2_scheme``, which is
``auto_error=False`` and only paints the OpenAPI lock icon):
  * ``Depends(get_current_user)`` — the HTTP enforcing dependency;
  * ``authenticate_websocket`` — the WS handshake verifier (closes 1008);
  * ``FromDishka[AuthUnitOfWork]`` / ``FromDishka[User]`` — request-scoped
    providers that raise 401 when unauthenticated.

The gatekeeper sub-app (``infra/gatekeeper/``) is its own auth domain and is
excluded.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

_BASE = Path(__file__).resolve().parent.parent
_FEATURES = _BASE / "forge" / "features"
_SERVICES = _BASE / "forge" / "templates" / "services"

# Routers gated through an auth-bound Dishka service (FromDishka[<Service>] ->
# AuthUnitOfWork -> get_current_user -> 401). Listed explicitly because the
# guard can't trace the provider graph; each is covered by runtime tests.
_GATED_VIA_SERVICE: dict[str, str] = {
    "templates/services/python-service-template/template/src/app/api/v1/endpoints/items.py": (
        "FromDishka[ItemService] -> AuthUnitOfWork -> 401"
    ),
    "templates/services/python/tenant-management-service/template/src/app/api/v1/endpoints/realms.py": (
        "FromDishka[RealmService] -> AuthUnitOfWork -> 401"
    ),
    "templates/services/python/tenant-management-service/template/src/app/api/v1/endpoints/tenants.py": (
        "FromDishka[TenantService] -> AuthUnitOfWork -> 401"
    ),
}

# Intentionally public routers, each with a reason.
_PUBLIC_ALLOWLIST: dict[str, str] = {
    "features/observability/templates/enhanced_health/python/files/src/app/api/v1/endpoints/health_deep.py": (
        "readiness/liveness probe — reachable by orchestrators without a token"
    ),
    "features/auth/templates/platform_auth_in_memory/python/files/src/app/api/v1/endpoints/dev_auth.py": (
        "dev-only token minting; install_in_memory_auth refuses to boot in prod"
    ),
    "templates/services/python-service-template/template/src/app/api/v1/endpoints/health.py": (
        "liveness/readiness probes — must be reachable without a token"
    ),
    "templates/services/python-service-template/template/src/app/api/v1/endpoints/home.py": (
        "landing/info — exposes only app title/version/description, no secrets"
    ),
    "templates/services/python-service-template/template/src/app/api/v1/endpoints/admin.py": (
        "diagnostics gated by require_non_production (404 in a production env)"
    ),
}

_ENFORCING_PATTERNS = (
    "Depends(get_current_user)",
    "authenticate_websocket",
    "FromDishka[AuthUnitOfWork]",
    "FromDishka[User]",
)

_ROUTER_RE = re.compile(r"^\s*router\s*=\s*APIRouter\(", re.MULTILINE)


def _code_for_matching(src: str) -> str:
    """Return the source with imports, docstrings, and comments removed so the
    enforcing-pattern substring match can't be fooled by a pattern appearing
    in an unused import, a docstring, or a comment. Exact spacing of the
    REMAINING code is preserved so patterns like ``Depends(get_current_user)``
    still match verbatim. Falls back to a full-line-comment strip if the file
    doesn't parse as plain Python (e.g. a Jinja template)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))

    blanked: set[int] = set()

    def _blank(node) -> None:
        for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
            blanked.add(ln)

    def _blank_docstring(body) -> None:
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            _blank(body[0])

    _blank_docstring(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            _blank(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _blank_docstring(node.body)

    lines = ["" if i in blanked else ln for i, ln in enumerate(src.splitlines(), 1)]

    # Cut inline comments (tokenize identifies COMMENT tokens correctly, so a
    # '#' inside a string literal is not mistaken for a comment).
    try:
        rendered = "\n".join(lines)
        out = rendered.splitlines()
        for tok in tokenize.generate_tokens(io.StringIO(rendered).readline):
            if tok.type == tokenize.COMMENT:
                row, col = tok.start
                if row - 1 < len(out):
                    out[row - 1] = out[row - 1][:col]
        return "\n".join(out)
    except tokenize.TokenError:
        return "\n".join(lines)


def _discover_routers() -> list[Path]:
    routers: list[Path] = []
    for root in (_FEATURES, _SERVICES):
        for path in root.rglob("*.py"):
            rel = path.as_posix()
            if root is _FEATURES and "/files/" not in rel:
                continue
            if "/deploy/infra/gatekeeper/" in rel:
                continue
            text = path.read_text(encoding="utf-8")
            if _ROUTER_RE.search(text):
                routers.append(path)
    return sorted(routers)


_ROUTERS = _discover_routers()


def _rel(path: Path) -> str:
    # Key relative to forge/ so feature and template paths share a namespace.
    return path.relative_to(_BASE / "forge").as_posix()


def test_discovery_found_routers() -> None:
    assert len(_ROUTERS) >= 12, f"expected to discover the known routers, got {len(_ROUTERS)}"


@pytest.mark.parametrize("path", _ROUTERS, ids=_rel)
def test_router_is_gated_or_explicitly_public(path: Path) -> None:
    rel = _rel(path)
    src = _code_for_matching(path.read_text(encoding="utf-8"))

    gated = any(pat in src for pat in _ENFORCING_PATTERNS)
    if gated or rel in _PUBLIC_ALLOWLIST or rel in _GATED_VIA_SERVICE:
        return
    raise AssertionError(
        f"{rel} defines an APIRouter but declares no recognized auth pattern "
        f"({', '.join(_ENFORCING_PATTERNS)}). Gate it, add it to "
        f"_GATED_VIA_SERVICE (if gated through an auth-bound Dishka service), "
        f"or add it to _PUBLIC_ALLOWLIST with a documented reason."
    )


def test_oauth2_scheme_alone_is_not_counted_as_gated() -> None:
    # oauth2_scheme is auto_error=False and does NOT enforce. A router relying
    # ONLY on it would be treated as ungated. The items/realms/tenants routers
    # pair it with an auth-bound FromDishka service (the real gate).
    assert "oauth2_scheme" not in _ENFORCING_PATTERNS


def test_allowlists_have_no_stale_entries() -> None:
    # Every allowlisted path must still exist (catch renames/deletions).
    for rel in {**_PUBLIC_ALLOWLIST, **_GATED_VIA_SERVICE}:
        assert (_BASE / "forge" / rel).is_file(), f"stale allowlist entry: {rel}"
