# platform-auth

Identity, RBAC, and service-to-service authentication primitives for the platform services.

This SDK is the single point of truth for how the platform validates JWT bearer
tokens, propagates tenant identity, and enforces scope-based access control. It
is consumed by every application service (and TMS) via editable install.

## Public API

- `IdentityContext` — the verified identity of the caller (tenant, subject,
  roles, scopes, actor).
- `AuthGuard` — FastAPI dependency that validates `Authorization: Bearer`
  tokens against issuer / audience / signature / expiry / revocation and
  returns an `IdentityContext`.
- `Scope` — `StrEnum` of platform permissions, with explicit hierarchy
  (`<service>:*` covers `<service>:read|write|admin`).
- `require_scope(*scopes)` — FastAPI dependency factory that 403s when the
  caller's scopes do not satisfy the required ones.
- `S2SClient` — async httpx wrapper that obtains audience-restricted tokens
  via OAuth2 client_credentials or RFC 8693 token-exchange and attaches them
  to outbound calls.
- `JWKSCache` — multi-issuer JWKS cache with key-rotation handling and
  graceful degradation.
- `RevocationStore` — Redis-backed `jti` denylist consulted by `AuthGuard`.

## Status

Foundation workstream (WS1) of the platform multi-tenancy and security
improvement plan. See `docs/architecture/decisions/0001-hybrid-realm-topology.md`
and surrounding ADRs for the architectural context.
