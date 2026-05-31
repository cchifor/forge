"""GA hardening source-assertion tests for the python-service-template.

The forge venv can't import the generated FastAPI app, so these tests read
the template text and assert on the hardening invariants the generator must
preserve:

* WS-8.2 — the python service Dockerfile pins deps with ``uv sync --frozen``
  so the committed ``uv.lock`` is authoritative (no silent re-resolve).
* WS-6.4 — the OpenAPI ``responses`` advertise the single richer
  ``Error{message, type, detail}`` model for *every* error status code
  (400/401/403/404/409/422/500), the HTTP/validation/global handlers all
  build that model through the shared ``_envelope`` helper, and the errors
  module carries a CHANGELOG/deprecation note describing the convergence.

  NOTE: the domain (``ApplicationError``) handler's RFC-007 wire body
  ``{"error": {...}}`` is intentionally left in place — it is a deliberate
  cross-stack contract shared byte-for-byte with the node and rust backends
  via the observability ``ErrorPort`` adapters and locked by
  ``tests/test_error_port.py``. Flipping that wire shape can only happen in
  lockstep with those sibling adapters, so this slice unifies the *documented*
  contract (OpenAPI) and records the deprecation rather than breaking
  tri-language parity.
* WS-2.9 — the unauthenticated ``/api/v1/admin/log-level`` route is gated
  (admin scope / ENV guard), not reachable unconditionally in prod builds.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (
    REPO_ROOT
    / "forge"
    / "templates"
    / "services"
    / "python-service-template"
    / "template"
)


def _read(rel: str) -> str:
    return (TEMPLATE / rel).read_text(encoding="utf-8")


# --- WS-8.2: frozen install ---------------------------------------------------


def test_dockerfile_uv_sync_is_frozen():
    df = _read("Dockerfile.jinja")
    # Every ``uv sync`` invocation must pin to the committed lockfile.
    sync_lines = [ln for ln in df.splitlines() if "uv sync" in ln and "RUN" in ln]
    assert sync_lines, "expected at least one `RUN uv sync` line in the Dockerfile"
    for line in sync_lines:
        assert "--frozen" in line, f"`uv sync` line is not frozen: {line!r}"


def test_dockerfile_keeps_no_dev_no_editable():
    df = _read("Dockerfile.jinja")
    # The frozen change must not drop the existing prod-install flags.
    for line in df.splitlines():
        if "uv sync" in line and "RUN" in line:
            assert "--no-dev" in line
            assert "--no-editable" in line


# --- WS-6.4: unified error envelope (OpenAPI + deprecation note) -------------


def test_openapi_responses_unify_error_model_for_all_codes():
    main = _read("src/app/main.py")
    responses_block = main.split("responses=", 1)[1].split("_configure_middleware", 1)[0]
    # The unified model must be advertised for the domain status codes too,
    # not just the original 400/422/500.
    for code in (
        "HTTP_400_BAD_REQUEST",
        "HTTP_401_UNAUTHORIZED",
        "HTTP_403_FORBIDDEN",
        "HTTP_404_NOT_FOUND",
        "HTTP_409_CONFLICT",
        "HTTP_422_UNPROCESSABLE_CONTENT",
        "HTTP_500_INTERNAL_SERVER_ERROR",
    ):
        assert code in responses_block, f"OpenAPI responses missing {code}"
    # Exactly one response model is advertised across all codes.
    assert '{"model": Error}' in responses_block
    assert "model" not in responses_block.replace('{"model": Error}', "")


def test_handlers_share_the_error_model_builder():
    errors = _read("src/app/core/errors.py.jinja")
    # The shared ``_envelope`` builder constructs the richer Error{...} model
    # and is what HTTP / validation / global handlers funnel through.
    envelope_block = errors.split("def _envelope(", 1)[1].split("\ndef ", 1)[0]
    assert "Error(" in envelope_block
    assert "detail=" in envelope_block
    for handler in (
        "http_exception_handler",
        "validation_exception_handler",
        "global_exception_handler",
    ):
        block = errors.split(f"def {handler}", 1)[1].split("\ndef ", 1)[0]
        assert "_envelope(" in block, f"{handler} not on the unified _envelope builder"


def test_error_module_documents_envelope_deprecation():
    errors = _read("src/app/core/errors.py.jinja")
    lowered = errors.lower()
    assert "deprecat" in lowered, "missing deprecation note for the domain error shape"
    # The note references the WS-6.4 convergence and the legacy domain shape so
    # consumers know which read path is on the way out.
    assert "ws-6.4" in lowered
    assert '{"error"' in errors or 'body["error"]' in errors


# --- WS-2.9: gated log-level route -------------------------------------------


def test_log_level_route_is_gated():
    admin = _read("src/app/api/v1/endpoints/admin.py")
    # The route stays in source (kept for non-prod diagnostics) ...
    assert "/log-level" in admin
    assert "set_log_level" in admin
    # ... but must not be reachable unconditionally: an ENV / scope guard
    # has to stand in front of the handler.
    gated = (
        "ENV" in admin
        or "environment" in admin
        or "Depends(" in admin
        or "Security(" in admin
        or "scope" in admin.lower()
    )
    assert gated, "log-level route has no ENV/scope guard — unauthenticated in prod"
    # The guard must explicitly reject the production environment.
    assert "production" in admin or "PROD" in admin or "prod" in admin


def test_log_level_guard_applies_to_whole_router():
    admin = _read("src/app/api/v1/endpoints/admin.py")
    # The guard is attached at the router level so it covers every admin route,
    # not just the one endpoint that exists today.
    assert "APIRouter(dependencies=[" in admin
    assert "require_non_production" in admin
