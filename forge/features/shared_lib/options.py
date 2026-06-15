"""``platform.shared_lib`` option — shared Python package scaffold."""

from __future__ import annotations

from forge.api import ForgeAPI
from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
)


def register_all(api: ForgeAPI) -> None:
    api.add_option(
        Option(
            path="platform.shared_lib",
            type=OptionType.BOOL,
            default=False,
            summary="Scaffold a shared Python package in packages/ for cross-backend code reuse.",
            description="""\
Drops a ready-to-import ``shared`` Python package at
``<project>/packages/shared/`` with Pydantic domain models, a utilities
namespace, and smoke tests. Every Python backend can reference it as
a ``[tool.uv.sources]`` path dependency for zero-publish local
development.

Use this when multiple backends need to share value objects, domain
models, or pure-logic helpers without duplicating code across services.

BACKENDS: python
ENDPOINTS: none — library only.""",
            category=FeatureCategory.PLATFORM,
            enables={True: ("shared_lib_python",)},
        )
    )
