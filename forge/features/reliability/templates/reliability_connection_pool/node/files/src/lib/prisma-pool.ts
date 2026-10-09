/**
 * Prisma pool sizing helper — documents the connection_limit env var so
 * the generated Prisma client doesn't saturate under burst traffic.
 *
 * Preserve the legacy URL helper for callers. Prisma 7 uses the pg driver:
 * prismaPoolOptions translates those parameters into native driver settings.
 *
 * Recommended:
 *   connection_limit = min(physical_cores * 2 + 1, 30)
 *   pool_timeout     = 10s
 */

import { databaseConnectionOptions } from "./prisma-options.js";

const DEFAULT_LIMIT = Number(process.env.PRISMA_CONNECTION_LIMIT ?? "20");
const DEFAULT_POOL_TIMEOUT = Number(process.env.PRISMA_POOL_TIMEOUT ?? "10");

export function databaseUrlWithPool(base: string): string {
	const url = new URL(base);
	if (!url.searchParams.has("connection_limit")) {
		url.searchParams.set("connection_limit", String(DEFAULT_LIMIT));
	}
	if (!url.searchParams.has("pool_timeout")) {
		url.searchParams.set("pool_timeout", String(DEFAULT_POOL_TIMEOUT));
	}
	return url.toString();
}

/** Prisma 7 delegates pooling to pg; translate legacy URL/env settings. */
export function prismaPoolOptions(base: string) {
	return databaseConnectionOptions(databaseUrlWithPool(base));
}
