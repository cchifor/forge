"""Invariants for ``forge.features.streaming`` — SSE fanout via weld-streaming."""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY
from forge.options import OPTION_REGISTRY


def test_streaming_sse_option_registered() -> None:
    assert "streaming.sse" in OPTION_REGISTRY
    opt = OPTION_REGISTRY["streaming.sse"]
    assert opt.default is False
    assert opt.enables[True] == ("streaming_sse",)
    assert opt.stability == "beta"


def test_streaming_sse_fragment_registered() -> None:
    assert "streaming_sse" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["streaming_sse"]
    assert BackendLanguage.PYTHON in frag.implementations
    assert frag.parity_tier == 3


def test_streaming_sse_depends_on_events_core() -> None:
    """The streamer subscribes to the EventBus, so events_core must be
    present in any plan that includes streaming_sse."""
    frag = FRAGMENT_REGISTRY["streaming_sse"]
    assert frag.depends_on == ("events_core",)


def test_streaming_sse_declares_weld_streaming_and_sse_starlette() -> None:
    frag = FRAGMENT_REGISTRY["streaming_sse"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    assert "weld-streaming" in impl.dependencies
    assert any(d.startswith("sse-starlette") for d in impl.dependencies)


def test_streaming_sse_files_present() -> None:
    frag = FRAGMENT_REGISTRY["streaming_sse"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    files_root = Path(impl.fragment_dir) / "files"
    assert (files_root / "src" / "app" / "streaming" / "__init__.py").is_file()
    assert (files_root / "src" / "app" / "streaming" / "streamer.py").is_file()
    assert (files_root / "src" / "app" / "api" / "v1" / "endpoints" / "stream.py").is_file()


def test_streaming_sse_inject_yaml_mounts_router() -> None:
    frag = FRAGMENT_REGISTRY["streaming_sse"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    inject = Path(impl.fragment_dir) / "inject.yaml"
    text = inject.read_text(encoding="utf-8")
    assert "FORGE:API_ROUTER_REGISTRATION" in text
    assert "stream_endpoint.router" in text
