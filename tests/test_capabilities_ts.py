"""The brownfield binding emits a `capabilities.ts` flag (plan §F).

`agentTransport` is `"external"` when the project binds an agent (subscribe-kind)
contract op to the upstream backend, and `"stub"` otherwise. The chat component
reads it at mount: `"stub"` disables the input and shows an inert message, so the
"runnable app" criterion holds even when no live agent transport is configured.
"""

from __future__ import annotations

from forge.codegen.openapi_binding import emit_capabilities


def test_external_transport() -> None:
    ts = emit_capabilities("external")
    assert 'export const agentTransport = "external"' in ts
    assert "as const" in ts  # narrows the literal type for consumers


def test_stub_transport() -> None:
    ts = emit_capabilities("stub")
    assert 'export const agentTransport = "stub"' in ts


def test_generated_banner_present() -> None:
    # A do-not-edit banner so users know it is regenerated on --update.
    assert "forge" in emit_capabilities("stub").lower()
    assert "do not edit" in emit_capabilities("stub").lower()


def test_rejects_unknown_transport() -> None:
    import pytest

    from forge.errors import GeneratorError

    with pytest.raises(GeneratorError):
        emit_capabilities("bogus")
