"""Shared sentinel-block primitives used by every injector.

Every forge injector (text-fallback, Python LibCST, TypeScript regex,
ts-morph sidecar) wraps emitted blocks with::

    {prefix} FORGE:BEGIN {tag}
    <snippet body>
    {prefix} FORGE:END {tag}

Where ``prefix`` is the comment syntax for the file's language and
``tag`` uniquely identifies the (feature, marker) pair. This module
centralises:

* the comment-prefix lookup (``_comment_prefix``)
* the canonical sentinel-tag format (``_sentinel_tag``)
* indent + uniqueness helpers
* the BEGIN/END block renderer
* the text-marker fallback injector (``_inject_snippet``)
* the sentinel-block presence + body extraction helpers used by zone
  semantics (``_has_sentinel_block``, ``_read_block_body``)

Splitting these out of :mod:`forge.feature_injector` (P1.1, Epic 1b)
keeps the orchestrator's responsibilities cleanly separated from the
text-manipulation primitives. The names are kept underscore-prefixed
so callers in ``forge/`` and ``tests/`` that import them by name from
either location keep working through the shim re-exports in
``feature_injector``.
"""

from __future__ import annotations

import re
from pathlib import Path

from forge.errors import (
    INJECTION_MARKER_AMBIGUOUS,
    INJECTION_MARKER_MISSING,
    INJECTION_SENTINEL_CORRUPT,
    INJECTION_TARGET_MISSING,
    InjectionError,
)
from forge.fragments import MARKER_PREFIX

# File-extension → single-line comment prefix. Only line-comment forms are
# supported (never `/* */` or `<!-- -->`); in practice every injection
# target in the forge registry is a .py / .ts / .rs file.
_COMMENT_PREFIXES: dict[str, str] = {
    ".py": "#",
    ".pyi": "#",
    ".yml": "#",
    ".yaml": "#",
    ".toml": "#",
    ".env": "#",
    ".sh": "#",
    ".ts": "//",
    ".tsx": "//",
    ".js": "//",
    ".jsx": "//",
    ".mjs": "//",
    ".cjs": "//",
    ".rs": "//",
    ".go": "//",
}


def _comment_prefix(file: Path) -> str:
    """Comment-syntax prefix for BEGIN/END sentinels.

    Unknown extensions fall back to ``#``. If you add a fragment that
    injects into a new file type, register its prefix here rather than
    relying on the fallback — sentinel mismatches break idempotency.
    """
    return _COMMENT_PREFIXES.get(file.suffix.lower(), "#")


def _sentinel_tag(feature_key: str, marker: str) -> str:
    """Tag identifying one injection. Unique per (file, feature, marker)."""
    # Strip FORGE: prefix from marker so the tag reads naturally.
    naked = marker[len(MARKER_PREFIX) :] if marker.startswith(MARKER_PREFIX) else marker
    return f"{feature_key}:{naked}"


def _indent_of(line: str) -> str:
    """Whitespace prefix of ``line`` (spaces/tabs only)."""
    m = re.match(r"[ \t]*", line)
    return m.group(0) if m else ""


def _find_unique_line(lines: list[str], substring: str, file: Path, *, needle: str) -> int | None:
    """Return the unique line index containing ``substring`` or None.

    Raises if the substring appears more than once — ambiguous sentinels
    would silently corrupt re-injection.
    """
    hits = [i for i, line in enumerate(lines) if substring in line]
    if not hits:
        return None
    if len(hits) > 1:
        raise InjectionError(
            f"'{needle}' appears {len(hits)} times in {file}; must be unique.",
            code=INJECTION_MARKER_AMBIGUOUS,
            context={"file": str(file), "marker": needle, "count": len(hits)},
        )
    return hits[0]


def _render_block(indent: str, prefix: str, tag: str, snippet: str) -> str:
    """Produce ``{indent}{prefix} BEGIN ...\\n<snippet>\\n{indent}{prefix} END ...\\n``."""
    begin = f"{indent}{prefix} {MARKER_PREFIX}BEGIN {tag}\n"
    end = f"{indent}{prefix} {MARKER_PREFIX}END {tag}\n"
    body = "".join(f"{indent}{line}\n" for line in snippet.splitlines())
    return begin + body + end


def _has_sentinel_block(file: Path, feature_key: str, marker: str) -> bool:
    """True when ``file`` already contains a BEGIN/END sentinel pair for this tag."""
    if not file.is_file():
        return False
    tag = _sentinel_tag(feature_key, marker)
    begin_needle = f"{MARKER_PREFIX}BEGIN {tag}"
    end_needle = f"{MARKER_PREFIX}END {tag}"
    text = file.read_text(encoding="utf-8")
    return begin_needle in text and end_needle in text


def _read_block_body(file: Path, feature_key: str, marker: str) -> str | None:
    """Return the lines between BEGIN/END sentinels for this tag, exclusive."""
    if not file.is_file():
        return None
    tag = _sentinel_tag(feature_key, marker)
    begin_needle = f"{MARKER_PREFIX}BEGIN {tag}"
    end_needle = f"{MARKER_PREFIX}END {tag}"
    text = file.read_text(encoding="utf-8")
    if begin_needle not in text or end_needle not in text:
        return None
    lines = text.splitlines(keepends=True)
    begin_idx = next((i for i, line in enumerate(lines) if begin_needle in line), None)
    end_idx = next((i for i, line in enumerate(lines) if end_needle in line), None)
    if begin_idx is None or end_idx is None or end_idx <= begin_idx:
        return None
    return "".join(lines[begin_idx + 1 : end_idx])


def _inject_snippet(
    file: Path,
    feature_key: str,
    marker: str,
    snippet: str,
    position: str,
) -> None:
    """Insert or replace ``snippet`` at a ``# FORGE:<marker>`` site.

    The injection is wrapped in BEGIN / END sentinel comments keyed to
    ``feature_key:marker_name``. Running this twice on the same file replaces
    the existing block in place rather than duplicating — the foundation
    of ``forge update`` idempotency (see B2.4 plan).

    Rules:
      - Marker (the ``# FORGE:<marker>`` line) must appear exactly once.
      - If a BEGIN/END pair with this tag exists, replace the block (lines
        between the two sentinels, inclusive).
      - Otherwise, emit ``BEGIN, <snippet lines>, END`` at the marker
        position (``before`` → above the marker; ``after`` → below).
      - Indentation is inherited from the marker line and applied to the
        sentinel + snippet lines so the block slots into the enclosing
        scope cleanly.
    """
    if not file.is_file():
        raise InjectionError(
            f"Injection target not found: {file}",
            code=INJECTION_TARGET_MISSING,
            context={"file": str(file)},
        )

    needle = marker if marker.startswith(MARKER_PREFIX) else f"{MARKER_PREFIX}{marker}"
    prefix = _comment_prefix(file)
    tag = _sentinel_tag(feature_key, marker)
    begin_needle = f"{MARKER_PREFIX}BEGIN {tag}"
    end_needle = f"{MARKER_PREFIX}END {tag}"

    text = file.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Path 1 — sentinel block already present → replace in place.
    begin_idx = _find_unique_line(lines, begin_needle, file, needle=begin_needle)
    if begin_idx is not None:
        end_idx = _find_unique_line(lines, end_needle, file, needle=end_needle)
        if end_idx is None or end_idx < begin_idx:
            raise InjectionError(
                f"{file}: found BEGIN sentinel for '{tag}' but matching END "
                f"is missing or out of order.",
                code=INJECTION_SENTINEL_CORRUPT,
                context={"file": str(file), "tag": tag},
            )
        # Preserve the BEGIN line's indentation so a regenerated block keeps
        # the same shape as the original marker-aligned one.
        indent = _indent_of(lines[begin_idx])
        fresh = _render_block(indent, prefix, tag, snippet)
        lines = lines[:begin_idx] + [fresh] + lines[end_idx + 1 :]
        file.write_text("".join(lines), encoding="utf-8")
        return

    # Path 2 — fresh injection: find the marker and insert a new block.
    marker_idx = _find_unique_line(lines, needle, file, needle=needle)
    if marker_idx is None:
        raise InjectionError(
            f"Marker '{needle}' not found in {file}. "
            "Add the marker to the base template or check the fragment's inject.yaml.",
            code=INJECTION_MARKER_MISSING,
            context={"file": str(file), "marker": needle},
        )
    indent = _indent_of(lines[marker_idx])
    block = _render_block(indent, prefix, tag, snippet)

    insert_at = marker_idx + 1 if position == "after" else marker_idx
    lines = lines[:insert_at] + [block] + lines[insert_at:]
    file.write_text("".join(lines), encoding="utf-8")
