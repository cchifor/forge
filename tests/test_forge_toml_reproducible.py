"""WS-3.3(d): forge.toml provenance timestamps must be reproducible.

``forge.toml`` records an ``emitted_at`` per provenance entry, stamped from
``datetime.now()`` at generation time — so two otherwise-identical generations
produce byte-different manifests, breaking reproducible-build verification.

Honoring the de-facto-standard ``SOURCE_DATE_EPOCH`` env var lets a build
pin the timestamp, making the manifest byte-reproducible.
"""

from __future__ import annotations

import importlib

provenance = importlib.import_module("forge.sync.provenance")


def test_utc_now_iso_honors_source_date_epoch(monkeypatch):
    # 2021-01-01T00:00:00Z == epoch 1609459200
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1609459200")
    stamp = provenance._utc_now_iso()
    assert stamp == "2021-01-01T00:00:00Z", stamp


def test_utc_now_iso_is_byte_stable_under_frozen_epoch(monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    first = provenance._utc_now_iso()
    second = provenance._utc_now_iso()
    assert first == second, "frozen SOURCE_DATE_EPOCH must give identical timestamps"


def test_utc_now_iso_falls_back_to_wallclock_without_epoch(monkeypatch):
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    stamp = provenance._utc_now_iso()
    # Still the canonical ISO-8601 UTC second-resolution shape.
    assert stamp.endswith("Z") and "T" in stamp and len(stamp) == 20, stamp


def test_utc_now_iso_ignores_blank_epoch(monkeypatch):
    # An empty string is not a valid epoch — fall back to wall clock, not crash.
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "")
    stamp = provenance._utc_now_iso()
    assert stamp.endswith("Z") and "T" in stamp, stamp
