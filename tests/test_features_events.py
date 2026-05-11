"""Invariants for the ``forge.features.events`` feature (1.2.0-alpha.1).

Verifies that the events.bus + events.outbox options wire through the
option registry, register the right fragments, and that the fragments'
template trees contain the files the generated service expects.
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY
from forge.options import OPTION_REGISTRY


def test_events_bus_option_registered() -> None:
    assert "events.bus" in OPTION_REGISTRY
    opt = OPTION_REGISTRY["events.bus"]
    assert opt.default == "none"
    assert opt.options == ("none", "postgres_notify", "memory")
    assert opt.enables["postgres_notify"] == ("events_core",)
    assert opt.enables["memory"] == ("events_core",)


def test_events_outbox_option_registered() -> None:
    assert "events.outbox" in OPTION_REGISTRY
    opt = OPTION_REGISTRY["events.outbox"]
    assert opt.default is True
    assert opt.enables[True] == ("events_outbox",)


def test_events_core_fragment_registered() -> None:
    assert "events_core" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["events_core"]
    assert BackendLanguage.PYTHON in frag.implementations
    assert BackendLanguage.NODE not in frag.implementations
    assert BackendLanguage.RUST not in frag.implementations
    assert frag.parity_tier == 3  # python-only — weld-events has no Node/Rust port
    assert "postgres" in frag.capabilities


def test_events_outbox_fragment_depends_on_core() -> None:
    assert "events_outbox" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["events_outbox"]
    assert frag.depends_on == ("events_core",)
    assert frag.parity_tier == 3


def test_events_core_declares_weld_events_dep() -> None:
    frag = FRAGMENT_REGISTRY["events_core"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    assert "weld-events" in impl.dependencies


def test_events_core_files_present() -> None:
    frag = FRAGMENT_REGISTRY["events_core"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    files_root = Path(impl.fragment_dir) / "files"
    assert (files_root / "src" / "app" / "events" / "__init__.py").is_file()
    assert (files_root / "src" / "app" / "events" / "bus.py").is_file()


def test_events_outbox_ships_migration() -> None:
    frag = FRAGMENT_REGISTRY["events_outbox"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    migration = (
        Path(impl.fragment_dir)
        / "files"
        / "alembic"
        / "versions"
        / "0002_outbox.py.jinja"
    )
    assert migration.is_file(), f"outbox migration missing: {migration}"
    text = migration.read_text(encoding="utf-8")
    assert 'op.create_table(\n        "outbox"' in text


def test_events_core_inject_yaml_targets_ioc_infra() -> None:
    frag = FRAGMENT_REGISTRY["events_core"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    inject = Path(impl.fragment_dir) / "inject.yaml"
    assert inject.is_file()
    text = inject.read_text(encoding="utf-8")
    assert "src/app/core/ioc/infra.py" in text
    assert "FORGE:IOC_INFRA_PROVIDERS" in text


def test_events_outbox_inject_yaml_wires_lifespan_hooks() -> None:
    frag = FRAGMENT_REGISTRY["events_outbox"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    inject = Path(impl.fragment_dir) / "inject.yaml"
    assert inject.is_file()
    text = inject.read_text(encoding="utf-8")
    assert "FORGE:LIFESPAN_STARTUP" in text
    assert "FORGE:LIFESPAN_SHUTDOWN" in text
