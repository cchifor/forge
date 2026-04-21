# expect: ok
"""ty should handle generic Protocol types correctly.

forge uses Protocol for its port abstractions (LLM, queue, vector store).
A regression that mis-infers Protocol bounds would make port registration
tests fail in confusing ways.

Uses the pre-3.12 ``TypeVar`` + ``Generic`` / ``Protocol`` pattern since
forge still supports Python 3.11.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

T = TypeVar("T")


class Store(Protocol[T]):
    def put(self, key: str, value: T) -> None: ...
    def get(self, key: str) -> T | None: ...


class StringStore:
    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def put(self, key: str, value: str) -> None:
        self._d[key] = value

    def get(self, key: str) -> str | None:
        return self._d.get(key)


def consume(store: Store[str]) -> str | None:
    store.put("k", "v")
    return store.get("k")


def driver() -> str | None:
    return consume(StringStore())
