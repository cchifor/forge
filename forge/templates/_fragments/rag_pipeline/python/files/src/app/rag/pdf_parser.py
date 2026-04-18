"""Best-effort PDF → text extraction for RAG ingestion.

Uses `pymupdf` (aka `fitz`) — the only hard dependency — to walk pages and
concat their extracted text. Preserves paragraph breaks so the recursive
chunker downstream can still respect document structure. For scanned PDFs
you'll want OCR (Tesseract, Rapid-OCR) before ingestion; this module
treats no-text pages as empty rather than failing the whole document.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text_from_pdf(path: Path | str) -> str:
    """Return concatenated text of every page, joined with blank lines.

    Raises :class:`RuntimeError` if `pymupdf` is not installed — surface the
    missing dependency to the caller so they can show a clean error.
    """
    try:
        import pymupdf  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "pymupdf not installed; add it to your service and re-sync"
        ) from e

    path = Path(path)
    doc = pymupdf.open(str(path))
    try:
        chunks: list[str] = []
        for page in doc:
            try:
                page_text = page.get_text("text")
            except Exception as e:  # noqa: BLE001
                logger.debug("page extract failed: %s", e)
                continue
            if page_text and page_text.strip():
                chunks.append(page_text.strip())
        return "\n\n".join(chunks)
    finally:
        doc.close()


def extract_text_from_bytes(data: bytes, filename: str | None = None) -> str:
    """In-memory PDF parsing — convenience for upload endpoints."""
    try:
        import pymupdf  # type: ignore
    except ImportError as e:
        raise RuntimeError("pymupdf not installed") from e

    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        chunks: list[str] = []
        for page in doc:
            try:
                page_text = page.get_text("text")
            except Exception as e:  # noqa: BLE001
                logger.debug("page extract failed (%s): %s", filename or "?", e)
                continue
            if page_text and page_text.strip():
                chunks.append(page_text.strip())
        return "\n\n".join(chunks)
    finally:
        doc.close()
