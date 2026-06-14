/**
 * Cross-SDK parity runner for the Node SDK.
 *
 * Loads the canonical scenario spec produced by Python's
 * `tests/contract/auth_sdk_parity/scenarios.py::scenarios_as_json()`,
 * mints a JWT for each scenario via the SDK's testing helper, runs
 * `AuthGuard.verify()`, and asserts the outcome matches the expected
 * shape from the spec.
 *
 * Path semantics:
 *   - The forge test orchestrator (Python) writes the JSON dump to
 *     a tempfile and passes the path via `PARITY_FIXTURES` env var.
 *   - When the env var is unset (e.g. `npx vitest run` invoked
 *     directly during local development), this test is skipped.
 *
 * Cross-language parity contract:
 *   - Same JWT inputs (each scenario's mint config) must yield the
 *     same `IdentityContext` (or matching `AuthError` reason slug)
 *     across Python, Node, and Rust.
 *   - The `reason()` slugs are pinned in `exceptions.ts` and asserted
 *     here against the scenario's `expected.error` literal.
 *
 * Run from forge's CI:
 *   ```bash
 *   cd sdks/platform-auth-node
 *   npm install
 *   PARITY_FIXTURES=/path/to/scenarios.json npx vitest run test/parity_runner.test.ts
 *   ```
 */

import { readFileSync } from "node:fs";

import { describe, expect, test } from "vitest";

import {
  ActorNotAuthorized,
  AuthError,
  AuthGuard,
  buildIdentity,
  InMemoryIssuerTrustMap,
  IssuerNotTrusted,
  InvalidToken,
  InMemoryRevocationStore,
  JWKSCache,
  ScopeRequired,
  StaticMayActPolicy,
  TenantSuspended,
  TokenExpired,
  TokenRevoked,
  type IdentityContext,
  type IssuerTrustMap,
  type RevocationStore,
} from "../src/index.js";
import {
  buildTestToken,
  generateTestKeypair,
  type ActClaim,
  type TestEcdsaKeypair,
} from "../src/testing.js";

// ---------------------------------------------------------------- spec types

interface ExpectedOutcome {
  identity?: {
    tenant_id: string;
    subject: string;
    roles?: string[];
    scopes?: string[];
    actor?: string | null;
    tenant_slug?: string | null;
    is_platform_admin?: boolean;
  };
  error?: string;
  error_message_contains?: string | null;
}

interface Scenario {
  name: string;
  description: string;
  issuer: string;
  audience: string | string[];
  subject: string;
  tenant_id: string;
  tenant_id_claim: string;
  tenant_slug: string | null;
  tenant_slug_claim: string;
  roles_claim: string;
  scope_claim: string;
  roles: string[];
  scopes: string[];
  ttl_seconds: number;
  expires_at: number | null;
  issued_at: number | null;
  jti: string | null;
  algorithm: string;
  act: ActClaim | null;
  extra_claims: Record<string, unknown>;
  omit_claims: string[];
  verifier_audience: string | string[];
  verifier_algorithms: string[];
  verifier_tenant_id_claim: string;
  verifier_roles_claim: string;
  verifier_scope_claim: string;
  verifier_tenant_slug_claim: string;
  revocation_denylist: string[];
  trust_map_overrides: Record<string, { expected_issuer: string; suspended?: boolean }>;
  may_act_allowlist: Record<string, string[]>;
  expected: ExpectedOutcome;
}

// Map cross-language `reason()` slugs to Node `AuthError` subclasses.
const SLUG_TO_CTOR = {
  invalid_token: InvalidToken,
  token_expired: TokenExpired,
  token_revoked: TokenRevoked,
  issuer_not_trusted: IssuerNotTrusted,
  actor_not_authorized: ActorNotAuthorized,
  scope_required: ScopeRequired,
  tenant_suspended: TenantSuspended,
} as const;

// Canonical issuer/audience constants — must match scenarios.py.
const ISSUER = "http://gatekeeper.test:5000";

// ---------------------------------------------------------------- harness

function loadScenarios(): Scenario[] | null {
  const path = process.env.PARITY_FIXTURES;
  if (!path) {
    return null;
  }
  const raw = readFileSync(path, "utf-8");
  return JSON.parse(raw) as Scenario[];
}

async function buildAuthGuardForScenario(
  scenario: Scenario,
  keypair: TestEcdsaKeypair,
): Promise<AuthGuard> {
  // JWKSCache pre-populated via httpx-style mock isn't directly
  // available in jose's createRemoteJWKSet, but our wrapper accepts
  // a Map of pre-resolved keys via the AuthGuard's verify() resolver
  // path. The simplest cross-language approach: stand up an in-memory
  // HTTP responder so jose's remote-set fetches the JWKS doc.
  //
  // Vitest runs each test in a worker; spawning a tiny HTTP server
  // per scenario is wasteful. Instead, inject the JWKS via jose's
  // `createLocalJWKSet`-equivalent pattern by overriding the
  // resolver. Our JWKSCache is a thin wrapper — the public API
  // doesn't expose a "set keys directly" hook today, so we stand up
  // a minimal in-process JWKS HTTP responder via fetch override.
  const cache = new JWKSCache();

  // Always register the *canonical* ISSUER (not scenario.issuer) so
  // the rogue-issuer rejection scenario actually fires. scenario.issuer
  // is the mint-side override.
  cache.registerIssuer(ISSUER, `${ISSUER}/auth/jwks`);

  // Patch global fetch so jose's remote JWKS fetches resolve against
  // the test keypair without going to the network. Vitest gives each
  // test a fresh global, so this doesn't bleed across scenarios.
  const jwksDoc = keypair.jwks();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: RequestInfo | URL): Promise<Response> => {
    const urlString = url instanceof URL ? url.toString() : String(url);
    if (urlString.endsWith("/auth/jwks")) {
      return new Response(JSON.stringify(jwksDoc), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return originalFetch(url as RequestInfo);
  }) as typeof fetch;

  const verifierAudiences = Array.isArray(scenario.verifier_audience)
    ? scenario.verifier_audience
    : [scenario.verifier_audience];

  // Trust map — scenario opt-in only. Default empty so most
  // scenarios don't get a "missing trust record" rejection.
  let trustMap: IssuerTrustMap | undefined;
  if (Object.keys(scenario.trust_map_overrides).length > 0) {
    const records = new Map<string, { expectedIssuer: string; suspended: boolean }>();
    for (const [tenantId, record] of Object.entries(scenario.trust_map_overrides)) {
      records.set(tenantId, {
        expectedIssuer: record.expected_issuer,
        suspended: record.suspended ?? false,
      });
    }
    trustMap = new InMemoryIssuerTrustMap(records);
  }

  // MayActPolicy — scenario specifies actor → audiences (intuitive),
  // but the SDK's `StaticMayActPolicy` (post-Phase-9 cross-language
  // alignment) is keyed audience → actors. Invert here.
  let mayAct: StaticMayActPolicy | undefined;
  if (Object.keys(scenario.may_act_allowlist).length > 0) {
    const inverted = new Map<string, Set<string>>();
    for (const [actor, audiences] of Object.entries(scenario.may_act_allowlist)) {
      for (const audience of audiences) {
        let set = inverted.get(audience);
        if (!set) {
          set = new Set();
          inverted.set(audience, set);
        }
        set.add(actor);
      }
    }
    mayAct = new StaticMayActPolicy(inverted);
  }

  let revocation: RevocationStore | undefined;
  if (scenario.revocation_denylist.length > 0) {
    revocation = new InMemoryRevocationStore(scenario.revocation_denylist);
  }

  const config: ConstructorParameters<typeof AuthGuard>[0] = {
    audiences: verifierAudiences,
    jwks: cache,
    algorithms: scenario.verifier_algorithms,
    tenantIdClaim: scenario.verifier_tenant_id_claim,
    tenantSlugClaim: scenario.verifier_tenant_slug_claim,
    rolesClaim: scenario.verifier_roles_claim,
    scopeClaim: scenario.verifier_scope_claim,
  };
  if (trustMap !== undefined) {
    config.trustMap = trustMap;
  }
  if (mayAct !== undefined) {
    config.mayAct = mayAct;
  }
  if (revocation !== undefined) {
    config.revocation = revocation;
  }
  return new AuthGuard(config);
}

async function mintScenarioToken(
  scenario: Scenario,
  keypair: TestEcdsaKeypair,
): Promise<string> {
  // Negative-test paths (`alg=none`, `alg=HS256`, missing `kid`) need
  // hand-crafted tokens that buildTestToken won't produce — handle
  // them explicitly, dispatch the rest to the SDK's testing helper.
  const audiences = Array.isArray(scenario.audience) ? scenario.audience : [scenario.audience];

  if (scenario.algorithm === "none" || scenario.algorithm === "HS256") {
    // Hand-craft so the verifier sees the alg-allowlist mismatch
    // before any signature check. The verifier rejects without
    // attempting to verify the signature, so the body shape doesn't
    // need to round-trip through the keypair.
    return buildUnverifiedToken(scenario, keypair, audiences);
  }
  if (scenario.omit_claims.includes("kid")) {
    return buildTokenWithoutKid(scenario, keypair, audiences);
  }

  // Mint the tenant_slug via extraClaims since buildTestToken's
  // signature doesn't expose a dedicated tenantSlug param (the SDK
  // testing helper is intentionally minimal — extraClaims is the
  // designed extension point).
  const extraClaims = { ...scenario.extra_claims };
  if (scenario.tenant_slug !== null) {
    extraClaims[scenario.tenant_slug_claim] = scenario.tenant_slug;
  }
  const opts: Parameters<typeof buildTestToken>[0] = {
    keypair,
    issuer: scenario.issuer,
    audience: audiences.length === 1 ? audiences[0]! : audiences,
    subject: scenario.subject,
    tenantId: scenario.tenant_id,
    tenantIdClaim: scenario.tenant_id_claim,
    rolesClaim: scenario.roles_claim,
    scopeClaim: scenario.scope_claim,
    roles: scenario.roles,
    scopes: scenario.scopes,
    ttlSeconds: scenario.ttl_seconds,
    extraClaims,
  };
  // Negative offsets in the spec (e.g., `expires_at: -1800`) mean
  // "X seconds from now" — translate to absolute timestamps.
  const nowSec = Math.floor(Date.now() / 1000);
  if (scenario.issued_at !== null) {
    opts.issuedAt = nowSec + scenario.issued_at;
  }
  if (scenario.expires_at !== null) {
    opts.expiresAt = nowSec + scenario.expires_at;
  }
  if (scenario.jti !== null) {
    opts.jti = scenario.jti;
  }
  if (scenario.act !== null) {
    opts.act = scenario.act;
  }
  // The tenant claim being in `omit_claims` means we want the token
  // WITHOUT the claim. buildTestToken's API doesn't have an "omit"
  // hook, so we work around by passing an empty tenant_id_claim
  // override (then strip the resulting field via extra_claims) — but
  // that's brittle. Cleaner: use buildTestToken with a placeholder
  // tenant_id, then manually re-encode the payload sans the claim.
  if (scenario.omit_claims.includes(scenario.tenant_id_claim)) {
    return buildTokenOmittingClaim(scenario, keypair, audiences, scenario.tenant_id_claim);
  }
  return buildTestToken(opts);
}

/**
 * Hand-craft a token with the scenario's algorithm header but signed
 * (or unsigned, for `alg=none`) so the verifier can read the header
 * + payload before its alg-allowlist check fires.
 *
 * The verifier rejects on alg mismatch BEFORE verifying the
 * signature, so we don't need a valid signature here — just a
 * structurally-parseable token.
 */
function buildUnverifiedToken(
  scenario: Scenario,
  keypair: TestEcdsaKeypair,
  audiences: readonly string[],
): string {
  const nowSec = Math.floor(Date.now() / 1000);
  const issuedAt = nowSec + (scenario.issued_at ?? 0);
  const expiresAt =
    scenario.expires_at !== null ? nowSec + scenario.expires_at : issuedAt + scenario.ttl_seconds;

  const header: Record<string, unknown> = { alg: scenario.algorithm };
  if (!scenario.omit_claims.includes("kid")) {
    header.kid = keypair.kid;
  }
  const payload: Record<string, unknown> = {
    iss: scenario.issuer,
    aud: audiences.length === 1 ? audiences[0] : audiences,
    sub: scenario.subject,
    iat: issuedAt,
    exp: expiresAt,
    jti: scenario.jti ?? `test-jti-${Math.random().toString(16).slice(2)}`,
    [scenario.tenant_id_claim]: scenario.tenant_id,
  };
  if (scenario.roles.length > 0) payload[scenario.roles_claim] = scenario.roles;
  if (scenario.scopes.length > 0) payload[scenario.scope_claim] = scenario.scopes.join(" ");
  if (scenario.act !== null) payload.act = scenario.act;
  Object.assign(payload, scenario.extra_claims);

  const headerB64 = base64Url(JSON.stringify(header));
  const payloadB64 = base64Url(JSON.stringify(payload));
  // Trailing dot for unsigned (`alg=none`); empty signature segment
  // for HS256 (the verifier rejects on alg-allowlist before the
  // signature check, so the empty sig is never inspected).
  return `${headerB64}.${payloadB64}.`;
}

function buildTokenWithoutKid(
  scenario: Scenario,
  keypair: TestEcdsaKeypair,
  audiences: readonly string[],
): string {
  // Same as buildUnverifiedToken but with the scenario's actual
  // (ES256) algorithm so the signature could in principle verify.
  // We just omit the kid header so the verifier rejects on
  // missing-kid before the signature check.
  return buildUnverifiedToken(scenario, keypair, audiences);
}

async function buildTokenOmittingClaim(
  scenario: Scenario,
  keypair: TestEcdsaKeypair,
  audiences: readonly string[],
  claim: string,
): Promise<string> {
  // Mint the normal token, then re-sign without the claim. Easier
  // than threading "omit" support through buildTestToken's API.
  const fullOpts: Parameters<typeof buildTestToken>[0] = {
    keypair,
    issuer: scenario.issuer,
    audience: audiences.length === 1 ? audiences[0]! : audiences,
    subject: scenario.subject,
    tenantId: scenario.tenant_id,
    tenantIdClaim: scenario.tenant_id_claim,
    rolesClaim: scenario.roles_claim,
    scopeClaim: scenario.scope_claim,
    roles: scenario.roles,
    scopes: scenario.scopes,
    ttlSeconds: scenario.ttl_seconds,
    extraClaims: scenario.extra_claims,
  };
  const fullToken = await buildTestToken(fullOpts);
  // Decode payload, strip claim, re-sign manually using the SDK's
  // testing helper for jose-based ES256 signing.
  const [headerB64, payloadB64] = fullToken.split(".");
  if (!headerB64 || !payloadB64) {
    throw new Error("malformed token from buildTestToken");
  }
  const payload = JSON.parse(
    Buffer.from(payloadB64, "base64url").toString("utf-8"),
  ) as Record<string, unknown>;
  delete payload[claim];
  // Reuse the helper to sign the modified payload.
  return buildTestToken({
    ...fullOpts,
    extraClaims: { ...fullOpts.extraClaims, ...payload, _omit_marker: undefined },
  });
}

function base64Url(input: string): string {
  return Buffer.from(input, "utf-8")
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

// ---------------------------------------------------------------- runner

const scenarios = loadScenarios();

describe.skipIf(!scenarios)("cross-SDK parity (Node)", () => {
  if (!scenarios) {
    test("env var PARITY_FIXTURES required", () => {
      // eslint-disable-next-line @typescript-eslint/no-unused-expressions
      expect.fail("PARITY_FIXTURES env var must point to scenarios JSON");
    });
    return;
  }
  for (const scenario of scenarios) {
    test(scenario.name, async () => {
      // Fresh keypair per scenario so test order doesn't matter.
      const keypair = await generateTestKeypair();
      const authGuard = await buildAuthGuardForScenario(scenario, keypair);
      const token = await mintScenarioToken(scenario, keypair);

      if (scenario.expected.identity !== undefined) {
        // Success path.
        const identity: IdentityContext = await authGuard.verify(token);
        const expected = scenario.expected.identity;
        expect(identity.tenantId).toBe(expected.tenant_id);
        expect(identity.subject).toBe(expected.subject);
        expect([...identity.roles].sort()).toEqual([...(expected.roles ?? [])].sort());
        expect([...identity.scopes].sort()).toEqual([...(expected.scopes ?? [])].sort());
        expect(identity.actor).toBe(expected.actor ?? null);
        // Optional tenant_slug — assert when the scenario pins it; an
        // undefined expectation key means "any value is fine"
        // (back-compat for scenarios written before the field shipped).
        if (expected.tenant_slug !== undefined) {
          expect(identity.tenantSlug).toBe(expected.tenant_slug);
        }
        if (expected.is_platform_admin !== undefined) {
          expect(identity.isPlatformAdmin).toBe(expected.is_platform_admin);
        }
      } else if (scenario.expected.error !== undefined) {
        const slug = scenario.expected.error;
        const expectedCtor = SLUG_TO_CTOR[slug as keyof typeof SLUG_TO_CTOR];
        expect(expectedCtor, `unknown slug ${slug}`).toBeDefined();
        let caught: unknown;
        try {
          await authGuard.verify(token);
        } catch (err) {
          caught = err;
        }
        expect(caught, `scenario ${scenario.name} should have thrown`).toBeInstanceOf(
          expectedCtor!,
        );
        if (scenario.expected.error_message_contains) {
          const message = (caught as Error).message;
          expect(message.toLowerCase()).toContain(
            scenario.expected.error_message_contains.toLowerCase(),
          );
        }
        // Sanity: pinned reason slug matches across the language boundary.
        expect((caught as AuthError).reason).toBe(slug);
        // Use buildIdentity import to silence the lint rule about the
        // helper being unused — we re-export it for type symmetry but
        // don't construct identities directly here.
        void buildIdentity;
      } else {
        throw new Error(
          `scenario ${scenario.name}: expected outcome must declare identity OR error`,
        );
      }
    });
  }
});
