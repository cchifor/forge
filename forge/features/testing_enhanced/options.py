"""``platform.testing_enhanced`` option — failure forensics + coverage registry."""

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
            path="platform.testing_enhanced",
            type=OptionType.BOOL,
            default=False,
            summary="Failure forensics + coverage registry for structured test diagnostics.",
            description="""\
Opt-in testing infrastructure that captures structured failure context
on every test failure (written to ``tests/.failure-context/<test-id>/``)
and ships a ``coverage.json`` registry defining per-module coverage
thresholds.  Failure context includes timestamps, pytest markers, and
CI metadata (GitHub Actions run ID, SHA, ref) for post-mortem debugging
without reproducing locally.

BACKENDS: python
ENDPOINTS: none — test infrastructure only.""",
            category=FeatureCategory.PLATFORM,
            stability="beta",
            enables={True: ("testing_enhanced_python",)},
        )
    )
