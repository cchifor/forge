/**
 * S2SClient — outbound service-to-service auth.
 *
 * Mirrors Python `platform_auth.s2s_client.S2SClient`. Each instance
 * targets a single downstream audience. Obtains an audience-restricted
 * bearer via OAuth2 `client_credentials` (machine identity) or RFC 8693
 * token-exchange (on-behalf-of a user), caches it until shortly before
 * expiry, and attaches it to outbound HTTP calls via `Authorization:
 * Bearer <token>`.
 *
 * Construction:
 *
 * ```ts
 * const workflowToKnowledge = new S2SClient({
 *   audience: "svc-knowledge",
 *   tokenEndpoint: "http://gatekeeper:5000/auth/token",
 *   clientId: "svc-workflow",
 *   clientSecret: process.env.WORKFLOW_GATEKEEPER_SECRET!,
 * });
 * ```
 *
 * Usage in a request handler:
 *
 * ```ts
 * const response = await workflowToKnowledge.get(
 *   "http://knowledge.svc/api/items",
 *   { onBehalfOf: req.headers.authorization?.slice("Bearer ".length) },
 * );
 * ```
 *
 * Without `onBehalfOf`, the call uses `client_credentials` and the
 * downstream sees a machine-identity token (no `sub`). With it, the
 * call uses RFC 8693 token-exchange and the downstream sees the user's
 * identity preserved plus `act` recording this service as the actor.
 */

import { LRUCache } from "lru-cache";

import { S2SAuthError } from "./exceptions.js";

// Token-exchange grant + token type identifiers per RFC 8693.
const _GRANT_CLIENT_CREDENTIALS = "client_credentials";
const _GRANT_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange";
const _TOKEN_TYPE_ACCESS = "urn:ietf:params:oauth:token-type:access_token";

/** Cache key for the client_credentials token (no subject). */
const _CLIENT_CREDENTIALS_KEY = "__client_credentials__";

/** Refresh cached tokens this many seconds before their natural expiry. */
export const DEFAULT_SAFETY_MARGIN_SECONDS = 60;

export const DEFAULT_HTTP_TIMEOUT_MS = 10_000;
export const DEFAULT_MAX_CACHE_ENTRIES = 1024;

interface CachedToken {
  token: string;
  /** Monotonic milliseconds — when this token's TTL elapses (minus safety margin). */
  expiresAtMs: number;
}

export interface CacheStats {
  hits: number;
  misses: number;
  /** Hit-rate as a fraction in `[0, 1]`. Returns 0 when no calls yet. */
  hitRate: number;
}

export interface S2SClientOptions {
  /** Required: downstream audience this client targets. */
  audience: string;
  /** Required: Gatekeeper's `/auth/token` URL. */
  tokenEndpoint: string;
  /** Required: this service's registered client_id. */
  clientId: string;
  /** Required: argon2id-hashed secret pre-shared with Gatekeeper. */
  clientSecret: string;
  /** Optional: max cached tokens before LRU eviction. Default 1024. */
  maxCacheEntries?: number;
  /** Optional: refresh tokens this many seconds before their `exp`. Default 60. */
  safetyMarginSeconds?: number;
  /** Optional: HTTP timeout per call (ms). Default 10000. */
  requestTimeoutMs?: number;
}

export interface RequestOptions extends RequestInit {
  /**
   * Optional: when provided, performs RFC 8693 token-exchange so the
   * downstream sees the user's identity + this service as the actor.
   * Pass the *raw* user bearer token (without the `Bearer ` prefix).
   */
  onBehalfOf?: string;
  /**
   * Optional: tenant id for multi-tenant `client_credentials` scoping.
   * Platform extension to RFC 6749 §4.4 — Gatekeeper accepts this
   * field to mint a tenant-scoped machine token. Ignored on
   * token-exchange (the subject_token's tenant wins).
   */
  tenantId?: string;
}

/** Audience-restricted outbound HTTP client. */
export class S2SClient {
  private readonly audience: string;
  private readonly tokenEndpoint: string;
  private readonly clientId: string;
  private readonly clientSecret: string;
  private readonly maxCache: number;
  private readonly safetyMarginSeconds: number;
  private readonly requestTimeoutMs: number;
  private readonly tokens: LRUCache<string, CachedToken>;
  private readonly inflight: Map<string, Promise<CachedToken>> = new Map();
  private hits = 0;
  private misses = 0;

  constructor(options: S2SClientOptions) {
    if (!options.audience) {
      throw new Error("audience must be non-empty");
    }
    if (!options.tokenEndpoint) {
      throw new Error("tokenEndpoint must be non-empty");
    }
    if (!options.clientId) {
      throw new Error("clientId must be non-empty");
    }
    if (!options.clientSecret) {
      throw new Error("clientSecret must be non-empty");
    }
    const maxCache = options.maxCacheEntries ?? DEFAULT_MAX_CACHE_ENTRIES;
    if (maxCache <= 0) {
      throw new Error("maxCacheEntries must be positive");
    }
    const safetyMargin = options.safetyMarginSeconds ?? DEFAULT_SAFETY_MARGIN_SECONDS;
    if (safetyMargin < 0) {
      throw new Error("safetyMarginSeconds must be non-negative");
    }
    this.audience = options.audience;
    this.tokenEndpoint = options.tokenEndpoint;
    this.clientId = options.clientId;
    this.clientSecret = options.clientSecret;
    this.maxCache = maxCache;
    this.safetyMarginSeconds = safetyMargin;
    this.requestTimeoutMs = options.requestTimeoutMs ?? DEFAULT_HTTP_TIMEOUT_MS;
    this.tokens = new LRUCache<string, CachedToken>({ max: this.maxCache });
  }

  /** Primary audience this client targets. */
  get targetAudience(): string {
    return this.audience;
  }

  /**
   * Return a cached or freshly-obtained token for this client's audience.
   *
   * With `onBehalfOf=<userToken>`, performs RFC 8693 token-exchange:
   * the returned token preserves the user's `sub` and tenant, with
   * `act` recording this service. Without it, performs a
   * `client_credentials` grant for a machine-identity token.
   *
   * Throws `S2SAuthError` on token-endpoint failure.
   */
  async getToken(opts: { onBehalfOf?: string; tenantId?: string } = {}): Promise<string> {
    const cacheKey = this.cacheKey(opts.onBehalfOf, opts.tenantId);
    const cached = this.tokens.get(cacheKey);
    const nowMs = Date.now();
    if (cached && cached.expiresAtMs > nowMs) {
      this.hits += 1;
      return cached.token;
    }

    // Single-flight: if another caller is already fetching for the
    // same key, await their result instead of duplicating the request.
    const existing = this.inflight.get(cacheKey);
    if (existing) {
      const fresh = await existing;
      this.hits += 1;
      return fresh.token;
    }

    this.misses += 1;
    const fetchPromise = this.fetchToken(opts.onBehalfOf, opts.tenantId);
    this.inflight.set(cacheKey, fetchPromise);
    try {
      const fresh = await fetchPromise;
      this.tokens.set(cacheKey, fresh);
      return fresh.token;
    } finally {
      this.inflight.delete(cacheKey);
    }
  }

  /**
   * Drop the cached token for this subject; the next call refetches.
   * Useful when the downstream returned 401 (token might be revoked
   * upstream while still inside our cache window).
   */
  invalidate(opts: { onBehalfOf?: string; tenantId?: string } = {}): void {
    this.tokens.delete(this.cacheKey(opts.onBehalfOf, opts.tenantId));
  }

  /** Drop every cached token. Use sparingly. */
  clearCache(): void {
    this.tokens.clear();
  }

  cacheStats(): CacheStats {
    const total = this.hits + this.misses;
    return {
      hits: this.hits,
      misses: this.misses,
      hitRate: total === 0 ? 0 : this.hits / total,
    };
  }

  // ---------------------------------------------------------------- HTTP API

  /**
   * Send an authenticated request.
   *
   * On a 401 response we drop the cached token and retry once — the
   * downstream may have rotated keys or revoked the token while it
   * was still in our cache.
   */
  async request(method: string, url: string, options: RequestOptions = {}): Promise<Response> {
    const { onBehalfOf, tenantId, headers, ...init } = options;
    const baseHeaders = new Headers(headers);

    let token = await this.getToken({ onBehalfOf, tenantId });
    baseHeaders.set("Authorization", `Bearer ${token}`);

    let response = await this.doFetch(method, url, baseHeaders, init);
    if (response.status === 401) {
      // Stale token — refetch and try once more.
      this.invalidate({ onBehalfOf, tenantId });
      token = await this.getToken({ onBehalfOf, tenantId });
      baseHeaders.set("Authorization", `Bearer ${token}`);
      response = await this.doFetch(method, url, baseHeaders, init);
    }
    return response;
  }

  async get(url: string, options?: RequestOptions): Promise<Response> {
    return this.request("GET", url, options);
  }

  async post(url: string, options?: RequestOptions): Promise<Response> {
    return this.request("POST", url, options);
  }

  async put(url: string, options?: RequestOptions): Promise<Response> {
    return this.request("PUT", url, options);
  }

  async patch(url: string, options?: RequestOptions): Promise<Response> {
    return this.request("PATCH", url, options);
  }

  async delete(url: string, options?: RequestOptions): Promise<Response> {
    return this.request("DELETE", url, options);
  }

  // ---------------------------------------------------------------- internals

  private async doFetch(
    method: string,
    url: string,
    headers: Headers,
    init: RequestInit,
  ): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.requestTimeoutMs);
    try {
      return await fetch(url, {
        ...init,
        method,
        headers,
        signal: init.signal ?? controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
  }

  private cacheKey(onBehalfOf: string | undefined, tenantId: string | undefined): string {
    const suffix = tenantId ? `:tenant:${tenantId}` : "";
    if (onBehalfOf === undefined) {
      return _CLIENT_CREDENTIALS_KEY + suffix;
    }
    // Prefer the subject token's `jti` so two on-behalf-of calls for
    // the same user share a cache entry. Fall back to a hash so we
    // never store the raw token as a Map key.
    const jti = unverifiedJti(onBehalfOf);
    if (jti !== null) {
      return `obo:jti:${jti}${suffix}`;
    }
    return `obo:hash:${shortHash(onBehalfOf)}${suffix}`;
  }

  private async fetchToken(
    onBehalfOf: string | undefined,
    tenantId: string | undefined,
  ): Promise<CachedToken> {
    const params = new URLSearchParams();
    params.set("client_id", this.clientId);
    params.set("client_secret", this.clientSecret);
    params.set("audience", this.audience);
    if (onBehalfOf === undefined) {
      params.set("grant_type", _GRANT_CLIENT_CREDENTIALS);
      if (tenantId !== undefined) {
        params.set("tenant_id", tenantId);
      }
    } else {
      params.set("grant_type", _GRANT_TOKEN_EXCHANGE);
      params.set("subject_token", onBehalfOf);
      params.set("subject_token_type", _TOKEN_TYPE_ACCESS);
      // tenant_id ignored on token-exchange — the subject_token's
      // tenant is the source of truth.
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.requestTimeoutMs);
    let response: Response;
    try {
      response = await fetch(this.tokenEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: params.toString(),
        signal: controller.signal,
      });
    } catch (err) {
      throw new S2SAuthError(`token endpoint unreachable: ${String(err)}`, {
        tokenEndpoint: this.tokenEndpoint,
      });
    } finally {
      clearTimeout(timer);
    }

    if (response.status !== 200) {
      const body = await safeText(response);
      throw new S2SAuthError(`token endpoint returned HTTP ${response.status}`, {
        status: response.status,
        body,
      });
    }

    let payload: { access_token?: unknown; expires_in?: unknown };
    try {
      payload = (await response.json()) as typeof payload;
    } catch {
      throw new S2SAuthError("token endpoint returned non-JSON response");
    }

    const accessToken = payload.access_token;
    if (typeof accessToken !== "string" || !accessToken) {
      throw new S2SAuthError("token endpoint response missing 'access_token'", {
        grant: params.get("grant_type"),
      });
    }
    let expiresIn = payload.expires_in;
    if (typeof expiresIn !== "number" || expiresIn <= 0) {
      // Spec-compliant servers always return expires_in; default
      // defensively rather than refusing to cache.
      expiresIn = 300;
    }
    const ttlMs = Math.max(0, (expiresIn - this.safetyMarginSeconds) * 1000);
    return {
      token: accessToken,
      expiresAtMs: Date.now() + ttlMs,
    };
  }
}

// ---------------------------------------------------------------- helpers

/** Decode a JWT's `jti` without verifying the signature. */
function unverifiedJti(token: string): string | null {
  const parts = token.split(".");
  if (parts.length < 2) {
    return null;
  }
  try {
    const payload = parts[1]!;
    const padded = payload + "=".repeat((4 - (payload.length % 4)) % 4);
    const decoded = Buffer.from(
      padded.replace(/-/g, "+").replace(/_/g, "/"),
      "base64",
    ).toString("utf-8");
    const claims = JSON.parse(decoded) as { jti?: unknown };
    return typeof claims.jti === "string" && claims.jti.length > 0 ? claims.jti : null;
  } catch {
    return null;
  }
}

/** Short stable hash for cache keys when the subject token has no jti. */
function shortHash(input: string): string {
  let hash = 0n;
  const prime = 1099511628211n;
  for (let i = 0; i < input.length; i++) {
    hash ^= BigInt(input.charCodeAt(i));
    hash = (hash * prime) & 0xffffffffffffffffn;
  }
  return hash.toString(16).padStart(16, "0");
}

/** Short, log-safe excerpt of a response body. */
async function safeText(response: Response): Promise<string> {
  try {
    const text = await response.text();
    return text.slice(0, 200);
  } catch {
    return "<unreadable>";
  }
}
