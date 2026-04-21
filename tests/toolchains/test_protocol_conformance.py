"""Protocol-conformance tests for :class:`BackendToolchain`.

Every entry in :data:`BACKEND_REGISTRY` — built-in or plugin-registered —
must carry a toolchain that satisfies the :class:`BackendToolchain`
Protocol. These tests catch two regression classes:

1. A contributor adds a new ``BackendSpec(...)`` without setting
   ``toolchain``; the default factory should still produce a Noop.
2. A plugin registers a backend with a broken toolchain object
   (missing method, wrong signature); ``runtime_checkable`` catches it.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from forge.config import BACKEND_REGISTRY
from forge.toolchains import NOOP_TOOLCHAIN, BackendToolchain, Check, NoopToolchain
from forge.toolchains.node import NODE_TOOLCHAIN
from forge.toolchains.python import PYTHON_TOOLCHAIN
from forge.toolchains.rust import RUST_TOOLCHAIN


@pytest.mark.parametrize(
    "lang_spec",
    list(BACKEND_REGISTRY.items()),
    ids=lambda item: item[0].value,
)
def test_every_registered_backend_has_a_toolchain(lang_spec):
    _lang, spec = lang_spec
    assert spec.toolchain is not None, f"{spec.display_label} has no toolchain"
    assert isinstance(spec.toolchain, BackendToolchain), (
        f"{spec.display_label}'s toolchain {spec.toolchain!r} doesn't satisfy "
        "the BackendToolchain Protocol"
    )
    # Every toolchain must advertise a short name for diagnostic output.
    assert spec.toolchain.name
    assert isinstance(spec.toolchain.name, str)


@pytest.mark.parametrize(
    "toolchain",
    [PYTHON_TOOLCHAIN, NODE_TOOLCHAIN, RUST_TOOLCHAIN, NOOP_TOOLCHAIN],
    ids=lambda tc: tc.name,
)
def test_toolchain_methods_accept_expected_signature(toolchain):
    """All three methods take ``backend_dir`` + keyword ``quiet`` and
    return the expected shape. Keeps the Protocol honest over time."""
    for method_name in ("install", "verify", "post_generate"):
        method = getattr(toolchain, method_name)
        sig = inspect.signature(method)
        params = dict(sig.parameters)
        assert "backend_dir" in params
        assert "quiet" in params


def test_noop_toolchain_returns_empty_check_list(tmp_path: Path) -> None:
    assert NOOP_TOOLCHAIN.verify(tmp_path) == []
    assert NOOP_TOOLCHAIN.install(tmp_path) is None
    assert NOOP_TOOLCHAIN.post_generate(tmp_path) is None


def test_noop_toolchain_is_default_for_backend_spec_without_toolchain() -> None:
    """A ``BackendSpec(...)`` without an explicit toolchain gets the Noop.

    Regression guard: the default_factory was added to avoid forcing
    every ``BackendSpec`` call-site (including plugin code) to import
    :class:`NoopToolchain`. Breaking the factory silently would ship a
    ``BackendSpec`` with no toolchain and blow up at dispatch time.
    """
    from forge.config import BackendSpec

    spec = BackendSpec(
        template_dir="services/fake",
        display_label="Fake",
        version_field="fake_version",
        version_choices=("1.0",),
    )
    assert isinstance(spec.toolchain, NoopToolchain)
    assert spec.toolchain.verify(Path("/tmp")) == []


def test_check_is_failure_discriminator() -> None:
    """The ``is_failure`` helper narrows the four states into a bool
    used by the matrix runner's lane-B exit-code logic (any ``fail`` ⇒
    non-zero exit)."""
    assert Check(name="x", status="fail").is_failure()
    assert not Check(name="x", status="ok").is_failure()
    assert not Check(name="x", status="warn").is_failure()
    assert not Check(name="x", status="skip").is_failure()
