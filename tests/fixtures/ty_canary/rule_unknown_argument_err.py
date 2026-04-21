# expect: error[unknown-argument]
"""ty must flag a keyword argument the callee doesn't accept."""

from __future__ import annotations


def greet(name: str) -> str:
    return f"Hello, {name}"


def caller() -> str:
    # `suffix=` is not a known parameter of greet().
    return greet(name="ada", suffix="!")  # type: ignore[call-arg]
