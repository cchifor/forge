"""Async client factory for the Airlock sandbox orchestrator.

The :class:`weld.airlock.AsyncAirlockClient` is app-scoped (one per
service) and owns an :class:`httpx.AsyncClient` underneath. The
lifespan handler awaits ``aclose()`` on shutdown so connections drain
cleanly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weld.airlock import DEFAULT_RETRY_POLICY, AsyncAirlockClient

if TYPE_CHECKING:
    from app.core.config.domain import Settings


def build_airlock_client(settings: Settings) -> AsyncAirlockClient:
    return AsyncAirlockClient(
        base_url=settings.airlock.base_url,
        token=settings.airlock.token,
        retry_policy=DEFAULT_RETRY_POLICY,
    )
