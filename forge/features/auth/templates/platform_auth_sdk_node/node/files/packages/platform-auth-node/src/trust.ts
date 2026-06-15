/**
 * Per-tenant issuer trust map.
 *
 * Mirrors Python platform_auth.trust: each tenant declares which OIDC
 * issuer should sign tokens for it. Verification rejects tokens whose
 * ``iss`` claim doesn't match the tenant's expected issuer (defends
 * against a compromised second-issuer that could otherwise mint valid
 * tokens for any tenant).
 *
 * The trust map is also where suspended-tenant gating happens:
 * setting ``suspended: true`` blocks verification for that tenant
 * regardless of token validity.
 */

/** Per-tenant trust record. */
export interface TenantTrust {
  /** Issuer URL whose tokens are accepted for this tenant. */
  readonly expectedIssuer: string;
  /** When true, all tokens for this tenant are rejected (TenantSuspended). */
  readonly suspended: boolean;
}

/** Async lookup interface for tenant → trust mapping. */
export interface IssuerTrustMap {
  /** Returns the trust record for ``tenantId``, or ``null`` if unknown. */
  get(tenantId: string): Promise<TenantTrust | null>;
}

/**
 * In-memory map for fixed configurations. Suitable for single-tenant
 * deployments and dev/test fixtures. Multi-tenant production typically
 * fronts this with a Redis or DB-backed implementation.
 */
export class InMemoryIssuerTrustMap implements IssuerTrustMap {
  private readonly tenants: ReadonlyMap<string, TenantTrust>;

  constructor(tenants: Iterable<readonly [string, TenantTrust]> | Record<string, TenantTrust>) {
    const entries = Symbol.iterator in Object(tenants)
      ? (tenants as Iterable<readonly [string, TenantTrust]>)
      : Object.entries(tenants as Record<string, TenantTrust>);
    this.tenants = new Map(entries);
  }

  async get(tenantId: string): Promise<TenantTrust | null> {
    return this.tenants.get(tenantId) ?? null;
  }
}

/**
 * Wraps any IssuerTrustMap with an LRU cache to amortize lookups.
 * The wrapped store sees one call per cache miss / TTL expiry; the
 * AuthGuard hot path reads from memory.
 *
 * Cache invalidation is TTL-only — a tenant whose trust changes
 * upstream (suspension, issuer migration) takes up to ``ttlMs`` to
 * propagate. Operators that need immediate revocation should clear
 * the cache via ``invalidate(tenantId)`` from the same process that
 * mutates the upstream store.
 */
export class CachingIssuerTrustMap implements IssuerTrustMap {
  private readonly inner: IssuerTrustMap;
  private readonly ttlMs: number;
  private readonly cache: Map<string, { value: TenantTrust | null; expiresAt: number }> = new Map();

  constructor(inner: IssuerTrustMap, ttlMs = 60_000) {
    if (ttlMs <= 0) {
      throw new Error("ttlMs must be positive");
    }
    this.inner = inner;
    this.ttlMs = ttlMs;
  }

  async get(tenantId: string): Promise<TenantTrust | null> {
    const now = Date.now();
    const cached = this.cache.get(tenantId);
    if (cached && cached.expiresAt > now) {
      return cached.value;
    }
    const fresh = await this.inner.get(tenantId);
    this.cache.set(tenantId, { value: fresh, expiresAt: now + this.ttlMs });
    return fresh;
  }

  invalidate(tenantId: string): void {
    this.cache.delete(tenantId);
  }
}
