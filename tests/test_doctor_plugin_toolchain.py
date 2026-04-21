"""Tests for :func:`forge.doctor.check_registered_backends`.

Asserts two invariants:

1. Every built-in backend (Python / Node / Rust) appears in the doctor
   report with its toolchain name — regression guard against a
   refactor dropping the registry hookup.
2. A plugin-registered backend that attaches a real toolchain appears
   with status ``"ok"``; one that falls back to Noop appears with
   ``"warn"`` and a fix hint pointing at ``docs/adding-a-backend.md``.
"""

from __future__ import annotations

import pytest

from forge.config import BACKEND_REGISTRY, BackendSpec, register_backend_language
from forge.doctor import check_registered_backends
from forge.toolchains import Check, NOOP_TOOLCHAIN


class _FakeToolchain:
    """A BackendToolchain-satisfying stand-in for plugin tests."""

    name = "fake"

    def install(self, backend_dir, *, quiet: bool = False) -> None:  # noqa: ARG002
        return None

    def verify(self, backend_dir, *, quiet: bool = False) -> list[Check]:  # noqa: ARG002
        return []

    def post_generate(self, backend_dir, *, quiet: bool = False) -> None:  # noqa: ARG002
        return None


@pytest.fixture
def isolated_registry():
    """Snapshot-and-restore BACKEND_REGISTRY so tests can add plugin
    entries without leaking into each other or into the rest of the
    suite."""
    snapshot = dict(BACKEND_REGISTRY)
    yield BACKEND_REGISTRY
    BACKEND_REGISTRY.clear()
    BACKEND_REGISTRY.update(snapshot)


def test_built_in_backends_appear_in_doctor() -> None:
    results = check_registered_backends()
    names = {r.name for r in results}
    assert "backend:python" in names
    assert "backend:node" in names
    assert "backend:rust" in names


def test_built_in_rows_are_ok() -> None:
    """Built-ins ship real toolchains; any warn row here would mean a
    registry regression (spec lost its toolchain attr)."""
    for row in check_registered_backends():
        if row.name in ("backend:python", "backend:node", "backend:rust"):
            assert row.status == "ok", row.detail


def test_plugin_with_real_toolchain_shows_ok(isolated_registry) -> None:
    sentinel = register_backend_language("fakelang")
    isolated_registry[sentinel] = BackendSpec(
        template_dir="services/fake",
        display_label="FakeLang (Web)",
        version_field="fakelang_version",
        version_choices=("1.0",),
        toolchain=_FakeToolchain(),
    )

    rows = check_registered_backends()
    fake_row = next(r for r in rows if r.name == "backend:fakelang")
    assert fake_row.status == "ok"
    assert "FakeLang" in fake_row.detail
    assert "fake" in fake_row.detail


def test_plugin_with_noop_toolchain_shows_warn(isolated_registry) -> None:
    """A plugin that forgets to ship a toolchain ends up with Noop by
    default (via ``BackendSpec``'s factory). The doctor flags this so
    the plugin author knows install/verify hooks are skipped."""
    sentinel = register_backend_language("noopish")
    isolated_registry[sentinel] = BackendSpec(
        template_dir="services/noopish",
        display_label="Noopish",
        version_field="noopish_version",
        version_choices=("1.0",),
        # No toolchain= kwarg; default_factory provides NOOP_TOOLCHAIN.
    )

    rows = check_registered_backends()
    row = next(r for r in rows if r.name == "backend:noopish")
    assert row.status == "warn"
    assert "Noop" in row.detail
    assert row.fix is not None
    assert "docs/adding-a-backend.md" in row.fix


def test_explicit_noop_toolchain_also_warns(isolated_registry) -> None:
    """Same behavior as the default-noop case: explicitly passing
    ``NOOP_TOOLCHAIN`` should still warn, not sneak past the check."""
    sentinel = register_backend_language("explicit_noop")
    isolated_registry[sentinel] = BackendSpec(
        template_dir="services/en",
        display_label="Explicit Noop",
        version_field="en_version",
        version_choices=("1.0",),
        toolchain=NOOP_TOOLCHAIN,
    )

    rows = check_registered_backends()
    row = next(r for r in rows if r.name == "backend:explicit_noop")
    assert row.status == "warn"


def test_doctor_run_includes_backend_rows() -> None:
    """End-to-end: ``doctor.run()`` should embed the backend rows."""
    from forge.doctor import run  # noqa: PLC0415

    report = run()
    names = {r.name for r in report.results}
    assert any(n.startswith("backend:") for n in names), (
        "doctor report does not surface backend rows — "
        "check_registered_backends wasn't called"
    )
