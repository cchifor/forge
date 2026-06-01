"""Invariants for ``forge.features.mcp_template`` — first-party MCP host."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.capability_resolver import resolve
from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.errors import OptionsError
from forge.fragments import FRAGMENT_REGISTRY
from forge.options import OPTION_REGISTRY


def _py_mcp_project(options: dict[str, object]) -> ProjectConfig:
    return ProjectConfig(
        project_name="P",
        backends=[
            BackendConfig(
                name="api", project_name="P", language=BackendLanguage.PYTHON, server_port=5000
            )
        ],
        frontend=None,
        options=options,
    )


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
    # ping.py.jinja — the plugin slug interpolates ``{{ project_slug }}``.
    assert (plugins / "ping.py.jinja").is_file()


def test_mcp_template_server_inject_mounts_on_main_app() -> None:
    frag = FRAGMENT_REGISTRY["mcp_template_server"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    inject = Path(impl.fragment_dir) / "inject.yaml"
    text = inject.read_text(encoding="utf-8")
    assert "src/app/main.py" in text
    assert 'app.mount("/mcp"' in text


def test_mcp_with_auth_none_is_rejected() -> None:
    """The MCP server exposes tool invocation; auth.mode=none + mcp must error."""
    with pytest.raises(OptionsError):
        resolve(_py_mcp_project({"platform.mcp": True, "auth.mode": "none"}))


def test_mcp_with_auth_generate_is_allowed() -> None:
    resolve(_py_mcp_project({"platform.mcp": True, "auth.mode": "generate"}))


def test_auth_none_without_mcp_is_allowed() -> None:
    resolve(_py_mcp_project({"auth.mode": "none"}))


def test_mcp_router_requires_authentication() -> None:
    """Regression guard for the unauthenticated-MCP vuln. Every /mcp route must
    be gated: the server exposes tool invocation (subprocess exec), approval-
    token minting, and an audit log of user identities. Verified behaviourally
    (auth on + no token -> 401) via the real weld SDK; this locks the gate into
    the template so it cannot silently regress. NOTE: oauth2_scheme is
    auto_error=False and does NOT gate — get_current_user (raises 401) is the
    enforcing dependency."""
    router = (
        Path(__file__).resolve().parent.parent
        / "forge/features/platform/templates/mcp_server/python/files/src/app/mcp/router.py"
    )
    src = router.read_text(encoding="utf-8")
    assert "from weld.fastapi.security.auth import get_current_user" in src
    assert "dependencies=[Depends(get_current_user)]" in src


def test_mcp_via_agent_tool_calling_with_auth_none_is_rejected() -> None:
    """agent.mode=tool_calling ALSO enables mcp_server — it must require auth
    too (the guard checks the resolved fragment set, not just platform.mcp)."""
    with pytest.raises(OptionsError):
        resolve(_py_mcp_project({"agent.mode": "tool_calling", "auth.mode": "none"}))


def test_mcp_via_agent_tool_calling_with_auth_generate_is_allowed() -> None:
    resolve(_py_mcp_project({"agent.mode": "tool_calling", "auth.mode": "generate"}))


_MCP_ROUTER = (
    Path(__file__).resolve().parent.parent
    / "forge/features/platform/templates/mcp_server/python/files/src/app/mcp/router.py"
)


def test_mcp_invoke_attributes_to_verified_user_not_header() -> None:
    """invoke_tool must take the audit user_id from the verified token, not the
    spoofable x-gatekeeper-user-id header."""
    src = _MCP_ROUTER.read_text(encoding="utf-8")
    assert "str(user.id) if user is not None else None" in src
    assert 'user_id = request.headers.get("x-gatekeeper-user-id")' not in src


def test_mcp_audit_entry_matches_on_disk_shape() -> None:
    """McpAuditEntry must mirror the on-disk JSONL (ts float, user_id nullable)
    or GET /mcp/audit 500s on real entries."""
    src = _MCP_ROUTER.read_text(encoding="utf-8")
    assert "ts: float" in src
    assert "user_id: str | None = None" in src
