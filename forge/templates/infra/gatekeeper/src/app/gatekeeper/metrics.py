# src/app/gatekeeper/metrics.py
"""
Prometheus metrics for the Gatekeeper service.

Defines custom counters and histograms that capture business-level
observability:

* **Authentication outcomes** — per-tenant, per-method (jwt / api_key),
  per-status (success / failed / expired / redirected).
* **Rate-limit rejections** — per-tenant 429 events.
* **Auth request latency** — histogram bucketed for the ``/auth``
  critical path.
* **API key management** — counters for create / revoke operations.

All metrics are exposed via ``GET /metrics`` in standard Prometheus
exposition format and scraped by the cluster Prometheus instance.
"""

from __future__ import annotations

import time as _time

from prometheus_client import Counter, Histogram

# ── Authentication events ───────────────────────────────────────────────────

AUTH_REQUESTS = Counter(
    "gatekeeper_auth_requests_total",
    "Total authentication attempts processed by /auth",
    ["tenant_id", "method", "status"],
)
"""
Labels
------
tenant_id : str
    The resolved tenant slug.
method : str
    ``"jwt"`` | ``"api_key"`` | ``"none"``
status : str
    ``"success"`` | ``"failed"`` | ``"expired_refreshed"`` |
    ``"redirected"`` | ``"rate_limited"`` | ``"invalid_key"`` |
    ``"error"``
"""

# ── Rate-limit rejections ──────────────────────────────────────────────────

RATE_LIMIT_REJECTIONS = Counter(
    "gatekeeper_rate_limit_rejections_total",
    "Total HTTP 429 responses due to tenant quota limits",
    ["tenant_id"],
)

# ── Auth latency ───────────────────────────────────────────────────────────

AUTH_LATENCY = Histogram(
    "gatekeeper_auth_duration_seconds",
    "Latency of the /auth endpoint in seconds",
    ["tenant_id", "method"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

# ── Redis resilience ───────────────────────────────────────────────────────

REDIS_FALLBACK_EVENTS = Counter(
    "gatekeeper_redis_fallback_total",
    "Times the service fell back from Redis to in-memory persistence",
)

REDIS_RECONNECTIONS = Counter(
    "gatekeeper_redis_reconnections_total",
    "Successful Redis reconnections after a fallback period",
)

# ── API-key management ─────────────────────────────────────────────────────

APIKEY_OPERATIONS = Counter(
    "gatekeeper_apikey_operations_total",
    "API key lifecycle operations",
    ["tenant_id", "operation"],
)
"""
Labels
------
operation : str
    ``"created"`` | ``"revoked"`` | ``"listed"``
"""


# ── Auth metrics recorder ─────────────────────────────────────────────────


class AuthMetricsRecorder:
    """
    Tracks auth timing and outcome for a single ``/auth`` request.

    Eliminates the repeated metric-recording boilerplate in the auth
    endpoint by centralising the ``AUTH_REQUESTS`` counter and
    ``AUTH_LATENCY`` histogram updates in one place.
    """

    def __init__(self, tenant: str, method: str = "none") -> None:
        self.tenant = tenant
        self.method = method
        self._t0 = _time.monotonic()

    def record(self, status: str) -> None:
        """Increment the auth counter and observe latency."""
        AUTH_REQUESTS.labels(
            tenant_id=self.tenant, method=self.method, status=status
        ).inc()
        AUTH_LATENCY.labels(tenant_id=self.tenant, method=self.method).observe(
            _time.monotonic() - self._t0
        )
