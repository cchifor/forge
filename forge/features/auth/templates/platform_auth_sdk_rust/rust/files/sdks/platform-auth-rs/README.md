# `platform-auth` (Rust SDK)

Identity, RBAC, and S2S authentication primitives for Axum services. Rust port of [`platform-auth` (Python)](../platform-auth/) shipped by the same forge auth feature.

## Status

Greenfield port — feature parity with the Python SDK is enforced by the cross-SDK parity test suite (`forge/tests/contract/auth_sdk_parity/`). The initial cut covers token verification, scope matching, trust mapping, may-act policy, the JWKS cache, and the revocation store. The Tower/Axum integration (`AuthLayer` + `FromRequestParts<IdentityContext>`), `S2SClient`, and the test-token minter ship in follow-up phases.

## Install

The SDK is a workspace package shipped under `sdks/platform-auth-rs/` in every forge project that opts into `auth.mode=generate` and has at least one Rust backend. Reference it from the backend's `Cargo.toml`:

```toml
[dependencies]
platform-auth = { path = "../sdks/platform-auth-rs" }
```

Enable the optional `axum` feature when you want the Tower layer + extractor:

```toml
[dependencies]
platform-auth = { path = "../sdks/platform-auth-rs", features = ["axum"] }
```

## Usage

```rust
use std::sync::Arc;
use platform_auth::{AuthGuard, AuthGuardConfig, JwksCache, InMemoryIssuerTrustMap, TenantTrust};

let jwks = Arc::new(JwksCache::with_defaults()?);
jwks.register_issuer(
    "http://gatekeeper:5000",
    "http://gatekeeper:5000/auth/jwks",
).await?;

let mut config = AuthGuardConfig::new("svc-things", jwks);
config.trust_map = Some(Arc::new(InMemoryIssuerTrustMap::with_tenants([
    ("00000000-0000-0000-0000-000000000001".to_string(), TenantTrust {
        expected_issuer: "http://gatekeeper:5000".into(),
        suspended: false,
    }),
])));

let auth = AuthGuard::new(config)?;

// In an Axum handler (with the `axum` feature):
async fn list_things(identity: IdentityContext) -> Result<Json<Vec<Thing>>, ApiError> {
    if !identity.has_scope("things:read") {
        return Err(ApiError::forbidden());
    }
    repo.list(identity.tenant_id).await
}
```

## Design parity

| Python module | Node module | Rust module |
| --- | --- | --- |
| `auth_guard.py::AuthGuard` | `AuthGuard.ts` | `auth_guard.rs` |
| `identity.py::IdentityContext` | `IdentityContext.ts` | `identity.rs` |
| `jwks.py::JWKSCache` | `JWKSCache.ts` | `jwks.rs` |
| `s2s_client.py::S2SClient` | `S2SClient.ts` (deferred) | `s2s_client.rs` (deferred) |
| `scopes.py::scope_satisfies` | `scopes.ts::scopeSatisfies` | `scopes.rs::scope_satisfies` |
| `trust.py::IssuerTrustMap` | `trust.ts::IssuerTrustMap` | `trust.rs::IssuerTrustMap` |
| `may_act.py::MayActPolicy` | `may_act.ts::MayActPolicy` | `may_act.rs::MayActPolicy` |
| `revocation.py::RevocationStore` | `revocation.ts::RevocationStore` | `revocation.rs::RevocationStore` |
| `exceptions.py::*` | `exceptions.ts::*` | `errors.rs::AuthError::*` |
| `testing.py::*` | `testing.ts::*` (deferred) | `testing.rs::*` (deferred) |

`reason()` slugs (and HTTP status codes) on `AuthError` are part of the public cross-language contract — clients and metrics dashboards dispatch on them — so changing one is a parity-breaking change.

## Testing parity

`forge/tests/contract/auth_sdk_parity/` ships shared JWT fixtures (valid / expired / wrong-issuer / wrong-audience / wrong-alg / RFC 8693 act chain / invalid signature). Each SDK runs the same fixtures through its `AuthGuard::verify()` and asserts matching outcomes — same `IdentityContext` on success, same `AuthError` variant on failure.

## Cross-reference

- Implementation plan: `~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md` (Phase 6 deliverables).
- Python SDK: `sdks/platform-auth/`.
- Node SDK: `sdks/platform-auth-node/`.
