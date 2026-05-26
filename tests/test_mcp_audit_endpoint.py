"""Forge-side invariants for the ``GET /mcp/audit?limit=N`` endpoint
shipped with the ``mcp_server`` fragment (Pillar F.5).

The endpoint itself is exercised by ``tests/test_mcp_audit.py`` against
the template's read helper (``read_last_n``) and by the in-template
runtime tests under matrix-generate. These tests guard the *shipping*
shape so a future refactor of router.py / audit.py can't silently drop
the read-side audit endpoint that operators depend on.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY


def _mcp_server_files_root() -> Path:
    return (
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
    )


def _router_source() -> str:
    return (_mcp_server_files_root() / "router.py").read_text(encoding="utf-8")


def _audit_source() -> str:
    return (_mcp_server_files_root() / "audit.py").read_text(encoding="utf-8")


# -- File-level invariants ----------------------------------------------------


class TestEndpointDeclared:
    """Static-analysis: router.py declares the GET /audit route + helper."""

    def test_router_declares_get_audit(self) -> None:
        src = _router_source()
        assert '@router.get("/audit"' in src, "GET /mcp/audit route missing"

    def test_router_uses_limit_query_with_bounds(self) -> None:
        src = _router_source()
        # Operators expect a default of 50, a hard floor of 1, and a
        # ceiling of 1000 so the endpoint can't be weaponised to read
        # an unbounded audit log into memory.
        assert "default=50" in src
        assert "ge=1" in src
        assert "le=1000" in src

    def test_router_response_model_uses_entries_field(self) -> None:
        """Codex Phase B round 1 tightening: the response model entries
        is now `list[McpAuditEntry]` (a typed Pydantic model) rather
        than the original loose `list[dict[str, Any]]`. McpAuditEntry
        carries the JSONL field shape verbatim + `extra="allow"` so
        forward-compat additions (RFC-014 deferred fields) pass through.
        """
        src = _router_source()
        assert "class McpAuditResponse" in src
        assert "class McpAuditEntry" in src
        assert "entries: list[McpAuditEntry]" in src
        # Forward-compat: extra="allow" preserves unknown fields if the
        # write path adds tool_call_id / approval_mode / correlation_id.
        assert 'extra": "allow"' in src or "'extra': 'allow'" in src

    def test_router_returns_500_on_storage_failure(self) -> None:
        """The endpoint must surface storage errors as 500 — silent
        fallback to ``[]`` would mask a broken audit pipeline."""
        src = _router_source()
        assert "status_code=500" in src
        # And the trigger is an OSError from the read helper.
        assert "except OSError" in src

    def test_audit_module_exports_read_helper(self) -> None:
        src = _audit_source()
        assert "def read_last_n(" in src

    def test_router_imports_read_helper(self) -> None:
        src = _router_source()
        assert "read_last_n" in src


# -- Fragment-registry invariants --------------------------------------------


class TestFragmentShipsEndpoint:
    """``agent.mode=tool_calling`` pulls mcp_server; the bundle is the
    only path through which the audit endpoint reaches a generated
    project. Verify the fragment still points at the template tree we
    just edited (not a moved copy)."""

    def test_mcp_server_fragment_python_files_root_matches(self) -> None:
        frag = FRAGMENT_REGISTRY["mcp_server"]
        impl = frag.implementations[BackendLanguage.PYTHON]
        files_root = Path(impl.fragment_dir) / "files"
        assert (files_root / "src" / "app" / "mcp" / "audit.py").is_file()
        assert (files_root / "src" / "app" / "mcp" / "router.py").is_file()

    def test_shipped_router_has_audit_endpoint(self) -> None:
        """End-to-end: the file the resolver hands to the applier
        is the one with the new endpoint (not a stale copy elsewhere
        on disk)."""
        frag = FRAGMENT_REGISTRY["mcp_server"]
        impl = frag.implementations[BackendLanguage.PYTHON]
        router_path = Path(impl.fragment_dir) / "files" / "src" / "app" / "mcp" / "router.py"
        src = router_path.read_text(encoding="utf-8")
        assert '@router.get("/audit"' in src


# -- Behaviour invariant via the template's audit module ---------------------


def _load_audit_module():
    """Import the in-template ``audit.py`` directly.

    Mirrors the ``_load_audit_module`` helper in ``test_mcp_audit.py``
    so this file remains self-contained for selective pytest runs.
    """
    path = _mcp_server_files_root() / "audit.py"
    # _secret() fires at module scope and defaults to production posture.
    # Provide the signing key before import so the eager check succeeds.
    os.environ.setdefault("MCP_APPROVAL_SIGNING_KEY", "test-key-deadbeefx2")
    spec = importlib.util.spec_from_file_location("mcp_audit_endpoint_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mcp_audit_endpoint_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit_module():
    return _load_audit_module()


@pytest.fixture(autouse=True)
def _fixed_secret(monkeypatch):
    monkeypatch.setenv("MCP_APPROVAL_SIGNING_KEY", "test-key-deadbeefx2")


class TestReadHelperContract:
    """Light end-to-end check that the helper backing the endpoint
    obeys the operator-facing contract (most-recent-first ordering +
    bounded result)."""

    def test_most_recent_first_with_limit(self, audit_module, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("MCP_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
        for i in range(5):
            audit_module.record_invocation(
                audit_module.AuditEntry(
                    timestamp=float(i),
                    user_id=f"u-{i}",
                    server="fs",
                    tool="read_file",
                    input_hash=f"h{i}",
                    decision="approved",
                )
            )

        page = audit_module.read_last_n(3)
        assert [e["ts"] for e in page] == [4.0, 3.0, 2.0]
        assert all("decision" in e for e in page)

    def test_empty_log_returns_empty_list(self, audit_module, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("MCP_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
        assert audit_module.read_last_n(50) == []
