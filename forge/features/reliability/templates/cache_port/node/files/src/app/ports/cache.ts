/**
 * Cache port — capability contract for generic key/value caching.
 *
 * Distinct from the response-cache middleware (HTTP-shape keying);
 * this is the generic K/V surface used for idempotency-key dedupe,
 * LLM-response memoization, and denormalized read caches.
 *
 * Adapters live under `app/adapters/cache/<provider>.ts`. The port's
 * surface is intentionally minimal: ``get`` / ``set`` (with optional
 * TTL) / ``invalidate``. Bulk and pattern-match operations are
 * provider-specific and stay inside adapters.
 *
 * Mirror of the Python ``app.ports.cache.CachePort`` Protocol — values
 * are JSON-serialisable and the contract is identical across the
 * three backends.
 */

export interface CachePort {
	/** Return the cached value for ``key`` or ``null`` if missing or expired. */
	get<T = unknown>(key: string): Promise<T | null>;

	/**
	 * Store ``value`` under ``key``.
	 *
	 * ``ttlSeconds`` undefined means "no expiry" — the entry lives until
	 * explicitly invalidated or evicted by the adapter's own pressure
	 * policy (LRU for in-memory, ``maxmemory-policy`` for Redis).
	 * ``ttlSeconds <= 0`` is treated as an immediate invalidate.
	 */
	set<T = unknown>(key: string, value: T, ttlSeconds?: number): Promise<void>;

	/** Drop ``key`` from the cache. Idempotent — missing key is not an error. */
	invalidate(key: string): Promise<void>;
}
