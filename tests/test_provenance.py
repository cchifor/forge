"""Tests for the provenance manifest (0.2 of the 1.0 roadmap)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.provenance import (
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
        assert d == {
            "a.py": {
                "origin": "fragment",
                "sha256": pytest.approx(d["a.py"]["sha256"]),
                "fragment_name": "rate_limit",
            }
        }

    def test_as_dict_omits_none_fields(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("pass")
        c = ProvenanceCollector(project_root=tmp_path)
        c.record(tmp_path / "a.py", origin="base-template")
        entry = c.as_dict()["a.py"]
        assert "fragment_name" not in entry
        assert "fragment_version" not in entry


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
        from forge.forge_toml import read_forge_toml, write_forge_toml  # noqa: PLC0415

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
        from forge.forge_toml import read_forge_toml, write_forge_toml  # noqa: PLC0415

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
