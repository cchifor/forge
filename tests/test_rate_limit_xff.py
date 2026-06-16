"""Rate-limiter must key on the real client behind a proxy (XFF) and bound
its bucket map.

Bug (#21): the in-memory token-bucket rate limiter keys on the raw transport
peer (``request.client.host`` / the Axum ``ConnectInfo`` socket addr). Behind
a reverse proxy/load-balancer every anonymous client shares the proxy's single
peer address, so they all collapse into ONE global bucket — one noisy client
rate-limits everyone, and (separately) the ``defaultdict`` of buckets grows
without bound because idle buckets are never evicted.

Fix (python + rust): when an ``X-Forwarded-For`` header is present, derive the
client key from its left-most (originating) address instead of the transport
peer; and bound/evict idle buckets so the map can't grow unboundedly.

The Python middleware is loaded from the template path with ``fastapi`` /
``starlette`` stubbed (they aren't installed in forge CI), mirroring the
importlib pattern in ``tests/test_gatekeeper_apikeys.py``. The Rust variant
can't be compiled here, so it's gated structurally over its source text.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RL_DIR = (
    _REPO_ROOT
    / "forge"
    / "features"
    / "middleware"
    / "templates"
    / "rate_limit"
)
_PY_PATH = _RL_DIR / "python" / "files" / "src" / "app" / "middleware" / "rate_limit.py"
_RUST_PATH = _RL_DIR / "rust" / "files" / "src" / "middleware" / "rate_limit.rs"


# --------------------------------------------------------------------------- #
# fastapi / starlette stubs                                                    #
# --------------------------------------------------------------------------- #
def _install_web_stubs() -> None:
    """Ensure the ``fastapi`` / ``starlette`` symbols the template module imports
    exist, so it loads without the real (uninstalled) packages.

    Augments rather than skip-if-present: another test in the same xdist worker
    may have installed a *partial* ``fastapi``/``starlette`` stub (missing
    ``status`` / ``BaseHTTPMiddleware`` etc.), so we backfill each required
    attribute individually rather than gating on module presence.
    """
    starlette = sys.modules.setdefault("starlette", types.ModuleType("starlette"))
    mw = sys.modules.setdefault("starlette.middleware", types.ModuleType("starlette.middleware"))
    base = sys.modules.setdefault(
        "starlette.middleware.base", types.ModuleType("starlette.middleware.base")
    )
    if not hasattr(base, "BaseHTTPMiddleware"):

        class BaseHTTPMiddleware:  # noqa: D401 - minimal stand-in
            def __init__(self, app) -> None:
                self.app = app

        base.BaseHTTPMiddleware = BaseHTTPMiddleware
    starlette.middleware = mw
    mw.base = base

    fastapi = sys.modules.setdefault("fastapi", types.ModuleType("fastapi"))
    responses = sys.modules.setdefault("fastapi.responses", types.ModuleType("fastapi.responses"))
    if not hasattr(fastapi, "Request"):
        fastapi.Request = type("Request", (), {})
    if not hasattr(fastapi, "Response"):
        fastapi.Response = type("Response", (), {})
    if not hasattr(fastapi, "status") or not hasattr(
        fastapi.status, "HTTP_429_TOO_MANY_REQUESTS"
    ):
        fastapi.status = type("_Status", (), {"HTTP_429_TOO_MANY_REQUESTS": 429})
    if not hasattr(responses, "JSONResponse"):

        class JSONResponse:
            def __init__(self, *, status_code, content, headers=None) -> None:
                self.status_code = status_code
                self.content = content
                self.headers = headers or {}

        responses.JSONResponse = JSONResponse
    fastapi.responses = responses


def _load_rate_limit_module() -> types.ModuleType:
    _install_web_stubs()
    spec = importlib.util.spec_from_file_location("rl_py_under_test", _PY_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["rl_py_under_test"] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# fake request                                                                 #
# --------------------------------------------------------------------------- #
class _Client:
    def __init__(self, host: str) -> None:
        self.host = host


class _State:
    pass


class _FakeRequest:
    """Minimal Starlette-ish request for ``_resolve_key``."""

    def __init__(self, *, peer_host: str, xff: str | None = None) -> None:
        self.client = _Client(peer_host)
        self.state = _State()
        self.headers = {}
        if xff is not None:
            self.headers["x-forwarded-for"] = xff


# --------------------------------------------------------------------------- #
# Python: XFF keying                                                           #
# --------------------------------------------------------------------------- #
def test_python_xff_clients_get_distinct_keys() -> None:
    """Two different originating clients behind the SAME proxy peer must
    resolve to DIFFERENT bucket keys."""
    module = _load_rate_limit_module()
    mw = module.RateLimitMiddleware(app=None, requests_per_minute=120)

    # Both arrive via proxy peer 10.0.0.1, but are distinct real clients.
    req_a = _FakeRequest(peer_host="10.0.0.1", xff="203.0.113.7")
    req_b = _FakeRequest(peer_host="10.0.0.1", xff="198.51.100.42")

    key_a = mw._resolve_key(req_a)
    key_b = mw._resolve_key(req_b)

    assert key_a != key_b, (
        "two distinct XFF clients behind one proxy peer collapsed into the "
        f"same bucket key ({key_a!r}); the limiter must key on the X-Forwarded-For "
        "originating address, not the shared transport peer"
    )
    # The originating client IP must drive the key, not the proxy peer.
    assert "203.0.113.7" in key_a
    assert "198.51.100.42" in key_b


def test_python_xff_uses_leftmost_address() -> None:
    """For a chained ``client, proxy1, proxy2`` XFF, the left-most
    (originating) address is the key."""
    module = _load_rate_limit_module()
    mw = module.RateLimitMiddleware(app=None, requests_per_minute=120)

    req = _FakeRequest(peer_host="10.0.0.1", xff="203.0.113.7, 70.41.3.18, 150.172.238.178")
    key = mw._resolve_key(req)
    assert "203.0.113.7" in key, f"expected left-most XFF address in key, got {key!r}"
    assert "150.172.238.178" not in key


def test_python_two_xff_clients_have_independent_budgets() -> None:
    """End-to-end through dispatch: exhausting client A's budget must NOT
    rate-limit client B (they must not share a bucket)."""
    import asyncio

    module = _load_rate_limit_module()
    # burst=2 → each client gets 2 tokens before a 429.
    mw = module.RateLimitMiddleware(app=None, requests_per_minute=120, burst=2)

    async def _ok(_request):
        return "OK"

    async def _run() -> None:
        a = _FakeRequest(peer_host="10.0.0.1", xff="203.0.113.7")
        b = _FakeRequest(peer_host="10.0.0.1", xff="198.51.100.42")
        # Drain A's two tokens.
        assert await mw.dispatch(a, _ok) == "OK"
        assert await mw.dispatch(a, _ok) == "OK"
        a_third = await mw.dispatch(a, _ok)
        assert getattr(a_third, "status_code", None) == 429, "A should be limited after burst"
        # B, a *different* origin behind the same proxy, must still be allowed.
        b_first = await mw.dispatch(b, _ok)
        assert b_first == "OK", (
            "client B was rate-limited by client A's traffic — they shared a "
            "bucket because the limiter keyed on the shared proxy peer"
        )

    asyncio.run(_run())


def test_python_buckets_are_bounded() -> None:
    """The bucket map must not grow without bound: idle buckets are evicted
    so a flood of unique clients can't OOM the process."""
    import asyncio

    module = _load_rate_limit_module()
    mw = module.RateLimitMiddleware(app=None, requests_per_minute=120, burst=120)

    async def _ok(_request):
        return "OK"

    async def _run() -> None:
        for i in range(5000):
            req = _FakeRequest(peer_host="10.0.0.1", xff=f"203.0.113.{i % 256}.{i}")
            await mw.dispatch(req, _ok)

    asyncio.run(_run())

    # Find the live bucket map regardless of its private attribute name.
    bucket_map = None
    for name in ("_buckets",):
        bucket_map = getattr(mw, name, None)
        if bucket_map is not None:
            break
    assert bucket_map is not None, "rate limiter must expose its bucket map"
    assert len(bucket_map) <= 4096, (
        f"bucket map grew to {len(bucket_map)} entries with no eviction — an "
        "unbounded defaultdict of buckets is a memory-exhaustion vector"
    )


# --------------------------------------------------------------------------- #
# Rust: structural parity                                                      #
# --------------------------------------------------------------------------- #
def test_rust_keys_on_x_forwarded_for() -> None:
    text = _RUST_PATH.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "x-forwarded-for" in lowered, (
        "rust rate limiter must read the X-Forwarded-For header to derive the "
        "real client key behind a proxy, instead of only using the "
        "ConnectInfo transport peer"
    )


def test_rust_bounds_bucket_map() -> None:
    text = _RUST_PATH.read_text(encoding="utf-8")
    # Eviction / size-bound: the map must be pruned of stale entries or capped.
    has_bound = any(
        token in text
        for token in ("retain(", "remove(", "MAX_BUCKETS", "max_buckets")
    )
    assert has_bound, (
        "rust rate limiter must bound/evict its bucket HashMap (retain/remove/"
        "cap) — an ever-growing map is a memory-exhaustion vector"
    )


def test_rust_strictly_bounds_bucket_map_under_active_flood() -> None:
    """The idle-retain alone leaves the map unbounded when EVERY client is
    active (no bucket has fully refilled, so ``retain`` removes nothing and the
    new key is inserted anyway). Mirroring Python's hard cap, the Rust limiter
    must, after the idle-retain, evict the least-recently-used bucket (smallest
    ``last_refill``) whenever the map is STILL at/over the cap before inserting.
    """
    text = _RUST_PATH.read_text(encoding="utf-8")
    # LRU eviction by oldest last_refill, performed via min_by + remove. This is
    # strictly stronger than the idle-only retain, which can't bound an
    # all-active flood.
    assert "min_by" in text, (
        "rust rate limiter must pick the least-recently-used bucket "
        "(min_by over last_refill) to evict when at capacity"
    )
    assert "last_refill" in text, "LRU eviction must key on the last_refill Instant"
    assert "remove(" in text, (
        "rust rate limiter must remove() the LRU bucket so the map is strictly "
        "bounded even when every client is active — the idle retain alone is "
        "not a hard cap"
    )
    # The eviction must be conditioned on the map still being full AFTER the
    # idle retain (a second len()>=MAX_BUCKETS guard), not the single pre-retain
    # check — otherwise an all-active flood grows the map past MAX_BUCKETS.
    assert text.count("MAX_BUCKETS") >= 3, (
        "expected a second MAX_BUCKETS guard after the idle retain to force a "
        "hard-cap LRU eviction when all buckets are active"
    )


# --------------------------------------------------------------------------- #
# Python: trusted-proxy gating of X-Forwarded-For                              #
# --------------------------------------------------------------------------- #
def test_python_trusts_xff_only_from_private_peer() -> None:
    """When the transport peer is a PRIVATE/loopback address (the in-cluster
    reverse-proxy topology), the left-most X-Forwarded-For entry drives the
    key — existing trusted-proxy behaviour."""
    module = _load_rate_limit_module()
    mw = module.RateLimitMiddleware(app=None, requests_per_minute=120)

    # Peer 10.0.0.1 is the in-cluster Traefik proxy → XFF is trusted.
    req = _FakeRequest(peer_host="10.0.0.1", xff="203.0.113.7")
    key = mw._resolve_key(req)
    assert "203.0.113.7" in key, (
        f"behind a private (trusted) proxy peer, the XFF originating address "
        f"must drive the key, got {key!r}"
    )


def test_python_ignores_xff_from_public_peer() -> None:
    """When the transport peer is PUBLIC (the app is internet-facing, or sits
    behind a proxy that APPENDS rather than overrides XFF), a client-supplied
    X-Forwarded-For must NOT be trusted — the key falls back to the transport
    peer so the XFF can't be used to spoof / evade the bucket."""
    module = _load_rate_limit_module()
    mw = module.RateLimitMiddleware(app=None, requests_per_minute=120)

    # Two requests from the SAME public peer, each spoofing a different XFF.
    req_a = _FakeRequest(peer_host="8.8.8.8", xff="203.0.113.7")
    req_b = _FakeRequest(peer_host="8.8.8.8", xff="198.51.100.42")

    key_a = mw._resolve_key(req_a)
    key_b = mw._resolve_key(req_b)

    assert key_a == key_b, (
        "two requests from the same public peer with different spoofed XFF "
        f"headers got distinct keys ({key_a!r} vs {key_b!r}); an untrusted "
        "(public) peer must not be able to spoof its rate-limit bucket via XFF"
    )
    assert "8.8.8.8" in key_a, (
        f"untrusted public peer must key on its own transport address, got {key_a!r}"
    )
    assert "203.0.113.7" not in key_a, (
        "client-supplied XFF from a public peer must be ignored"
    )


def test_python_spoofed_xff_from_public_peer_shares_one_bucket() -> None:
    """End-to-end: a public peer rotating its X-Forwarded-For on every request
    must NOT get a fresh budget each time — all spoofed requests from one
    public peer share a single bucket."""
    import asyncio

    module = _load_rate_limit_module()
    # burst=2 → the shared bucket allows 2 requests, then 429s.
    mw = module.RateLimitMiddleware(app=None, requests_per_minute=120, burst=2)

    async def _ok(_request):
        return "OK"

    async def _run() -> None:
        # Same public peer, fresh spoofed XFF on each request.
        assert await mw.dispatch(
            _FakeRequest(peer_host="1.1.1.1", xff="203.0.113.1"), _ok
        ) == "OK"
        assert await mw.dispatch(
            _FakeRequest(peer_host="1.1.1.1", xff="203.0.113.2"), _ok
        ) == "OK"
        third = await mw.dispatch(
            _FakeRequest(peer_host="1.1.1.1", xff="203.0.113.3"), _ok
        )
        assert getattr(third, "status_code", None) == 429, (
            "a public peer rotating its XFF got a fresh budget each request — "
            "spoofed XFF from an untrusted peer must be ignored so all its "
            "requests share one bucket"
        )

    asyncio.run(_run())


def test_python_is_trusted_peer_classification() -> None:
    """The is_trusted_peer helper classifies private/loopback/link-local as
    trusted and public addresses as untrusted."""
    module = _load_rate_limit_module()
    is_trusted = module.is_trusted_peer
    for ip in ("10.0.0.1", "192.168.1.1", "172.16.0.1", "127.0.0.1", "::1",
               "169.254.1.1", "fe80::1", "fc00::1"):
        assert is_trusted(ip) is True, f"{ip} should be trusted"
    # NB: TEST-NET ranges (203.0.113.0/24 etc.) are classified private/reserved
    # by the stdlib, so use genuinely globally-routable addresses here.
    for ip in ("8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"):
        assert is_trusted(ip) is False, f"{ip} should be untrusted"
    # Garbage / unparseable input is never trusted.
    assert is_trusted("not-an-ip") is False
    assert is_trusted("") is False


# --------------------------------------------------------------------------- #
# Rust: structural parity for the trusted-proxy gate                           #
# --------------------------------------------------------------------------- #
def test_rust_gates_xff_on_trusted_peer() -> None:
    text = _RUST_PATH.read_text(encoding="utf-8")
    assert "is_trusted_peer" in text, (
        "rust rate limiter must gate X-Forwarded-For on a trusted transport "
        "peer via an is_trusted_peer(ip) helper so an untrusted (public) peer "
        "can't spoof its rate-limit key"
    )
    # The helper must classify private / loopback / link-local addresses.
    lowered = text.lower()
    assert "is_loopback" in lowered, (
        "is_trusted_peer must treat loopback addresses as trusted"
    )
    assert "is_private" in lowered or "is_link_local" in lowered, (
        "is_trusted_peer must treat private / link-local addresses as trusted"
    )
