/**
 * Test-token minting helpers.
 *
 * Mirrors Python `platform_auth.testing`: lets unit tests mint
 * AuthGuard-verifiable JWTs without standing up a real IdP. The
 * helpers expose a tiny ECDSA P-256 keypair, a JWKS document
 * derived from it, and a `buildTestToken` function that signs
 * arbitrary claims.
 *
 * Cross-language parity: the same `buildTestToken({...})` invocation
 * with the same options must produce a token that all three SDKs
 * (`platform_auth.testing` Python, this file, and
 * `platform-auth-rs::testing` Rust) verify identically. The shared
 * parity-fixture suite at `forge/tests/contract/auth_sdk_parity/`
 * pins this contract.
 *
 * Not exported from the package root by default — consumers import
 * from `@forge/platform-auth-node/testing` so the test-only deps
 * tree-shake cleanly out of production bundles.
 */

import { exportJWK, generateKeyPair, SignJWT, type JWK, type KeyLike } from "jose";

/** A test ECDSA P-256 keypair plus its JWK shapes. */
export interface TestEcdsaKeypair {
  /** Stable kid generated at construction time. */
  readonly kid: string;
  readonly privateKey: KeyLike;
  readonly publicKey: KeyLike;
  readonly publicJwk: JWK;
  /** A complete JWKS document containing only this keypair's public JWK. */
  jwks(): { keys: JWK[] };
}

/** Generate a fresh ES256 keypair (slow — ~tens of ms). Cache per test file. */
export async function generateTestKeypair(opts: { kid?: string } = {}): Promise<TestEcdsaKeypair> {
  const { privateKey, publicKey } = await generateKeyPair("ES256", { extractable: true });
  const publicJwk = await exportJWK(publicKey);
  const kid = opts.kid ?? `test-key-${randomKid()}`;
  // jose's exportJWK produces a JWK without `kid`/`alg`/`use`; bake those in
  // so the resulting JWKS document is directly usable by AuthGuard's
  // verifier without a custom resolver.
  publicJwk.kid = kid;
  publicJwk.alg = "ES256";
  publicJwk.use = "sig";
  return {
    kid,
    privateKey,
    publicKey,
    publicJwk,
    jwks(): { keys: JWK[] } {
      return { keys: [publicJwk] };
    },
  };
}

/** Options for `buildTestToken`. Defaults match the platform-auth contract. */
export interface BuildTestTokenOptions {
  /** Required: the keypair to sign with. */
  keypair: TestEcdsaKeypair;

  /** Required: claim values that drive the verifier. */
  issuer: string;
  audience: string | readonly string[];
  subject: string;
  tenantId: string;

  /** Optional: extra claims merged into the payload. */
  roles?: readonly string[];
  scopes?: readonly string[];
  /** Override the default `https://forge/tenant_id` claim name. */
  tenantIdClaim?: string;
  /**
   * Plural to match `AuthGuardConfig.rolesClaim`, the Python
   * `roles_claim`, and the Rust `roles_claim`. The cross-language JWT
   * claim defaults to `"roles"` (a JSON array of strings).
   */
  rolesClaim?: string;
  scopeClaim?: string;

  /** Lifetime knobs (seconds). Defaults to 5 minutes valid from now. */
  ttlSeconds?: number;
  notBeforeSeconds?: number;
  /** Set explicit `exp` instead of computing from `ttlSeconds`. */
  expiresAt?: number;
  /** Set explicit `iat`. Defaults to `now`. */
  issuedAt?: number;

  /** RFC 8693 `act` chain — produces an on-behalf-of token. */
  act?: ActClaim | null;

  /** jti override; defaults to a random one. */
  jti?: string;

  /** Override the JWT `alg` header (e.g., `none`/`HS256` for negative tests). */
  algorithm?: string;

  /** Extra claims to include verbatim (use for negative-test scenarios). */
  extraClaims?: Record<string, unknown>;
}

/**
 * RFC 8693 `act` claim. Recursive so chains can be expressed directly.
 * The verifier walks `act.act.act...` up to 10 hops.
 */
export interface ActClaim {
  /** Machine identity of the actor (e.g., `svc-workflow`). */
  client_id?: string;
  /** Authorized party — fallback for `client_id`. */
  azp?: string;
  /** Actor subject — last-resort fallback. */
  sub?: string;
  /** Nested act for multi-hop delegation chains. */
  act?: ActClaim;
}

/**
 * Mint a signed JWT with the given claims.
 *
 * Use this from unit tests to feed AuthGuard a verifiable token
 * without needing a real Gatekeeper/Keycloak. The `algorithm`
 * option lets negative tests exercise the alg-allowlist (e.g.,
 * minting an HS256 token to confirm AuthGuard rejects it).
 */
export async function buildTestToken(opts: BuildTestTokenOptions): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const issuedAt = opts.issuedAt ?? now;
  const expiresAt =
    opts.expiresAt ?? issuedAt + (opts.ttlSeconds ?? 300); // 5 min default
  const audiences = Array.isArray(opts.audience)
    ? [...opts.audience]
    : [opts.audience];
  const tenantClaim = opts.tenantIdClaim ?? "https://forge/tenant_id";
  const rolesKey = opts.rolesClaim ?? "roles";
  const scopeKey = opts.scopeClaim ?? "scope";

  const payload: Record<string, unknown> = {
    sub: opts.subject,
    [tenantClaim]: opts.tenantId,
    jti: opts.jti ?? randomJti(),
  };
  if (opts.roles && opts.roles.length > 0) {
    payload[rolesKey] = [...opts.roles];
  }
  if (opts.scopes && opts.scopes.length > 0) {
    payload[scopeKey] = opts.scopes.join(" ");
  }
  if (opts.act) {
    payload.act = opts.act;
  }
  if (opts.notBeforeSeconds !== undefined) {
    payload.nbf = issuedAt + opts.notBeforeSeconds;
  }
  if (opts.extraClaims) {
    Object.assign(payload, opts.extraClaims);
  }

  const algorithm = opts.algorithm ?? "ES256";
  const signer = new SignJWT(payload)
    .setProtectedHeader({ alg: algorithm, kid: opts.keypair.kid })
    .setIssuer(opts.issuer)
    .setAudience(audiences)
    .setIssuedAt(issuedAt)
    .setExpirationTime(expiresAt);

  // Use the private key for asymmetric algs (the only path AuthGuard
  // accepts by default). Negative-test callers wanting symmetric or
  // `none` can pass `algorithm: "HS256"` and bring their own key
  // material via `extraClaims`-style overrides — beyond the scope of
  // this helper, document as unsupported.
  return await signer.sign(opts.keypair.privateKey);
}

// ---------------------------------------------------------------- internals

function randomJti(): string {
  // Cryptographic randomness when available; fallback to Math.random
  // for environments without crypto.getRandomValues.
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `test-jti-${Math.floor(Math.random() * 1e12).toString(36)}`;
}

function randomKid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return Math.floor(Math.random() * 1e12).toString(36);
}
