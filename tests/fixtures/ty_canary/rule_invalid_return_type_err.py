# expect: error[invalid-return-type]
"""ty must flag a function that returns an incompatible type."""

from __future__ import annotations


def produces_int() -> int:
    # Returns a str where the signature promises int.
    return "not an int"  # type: ignore[return-value]
