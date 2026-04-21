"""Unit tests for the RFC-006 smoke-contract helper module.

The main ``tests/matrix/smoke_contract.py`` module runs against a live
generated project during lane C. This test file is different — it
exercises the helper code itself (health checks, OpenAPI validation,
violation records) against a local stub server, so lane C isn't the
only place a regression in the contract logic gets caught.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tests.matrix.smoke_contract import (
    assert_contract,
    format_result,
    results_exit_code,
)


def _make_stub_handler(responses: dict[str, tuple[int, dict]]):
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            match = responses.get(self.path)
            if match is None:
                self.send_response(404)
                self.end_headers()
                return
            status, body = match
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            payload = json.dumps(body).encode("utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args, **_kwargs):
            return  # silence the stderr chatter

    return _Handler


@pytest.fixture
def stub_server(request):
    """Launch a stub HTTP server with a per-test response map.

    The test parametrizes ``responses`` via ``request.param``; the
    fixture tears the server down cleanly at the end.
    """
    responses: dict[str, tuple[int, dict]] = request.param
    handler = _make_stub_handler(responses)
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Give the thread a moment to actually bind before tests hit it
        # — without this the first connect occasionally races the accept.
        time.sleep(0.05)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


GOOD_SERVER_RESPONSES = {
    "/healthz": (200, {"status": "ok"}),
    "/readyz": (200, {"status": "UP", "components": {"database": "UP"}}),
    "/openapi.json": (
        200,
        {"openapi": "3.1.0", "paths": {"/api/v1/items": {}}, "info": {"title": "x"}},
    ),
}


@pytest.mark.parametrize("stub_server", [GOOD_SERVER_RESPONSES], indirect=True)
def test_happy_path_all_three_endpoints(stub_server: str) -> None:
    result = assert_contract(stub_server, scenario="test", backend_name="api")
    assert result.passed, format_result(result)
    assert result.scenario == "test"
    assert result.backend_name == "api"


MISSING_LIVENESS_RESPONSES = {
    "/readyz": (200, {"status": "UP"}),
    "/openapi.json": (200, {"openapi": "3.1.0", "paths": {"/x": {}}}),
}


@pytest.mark.parametrize("stub_server", [MISSING_LIVENESS_RESPONSES], indirect=True)
def test_missing_liveness_is_a_violation(stub_server: str) -> None:
    result = assert_contract(stub_server, scenario="test", backend_name="api")
    assert not result.passed
    endpoints = [v.endpoint for v in result.violations]
    assert "/healthz" in endpoints


WRONG_LIVENESS_STATUS = {
    "/healthz": (200, {"status": "BROKEN"}),
    "/readyz": (200, {"status": "UP"}),
    "/openapi.json": (200, {"openapi": "3.1.0", "paths": {"/x": {}}}),
}


@pytest.mark.parametrize("stub_server", [WRONG_LIVENESS_STATUS], indirect=True)
def test_liveness_must_report_ok_or_up(stub_server: str) -> None:
    result = assert_contract(stub_server, scenario="test", backend_name="api")
    assert not result.passed
    assert any("liveness 'status'" in v.reason for v in result.violations)


READINESS_503_IS_ALLOWED = {
    "/healthz": (200, {"status": "ok"}),
    "/readyz": (503, {"status": "DOWN", "components": {"database": "DOWN"}}),
    "/openapi.json": (200, {"openapi": "3.1.0", "paths": {"/x": {}}}),
}


@pytest.mark.parametrize("stub_server", [READINESS_503_IS_ALLOWED], indirect=True)
def test_readiness_503_is_allowed_when_deps_down(stub_server: str) -> None:
    """A readiness probe returning 503 is an honest signal that a
    dependency is unhealthy — not a contract violation. Lane C relies
    on this so compose-up can race healthchecks without flapping."""
    result = assert_contract(stub_server, scenario="test", backend_name="api")
    assert result.passed, format_result(result)


BAD_OPENAPI = {
    "/healthz": (200, {"status": "ok"}),
    "/readyz": (200, {"status": "UP"}),
    "/openapi.json": (200, {"paths": {"/x": {}}}),  # missing 'openapi' key
}


@pytest.mark.parametrize("stub_server", [BAD_OPENAPI], indirect=True)
def test_openapi_must_declare_version(stub_server: str) -> None:
    result = assert_contract(stub_server, scenario="test", backend_name="api")
    assert not result.passed
    assert any("openapi" in v.reason.lower() for v in result.violations)


OPENAPI_NO_PATHS = {
    "/healthz": (200, {"status": "ok"}),
    "/readyz": (200, {"status": "UP"}),
    "/openapi.json": (200, {"openapi": "3.1.0"}),
}


@pytest.mark.parametrize("stub_server", [OPENAPI_NO_PATHS], indirect=True)
def test_openapi_must_expose_at_least_one_path(stub_server: str) -> None:
    result = assert_contract(stub_server, scenario="test", backend_name="api")
    assert not result.passed
    assert any("path" in v.reason.lower() for v in result.violations)


def test_results_exit_code_zero_on_empty() -> None:
    assert results_exit_code([]) == 0


@pytest.mark.parametrize("stub_server", [GOOD_SERVER_RESPONSES], indirect=True)
def test_results_exit_code_zero_on_all_pass(stub_server: str) -> None:
    r = assert_contract(stub_server, scenario="x", backend_name="y")
    assert results_exit_code([r]) == 0


@pytest.mark.parametrize("stub_server", [MISSING_LIVENESS_RESPONSES], indirect=True)
def test_results_exit_code_two_on_any_fail(stub_server: str) -> None:
    r = assert_contract(stub_server, scenario="x", backend_name="y")
    assert results_exit_code([r]) == 2
