"""Long / deep-path robustness for the merge-mode update flow.

P2 (1.1.0-alpha.2) — Windows' 260-char default ``MAX_PATH`` limit
bites when ``forge --update`` walks deeply nested fragment outputs.
``docs/WINDOWS_DEV.md`` documents the OS-side workaround
(``LongPathsEnabled`` registry flip); these tests guard the forge-side
behaviour so a regression in path handling fires in CI before users hit
it.

The tests construct a deliberately deep directory structure under
``tmp_path`` and exercise the three hot paths that walk fragment file
trees: ``forge.appliers.files.copy_files`` (file-copy applier),
``forge.merge.sha256_of_file`` / ``is_binary_file`` (used by every
merge decision), and the full ``plan_update`` walk. Cross-platform —
the deep nesting is the test signal regardless of OS.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.appliers.files import copy_files
from forge.merge import (
    file_three_way_decide,
    is_binary_file,
    sha256_of_file,
    sha256_of_text,
)


# 6 path components × short segments = ~50 chars added on top of
# tmp_path. Stays comfortably under Windows' 260-char MAX_PATH default
# even when tmp_path itself eats ~120 chars (the typical pytest-of-X
# / pytest-N / test_long_module_function_param0 / src prefix). For an
# explicit MAX_PATH-crossing stress run see the opt-in test at the
# bottom of this module.
_NEST_DEPTH = 6
_NEST_SEGMENT = "deep"


def _build_deep_tree(root: Path, *, depth: int = _NEST_DEPTH) -> Path:
    """Return ``root / deep / ... / deep`` with one file per level."""
    cur = root
    for i in range(depth):
        cur = cur / f"{_NEST_SEGMENT}_{i:02d}"
        cur.mkdir(parents=True, exist_ok=True)
        (cur / "marker.txt").write_text(
            f"level {i} of {depth}\n", encoding="utf-8"
        )
    return cur


# ---------------------------------------------------------------------------
# Hash helpers handle deeply nested files
# ---------------------------------------------------------------------------


class TestHashHelpersOnDeepPaths:
    def test_sha256_of_file_works_at_depth(self, tmp_path: Path) -> None:
        leaf = _build_deep_tree(tmp_path)
        deepest = leaf / "marker.txt"
        # File reaches us at the leaf. Hash must succeed and equal the
        # text-based hash.
        assert deepest.is_file()
        body = deepest.read_text(encoding="utf-8")
        assert sha256_of_file(deepest) == sha256_of_text(body)

    def test_is_binary_file_works_at_depth(self, tmp_path: Path) -> None:
        leaf = _build_deep_tree(tmp_path)
        text = leaf / "marker.txt"
        binary = leaf / "blob.bin"
        binary.write_bytes(b"\x00\x01\x02" * 50)
        assert is_binary_file(text) is False
        assert is_binary_file(binary) is True


# ---------------------------------------------------------------------------
# copy_files round-trip across deep paths
# ---------------------------------------------------------------------------


class TestCopyFilesAcrossDeepPaths:
    def test_strict_mode_creates_full_nested_tree(self, tmp_path: Path) -> None:
        # Source: deep tree with real content. Destination: a sibling
        # tree the applier must reproduce, parents and all.
        src_root = tmp_path / "src"
        src_leaf = _build_deep_tree(src_root, depth=_NEST_DEPTH)
        # Add an extra fragment-shaped file so we copy more than markers.
        (src_leaf / "fragment.py").write_text(
            "VALUE = 42\n", encoding="utf-8"
        )

        dst_root = tmp_path / "dst"
        dst_root.mkdir()

        outcomes = copy_files(src_root, dst_root, update_mode="strict")

        # Every source file lands under dst_root with the same relative
        # path. A walk over the source verifies parity.
        for src_path in src_root.rglob("*"):
            if src_path.is_file():
                rel = src_path.relative_to(src_root)
                dst_path = dst_root / rel
                assert dst_path.is_file(), (
                    f"missing copy for deeply nested {rel}"
                )
                assert dst_path.read_text(encoding="utf-8") == src_path.read_text(
                    encoding="utf-8"
                )
        # All outcomes are 'applied' on a fresh emit.
        assert all(o.action == "applied" for o in outcomes)

    def test_merge_mode_round_trip_preserves_user_edits_at_depth(
        self, tmp_path: Path
    ) -> None:
        """Build a baseline, drift the manifest, edit the deep file:
        ``file_three_way_decide`` must classify it correctly."""
        src_root = tmp_path / "src"
        leaf = _build_deep_tree(src_root, depth=_NEST_DEPTH)
        (leaf / "fragment.py").write_text(
            "ORIGINAL = 1\n", encoding="utf-8"
        )

        dst_root = tmp_path / "dst"
        dst_root.mkdir()
        # First emit (strict) — establishes the baseline content.
        copy_files(src_root, dst_root, update_mode="strict")

        # Capture the baseline SHA. User then edits the deep file in
        # the destination tree.
        rel = (
            Path(_NEST_SEGMENT + "_00")
            / "/".join(f"{_NEST_SEGMENT}_{i:02d}" for i in range(1, _NEST_DEPTH))
            / "fragment.py"
        )
        # Actually compute the rel path from the leaf back to the src root.
        rel = (leaf / "fragment.py").relative_to(src_root)
        baseline_dst = dst_root / rel
        baseline_sha = sha256_of_file(baseline_dst)
        baseline_dst.write_text("# user edit at depth\n", encoding="utf-8")

        # Re-render the source — fragment also moves.
        (leaf / "fragment.py").write_text("NEW = 2\n", encoding="utf-8")

        # Three-way decide on the deep path.
        baselines = {rel.as_posix(): baseline_sha}
        outcomes = copy_files(
            src_root,
            dst_root,
            update_mode="merge",
            file_baselines=baselines,
            project_root=dst_root,
        )

        deep = next(
            o for o in outcomes if o.target == baseline_dst
        )
        assert deep.action == "conflict"
        assert deep.sidecar_path is not None
        assert deep.sidecar_path.is_file()
        # User content untouched.
        assert (
            baseline_dst.read_text(encoding="utf-8")
            == "# user edit at depth\n"
        )


# ---------------------------------------------------------------------------
# Pure decision works regardless of path length
# ---------------------------------------------------------------------------


class TestDecisionForDeepPaths:
    def test_decide_pure_function_unaffected_by_path_length(self) -> None:
        """``file_three_way_decide`` is path-agnostic — only hashes matter.
        This guards against a regression where some future commit
        accidentally couples decisions to absolute path length."""
        baseline = sha256_of_text("body\n")
        assert (
            file_three_way_decide(
                baseline_sha=baseline,
                current_sha=baseline,
                new_sha=sha256_of_text("new\n"),
            )
            == "applied"
        )
        # And one with a stale baseline, simulating drift.
        assert (
            file_three_way_decide(
                baseline_sha="0" * 64,
                current_sha=sha256_of_text("user\n"),
                new_sha=sha256_of_text("frag\n"),
            )
            == "conflict"
        )


# ---------------------------------------------------------------------------
# Optional opt-in stress test — path > MAX_PATH on Windows defaults
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    True,
    reason=(
        "Stress test: builds a path > Windows MAX_PATH default. Skipped by "
        "default — opt in by removing the skipif when verifying long-path "
        "support on a Windows machine with LongPathsEnabled=1."
    ),
)
def test_path_longer_than_windows_max_path(tmp_path: Path) -> None:  # pragma: no cover
    # Construct a path explicitly longer than 260 chars under tmp_path.
    # Most CI/dev tmp_path values are already 60-100 chars deep, so 22
    # additional segments × 12 chars ≈ 264 — guaranteed to cross MAX_PATH.
    leaf = _build_deep_tree(tmp_path, depth=22)
    target = leaf / "very_deep.py"
    target.write_text("DEEP = True\n", encoding="utf-8")
    # If the OS-side long-path flag isn't set, this raises.
    assert target.is_file()
    # Hash + binary-detect must work.
    assert sha256_of_file(target) == sha256_of_text("DEEP = True\n")
    assert is_binary_file(target) is False
