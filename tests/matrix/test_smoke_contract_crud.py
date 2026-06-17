"""CRUD-cycle checks in the RFC-006 smoke contract.

The contract historically asserted only health + OpenAPI, so a generated
backend whose data endpoints 500 (e.g. the no-auth unbound-``req.identity``
bug in the Node/Rust templates) sailed through lane C green. These tests pin
the new CRUD cycle: a 5xx on the entity list/create endpoint is a violation,
while a 4xx create (an entity schema the generic body didn't match) is
tolerated so the check stays robust across feature field variations.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from tests.matrix.smoke_contract import assert_contract, format_result

_HEALTH = {
    "/api/v1/health/live": (200, {"status": "UP"}),
    "/api/v1/health/ready": (200, {"status": "UP", "components": {"database": {"status": "UP"}}}),
}


def _make_handler(get_map: dict, post_map: dict):
    class _Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            payload = json.dumps(body).encode("utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):  # noqa: N802
            match = get_map.get(self.path)
            if match is None:
                self.send_response(404)
                self.end_headers()
                return
            self._send(*match)

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length:
                self.rfile.read(length)
            match = post_map.get(self.path)
            if match is None:
                self.send_response(404)
                self.end_headers()
                return
            self._send(*match)

        def log_message(self, *_args, **_kwargs):
            return

    return _Handler


def _serve(get_map: dict, post_map: dict):
    server = HTTPServer(("127.0.0.1", 0), _make_handler(get_map, post_map))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.05)
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_crud_list_5xx_is_a_violation() -> None:
    get_map = {**_HEALTH, "/api/v1/items": (500, {"error": "InternalError"})}
    server, url = _serve(get_map, {})
    try:
        result = assert_contract(url, "test", "api", crud_entities=["items"], readiness_wait_s=3)
    finally:
        server.shutdown()
        server.server_close()
    assert not result.passed, "a 5xx on the entity list endpoint must be a violation"
    assert any("items" in v.endpoint or "items" in v.reason for v in result.violations)


def test_crud_create_5xx_is_a_violation() -> None:
    get_map = {**_HEALTH, "/api/v1/items": (200, {"items": [], "total": 0})}
    post_map = {"/api/v1/items": (500, {"error": "InternalError"})}
    server, url = _serve(get_map, post_map)
    try:
        result = assert_contract(url, "test", "api", crud_entities=["items"], readiness_wait_s=3)
    finally:
        server.shutdown()
        server.server_close()
    assert not result.passed, "a 5xx on the entity create endpoint must be a violation"


def test_crud_happy_path_passes() -> None:
    get_map = {**_HEALTH, "/api/v1/items": (200, {"items": [], "total": 0})}
    post_map = {"/api/v1/items": (201, {"id": "1", "name": "x"})}
    server, url = _serve(get_map, post_map)
    try:
        result = assert_contract(url, "test", "api", crud_entities=["items"], readiness_wait_s=3)
    finally:
        server.shutdown()
        server.server_close()
    assert result.passed, format_result(result)


def test_crud_create_4xx_is_tolerated() -> None:
    """A 4xx create (generic body didn't match this entity's required fields)
    is NOT a violation — only 5xx is. Keeps the check robust across entities."""
    get_map = {**_HEALTH, "/api/v1/items": (200, {"items": []})}
    post_map = {"/api/v1/items": (422, {"error": "validation"})}
    server, url = _serve(get_map, post_map)
    try:
        result = assert_contract(url, "test", "api", crud_entities=["items"], readiness_wait_s=3)
    finally:
        server.shutdown()
        server.server_close()
    assert result.passed, format_result(result)
