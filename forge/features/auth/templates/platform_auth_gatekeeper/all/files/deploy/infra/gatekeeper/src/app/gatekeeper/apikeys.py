# src/app/gatekeeper/apikeys.py
"""
API key validation for machine-to-machine authentication.

Keys are stored in Redis as ``apikey:<sha256_hash>`` → JSON payload.
The Gatekeeper hashes an incoming ``X-API-Key`` header with SHA-256 and
does a single ``GET`` against Redis to validate it.

Key format (Stripe-style):
    ``<env>_<tenant_id>_<random_secret>``
    e.g. ``live_tenantA_8f92a3b1c4…``
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass

from app.gatekeeper.redis import get_redis

logger = logging.getLogger(__name__)

# Redis key prefix
_KEY_PREFIX = "apikey"


@dataclass(frozen=True, slots=True)
class APIKeyRecord:
    """Deserialized API key metadata stored in Redis."""

    key_id: str
    tenant_id: str
    name: str
    roles: list[str]
    owner: str


def cache_subject(record: APIKeyRecord) -> str:
    """Stable per-credential identity for the internal-token cache key.

    Derived from ``(tenant_id, key_id)`` — NOT ``owner`` — so two keys
    created by the same admin (or two keys that happen to share an
    ``owner`` value across tenants) never collapse onto one cached
    internal JWT. Without this, the first key's bearer (its roles and
    tenant) would be served to every later request under the same owner.
    """
    return f"{record.tenant_id}:{record.key_id}"


# ── Hashing ─────────────────────────────────────────────────────────────────


def hash_api_key(plain_key: str) -> str:
    """Return the SHA-256 hex digest of *plain_key*."""
    return hashlib.sha256(plain_key.encode()).hexdigest()


# ── Key generation ──────────────────────────────────────────────────────────


def generate_api_key(tenant_id: str, env: str = "live") -> tuple[str, str]:
    """
    Generate a new API key and return ``(plain_text_key, key_hash)``.

    The plain-text key is shown to the user **exactly once**.
    Only the SHA-256 hash is persisted.
    """
    raw_secret = secrets.token_urlsafe(32)
    plain_text_key = f"{env}_{tenant_id}_{raw_secret}"
    key_hash = hash_api_key(plain_text_key)
    return plain_text_key, key_hash


def key_prefix(plain_key: str, extra_chars: int = 4) -> str:
    """
    Return a short prefix suitable for display (e.g. ``live_tenantA_8f92``).

    Parameters
    ----------
    plain_key:
        The full plain-text API key.
    extra_chars:
        How many characters of the random part to include.
    """
    # Find the third underscore (after env_tenant_)
    parts = plain_key.split("_", 2)
    if len(parts) < 3:
        return plain_key[:12]
    base = f"{parts[0]}_{parts[1]}_"
    return f"{base}{parts[2][:extra_chars]}…"


# ── Redis operations ────────────────────────────────────────────────────────


def _redis_key(key_hash: str) -> str:
    return f"{_KEY_PREFIX}:{key_hash}"


async def store_api_key(
    key_hash: str,
    *,
    key_id: str,
    tenant_id: str,
    name: str,
    roles: list[str],
    owner: str,
) -> None:
    """Persist the hashed key metadata in Redis."""
    r = get_redis()
    payload = json.dumps(
        {
            "key_id": key_id,
            "tenant_id": tenant_id,
            "name": name,
            "roles": roles,
            "owner": owner,
        }
    )
    await r.set(_redis_key(key_hash), payload)
    # Also maintain a per-tenant index so we can list / revoke keys
    await r.sadd(f"apikeys_by_tenant:{tenant_id}", key_hash)


async def validate_api_key(plain_key: str) -> APIKeyRecord | None:
    """
    Validate an incoming API key against Redis.

    Returns the :class:`APIKeyRecord` on success, or ``None`` if the key
    is unknown / revoked.
    """
    r = get_redis()
    key_hash = hash_api_key(plain_key)
    raw = await r.get(_redis_key(key_hash))
    if raw is None:
        return None

    try:
        data = json.loads(raw)
        return APIKeyRecord(
            key_id=data["key_id"],
            tenant_id=data["tenant_id"],
            name=data["name"],
            roles=data["roles"],
            owner=data["owner"],
        )
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Corrupt API key record in Redis: %s", exc)
        return None


async def revoke_api_key(key_hash: str, tenant_id: str) -> bool:
    """
    Remove an API key from Redis **iff it belongs to** *tenant_id*.

    Returns ``True`` only when the key existed, was owned by ``tenant_id``,
    and was deleted; ``False`` otherwise (unknown key, corrupt record, or a
    key owned by a different tenant).

    The ownership check is mandatory: the key hash is the only thing the
    caller supplies, so deleting on the hash alone would let an admin of one
    tenant revoke another tenant's key by knowing/guessing its hash
    (cross-tenant IDOR). We load the record first and compare its stored
    ``tenant_id`` before deleting.
    """
    r = get_redis()
    raw = await r.get(_redis_key(key_hash))
    if raw is None:
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Corrupt record — refuse to delete on an unverifiable owner.
        logger.warning("Corrupt API key record on revoke: hash=%s", key_hash[:12])
        return False
    if data.get("tenant_id") != tenant_id:
        # Belongs to another tenant: do not touch its key or its index.
        logger.warning(
            "Cross-tenant API key revoke blocked: hash=%s requesting_tenant=%s",
            key_hash[:12],
            tenant_id,
        )
        return False
    deleted = await r.delete(_redis_key(key_hash))
    await r.srem(f"apikeys_by_tenant:{tenant_id}", key_hash)
    return deleted > 0


async def list_api_keys(tenant_id: str) -> list[dict]:
    """
    Return metadata for all active API keys belonging to *tenant_id*.

    The actual secret is never stored in Redis, so this is safe to expose.
    """
    r = get_redis()
    hashes = await r.smembers(f"apikeys_by_tenant:{tenant_id}")
    results: list[dict] = []
    for h in hashes:
        raw = await r.get(_redis_key(h))
        if raw is None:
            # Key was deleted but index wasn't cleaned up
            await r.srem(f"apikeys_by_tenant:{tenant_id}", h)
            continue
        try:
            data = json.loads(raw)
            data["key_hash"] = h
            results.append(data)
        except (json.JSONDecodeError, KeyError):
            continue
    return results
