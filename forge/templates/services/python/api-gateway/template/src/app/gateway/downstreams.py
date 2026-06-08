"""Downstream-service registry for the API gateway.

Downstream services are declared to the gateway through environment variables
of the form ``INTERNAL_SERVICE_URL_<NAME>``, where ``<NAME>`` is the
upper-cased service name. These are injected into the gateway container at
compose-synthesis time (P4.2), e.g.::

    INTERNAL_SERVICE_URL_KNOWLEDGE=http://knowledge:5000
    INTERNAL_SERVICE_URL_BILLING=http://billing:5001

are exposed by this module as::

    {"knowledge": "http://knowledge:5000", "billing": "http://billing:5001"}

The environment is read on every call (not cached at import time) so the map
reflects the live process environment and stays testable. Pure stdlib — no
third-party dependency.
"""

from __future__ import annotations

import os

#: Prefix for the per-downstream URL environment variables.
_ENV_PREFIX = "INTERNAL_SERVICE_URL_"


def downstream_map() -> dict[str, str]:
    """Return ``{service_name_lower: internal_url}`` from the environment.

    Reads every ``INTERNAL_SERVICE_URL_<NAME>`` variable currently set,
    lower-casing ``<NAME>`` for the registry key. Empty values are skipped so a
    declared-but-blank variable doesn't register an unreachable service.
    """
    services: dict[str, str] = {}
    for key, value in os.environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        url = value.strip()
        if not url:
            continue
        name = key[len(_ENV_PREFIX) :].lower()
        if name:
            services[name] = url
    return services


def resolve_downstream(service: str) -> str | None:
    """Return the internal URL for ``service`` (case-insensitive), or ``None``."""
    return downstream_map().get(service.lower())
