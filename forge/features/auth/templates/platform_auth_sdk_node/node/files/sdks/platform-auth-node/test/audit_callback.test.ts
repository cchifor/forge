/**
 * Audit-callback contract tests for the Node SDK.
 *
 * Mirrors the Rust ``tests/audit_callback.rs`` cargo tests and the
 * Python ``tests/unit/test_auth_guard.py::TestAudit`` suite. Cross-
 * language audit-record shape is the public contract — this file
 * pins the Node-side behavior so a regression where ``_emitAudit``
 * stops populating a field (or the callback stops firing on the
 * allow path) gets caught at SDK build time.
 *
 * Run via:
 *   cd sdks/platform-auth-node
 *   npm install
 *   npx vitest run test/audit_callback.test.ts
 *
 * The forge orchestrator drives this from Python via the same
 * ``test_node_runner.py`` path that drives the parity runner — see
 * forge/tests/contract/auth_sdk_parity/.
 */

import { describe, expect, test } from "vitest";

import {
  AuthGuard,
  type AuthAuditRecord,
  type IssuerTrustMap,
} from "../src/index.js";
import {
  buildTestToken,
  generateTestKeypair,
  type TestEcdsaKeypair,
} from "../src/testing.js";

const TEST_ISSUER = "http://gatekeeper.test:5000";
const TEST_AUDIENCE = "svc-test";
const TEST_TENANT_ID = "11111111-1111-4111-8111-111111111111";
const TEST_SUBJECT = "22222222-2222-4222-8222-222222222222";

/**
 * Stand up a JWKSCache-backed AuthGuard wired to a freshly-generated
 * keypair. Returns the guard plus a token-minter so tests can mint
 * scenario-specific JWTs against the same key the verifier trusts.
 */
async function buildGuard(audit: (record: AuthAuditRecord) => void) {
  const keypair = await generateTestKeypair();
  // jose's createRemoteJWKSet is what JWKSCache wraps; for unit tests
  // we side-step the HTTP fetch by registering a static getter that
  // returns the keypair's public key directly. Same pattern used by
  // the parity runner.
  const jwks = {
    registeredIssuers(): ReadonlySet<string> {
      return new Set([TEST_ISSUER]);
    },
    keyResolverFor(_iss: string) {
      return keypair.getKey;
    },
    // Concrete JWKSCache has more methods, but verify() only touches
    // these two — duck-type to avoid spinning up the full cache.
  };
  const trustMap: IssuerTrustMap = {
    async resolve(_tenantId: string) {
      return { expectedIssuer: TEST_ISSUER, suspended: false };
    },
  };
  const guard = new AuthGuard({
    audience: TEST_AUDIENCE,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    jwks: jwks as any,
    trustMap,
    audit,
  });
  return { guard, keypair };
}

async function mintToken(
  keypair: TestEcdsaKeypair,
  overrides: { tenantSlug?: string } = {},
): Promise<string> {
  const opts: Parameters<typeof buildTestToken>[0] = {
    keypair,
    issuer: TEST_ISSUER,
    audience: TEST_AUDIENCE,
    subject: TEST_SUBJECT,
    tenantId: TEST_TENANT_ID,
    extraClaims: {},
  };
  if (overrides.tenantSlug !== undefined) {
    opts.extraClaims = { "https://forge/tenant_slug": overrides.tenantSlug };
  }
  return buildTestToken(opts);
}

describe("audit callback", () => {
  test("fires once on the allow path with the full record shape", async () => {
    const captured: AuthAuditRecord[] = [];
    const { guard, keypair } = await buildGuard((record) => {
      captured.push(record);
    });
    const token = await mintToken(keypair);

    await guard.verify(token);

    expect(captured).toHaveLength(1);
    const record = captured[0]!;
    expect(record.decision).toBe("allow");
    expect(record.audience).toBe(TEST_AUDIENCE);
    expect(record.audiences).toEqual([TEST_AUDIENCE]);
    expect(record.tsUnix).toBeGreaterThan(0);
    expect(record.tenantId).toBe(TEST_TENANT_ID);
    expect(record.subject).toBe(TEST_SUBJECT);
    expect(record.actor).toBeNull();
    expect(Array.isArray(record.scopes)).toBe(true);
    expect(record.jti).toBeDefined();
    expect(record.iss).toBe(TEST_ISSUER);
    expect(record.reason).toBeUndefined();
  });

  test("propagates tenant_slug from IdentityContext", async () => {
    const captured: AuthAuditRecord[] = [];
    const { guard, keypair } = await buildGuard((record) => {
      captured.push(record);
    });
    const token = await mintToken(keypair, { tenantSlug: "acme-corp" });

    await guard.verify(token);

    expect(captured).toHaveLength(1);
    expect(captured[0]!.tenantSlug).toBe("acme-corp");
  });

  test("tenant_slug is null when the claim is absent", async () => {
    // Stable-schema contract for downstream pipelines: the field is
    // present in the record (as null) rather than omitted, so JSON
    // consumers can rely on a fixed key set.
    const captured: AuthAuditRecord[] = [];
    const { guard, keypair } = await buildGuard((record) => {
      captured.push(record);
    });
    const token = await mintToken(keypair);

    await guard.verify(token);

    expect(captured).toHaveLength(1);
    expect(captured[0]!.tenantSlug).toBeNull();
  });

  test("does not fire on the deny path (cross-SDK forward-compat parity)", async () => {
    // Today's contract: Python + Node + Rust all emit on allow only.
    // The deny path is reserved as an extension point all three SDKs
    // flip together. Pinning the count here so a future change to
    // fire on deny lands across all three SDKs in lockstep.
    const captured: AuthAuditRecord[] = [];
    const { guard, keypair } = await buildGuard((record) => {
      captured.push(record);
    });
    // Mint with a wrong audience so verify rejects.
    const token = await buildTestToken({
      keypair,
      issuer: TEST_ISSUER,
      audience: "wrong-audience",
      subject: TEST_SUBJECT,
      tenantId: TEST_TENANT_ID,
    });

    await expect(guard.verify(token)).rejects.toBeDefined();
    expect(captured).toHaveLength(0);
  });
});
