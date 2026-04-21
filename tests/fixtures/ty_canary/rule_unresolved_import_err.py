# expect: error[unresolved-import]
"""ty must flag an import that doesn't resolve in the environment."""

from __future__ import annotations

import this_module_definitely_does_not_exist_12345  # type: ignore[import-not-found]


def sentinel() -> object:
    return this_module_definitely_does_not_exist_12345.anything
