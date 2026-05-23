/**
 * Redis cache adapter — ``CachePort`` implementation backed by ioredis.
 *
 * Values are stored as JSON; non-serialisable values throw at ``set``
 * time. Cross-replica safe — eviction is governed by Redis's
 * ``maxmemory-policy`` (typically ``allkeys-lru``).
 *
 * Shares the Redis sidecar with queue/rate-limit fragments via the
 * standard ``REDIS_URL`` env var; cache traffic runs on a dedicated DB
 * (default ``/3``) so eviction pressure doesn't clobber queue keysets.
 */

import { Redis } from "ioredis";

import type { CachePort } from "../../ports/cache.js";

const DEFAULT_URL = "redis://redis:6379/3";

function readCacheUrl(): string {
	return process.env.CACHE_REDIS_URL ?? DEFAULT_URL;
}

export class RedisCacheAdapter implements CachePort {
	private readonly client: Redis;

	constructor(url: string = readCacheUrl()) {
		this.client = new Redis(url, {
			maxRetriesPerRequest: null,
			enableReadyCheck: false,
		});
	}

	async get<T = unknown>(key: string): Promise<T | null> {
		const raw = await this.client.get(key);
		if (raw === null) {
			return null;
		}
		try {
			return JSON.parse(raw) as T;
		} catch {
			// Tolerate raw-string writes from ops tools (redis-cli set
			// foo bar) — returning the raw value beats throwing in the
			// middle of a cache read.
			return raw as unknown as T;
		}
	}

	async set<T = unknown>(key: string, value: T, ttlSeconds?: number): Promise<void> {
		if (ttlSeconds !== undefined && ttlSeconds <= 0) {
			await this.client.del(key);
			return;
		}
		const payload = JSON.stringify(value);
		if (ttlSeconds === undefined) {
			await this.client.set(key, payload);
		} else {
			await this.client.set(key, payload, "EX", ttlSeconds);
		}
	}

	async invalidate(key: string): Promise<void> {
		await this.client.del(key);
	}

	async close(): Promise<void> {
		await this.client.quit();
	}
}
