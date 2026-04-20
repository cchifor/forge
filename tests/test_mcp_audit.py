"""Tests for the MCP approval-token + audit-log middleware (A4-6).

Loaded from the template path so the tests validate what forge ships
to generated projects.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_audit_module():
    path = (
        Path(__file__).resolve().parent.parent
        / "forge"
        / "templates"
        / "_fragments"
        / "mcp_server"
        / "python"
        / "files"
        / "src"
        / "app"
        / "mcp"
        / "audit.py"
    )
    spec = importlib.util.spec_from_file_location("mcp_audit_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mcp_audit_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit_module():
    return _load_audit_module()


@pytest.fixture(autouse=True)
def _fixed_secret(monkeypatch):
    monkeypatch.setenv("MCP_APPROVAL_SIGNING_KEY", "test-key-deadbeefx2")


class TestHashInput:
    def test_deterministic(self, audit_module) -> None:
        a = audit_module.hash_input({"a": 1, "b": [2, 3]})
        b = audit_module.hash_input({"b": [2, 3], "a": 1})  # key order flipped
        assert a == b

    def test_different_content(self, audit_module) -> None:
        a = audit_module.hash_input({"x": 1})
        b = audit_module.hash_input({"x": 2})
        assert a != b


class TestMintAndVerify:
    def test_roundtrip(self, audit_module) -> None:
        token = audit_module.mint_approval_token(
            server="fs",
            tool="read_file",
            input_payload={"path": "/tmp/a.txt"},
        )
        assert audit_module.verify_approval_token(
            token,
            server="fs",
            tool="read_file",
            input_payload={"path": "/tmp/a.txt"},
        )

    def test_rejects_different_input(self, audit_module) -> None:
        token = audit_module.mint_approval_token(
            server="fs", tool="read_file", input_payload={"path": "/tmp/a.txt"}
        )
        assert not audit_module.verify_approval_token(
            token,
            server="fs",
            tool="read_file",
            input_payload={"path": "/tmp/different.txt"},
        )

    def test_rejects_different_tool(self, audit_module) -> None:
        token = audit_module.mint_approval_token(
            server="fs", tool="read_file", input_payload={"path": "/tmp/a.txt"}
        )
        assert not audit_module.verify_approval_token(
            token,
            server="fs",
            tool="write_file",  # different tool
            input_payload={"path": "/tmp/a.txt"},
        )

    def test_rejects_expired(self, audit_module) -> None:
        # Mint, then verify with a max_age smaller than "now" can support.
        token = audit_module.mint_approval_token(
            server="fs", tool="read_file", input_payload={"path": "/tmp/a.txt"}
        )
        # Travel forward via mocked time.
        import time

        original_time = time.time()
        with patch.object(
            audit_module.time, "time", return_value=original_time + 7200
        ):
            assert not audit_module.verify_approval_token(
                token,
                server="fs",
                tool="read_file",
                input_payload={"path": "/tmp/a.txt"},
                max_age_seconds=3600,
            )

    def test_rejects_tampered_signature(self, audit_module) -> None:
        token = audit_module.mint_approval_token(
            server="fs", tool="read_file", input_payload={"path": "/tmp/a.txt"}
        )
        # Flip one character in the signature tail.
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
        assert not audit_module.verify_approval_token(
            tampered,
            server="fs",
            tool="read_file",
            input_payload={"path": "/tmp/a.txt"},
        )

    def test_rejects_malformed(self, audit_module) -> None:
        assert not audit_module.verify_approval_token(
            "not-a-token",
            server="fs",
            tool="read_file",
            input_payload={},
        )


class TestRecordInvocation:
    def test_writes_jsonl_line(self, audit_module, tmp_path, monkeypatch) -> None:
        import json

        log_path = tmp_path / "audit.jsonl"
        monkeypatch.setenv("MCP_AUDIT_LOG", str(log_path))

        entry = audit_module.AuditEntry(
            timestamp=1700000000.0,
            user_id="user-42",
            server="fs",
            tool="read_file",
            input_hash="abc123",
            decision="approved",
        )
        audit_module.record_invocation(entry)

        body = log_path.read_text(encoding="utf-8").strip()
        parsed = json.loads(body)
        assert parsed["user_id"] == "user-42"
        assert parsed["server"] == "fs"
        assert parsed["decision"] == "approved"

    def test_append_mode(self, audit_module, tmp_path, monkeypatch) -> None:
        log_path = tmp_path / "audit.jsonl"
        monkeypatch.setenv("MCP_AUDIT_LOG", str(log_path))

        for i in range(3):
            audit_module.record_invocation(
                audit_module.AuditEntry(
                    timestamp=float(i),
                    user_id="u",
                    server="s",
                    tool="t",
                    input_hash="h",
                    decision="auto",
                )
            )
        assert len(log_path.read_text(encoding="utf-8").strip().splitlines()) == 3
