/**
 * IdentityContext — verified identity of the caller.
 *
 * Mirrors Python platform_auth.identity.IdentityContext. Built by
 * AuthGuard.verify() after a token survives signature, issuer,
 * audience, expiry, revocation, and may_act checks. Service handlers
 * consume it; nothing else in the request should touch raw JWT claims.
 *
 * Frozen object so it can live across async boundaries (in
 * AsyncLocalStorage, on req.identity, etc.) without surprise mutation.
 * `rawClaims` is provided for advanced uses but typed accessors should
 * be preferred.
 */

import { scopeSatisfies } from "./scopes.js";

/** Cross-tenant operator scopes — gating is_platform_admin. */
export const PLATFORM_SUPPORT_READ = "platform:support:read";
export const PLATFORM_SUPPORT_WRITE = "platform:support:write";

/** Verified caller identity, immutable after construction. */
export interface IdentityContext {
  readonly tenantId: string;
  readonly subject: string;
  readonly roles: ReadonlySet<string>;
  readonly scopes: ReadonlySet<string>;
  /** RFC 8693 immediate-actor identifier when token was minted via token-exchange; null otherwise. */
  readonly actor: string | null;
  /**
   * Optional human-readable tenant slug from the configured
   * ``tenantSlugClaim``. ``null`` when the JWT doesn't carry the
   * claim. Consumers that need a stable identifier should always
   * prefer ``tenantId`` (UUID); the slug is for log labels and
   * human-facing error messages.
   */
  readonly tenantSlug: string | null;
  /** Raw decoded JWT claims. Consume only via typed accessors. */
  readonly rawClaims: Readonly<Record<string, unknown>>;

  /** True iff this identity's scopes satisfy ``required`` (wildcard-aware). */
  hasScope(required: string): boolean;
  /** True iff any of ``required`` is satisfied. */
  hasAnyScope(...required: readonly string[]): boolean;
  /** True iff every scope in ``required`` is satisfied. */
  hasAllScopes(...required: readonly string[]): boolean;
  /** True iff this identity holds any cross-tenant ``platform:support`` scope. */
  readonly isPlatformAdmin: boolean;
  /** True iff this token was minted via on-behalf-of token-exchange. */
  readonly isActor: boolean;
}

interface IdentityContextInit {
  tenantId: string;
  subject: string;
  roles?: Iterable<string>;
  scopes?: Iterable<string>;
  actor?: string | null;
  tenantSlug?: string | null;
  rawClaims?: Record<string, unknown>;
}

/**
 * Build a frozen IdentityContext.
 *
 * Use this from AuthGuard.verify(); test fixtures use
 * ``buildTestIdentity()`` from ``./testing.js`` instead.
 */
export function buildIdentity(init: IdentityContextInit): IdentityContext {
  if (!init.tenantId) {
    throw new Error("tenantId must be non-empty");
  }
  if (!init.subject) {
    throw new Error("subject must be non-empty");
  }
  const roles = Object.freeze(new Set(init.roles ?? [])) as ReadonlySet<string>;
  const scopes = Object.freeze(new Set(init.scopes ?? [])) as ReadonlySet<string>;
  const actor = init.actor ?? null;
  const tenantSlug = init.tenantSlug ?? null;
  const rawClaims = Object.freeze({ ...(init.rawClaims ?? {}) });

  const hasScope = (required: string): boolean => scopeSatisfies(required, scopes);
  const hasAnyScope = (...required: readonly string[]): boolean =>
    required.some(hasScope);
  const hasAllScopes = (...required: readonly string[]): boolean =>
    required.every(hasScope);

  const ctx: IdentityContext = Object.freeze({
    tenantId: init.tenantId,
    subject: init.subject,
    roles,
    scopes,
    actor,
    tenantSlug,
    rawClaims,
    hasScope,
    hasAnyScope,
    hasAllScopes,
    get isPlatformAdmin(): boolean {
      return hasAnyScope(PLATFORM_SUPPORT_READ, PLATFORM_SUPPORT_WRITE);
    },
    get isActor(): boolean {
      return actor !== null;
    },
  });

  return ctx;
}
