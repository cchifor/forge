/**
 * AuthGuard — JWT bearer-token verifier.
 *
 * Mirrors Python platform_auth.auth_guard.AuthGuard. On each request:
 *   1. Extract ``Authorization: Bearer <jwt>`` from the request.
 *   2. Reject any algorithm not in the configured allowlist.
 *   3. Read the unverified ``iss`` claim, look up the JWKS resolver.
 *   4. Verify signature + ``aud`` + ``exp`` + ``nbf`` + required claims via jose.
 *   5. Resolve tenant claim, consult IssuerTrustMap.
 *   6. Consult RevocationStore.
 *   7. Walk RFC 8693 ``act`` chain, ask MayActPolicy.
 *   8. Build IdentityContext, return.
 *
 * A failure at any step throws a typed AuthError. The caller's HTTP
 * exception handler maps these to RFC 7807 responses via
 * ``error.statusCode`` and ``error.reason``.
 *
 * Constructed once per process and reused as a Fastify pre-handler;
 * never per-request.
 */

import { type JWTPayload, decodeJwt, decodeProtectedHeader, errors as joseErrors, jwtVerify } from "jose";

import {
  ActorNotAuthorized,
  type AuthError,
  InvalidToken,
  IssuerNotTrusted,
  ScopeRequired,
  TenantSuspended,
  TokenExpired,
  TokenRevoked,
} from "./exceptions.js";
import { type IdentityContext, buildIdentity } from "./IdentityContext.js";
import { JWKSCache } from "./JWKSCache.js";
import { type MayActPolicy } from "./may_act.js";
import { type RevocationStore } from "./revocation.js";
import { type IssuerTrustMap } from "./trust.js";

export const DEFAULT_TENANT_ID_CLAIM = "https://forge/tenant_id";
export const DEFAULT_TENANT_SLUG_CLAIM = "https://forge/tenant_slug";
export const DEFAULT_ROLES_CLAIM = "roles";
export const DEFAULT_SCOPE_CLAIM = "scope";

/**
 * Claims jose must enforce as present (RFC 9068 §2.2 — Required Claims).
 * ``nbf`` is intentionally absent: it is OPTIONAL per RFC 7519 §4.1.5.
 */
export const REQUIRED_CLAIMS = ["iss", "aud", "sub", "exp", "iat", "jti"] as const;

/**
 * Accepted JWT signing algorithms. Asymmetric only — never include
 * ``none`` or ``HS*`` here; doing so would let any party with the
 * symmetric secret forge tokens. ES256 is the platform standard
 * (smaller signatures, ~10× faster signing than RS256).
 */
export const DEFAULT_ALGORITHMS = ["ES256"] as const;

export const DEFAULT_CLOCK_SKEW_SECONDS = 30;

/**
 * Extra context emitted to the audit callback per allow / deny decision.
 * Keep it shallow + JSON-serializable; downstream audit pipelines treat
 * the shape as the public contract.
 */
export type AuthAuditRecord = {
  decision: "allow" | "deny";
  audience: string;
  audiences: readonly string[];
  tsUnix: number;
  tenantId?: string;
  /**
   * Optional human-readable tenant slug from the verified
   * IdentityContext.tenantSlug. Mirrors Python's `_emit_audit`
   * `tenant_slug` field and Rust's `AuthAuditRecord.tenant_slug`.
   * Absent when the identity has no slug.
   */
  tenantSlug?: string | null;
  subject?: string;
  actor?: string | null;
  scopes?: readonly string[];
  jti?: string;
  iss?: string;
  reason?: string;
};

export type AuthAuditCallback = (record: AuthAuditRecord) => void | Promise<void>;

export interface AuthGuardConfig {
  /** Single audience this verifier accepts. Mutually exclusive with ``audiences``. */
  audience?: string;
  /** Multiple accepted audiences (token's ``aud`` matches any). Mutually exclusive with ``audience``. */
  audiences?: readonly string[];

  /** Required: multi-issuer JWKS cache. */
  jwks: JWKSCache;

  /** Optional: per-tenant issuer trust map. */
  trustMap?: IssuerTrustMap;
  /** Optional: revoked-jti store. */
  revocation?: RevocationStore;
  /** Optional: RFC 8693 act-chain authorization policy. */
  mayAct?: MayActPolicy;

  /** Allowed signing algorithms. Default ``["ES256"]``. ``"none"`` always rejected. */
  algorithms?: readonly string[];
  /** Clock-skew leeway in seconds. Default 30. */
  clockSkewSeconds?: number;

  /** JWT claim carrying the tenant UUID. Default ``"https://forge/tenant_id"``. */
  tenantIdClaim?: string;
  /** JWT claim carrying the optional tenant slug. Default ``"https://forge/tenant_slug"``. */
  tenantSlugClaim?: string;
  /** JWT claim carrying realm roles. Default ``"roles"``. */
  rolesClaim?: string;
  /** JWT claim carrying space-separated OAuth scopes. Default ``"scope"``. */
  scopeClaim?: string;

  /** Optional audit callback fired on every verification. */
  audit?: AuthAuditCallback;
}

/** Anything with HTTP-style headers — Fastify request, fetch Request, etc. */
export interface RequestLike {
  headers: { get?(name: string): string | null } | Record<string, string | string[] | undefined>;
}

const _UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

export class AuthGuard {
  private readonly _audiences: readonly string[];
  private readonly _algorithms: readonly string[];
  private readonly _clockSkew: number;
  private readonly _tenantIdClaim: string;
  private readonly _tenantSlugClaim: string;
  private readonly _rolesClaim: string;
  private readonly _scopeClaim: string;
  private readonly _jwks: JWKSCache;
  private readonly _trustMap: IssuerTrustMap | undefined;
  private readonly _revocation: RevocationStore | undefined;
  private readonly _mayAct: MayActPolicy | undefined;
  private readonly _audit: AuthAuditCallback | undefined;

  constructor(config: AuthGuardConfig) {
    if (config.audience !== undefined && config.audiences !== undefined) {
      throw new Error("provide either audience or audiences, not both");
    }
    if (config.audiences !== undefined) {
      if (config.audiences.length === 0) {
        throw new Error("audiences must be non-empty");
      }
      for (const entry of config.audiences) {
        if (!entry) {
          throw new Error("audience entries must be non-empty");
        }
      }
      this._audiences = [...config.audiences];
    } else {
      if (!config.audience) {
        throw new Error("audience must be non-empty");
      }
      this._audiences = [config.audience];
    }

    const algs = config.algorithms ?? DEFAULT_ALGORITHMS;
    if (algs.length === 0) {
      throw new Error("algorithms must be non-empty");
    }
    for (const alg of algs) {
      if (alg.toLowerCase() === "none") {
        throw new Error(`algorithm ${JSON.stringify(alg)} is forbidden`);
      }
    }
    const clockSkew = config.clockSkewSeconds ?? DEFAULT_CLOCK_SKEW_SECONDS;
    if (clockSkew < 0) {
      throw new Error("clockSkewSeconds must be non-negative");
    }

    this._jwks = config.jwks;
    this._trustMap = config.trustMap;
    this._revocation = config.revocation;
    this._mayAct = config.mayAct;
    this._algorithms = [...algs];
    this._clockSkew = clockSkew;
    this._tenantIdClaim = config.tenantIdClaim ?? DEFAULT_TENANT_ID_CLAIM;
    this._tenantSlugClaim = config.tenantSlugClaim ?? DEFAULT_TENANT_SLUG_CLAIM;
    this._rolesClaim = config.rolesClaim ?? DEFAULT_ROLES_CLAIM;
    this._scopeClaim = config.scopeClaim ?? DEFAULT_SCOPE_CLAIM;
    this._audit = config.audit;
  }

  /** Primary audience — kept singular for diagnostic/logging callers. */
  get audience(): string {
    // Constructor validated _audiences is non-empty.
    // biome-ignore lint/style/noNonNullAssertion: validated at construction
    return this._audiences[0]!;
  }

  /** All accepted audiences. */
  get audiences(): readonly string[] {
    return this._audiences;
  }

  /**
   * Extract the bearer token from a Fastify request and verify.
   *
   * Returns the IdentityContext built from the verified claims. Throws
   * AuthError subclasses on failure — the caller (typically a Fastify
   * pre-handler) translates them via ``error.statusCode``.
   */
  async verifyRequest(request: RequestLike): Promise<IdentityContext> {
    const token = this._extractBearer(request);
    return this.verify(token);
  }

  /**
   * Validate ``token`` and return the verified IdentityContext.
   *
   * Use this directly when you have a token in hand and don't have a
   * request — e.g., event-bus consumers verifying a producer's S2S
   * token recorded on the event envelope.
   */
  async verify(token: string): Promise<IdentityContext> {
    if (!token) {
      throw new InvalidToken("missing bearer token");
    }

    let header: ReturnType<typeof decodeProtectedHeader>;
    try {
      header = decodeProtectedHeader(token);
    } catch (err) {
      throw new InvalidToken("malformed token header", { cause: String(err) });
    }
    const alg = header.alg;
    if (typeof alg !== "string" || !this._algorithms.includes(alg)) {
      throw new InvalidToken(`algorithm ${JSON.stringify(alg)} not allowed`);
    }
    if (typeof header.kid !== "string" || !header.kid) {
      throw new InvalidToken("token header missing 'kid'");
    }

    let unverified: JWTPayload;
    try {
      unverified = decodeJwt(token);
    } catch (err) {
      throw new InvalidToken("malformed token", { cause: String(err) });
    }
    const iss = unverified.iss;
    if (typeof iss !== "string" || !iss) {
      throw new InvalidToken("token missing 'iss'");
    }
    if (!this._jwks.registeredIssuers().has(iss)) {
      throw new InvalidToken(`issuer ${JSON.stringify(iss)} is not registered`);
    }

    const keyResolver = this._jwks.keyResolverFor(iss);
    let payload: JWTPayload;
    try {
      const result = await jwtVerify(token, keyResolver, {
        algorithms: [...this._algorithms],
        audience: [...this._audiences],
        clockTolerance: this._clockSkew,
        requiredClaims: [...REQUIRED_CLAIMS],
      });
      payload = result.payload;
    } catch (err) {
      throw this._translateJoseError(err);
    }

    const tenantId = this._extractTenantId(payload);
    if (this._trustMap !== undefined) {
      await this._enforceTrust(tenantId, iss);
    }

    const jti = payload.jti;
    if (typeof jti !== "string" || !jti) {
      // jose's requiredClaims should have caught this, but be defensive.
      throw new InvalidToken("missing required claim: jti");
    }
    if (this._revocation !== undefined && (await this._revocation.isRevoked(jti))) {
      throw new TokenRevoked(`token jti ${JSON.stringify(jti)} is revoked`);
    }

    const actor = this._enforceActChain(payload);

    // Optional tenant slug — read from the configured claim if present.
    // Absent / non-string → null (informational field; we don't reject
    // the token over a malformed slug).
    const slugRaw = payload[this._tenantSlugClaim];
    const tenantSlug = typeof slugRaw === "string" ? slugRaw : null;

    const identity = buildIdentity({
      tenantId,
      subject: String(payload.sub),
      roles: this._roles(payload),
      scopes: this._scopes(payload),
      actor,
      tenantSlug,
      rawClaims: payload as Record<string, unknown>,
    });

    await this._emitAudit({ decision: "allow", identity, jti, iss });
    return identity;
  }

  // ---------------------------------------------------------------- helpers

  private _extractBearer(request: RequestLike): string {
    const headers = request.headers;
    let raw: string | null = null;
    if (typeof (headers as { get?: (n: string) => string | null }).get === "function") {
      // fetch / web-standard Headers
      raw = (headers as { get: (n: string) => string | null }).get("authorization");
    } else {
      const dict = headers as Record<string, string | string[] | undefined>;
      const value = dict.authorization ?? dict.Authorization;
      raw = Array.isArray(value) ? (value[0] ?? null) : (value ?? null);
    }
    if (!raw) {
      throw new InvalidToken("missing Authorization header");
    }
    const idx = raw.indexOf(" ");
    if (idx < 0) {
      throw new InvalidToken("Authorization header is not a Bearer token");
    }
    const prefix = raw.slice(0, idx);
    const token = raw.slice(idx + 1).trim();
    if (prefix.toLowerCase() !== "bearer" || !token) {
      throw new InvalidToken("Authorization header is not a Bearer token");
    }
    return token;
  }

  private _translateJoseError(err: unknown): AuthError {
    if (err instanceof joseErrors.JWTExpired) {
      return new TokenExpired("token expired", { cause: String(err) });
    }
    if (err instanceof joseErrors.JWTClaimValidationFailed) {
      return new InvalidToken(err.message, { claim: err.claim });
    }
    if (err instanceof joseErrors.JWSSignatureVerificationFailed) {
      return new InvalidToken("signature mismatch", { cause: String(err) });
    }
    if (err instanceof joseErrors.JWSInvalid) {
      return new InvalidToken("malformed token", { cause: String(err) });
    }
    if (err instanceof joseErrors.JWTInvalid) {
      return new InvalidToken("invalid token", { cause: String(err) });
    }
    return new InvalidToken(String(err));
  }

  private _extractTenantId(claims: JWTPayload): string {
    const raw = claims[this._tenantIdClaim];
    if (raw === undefined || raw === null) {
      throw new InvalidToken(`missing tenant claim: ${JSON.stringify(this._tenantIdClaim)}`);
    }
    if (typeof raw !== "string") {
      throw new InvalidToken(
        `tenant claim ${JSON.stringify(this._tenantIdClaim)} must be a UUID string`,
      );
    }
    if (!_UUID_RE.test(raw)) {
      throw new InvalidToken(
        `tenant claim ${JSON.stringify(this._tenantIdClaim)} is not a valid UUID`,
      );
    }
    return raw;
  }

  private async _enforceTrust(tenantId: string, iss: string): Promise<void> {
    const record = await this._trustMap!.get(tenantId);
    if (record === null) {
      throw new InvalidToken(`unknown tenant ${tenantId}`);
    }
    if (record.expectedIssuer !== iss) {
      throw new IssuerNotTrusted(
        `tenant ${tenantId} expects issuer ${JSON.stringify(record.expectedIssuer)}, ` +
          `token presents ${JSON.stringify(iss)}`,
      );
    }
    if (record.suspended) {
      throw new TenantSuspended(`tenant ${tenantId} is suspended`);
    }
  }

  private _enforceActChain(claims: JWTPayload): string | null {
    const act = claims.act;
    if (act === undefined || act === null) {
      return null;
    }
    if (typeof act !== "object" || Array.isArray(act)) {
      throw new InvalidToken("'act' claim must be an object");
    }

    let immediateActor: string | null = null;
    let current: Record<string, unknown> | null = act as Record<string, unknown>;
    let depth = 0;
    const maxDepth = 10;

    while (current !== null) {
      if (depth >= maxDepth) {
        throw new InvalidToken(`act chain too deep (>${maxDepth} hops)`);
      }
      const actorId = AuthGuard._actorIdentifier(current);
      if (actorId === null) {
        throw new InvalidToken("'act' entry missing actor identifier");
      }
      if (immediateActor === null) {
        immediateActor = actorId;
      }
      if (
        this._mayAct !== undefined &&
        !this._mayAct.isAuthorized(actorId, this._audiences[0]!)
      ) {
        throw new ActorNotAuthorized(
          `actor ${JSON.stringify(actorId)} not authorized to act for ` +
            `${JSON.stringify(this._audiences[0])}`,
        );
      }
      const nested: unknown = current.act;
      current =
        nested !== null && typeof nested === "object" && !Array.isArray(nested)
          ? (nested as Record<string, unknown>)
          : null;
      depth += 1;
    }
    return immediateActor;
  }

  private static _actorIdentifier(entry: Record<string, unknown>): string | null {
    // Prefer client_id (machine identity) over sub (which could be an
    // impersonated user — wrong identity to gate on).
    for (const key of ["client_id", "azp", "sub"] as const) {
      const value = entry[key];
      if (typeof value === "string" && value) {
        return value;
      }
    }
    return null;
  }

  private _roles(claims: JWTPayload): Iterable<string> {
    const raw = claims[this._rolesClaim];
    if (raw === undefined || raw === null) {
      return [];
    }
    if (typeof raw === "string") {
      return raw
        .replace(/,/g, " ")
        .split(/\s+/)
        .filter((s) => s.length > 0);
    }
    if (Array.isArray(raw)) {
      return raw.filter((r): r is string => typeof r === "string");
    }
    throw new InvalidToken(`roles claim ${JSON.stringify(this._rolesClaim)} has unexpected shape`);
  }

  private _scopes(claims: JWTPayload): Iterable<string> {
    const raw = claims[this._scopeClaim];
    if (raw === undefined || raw === null) {
      return [];
    }
    if (typeof raw === "string") {
      return raw.split(/\s+/).filter((s) => s.length > 0);
    }
    if (Array.isArray(raw)) {
      return raw.filter((s): s is string => typeof s === "string");
    }
    throw new InvalidToken(`scope claim ${JSON.stringify(this._scopeClaim)} has unexpected shape`);
  }

  private async _emitAudit(args: {
    decision: "allow" | "deny";
    identity?: IdentityContext;
    jti?: string;
    iss?: string;
    reason?: string;
  }): Promise<void> {
    if (this._audit === undefined) {
      return;
    }
    const record: AuthAuditRecord = {
      decision: args.decision,
      audience: this._audiences[0]!,
      audiences: this._audiences,
      tsUnix: Date.now() / 1000,
    };
    if (args.identity !== undefined) {
      record.tenantId = args.identity.tenantId;
      record.tenantSlug = args.identity.tenantSlug;
      record.subject = args.identity.subject;
      record.actor = args.identity.actor;
      record.scopes = [...args.identity.scopes].sort();
    }
    if (args.jti !== undefined) {
      record.jti = args.jti;
    }
    if (args.iss !== undefined) {
      record.iss = args.iss;
    }
    if (args.reason !== undefined) {
      record.reason = args.reason;
    }
    await Promise.resolve(this._audit(record));
  }
}

/**
 * Build a Fastify pre-handler that enforces ``required`` scopes.
 *
 * Expects an AuthGuard-decorated identity already bound to the request
 * (typically via the platform-auth Fastify plugin under
 * ``req.identity``). Raises ``ScopeRequired`` if any required scope is
 * unsatisfied; raises ``InvalidToken`` if no identity has been bound
 * (mis-wired endpoint — fail closed).
 *
 * Required scopes accept raw strings; the upstream route handler
 * converts ``Scope`` enum members.
 */
export function requireScope(...required: readonly string[]) {
  const needed = new Set(required);
  return async function preHandler(request: { identity?: IdentityContext }): Promise<void> {
    const identity = request.identity;
    if (identity === undefined) {
      throw new InvalidToken("no verified identity bound to request");
    }
    if (needed.size === 0) {
      return;
    }
    const missing = new Set<string>();
    for (const scope of needed) {
      if (!identity.hasScope(scope)) {
        missing.add(scope);
      }
    }
    if (missing.size > 0) {
      throw new ScopeRequired(missing);
    }
  };
}
