"""Invariants for the Flutter AG-UI client deprecation (v2 Theme 9).

Before this theme the Flutter frontend template carried a local copy of
``AgUiClient`` at
``lib/src/features/chat/data/ag_ui_client.dart`` that had drifted from
the canonical implementation in ``packages/forge-canvas-dart``. This
test pins the consolidated state:

  * the deprecated local file is gone from the template tree
  * the chat providers import the client from ``package:forge_canvas``
  * ``forge_canvas`` is declared as a dep in the template's pubspec
  * the package's ``AgUiClient`` exposes the generic, parser-driven API
    that the chat layer relies on (runAgent helper + caller-supplied
    parser + onParseError hook)

These are static-asserts against the template tree — no copier run
needed, in keeping with the rest of the canvas test suite (see
``tests/test_canvas_lint_codegen.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE_ROOT = (
    _REPO_ROOT
    / "forge"
    / "templates"
    / "apps"
    / "flutter-frontend-template"
    / "{{project_slug}}"
)
_CHAT_ROOT = _TEMPLATE_ROOT / "lib" / "src" / "features" / "chat"
_PACKAGE_ROOT = _REPO_ROOT / "packages" / "forge-canvas-dart"


# ---------------------------------------------------------------------------
# Template-side invariants
# ---------------------------------------------------------------------------


class TestLocalClientGone:
    """The deprecated local copy must not ship to generated apps."""

    def test_template_root_exists(self) -> None:
        # Sanity guard — if the template moves, every other assertion in
        # this module silently passes against thin air.
        assert _CHAT_ROOT.is_dir(), (
            f"chat feature root missing at {_CHAT_ROOT}; template layout changed?"
        )

    def test_data_dir_has_no_ag_ui_client_dart(self) -> None:
        data_dir = _CHAT_ROOT / "data"
        assert data_dir.is_dir(), f"chat/data/ missing at {data_dir}"
        stragglers = [p for p in data_dir.iterdir() if p.name == "ag_ui_client.dart"]
        assert not stragglers, (
            f"deprecated local AgUiClient must be deleted; found {stragglers}"
        )

    def test_no_relative_imports_of_local_client_anywhere(self) -> None:
        """No file under the template should still import `data/ag_ui_client.dart`."""
        offenders: list[str] = []
        for path in _TEMPLATE_ROOT.rglob("*.dart"):
            text = path.read_text(encoding="utf-8")
            if "data/ag_ui_client.dart" in text:
                offenders.append(str(path.relative_to(_TEMPLATE_ROOT)))
        assert not offenders, (
            "stale imports of the deleted local client: "
            + ", ".join(offenders)
        )


class TestPackageImport:
    """Consumers must reach AgUiClient through the published package."""

    def test_chat_providers_imports_forge_canvas_package(self) -> None:
        providers = _CHAT_ROOT / "presentation" / "chat_providers.dart"
        text = providers.read_text(encoding="utf-8")
        assert "package:forge_canvas/forge_canvas.dart" in text, (
            "chat_providers.dart must import AgUiClient from package:forge_canvas"
        )

    def test_chat_providers_uses_fc_AgUiClient(self) -> None:
        """The provider should construct the package's generic AgUiClient.

        We accept either the `fc.AgUiClient` aliased form or an unaliased
        `AgUiClient` reference — what matters is that no other source of
        `AgUiClient` is visible (the local file is deleted).
        """
        providers = _CHAT_ROOT / "presentation" / "chat_providers.dart"
        text = providers.read_text(encoding="utf-8")
        assert "AgUiClient" in text, "AgUiClient reference missing entirely"
        # The package's API is generic; the provider must specialize it
        # with the local sealed event union so the reducer compiles.
        assert "AgUiClient<AgUiEvent>" in text, (
            "Provider must specialize fc.AgUiClient<AgUiEvent> so the "
            "package's generic parser binds to the local sealed event union"
        )

    def test_chat_providers_passes_parser(self) -> None:
        providers = _CHAT_ROOT / "presentation" / "chat_providers.dart"
        text = providers.read_text(encoding="utf-8")
        assert "AgUiEvent.parse" in text, (
            "Provider must pass AgUiEvent.parse as the parser callback"
        )


class TestPubspecDeclaresForgeCanvas:
    def test_forge_canvas_is_in_dependencies(self) -> None:
        pubspec = _TEMPLATE_ROOT / "pubspec.yaml"
        text = pubspec.read_text(encoding="utf-8")
        # The dep is wrapped in `{% if include_chat %}` — assert by
        # substring rather than parsing YAML (which would choke on Jinja).
        assert "forge_canvas:" in text, (
            "forge_canvas dependency must be declared in template pubspec"
        )

    def test_forge_canvas_pin_matches_published_alpha(self) -> None:
        pubspec = _TEMPLATE_ROOT / "pubspec.yaml"
        text = pubspec.read_text(encoding="utf-8")
        # The pin should reference an alpha that ships the generic
        # AgUiClient<E> API (alpha.6+).
        assert "forge_canvas: ^1.0.0-alpha." in text, (
            "forge_canvas pin must use the 1.0.0-alpha.x range"
        )


# ---------------------------------------------------------------------------
# Package-side invariants
# ---------------------------------------------------------------------------


class TestPackageClientShape:
    """The package's AgUiClient must expose the API the template depends on."""

    def test_client_is_generic_over_event_type(self) -> None:
        client = _PACKAGE_ROOT / "lib" / "src" / "ag_ui_client.dart"
        text = client.read_text(encoding="utf-8")
        assert "class AgUiClient<E>" in text, (
            "Package AgUiClient must be generic over the caller's event type"
        )

    def test_client_takes_parser_callback(self) -> None:
        client = _PACKAGE_ROOT / "lib" / "src" / "ag_ui_client.dart"
        text = client.read_text(encoding="utf-8")
        assert "required E? Function(Map<String, dynamic>) parser" in text, (
            "Package AgUiClient must accept a parser: (Map) -> E? in its constructor"
        )

    def test_client_exposes_runAgent_helper(self) -> None:
        client = _PACKAGE_ROOT / "lib" / "src" / "ag_ui_client.dart"
        text = client.read_text(encoding="utf-8")
        # The runAgent helper must mirror the deepagent /agent/run contract.
        for marker in (
            "Stream<E> runAgent",
            "required String threadId",
            "required String runId",
            "required List<Map<String, dynamic>> messages",
            "Map<String, dynamic> forwardedProps",
            "String? bearerToken",
        ):
            assert marker in text, (
                f"runAgent helper missing expected fragment: {marker!r}"
            )

    def test_library_exports_ag_ui_client(self) -> None:
        lib = _PACKAGE_ROOT / "lib" / "forge_canvas.dart"
        text = lib.read_text(encoding="utf-8")
        assert "export 'src/ag_ui_client.dart';" in text, (
            "forge_canvas library must export src/ag_ui_client.dart"
        )

    def test_package_does_not_collide_with_template_AgUiEvent(self) -> None:
        """The package must not export a top-level `AgUiEvent` type.

        The template ships its own sealed `AgUiEvent` hierarchy. If the
        package also exports a public `AgUiEvent`, the chat layer's
        `import 'package:forge_canvas/forge_canvas.dart' as fc;` aliasing
        still works, but unaliased call sites would break. Keep the
        package event-type-agnostic until codegen unifies them.
        """
        lib = _PACKAGE_ROOT / "lib" / "forge_canvas.dart"
        exported = lib.read_text(encoding="utf-8")
        # generated/events.dart defines a sealed AgUiEvent that would
        # conflict with the template's; it is intentionally not exported.
        assert "export 'src/generated/events.dart'" not in exported, (
            "src/generated/events.dart must stay private — its AgUiEvent "
            "would conflict with the template's sealed hierarchy"
        )

    def test_ag_ui_client_does_not_redeclare_AgUiEvent(self) -> None:
        client = _PACKAGE_ROOT / "lib" / "src" / "ag_ui_client.dart"
        # Strip Dart line-comments so a docstring mentioning the
        # symbol doesn't trip the check.
        stripped = "\n".join(
            line for line in client.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("//") and not line.lstrip().startswith("///")
        )
        assert "class AgUiEvent" not in stripped, (
            "Package AgUiClient is now generic — the legacy concrete AgUiEvent "
            "value class must be removed to avoid name collision"
        )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
