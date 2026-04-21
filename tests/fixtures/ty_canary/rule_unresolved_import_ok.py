# expect: ok
"""A resolvable stdlib import should not produce any diagnostic."""

from __future__ import annotations

import json


def sentinel(payload: dict[str, int]) -> str:
    return json.dumps(payload)
