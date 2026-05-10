/**
 * Token revocation store interface.
 *
 * Mirrors Python platform_auth.revocation: AuthGuard consults this
 * after JWT signature/claim verification but before issuing the
 * IdentityContext. A token whose ``jti`` is present in the store
 * is rejected with ``TokenRevoked``.
 *
 * The interface is intentionally minimal so consumers can back it
 * with whatever they have — Redis SET, a database table, an
 * in-memory bloom filter for a fixed denylist, etc.
 */

export interface RevocationStore {
  /** True iff ``jti`` is on the revocation denylist. */
  isRevoked(jti: string): Promise<boolean>;
}

/**
 * Permissive store — never reports anything as revoked.
 *
 * Useful as a default when revocation isn't wired yet; AuthGuard
 * treats this as equivalent to having no store at all.
 */
export class NeverRevokedStore implements RevocationStore {
  async isRevoked(_jti: string): Promise<boolean> {
    return false;
  }
}

/**
 * In-memory denylist. Construct with the initial set; mutate via
 * ``revoke()`` / ``unrevoke()``. NOT shared across processes — use
 * a Redis or DB-backed implementation for multi-replica deployments.
 */
export class InMemoryRevocationStore implements RevocationStore {
  private readonly revoked: Set<string>;

  constructor(initial: Iterable<string> = []) {
    this.revoked = new Set(initial);
  }

  revoke(jti: string): void {
    this.revoked.add(jti);
  }

  unrevoke(jti: string): void {
    this.revoked.delete(jti);
  }

  async isRevoked(jti: string): Promise<boolean> {
    return this.revoked.has(jti);
  }
}
