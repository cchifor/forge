# expect: error[missing-argument]
"""ty must flag a call that omits a required positional argument."""

from __future__ import annotations


def greet(name: str, suffix: str) -> str:
    return f"Hello, {name}{suffix}"


def caller() -> str:
    # Missing the required `suffix` argument.
    return greet("ada")  # type: ignore[call-arg]
