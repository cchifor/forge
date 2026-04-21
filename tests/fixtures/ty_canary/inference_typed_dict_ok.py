# expect: ok
"""ty should infer TypedDict access correctly.

forge uses TypedDicts in places like the provenance manifest and the CLI
JSON envelope; a ty regression that breaks inference here would break our
real code silently.
"""

from __future__ import annotations

from typing import TypedDict


class Envelope(TypedDict):
    error: str
    code: str
    hint: str | None


def extract(e: Envelope) -> str:
    return e["code"]


def build() -> Envelope:
    return {"error": "boom", "code": "FORGE_ERROR", "hint": None}
