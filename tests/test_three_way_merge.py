"""Tests for three-way merge runtime (A3-1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.feature_injector import _Injection, _apply_zoned_injection
from forge.forge_toml import read_forge_toml, write_forge_toml
from forge.merge import (
    MergeBlockCollector,
    sha256_of_text,
    three_way_decide,
    write_sidecar,
)
from forge.provenance import ProvenanceCollector


class TestThreeWayDecide:
    def test_applied_when_current_matches_baseline(self) -> None:
        # User didn't touch the block; overwrite with new snippet.
        baseline = "old body\n"
        baseline_sha = sha256_of_text(baseline)
        assert three_way_decide(
            baseline_sha=baseline_sha,
            current_body=baseline,
            new_body="new body\n",
        ) == "applied"

    def test_skipped_no_change_when_new_equals_baseline(self) -> None:
        # Fragment snippet unchanged; user may have edited the block.
        baseline = "body\n"
        baseline_sha = sha256_of_text(baseline)
        assert three_way_decide(
            baseline_sha=baseline_sha,
            current_body="user edited\n",
            new_body=baseline,
        ) == "skipped-no-change"

    def test_skipped_idempotent_when_current_equals_new(self) -> None:
        assert three_way_decide(
            baseline_sha=sha256_of_text("other\n"),
            current_body="same\n",
            new_body="same\n",
        ) == "skipped-idempotent"

    def test_conflict_when_everything_differs(self) -> None:
        assert three_way_decide(
            baseline_sha=sha256_of_text("old\n"),
            current_body="user edit\n",
            new_body="fragment edit\n",
        ) == "conflict"

    def test_no_baseline_returns_sentinel(self) -> None:
        assert three_way_decide(
            baseline_sha=None,
            current_body="current\n",
            new_body="new\n",
        ) == "no-baseline"


class TestSidecar:
    def test_sidecar_contains_new_block(self, tmp_path: Path) -> None:
        target = tmp_path / "main.py"
        target.write_text("x = 1\n", encoding="utf-8")
        sidecar = write_sidecar(target, "fragment edit\n", "f:X")
        body = sidecar.read_text(encoding="utf-8")
        assert "fragment edit" in body
        assert "f:X" in body
        assert sidecar.name == "main.py.forge-merge"


class TestForgeTomlMergeBlocks:
    def test_merge_blocks_roundtrip(self, tmp_path: Path) -> None:
        manifest = tmp_path / "forge.toml"
        write_forge_toml(
            manifest,
            version="1.0.0a3.dev0",
            project_name="demo",
            templates={"python": "services/python-service-template"},
            options={},
            merge_blocks={
                "src/app/main.py::rate_limit:MIDDLEWARE": {"sha256": "abc123"},
            },
        )
        data = read_forge_toml(manifest)
        key = "src/app/main.py::rate_limit:MIDDLEWARE"
        assert key in data.merge_blocks
        assert data.merge_blocks[key]["sha256"] == "abc123"

    def test_empty_merge_blocks_not_serialized(self, tmp_path: Path) -> None:
        manifest = tmp_path / "forge.toml"
        write_forge_toml(
            manifest,
            version="1.0.0a3.dev0",
            project_name="demo",
            templates={"python": "services/python-service-template"},
            options={},
            merge_blocks=None,
        )
        body = manifest.read_text(encoding="utf-8")
        assert "[forge.merge_blocks" not in body


class TestApplyMergeZoneE2E:
    def _make_target(self, tmp_path: Path) -> Path:
        target = tmp_path / "main.py"
        target.write_text(
            "def app():\n    # FORGE:X\n    return None\n", encoding="utf-8"
        )
        return target

    def test_first_apply_records_baseline(self, tmp_path: Path) -> None:
        target = self._make_target(tmp_path)
        collector = ProvenanceCollector(project_root=tmp_path)
        inj = _Injection(
            feature_key="f",
            target="main.py",
            marker="X",
            snippet="import v1\n",
            position="after",
            zone="merge",
        )
        assert _apply_zoned_injection(
            target, inj, project_root=tmp_path, collector=collector
        ) is True
        key = MergeBlockCollector.key_for("main.py", "f", "X")
        assert key in collector.merge_blocks

    def test_reapply_unchanged_user_updates_block(self, tmp_path: Path) -> None:
        """User didn't touch the block — safe overwrite with new snippet."""
        target = self._make_target(tmp_path)
        collector = ProvenanceCollector(project_root=tmp_path)

        inj1 = _Injection(
            feature_key="f", target="main.py", marker="X",
            snippet="import v1", position="after", zone="merge",
        )
        _apply_zoned_injection(target, inj1, project_root=tmp_path, collector=collector)

        # Persist baseline via forge.toml.
        write_forge_toml(
            tmp_path / "forge.toml",
            version="1.0.0a3.dev0",
            project_name="demo",
            templates={"python": "services/python-service-template"},
            options={},
            merge_blocks=collector.merge_blocks_as_dict(),
        )

        # Re-apply with a new snippet; user didn't touch the block.
        collector2 = ProvenanceCollector(project_root=tmp_path)
        inj2 = _Injection(
            feature_key="f", target="main.py", marker="X",
            snippet="import v2", position="after", zone="merge",
        )
        applied = _apply_zoned_injection(
            target, inj2, project_root=tmp_path, collector=collector2
        )
        assert applied is True
        assert "import v2" in target.read_text(encoding="utf-8")
        assert "import v1" not in target.read_text(encoding="utf-8")

    def test_conflict_emits_sidecar(self, tmp_path: Path) -> None:
        """User edited the block AND fragment snippet changed — conflict."""
        target = self._make_target(tmp_path)
        collector = ProvenanceCollector(project_root=tmp_path)

        inj1 = _Injection(
            feature_key="f", target="main.py", marker="X",
            snippet="import baseline", position="after", zone="merge",
        )
        _apply_zoned_injection(target, inj1, project_root=tmp_path, collector=collector)
        write_forge_toml(
            tmp_path / "forge.toml",
            version="1.0.0a3.dev0",
            project_name="demo",
            templates={"python": "services/python-service-template"},
            options={},
            merge_blocks=collector.merge_blocks_as_dict(),
        )

        # User edits the block.
        body = target.read_text(encoding="utf-8")
        body = body.replace("import baseline", "user edit import")
        target.write_text(body, encoding="utf-8")

        # Fragment wants a different snippet.
        collector2 = ProvenanceCollector(project_root=tmp_path)
        inj2 = _Injection(
            feature_key="f", target="main.py", marker="X",
            snippet="fragment new import", position="after", zone="merge",
        )
        applied = _apply_zoned_injection(
            target, inj2, project_root=tmp_path, collector=collector2
        )
        # Conflict → target untouched, sidecar emitted.
        assert applied is False
        assert "user edit import" in target.read_text(encoding="utf-8")
        sidecar = target.with_suffix(".py.forge-merge")
        assert sidecar.is_file()
        assert "fragment new import" in sidecar.read_text(encoding="utf-8")

    def test_skipped_no_change_when_fragment_unchanged(self, tmp_path: Path) -> None:
        """User edited the block; fragment snippet hasn't changed — keep user's edit."""
        target = self._make_target(tmp_path)
        collector = ProvenanceCollector(project_root=tmp_path)
        inj1 = _Injection(
            feature_key="f", target="main.py", marker="X",
            snippet="baseline", position="after", zone="merge",
        )
        _apply_zoned_injection(target, inj1, project_root=tmp_path, collector=collector)
        write_forge_toml(
            tmp_path / "forge.toml",
            version="1.0.0a3.dev0",
            project_name="demo",
            templates={"python": "services/python-service-template"},
            options={},
            merge_blocks=collector.merge_blocks_as_dict(),
        )

        # User edits the block.
        body = target.read_text(encoding="utf-8")
        body = body.replace("baseline", "my custom impl")
        target.write_text(body, encoding="utf-8")

        # Fragment snippet is unchanged.
        inj2 = _Injection(
            feature_key="f", target="main.py", marker="X",
            snippet="baseline", position="after", zone="merge",
        )
        collector2 = ProvenanceCollector(project_root=tmp_path)
        applied = _apply_zoned_injection(
            target, inj2, project_root=tmp_path, collector=collector2
        )
        # No conflict, no change — the user's custom impl is preserved.
        assert applied is False
        assert "my custom impl" in target.read_text(encoding="utf-8")
