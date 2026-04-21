# expect: ok
"""All required arguments present should produce no diagnostic."""

from __future__ import annotations


def greet(name: str, suffix: str) -> str:
    return f"Hello, {name}{suffix}"


def caller() -> str:
    return greet("ada", "!")
