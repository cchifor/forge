"""TypeScript / JavaScript anchor-based injector.

Mirrors the Python LibCST injector's contract but uses ``//`` comment
sentinels and doesn't require a TS parser sidecar. The injector:

    * Locates anchor comments (``// forge:anchor <name>``) or legacy
      markers (``// FORGE:<NAME>``) by regex
    * Wraps new blocks with ``// FORGE:BEGIN tag`` / ``// FORGE:END tag``
    * Replaces existing sentinel blocks in place on re-apply
    * Preserves the anchor's leading indentation

Full ts-morph AST integration (Phase 2.1 stretch goal) lands in 1.0.0a2
as an optional sidecar process. For the alpha, this regex-based
injector is robust enough to survive Prettier reformatting because it
anchors on comment content, not line offsets.
"""

from __future__ import annotations

import re
from pathlib import Path

ANCHOR_RE = re.compile(r"//\s*forge:anchor\s+(\S+)")
LEGACY_RE = re.compile(r"//\s*FORGE:([A-Z_]+)")
BEGIN_RE = re.compile(r"//\s*FORGE:BEGIN\s+(\S+)")
END_RE = re.compile(r"//\s*FORGE:END\s+(\S+)")


def inject_ts(
    file: Path,
    feature_key: str,
    marker: str,
    snippet: str,
    position: str = "after",
) -> None:
    """Insert (or replace) ``snippet`` at the named TS anchor.

    When ``FORGE_TS_AST=1`` and node + ts-morph are available, dispatches
    to the AST-aware sidecar. Falls back to the regex path when the
    sidecar can't run — the regex injector is robust enough for every
    shipped forge fragment.
    """
    from forge.injectors.ts_morph_sidecar import (  # noqa: PLC0415
        inject_ts_via_morph,
        is_enabled,
    )

    if not file.is_file():
        raise FileNotFoundError(file)

    if is_enabled() and inject_ts_via_morph(file, feature_key, marker, snippet, position):
        return

    source = file.read_text(encoding="utf-8")
    marker_name = marker.removeprefix("FORGE:")
    tag = f"{feature_key}:{marker_name}"
    lines = source.splitlines(keepends=True)

    begin_idx, end_idx = _find_sentinel_block(lines, tag)
    if begin_idx is not None and end_idx is not None:
        indent = _leading_indent(lines[begin_idx])
        fresh = _render_block(indent, tag, snippet)
        lines = lines[:begin_idx] + [fresh] + lines[end_idx + 1 :]
        file.write_text("".join(lines), encoding="utf-8")
        return

    anchor_idx = _find_anchor(lines, marker_name)
    if anchor_idx is None:
        raise ValueError(
            f"Anchor for {marker_name!r} not found in {file}. "
            "Add `// forge:anchor <name>` or the legacy `// FORGE:<NAME>` marker."
        )

    indent = _leading_indent(lines[anchor_idx])
    block = _render_block(indent, tag, snippet)
    insert_at = anchor_idx + 1 if position == "after" else anchor_idx
    lines = lines[:insert_at] + [block] + lines[insert_at:]
    file.write_text("".join(lines), encoding="utf-8")


def _find_anchor(lines: list[str], marker_name: str) -> int | None:
    hits: list[int] = []
    normalized = marker_name.lower().strip(":").strip()
    for i, line in enumerate(lines):
        if BEGIN_RE.search(line) or END_RE.search(line):
            continue
        m = ANCHOR_RE.search(line)
        if m and m.group(1).lower() == normalized:
            hits.append(i)
            continue
        m2 = LEGACY_RE.search(line)
        if m2 and m2.group(1) == marker_name.upper():
            hits.append(i)
    if not hits:
        return None
    if len(hits) > 1:
        raise ValueError(
            f"Anchor {marker_name!r} appears on multiple lines ({hits}); must be unique."
        )
    return hits[0]


def _find_sentinel_block(lines: list[str], tag: str) -> tuple[int | None, int | None]:
    begin_idx: int | None = None
    end_idx: int | None = None
    for i, line in enumerate(lines):
        bm = BEGIN_RE.search(line)
        if bm and bm.group(1) == tag:
            begin_idx = i
            continue
        em = END_RE.search(line)
        if em and em.group(1) == tag:
            end_idx = i
            break
    return begin_idx, end_idx


def _leading_indent(line: str) -> str:
    m = re.match(r"[ \t]*", line)
    return m.group(0) if m else ""


def _render_block(indent: str, tag: str, snippet: str) -> str:
    begin = f"{indent}// FORGE:BEGIN {tag}\n"
    end = f"{indent}// FORGE:END {tag}\n"
    body_lines: list[str] = []
    for raw in snippet.splitlines():
        body_lines.append(f"{indent}{raw}\n")
    return begin + "".join(body_lines) + end
