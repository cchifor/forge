"""User-facing options for built-in middleware features.

POC scope: ``middleware.correlation_id`` only.
"""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="middleware.correlation_id",
        type=OptionType.ENUM,
        default="always-on",
        options=("always-on",),  # degenerate single-value enum
        summary="X-Request-ID ingress + ContextVar propagation.",
        description="""\
Every inbound request is tagged with an X-Request-ID header, the value
is stored in a ContextVar so any async task downstream sees it, and the
same ID is echoed back on the response.

This option is always-on — it has no off value. Index the
``correlation_id`` log field in your aggregator to trace a single
request end-to-end across services.

BACKENDS: python
ENDPOINTS: none — ambient context via service.observability.correlation""",
        category=FeatureCategory.OBSERVABILITY,
        enables={"always-on": ("correlation_id",)},
    )
)
