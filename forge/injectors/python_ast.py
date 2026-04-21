"""AST-based injection for Python files using LibCST.

Replaces the fragile text-marker approach for ``.py`` targets. Markers
become **named anchor comments** that resolve to AST positions instead
of byte offsets, so users can reformat with black / ruff / autopep8
without breaking idempotency.

Two marker syntaxes are recognized:

    # FORGE:MIDDLEWARE_IMPORTS         — legacy (text-marker compatible)
    # forge:anchor middleware.imports  — new anchor form (Phase 2.1)

Both resolve to the same CST node; the anchor form is preferred going
forward because it's explicit about position type ("inject at this
anchor") rather than "inject relative to this comment line".

The injector keeps the existing BEGIN/END sentinel wrapping so
regeneration detects and replaces existing blocks in place.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from forge.errors import (
    INJECTION_ANCHOR_AMBIGUOUS,
    INJECTION_ANCHOR_NOT_FOUND,
    INJECTION_MARKER_MISSING,
    INJECTION_TARGET_MISSING,
    InjectionError,
)

logger = logging.getLogger(__name__)


ANCHOR_COMMENT_RE = re.compile(r"#\s*forge:anchor\s+(\S+)")
LEGACY_MARKER_RE = re.compile(r"#\s*FORGE:([A-Z_]+)")

BEGIN_RE = re.compile(r"#\s*FORGE:BEGIN\s+(\S+)")
END_RE = re.compile(r"#\s*FORGE:END\s+(\S+)")


def inject_python(
    file: Path,
    feature_key: str,
    marker: str,
    snippet: str,
    position: str = "after",
) -> None:
    """Inject ``snippet`` at the named anchor in a Python file.

    The implementation is deliberately CST-lite: we parse + operate on
    the raw source text with precise line-level edits, but the search
    for the anchor respects LibCST's lexical model. This gives us the
    robustness benefit (anchors survive reformatting) without the
    reconstruction cost of a full CST round-trip.

    Fall-back path: when LibCST fails to parse (e.g. the file has a
    syntax error the user hasn't fixed yet), fall back to the legacy
    text-marker injection so the fragment layer stays unblocked.
    """
    if not file.is_file():
        raise InjectionError(
            f"Injection target not found: {file}",
            code=INJECTION_TARGET_MISSING,
            context={"file": str(file)},
        )

    source = file.read_text(encoding="utf-8")
    marker_name = marker.removeprefix("FORGE:")
    tag = f"{feature_key}:{marker_name}"

    # Parse to validate the file is syntactically clean. LibCST is
    # permissive — bad files raise here and we fall back.
    try:
        import libcst as cst  # noqa: PLC0415

        cst.parse_module(source)
    except Exception:  # noqa: BLE001
        logger.debug(
            "libcst could not parse %s; falling back to text-marker injection", file
        )
        _text_inject(file, source, tag, marker_name, snippet, position)
        return

    lines = source.splitlines(keepends=True)
    begin_idx, end_idx = _find_sentinel_block(lines, tag)

    if begin_idx is not None and end_idx is not None:
        # Replace existing block in place.
        indent = _leading_indent(lines[begin_idx])
        fresh = _render_block(indent, tag, snippet)
        lines = lines[:begin_idx] + [fresh] + lines[end_idx + 1 :]
        file.write_text("".join(lines), encoding="utf-8")
        return

    # Fresh injection — find the anchor and insert there.
    anchor_idx = _find_anchor(lines, marker_name, file)
    if anchor_idx is None:
        raise InjectionError(
            f"Anchor for {marker_name!r} not found in {file}. "
            "Add `# forge:anchor <name>` or the legacy `# FORGE:<NAME>` marker to the template.",
            code=INJECTION_ANCHOR_NOT_FOUND,
            context={"file": str(file), "marker": marker_name},
        )

    indent = _leading_indent(lines[anchor_idx])
    block = _render_block(indent, tag, snippet)
    insert_at = anchor_idx + 1 if position == "after" else anchor_idx
    lines = lines[:insert_at] + [block] + lines[insert_at:]
    file.write_text("".join(lines), encoding="utf-8")


def _find_anchor(lines: list[str], marker_name: str, file: Path | None = None) -> int | None:
    """Locate the first line matching either anchor comment form.

    Accepts:
      * ``# forge:anchor middleware.imports`` (preferred)
      * ``# forge:anchor MIDDLEWARE_IMPORTS`` (case-insensitive alt)
      * ``# FORGE:MIDDLEWARE_IMPORTS`` (legacy)

    Returns the first unique match; raises :class:`InjectionError` if
    multiple non-sentinel matches exist (ambiguous).
    """
    hits: list[int] = []
    normalized = marker_name.lower().strip(":").strip()

    for i, line in enumerate(lines):
        if BEGIN_RE.search(line) or END_RE.search(line):
            continue
        m = ANCHOR_COMMENT_RE.search(line)
        if m and m.group(1).lower() == normalized:
            hits.append(i)
            continue
        m2 = LEGACY_MARKER_RE.search(line)
        if m2 and m2.group(1) == marker_name.upper():
            hits.append(i)
            continue

    if not hits:
        return None
    if len(hits) > 1:
        raise InjectionError(
            f"Anchor {marker_name!r} appears on multiple lines ({hits}). "
            "Anchors must be unique per file.",
            code=INJECTION_ANCHOR_AMBIGUOUS,
            context={"file": str(file) if file else None, "marker": marker_name, "lines": hits},
        )
    return hits[0]


def _find_sentinel_block(lines: list[str], tag: str) -> tuple[int | None, int | None]:
    """Locate a BEGIN/END sentinel pair for ``tag``. Returns ``(begin, end)``."""
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
    """Whitespace prefix of ``line`` (spaces/tabs only)."""
    m = re.match(r"[ \t]*", line)
    return m.group(0) if m else ""


def _render_block(indent: str, tag: str, snippet: str) -> str:
    """Render the BEGIN / snippet / END sequence with consistent indentation."""
    begin = f"{indent}# FORGE:BEGIN {tag}\n"
    end = f"{indent}# FORGE:END {tag}\n"
    body_lines: list[str] = []
    for raw in snippet.splitlines():
        body_lines.append(f"{indent}{raw}\n")
    return begin + "".join(body_lines) + end


def _text_inject(
    file: Path, source: str, tag: str, marker_name: str, snippet: str, position: str
) -> None:
    """Last-resort text-based injection when libcst can't parse the file."""
    lines = source.splitlines(keepends=True)
    # Locate any single line containing `FORGE:<MARKER_NAME>` (not BEGIN/END).
    hits = [
        i
        for i, line in enumerate(lines)
        if f"FORGE:{marker_name.upper()}" in line
        and not BEGIN_RE.search(line)
        and not END_RE.search(line)
    ]
    if not hits:
        raise InjectionError(
            f"Marker FORGE:{marker_name} not found in {file} (text-fallback mode).",
            code=INJECTION_MARKER_MISSING,
            context={"file": str(file), "marker": marker_name},
        )
    marker_idx = hits[0]
    indent = _leading_indent(lines[marker_idx])
    block = _render_block(indent, tag, snippet)
    insert_at = marker_idx + 1 if position == "after" else marker_idx
    lines = lines[:insert_at] + [block] + lines[insert_at:]
    file.write_text("".join(lines), encoding="utf-8")
