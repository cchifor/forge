"""``platform.*`` features — operator-facing surfaces.

Wave B of the features-reorganization refactor. Covers admin UI,
outbound webhooks, CLI extensions, MCP scaffolds (server + per-frontend
UI components), and the AGENTS.md AI-orientation drop. Object-store
and security namespaces split out into sibling feature dirs since
they're independent option namespaces with their own fragments.
"""

from __future__ import annotations

from forge.features.platform import (  # noqa: F401, E402
    fragments,
    options,
)
