"""Guard: generated chat/agent templates must not pin a dated Claude snapshot.

Current Claude model IDs are non-dated aliases (``claude-sonnet-4-6``,
``claude-opus-4-8``, …). A *dated* form (``claude-...-20YYMMDD``) is always a
stale snapshot that deprecates and eventually 404s — exactly the drift that
shipped ``claude-sonnet-4-20250514`` in two separate Vue files. This locks the
fix in: a dated Claude ID under the chat-frontend or agent templates fails CI.
"""

from __future__ import annotations

import re
from pathlib import Path

# Where generated model defaults live (frontend chat pickers + the agent runner).
_ROOTS = (
    Path(__file__).resolve().parent.parent / "forge" / "templates" / "apps",
    Path(__file__).resolve().parent.parent / "forge" / "features" / "agent",
)
_SCANNED_SUFFIXES = {".ts", ".js", ".vue", ".svelte", ".dart", ".py", ".jinja", ".j2"}
# ``claude-<family>-<...>-<8-digit date>`` — the deprecated dated-snapshot form.
_DATED_CLAUDE = re.compile(r"claude-[a-z0-9.]+-20\d{6}")


def test_no_dated_claude_model_ids_in_templates():
    offenders: list[str] = []
    for root in _ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in _SCANNED_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for match in _DATED_CLAUDE.finditer(text):
                offenders.append(f"{path.relative_to(root.parent.parent.parent)}: {match.group(0)}")
    assert not offenders, (
        "Dated Claude model snapshots are deprecated — pin a non-dated alias "
        "(e.g. claude-sonnet-4-6) instead. Found:\n  " + "\n  ".join(sorted(offenders))
    )
