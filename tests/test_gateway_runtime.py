"""Runtime tests for the rendered ``api-gateway`` template (execution gap).

The other gateway tests (``test_backend_app_template_gateway.py``) only
AST-parse the rendered gateway modules — they never *execute* them, so a
logic bug (audience-confusion in the S2S token cache, a 500 escaping where a
502 is promised, a missing HTTP verb) passes those tests silently.

This module closes that gap. It renders the real api-gateway variant via the
generator (``dry_run=True``), puts the rendered ``<svc>/src`` on ``sys.path``,
imports the rendered ``app.gateway.s2s_client`` / ``app.gateway.downstreams``,
and exercises them IN-PROCESS with httpx mocked via a ``MockTransport`` — no
network. The gateway endpoint itself imports FastAPI (not a forge dependency),
so its method coverage and S2S-failure → 502 mapping are asserted by parsing
the rendered ``gateway.py`` instead of importing it.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import sys
from collections.abc import Awaitable
from pathlib import Path

import httpx
import pytest

from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.generator import generate


def _run[T](coro: Awaitable[T]) -> T:
    """Run an async coroutine to completion (no pytest-asyncio dependency)."""
    return asyncio.run(coro)


# --- render the real api-gateway variant once for the whole module ---------


@pytest.fixture(scope="module")
def gateway_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Render the api-gateway variant and return ``<svc>/src`` (on sys.path)."""
    out = tmp_path_factory.mktemp("gw_runtime")
    cfg = ProjectConfig(
        project_name="gw_rt",
        output_dir=str(out),
        backends=[
            BackendConfig(
                name="gw",
                project_name="gw_rt",
                language=BackendLanguage.PYTHON,
                app_template="api-gateway",
                features=["items"],
            )
        ],
        frontend=None,
    )
    root = generate(cfg, quiet=True, dry_run=True)
    src = root / "services" / "gw" / "src"
    assert src.is_dir(), f"rendered src missing: {src}"
    sys.path.insert(0, str(src))
    # Drop any previously-imported (stale-path) copies so we import THIS render.
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    yield src
    sys.path.remove(str(src))
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]


@pytest.fixture()
def s2s_mod(gateway_src: Path):
    """Import the rendered ``app.gateway.s2s_client`` module fresh per test."""
    sys.modules.pop("app.gateway.s2s_client", None)
    return importlib.import_module("app.gateway.s2s_client")


@pytest.fixture()
def downstreams_mod(gateway_src: Path):
    """Import the rendered ``app.gateway.downstreams`` module fresh per test."""
    sys.modules.pop("app.gateway.downstreams", None)
    return importlib.import_module("app.gateway.downstreams")


# --- a mock-transport-backed AsyncClient factory ---------------------------


def _install_mock_client(monkeypatch, s2s_mod, handler, *, calls: list):
    """Patch ``httpx.AsyncClient`` *in the rendered module* with a mock one.

    ``handler(request) -> httpx.Response`` decides each token response; every
    request the client makes is appended to ``calls`` so tests can assert how
    many mints actually happened.
    """
    transport = httpx.MockTransport(handler)

    class _Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):  # noqa: D401, ARG002
            calls.append(kwargs)
            super().__init__(transport=transport)

    monkeypatch.setattr(s2s_mod.httpx, "AsyncClient", _Client)


def _configured_client(s2s_mod):
    return s2s_mod.S2SClient(
        client_id="gw",
        client_secret="shh",
        token_endpoint="https://gatekeeper.test/token",
    )


# === (1) S2SClient: per-audience cache (audience confusion) ================


def test_audience_cache_mints_distinct_tokens_per_audience(monkeypatch, s2s_mod):
    """Minting for audience A then B yields DISTINCT tokens (no reuse)."""
    seen_audiences: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        # crude form parse: find audience=...
        aud = None
        for part in body.split("&"):
            if part.startswith("audience="):
                aud = part.split("=", 1)[1]
        seen_audiences.append(aud)
        return httpx.Response(200, json={"access_token": f"tok-{aud}", "expires_in": 300})

    calls: list = []
    _install_mock_client(monkeypatch, s2s_mod, handler, calls=calls)
    client = _configured_client(s2s_mod)

    tok_a = _run(client.token(audience="orders"))
    tok_b = _run(client.token(audience="inventory"))

    assert tok_a == "tok-orders"
    assert tok_b == "tok-inventory"
    assert tok_a != tok_b, "audience confusion: same token reused across audiences"
    assert seen_audiences == ["orders", "inventory"]
    assert len(calls) == 2, "expected one mint per distinct audience"


def test_audience_cache_reuses_within_expiry_same_audience(monkeypatch, s2s_mod):
    """A 2nd call for audience A within expiry returns the CACHED token."""
    mint_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        mint_count["n"] += 1
        return httpx.Response(200, json={"access_token": "tok-A", "expires_in": 300})

    calls: list = []
    _install_mock_client(monkeypatch, s2s_mod, handler, calls=calls)
    client = _configured_client(s2s_mod)

    first = _run(client.token(audience="orders"))
    second = _run(client.token(audience="orders"))

    assert first == second == "tok-A"
    assert mint_count["n"] == 1, "cached token for the same audience was not reused"
    assert len(calls) == 1


def test_cache_is_keyed_by_audience_no_cross_reuse(monkeypatch, s2s_mod):
    """The cache dict is per-audience: A's entry never satisfies B's request."""
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        return httpx.Response(200, json={"access_token": f"tok-{counter['n']}", "expires_in": 300})

    calls: list = []
    _install_mock_client(monkeypatch, s2s_mod, handler, calls=calls)
    client = _configured_client(s2s_mod)

    _run(client.token(audience="orders"))  # mint #1 -> tok-1
    _run(client.token(audience="inventory"))  # mint #2 -> tok-2 (NOT tok-1)
    again = _run(client.token(audience="orders"))  # cached -> tok-1

    assert again == "tok-1", "second 'orders' call must return orders' own cached token"
    assert counter["n"] == 2, "only two distinct mints (one per audience)"
    # The cache structure itself is per-audience.
    assert set(client._cache.keys()) == {"orders", "inventory"}


# === (2) S2SClient: graceful degrade when unconfigured =====================


def test_graceful_degrade_returns_empty_header_no_http(monkeypatch, s2s_mod):
    """With GATEKEEPER_* env unset, auth_header() returns {} and never calls httpx."""
    for var in ("GATEKEEPER_CLIENT_ID", "GATEKEEPER_CLIENT_SECRET", "GATEKEEPER_TOKEN_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("httpx must not be called when unconfigured")

    calls: list = []
    _install_mock_client(monkeypatch, s2s_mod, handler, calls=calls)

    client = s2s_mod.S2SClient()  # fully env-driven -> unconfigured
    assert client.configured is False
    assert _run(client.auth_header(audience="orders")) == {}
    assert _run(client.token(audience="orders")) is None
    assert calls == [], "no AsyncClient should be constructed when unconfigured"


# === (3) S2SClient: mint failure surfaces a clean (catchable) error ========


def test_mint_failure_on_5xx_raises_s2s_mint_error(monkeypatch, s2s_mod):
    """A 500 from the token endpoint raises S2SMintError, not a raw HTTPError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server_error"})

    calls: list = []
    _install_mock_client(monkeypatch, s2s_mod, handler, calls=calls)
    client = _configured_client(s2s_mod)

    with pytest.raises(s2s_mod.S2SMintError):
        _run(client.token(audience="orders"))


def test_mint_failure_on_connect_error_raises_s2s_mint_error(monkeypatch, s2s_mod):
    """A transport/connect error raises S2SMintError, never escapes raw."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("gatekeeper down")

    calls: list = []
    _install_mock_client(monkeypatch, s2s_mod, handler, calls=calls)
    client = _configured_client(s2s_mod)

    with pytest.raises(s2s_mod.S2SMintError):
        _run(client.auth_header(audience="orders"))


def test_mint_failure_on_malformed_body_is_not_keyerror(monkeypatch, s2s_mod):
    """A 200 with no access_token raises S2SMintError (NOT KeyError -> 500)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token_type": "Bearer"})  # no access_token

    calls: list = []
    _install_mock_client(monkeypatch, s2s_mod, handler, calls=calls)
    client = _configured_client(s2s_mod)

    with pytest.raises(s2s_mod.S2SMintError):
        _run(client.token(audience="orders"))
    # Specifically: it must not be a bare KeyError leaking the dict access.
    try:
        _run(client.token(audience="orders"))
    except KeyError:  # pragma: no cover
        pytest.fail("malformed token body leaked a KeyError (would 500)")
    except s2s_mod.S2SMintError:
        pass


# === (4) downstreams: live env parse + case-insensitive resolve ============


def test_downstream_map_parses_live_env(monkeypatch, downstreams_mod):
    """downstream_map() reads INTERNAL_SERVICE_URL_* from the live env."""
    monkeypatch.setenv("INTERNAL_SERVICE_URL_ORDERS", "http://orders:5020")
    monkeypatch.setenv("INTERNAL_SERVICE_URL_INVENTORY", "http://inventory:5030")
    monkeypatch.setenv("INTERNAL_SERVICE_URL_BLANK", "   ")  # skipped (blank)

    mapping = downstreams_mod.downstream_map()
    assert mapping["orders"] == "http://orders:5020"
    assert mapping["inventory"] == "http://inventory:5030"
    assert "blank" not in mapping, "blank-valued downstream must be skipped"


def test_resolve_downstream_is_case_insensitive(monkeypatch, downstreams_mod):
    """resolve_downstream() matches the service name case-insensitively."""
    monkeypatch.setenv("INTERNAL_SERVICE_URL_ORDERS", "http://orders:5020")
    assert downstreams_mod.resolve_downstream("orders") == "http://orders:5020"
    assert downstreams_mod.resolve_downstream("ORDERS") == "http://orders:5020"
    assert downstreams_mod.resolve_downstream("Orders") == "http://orders:5020"
    assert downstreams_mod.resolve_downstream("unknown") is None


# === (5) method coverage + 502 mapping (AST on rendered gateway.py) ========
#
# The rendered gateway endpoint imports FastAPI, which is not a forge
# dependency, so we assert its shape by parsing the rendered source rather
# than importing it.


def _gateway_py(gateway_src: Path) -> str:
    return (gateway_src / "app/api/v1/endpoints/gateway.py").read_text(encoding="utf-8")


def test_rendered_gateway_proxies_all_verbs(gateway_src: Path):
    """The api_route catch-all registers PUT/PATCH/DELETE (+ OPTIONS/HEAD)."""
    tree = ast.parse(_gateway_py(gateway_src))

    methods: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # @router.api_route(..., methods=[...])
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "api_route"):
            continue
        for kw in node.keywords:
            if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                for elt in kw.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        methods.add(elt.value.upper())

    assert methods, "no @router.api_route(methods=[...]) found in rendered gateway"
    assert {"GET", "POST", "PUT", "PATCH", "DELETE"} <= methods, (
        f"gateway must proxy all CRUD verbs; got {sorted(methods)}"
    )
    assert {"OPTIONS", "HEAD"} <= methods, (
        f"gateway should also proxy OPTIONS/HEAD; got {sorted(methods)}"
    )


def test_rendered_gateway_maps_s2s_mint_failure_to_502(gateway_src: Path):
    """A token-mint failure is caught and re-raised as a 502, not a 500."""
    src = _gateway_py(gateway_src)
    assert "S2SMintError" in src, "gateway must import/handle S2SMintError"

    tree = ast.parse(src)
    # Find an `except S2SMintError` whose body raises HTTPException(502).
    found_502_handler = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        names: set[str] = set()
        exc_type = node.type
        if isinstance(exc_type, ast.Name):
            names.add(exc_type.id)
        elif isinstance(exc_type, ast.Tuple):
            names.update(e.id for e in exc_type.elts if isinstance(e, ast.Name))
        if "S2SMintError" not in names:
            continue
        handler_src = ast.get_source_segment(src, node) or ""
        if "HTTP_502_BAD_GATEWAY" in handler_src or "502" in handler_src:
            found_502_handler = True
    assert found_502_handler, "S2S mint failure must be mapped to a 502 in the gateway proxy"


def test_rendered_gateway_drops_redundant_media_type(gateway_src: Path):
    """The dead ``media_type=`` arg (redundant with copied content-type) is gone."""
    assert "media_type=downstream.headers" not in _gateway_py(gateway_src)
