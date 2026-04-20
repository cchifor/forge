/**
 * Prisma pool sizing helper — documents the connection_limit env var so
 * the generated Prisma client doesn't saturate under burst traffic.
 *
 * Prisma reads ``?connection_limit=N`` directly off ``DATABASE_URL``, so
 * the wiring here is "produce a URL-patching helper" rather than a full
 * pool class. The user's Prisma client picks up the patched URL on boot.
 *
 * Recommended:
 *   connection_limit = min(physical_cores * 2 + 1, 30)
 *   pool_timeout     = 10s
 */

const DEFAULT_LIMIT = Number(process.env.PRISMA_CONNECTION_LIMIT ?? "20")
const DEFAULT_POOL_TIMEOUT = Number(process.env.PRISMA_POOL_TIMEOUT ?? "10")

export function databaseUrlWithPool(base: string): string {
  const url = new URL(base)
  if (!url.searchParams.has("connection_limit")) {
    url.searchParams.set("connection_limit", String(DEFAULT_LIMIT))
  }
  if (!url.searchParams.has("pool_timeout")) {
    url.searchParams.set("pool_timeout", String(DEFAULT_POOL_TIMEOUT))
  }
  return url.toString()
}
