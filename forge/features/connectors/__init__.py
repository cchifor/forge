"""``connectors.*`` — pluggable read/write adapters via weld-connectors.

Wraps :func:`weld.connectors.build_default_connector_registry` so the
service composes its own data-plane adapters (HTTP, FS, SQL, S3, MCP)
from a single registry. Backends are selectable via
``connectors.backends`` — each enabled backend pulls the matching
``weld-connectors[<backend>]`` extra so unused dependencies stay out.

Python-only — the weld-connectors SDK has no Node/Rust port.
"""

from __future__ import annotations

from forge.features.connectors import (  # noqa: F401, E402
    fragments,
    options,
)
