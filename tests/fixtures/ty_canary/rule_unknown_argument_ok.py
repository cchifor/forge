# expect: ok
"""Only known keyword arguments produce no diagnostic."""

from __future__ import annotations


def greet(name: str) -> str:
    return f"Hello, {name}"


def caller() -> str:
    return greet(name="ada")
