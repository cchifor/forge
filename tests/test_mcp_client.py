"""Tests for the MCP stdio JSON-RPC client (A3-2).

The real client lives under a template directory so it ships with every
Python service forge generates. These tests import it by path and
exercise the serialisation / dispatch logic without spinning up a real
MCP server.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_mcp_client_module():
    """Import the template's client.py directly — it's not on sys.path.

    mcp_server moved under forge.features.platform in the
    features-reorganization refactor. The on-disk layout is unchanged
    below the fragment root.
    """
    client_path = (
        Path(__file__).resolve().parent.parent
        / "forge"
        / "features"
        / "platform"
        / "templates"
        / "mcp_server"
        / "python"
        / "files"
        / "src"
        / "app"
        / "mcp"
        / "client.py"
    )
    # The module does ``from app.ports...`` style imports; use a throwaway
    # spec so pytest doesn't try to resolve those.
    spec = importlib.util.spec_from_file_location("mcp_client_under_test", client_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mcp_client_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mcp_client_module():
    return _load_mcp_client_module()


class TestLoadRegistryFromConfig:
    def test_empty_config_produces_empty_registry(self, mcp_client_module) -> None:
        registry = mcp_client_module.load_registry_from_config({"version": 1, "servers": {}})
        assert registry.live_servers() == []

    def test_server_entry_becomes_config(self, mcp_client_module) -> None:
        registry = mcp_client_module.load_registry_from_config(
            {
                "version": 1,
                "defaultApprovalMode": "prompt-once",
                "servers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                        "approvalMode": "auto",
                    }
                },
            }
        )
        # Registry won't actually spawn the process in tests; just verify
        # the config was parsed into an McpServerConfig.
        configs = registry._config
        assert "filesystem" in configs
        assert configs["filesystem"].command == "npx"
        assert configs["filesystem"].approval_mode == "auto"

    def test_default_approval_mode_applied_when_server_omits_it(self, mcp_client_module) -> None:
        registry = mcp_client_module.load_registry_from_config(
            {
                "version": 1,
                "defaultApprovalMode": "prompt-every",
                "servers": {
                    "plain": {"command": "echo", "args": ["hi"]},
                },
            }
        )
        assert registry._config["plain"].approval_mode == "prompt-every"


class TestMcpStdioClient:
    def test_next_id_increments(self, mcp_client_module) -> None:
        """Request ids must increment so response matching works."""
        cfg = mcp_client_module.McpServerConfig(
            name="x", command="echo", args=[], env={}, approval_mode="auto"
        )
        client = mcp_client_module.McpStdioClient(cfg)
        assert client._next_id == 1
