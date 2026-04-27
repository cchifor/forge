"""Tests for file-level three-way merge (P0.1, 1.1.0-alpha.2).

Mirrors :mod:`tests.test_three_way_merge` for the file-copy path used by
:mod:`forge.appliers.files`. The decision function is pure over content
hashes; sidecar emission is the only I/O.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.merge import (
    FileMergeOutcome,
    file_three_way_decide,
    is_binary_file,
    sha256_of_file,
    sha256_of_text,
    write_file_sidecar,
)


# ---------------------------------------------------------------------------
# file_three_way_decide — exhaustive decision table
# ---------------------------------------------------------------------------


class TestFileThreeWayDecide:
    """Every row of the 7-row decision table, expressed by name."""

    def test_no_baseline_no_current_emits(self) -> None:
        # First emit: file never tracked, never on disk.
        assert (
            file_three_way_decide(
                baseline_sha=None,
                current_sha=None,
                new_sha=sha256_of_text("hello\n"),
            )
            == "applied"
        )

    def test_no_baseline_existing_current_preserves(self) -> None:
        # Pre-1.0 generation or hand-authored file forge never tracked.
        assert (
            file_three_way_decide(
                baseline_sha=None,
                current_sha=sha256_of_text("user wrote this\n"),
                new_sha=sha256_of_text("fragment wants\n"),
            )
            == "no-baseline"
        )

    def test_baseline_user_deleted_reemits(self) -> None:
        # User deleted a fragment-authored file. We re-emit; deletion is
        # not a supported way to opt out — disable the fragment instead.
        baseline = sha256_of_text("body\n")
        assert (
            file_three_way_decide(
                baseline_sha=baseline,
                current_sha=None,
                new_sha=sha256_of_text("body\n"),
            )
            == "applied"
        )

    def test_idempotent_when_current_matches_new(self) -> None:
        # Fragment changed since baseline, user matched the new state by
        # coincidence. Nothing to do.
        new = sha256_of_text("matching\n")
        assert (
            file_three_way_decide(
                baseline_sha=sha256_of_text("old\n"),
                current_sha=new,
                new_sha=new,
            )
            == "skipped-idempotent"
        )

    def test_applied_when_current_matches_baseline(self) -> None:
        # User didn't touch the file; safe overwrite with new content.
        baseline = sha256_of_text("v1\n")
        assert (
            file_three_way_decide(
                baseline_sha=baseline,
                current_sha=baseline,
                new_sha=sha256_of_text("v2\n"),
            )
            == "applied"
        )

    def test_skipped_no_change_when_fragment_unchanged(self) -> None:
        # Fragment unchanged since baseline; user edited locally. Keep
        # the user edit; do not regenerate identical content over it.
        baseline = sha256_of_text("v1\n")
        assert (
            file_three_way_decide(
                baseline_sha=baseline,
                current_sha=sha256_of_text("user edit\n"),
                new_sha=baseline,
            )
            == "skipped-no-change"
        )

    def test_conflict_when_all_three_differ(self) -> None:
        # Both user and fragment moved; we cannot reconcile, so sidecar.
        assert (
            file_three_way_decide(
                baseline_sha=sha256_of_text("v1\n"),
                current_sha=sha256_of_text("user edit\n"),
                new_sha=sha256_of_text("v2\n"),
            )
            == "conflict"
        )


# ---------------------------------------------------------------------------
# Hashing — CRLF normalisation for text, raw bytes for binary
# ---------------------------------------------------------------------------


class TestSha256OfFile:
    def test_crlf_lf_round_trip_text(self, tmp_path: Path) -> None:
        # A fragment file checked-in LF should hash the same on a Windows
        # working tree where the editor turned it into CRLF.
        lf = tmp_path / "lf.txt"
        crlf = tmp_path / "crlf.txt"
        lf.write_bytes(b"alpha\nbeta\ngamma\n")
        crlf.write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")
        assert sha256_of_file(lf) == sha256_of_file(crlf)

    def test_text_matches_sha256_of_text(self, tmp_path: Path) -> None:
        body = "hello\nworld\n"
        path = tmp_path / "text.txt"
        path.write_text(body, encoding="utf-8")
        assert sha256_of_file(path) == sha256_of_text(body)

    def test_binary_hashes_raw_bytes(self, tmp_path: Path) -> None:
        # A null byte makes the file binary; CRLF normalisation must NOT
        # apply (would corrupt the bytes).
        raw = b"PNG\x00\r\n\xffrest"
        path = tmp_path / "image.png"
        path.write_bytes(raw)
        assert sha256_of_file(path) != sha256_of_text(raw.decode("latin-1"))
        # ... but two binary files with identical bytes match exactly.
        twin = tmp_path / "image-twin.png"
        twin.write_bytes(raw)
        assert sha256_of_file(path) == sha256_of_file(twin)

    def test_non_utf8_treated_as_binary(self, tmp_path: Path) -> None:
        # Latin-1 file with no null byte but invalid UTF-8 falls through
        # to byte hashing; CRLF normalisation can't apply to bytes that
        # don't decode.
        path = tmp_path / "latin1.txt"
        path.write_bytes(b"caf\xe9\n")
        # Hashes the raw bytes; computable without raising.
        digest = sha256_of_file(path)
        assert len(digest) == 64


class TestIsBinaryFile:
    def test_text_file_not_binary(self, tmp_path: Path) -> None:
        path = tmp_path / "code.py"
        path.write_text("x = 1\n", encoding="utf-8")
        assert is_binary_file(path) is False

    def test_null_byte_makes_binary(self, tmp_path: Path) -> None:
        path = tmp_path / "blob.bin"
        path.write_bytes(b"\x00\x01\x02")
        assert is_binary_file(path) is True

    def test_missing_file_not_binary(self, tmp_path: Path) -> None:
        # Caller-side: a missing file is not binary in the
        # "preserve user delete" sense; the decision function handles
        # the missing case via current_sha=None.
        assert is_binary_file(tmp_path / "missing") is False

    def test_null_byte_beyond_sample_window_not_detected(
        self, tmp_path: Path
    ) -> None:
        # Match Git's heuristic: only the first 8 KiB matters. A null
        # byte at offset 16 KiB does not flip the file to binary.
        path = tmp_path / "long.txt"
        body = b"a" * 16384 + b"\x00rest"
        path.write_bytes(body)
        assert is_binary_file(path) is False


# ---------------------------------------------------------------------------
# write_file_sidecar — text + binary variants
# ---------------------------------------------------------------------------


class TestWriteFileSidecar:
    def test_text_sidecar_has_banner_and_content(self, tmp_path: Path) -> None:
        target = tmp_path / "config.yaml"
        target.write_text("user: edit\n", encoding="utf-8")
        sidecar = write_file_sidecar(
            target, "fragment: wanted\n", tag="my_fragment:files/config.yaml"
        )
        body = sidecar.read_text(encoding="utf-8")
        assert sidecar.name == "config.yaml.forge-merge"
        assert "fragment: wanted" in body
        assert "my_fragment:files/config.yaml" in body
        assert "merge by hand" in body.lower()

    def test_binary_sidecar_no_banner(self, tmp_path: Path) -> None:
        target = tmp_path / "logo.png"
        target.write_bytes(b"\x89PNG-old")
        sidecar = write_file_sidecar(
            target, b"\x89PNG-new", tag="branding:files/logo.png"
        )
        # Suffix concat preserves the original ".png" so users can spot
        # the file type at a glance: ``logo.png.forge-merge.bin``.
        assert sidecar.name == "logo.png.forge-merge.bin"
        # Binary sidecar is the raw bytes; no annotation.
        assert sidecar.read_bytes() == b"\x89PNG-new"

    def test_target_untouched_after_sidecar(self, tmp_path: Path) -> None:
        # Sidecar emission must never overwrite the target — the user's
        # local state is the resolution authority.
        target = tmp_path / "main.py"
        target.write_text("user edit\n", encoding="utf-8")
        write_file_sidecar(target, "fragment edit\n", tag="f:X")
        assert target.read_text(encoding="utf-8") == "user edit\n"

    def test_dotted_filename_sidecar_path(self, tmp_path: Path) -> None:
        # archive.tar.gz → archive.tar.gz.forge-merge (preserves both
        # extensions; pathlib.with_suffix drops only the last component).
        target = tmp_path / "archive.tar.gz"
        target.write_bytes(b"old")
        sidecar = write_file_sidecar(target, "new\n", tag="t")
        assert sidecar.name == "archive.tar.gz.forge-merge"

    def test_no_extension_sidecar_path(self, tmp_path: Path) -> None:
        # Dockerfile (no suffix) → Dockerfile.forge-merge.
        target = tmp_path / "Dockerfile"
        target.write_text("FROM old\n", encoding="utf-8")
        sidecar = write_file_sidecar(target, "FROM new\n", tag="t")
        assert sidecar.name == "Dockerfile.forge-merge"


# ---------------------------------------------------------------------------
# FileMergeOutcome — value-object shape
# ---------------------------------------------------------------------------


class TestFileMergeOutcome:
    def test_default_no_sidecar(self, tmp_path: Path) -> None:
        outcome = FileMergeOutcome(action="applied", target=tmp_path / "x.py")
        assert outcome.sidecar_path is None
        assert outcome.action == "applied"

    def test_conflict_carries_sidecar_path(self, tmp_path: Path) -> None:
        target = tmp_path / "x.py"
        sidecar = tmp_path / "x.py.forge-merge"
        outcome = FileMergeOutcome(
            action="conflict", target=target, sidecar_path=sidecar
        )
        assert outcome.sidecar_path == sidecar

    @pytest.mark.parametrize(
        "action",
        ["applied", "skipped-idempotent", "skipped-no-change", "conflict", "no-baseline"],
    )
    def test_action_vocabulary(self, action: str, tmp_path: Path) -> None:
        # Encodes the contract that callers can match on these strings.
        outcome = FileMergeOutcome(action=action, target=tmp_path / "x")
        assert outcome.action == action
