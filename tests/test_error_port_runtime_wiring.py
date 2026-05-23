"""Tests for Pillar E.1.b — wiring the ``error_port`` adapter into each
backend's central error-handler.

PR #89 shipped the port + default adapter as scaffolding only. This
follow-up routes the runtime request path through
``DefaultErrorPort.serialize`` so the port actually executes when an
exception escapes a handler. The wire shape stays RFC-007 — the goal
isn't a behavioural change for default deployments, it's making the
swappable adapter SLot reachable from production code (custom-envelope
plugins now have a real seam to override).

The runtime wiring is controlled per-backend by the Copier var
``include_error_envelope`` (Jinja-templated handler files). The var
defaults to ``True`` so existing projects pick up the port path on
their next ``forge --update``; flipping it to ``False`` preserves the
inline serialiser (E.1.b follow-up will sync this from
``observability.error_envelope`` automatically — until then the
default is the only path exercised end-to-end).

The behavioural cross-language envelope-shape test that codex flagged
on PR #89 (round 1 finding #1) is satisfied by the per-backend
integration tests under each template's ``tests/`` directory — those
spin up the real framework and assert the JSON wire shape EXACTLY.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge import variable_mapper
from forge.config import BackendConfig, BackendLanguage

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_ROOT = REPO_ROOT / "forge" / "templates" / "services"

PYTHON_HANDLER = TEMPLATES_ROOT / "python-service-template/template/src/app/core/errors.py.jinja"
NODE_HANDLER = (
    TEMPLATES_ROOT / "node-service-template/template/src/middleware/error-handler.ts.jinja"
)
RUST_HANDLER = TEMPLATES_ROOT / "rust-service-template/template/src/errors.rs.jinja"


def _render_jinja(template_path: Path, *, include_error_envelope: bool) -> str:
    """Render a Jinja template with ONLY the wiring flag set.

    Doesn't pull copier into the test path — the handler templates use a
    tiny subset of Jinja that ``jinja2`` renders directly. Keeps this
    test independent of Copier's rendering pipeline (which is exercised
    end-to-end by the matrix tests).
    """
    from jinja2 import Environment  # noqa: PLC0415

    env = Environment(
        keep_trailing_newline=True,
        autoescape=False,
        # Match Copier defaults so block tags etc. behave identically.
        trim_blocks=False,
        lstrip_blocks=False,
    )
    template = env.from_string(template_path.read_text(encoding="utf-8"))
    return template.render(include_error_envelope=include_error_envelope)


# -- handler files exist as .jinja (port-wiring is template-conditional) -----


@pytest.mark.parametrize(
    "handler",
    [PYTHON_HANDLER, NODE_HANDLER, RUST_HANDLER],
    ids=["python", "node", "rust"],
)
def test_central_handler_is_jinja_template(handler: Path) -> None:
    """The handler files must be Jinja templates so the port-wiring
    branch is conditionally compiled in/out. A regression to a static
    ``.py`` / ``.ts`` / ``.rs`` file would lose the disable-via-option
    knob."""
    assert handler.is_file(), f"central handler missing: {handler}"


# -- Python handler — Jinja conditional ---------------------------------------


def test_python_handler_imports_default_error_port_when_enabled() -> None:
    """With ``include_error_envelope=True`` the generated Python
    handler imports ``DefaultErrorPort`` from the fragment-shipped
    adapter and binds it to the ``_serialize_exception`` seam — the
    runtime path actually exercises the port."""
    rendered = _render_jinja(PYTHON_HANDLER, include_error_envelope=True)
    assert "from app.adapters.error_default import DefaultErrorPort" in rendered
    assert "_serialize_exception = DefaultErrorPort().serialize" in rendered
    # Soft-import safety net stays in place — the disabled fragment
    # case never crashes startup on a stale flag.
    assert "ImportError" in rendered


def test_python_handler_stays_inline_when_disabled() -> None:
    """With ``include_error_envelope=False`` the handler doesn't
    reference the fragment-shipped adapter at all — the port files
    aren't on disk in that mode and a stray import would break startup.
    The inline ``_default_serialize_exception`` owns the wire shape."""
    rendered = _render_jinja(PYTHON_HANDLER, include_error_envelope=False)
    assert "from app.adapters.error_default import DefaultErrorPort" not in rendered
    assert "_serialize_exception = _default_serialize_exception" in rendered


def test_python_handler_central_seam_is_called_from_domain_handler() -> None:
    """Both branches must funnel ``ApplicationError`` through
    ``_serialize_exception`` — that's the seam the port adapter binds
    to. If the central handler regresses to inline envelope
    construction we lose the runtime wiring."""
    for flag in (True, False):
        rendered = _render_jinja(PYTHON_HANDLER, include_error_envelope=flag)
        assert "_serialize_exception(exc)" in rendered, (
            f"domain handler must delegate to _serialize_exception (include_error_envelope={flag})"
        )
        assert "def status_for_code(code:" in rendered


# -- Node handler — Jinja conditional -----------------------------------------


def test_node_handler_dynamic_imports_adapter_when_enabled() -> None:
    """With ``include_error_envelope=True`` the Node handler
    dynamically imports the fragment-shipped adapter so the port is
    on the runtime path. The soft try/catch keeps the inline fallback
    available — same backwards-compat invariant as Python."""
    rendered = _render_jinja(NODE_HANDLER, include_error_envelope=True)
    assert 'import("../app/adapters/error-default.js")' in rendered
    assert "new mod.DefaultErrorPort()" in rendered
    # Soft import catches the missing-file case.
    assert "} catch" in rendered


def test_node_handler_stays_inline_when_disabled() -> None:
    """With ``include_error_envelope=False`` the dynamic import is
    stripped and the handler binds straight to ``defaultSerialize``."""
    rendered = _render_jinja(NODE_HANDLER, include_error_envelope=False)
    assert 'import("../app/adapters/error-default.js")' not in rendered
    assert "_serializeException: SerializeFn = defaultSerialize" in rendered


def test_node_handler_central_seam_is_called_from_app_error_branch() -> None:
    """Both branches must funnel ``AppError`` through
    ``_serializeException`` — the seam the port adapter overwrites."""
    for flag in (True, False):
        rendered = _render_jinja(NODE_HANDLER, include_error_envelope=flag)
        assert "_serializeException(error)" in rendered, (
            f"errorHandler must delegate to _serializeException (include_error_envelope={flag})"
        )
        assert "statusForCode(error.code)" in rendered


# -- Rust handler — Jinja conditional -----------------------------------------


def test_rust_handler_uses_default_error_port_when_enabled() -> None:
    """With ``include_error_envelope=True`` the ``IntoResponse for
    AppError`` impl delegates to ``DefaultErrorPort.serialize`` via the
    ``+ 'static`` dyn-cast (the PR #89 fix). When this branch is
    rendered the ``error_port`` fragment is expected to ship the port
    module — the resolver pairs them via the default-on option."""
    rendered = _render_jinja(RUST_HANDLER, include_error_envelope=True)
    assert "use crate::error_port::{ErrorPort, default::DefaultErrorPort}" in rendered
    assert "port.serialize(&self as &(dyn std::error::Error + 'static))" in rendered


def test_rust_handler_stays_inline_when_disabled() -> None:
    """With ``include_error_envelope=False`` the ``crate::error_port``
    use-statement is stripped — that's the load-bearing safety on Rust
    since the port module isn't on disk when the fragment is disabled
    (Rust has no soft-import equivalent)."""
    rendered = _render_jinja(RUST_HANDLER, include_error_envelope=False)
    # The doc-comment may reference ``crate::error_port`` documentarily;
    # what matters is the executable ``use`` + ``port.serialize`` calls
    # don't compile in. Strip lines whose first non-whitespace is ``//``
    # (Rust line comments) before searching.
    executable = "\n".join(
        line for line in rendered.splitlines() if not line.lstrip().startswith("//")
    )
    assert "use crate::error_port" not in executable
    assert "port.serialize" not in executable
    assert "default_envelope(&self)" in executable


def test_rust_handler_exposes_status_for_code_helper() -> None:
    """The Rust side gains a ``status_for_code`` helper for parity with
    Python + Node — fragments that mint new codes look up the matching
    status via the same vocabulary across backends."""
    rendered = _render_jinja(RUST_HANDLER, include_error_envelope=True)
    assert "pub fn status_for_code(code: &str)" in rendered


# -- variable_mapper threading ------------------------------------------------


def test_backend_context_defaults_include_error_envelope_to_true() -> None:
    """The default must be ``True`` so the port wiring lands on every
    project that doesn't explicitly opt out — mirrors
    ``observability.error_envelope``'s default. Failing this test means
    new projects ship without runtime wiring (silent regression vs
    PR #89's promise that the port becomes the canonical surface)."""
    bc = BackendConfig(
        name="svc",
        project_name="ErrorPortWiringTest",
        language=BackendLanguage.PYTHON,
        server_port=5000,
    )
    ctx = variable_mapper.backend_context(bc)
    assert ctx["include_error_envelope"] is True


def test_backend_context_threads_include_error_envelope_override() -> None:
    """Generator integration is a follow-up (the wiring from
    ``observability.error_envelope`` into the kwarg lives in
    ``generator.py`` which this PR scopes out). For now the kwarg is
    callable directly so tests + future generator threading land cleanly."""
    bc = BackendConfig(
        name="svc",
        project_name="ErrorPortWiringTest",
        language=BackendLanguage.PYTHON,
        server_port=5000,
    )
    ctx = variable_mapper.backend_context(bc, include_error_envelope=False)
    assert ctx["include_error_envelope"] is False


def test_backend_context_threads_per_backend() -> None:
    """All three backends must receive the same flag — cross-stack
    runtime-wiring parity. A Python-only flag would silently leave
    Node + Rust on the inline path."""
    for lang in (BackendLanguage.PYTHON, BackendLanguage.NODE, BackendLanguage.RUST):
        bc = BackendConfig(
            name="svc",
            project_name="ErrorPortWiringTest",
            language=lang,
            server_port=5000,
        )
        ctx = variable_mapper.backend_context(bc, include_error_envelope=True)
        assert ctx["include_error_envelope"] is True


# -- wire-shape invariant across all three rendered handlers ------------------


_RFC007_FIELDS = ("code", "message", "type", "context", "correlation_id")


@pytest.mark.parametrize(
    ("handler", "context_label"),
    [
        (PYTHON_HANDLER, "python-port-on"),
        (NODE_HANDLER, "node-port-on"),
        (RUST_HANDLER, "rust-port-on"),
    ],
)
def test_rendered_handler_keeps_rfc007_wire_shape(handler: Path, context_label: str) -> None:
    """When the port is wired (``include_error_envelope=True``), the
    rendered handler must reference every RFC-007 envelope field —
    otherwise the wire shape drifts away from the canonical contract
    the unified frontend client depends on."""
    rendered = _render_jinja(handler, include_error_envelope=True)
    for field in _RFC007_FIELDS:
        # Rust uses ``type_name`` internally for the keyword collision;
        # serde renames to ``type`` at serialize time, which we already
        # cover in the structural test against the port module itself.
        needle = "type_name" if field == "type" and "rust" in context_label else field
        assert needle in rendered, (
            f"{context_label}: rendered handler missing RFC-007 wire field "
            f"{field!r} (looking for {needle!r})"
        )
