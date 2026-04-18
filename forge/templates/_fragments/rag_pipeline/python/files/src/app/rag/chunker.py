"""Recursive text chunker.

Splits on paragraph → line → sentence → word boundaries so chunks respect
the natural structure of prose. Defaults target 800 characters per chunk
with 120 characters of overlap — conservative numbers that fit comfortably
inside ``text-embedding-3-small``'s 8191-token limit with plenty of
headroom for headers / boilerplate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkOptions:
    max_chars: int = 800
    overlap_chars: int = 120
    min_chars: int = 40


_PARAGRAPH_SEP = re.compile(r"\n\s*\n")
_LINE_SEP = re.compile(r"\n")
_SENTENCE_SEP = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, options: ChunkOptions | None = None) -> list[str]:
    """Return ordered chunks covering the input text with light overlap.

    - Preserves whole paragraphs when they fit under ``max_chars``.
    - Splits oversized paragraphs on line, then sentence, then word.
    - Trims whitespace but does not otherwise normalize content.
    """
    opts = options or ChunkOptions()
    text = (text or "").strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in _PARAGRAPH_SEP.split(text) if p.strip()]

    units: list[str] = []
    for para in paragraphs:
        if len(para) <= opts.max_chars:
            units.append(para)
            continue
        units.extend(_subdivide(para, opts.max_chars))

    return _apply_overlap(units, opts)


def _subdivide(block: str, max_chars: int) -> list[str]:
    """Split a paragraph-sized block along progressively finer boundaries."""
    pieces: list[str] = []
    for line in _LINE_SEP.split(block):
        line = line.strip()
        if not line:
            continue
        if len(line) <= max_chars:
            pieces.append(line)
            continue
        sentences = [s.strip() for s in _SENTENCE_SEP.split(line) if s.strip()]
        buffer = ""
        for sentence in sentences:
            if len(sentence) > max_chars:
                # Finally fall back to a hard word-level chop.
                for word_chunk in _word_chop(sentence, max_chars):
                    pieces.append(word_chunk)
                continue
            candidate = f"{buffer} {sentence}".strip() if buffer else sentence
            if len(candidate) <= max_chars:
                buffer = candidate
            else:
                if buffer:
                    pieces.append(buffer)
                buffer = sentence
        if buffer:
            pieces.append(buffer)
    return pieces


def _word_chop(text: str, max_chars: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    buf = ""
    for w in words:
        if len(buf) + len(w) + 1 > max_chars:
            if buf:
                chunks.append(buf.strip())
            buf = w
        else:
            buf = f"{buf} {w}".strip() if buf else w
    if buf:
        chunks.append(buf.strip())
    return chunks


def _apply_overlap(units: list[str], opts: ChunkOptions) -> list[str]:
    if opts.overlap_chars <= 0 or len(units) < 2:
        return [u for u in units if len(u) >= opts.min_chars]
    out: list[str] = []
    for i, unit in enumerate(units):
        if i == 0 or opts.overlap_chars == 0:
            out.append(unit)
            continue
        tail = units[i - 1][-opts.overlap_chars :]
        out.append(f"{tail} {unit}".strip())
    return [u for u in out if len(u) >= opts.min_chars]
