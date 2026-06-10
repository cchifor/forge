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
import ipaddress
import json
import logging
import os
import socket
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from app.data.models.webhook import Webhook
from app.domain.webhook import WebhookDeliveryResult

logger = logging.getLogger(__name__)


class WebhookUrlError(ValueError):
    """Raised when a webhook target URL is rejected by the SSRF guard."""


def _is_dev() -> bool:
    env = os.environ.get("ENV", os.environ.get("ENVIRONMENT", "production")).strip().lower()
    return env in {"development", "dev", "test", "testing", "local", "ci"}


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Block any address that could reach internal infrastructure: loopback,
    RFC1918 / unique-local private ranges, link-local (incl. the 169.254.169.254
    cloud-metadata endpoint), multicast, reserved, and the unspecified
    address. IPv4-mapped IPv6 is unwrapped first so ``::ffff:127.0.0.1`` can't
    sneak past."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_outbound_url(url: str) -> None:
    """Reject webhook targets that point at internal/non-public hosts (SSRF).

    Enforced at BOTH create time (fast feedback) and fire time (the
    authoritative check, since DNS can change between the two). Requires an
    ``https`` scheme in a production posture; ``http`` is tolerated only in a
    dev/test environment. Resolves the host and blocks if ANY resolved
    address is internal. Raises :class:`WebhookUrlError` on rejection.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise WebhookUrlError(f"unsupported URL scheme {scheme!r}; use https")
    if scheme == "http" and not _is_dev():
        raise WebhookUrlError("http webhook targets are not allowed in production; use https")
    host = parsed.hostname
    if not host:
        raise WebhookUrlError("webhook URL has no host")

    # A literal IP bypasses DNS — check it directly. Otherwise resolve every
    # address the host maps to and block if any is internal.
    candidates: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    try:
        candidates.append(ipaddress.ip_address(host))
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if scheme == "https" else 80))
        except socket.gaierror as e:
            raise WebhookUrlError(f"could not resolve webhook host {host!r}") from e
        for info in infos:
            addr = info[4][0]
            try:
                candidates.append(ipaddress.ip_address(addr.split("%", 1)[0]))
            except ValueError:
                continue
    if not candidates:
        raise WebhookUrlError(f"webhook host {host!r} resolved to no usable address")
    for ip in candidates:
        if _ip_is_blocked(ip):
            raise WebhookUrlError(
                f"webhook host {host!r} resolves to a non-public address ({ip}); refused"
            )


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

    # Authoritative SSRF check, at the moment of the request (DNS may have
    # changed since the webhook was created).
    try:
        validate_outbound_url(webhook.url)
    except WebhookUrlError as e:
        return WebhookDeliveryResult(
            webhook_id=webhook.id,
            status_code=None,
            ok=False,
            error=f"refused: {e}",
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
        # follow_redirects=False is httpx's default; pin it explicitly so a
        # 3xx to an internal host can't bypass the SSRF guard above.
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
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
