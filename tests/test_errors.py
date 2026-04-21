"""Tests for the ``forge.errors`` hierarchy introduced in Epic D (1.1.0)."""

from __future__ import annotations

import pytest

from forge.errors import (
    FRAGMENT_DIR_MISSING,
    INJECTION_ANCHOR_NOT_FOUND,
    INJECTION_MARKER_AMBIGUOUS,
    MERGE_CONFLICT,
    OPTIONS_UNKNOWN_PATH,
    PLUGIN_COLLISION,
    PROVENANCE_MANIFEST_MISSING,
    ForgeError,
    FragmentError,
    GeneratorError,
    InjectionError,
    MergeError,
    OptionsError,
    PluginError,
    ProvenanceError,
)

# ---------------------------------------------------------------------------
# Base class construction + envelope
# ---------------------------------------------------------------------------


def test_forge_error_default_code_is_base() -> None:
    err = ForgeError("something broke")
    assert err.message == "something broke"
    assert err.code == "FORGE_ERROR"
    assert err.hint is None
    assert err.context == {}


def test_forge_error_accepts_code_hint_context() -> None:
    err = ForgeError(
        "boom",
        code="CUSTOM_CODE",
        hint="try reading the docs",
        context={"file": "/tmp/x"},
    )
    assert err.code == "CUSTOM_CODE"
    assert err.hint == "try reading the docs"
    assert err.context == {"file": "/tmp/x"}


def test_as_envelope_omits_empty_hint_and_context() -> None:
    err = ForgeError("boom", code="BOOM")
    env = err.as_envelope()
    assert env == {"error": "boom", "code": "BOOM"}


def test_as_envelope_includes_hint_and_context() -> None:
    err = ForgeError("boom", code="BOOM", hint="do X", context={"k": "v"})
    env = err.as_envelope()
    assert env == {"error": "boom", "code": "BOOM", "hint": "do X", "context": {"k": "v"}}


def test_context_is_copied_not_referenced() -> None:
    source = {"file": "/tmp/x"}
    err = ForgeError("boom", context=source)
    source["file"] = "/tmp/mutated"
    assert err.context == {"file": "/tmp/x"}


# ---------------------------------------------------------------------------
# Subclass default codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cls", "expected_default"),
    [
        (OptionsError, "OPTIONS_ERROR"),
        (FragmentError, "FRAGMENT_ERROR"),
        (InjectionError, "INJECTION_ERROR"),
        (MergeError, "MERGE_ERROR"),
        (ProvenanceError, "PROVENANCE_ERROR"),
        (PluginError, "PLUGIN_ERROR"),
    ],
)
def test_subclass_default_codes(cls: type[ForgeError], expected_default: str) -> None:
    err = cls("some message")
    assert err.code == expected_default


def test_subclass_accepts_specific_code() -> None:
    err = OptionsError("unknown path", code=OPTIONS_UNKNOWN_PATH, context={"path": "rag.foo"})
    assert err.code == "OPTIONS_UNKNOWN_PATH"
    assert err.context == {"path": "rag.foo"}


# ---------------------------------------------------------------------------
# Hierarchy + alias
# ---------------------------------------------------------------------------


def test_every_subclass_is_a_forge_error() -> None:
    for cls in (
        OptionsError,
        FragmentError,
        InjectionError,
        MergeError,
        ProvenanceError,
        PluginError,
    ):
        assert issubclass(cls, ForgeError)
        assert issubclass(cls, RuntimeError)


def test_generator_error_is_alias_of_forge_error() -> None:
    # Deprecated alias retained through 1.x so ``except GeneratorError:``
    # callers keep catching every forge failure (including new subclasses).
    assert GeneratorError is ForgeError
    err = OptionsError("x", code=OPTIONS_UNKNOWN_PATH)
    assert isinstance(err, GeneratorError)


def test_except_generator_error_still_catches_subclasses() -> None:
    with pytest.raises(GeneratorError):
        raise FragmentError("missing dir", code=FRAGMENT_DIR_MISSING)

    with pytest.raises(GeneratorError):
        raise InjectionError("no anchor", code=INJECTION_ANCHOR_NOT_FOUND)


# ---------------------------------------------------------------------------
# Exit-code mapping via _exit_code_for
# ---------------------------------------------------------------------------


def test_exit_code_mapping() -> None:
    from forge.cli.main import _exit_code_for

    assert _exit_code_for(OptionsError("x", code=OPTIONS_UNKNOWN_PATH)) == 2
    assert _exit_code_for(FragmentError("x", code=FRAGMENT_DIR_MISSING)) == 2
    assert _exit_code_for(InjectionError("x", code=INJECTION_MARKER_AMBIGUOUS)) == 3
    assert _exit_code_for(MergeError("x", code=MERGE_CONFLICT)) == 4
    assert _exit_code_for(ProvenanceError("x", code=PROVENANCE_MANIFEST_MISSING)) == 5
    assert _exit_code_for(PluginError("x", code=PLUGIN_COLLISION)) == 6
    # Base class falls back to generic 2
    assert _exit_code_for(ForgeError("generic")) == 2


# ---------------------------------------------------------------------------
# JSON envelope emission through _json_error
# ---------------------------------------------------------------------------


def test_json_error_envelope_for_forge_error(capsys: pytest.CaptureFixture[str]) -> None:
    import io

    from forge.cli.main import _json_error

    out = io.StringIO()
    err = InjectionError(
        "missing anchor for MIDDLEWARE_IMPORTS",
        code=INJECTION_ANCHOR_NOT_FOUND,
        hint="add `# forge:anchor middleware.imports`",
        context={"file": "/tmp/app.py"},
    )
    with pytest.raises(SystemExit) as exc_info:
        _json_error(out, err)
    assert exc_info.value.code == 3  # InjectionError → exit 3

    import json

    payload = json.loads(out.getvalue())
    assert payload == {
        "error": "missing anchor for MIDDLEWARE_IMPORTS",
        "code": "INJECTION_ANCHOR_NOT_FOUND",
        "hint": "add `# forge:anchor middleware.imports`",
        "context": {"file": "/tmp/app.py"},
    }


def test_json_error_envelope_for_plain_string() -> None:
    """Legacy callers pass ``str(e)`` from ValueError/KeyError catches."""
    import io
    import json

    from forge.cli.main import _json_error

    out = io.StringIO()
    with pytest.raises(SystemExit) as exc_info:
        _json_error(out, "raw string message")
    assert exc_info.value.code == 2

    payload = json.loads(out.getvalue())
    assert payload == {"error": "raw string message"}
