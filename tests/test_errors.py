"""Tests for the ``forge.errors`` hierarchy introduced in Epic D (1.1.0)."""

from __future__ import annotations

import pytest

from forge.errors import (
    FILESYSTEM_IO_ERROR,
    FRAGMENT_DIR_MISSING,
    INJECTION_ANCHOR_NOT_FOUND,
    INJECTION_MARKER_AMBIGUOUS,
    MERGE_CONFLICT,
    OPTIONS_UNKNOWN_PATH,
    PLUGIN_COLLISION,
    PROVENANCE_MANIFEST_MISSING,
    TEMPLATE_JINJA_ERROR,
    TEMPLATE_NOT_FOUND,
    TEMPLATE_RENDER_FAILED,
    FilesystemError,
    ForgeError,
    FragmentError,
    GeneratorError,
    InjectionError,
    MergeError,
    OptionsError,
    PluginError,
    ProvenanceError,
    TemplateError,
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
        (TemplateError, "TEMPLATE_ERROR"),
        (FilesystemError, "FILESYSTEM_ERROR"),
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
        TemplateError,
        FilesystemError,
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


class TestDeprecatedGeneratorError:
    """Epic S (1.1.0-alpha.1) — reading ``GeneratorError`` from
    ``forge.errors`` now emits a DeprecationWarning. The suite
    as a whole silences this via ``pyproject.toml`` so noise doesn't
    drown out real signal; this class explicitly unsilences it to
    assert the warning still fires for third-party callers.
    """

    def test_getattr_emits_deprecation_warning(self) -> None:
        import importlib
        import warnings

        # Re-import to get a fresh module-attribute access path. Without
        # the reload, the already-resolved module attribute in this
        # test module's namespace doesn't re-trigger __getattr__.
        mod = importlib.import_module("forge.errors")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            val = mod.GeneratorError
        assert val is mod.ForgeError
        dep_warnings = [w for w in captured if issubclass(w.category, DeprecationWarning)]
        assert dep_warnings, (
            "expected a DeprecationWarning when reading "
            "forge.errors.GeneratorError; got none"
        )
        assert "GeneratorError is deprecated" in str(dep_warnings[0].message)

    def test_unknown_attribute_still_raises_attribute_error(self) -> None:
        import forge.errors

        with pytest.raises(AttributeError, match="no attribute"):
            forge.errors.ThisNameDoesNotExist  # noqa: B018


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
    assert _exit_code_for(TemplateError("x", code=TEMPLATE_RENDER_FAILED)) == 7
    assert _exit_code_for(FilesystemError("x", code=FILESYSTEM_IO_ERROR)) == 8
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


# ---------------------------------------------------------------------------
# _run_copier error-path fidelity (Sprint 1 / change #3)
# ---------------------------------------------------------------------------


class TestRunCopierErrorFidelity:
    """``_run_copier`` used to collapse CopierError / OSError / RuntimeError
    into one ``GeneratorError(code="FORGE_ERROR")``. These cases pin the
    post-Epic-S three-way split so ``--json`` consumers can tell template
    authoring bugs from Jinja crashes from filesystem failures.
    """

    def test_missing_template_raises_template_not_found(self, tmp_path) -> None:
        from pathlib import Path

        from forge.generator import _run_copier

        missing = tmp_path / "does_not_exist"
        with pytest.raises(TemplateError) as exc_info:
            _run_copier(missing, Path(tmp_path) / "dst", {}, quiet=True)
        err = exc_info.value
        assert err.code == TEMPLATE_NOT_FOUND
        assert err.context["template"] == "does_not_exist"

    def test_copier_error_maps_to_template_render_failed(
        self, tmp_path, monkeypatch
    ) -> None:
        from copier.errors import CopierError

        from forge.generator import _run_copier

        template = tmp_path / "t"
        template.mkdir()

        def boom(*_args, **_kwargs):
            raise CopierError("copier blew up")

        monkeypatch.setattr("forge.generator.run_copy", boom)

        with pytest.raises(TemplateError) as exc_info:
            _run_copier(template, tmp_path / "dst", {}, quiet=True)
        err = exc_info.value
        assert err.code == TEMPLATE_RENDER_FAILED
        assert err.context["template"] == "t"
        assert err.context["copier_type"] == "CopierError"
        assert isinstance(err.__cause__, CopierError)

    def test_os_error_maps_to_filesystem_error(self, tmp_path, monkeypatch) -> None:
        from forge.generator import _run_copier

        template = tmp_path / "t"
        template.mkdir()

        def boom(*_args, **_kwargs):
            raise OSError(13, "Permission denied")

        monkeypatch.setattr("forge.generator.run_copy", boom)

        with pytest.raises(FilesystemError) as exc_info:
            _run_copier(template, tmp_path / "dst", {}, quiet=True)
        err = exc_info.value
        assert err.code == FILESYSTEM_IO_ERROR
        assert err.context["errno"] == 13
        assert err.context["strerror"] == "Permission denied"

    def test_runtime_error_maps_to_template_jinja_error(
        self, tmp_path, monkeypatch
    ) -> None:
        from forge.generator import _run_copier

        template = tmp_path / "t"
        template.mkdir()

        class CustomJinjaBoom(RuntimeError):
            pass

        def boom(*_args, **_kwargs):
            raise CustomJinjaBoom("undefined variable 'xyz'")

        monkeypatch.setattr("forge.generator.run_copy", boom)

        with pytest.raises(TemplateError) as exc_info:
            _run_copier(template, tmp_path / "dst", {}, quiet=True)
        err = exc_info.value
        assert err.code == TEMPLATE_JINJA_ERROR
        assert err.context["runtime_type"] == "CustomJinjaBoom"

    def test_forge_error_re_raise_preserves_subclass(self, tmp_path, monkeypatch) -> None:
        """``ForgeError`` already has the envelope it needs — re-raise
        untouched so callers don't see a double-wrapped TemplateError."""
        from forge.errors import InjectionError
        from forge.generator import _run_copier

        template = tmp_path / "t"
        template.mkdir()

        def boom(*_args, **_kwargs):
            raise InjectionError("inner", code="INNER_CODE")

        monkeypatch.setattr("forge.generator.run_copy", boom)

        with pytest.raises(InjectionError) as exc_info:
            _run_copier(template, tmp_path / "dst", {}, quiet=True)
        assert exc_info.value.code == "INNER_CODE"
