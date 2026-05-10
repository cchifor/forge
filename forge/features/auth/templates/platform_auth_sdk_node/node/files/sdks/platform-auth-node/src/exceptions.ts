/**
 * Exception hierarchy for @forge/platform-auth-node.
 *
 * Mirrors Python platform_auth.exceptions: every error carries a stable
 * `reason` slug and an HTTP-equivalent `statusCode` so callers can map
 * them directly to RFC 7807 problem responses without sniffing the
 * type tree. The slugs are part of the public contract — clients
 * dispatch on them across the parity boundary, so changing one is a
 * cross-language breaking change.
 */

export class AuthError extends Error {
  /** Stable snake_case slug for client-side dispatch. Public contract. */
  readonly reason: string = "auth_error";
  /** HTTP-equivalent status code for the problem response mapping. */
  readonly statusCode: number = 401;
  /** Arbitrary extra context (never secrets). Drop into the audit log. */
  readonly extra: Record<string, unknown>;

  constructor(detail?: string, extra: Record<string, unknown> = {}) {
    super(detail ?? "auth_error");
    this.name = this.constructor.name;
    this.extra = extra;
    // Restore prototype for `instanceof` to work across the ESM boundary.
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class InvalidToken extends AuthError {
  override readonly reason = "invalid_token";
  override readonly statusCode = 401;
}

export class TokenExpired extends AuthError {
  override readonly reason = "token_expired";
  override readonly statusCode = 401;
}

export class TokenRevoked extends AuthError {
  override readonly reason = "token_revoked";
  override readonly statusCode = 401;
}

export class IssuerNotTrusted extends AuthError {
  override readonly reason = "issuer_not_trusted";
  override readonly statusCode = 401;
}

export class ActorNotAuthorized extends AuthError {
  override readonly reason = "actor_not_authorized";
  override readonly statusCode = 403;
}

export class ScopeRequired extends AuthError {
  override readonly reason = "scope_required";
  override readonly statusCode = 403;
  readonly missingScopes: ReadonlySet<string>;

  constructor(missingScopes: ReadonlySet<string> | Iterable<string>, detail?: string) {
    const frozen = new Set(missingScopes);
    super(detail, { missingScopes: [...frozen].sort() });
    this.missingScopes = frozen as ReadonlySet<string>;
  }
}

export class TenantSuspended extends AuthError {
  override readonly reason = "tenant_suspended";
  override readonly statusCode = 403;
}

export class S2SAuthError extends AuthError {
  override readonly reason = "s2s_auth_error";
  override readonly statusCode = 503;
}
