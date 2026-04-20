"""Tests for the three-zone merge system (2.2 of the 1.0 roadmap)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from forge.errors import GeneratorError
from forge.feature_injector import (
    _Injection,
    _apply_zoned_injection,
    _has_sentinel_block,
    _load_injections,
)


class TestLoadInjectionsZone:
    def test_zone_defaults_to_generated(self, tmp_path: Path) -> None:
        p = tmp_path / "inject.yaml"
        p.write_text(
            yaml.safe_dump(
                [{"target": "a.py", "marker": "X", "snippet": "pass"}]
            )
        )
        out = _load_injections(p, "f")
        assert out[0].zone == "generated"

    def test_explicit_zone_loaded(self, tmp_path: Path) -> None:
        p = tmp_path / "inject.yaml"
        p.write_text(
            yaml.safe_dump(
                [
                    {
                        "target": "a.py",
                        "marker": "X",
                        "snippet": "pass",
                        "zone": "user",
                    },
                    {
                        "target": "b.py",
                        "marker": "Y",
                        "snippet": "pass",
                        "zone": "merge",
                    },
                ]
            )
        )
        out = _load_injections(p, "f")
        assert out[0].zone == "user"
        assert out[1].zone == "merge"

    def test_rejects_invalid_zone(self, tmp_path: Path) -> None:
        p = tmp_path / "inject.yaml"
        p.write_text(
            yaml.safe_dump(
                [
                    {
                        "target": "a.py",
                        "marker": "X",
                        "snippet": "pass",
                        "zone": "bogus",
                    }
                ]
            )
        )
        with pytest.raises(GeneratorError, match="zone must be"):
            _load_injections(p, "f")


class TestZoneSemantics:
    def _make_target(self, tmp_path: Path) -> Path:
        p = tmp_path / "main.py"
        p.write_text(
            "def app():\n    # FORGE:X\n    return None\n", encoding="utf-8"
        )
        return p

    def test_generated_zone_always_applies(self, tmp_path: Path) -> None:
        target = self._make_target(tmp_path)
        inj1 = _Injection(
            feature_key="f",
            target="main.py",
            marker="X",
            snippet="v1",
            position="after",
            zone="generated",
        )
        assert _apply_zoned_injection(target, inj1) is True
        body = target.read_text(encoding="utf-8")
        assert "v1" in body

        inj2 = _Injection(
            feature_key="f",
            target="main.py",
            marker="X",
            snippet="v2",
            position="after",
            zone="generated",
        )
        assert _apply_zoned_injection(target, inj2) is True
        body = target.read_text(encoding="utf-8")
        assert "v2" in body
        assert "v1" not in body

    def test_user_zone_applies_first_time_then_preserved(self, tmp_path: Path) -> None:
        target = self._make_target(tmp_path)
        first = _Injection(
            feature_key="f",
            target="main.py",
            marker="X",
            snippet="original",
            position="after",
            zone="user",
        )
        # First apply: no block exists, so it's added.
        assert _apply_zoned_injection(target, first) is True
        assert "original" in target.read_text(encoding="utf-8")

        # User customizes the block. (Simulate by editing the file.)
        body = target.read_text(encoding="utf-8")
        edited = body.replace("original", "user edit")
        target.write_text(edited, encoding="utf-8")

        # Second apply with different snippet: should NOT overwrite.
        second = _Injection(
            feature_key="f",
            target="main.py",
            marker="X",
            snippet="upstream change",
            position="after",
            zone="user",
        )
        assert _apply_zoned_injection(target, second) is False
        final = target.read_text(encoding="utf-8")
        assert "user edit" in final
        assert "upstream change" not in final

    def test_merge_zone_applies_for_now(self, tmp_path: Path) -> None:
        """Phase 2.2 alpha: merge zone is accepted but behaves like generated
        until the three-way merge lands."""
        target = self._make_target(tmp_path)
        inj = _Injection(
            feature_key="f",
            target="main.py",
            marker="X",
            snippet="v1",
            position="after",
            zone="merge",
        )
        assert _apply_zoned_injection(target, inj) is True
        assert "v1" in target.read_text(encoding="utf-8")


class TestHasSentinelBlock:
    def test_detects_existing_block(self, tmp_path: Path) -> None:
        p = tmp_path / "main.py"
        p.write_text(
            "def app():\n"
            "    # FORGE:BEGIN f:X\n"
            "    pass\n"
            "    # FORGE:END f:X\n"
            "    return None\n",
            encoding="utf-8",
        )
        assert _has_sentinel_block(p, "f", "X") is True

    def test_false_when_absent(self, tmp_path: Path) -> None:
        p = tmp_path / "main.py"
        p.write_text("def app():\n    return None\n", encoding="utf-8")
        assert _has_sentinel_block(p, "f", "X") is False

    def test_false_when_file_missing(self, tmp_path: Path) -> None:
        assert _has_sentinel_block(tmp_path / "nope.py", "f", "X") is False
