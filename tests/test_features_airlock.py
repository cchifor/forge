"""Invariants for ``forge.features.airlock`` — Airlock sandbox client."""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY
from forge.options import OPTION_REGISTRY


def test_airlock_client_option_registered() -> None:
    assert "airlock.client" in OPTION_REGISTRY
    opt = OPTION_REGISTRY["airlock.client"]
    assert opt.default is False
    assert opt.enables[True] == ("airlock_client",)


def test_airlock_client_fragment_registered() -> None:
    assert "airlock_client" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["airlock_client"]
    assert BackendLanguage.PYTHON in frag.implementations
    assert frag.parity_tier == 3
    impl = frag.implementations[BackendLanguage.PYTHON]
    assert "weld-airlock" in impl.dependencies


def test_airlock_client_emits_env_vars() -> None:
    frag = FRAGMENT_REGISTRY["airlock_client"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    env_paths = {name for name, _default in impl.env_vars}
    assert "AIRLOCK_BASE_URL" in env_paths
    assert "AIRLOCK_TOKEN" in env_paths


def test_airlock_client_scaffolds_clients_directory() -> None:
    frag = FRAGMENT_REGISTRY["airlock_client"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    files_root = Path(impl.fragment_dir) / "files"
    assert (files_root / "src" / "app" / "clients" / "__init__.py").is_file()
    assert (files_root / "src" / "app" / "clients" / "airlock.py").is_file()


def test_airlock_client_inject_wires_shutdown_hook() -> None:
    """The httpx session inside AsyncAirlockClient needs aclose() at
    shutdown to drain in-flight connections."""
    frag = FRAGMENT_REGISTRY["airlock_client"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    inject = Path(impl.fragment_dir) / "inject.yaml"
    text = inject.read_text(encoding="utf-8")
    assert "FORGE:LIFESPAN_SHUTDOWN" in text
    assert "aclose" in text
