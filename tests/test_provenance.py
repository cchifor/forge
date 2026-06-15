"""Tests for the provenance manifest (0.2 of the 1.0 roadmap)."""

from __future__ import annotations

from pathlib import Path

from forge.sync.provenance import (
    ProvenanceCollector,
    ProvenanceRecord,
    classify,
    sha256_of,
)


class TestSha256Of:
    def test_normalizes_crlf_to_lf(self, tmp_path: Path) -> None:
        lf = tmp_path / "lf.txt"
        lf.write_bytes(b"a\nb\nc\n")
        crlf = tmp_path / "crlf.txt"
        crlf.write_bytes(b"a\r\nb\r\nc\r\n")
        assert sha256_of(lf) == sha256_of(crlf)

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        a = tmp_path / "a.txt"
        a.write_text("hello")
        b = tmp_path / "b.txt"
        b.write_text("world")
        assert sha256_of(a) != sha256_of(b)

    def test_stable_across_invocations(self, tmp_path: Path) -> None:
        p = tmp_path / "x.txt"
        p.write_text("content")
        assert sha256_of(p) == sha256_of(p)

    def test_crlf_straddling_chunk_boundary_matches_merge(self, tmp_path: Path) -> None:
        """A CRLF split across the 64 KiB read boundary must still collapse.

        ``sha256_of`` streams the file in 65536-byte chunks. If a ``\\r\\n``
        lands with the CR as the last byte of one chunk and the LF as the
        first byte of the next, a naive per-chunk ``replace(b"\\r\\n", b"\\n")``
        never sees the pair and leaves a stray CR in the digest — diverging
        from ``merge.sha256_of_file`` (which normalizes the whole content
        globally). That divergence breaks the update/harvest round-trip for
        CRLF files at exactly this size.
        """
        from forge.sync.merge import sha256_of_file  # noqa: PLC0415

        # 65535 filler bytes, then a CRLF whose CR is byte 65535 (end of the
        # first 65536-byte chunk) and whose LF is byte 65536 (start of the
        # second chunk).
        data = b"a" * 65535 + b"\r\n" + b"b" * 16
        f = tmp_path / "straddle.txt"
        f.write_bytes(data)

        assert sha256_of(f) == sha256_of_file(f)


class TestProvenanceCollector:
    def test_records_file_with_relative_path(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n")
        c = ProvenanceCollector(project_root=tmp_path)
        c.record(tmp_path / "a.py", origin="base-template")
        assert "a.py" in c.records
        assert c.records["a.py"].origin == "base-template"

    def test_records_fragment_with_metadata(self, tmp_path: Path) -> None:
        (tmp_path / "routes.py").write_text("# routes")
        c = ProvenanceCollector(project_root=tmp_path)
        c.record(
            tmp_path / "routes.py",
            origin="fragment",
            fragment_name="rate_limit",
            fragment_version="1.2.0",
        )
        rec = c.records["routes.py"]
        assert rec.origin == "fragment"
        assert rec.fragment_name == "rate_limit"
        assert rec.fragment_version == "1.2.0"

    def test_posix_path_keys_on_windows_and_linux(self, tmp_path: Path) -> None:
        nested = tmp_path / "src" / "app" / "main.py"
        nested.parent.mkdir(parents=True)
        nested.write_text("pass")
        c = ProvenanceCollector(project_root=tmp_path)
        c.record(nested, origin="base-template")
        assert "src/app/main.py" in c.records

    def test_drop_records_under_directory(self, tmp_path: Path) -> None:
        """drop_records_under('alembic') removes every record under that prefix.

        Used by strip_python_database after _delete_targets wipes DB-stack
        directories — without pruning, the manifest retains ghost rows for
        files no longer on disk.
        """
        for rel in ("alembic/env.py", "alembic/versions/0001.py", "src/app/main.py"):
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")
        c = ProvenanceCollector(project_root=tmp_path)
        for rel in ("alembic/env.py", "alembic/versions/0001.py", "src/app/main.py"):
            c.record(tmp_path / rel, origin="base-template")

        c.drop_records_under("alembic")

        assert "alembic/env.py" not in c.records
        assert "alembic/versions/0001.py" not in c.records
        assert "src/app/main.py" in c.records  # untouched

    def test_drop_records_under_single_file(self, tmp_path: Path) -> None:
        """drop_records_under('alembic.ini') drops just that one record."""
        for rel in ("alembic.ini", "alembic.toml"):
            (tmp_path / rel).write_text("x")
        c = ProvenanceCollector(project_root=tmp_path)
        c.record(tmp_path / "alembic.ini", origin="base-template")
        c.record(tmp_path / "alembic.toml", origin="base-template")

        c.drop_records_under("alembic.ini")

        assert "alembic.ini" not in c.records
        # 'alembic.toml' must survive — it shares a stem but isn't under the prefix.
        assert "alembic.toml" in c.records

    def test_drop_records_under_noop_on_missing_prefix(self, tmp_path: Path) -> None:
        c = ProvenanceCollector(project_root=tmp_path)
        (tmp_path / "kept.py").write_text("x")
        c.record(tmp_path / "kept.py", origin="base-template")
        c.drop_records_under("does/not/exist")
        assert "kept.py" in c.records

    def test_skips_files_outside_project_root(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("nope")
        try:
            c = ProvenanceCollector(project_root=tmp_path / "inside")
            (tmp_path / "inside").mkdir()
            c.record(outside, origin="base-template")
            assert c.records == {}
        finally:
            outside.unlink(missing_ok=True)

    def test_as_dict_is_toml_serializable(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("pass")
        c = ProvenanceCollector(project_root=tmp_path)
        c.record(
            tmp_path / "a.py",
            origin="fragment",
            fragment_name="rate_limit",
        )
        d = c.as_dict()
        # ``emitted_at`` is auto-populated; it's a non-empty ISO-8601 string but
        # we don't assert the exact timestamp.
        entry = d["a.py"]
        assert entry["origin"] == "fragment"
        assert entry["sha256"]
        assert entry["fragment_name"] == "rate_limit"
        assert "emitted_at" in entry and entry["emitted_at"]
        # Only fields above plus emitted_at; no fragment_version / template_*.
        assert set(entry) == {"origin", "sha256", "fragment_name", "emitted_at"}

    def test_as_dict_omits_none_fields(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("pass")
        c = ProvenanceCollector(project_root=tmp_path)
        c.record(tmp_path / "a.py", origin="base-template")
        entry = c.as_dict()["a.py"]
        assert "fragment_name" not in entry
        assert "fragment_version" not in entry

    def test_as_dict_includes_all_v2_fields_when_present(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("# routes")
        c = ProvenanceCollector(project_root=tmp_path)
        c.record(
            tmp_path / "main.py",
            origin="base-template",
            template_name="python-service-template",
            template_version="0.6.1",
        )
        entry = c.as_dict()["main.py"]
        assert entry["template_name"] == "python-service-template"
        assert entry["template_version"] == "0.6.1"
        assert "emitted_at" in entry
        # Fragment fields stay absent for base-template origin.
        assert "fragment_name" not in entry
        assert "fragment_version" not in entry

    def test_as_dict_includes_fragment_version_when_present(self, tmp_path: Path) -> None:
        (tmp_path / "f.py").write_text("# fragment")
        c = ProvenanceCollector(project_root=tmp_path)
        c.record(
            tmp_path / "f.py",
            origin="fragment",
            fragment_name="cors",
            fragment_version="2.3.4",
        )
        entry = c.as_dict()["f.py"]
        assert entry["fragment_version"] == "2.3.4"

    def test_record_skips_when_file_not_present(self, tmp_path: Path) -> None:
        # Fragment declared a file but it didn't actually land — record() must no-op.
        c = ProvenanceCollector(project_root=tmp_path)
        c.record(tmp_path / "missing.py", origin="fragment", fragment_name="x")
        assert c.records == {}


class TestRecordInjectionTarget:
    """D3 regression — a fragment injecting a block into a base-template
    file must NOT take ownership of the whole file. Otherwise disabling
    the fragment lets the uninstaller delete a base-template entrypoint
    (e.g. Node ``src/app.ts``), breaking every later fragment that
    injects into it during ``forge --update``.
    """

    def test_preserves_base_template_origin(self, tmp_path: Path) -> None:
        app = tmp_path / "src" / "app.ts"
        app.parent.mkdir(parents=True)
        app.write_text("// base render\n")
        c = ProvenanceCollector(project_root=tmp_path)
        c.record(app, origin="base-template", template_name="node-service")
        base_sha = c.records["src/app.ts"].sha256

        # Fragment injects a block, changing the file's bytes.
        app.write_text("// base render\n// FORGE block\n")
        c.record_injection_target(app, fragment_name="rate_limit")

        rec = c.records["src/app.ts"]
        # Origin stays base-template; the file is NOT downgraded to fragment.
        assert rec.origin == "base-template"
        assert rec.fragment_name is None
        assert rec.template_name == "node-service"
        # SHA refreshed to the post-injection content so classify() reports
        # 'unchanged' rather than 'user-modified' on the next update.
        assert rec.sha256 != base_sha
        assert rec.sha256 == sha256_of(app)

    def test_preserves_user_origin(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        f.write_text("user code\n")
        c = ProvenanceCollector(project_root=tmp_path)
        c.records["main.py"] = ProvenanceRecord(origin="user", sha256="old")

        f.write_text("user code\n# block\n")
        c.record_injection_target(f, fragment_name="frag")

        assert c.records["main.py"].origin == "user"

    def test_no_record_when_no_prior_record(self, tmp_path: Path) -> None:
        # Injection NEVER creates a file (the injector requires the target to
        # already exist). So "no prior record" means an untracked / not-yet-
        # stamped base/user file, NOT a fragment-created one. The applier must
        # NOT claim ``origin="fragment"`` here — doing so would let a later
        # disable DELETE an untracked file. The injected block is tracked
        # separately via record_merge_block, so recording nothing is correct.
        f = tmp_path / "new.ts"
        f.write_text("// FORGE block\n")
        c = ProvenanceCollector(project_root=tmp_path)
        c.record_injection_target(f, fragment_name="frag", fragment_version="1.0.0")

        assert "new.ts" not in c.records

    def test_keeps_first_fragment_owner_when_already_fragment(self, tmp_path: Path) -> None:
        # A second fragment injecting into a file the FIRST fragment created
        # leaves it owned by the first fragment (still safe to uninstall), and
        # does NOT seize ownership — the second fragment's contribution is
        # tracked by its own merge-block record. Last-injector-wins ownership
        # would orphan the file when frag_a is later uninstalled.
        f = tmp_path / "owned.ts"
        f.write_text("// block A\n")
        c = ProvenanceCollector(project_root=tmp_path)
        c.record(f, origin="fragment", fragment_name="frag_a")
        sha_before = c.records["owned.ts"].sha256

        f.write_text("// block A\n// block B\n")
        c.record_injection_target(f, fragment_name="frag_b")

        rec = c.records["owned.ts"]
        assert rec.origin == "fragment"
        assert rec.fragment_name == "frag_a"  # first owner preserved
        assert rec.sha256 != sha_before  # but SHA refreshed (bytes changed)

    def test_skips_missing_file(self, tmp_path: Path) -> None:
        c = ProvenanceCollector(project_root=tmp_path)
        c.record_injection_target(tmp_path / "ghost.ts", fragment_name="frag")
        assert c.records == {}


class TestRecordMergeBlock:
    def test_records_minimum_baseline(self, tmp_path: Path) -> None:
        c = ProvenanceCollector(project_root=tmp_path)
        c.record_merge_block(
            rel_posix_path="src/app/main.py",
            feature_key="middleware_cors",
            marker="MIDDLEWARE_REGISTRATION",
            block_sha="abc123",
        )
        from forge.sync.merge import MergeBlockCollector

        key = MergeBlockCollector.key_for(
            "src/app/main.py", "middleware_cors", "MIDDLEWARE_REGISTRATION"
        )
        rec = c.merge_blocks[key]
        assert rec.sha256 == "abc123"
        # Optional fields default to None.
        assert rec.fragment_name is None
        assert rec.fragment_version is None
        assert rec.snippet_sha256 is None
        assert rec.line_range is None

    def test_records_with_full_metadata(self, tmp_path: Path) -> None:
        c = ProvenanceCollector(project_root=tmp_path)
        c.record_merge_block(
            rel_posix_path="src/app/main.py",
            feature_key="middleware_cors",
            marker="MIDDLEWARE_REGISTRATION",
            block_sha="abc",
            fragment_name="middleware_cors",
            fragment_version="1.2.0",
            snippet_sha256="def",
            line_range=(44, 46),
        )
        d = c.merge_blocks_as_dict()
        (entry,) = d.values()
        assert entry["sha256"] == "abc"
        assert entry["fragment_name"] == "middleware_cors"
        assert entry["fragment_version"] == "1.2.0"
        assert entry["snippet_sha256"] == "def"
        # line_range is serialized as a list (TOML doesn't have tuples).
        assert entry["line_range"] == [44, 46]

    def test_merge_blocks_as_dict_omits_none_fields(self, tmp_path: Path) -> None:
        c = ProvenanceCollector(project_root=tmp_path)
        c.record_merge_block(
            rel_posix_path="src/a.py",
            feature_key="feat",
            marker="X",
            block_sha="z",
        )
        d = c.merge_blocks_as_dict()
        (entry,) = d.values()
        # v1-shape entry — only sha256 emitted; richer fields skipped.
        assert set(entry) == {"sha256"}


class TestClassify:
    def test_unchanged_when_sha_matches(self, tmp_path: Path) -> None:
        p = tmp_path / "f.py"
        p.write_text("code")
        rec = ProvenanceRecord(origin="base-template", sha256=sha256_of(p))
        assert classify(p, rec) == "unchanged"

    def test_user_modified_when_content_changed(self, tmp_path: Path) -> None:
        p = tmp_path / "f.py"
        p.write_text("code")
        original_sha = sha256_of(p)
        p.write_text("user edit")
        rec = ProvenanceRecord(origin="base-template", sha256=original_sha)
        assert classify(p, rec) == "user-modified"

    def test_missing_when_file_deleted(self, tmp_path: Path) -> None:
        p = tmp_path / "gone.py"
        rec = ProvenanceRecord(origin="base-template", sha256="deadbeef")
        assert classify(p, rec) == "missing"


class TestForgeTomlRoundtrip:
    """Integration: write_forge_toml + read_forge_toml preserves provenance."""

    def test_provenance_survives_roundtrip(self, tmp_path: Path) -> None:
        from forge.sync.manifest import read_forge_toml, write_forge_toml  # noqa: PLC0415

        manifest = tmp_path / "forge.toml"
        provenance = {
            "src/app/main.py": {
                "origin": "base-template",
                "sha256": "abc123",
            },
            "src/app/middleware.py": {
                "origin": "fragment",
                "sha256": "def456",
                "fragment_name": "rate_limit",
            },
        }
        write_forge_toml(
            manifest,
            version="1.0.0a1",
            project_name="demo",
            templates={"python": "services/python-service-template"},
            options={},
            provenance=provenance,
        )
        data = read_forge_toml(manifest)
        assert data.provenance["src/app/main.py"]["origin"] == "base-template"
        assert data.provenance["src/app/main.py"]["sha256"] == "abc123"
        assert data.provenance["src/app/middleware.py"]["fragment_name"] == "rate_limit"

    def test_no_provenance_key_when_empty(self, tmp_path: Path) -> None:
        from forge.sync.manifest import write_forge_toml  # noqa: PLC0415

        manifest = tmp_path / "forge.toml"
        write_forge_toml(
            manifest,
            version="1.0.0a1",
            project_name="demo",
            templates={"python": "services/python-service-template"},
            options={},
            provenance=None,
        )
        body = manifest.read_text(encoding="utf-8")
        assert "[forge.provenance" not in body
