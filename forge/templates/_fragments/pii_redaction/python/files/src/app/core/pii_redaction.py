"""PII-redacting logging filter.

Attached to the root logger at lifecycle startup. Scrubs common high-value
PII and secret shapes from log records (both the formatted message and any
string fields in ``extra=``). Regex-based — keeps false-positive rate low by
using anchor patterns rather than free-form wildcards.

Install via :func:`install_pii_filter`; it is idempotent.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

# ASCII-only email regex. Deliberately stricter than RFC 5321 to keep
# false-positive rate down on things like "foo@ bar" split across words.
_EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b")

# Bearer / JWT-style tokens carried in HTTP headers or log lines.
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._\-]{16,}")

# Common API-key prefixes (OpenAI, Anthropic, Google). Add more as needed.
_API_KEY_RE = re.compile(
    r"\b("
    r"sk-[A-Za-z0-9_-]{16,}"
    r"|sk-ant-[A-Za-z0-9_-]{16,}"
    r"|AIza[A-Za-z0-9_-]{20,}"
    r"|hf_[A-Za-z0-9]{16,}"
    r")\b"
)

# Generic password=foo / api_key="bar" pairs.
_KV_SECRET_RE = re.compile(
    r"(?i)\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"]?([^\s'\",;}]+)"
)


class PiiRedactionFilter(logging.Filter):
    """Scrubs emails, bearer tokens, API keys, and key=value secret pairs."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._scrub(str(record.getMessage()))
        # getMessage() already formatted args, so clear them to avoid re-format.
        record.args = None
        for key, value in list(vars(record).items()):
            if isinstance(value, str) and key not in ("msg", "levelname", "name", "pathname"):
                setattr(record, key, self._scrub(value))
        return True

    @staticmethod
    def _scrub(text: str) -> str:
        text = _EMAIL_RE.sub("[email]", text)
        text = _BEARER_RE.sub("bearer [redacted]", text)
        text = _API_KEY_RE.sub("[api-key]", text)
        text = _KV_SECRET_RE.sub(
            lambda m: m.group(0).replace(m.group(1), "[redacted]"),
            text,
        )
        return text


def install_pii_filter(loggers: Iterable[str] = ("",)) -> None:
    """Attach a single filter instance to the named loggers (root by default).

    Idempotent — calling twice won't stack duplicate filters.
    """
    filt = PiiRedactionFilter()
    for name in loggers:
        lg = logging.getLogger(name)
        if any(isinstance(f, PiiRedactionFilter) for f in lg.filters):
            continue
        lg.addFilter(filt)
