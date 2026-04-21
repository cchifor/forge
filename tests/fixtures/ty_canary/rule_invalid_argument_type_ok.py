# expect: ok
"""A well-typed call should not produce any diagnostic."""

from __future__ import annotations


def double(n: int) -> int:
    return n + n


def caller() -> int:
    return double(21)
