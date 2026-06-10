"""Generated Node/Rust services must shut down gracefully.

Without a SIGTERM handler, a rollout (which sends SIGTERM) cuts in-flight
requests mid-response. Python is already correct via the FastAPI lifespan
teardown; these assert the Node + Rust entrypoints drain on signal."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_NODE = _ROOT / "forge/templates/services/node-service-template/template/src/index.ts"
_RUST = _ROOT / "forge/templates/services/rust-service-template/template/src/main.rs"


def test_node_drains_on_sigterm():
    src = _NODE.read_text(encoding="utf-8")
    assert "SIGTERM" in src and "SIGINT" in src
    assert "app.close()" in src, "must await Fastify close() to drain connections"


def test_rust_serves_with_graceful_shutdown():
    src = _RUST.read_text(encoding="utf-8")
    assert ".with_graceful_shutdown(shutdown_signal())" in src
    assert "SignalKind::terminate()" in src, "must handle SIGTERM, not just Ctrl-C"
