"""Outbound webhook delivery with HMAC-SHA256 signing.

Each delivery carries three headers the receiver MUST verify:

  * ``X-Webhook-Timestamp``  — RFC 3339 / Unix seconds; reject if older
    than ~5 minutes to limit the replay window.
  * ``X-Webhook-Nonce``      — 128-bit UUID; reject if seen before in the
    freshness window (maintain a short-TTL cache keyed by nonce).
  * ``X-Webhook-Signature``  — ``HMAC-SHA256(secret, timestamp "." nonce
    "." body)``, hex digest.

The nonce closes the within-same-second replay window that a
timestamp-only HMAC leaves open. Delivery is in-process, best-effort —
pair with ``background_tasks`` for retry semantics.
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Any

from app.data.models.webhook import Webhook
from app.domain.webhook import WebhookDeliveryResult

logger = logging.getLogger(__name__)


def _sign(secret: str, body: bytes, timestamp: str, nonce: str) -> str:
    """Return the hex digest of ``HMAC-SHA256(secret, timestamp.nonce.body)``.

    Nonce is included in the signed message so receivers cannot accept a
    replayed (timestamp, body) pair without also matching the nonce — and
    the nonce is expected to be unique per delivery.
    """
    message = timestamp.encode() + b"." + nonce.encode() + b"." + body
    digest = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return digest


def matches_event(webhook: Webhook, event: str) -> bool:
    """An empty ``events`` list means subscribe-all; otherwise fnmatch."""
    if not webhook.events:
        return True
    return any(fnmatch.fnmatch(event, pattern) for pattern in webhook.events)


async def deliver(webhook: Webhook, event: str, payload: dict[str, Any]) -> WebhookDeliveryResult:
    """POST ``payload`` to ``webhook.url`` with an HMAC signature header.

    Returns a ``WebhookDeliveryResult`` regardless of outcome so callers can
    record the attempt uniformly. Never raises — HTTP / signing failures
    surface on the result object.
    """
    start = time.perf_counter()
    try:
        import httpx  # type: ignore
    except ImportError:
        return WebhookDeliveryResult(
            webhook_id=webhook.id,
            status_code=None,
            ok=False,
            error="httpx not installed",
            duration_ms=0,
        )

    body = json.dumps({"event": event, "data": payload}, default=str).encode()
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    signature = _sign(webhook.secret, body, timestamp, nonce)

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": signature,
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Nonce": nonce,
        "X-Webhook-Event": event,
        "X-Webhook-Id": str(webhook.id),
    }
    if webhook.extra_headers:
        headers.update(webhook.extra_headers)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook.url, content=body, headers=headers)
        return WebhookDeliveryResult(
            webhook_id=webhook.id,
            status_code=resp.status_code,
            ok=resp.is_success,
            error=None if resp.is_success else f"http {resp.status_code}",
            duration_ms=int((time.perf_counter() - start) * 1000),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("webhook delivery failed: %s -> %s: %s", event, webhook.url, e)
        return WebhookDeliveryResult(
            webhook_id=webhook.id,
            status_code=None,
            ok=False,
            error=str(e),
            duration_ms=int((time.perf_counter() - start) * 1000),
        )


def generate_secret() -> str:
    """Return a 64-hex-char secret suitable for HMAC signing."""
    return uuid.uuid4().hex + uuid.uuid4().hex
