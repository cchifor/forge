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
    # mcp_server moved under forge.features.platform in the
    # features-reorganization refactor. The on-disk layout is the same,
    # just rooted at forge/features/platform/templates/ instead of
    # forge/templates/_fragments/.
    path = (
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
        with patch.object(audit_module.time, "time", return_value=original_time + 7200):
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


class TestReadLastN:
    """Read-back helper backing the ``GET /mcp/audit`` endpoint."""

    @staticmethod
    def _write_entries(audit_module, count: int) -> None:
        for i in range(count):
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

    def test_returns_most_recent_first(self, audit_module, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("MCP_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
        self._write_entries(audit_module, 5)

        page = audit_module.read_last_n(3)
        assert [e["ts"] for e in page] == [4.0, 3.0, 2.0]

    def test_limit_one_returns_single_newest(self, audit_module, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("MCP_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
        self._write_entries(audit_module, 5)

        page = audit_module.read_last_n(1)
        assert len(page) == 1
        assert page[0]["ts"] == 4.0

    def test_limit_exceeds_size_returns_all(self, audit_module, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("MCP_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
        self._write_entries(audit_module, 3)

        page = audit_module.read_last_n(1000)
        assert len(page) == 3
        # Still most-recent-first.
        assert [e["ts"] for e in page] == [2.0, 1.0, 0.0]

    def test_missing_log_returns_empty(self, audit_module, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("MCP_AUDIT_LOG", str(tmp_path / "does-not-exist.jsonl"))
        assert audit_module.read_last_n(50) == []

    def test_zero_or_negative_limit_returns_empty(
        self, audit_module, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setenv("MCP_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
        self._write_entries(audit_module, 2)
        assert audit_module.read_last_n(0) == []
        assert audit_module.read_last_n(-1) == []

    def test_skips_malformed_lines(self, audit_module, tmp_path, monkeypatch, caplog) -> None:
        """Malformed JSONL (likely from a concurrent write mid-flush) is
        skipped + emits a warning. Codex Phase B round 1 follow-up:
        assert the warning fires so corruption isn't completely silent —
        ops can grep CI logs for `MCP audit: skipping malformed line`.
        """
        import logging
        log_path = tmp_path / "audit.jsonl"
        monkeypatch.setenv("MCP_AUDIT_LOG", str(log_path))
        self._write_entries(audit_module, 2)
        # Splice a corrupt line into the middle.
        with log_path.open("a", encoding="utf-8") as f:
            f.write("not-valid-json\n")
        audit_module.record_invocation(
            audit_module.AuditEntry(
                timestamp=99.0,
                user_id="u-99",
                server="fs",
                tool="read_file",
                input_hash="h99",
                decision="approved",
            )
        )

        with caplog.at_level(logging.WARNING, logger="app.mcp.audit"):
            page = audit_module.read_last_n(10)
        assert [e["ts"] for e in page] == [99.0, 1.0, 0.0]
        assert any(
            "malformed" in record.message.lower() or "skip" in record.message.lower()
            for record in caplog.records
        ), "malformed-line skip should emit a warning"

    def test_oserror_propagates_uncaught(self, audit_module, tmp_path, monkeypatch) -> None:
        """Codex Phase B round 1 follow-up: when the JSONL file can be
        located but reading it fails (e.g. permission denied), read_last_n
        propagates OSError uncaught. The router's HTTPException(500)
        wrapping is where the conversion happens — not here.
        """
        import pytest
        log_path = tmp_path / "audit.jsonl"
        monkeypatch.setenv("MCP_AUDIT_LOG", str(log_path))
        self._write_entries(audit_module, 1)
        # Replace open() with a stub that raises OSError on read.
        original_open = type(log_path).open
        def _raising_open(self, *args, **kwargs):
            raise OSError(13, "Permission denied", str(self))
        monkeypatch.setattr(type(log_path), "open", _raising_open)
        try:
            with pytest.raises(OSError, match="Permission denied"):
                audit_module.read_last_n(10)
        finally:
            monkeypatch.setattr(type(log_path), "open", original_open)

    def test_entry_shape_round_trips(self, audit_module, tmp_path, monkeypatch) -> None:
        """Every field written by record_invocation comes back out."""
        monkeypatch.setenv("MCP_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
        audit_module.record_invocation(
            audit_module.AuditEntry(
                timestamp=1700000000.0,
                user_id="user-42",
                server="fs",
                tool="read_file",
                input_hash="abc123",
                decision="approved",
                error=None,
            )
        )
        page = audit_module.read_last_n(1)
        assert page == [
            {
                "ts": 1700000000.0,
                "user_id": "user-42",
                "server": "fs",
                "tool": "read_file",
                "input_hash": "abc123",
                "decision": "approved",
                "error": None,
            }
        ]
