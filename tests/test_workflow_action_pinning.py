"""Guard: third-party GitHub Actions must be pinned to a full commit SHA.

A mutable tag (``@v6``, ``@main``) lets the action's code change underneath a
green ``main`` — a supply-chain risk for CI that builds + can publish. Pinning
to a 40-char SHA freezes the code until a deliberate bump.
"""

from __future__ import annotations

import re
from pathlib import Path

_WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

# Documented exceptions: actions whose floating ref is intentional.
_ALLOWED_FLOATING = {
    # Tracks the latest stable Rust toolchain by design; pinning would freeze
    # the compiler version, defeating the purpose.
    "dtolnay/rust-toolchain@stable",
}

_USES = re.compile(r"uses:\s+(?P<ref>[^\s#]+)")
_SHA = re.compile(r"[0-9a-f]{40}")


def test_third_party_actions_pinned_to_sha() -> None:
    offenders: list[str] = []
    for wf in sorted(_WORKFLOWS.glob("*.yml")):
        for i, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            m = _USES.search(line)
            if not m:
                continue
            ref = m.group("ref")
            if "@" not in ref:
                continue  # local/composite action
            if ref in _ALLOWED_FLOATING:
                continue
            rev = ref.rpartition("@")[2]
            if not _SHA.fullmatch(rev):
                offenders.append(f"{wf.name}:{i} {ref}")
    assert not offenders, "unpinned actions (pin to a full SHA): " + "; ".join(offenders)
