/**
 * Multi-issuer JWKS cache with stale-serve fallback.
 *
 * Mirrors the Python (``platform_auth.jwks.JWKSCache``) and Rust
 * (``jwks.rs``) caches: fetch each issuer's JWKS document, cache the
 * resolved key set with a fetch timestamp, refresh after
 * ``lifespanSeconds``, and — critically — serve the last-known-good key
 * set for up to ``staleMaxSeconds`` when an upstream refresh fails
 * (IdP / JWKS outage).
 *
 * The previous incarnation delegated entirely to jose's
 * ``createRemoteJWKSet``, which has NO stale-on-error fallback: a JWKS
 * outage longer than ``cacheMaxAge`` rejected otherwise-valid tokens
 * whose ``kid`` was already cached, while the Rust + Python caches kept
 * serving. ``staleMaxSeconds`` was validated and documented but never
 * honoured — a cross-language parity gap. This class now owns the
 * fetch + cache + stale-serve policy; jose's ``createLocalJWKSet`` does
 * the crypto/key-matching over the fetched document.
 */

import {
  createLocalJWKSet,
  errors as joseErrors,
  type FlattenedJWSInput,
  type JSONWebKeySet,
  type JWK,
  type JWSHeaderParameters,
  type KeyLike,
} from "jose";

import { InvalidToken } from "./exceptions.js";

/** Default cache lifetimes (matches Python defaults). */
export const DEFAULT_LIFESPAN_SECONDS = 600; // 10 min between voluntary refreshes
export const DEFAULT_STALE_MAX_SECONDS = 1800; // 30 min stale-serve fallback
export const DEFAULT_HTTP_TIMEOUT_MS = 5_000;

/** A jose key resolver over a static JWKS document. */
type KeyResolver = (
  protectedHeader?: JWSHeaderParameters,
  token?: FlattenedJWSInput,
) => Promise<KeyLike | Uint8Array>;

/** Minimal ``fetch`` shape the cache depends on (injectable for tests). */
export type FetchLike = (
  url: string,
  init?: { signal?: AbortSignal },
) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>;

interface CachedKeys {
  resolve: KeyResolver;
  fetchedAtMs: number;
}

interface IssuerEntry {
  jwksUri: string;
  cache: CachedKeys | null;
  /** In-flight refresh, shared by concurrent arrivals (mirrors Rust's per-issuer refresh lock). */
  inFlight: Promise<void> | null;
}

export interface JWKSCacheOptions {
  /** Voluntary refresh interval (seconds). Default 600 = 10 min. */
  lifespanSeconds?: number;
  /** Max staleness during upstream outages (seconds). Default 1800 = 30 min. */
  staleMaxSeconds?: number;
  /** HTTP timeout per fetch (ms). Default 5000. */
  httpTimeoutMs?: number;
  /** Injectable ``fetch`` (tests). Default ``globalThis.fetch``. */
  fetchImpl?: FetchLike;
}

function isNoMatchingKey(err: unknown): boolean {
  return err instanceof joseErrors.JWKSNoMatchingKey;
}

export class JWKSCache {
  private readonly lifespanMs: number;
  private readonly staleMaxMs: number;
  private readonly httpTimeoutMs: number;
  private readonly fetchImpl: FetchLike;
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
    this.lifespanMs = lifespan * 1000;
    this.staleMaxMs = staleMax * 1000;
    this.httpTimeoutMs = opts.httpTimeoutMs ?? DEFAULT_HTTP_TIMEOUT_MS;
    this.fetchImpl =
      opts.fetchImpl ?? ((url, init) => globalThis.fetch(url, init) as ReturnType<FetchLike>);
  }

  /**
   * Register an issuer's JWKS URI. Idempotent for identical pairs;
   * a different URI for an existing issuer replaces it (drops its cache).
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
    this.entries.set(issuer, { jwksUri, cache: null, inFlight: null });
  }

  /** Returns the set of issuers that may be looked up. */
  registeredIssuers(): ReadonlySet<string> {
    return new Set(this.entries.keys());
  }

  /**
   * Returns the jose key-resolver function for ``issuer`` — the second
   * argument jose's ``jwtVerify`` expects. Resolution applies the
   * fresh-cache fast path, refresh-on-staleness, and stale-serve on
   * upstream failure.
   */
  keyResolverFor(issuer: string): KeyResolver {
    const entry = this.entries.get(issuer);
    if (entry === undefined) {
      throw new InvalidToken(`issuer not registered: ${JSON.stringify(issuer)}`);
    }
    return (protectedHeader, token) => this._resolveKey(issuer, protectedHeader, token);
  }

  /**
   * Direct JWK lookup by ``(issuer, kid)`` — used by callers that verify
   * outside jose's ``jwtVerify`` happy path. Returns the matching key;
   * throws ``InvalidToken`` when the issuer is unregistered or no key
   * matches after a refresh.
   */
  async getSigningKey(issuer: string, kid: string): Promise<JWK | KeyLike | Uint8Array> {
    try {
      return await this._resolveKey(
        issuer,
        { alg: "ES256", kid },
        { signature: "", protected: "", payload: "" } as FlattenedJWSInput,
      );
    } catch (err) {
      if (err instanceof InvalidToken) {
        throw err;
      }
      throw new InvalidToken(
        `JWKS unavailable for issuer ${JSON.stringify(issuer)} (kid=${JSON.stringify(kid)})`,
        { cause: String(err) },
      );
    }
  }

  private async _resolveKey(
    issuer: string,
    protectedHeader?: JWSHeaderParameters,
    token?: FlattenedJWSInput,
  ): Promise<KeyLike | Uint8Array> {
    const entry = this.entries.get(issuer);
    if (entry === undefined) {
      throw new InvalidToken(`issuer not registered: ${JSON.stringify(issuer)}`);
    }

    // Fast path: fresh cache + kid present.
    if (entry.cache !== null && Date.now() - entry.cache.fetchedAtMs < this.lifespanMs) {
      try {
        return await entry.cache.resolve(protectedHeader, token);
      } catch (err) {
        // A missing kid on a fresh cache means key rotation — fall through
        // and refresh. Any other error is a real verification failure.
        if (!isNoMatchingKey(err)) {
          throw err;
        }
      }
    }

    // Slow path: refresh (deduped across concurrent arrivals), then resolve
    // from the (possibly stale-served) cache.
    await this._refresh(entry);
    if (entry.cache === null) {
      throw new InvalidToken(`JWKS unavailable for issuer ${JSON.stringify(issuer)}`);
    }
    try {
      return await entry.cache.resolve(protectedHeader, token);
    } catch (err) {
      if (isNoMatchingKey(err)) {
        throw new InvalidToken(
          `unknown signing key for issuer ${JSON.stringify(issuer)} (JWKS refreshed)`,
        );
      }
      throw err;
    }
  }

  /**
   * Fetch + replace the cache. On fetch failure, keep the existing cache
   * if it is within the stale-serve window (the fix); otherwise propagate.
   * Concurrent callers share one in-flight fetch.
   */
  private async _refresh(entry: IssuerEntry): Promise<void> {
    if (entry.inFlight !== null) {
      return entry.inFlight;
    }
    const run = (async () => {
      const now = Date.now();
      try {
        const doc = await this._fetchJwks(entry.jwksUri);
        entry.cache = { resolve: createLocalJWKSet(doc), fetchedAtMs: now };
      } catch (err) {
        // Stale-serve: keep the last-known-good key set while inside the
        // staleness window. Outside it (or with no cache), fail.
        if (entry.cache !== null && now - entry.cache.fetchedAtMs < this.staleMaxMs) {
          return;
        }
        throw new InvalidToken(
          `JWKS unavailable for issuer ${JSON.stringify(entry.jwksUri)} and stale window expired`,
          { cause: String(err) },
        );
      }
    })();
    entry.inFlight = run;
    try {
      await run;
    } finally {
      entry.inFlight = null;
    }
  }

  private async _fetchJwks(jwksUri: string): Promise<JSONWebKeySet> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.httpTimeoutMs);
    try {
      const resp = await this.fetchImpl(jwksUri, { signal: controller.signal });
      if (!resp.ok) {
        throw new Error(`JWKS endpoint ${JSON.stringify(jwksUri)} returned HTTP ${resp.status}`);
      }
      const doc = (await resp.json()) as JSONWebKeySet | null;
      if (doc === null || typeof doc !== "object" || !Array.isArray(doc.keys)) {
        throw new Error(`JWKS endpoint ${JSON.stringify(jwksUri)} returned a document without 'keys'`);
      }
      return doc;
    } finally {
      clearTimeout(timer);
    }
  }
}
