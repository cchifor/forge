"""Tests for ``forge_core.observability.correlation``."""

from __future__ import annotations

from forge_core.observability import correlation
from forge_core.observability.correlation import (
    CORRELATION_HEADER,
    generate_correlation_id,
    get_correlation_id,
    set_correlation_id,
)


def test_default_correlation_id_is_empty() -> None:
    # Fresh context default — never raises.
    assert correlation.get_correlation_id() == ""


def test_set_then_get_roundtrips() -> None:
    set_correlation_id("abc123")
    assert get_correlation_id() == "abc123"


def test_generate_is_compact_hex() -> None:
    cid = generate_correlation_id()
    assert len(cid) == 16
    int(cid, 16)  # parses as hex


def test_header_constant() -> None:
    assert CORRELATION_HEADER == "X-Request-ID"
