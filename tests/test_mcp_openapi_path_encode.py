"""Path-parameter percent-encoding for the vendored OpenAPI→MCP generator.

``_render_path`` substitutes ``{param}`` placeholders from the MCP call args
into an OpenAPI path template. A path-parameter *value* that contains URL
structural characters (``/``, ``?``, ``#``, space) must be percent-encoded —
otherwise a value like ``"a/b"`` injects an extra path segment and corrupts the
request URL / upstream routing.

Loaded from the template path (with the vendored ``app.mcp._template.errors`` /
``...plugin`` deps stubbed) so the test validates exactly what forge ships to
generated projects — mirroring ``tests/test_gatekeeper_apikeys.py``.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_OPENAPI_PATH = (
    Path(__file__).resolve().parent.parent
    / "forge"
    / "features"
    / "mcp_template"
    / "templates"
    / "mcp_template_server"
    / "python"
    / "files"
    / "src"
    / "app"
    / "mcp"
    / "_template"
    / "openapi.py"
)


def _load_openapi_module() -> types.ModuleType:
    """Import the template ``openapi.py`` with its sibling vendored modules stubbed.

    ``openapi.py`` only pulls ``UpstreamError`` (from ``...errors``) and
    ``PluginContext`` / ``ToolDef`` (from ``...plugin``) out of its package,
    plus stdlib + httpx + PyYAML. Tiny stand-ins for the two siblings are
    enough to exec the module and reach ``_render_path``.
    """
    errors_mod = types.ModuleType("app.mcp._template.errors")

    class _UpstreamError(Exception):
        def __init__(self, message: str, *, status_code: int | None = None) -> None:
            super().__init__(message)
            self.status_code = status_code

    errors_mod.UpstreamError = _UpstreamError  # type: ignore[attr-defined]

    plugin_mod = types.ModuleType("app.mcp._template.plugin")
    plugin_mod.PluginContext = object  # type: ignore[attr-defined]
    plugin_mod.ToolDef = object  # type: ignore[attr-defined]

    for name in ("app", "app.mcp", "app.mcp._template"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["app.mcp._template.errors"] = errors_mod
    sys.modules["app.mcp._template.plugin"] = plugin_mod

    spec = importlib.util.spec_from_file_location("mcp_openapi_under_test", _OPENAPI_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mcp_openapi_under_test"] = module
    spec.loader.exec_module(module)
    return module


class TestRenderPathEncoding:
    def test_slash_in_value_is_percent_encoded(self) -> None:
        """A path-param value containing ``/`` must not inject an extra segment."""
        module = _load_openapi_module()
        out = module._render_path("/users/{id}/posts", {"id": "a/b"})
        assert out == "/users/a%2Fb/posts", (
            "path-param value with a slash must be percent-encoded, not injected "
            f"as a new path segment (got {out!r})"
        )

    def test_query_and_fragment_chars_are_encoded(self) -> None:
        module = _load_openapi_module()
        out = module._render_path("/t/{id}", {"id": "x?y#z"})
        assert out == "/t/x%3Fy%23z", (
            f"'?' and '#' in a path value must be percent-encoded (got {out!r})"
        )

    def test_space_is_encoded(self) -> None:
        module = _load_openapi_module()
        out = module._render_path("/t/{id}", {"id": "a b"})
        assert out == "/t/a%20b", f"space must be percent-encoded (got {out!r})"

    def test_safe_value_unchanged_and_arg_consumed(self) -> None:
        module = _load_openapi_module()
        args = {"id": "abc", "q": "keep"}
        out = module._render_path("/t/{id}", args)
        assert out == "/t/abc"
        # consumed path params are popped; non-path args remain for the querystring
        assert args == {"q": "keep"}
