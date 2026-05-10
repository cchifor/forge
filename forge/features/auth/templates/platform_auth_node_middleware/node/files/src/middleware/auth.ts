/**
 * Auth middleware bootstrap — Node service template.
 *
 * Wires the @forge/platform-auth-node SDK into Fastify's lifecycle.
 * Constructs an AuthGuard from environment-driven config, registers
 * the platformAuthPlugin (which adds the onRequest verifier hook + the
 * `app.requireScope(...)` decorator), and exports a bootstrap helper
 * that ``src/app.ts`` calls during plugin registration.
 *
 * Mirrors the Python service-template's ``app/middleware/auth_context.py``
 * + ``service/security/platform_auth_setup.py`` shape for Node:
 * single-pass verification, decorated request, RFC 7807 error
 * mapping, health/metrics/docs skip-list.
 *
 * Phase 3 (Python middleware) and Phase 5 (this file) preserve the
 * cross-language correctness contract — same env vars, same defaults,
 * same skip-list.
 */

import {
  AuthGuard,
  InMemoryIssuerTrustMap,
  JWKSCache,
  platformAuthPlugin,
  StaticMayActPolicy,
  type IssuerTrustMap,
  type MayActPolicy,
} from "@forge/platform-auth-node";
import type { FastifyInstance } from "fastify";

const _DEFAULT_ALGORITHMS = ["ES256"] as const;
const _DEFAULT_TENANT_ID_CLAIM = "https://forge/tenant_id";

/**
 * Build an AuthGuard from environment variables.
 *
 * Reads the same env keys the Gatekeeper container exposes:
 *  - ``GATEKEEPER_ISSUER`` — iss claim on internal JWTs
 *  - ``SERVICE_AUDIENCE`` — this service's expected aud claim
 *  - ``GATEKEEPER_ISSUER`` + ``/auth/jwks`` — JWKS endpoint
 *  - ``TENANT_ID_CLAIM`` (optional) — defaults to ``https://forge/tenant_id``
 *
 * Optional advanced wiring:
 *  - ``trustMap`` — pass an IssuerTrustMap implementation to enable
 *    per-tenant issuer enforcement. The default registers a single
 *    issuer (GATEKEEPER_ISSUER) and treats it as trusted for all
 *    tenants — fine for single-tenant deployments and dev.
 *  - ``mayActPolicy`` — pass a MayActPolicy to enable RFC 8693
 *    on-behalf-of authorization. The default rejects every actor
 *    (deny-by-default) — safe for services that don't expect S2S
 *    delegation.
 */
export interface AuthBootstrapOptions {
  /** Override the IssuerTrustMap. Default: in-memory trust for the gatekeeper issuer. */
  trustMap?: IssuerTrustMap;
  /** Override the MayActPolicy. Default: deny-all (no actor authorized). */
  mayActPolicy?: MayActPolicy;
  /** Skip-paths override. Defaults match the SDK's plugin defaults. */
  excludePaths?: readonly string[];
}

export async function bootstrapAuth(
  app: FastifyInstance,
  options: AuthBootstrapOptions = {},
): Promise<void> {
  const issuer = process.env.GATEKEEPER_ISSUER;
  const audience = process.env.SERVICE_AUDIENCE;
  if (!issuer) {
    throw new Error(
      "GATEKEEPER_ISSUER environment variable is required for auth wiring",
    );
  }
  if (!audience) {
    throw new Error(
      "SERVICE_AUDIENCE environment variable is required for auth wiring",
    );
  }

  const jwks = new JWKSCache();
  jwks.registerIssuer(issuer, `${issuer}/auth/jwks`);

  const authGuard = new AuthGuard({
    audience,
    jwks,
    algorithms: [..._DEFAULT_ALGORITHMS],
    tenantIdClaim: process.env.TENANT_ID_CLAIM ?? _DEFAULT_TENANT_ID_CLAIM,
    trustMap:
      options.trustMap ??
      new InMemoryIssuerTrustMap(
        new Map(), // empty by default — production deployments inject a real trust map
      ),
    mayAct:
      options.mayActPolicy ??
      new StaticMayActPolicy(new Map()), // deny-all by default
  });

  await app.register(platformAuthPlugin, {
    authGuard,
    excludePaths: options.excludePaths,
  });
}
