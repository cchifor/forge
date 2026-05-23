/**
 * In-process LRU cache adapter — TTL-aware ``CachePort`` implementation.
 *
 * Single-replica only. Multi-replica deployments should pick the Redis
 * adapter so eviction is consistent across pods.
 *
 * The LRU order is maintained by exploiting ``Map`` insertion order —
 * re-inserting on read bumps the entry to the most-recent end. TTL
 * expiry is checked lazily on read (cheap timestamp compare); a
 * background sweep would be overkill for this tier.
 */

import type { CachePort } from "../../ports/cache.js";

const DEFAULT_MAX_ENTRIES = 1024;

function readMaxEntries(): number {
	const raw = process.env.CACHE_MEMORY_MAX_ENTRIES;
	if (!raw) {
		return DEFAULT_MAX_ENTRIES;
	}
	const parsed = Number.parseInt(raw, 10);
	return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_MAX_ENTRIES;
}

interface Entry {
	value: unknown;
	/** Monotonic-ish epoch-ms deadline; ``null`` means no expiry. */
	expiresAt: number | null;
}

export class MemoryCacheAdapter implements CachePort {
	private readonly maxEntries: number;
	private readonly store = new Map<string, Entry>();

	constructor(options: { maxEntries?: number } = {}) {
		this.maxEntries = options.maxEntries ?? readMaxEntries();
	}

	async get<T = unknown>(key: string): Promise<T | null> {
		const entry = this.store.get(key);
		if (!entry) {
			return null;
		}
		if (entry.expiresAt !== null && Date.now() >= entry.expiresAt) {
			this.store.delete(key);
			return null;
		}
		// LRU bump on read — delete + re-insert moves to the most-recent
		// end of the Map's insertion-order iteration.
		this.store.delete(key);
		this.store.set(key, entry);
		return entry.value as T;
	}

	async set<T = unknown>(key: string, value: T, ttlSeconds?: number): Promise<void> {
		if (ttlSeconds !== undefined && ttlSeconds <= 0) {
			// Write-but-immediately-expired — treat as invalidate.
			this.store.delete(key);
			return;
		}
		const expiresAt = ttlSeconds === undefined ? null : Date.now() + ttlSeconds * 1000;
		this.store.delete(key);
		this.store.set(key, { value, expiresAt });
		while (this.store.size > this.maxEntries) {
			const oldestKey = this.store.keys().next().value;
			if (oldestKey === undefined) {
				break;
			}
			this.store.delete(oldestKey);
		}
	}

	async invalidate(key: string): Promise<void> {
		this.store.delete(key);
	}
}
