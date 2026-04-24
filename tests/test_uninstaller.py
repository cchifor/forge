"""Tests for Epic F's provenance-driven uninstall."""

from __future__ import annotations

from pathlib import Path

from forge.provenance import ProvenanceCollector, sha256_of
from forge.uninstaller import (
    UninstallOutcome,
    _remove_sentinel_block,
    disabled_fragments,
    uninstall_fragment,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _collector(tmp_path: Path) -> ProvenanceCollector:
    return ProvenanceCollector(project_root=tmp_path)


# ---------------------------------------------------------------------------
# disabled_fragments — set-diff against the resolved plan
# ---------------------------------------------------------------------------


class TestDisabledFragments:
    def test_returns_names_present_before_but_not_now(self) -> None:
        prev = {
            "src/a.py": {"origin": "fragment", "fragment_name": "rate_limit", "sha256": "abc"},
            "src/b.py": {"origin": "fragment", "fragment_name": "observability", "sha256": "def"},
            "README.md": {"origin": "base-template", "sha256": "ghi"},
        }
        assert disabled_fragments(prev, current_plan_fragments={"observability"}) == {
            "rate_limit"
        }

    def test_empty_when_all_fragments_still_enabled(self) -> None:
        prev = {
            "src/a.py": {"origin": "fragment", "fragment_name": "rate_limit", "sha256": "abc"},
        }
        assert disabled_fragments(prev, {"rate_limit", "other"}) == set()

    def test_ignores_non_fragment_provenance(self) -> None:
        prev = {
            "README.md": {"origin": "base-template", "sha256": "abc"},
            "src/hand.py": {"origin": "user", "sha256": "def"},
        }
        assert disabled_fragments(prev, set()) == set()

    def test_ignores_entries_without_fragment_name(self) -> None:
        prev = {
            "src/a.py": {"origin": "fragment", "sha256": "abc"},  # missing fragment_name
        }
        assert disabled_fragments(prev, set()) == set()


# ---------------------------------------------------------------------------
# uninstall_fragment — happy paths
# ---------------------------------------------------------------------------


class TestUninstallFragmentFiles:
    def test_unchanged_file_is_deleted(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "frag.py"
        _write(f, "content\n")
        prov = {
            "src/frag.py": {
                "origin": "fragment",
                "fragment_name": "my_frag",
                "sha256": sha256_of(f),
            }
        }
        coll = _collector(tmp_path)
        out = uninstall_fragment(tmp_path, "my_frag", prov, coll)

        assert out.deleted_files == ["src/frag.py"]
        assert out.preserved_files == []
        assert not f.exists()
        # Empty parent dir pruned.
        assert not (tmp_path / "src").exists()

    def test_user_modified_file_is_preserved(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "frag.py"
        _write(f, "original\n")
        original_sha = sha256_of(f)
        _write(f, "user edited\n")  # drift from baseline
        prov = {
            "src/frag.py": {
                "origin": "fragment",
                "fragment_name": "my_frag",
                "sha256": original_sha,
            }
        }
        coll = _collector(tmp_path)
        out = uninstall_fragment(tmp_path, "my_frag", prov, coll)

        assert out.preserved_files == ["src/frag.py"]
        assert out.deleted_files == []
        assert f.read_text(encoding="utf-8") == "user edited\n"

    def test_missing_file_listed_as_missing(self, tmp_path: Path) -> None:
        prov = {
            "src/already_deleted.py": {
                "origin": "fragment",
                "fragment_name": "my_frag",
                "sha256": "whatever",
            }
        }
        coll = _collector(tmp_path)
        out = uninstall_fragment(tmp_path, "my_frag", prov, coll)

        assert out.missing_files == ["src/already_deleted.py"]

    def test_only_this_fragments_files_touched(self, tmp_path: Path) -> None:
        """Files belonging to other fragments or to the base template stay put."""
        a = tmp_path / "src" / "mine.py"
        b = tmp_path / "src" / "theirs.py"
        c = tmp_path / "README.md"
        _write(a, "mine\n")
        _write(b, "theirs\n")
        _write(c, "# readme\n")
        prov = {
            "src/mine.py": {
                "origin": "fragment",
                "fragment_name": "my_frag",
                "sha256": sha256_of(a),
            },
            "src/theirs.py": {
                "origin": "fragment",
                "fragment_name": "other_frag",
                "sha256": sha256_of(b),
            },
            "README.md": {"origin": "base-template", "sha256": sha256_of(c)},
        }
        coll = _collector(tmp_path)
        uninstall_fragment(tmp_path, "my_frag", prov, coll)

        assert not a.exists()
        assert b.exists()
        assert c.exists()

    def test_collector_records_pruned_after_uninstall(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "frag.py"
        _write(f, "content\n")
        prov = {
            "src/frag.py": {
                "origin": "fragment",
                "fragment_name": "my_frag",
                "sha256": sha256_of(f),
            }
        }
        coll = _collector(tmp_path)
        # Seed the collector as if it had been mid-update.
        from forge.provenance import ProvenanceRecord

        coll.records["src/frag.py"] = ProvenanceRecord(
            origin="fragment", sha256=sha256_of(f), fragment_name="my_frag"
        )
        uninstall_fragment(tmp_path, "my_frag", prov, coll)

        assert "src/frag.py" not in coll.records


# ---------------------------------------------------------------------------
# _remove_sentinel_block — BEGIN/END scrubber
# ---------------------------------------------------------------------------


class TestRemoveSentinelBlock:
    def test_removes_clean_block(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        _write(
            f,
            "import app\n"
            "# FORGE:BEGIN rate_limit:MIDDLEWARE_REGISTRATION\n"
            "app.use_middleware(X)\n"
            "# FORGE:END rate_limit:MIDDLEWARE_REGISTRATION\n"
            "return app\n",
        )
        result = _remove_sentinel_block(f, "rate_limit", "FORGE:MIDDLEWARE_REGISTRATION")
        assert result == "removed"
        body = f.read_text(encoding="utf-8")
        assert body == "import app\nreturn app\n"

    def test_missing_block_returns_missing(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        _write(f, "import app\nreturn app\n")
        result = _remove_sentinel_block(f, "rate_limit", "FORGE:MIDDLEWARE")
        assert result == "missing"

    def test_orphan_begin_returns_conflicted(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        # Tag = feature_key:(marker stripped of FORGE:) = "mw:INIT"
        _write(f, "# FORGE:BEGIN mw:INIT\nbody\n")  # no END
        before = f.read_text(encoding="utf-8")
        result = _remove_sentinel_block(f, "mw", "FORGE:INIT")
        assert result == "conflicted"
        # File untouched on conflict.
        assert f.read_text(encoding="utf-8") == before

    def test_duplicate_begin_returns_conflicted(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        _write(
            f,
            "# FORGE:BEGIN mw:INIT\na\n"
            "# FORGE:BEGIN mw:INIT\nb\n"
            "# FORGE:END mw:INIT\n",
        )
        assert _remove_sentinel_block(f, "mw", "FORGE:INIT") == "conflicted"

    def test_end_before_begin_returns_conflicted(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        _write(
            f,
            "# FORGE:END mw:INIT\n# FORGE:BEGIN mw:INIT\nbody\n# FORGE:END mw:INIT\n",
        )
        assert _remove_sentinel_block(f, "mw", "FORGE:INIT") == "conflicted"


# ---------------------------------------------------------------------------
# Sentinel scrub integrated with uninstall_fragment
# ---------------------------------------------------------------------------


class TestUninstallFragmentBlocks:
    def test_removed_blocks_reported(self, tmp_path: Path) -> None:
        target = tmp_path / "src" / "main.py"
        _write(
            target,
            "# FORGE:BEGIN my_frag:INIT\n"
            "setup_my_frag()\n"
            "# FORGE:END my_frag:INIT\n",
        )
        coll = _collector(tmp_path)
        out = uninstall_fragment(
            tmp_path,
            "my_frag",
            provenance_tbl={},  # no files tagged; only block removal
            collector=coll,
            removed_blocks_in_files=[("src/main.py", "my_frag", "FORGE:INIT")],
        )
        assert out.removed_blocks == [("src/main.py", "my_frag:INIT")]
        assert "FORGE:BEGIN" not in target.read_text(encoding="utf-8")

    def test_conflicted_blocks_reported(self, tmp_path: Path) -> None:
        target = tmp_path / "src" / "main.py"
        _write(target, "# FORGE:BEGIN my_frag:INIT\nbody\n")  # orphan BEGIN
        coll = _collector(tmp_path)
        out = uninstall_fragment(
            tmp_path,
            "my_frag",
            provenance_tbl={},
            collector=coll,
            removed_blocks_in_files=[("src/main.py", "my_frag", "FORGE:INIT")],
        )
        assert out.conflicted_blocks == [("src/main.py", "my_frag:INIT")]
        assert out.removed_blocks == []

    def test_missing_block_silent(self, tmp_path: Path) -> None:
        target = tmp_path / "src" / "main.py"
        _write(target, "import app\n")  # no FORGE markers at all
        coll = _collector(tmp_path)
        out = uninstall_fragment(
            tmp_path,
            "my_frag",
            provenance_tbl={},
            collector=coll,
            removed_blocks_in_files=[("src/main.py", "my_frag", "FORGE:INIT")],
        )
        assert out.removed_blocks == []
        assert out.conflicted_blocks == []


# ---------------------------------------------------------------------------
# UninstallOutcome.as_dict shape — used by update_project's summary payload
# ---------------------------------------------------------------------------


class TestUninstallOutcomeDict:
    def test_as_dict_shape(self) -> None:
        o = UninstallOutcome(
            fragment_name="rate_limit",
            deleted_files=["a.py"],
            preserved_files=["b.py"],
            missing_files=["c.py"],
            removed_blocks=[("d.py", "rate_limit:M")],
            conflicted_blocks=[("e.py", "rate_limit:M2")],
        )
        assert o.as_dict() == {
            "fragment": "rate_limit",
            "deleted": ["a.py"],
            "preserved": ["b.py"],
            "missing": ["c.py"],
            "removed_blocks": [{"file": "d.py", "tag": "rate_limit:M"}],
            "conflicted_blocks": [{"file": "e.py", "tag": "rate_limit:M2"}],
        }


# ---------------------------------------------------------------------------
# _no_uninstall_flag — forge.toml escape-hatch reader
# ---------------------------------------------------------------------------


class TestNoUninstallFlag:
    def _toml(self, tmp_path: Path, body: str) -> Path:
        f = tmp_path / "forge.toml"
        _write(f, body)
        return f

    def test_flag_absent_returns_false(self, tmp_path: Path) -> None:
        from forge.updater import _no_uninstall_flag

        manifest = self._toml(tmp_path, '[forge]\nversion = "1.0.0"\n')
        assert _no_uninstall_flag(manifest) is False

    def test_flag_true_returns_true(self, tmp_path: Path) -> None:
        from forge.updater import _no_uninstall_flag

        manifest = self._toml(
            tmp_path,
            '[forge]\nversion = "1.0.0"\n\n[forge.update]\nno_uninstall = true\n',
        )
        assert _no_uninstall_flag(manifest) is True

    def test_flag_false_returns_false(self, tmp_path: Path) -> None:
        from forge.updater import _no_uninstall_flag

        manifest = self._toml(
            tmp_path,
            '[forge]\nversion = "1.0.0"\n\n[forge.update]\nno_uninstall = false\n',
        )
        assert _no_uninstall_flag(manifest) is False

    def test_corrupt_toml_returns_false(self, tmp_path: Path) -> None:
        from forge.updater import _no_uninstall_flag

        manifest = self._toml(tmp_path, "this is not valid TOML @@@ = [")
        assert _no_uninstall_flag(manifest) is False


# ---------------------------------------------------------------------------
# MergeBlockCollector.parse_key — round-trip used by _disabled_fragment_blocks
# ---------------------------------------------------------------------------


class TestMergeBlockKeyParse:
    def test_round_trip(self) -> None:
        from forge.merge import MergeBlockCollector

        key = MergeBlockCollector.key_for(
            "src/app/main.py", "rate_limit", "FORGE:MIDDLEWARE_REGISTRATION"
        )
        parsed = MergeBlockCollector.parse_key(key)
        assert parsed == (
            "src/app/main.py",
            "rate_limit",
            "FORGE:MIDDLEWARE_REGISTRATION",
        )

    def test_malformed_returns_none(self) -> None:
        from forge.merge import MergeBlockCollector

        assert MergeBlockCollector.parse_key("no separator here") is None
        assert MergeBlockCollector.parse_key("src/a.py::no_feature_marker") is None
