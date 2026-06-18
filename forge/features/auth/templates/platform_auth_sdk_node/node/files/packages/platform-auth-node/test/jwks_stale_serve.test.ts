/**
 * Regression: JWKSCache stale-serve fallback (audit #18).
 *
 * The cache must keep serving the last-known-good key set during an
 * upstream JWKS/IdP outage for up to `staleMaxSeconds`, then fail. The
 * previous implementation delegated to jose's `createRemoteJWKSet`,
 * which has no stale-on-error fallback, so an outage longer than the
 * refresh interval rejected valid tokens whose kid was already cached —
 * a parity gap vs the Rust + Python caches.
 *
 * Uses an injectable `fetchImpl` (no `globalThis.fetch` override) and a
 * fake clock; exercises only the key resolver, so no token/exp coupling.
 */

import { describe, expect, test, vi } from "vitest";

import { JWKSCache } from "../src/JWKSCache.js";
import { generateTestKeypair } from "../src/testing.js";

const ISSUER = "http://idp.test:5000";
const JWKS_URI = `${ISSUER}/auth/jwks`;

describe("JWKSCache stale-serve", () => {
  test("serves cached key during outage within staleMax, fails beyond it", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    try {
      const keypair = await generateTestKeypair();
      const jwksDoc = keypair.jwks();
      const header = { alg: "ES256", kid: keypair.kid };

      let outage = false;
      let fetchCalls = 0;
      const fetchImpl = vi.fn(async () => {
        fetchCalls += 1;
        if (outage) {
          throw new Error("ECONNREFUSED: JWKS endpoint unreachable");
        }
        return { ok: true, status: 200, json: async () => jwksDoc };
      });

      const cache = new JWKSCache({
        lifespanSeconds: 1,
        staleMaxSeconds: 100,
        fetchImpl,
      });
      cache.registerIssuer(ISSUER, JWKS_URI);
      const resolve = cache.keyResolverFor(ISSUER);

      // Warm the cache — one successful fetch.
      const key1 = await resolve(header);
      expect(key1).toBeDefined();
      expect(fetchCalls).toBe(1);

      // Outage begins. Advance past lifespan (1s) but within staleMax (100s):
      // the refresh is attempted and FAILS, yet the cached key must still serve.
      outage = true;
      vi.setSystemTime(new Date("2026-01-01T00:00:05Z")); // +5s
      const key2 = await resolve(header);
      expect(key2).toBeDefined();
      expect(fetchCalls).toBe(2); // proves a refresh was attempted (and failed)

      // Beyond the stale window: the cache must now fail closed.
      vi.setSystemTime(new Date("2026-01-01T00:02:30Z")); // +150s > staleMax
      await expect(resolve(header)).rejects.toThrow(/JWKS unavailable/);
    } finally {
      vi.useRealTimers();
    }
  });
});
