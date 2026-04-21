"""Tests for Epic H's ``.forge/lock`` + sentinel-audit machinery."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from forge.errors import (
    INJECTION_SENTINEL_CORRUPT,
    PROVENANCE_UPDATE_LOCK_HELD,
    InjectionError,
    ProvenanceError,
)
from forge.sentinel_audit import (
    SentinelIssue,
    audit_file,
    audit_targets,
    raise_if_corrupt,
)
from forge.updater_lock import _is_alive, _lock_path, acquire_lock

# ---------------------------------------------------------------------------
# Lock acquisition + release
# ---------------------------------------------------------------------------


class TestAcquireLock:
    def test_creates_lock_file_during_block(self, tmp_path: Path) -> None:
        with acquire_lock(tmp_path):
            lock = _lock_path(tmp_path)
            assert lock.is_file()
            data = json.loads(lock.read_text(encoding="utf-8"))
            assert data["pid"] == os.getpid()
            assert data["started"].endswith("Z")

    def test_removes_lock_file_on_clean_exit(self, tmp_path: Path) -> None:
        with acquire_lock(tmp_path):
            pass
        assert not _lock_path(tmp_path).exists()

    def test_removes_lock_file_on_exception(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError), acquire_lock(tmp_path):
            raise RuntimeError("fake failure inside the block")
        assert not _lock_path(tmp_path).exists()

    def test_reclaims_stale_lock(self, tmp_path: Path) -> None:
        """A lock file owned by a non-existent PID is reclaimable."""
        lock_dir = tmp_path / ".forge"
        lock_dir.mkdir()
        # PID 0 never exists on POSIX or Windows → always stale.
        (lock_dir / "lock").write_text(
            json.dumps({"pid": 0, "started": "2020-01-01T00:00:00Z"}),
            encoding="utf-8",
        )
        # Should not raise.
        with acquire_lock(tmp_path):
            pass

    def test_raises_when_live_pid_owns_lock(self, tmp_path: Path) -> None:
        """Another live process's lock is not reclaimable."""
        lock_dir = tmp_path / ".forge"
        lock_dir.mkdir()
        (lock_dir / "lock").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),  # this interpreter — definitely alive
                    "started": "2024-01-01T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ProvenanceError) as excinfo, acquire_lock(tmp_path):
            pass
        assert excinfo.value.code == PROVENANCE_UPDATE_LOCK_HELD
        assert excinfo.value.context["holder_pid"] == os.getpid()

    def test_no_lock_escape_hatch(self, tmp_path: Path) -> None:
        """`no_lock=True` skips the lock file entirely."""
        with acquire_lock(tmp_path, no_lock=True):
            assert not _lock_path(tmp_path).exists()
        # Still nothing after exit.
        assert not _lock_path(tmp_path).exists()

    def test_pid_0_is_not_alive(self) -> None:
        assert not _is_alive(0)

    def test_current_pid_is_alive(self) -> None:
        assert _is_alive(os.getpid())

    def test_corrupt_lock_file_is_treated_as_missing(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / ".forge"
        lock_dir.mkdir()
        (lock_dir / "lock").write_text("this is not JSON", encoding="utf-8")
        # Should acquire cleanly — garbled lock → treat as stale.
        with acquire_lock(tmp_path):
            assert _lock_path(tmp_path).is_file()


# ---------------------------------------------------------------------------
# sentinel_audit — per-file structural checks
# ---------------------------------------------------------------------------


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


class TestSentinelAuditFile:
    def test_clean_pair_has_no_issues(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        _write(
            f,
            "# FORGE:BEGIN rate_limit:MIDDLEWARE_IMPORTS\n"
            "from x import y\n"
            "# FORGE:END rate_limit:MIDDLEWARE_IMPORTS\n",
        )
        assert audit_file(f) == []

    def test_orphan_begin(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        _write(f, "# FORGE:BEGIN rate_limit:M\nfoo()\n")
        issues = audit_file(f)
        assert len(issues) == 1
        assert issues[0].kind == "orphan-begin"
        assert issues[0].tag == "rate_limit:M"
        assert issues[0].line == 1

    def test_end_before_begin(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        _write(f, "# FORGE:END rate_limit:M\nfoo()\n")
        issues = audit_file(f)
        assert any(i.kind == "end-before-begin" for i in issues)

    def test_duplicate_begin(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        _write(
            f,
            "# FORGE:BEGIN rate_limit:M\n"
            "body1\n"
            "# FORGE:END rate_limit:M\n"
            "# FORGE:BEGIN rate_limit:M\n"
            "body2\n"
            "# FORGE:END rate_limit:M\n",
        )
        issues = audit_file(f)
        assert any(i.kind == "duplicate-begin" for i in issues)
        assert any(i.kind == "duplicate-end" for i in issues)

    def test_nested_pair(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        _write(
            f,
            "# FORGE:BEGIN outer:X\n"
            "# FORGE:BEGIN inner:Y\n"
            "# FORGE:END inner:Y\n"
            "# FORGE:END outer:X\n",
        )
        issues = audit_file(f)
        assert any(i.kind == "nested-pair" for i in issues)

    def test_nonexistent_file_is_no_op(self, tmp_path: Path) -> None:
        assert audit_file(tmp_path / "missing.py") == []


# ---------------------------------------------------------------------------
# audit_targets + raise_if_corrupt
# ---------------------------------------------------------------------------


class TestAuditTargetsAndRaise:
    def test_audit_targets_aggregates_across_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        _write(f1, "# FORGE:BEGIN tag1\n")  # orphan-begin
        _write(f2, "# FORGE:END tag2\n")  # end-before-begin
        issues = audit_targets([f1, f2])
        kinds = {i.kind for i in issues}
        assert kinds == {"orphan-begin", "end-before-begin"}

    def test_raise_if_corrupt_no_issues_is_noop(self) -> None:
        raise_if_corrupt([])  # shouldn't raise

    def test_raise_if_corrupt_raises_injection_error(self, tmp_path: Path) -> None:
        issues = [
            SentinelIssue(file=tmp_path / "x.py", kind="orphan-begin", tag="t", line=1)
        ]
        with pytest.raises(InjectionError) as excinfo:
            raise_if_corrupt(issues)
        assert excinfo.value.code == INJECTION_SENTINEL_CORRUPT
        assert excinfo.value.context["issues"][0]["tag"] == "t"
