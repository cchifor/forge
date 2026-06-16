"""End-to-end: generate each ``--platform`` preset, boot it with docker compose,
and assert the *assembled* platform actually runs.

This is the highest-fidelity gate in the suite: it scaffolds a real project from
a platform preset, builds the images, starts the containers, and exercises the
running system — health endpoints for every preset, plus a live
service-to-service (S2S) token round-trip for the synthesis presets (gateway
mints a token from the gatekeeper using the *synthesized* registry secret, then
calls a downstream service which verifies it).

Heavy + opt-in: marked ``e2e`` (excluded from the default ``pytest`` run) and
skipped unless Docker is available. On a shared host the ingress ``traefik``
service is intentionally NOT started (it binds host :80, which often collides);
all assertions run *in-network* via ``docker compose exec`` so no host ports are
needed. Every test tears its stack down (``down -v``) in a ``finally``.

Run explicitly::

    UV_PYTHON=3.13 pytest tests/e2e/test_platform_compose_boot.py -m e2e -v -s
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Generous ceilings — a cold build pulls base images + compiles native wheels.
_BUILD_TIMEOUT = 1500
_UP_TIMEOUT = 360
_EXEC_TIMEOUT = 45
_HEALTH_WAIT = 180


def _forge_generate(preset: str, name: str, out_dir: Path) -> Path:
    """Scaffold ``preset`` via the real CLI; return the project root."""
    proc = subprocess.run(
        [
            sys.executable, "-m", "forge",
            "--platform", preset,
            "--project-name", name,
            "--output-dir", str(out_dir),
            "--no-docker", "--yes",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"forge --platform {preset} failed:\n{proc.stdout}\n{proc.stderr}"
    root = out_dir / name
    assert (root / "docker-compose.yml").is_file(), f"no docker-compose.yml for {preset}"
    return root


def _compose(root: Path, *args: str, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["docker", "compose", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            f"`docker compose {' '.join(args)}` failed ({proc.returncode}):\n"
            f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        )
    return proc


def _services(root: Path) -> list[str]:
    out = _compose(root, "config", "--services").stdout
    return [s.strip() for s in out.splitlines() if s.strip()]


def _boot(root: Path) -> None:
    """Build + start every service except ``traefik`` (the host-:80 ingress)."""
    services = [s for s in _services(root) if s != "traefik"]
    _compose(root, "up", "-d", "--build", *services, timeout=_BUILD_TIMEOUT + _UP_TIMEOUT)


def _wait_healthy(root: Path, services: list[str], timeout: int = _HEALTH_WAIT) -> None:
    """Block until each named long-running service reports docker-healthy."""
    deadline = time.monotonic() + timeout
    pending = set(services)
    last = ""
    while time.monotonic() < deadline:
        proc = _compose(root, "ps", "--format", "json", check=False)
        statuses = {}
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            statuses[rec.get("Service")] = rec.get("Health") or rec.get("State")
        last = ", ".join(f"{s}={statuses.get(s, '?')}" for s in services)
        if all(statuses.get(s) == "healthy" for s in pending):
            return
        time.sleep(4)
    raise AssertionError(f"services not healthy within {timeout}s: {last}")


def _exec_py(root: Path, service: str, script: str) -> str:
    """Run a python snippet inside ``service`` (in-network, no host ports)."""
    proc = _compose(
        root, "exec", "-T", service, "python", "-c", script,
        timeout=_EXEC_TIMEOUT, check=False,
    )
    assert proc.returncode == 0, (
        f"exec in {service} failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
    )
    return proc.stdout


def _teardown(root: Path) -> None:
    _compose(root, "down", "-v", "--remove-orphans", timeout=120, check=False)


# --- the health-check snippet, run inside a backend container ----------------
_HEALTH_SCRIPT = """
import json, urllib.request
base = "http://localhost:{port}"
for path in ["/api/v1/health/live", "/api/v1/health/ready", "/api/v1/info"]:
    r = urllib.request.urlopen(base + path, timeout=10)
    assert r.status == 200, path
print("HEALTH_OK")
"""

# --- the live S2S round-trip, run inside the gateway container ---------------
#
# This exercises a *protected* downstream route (``/api/v1/items``), not a
# health probe: the orders ``AuthContextMiddleware`` excludes ``/health*`` from
# verification, so only a non-excluded path actually drives the JWKS-backed
# token verifier. We prove two things end-to-end:
#   1. the verifier is live — a malformed bearer is rejected (401/403);
#   2. a token freshly minted from the synthesized registry secret is ACCEPTED
#      (200), which requires the backend to fetch gatekeeper's JWKS and validate
#      iss/aud/sig — the exact path that silently rejected valid tokens before
#      the server_url/audience + cold-start-retry fixes landed.
_S2S_SCRIPT = """
import os, json, urllib.request, urllib.parse, urllib.error
ep = os.environ["GATEKEEPER_TOKEN_ENDPOINT"]
cid = os.environ["GATEKEEPER_CLIENT_ID"]; sec = os.environ["GATEKEEPER_CLIENT_SECRET"]
orders = os.environ["INTERNAL_SERVICE_URL_ORDERS"]
items = orders + "/api/v1/items"

def status_for(headers):
    req = urllib.request.Request(items, headers=headers)
    try:
        return urllib.request.urlopen(req, timeout=10).status
    except urllib.error.HTTPError as e:
        return e.code

# 1) the verifier is engaged: a malformed bearer must be rejected.
bad = status_for({"Authorization": "Bearer not.a.jwt"})
assert bad in (401, 403), "verifier accepted a malformed token: %s" % bad

# 2) mint a real S2S token from the synthesized registry secret.
body = urllib.parse.urlencode({
    "grant_type": "client_credentials", "client_id": cid, "client_secret": sec,
    "audience": "svc-orders", "scope": "orders:read",
    "tenant_id": "00000000-0000-0000-0000-000000000001",
}).encode()
req = urllib.request.Request(ep, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
tok = json.load(urllib.request.urlopen(req, timeout=10))["access_token"]
assert tok.count(".") == 2, "minted token is not a JWT"

# 3) the SAME protected route now ACCEPTS the gatekeeper token.
ok = status_for({"Authorization": "Bearer " + tok})
assert ok == 200, "downstream rejected a valid gatekeeper token: %s" % ok
print("S2S_OK")
"""


def test_monolithic_platform_boots_and_serves(tmp_path: Path, require_docker: None) -> None:
    """`--platform monolithic`: backend boots, connects to postgres, serves CRUD."""
    root = _forge_generate("monolithic", "monoboot", tmp_path)
    try:
        _boot(root)
        _wait_healthy(root, ["backend"])
        assert "HEALTH_OK" in _exec_py(root, "backend", _HEALTH_SCRIPT.format(port=5000))
        items = _exec_py(
            root, "backend",
            "import urllib.request; print(urllib.request.urlopen("
            "'http://localhost:5000/api/v1/items', timeout=10).status)",
        )
        assert "200" in items
    finally:
        _teardown(root)


def test_headless_api_platform_s2s_round_trip(tmp_path: Path, require_docker: None) -> None:
    """`--platform headless-api`: gatekeeper + 2 services boot; a live S2S token
    minted from the synthesized registry secret is accepted by the downstream."""
    root = _forge_generate("headless-api", "hapiboot", tmp_path)
    try:
        _boot(root)
        _wait_healthy(root, ["keycloak", "gatekeeper", "gateway", "orders"])
        assert "HEALTH_OK" in _exec_py(root, "orders", _HEALTH_SCRIPT.format(port=5020))
        assert "S2S_OK" in _exec_py(root, "gateway", _S2S_SCRIPT)
    finally:
        _teardown(root)


def test_microservices_platform_s2s_round_trip(tmp_path: Path, require_docker: None) -> None:
    """`--platform microservices`: the full synthesis stack (3 services + event
    bus + frontend) boots and the S2S round-trip works."""
    root = _forge_generate("microservices", "msvcboot", tmp_path)
    try:
        _boot(root)
        _wait_healthy(root, ["keycloak", "gatekeeper", "gateway", "orders", "inventory"])
        assert "S2S_OK" in _exec_py(root, "gateway", _S2S_SCRIPT)
    finally:
        _teardown(root)


def test_multitenant_saas_platform_boots_and_serves(tmp_path: Path, require_docker: None) -> None:
    """`--platform multitenant-saas`: the full multi-tenant topology — Keycloak +
    gatekeeper + the TMS control plane + the RLS-isolated app service — boots and
    both backend tiers serve their health surface in-network.

    (No S2S round-trip here: this preset puts the gatekeeper at the edge rather
    than synthesizing an api-gateway, so the `_S2S_SCRIPT` env contract that the
    microservices/headless presets rely on isn't present.)
    """
    root = _forge_generate("multitenant-saas", "mtsaasboot", tmp_path)
    try:
        _boot(root)
        _wait_healthy(root, ["keycloak", "gatekeeper", "tms", "app"])
        # The TMS control plane and the tenant-scoped app both serve.
        assert "HEALTH_OK" in _exec_py(root, "tms", _HEALTH_SCRIPT.format(port=5010))
        assert "HEALTH_OK" in _exec_py(root, "app", _HEALTH_SCRIPT.format(port=5020))
    finally:
        _teardown(root)
