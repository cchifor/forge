"""``airlock.*`` — client for the Airlock sandbox orchestrator (weld-airlock).

Scaffolds the :class:`weld.airlock.AsyncAirlockClient` factory wired
into Dishka DI so handlers obtain sandbox handles without touching the
HTTP layer. The retry policy and correlation-id propagation come from
the SDK; configuration is via ``AIRLOCK_BASE_URL`` + ``AIRLOCK_TOKEN``.

Python-only — the Airlock client SDK is published only for Python.
"""

from __future__ import annotations

from forge.features.airlock import (  # noqa: F401, E402
    fragments,
    options,
)
