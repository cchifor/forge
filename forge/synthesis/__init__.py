"""Phase 4 — multi-service platform synthesis.

This package owns the *computation* of the cross-service service-to-service
(S2S) auth graph that ties multiple backends together: per-service client
id / secret / audiences + inter-service URLs + the shared OIDC issuer / realm.

The computation is pure and deterministic (no I/O, no clock, no randomness)
so two ``forge new`` runs with the same config produce byte-identical output
once the renderers consume it (P4.2). When multi-service synthesis is not
active the entry point returns ``None`` and downstream renderers behave
exactly as before — preserving the golden byte-identity contract.
"""

from __future__ import annotations

from forge.synthesis.platform import (
    PlatformSynthesis,
    ServiceClient,
    compute_platform_synthesis,
)

__all__ = [
    "PlatformSynthesis",
    "ServiceClient",
    "compute_platform_synthesis",
]
