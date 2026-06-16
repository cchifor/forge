"""HSTS must honor ``x-forwarded-proto`` behind a TLS-terminating proxy.

The ``security_headers`` middleware feature gates HSTS on the request scheme
being ``https``. Behind the documented Traefik deploy (TLS terminated at the
proxy), the app sees plain ``http`` and the ``x-forwarded-proto: https`` header,
so the scheme check alone never emits ``Strict-Transport-Security``. The sibling
gatekeeper middleware already reads ``x-forwarded-proto``; the standalone feature
template (Python AND Rust variants) must do the same.

These are structural assertions over the shipped template source — behavioural
verification lives in the generated-project test suite.
"""

from __future__ import annotations

from pathlib import Path

FEATURE_ROOT = (
    Path(__file__).resolve().parent.parent
    / "forge"
    / "features"
    / "middleware"
    / "templates"
    / "security_headers"
)

PYTHON_MW = (
    FEATURE_ROOT
    / "python"
    / "files"
    / "src"
    / "app"
    / "middleware"
    / "security_headers.py"
)

RUST_MW = FEATURE_ROOT / "rust" / "files" / "src" / "middleware" / "security_headers.rs"


def test_python_security_headers_honors_forwarded_proto() -> None:
    text = PYTHON_MW.read_text(encoding="utf-8")
    assert "x-forwarded-proto" in text, (
        "security_headers.py must read the x-forwarded-proto header so HSTS is "
        "emitted behind a TLS-terminating proxy (Traefik) where request.url.scheme "
        "is http — matching the sibling gatekeeper middleware."
    )


def test_rust_security_headers_honors_forwarded_proto() -> None:
    text = RUST_MW.read_text(encoding="utf-8")
    assert "x-forwarded-proto" in text, (
        "security_headers.rs must read the x-forwarded-proto header so HSTS is "
        "emitted behind a TLS-terminating proxy where uri().scheme_str() is http — "
        "matching the Python variant and the gatekeeper middleware."
    )
