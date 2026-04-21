# expect: ok
"""A correctly-typed return value should not produce any diagnostic."""

from __future__ import annotations


def produces_int() -> int:
    return 42
