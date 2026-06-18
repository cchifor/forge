"""Regression: record-side and merge-side hashing agree on binary files
(audit #22).

Provenance records a file's baseline with ``provenance.sha256_of`` (which
globally collapsed ``\\r\\n`` -> ``\\n`` with NO binary detection), while the
three-way merge recomputes with ``merge.sha256_of_file`` (binary-aware: raw
bytes for binary, CRLF-normalized for text). For a byte-identical binary blob
containing the bytes ``0x0D 0x0A`` the two digests diverged, so a bumped binary
fragment the user never touched produced a spurious ``.forge-merge.bin``
conflict (both baseline and current appear "moved").

Unifying record-side hashing with the binary-aware merge implementation makes
the digests agree.
"""

from __future__ import annotations

from pathlib import Path

from forge.sync.merge import sha256_of_file
from forge.sync.provenance import sha256_of


def test_record_and_merge_hash_agree_on_binary_with_crlf(tmp_path: Path) -> None:
    # Binary (null byte in the head sample) that happens to contain a CRLF pair.
    blob = b"\x00\x01\x02PNGish\r\n\xff\xfe payload \r\n tail"
    p = tmp_path / "asset.bin"
    p.write_bytes(blob)
    assert sha256_of(p) == sha256_of_file(p), (
        "record-side sha256_of must match merge-side sha256_of_file for binary "
        "content, or an untouched binary asset is flagged as a spurious conflict"
    )


def test_record_and_merge_hash_agree_on_text_with_crlf(tmp_path: Path) -> None:
    # Guard: the text path (CRLF-normalized) must remain consistent too.
    p = tmp_path / "f.txt"
    p.write_bytes(b"line1\r\nline2\r\n")
    assert sha256_of(p) == sha256_of_file(p)
