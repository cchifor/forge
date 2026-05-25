"""Verify that body-size limit enforcement is present in all three backend templates.

Template files ship inside forge and get rendered into generated projects,
so we verify template content rather than importing them.
"""

from __future__ import annotations

from pathlib import Path

_TEMPLATES = Path(__file__).resolve().parent.parent / "forge" / "templates" / "services"

_PYTHON_BODY_LIMIT = (
    _TEMPLATES
    / "python-service-template"
    / "template"
    / "src"
    / "app"
    / "middleware"
    / "body_limit.py"
)

_PYTHON_MAIN = (
    _TEMPLATES
    / "python-service-template"
    / "template"
    / "src"
    / "app"
    / "main.py"
)

_NODE_APP = (
    _TEMPLATES
    / "node-service-template"
    / "template"
    / "src"
    / "app.ts.jinja"
)

_RUST_APP = (
    _TEMPLATES
    / "rust-service-template"
    / "template"
    / "src"
    / "app.rs"
)


class TestPythonBodyLimit:
    """Python template ships an ASGI body-size middleware."""

    def test_body_limit_module_exists(self):
        assert _PYTHON_BODY_LIMIT.exists(), "body_limit.py middleware missing from Python template"

    def test_returns_413_on_oversized_body(self):
        src = _PYTHON_BODY_LIMIT.read_text(encoding="utf-8")
        assert "413" in src, "body_limit.py must return HTTP 413 for oversized requests"

    def test_content_length_header_checked(self):
        src = _PYTHON_BODY_LIMIT.read_text(encoding="utf-8")
        assert "content-length" in src.lower(), "body_limit.py must check Content-Length header"

    def test_streaming_byte_counting(self):
        src = _PYTHON_BODY_LIMIT.read_text(encoding="utf-8")
        assert "received" in src, "body_limit.py must count bytes for chunked/streaming bodies"

    def test_wired_in_main(self):
        src = _PYTHON_MAIN.read_text(encoding="utf-8")
        assert "ContentSizeLimitMiddleware" in src, (
            "ContentSizeLimitMiddleware must be registered in main.py"
        )

    def test_guards_against_double_response(self):
        src = _PYTHON_BODY_LIMIT.read_text(encoding="utf-8")
        assert "response_started" in src, (
            "body_limit.py must track response_started to avoid ASGI double-response"
        )


class TestNodeBodyLimit:
    """Node/Fastify template configures bodyLimit in the constructor."""

    def test_body_limit_in_fastify_options(self):
        src = _NODE_APP.read_text(encoding="utf-8")
        assert "bodyLimit" in src, "Fastify constructor must include bodyLimit option"

    def test_body_limit_value(self):
        src = _NODE_APP.read_text(encoding="utf-8")
        assert "1_048_576" in src, "Fastify bodyLimit should be 1 MiB (1_048_576)"


class TestRustBodyLimit:
    """Rust/axum template applies DefaultBodyLimit layer."""

    def test_default_body_limit_import(self):
        src = _RUST_APP.read_text(encoding="utf-8")
        assert "DefaultBodyLimit" in src, "app.rs must import DefaultBodyLimit"

    def test_default_body_limit_layer(self):
        src = _RUST_APP.read_text(encoding="utf-8")
        assert "DefaultBodyLimit::max" in src, "app.rs must apply DefaultBodyLimit::max layer"

    def test_body_limit_value(self):
        src = _RUST_APP.read_text(encoding="utf-8")
        assert "1_048_576" in src, "DefaultBodyLimit should be 1 MiB (1_048_576)"
