# `@forge/platform-auth-node`

Identity, RBAC, and S2S authentication primitives for Fastify services. Node port of [`platform-auth` (Python)](../platform-auth/) shipped by the same forge auth feature.

## Status

Greenfield port — feature parity with the Python SDK is enforced by the cross-SDK parity test suite (`forge/tests/contract/auth_sdk_parity/`). The initial cut covers token verification, scope matching, trust mapping, may-act policy, and the JWKS cache. The Fastify plugin (`./plugin.js`), `S2SClient`, and the test-token minter (`./testing.js`) ship in follow-up phases.

## Install

The SDK is a workspace package shipped under `sdks/platform-auth-node/` in every forge project that opts into `auth.mode=generate` and has at least one Node backend. Reference it from the backend's `package.json`:

```jsonc
{
  "dependencies": {
    "@forge/platform-auth-node": "workspace:*"
  }
}
```

## Usage

```ts
import {
  AuthGuard,
  JWKSCache,
  InMemoryIssuerTrustMap,
  StaticMayActPolicy,
} from "@forge/platform-auth-node";

const jwks = new JWKSCache();
jwks.registerIssuer(
  process.env.GATEKEEPER_ISSUER!,
  `${process.env.GATEKEEPER_ISSUER}/auth/jwks`,
);

const auth = new AuthGuard({
  audience: process.env.SERVICE_AUDIENCE!,
  jwks,
  trustMap: new InMemoryIssuerTrustMap({
    "00000000-0000-0000-0000-000000000001": {
      expectedIssuer: process.env.GATEKEEPER_ISSUER!,
      suspended: false,
    },
  }),
  mayAct: new StaticMayActPolicy({
    // Keyed audience → allowed-actors. "For svc-things, only
    // svc-workflow may act." Deny-by-default.
    "svc-things": ["svc-workflow"],
  }),
  algorithms: ["ES256"],
  tenantIdClaim: "https://forge/tenant_id",
});

// In a Fastify route's pre-handler:
const identity = await auth.verifyRequest(request);
if (!identity.hasScope("things:read")) {
  reply.code(403).send({ error: "forbidden" });
  return;
}
return repo.list({ tenantId: identity.tenantId });
```

## Design parity

| Python module | Node module | Notes |
| --- | --- | --- |
| `auth_guard.py::AuthGuard` | `AuthGuard.ts` | Uses jose's `jwtVerify` instead of PyJWT's `decode` |
| `auth_guard.py::require_scope` | `AuthGuard.ts::requireScope` | Returns a Fastify pre-handler |
| `identity.py::IdentityContext` | `IdentityContext.ts` | Frozen object; `hasScope/hasAnyScope/hasAllScopes` |
| `jwks.py::JWKSCache` | `JWKSCache.ts` | Wraps `createRemoteJWKSet` per issuer |
| `s2s_client.py::S2SClient` | `S2SClient.ts` | (follow-up) |
| `scopes.py::scope_satisfies` | `scopes.ts::scopeSatisfies` | Exact + trailing wildcard |
| `trust.py::IssuerTrustMap` | `trust.ts::IssuerTrustMap` | Async lookup; `InMemory` + `Caching` |
| `may_act.py::MayActPolicy` | `may_act.ts::MayActPolicy` | `AllowAll` + `Static` |
| `revocation.py::RevocationStore` | `revocation.ts::RevocationStore` | `InMemory` + `NeverRevoked` |
| `exceptions.py::*` | `exceptions.ts::*` | Same `reason` slugs + `statusCode` |
| `testing.py::*` | `testing.ts::*` | (follow-up) |

`reason` slugs and HTTP status codes are part of the public cross-language contract — clients and metrics dashboards dispatch on them — so changing one is a parity-breaking change.

## Testing parity

`forge/tests/contract/auth_sdk_parity/` ships shared JWT fixtures (valid / expired / wrong-issuer / wrong-audience / wrong-alg / RFC 8693 act chain / invalid signature). Each SDK runs the same fixtures through its `AuthGuard.verify()` and asserts matching outcomes — same `IdentityContext` on success, same `AuthError` subclass on failure.

## Cross-reference

- Implementation plan: `~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md` (Phase 4 deliverables).
- Python SDK: `sdks/platform-auth/`.
- Rust SDK: `sdks/platform-auth-rs/` (Phase 6).
