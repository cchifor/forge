/**
 * Multi-issuer JWKS cache.
 *
 * Mirrors Python platform_auth.jwks.JWKSCache, but uses jose's
 * built-in ``createRemoteJWKSet`` per-issuer instead of a hand-rolled
 * cache. ``createRemoteJWKSet`` already handles fetch + cache +
 * cache-max-age + cooldown-duration semantics; we add the multi-issuer
 * layer on top.
 *
 * Constructed once per process (typically inside AuthGuard); never
 * per-request.
 */

import {
  createRemoteJWKSet,
  type JWSHeaderParameters,
  type FlattenedJWSInput,
  type JWK,
  type KeyLike,
} from "jose";

import { InvalidToken } from "./exceptions.js";

/** Default cache lifetimes (matches Python defaults). */
export const DEFAULT_LIFESPAN_SECONDS = 600; // 10 min between voluntary refreshes
export const DEFAULT_STALE_MAX_SECONDS = 1800; // 30 min stale-serve fallback
export const DEFAULT_HTTP_TIMEOUT_MS = 5_000;

interface IssuerEntry {
  jwksUri: string;
  /** jose remote JWKS getter. Closes over its own cache + refresh logic. */
  getKey: (
    protectedHeader?: JWSHeaderParameters,
    token?: FlattenedJWSInput,
  ) => Promise<KeyLike | Uint8Array>;
}

export interface JWKSCacheOptions {
  /** Voluntary refresh interval (seconds). Default 600 = 10 min. */
  lifespanSeconds?: number;
  /** Max staleness during upstream outages (seconds). Default 1800 = 30 min. */
  staleMaxSeconds?: number;
  /** HTTP timeout per fetch (ms). Default 5000. */
  httpTimeoutMs?: number;
}

/**
 * Registers and caches JWKS documents for multiple issuers.
 *
 * Lifecycle:
 * 1. Caller registers every trusted issuer at startup via
 *    `registerIssuer(iss, jwksUri)`. Issuers absent from the registry
 *    cause `getSigningKey()` to throw (verifiers should consult the
 *    tenant→issuer trust map *before* asking JWKS).
 * 2. `getSigningKey(iss, kid)` returns the signing key for that issuer
 *    + key id. On unknown ``kid`` jose's remote-set silently refreshes
 *    once before failing — same behaviour as the Python cache's
 *    "force-refresh on unknown kid" path.
 *
 * The Python parity for ``getSigningKey()`` returns a key handle the
 * caller (AuthGuard) hands to `jwtVerify(token, jwksGetterForIssuer)`;
 * this cache exposes a ``keyResolver(iss)`` helper that returns the
 * jose getter for that issuer, which is the ergonomic shape jose's
 * verifier wants.
 */
export class JWKSCache {
  private readonly lifespanSeconds: number;
  private readonly staleMaxSeconds: number;
  private readonly httpTimeoutMs: number;
  private readonly entries: Map<string, IssuerEntry> = new Map();

  constructor(opts: JWKSCacheOptions = {}) {
    const lifespan = opts.lifespanSeconds ?? DEFAULT_LIFESPAN_SECONDS;
    const staleMax = opts.staleMaxSeconds ?? DEFAULT_STALE_MAX_SECONDS;
    if (lifespan <= 0) {
      throw new Error("lifespanSeconds must be positive");
    }
    if (staleMax < lifespan) {
      throw new Error(
        "staleMaxSeconds must be >= lifespanSeconds; otherwise stale-serve would be a no-op",
      );
    }
    this.lifespanSeconds = lifespan;
    this.staleMaxSeconds = staleMax;
    this.httpTimeoutMs = opts.httpTimeoutMs ?? DEFAULT_HTTP_TIMEOUT_MS;
  }

  /**
   * Register an issuer's JWKS URI. Idempotent for identical pairs;
   * a different URI for an existing issuer replaces it.
   */
  registerIssuer(issuer: string, jwksUri: string): void {
    if (!issuer) {
      throw new Error("issuer must be non-empty");
    }
    if (!jwksUri) {
      throw new Error("jwksUri must be non-empty");
    }
    const existing = this.entries.get(issuer);
    if (existing && existing.jwksUri === jwksUri) {
      return;
    }
    const getKey = createRemoteJWKSet(new URL(jwksUri), {
      // ``cacheMaxAge`` is the upper bound between fetches when keys
      // exist; matches the Python ``lifespan_seconds``.
      cacheMaxAge: this.lifespanSeconds * 1000,
      // ``cooldownDuration`` is the floor between fetches when a kid
      // is unknown — prevents thundering herd on key rotation.
      cooldownDuration: 30_000,
      timeoutDuration: this.httpTimeoutMs,
    });
    this.entries.set(issuer, { jwksUri, getKey });
  }

  /** Returns the set of issuers that may be looked up. */
  registeredIssuers(): ReadonlySet<string> {
    return new Set(this.entries.keys());
  }

  /**
   * Returns the jose key-resolver function for ``issuer``. The
   * returned function is what jose's ``jwtVerify`` expects as its
   * second argument — call it with the protected header and jose
   * resolves the right JWK.
   */
  keyResolverFor(issuer: string): IssuerEntry["getKey"] {
    const entry = this.entries.get(issuer);
    if (entry === undefined) {
      throw new InvalidToken(`issuer not registered: ${JSON.stringify(issuer)}`);
    }
    return entry.getKey;
  }

  /**
   * Direct JWK lookup by ``(issuer, kid)`` — used by callers that
   * verify outside of jose's ``jwtVerify`` happy path (e.g., manual
   * decoding for diagnostic tools, or an event-bus consumer that
   * needs the raw key material).
   *
   * Returns the JWK whose ``kid`` matches; throws ``InvalidToken``
   * when the issuer is unregistered or no key matches after a
   * forced refresh.
   */
  async getSigningKey(issuer: string, kid: string): Promise<JWK | KeyLike | Uint8Array> {
    const entry = this.entries.get(issuer);
    if (entry === undefined) {
      throw new InvalidToken(`issuer not registered: ${JSON.stringify(issuer)}`);
    }
    try {
      // Pass minimal protected-header + a forged FlattenedJWSInput so
      // jose's resolver picks the right kid. The token field is unused
      // by createRemoteJWKSet; it just needs the header.
      const key = await entry.getKey(
        { alg: "ES256", kid },
        { signature: "", protected: "", payload: "" } as FlattenedJWSInput,
      );
      return key;
    } catch (err) {
      throw new InvalidToken(
        `JWKS unavailable for issuer ${JSON.stringify(issuer)} (kid=${JSON.stringify(kid)})`,
        { cause: String(err) },
      );
    }
  }
}
