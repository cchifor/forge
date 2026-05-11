"""Invariants for ``forge.features.mcp_template`` — first-party MCP host."""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY
from forge.options import OPTION_REGISTRY


def test_mcp_template_options_registered() -> None:
    assert "mcp_template.server" in OPTION_REGISTRY
    assert "mcp_template.openapi_to_tools" in OPTION_REGISTRY
    server = OPTION_REGISTRY["mcp_template.server"]
    assert server.default is False
    assert server.stability == "beta"
    assert server.enables[True] == ("mcp_template_server",)
    tools = OPTION_REGISTRY["mcp_template.openapi_to_tools"]
    assert tools.default is False
    assert tools.stability == "experimental"
    assert tools.enables[True] == ("mcp_template_openapi_tools",)


def test_mcp_template_does_not_collide_with_platform_mcp() -> None:
    """The existing ``platform.mcp`` option (consumer side — tool
    registry + approval UI) coexists with ``mcp_template.*`` (host
    side — first-party integration server)."""
    assert "platform.mcp" in OPTION_REGISTRY
    # And the existing mcp_server fragment from forge.features.platform
    # stays distinct from the new mcp_template_server fragment.
    assert "mcp_server" in FRAGMENT_REGISTRY
    assert "mcp_template_server" in FRAGMENT_REGISTRY
    assert (
        FRAGMENT_REGISTRY["mcp_server"].implementations
        is not FRAGMENT_REGISTRY["mcp_template_server"].implementations
    )


def test_mcp_template_server_fragment_declares_weld_mcp_template() -> None:
    frag = FRAGMENT_REGISTRY["mcp_template_server"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    assert "weld-mcp-template" in impl.dependencies
    assert any(d.startswith("mcp>=") for d in impl.dependencies)
    assert frag.parity_tier == 3


def test_mcp_template_openapi_tools_depends_on_server() -> None:
    frag = FRAGMENT_REGISTRY["mcp_template_openapi_tools"]
    assert frag.depends_on == ("mcp_template_server",)
    impl = frag.implementations[BackendLanguage.PYTHON]
    # The [openapi] extra pulls in PyYAML + openapi schema parser.
    assert any("weld-mcp-template[openapi]" in d for d in impl.dependencies)


def test_mcp_template_server_files_present() -> None:
    frag = FRAGMENT_REGISTRY["mcp_template_server"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    files_root = Path(impl.fragment_dir) / "files"
    assert (files_root / "src" / "app" / "mcp" / "__init__.py").is_file()
    assert (files_root / "src" / "app" / "mcp" / "server.py").is_file()
    plugins = files_root / "src" / "app" / "mcp" / "plugins"
    assert (plugins / "__init__.py").is_file()
    assert (plugins / "ping.py").is_file()


def test_mcp_template_server_inject_mounts_on_main_app() -> None:
    frag = FRAGMENT_REGISTRY["mcp_template_server"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    inject = Path(impl.fragment_dir) / "inject.yaml"
    text = inject.read_text(encoding="utf-8")
    assert "src/app/main.py" in text
    assert 'app.mount("/mcp"' in text
