# expect: error[invalid-argument-type]
"""ty must flag a call that passes the wrong argument type."""

from __future__ import annotations


def double(n: int) -> int:
    return n + n


def caller() -> int:
    # Pass a str where int is required.
    return double("not an int")  # type: ignore[arg-type]
