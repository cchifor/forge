# Auth Architecture

How forge-generated projects authenticate users and services.

This document is the architectural reference for the auth stack
forge generates when `auth.mode = "generate"` (the default). For the
full implementation plan and rollout phasing, see the design doc at
`~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md`.
For the BFF + session-timeout RFC that drives the SPA half, see
`~/.claude/plans/analyze-the-following-issue-lovely-sonnet.md`.

## TL;DR

- **Keycloak** is the identity provider — login form, user store, OIDC
  authorization-code flow.
- **Gatekeeper** is the *sole* token authority for backend services.
  It mints ES256-signed JWTs from server-side state and serves them at
  `/auth/jwks`. Backends never trust Keycloak-issued tokens directly.
- **`platform-auth` SDKs** (Python, Node, Rust — one per backend
  language forge supports) are the verifier libraries. They expose a
  small public surface (`AuthGuard`, `IdentityContext`, `JWKSCache`,
  `S2SClient`, `MayActPolicy`, `IssuerTrustMap`, `RevocationStore`,
  scope matching, test-token minter) with cross-language parity
  enforced by a shared fixture suite.
- **Browser tokens never exist** — the SPA gets a single opaque
  `tenant_session_id` cookie; access + refresh tokens live server-side
  in Redis, encrypted with Fernet.
- **Sessions extend on real user activity**, not on background API
  traffic. The SPA explicitly POSTs `/auth/session` on
  mouse/keyboard/scroll/visibility events (debounced 30s,
  visibility-gated, BroadcastChannel-deduplicated across tabs).
- **Authorization is scope-based** with wildcard support
  (`<service>:<action>[:<resource>]`); RFC 8693 `act` chains carry
  on-behalf-of identities for service-to-service calls.

## Architecture diagram

```
Browser ──cookie──> Traefik ──ForwardAuth──> Gatekeeper(/auth) ──ES256 JWT──> Backend
                       │                       │                                │
                       │                       ├── Redis (sessions, body+active)
                       │                       ├── Keycloak (login form)
                       │                       ├── filesystem signing keys
                       │                       └── service_registry.yaml
                       │                                                        │
                       │                                                        │
                       └─── /auth/token ──── S2SClient (cached) ────────────────┤
                            /auth/jwks ──── JWKSCache (in each backend) ────────┘
```

The Phase 4 invariant: there is **one issuer, one JWKS, one audience**
per internal JWT that backends see. Backends do not trust Keycloak's
JWKS or its issuer URL — Keycloak's role is to authenticate the user
and hand the access+refresh tokens off to Gatekeeper, which then
mints the internal JWT.

## Components

### Keycloak (identity provider)

- Standard Keycloak install, one realm per project.
- Pre-configured with two clients in `infra/keycloak-realm.json`:
  - **`tms-web`** — public SPA client; PKCE-capable; standard
    authorization-code flow.
  - **`gatekeeper`** — confidential server client used by the
    Gatekeeper container itself (for the OIDC bridge + admin API
    calls). `serviceAccountsEnabled: true` so it can call the admin
    API to backfill the tenant attribute on freshly-registered
    users.
- Two protocol mappers on each client:
  - `gatekeeper-audience` (oidc-audience-mapper) — adds
    `aud: gatekeeper` to access tokens so Gatekeeper accepts them.
  - `tenant-id` (oidc-usermodel-attribute-mapper) — projects the
    user's `tenant_id` attribute into the
    `https://forge/tenant_id` claim. Backends consult this claim
    via the `AuthGuard` verifier.
- Realm JSON is validated at generate-time by
  `forge.docker_manager.render_keycloak_realm` — malformed JSON or
  missing required keys fail forge's generation rather than
  surfacing as `docker compose up` errors.

### Gatekeeper (token authority + BFF)

Source under `<project>/infra/gatekeeper/` (shipped by the
`platform_auth_gatekeeper` fragment). The container plays four
distinct roles:

#### 1. Traefik ForwardAuth interceptor

`GET /auth` is the single entry point for every authenticated route.
Traefik's `forwardauth` middleware calls it before forwarding the
request. Gatekeeper:

1. Reads the `tenant_session_id` cookie.
2. Calls `ServerSessionStore.check_validity(session_id, now)` —
   read-only; **does NOT** touch the session's idle TTL.
3. If the session is valid, mints an internal ES256 JWT with the
   appropriate claims and returns 200 + `Authorization: Bearer
   <jwt>` for Traefik to forward.
4. If the session is missing/expired, returns 302 to `/auth/login`.

The fact that `/auth` is read-only is load-bearing for the
inactivity-timeout discipline. See "Session lifecycle" below.

#### 2. Sole token authority (mint ES256 JWTs)

Phase 4 design — backends only trust tokens issued by Gatekeeper,
never Keycloak directly. Gatekeeper holds the ECDSA P-256 signing
keys at `/run/secrets/gatekeeper-signing/active.pem`, generated by
the `gatekeeper-keygen` init service before Gatekeeper boots. Public
keys are served at `GET /auth/jwks` for backend verification.

The internal JWT carries:
- `iss`: `http://gatekeeper:5000` (or the configured issuer URL)
- `aud`: the target service audience (e.g., `forge-services`,
  `svc-things`)
- `sub`: the upstream user's subject
- `exp`: `now + 300` (5-minute TTL — bounds the revocation
  latency)
- `jti`: random per-mint
- `https://forge/tenant_id`: the tenant UUID
- `roles` / `scope`: from the upstream Keycloak claims, plus any
  service-registry-driven additions
- `act` (when minted via on-behalf-of): RFC 8693 actor chain

Algorithm pinned to ES256 — `none` and HS\* are hard-rejected at
the verifier so a misconfigured caller can't downgrade.

#### 3. Backend-for-Frontend session manager

The browser holds **one** cookie: `tenant_session_id` (24-byte
URL-safe random, `HttpOnly`, `Secure`, `SameSite=Lax`,
`Max-Age=absolute_timeout_seconds`). Server-side state lives in
Redis under two keys per session:

| Key | Contents | TTL | Lifecycle |
| --- | --- | --- | --- |
| `gk:session:{id}:body` | Fernet-encrypted JSON: `access_token`, `refresh_token`, `tenant_id`, `sub`, `login_time`, `idle_timeout_seconds`, `absolute_timeout_seconds` | `absolute_timeout_seconds` | Set once at `/callback`. **Never extended** — disappearance = absolute expiry. |
| `gk:session:{id}:active` | `"1"` (plain string) | `idle_timeout_seconds` | Set on `/callback`; refreshed on every `touch` via a single atomic `SET ... EX`. **Disappearance = idle expiry.** |

The two-key model keeps atomicity reducible to single Redis
commands — no Lua, no read-evaluate-write race window. `touch` is
one `SET`; `check_validity` is one `MGET`. Concurrent touches both
succeed (both saw activity, both extended) — last-write-wins is
correct semantics.

`SameSite=Lax` (not `Strict`) allows deep-linking from external
tools (Slack, email, intranet portals) to land in the app already
authenticated. CSRF is mitigated at the API layer via
`Content-Type: application/json` + CORS preflight on every
mutating endpoint — per OWASP 2024–2025 SaaS-cookie guidance.

#### 4. Service-to-service token issuer

`POST /auth/token` is the OAuth2-style endpoint backends call when
they need to make an authenticated call to a sibling service.
Gatekeeper supports two grants:

- `client_credentials` — bare machine-identity token (no `sub`,
  no user context). The caller authenticates via its registered
  client_id + client_secret (argon2id-hashed in
  `secrets/service_registry.yaml`); the response carries a token
  audienced for the target service with the scopes the registry
  permits.
- `urn:ietf:params:oauth:grant-type:token-exchange` (RFC 8693) —
  on-behalf-of delegation. Caller passes its own credentials plus
  a `subject_token` (the inbound user token). Gatekeeper mints a
  new token preserving the user's `sub` and tenant, with `act`
  recording the calling service. Downstream verifies the chain
  via its `MayActPolicy`.

The service registry is loaded from
`/run/secrets/gatekeeper-service-registry/service_registry.yaml`.
Each entry maps `client_id → audiences → scopes`:

```yaml
- client_id: svc-workflow
  secret: argon2id-hash-of-the-secret
  audiences:
    svc-knowledge:
      scopes: [knowledge:read]
    svc-mcp:
      scopes: [mcp:read, mcp:write]
```

### Backend verifier SDKs

Three fragments ship one verifier SDK per backend language:

| Language | Fragment | SDK location | JWT lib |
| --- | --- | --- | --- |
| Python | `platform_auth_sdk_python` | `<project>/sdks/platform-auth/` | PyJWT |
| Node | `platform_auth_sdk_node` | `<project>/sdks/platform-auth-node/` | `jose` |
| Rust | `platform_auth_sdk_rust` | `<project>/sdks/platform-auth-rs/` | `jsonwebtoken` |

All three expose the same public surface:

- `AuthGuard` — verifies `Authorization: Bearer <jwt>` and returns an
  `IdentityContext`. Algorithm-pinned, audience-validated, required-
  claims-checked, tenant-claim-validated, RFC 8693 act-chain-walked,
  revocation-checked.
- `IdentityContext` — frozen object with `tenant_id`, `subject`,
  `roles`, `scopes`, `actor`, `raw_claims`. Helper methods:
  `has_scope` / `has_any_scope` / `has_all_scopes` /
  `is_platform_admin` / `is_actor`.
- `JWKSCache` — multi-issuer cache with stale-serve fallback. Holds
  the JWKS document for each registered issuer; refreshes every
  10 min by default, serves stale for up to 30 min during upstream
  outages, single-flight on key rotation. Per-language
  implementations leverage native lib affordances (`jose.createRemoteJWKSet`
  in Node, `tokio::sync::Mutex` for the per-issuer refresh in Rust).
- `S2SClient` — outbound HTTP client targeting a single audience.
  Caches client_credentials and on-behalf-of tokens per-user-jti;
  refreshes 60s before expiry; 401 retry-once. (Phase 4/6 follow-up
  for Node + Rust; Python ships today.)
- `MayActPolicy` — RFC 8693 act-chain authorization. Two
  implementations: `AllowAllMayActPolicy` (test-only) and
  `StaticMayActPolicy` (fixed `actor → audience` allowlist).
- `IssuerTrustMap` — per-tenant expected issuer + suspension flag.
  Implementations: `InMemoryIssuerTrustMap` (fixed) +
  `CachingIssuerTrustMap` (TTL cache around any backing impl).
- `RevocationStore` — pluggable jti denylist.
- `scope_satisfies` — wildcard-aware scope matching.
- `testing.{py,ts,rs}` — `build_test_token` + `TestEcdsaKeypair` +
  `jwks()` for unit tests minting AuthGuard-verifiable JWTs without
  needing a running Gatekeeper. Cross-language parity gate at
  `forge/tests/contract/auth_sdk_parity/` (Phase 9).

Public-API stability is enforced by per-language invariants tests
(`tests/test_features_auth_*_sdk.py`) plus the cross-SDK parity
fixture suite. `reason()` slugs on `AuthError` are part of the
public cross-language contract — clients dispatch on them.

### Frontend session-timeout components

Three fragments ship per-frontend session-timeout pieces:

| Frontend | Fragment | Location |
| --- | --- | --- |
| Vue 3 | `platform_auth_session_timeout_vue` | `apps/frontend/src/shared/composables/useSessionTimeout.ts` + `apps/frontend/src/features/auth/components/SessionTimeoutModal.vue` |
| Svelte 5 | `platform_auth_session_timeout_svelte` | `apps/frontend/src/lib/core/auth/session-timeout.svelte.ts` + `apps/frontend/src/lib/features/auth/components/SessionTimeoutModal.svelte` |
| Flutter | `platform_auth_session_timeout_flutter` | `apps/frontend/lib/src/features/auth/data/session_timeout_service.dart` + `apps/frontend/lib/src/features/auth/presentation/session_timeout_modal.dart` |

Each implements the same RFC-mandated SPA pattern:

- **Drift-immune countdown** — store `idleExpiresAt` (absolute target
  timestamp); recompute remaining via `Date.now()` (Vue/Svelte) or
  `DateTime.now()` (Flutter) at read time. Throttled / suspended
  apps catch up instantly when foregrounded.
- **Cross-tab leader election** (web only) — `BroadcastChannel`
  ensures only one tab POSTs per activity burst; siblings receive
  the resulting `expiresAt` and sync locally. Flutter web ships
  this in a follow-up `dart:js_interop` binding; Flutter native has
  exactly one app instance per device, so no dedup needed.
- **Visibility gating** — extensions only fire when
  `document.visibilityState === 'visible'` (web) or
  `AppLifecycleState.resumed` (Flutter). A backgrounded tab's
  outside-window events are ignored.
- **30-second debounce** on activity events — `mousemove`,
  `keydown`, `scroll`, `visibilitychange`. Defends against
  hammering the server's 4/min/session rate limit on every mouse
  twitch.
- **Silent disable** when bootstrap returns 401 (unauthenticated
  route) OR when timeouts come back as 0 (server-side disabled).
- **Endpoint semantics** — `GET /auth/session` is read-only;
  `POST /auth/session` is the *only* code path that touches the
  session's `:active` TTL.

The pre-warning modal opens at `T - warn_at_seconds` from idle
expiry. "Stay signed in" force-fires `extend()`, bypassing the
debounce. "Sign out" navigates to `/logout`.

## Token flow walkthroughs

### Browser login

```
1. User → /protected
2. Traefik → ForwardAuth → Gatekeeper /auth
3. Gatekeeper: no tenant_session_id cookie → 302 /auth/login
4. /auth/login → 302 Keycloak /auth (with PKCE state)
5. User authenticates in Keycloak → Keycloak → /callback?code=...
6. Gatekeeper /callback:
     a. exchange_code(code) → access_token, refresh_token, claims
     b. (optional) admin-API backfill if claims lack tenant_id
     c. ServerSessionStore.issue(...) → session_id
     d. Set-Cookie: tenant_session_id=<id>; HttpOnly; Lax; Max-Age=43200
     e. 302 /protected
7. User → /protected (now with cookie)
8. Traefik → ForwardAuth → Gatekeeper /auth
9. Gatekeeper:
     a. check_validity(session_id) → ServerSession
     b. mint_internal_jwt(...) → ES256 JWT
     c. 200 + Authorization: Bearer <jwt> + Set-Cookie (refresh)
10. Traefik forwards → Backend with Authorization header
11. Backend AuthGuard.verify(token) → IdentityContext on req.state
12. Handler: identity.has_scope("things:read") → 200 with data
```

### Service-to-service (on-behalf-of)

```
1. Service A handler (e.g., svc-workflow) holds the inbound user token
   on req.state.identity.raw_claims (or its language equivalent).
2. Wants to call svc-knowledge on behalf of the user:
     S2SClient(audience="svc-knowledge").get(
         "https://knowledge.svc/api/items",
         on_behalf_of=request.headers["authorization"],  # the inbound bearer
     )
3. S2SClient cache-hits or POSTs Gatekeeper /auth/token:
     grant_type: urn:ietf:params:oauth:grant-type:token-exchange
     subject_token: <user_token>
     audience: svc-knowledge
     client_id + client_secret: svc-workflow's registry creds
4. Gatekeeper:
     a. authenticate svc-workflow via service_registry.yaml argon2id check
     b. verify subject_token (svc-workflow's audience)
     c. mint new token: sub=user, tenant=user.tenant, aud=svc-knowledge,
        act={client_id: svc-workflow}
5. S2SClient receives the token; caches by (audience, user-jti);
   sends GET to knowledge with Authorization: Bearer <delegated_token>.
6. svc-knowledge AuthGuard:
     a. verify signature, audience, expiry, etc.
     b. walk act chain: ask MayActPolicy.is_authorized("svc-workflow",
        "svc-knowledge"). Allowlist matches → ok.
     c. IdentityContext{tenant_id=user.tenant, subject=user.sub,
        actor="svc-workflow"} → req.state.identity.
7. Handler authorises and serves; downstream sees the user's tenant
   for row-level filtering, with the elevated audit trail recording
   svc-workflow as the actor.
```

### Inactivity-driven session refresh

```
SPA mount → useSessionTimeout.bootstrap()
  → GET /auth/session → {idle_remaining_seconds: 1800, ...}
  → applyState: idleExpiresAt = now + 1800*1000

User moves the mouse:
  → onUserActive() debounce-armed for 30s.

30s later (no further activity bursts collapsed in):
  → BroadcastChannel.post({type: 'activity-claim', timestamp: T})
  → wait 50ms for sibling claims
  → no sibling beat us → POST /auth/session
  → Gatekeeper:
       a. rate-limit check (4/min/session)
       b. ServerSessionStore.touch(session_id, now) → SET :active EX 1800
       c. respond {idle_remaining_seconds: 1800, ...}
  → applyState
  → BroadcastChannel.post({type: 'extended', expiresAt: ...}) for siblings.

User idles for 30 min:
  → no POST → :active key TTL expires in Redis.
  → Traefik → ForwardAuth → Gatekeeper /auth
  → check_validity → :active gone → 302 /auth/login.

Modal at idleRemaining ≤ 60:
  → display "You'll be signed out in 60s"
  → "Stay signed in" → session.extend() → POST /auth/session → reset.
```

## Configuration knobs

All knobs default to safe production values. Override via env vars
on the gatekeeper service, or per-tenant via `TenantConfig` (which
the gatekeeper resolves from Redis with a 60s in-process cache).

| Variable | Default | Purpose |
| --- | --- | --- |
| `GATEKEEPER_ISSUER` | `http://gatekeeper:5000` | iss claim on internal JWTs |
| `INTERNAL_TOKEN_AUDIENCE` | `forge-services` | aud claim on internal JWTs |
| `INTERNAL_TOKEN_TTL_SECONDS` | `300` | Internal JWT lifetime |
| `KEY_BACKEND` | `file` | `file` ships today; `aws_kms`/`vault` are follow-ups |
| `SIGNING_KEY_DIR` | `/run/secrets/gatekeeper-signing` | Where keygen writes ECDSA keys |
| `SESSION_FERNET_KEY` | (env-required) | Symmetric key for body encryption — rotation invalidates all sessions |
| `SESSION_TIMEOUT_ENABLED` | `true` | PR 2 in platform's RFC; flip to `false` to disable timeouts entirely |
| `DEFAULT_IDLE_TIMEOUT_SECONDS` | `1800` (30 min) | Idle-expiry default; per-tenant override available |
| `DEFAULT_ABSOLUTE_TIMEOUT_SECONDS` | `43200` (12 h) | Absolute-expiry default; per-tenant override available |
| `SESSION_WARN_AT_SECONDS` | `60` | SPA pre-warning modal threshold |
| `SERVICE_REGISTRY_PATH` | `/run/secrets/gatekeeper-service-registry/service_registry.yaml` | argon2id-hashed S2S credentials |
| `SVC_AUTH_BACKEND` | `preshared` | `k8s` (projected SA tokens) and `mtls` are follow-ups |
| `TENANT_ID_CLAIM` | `https://forge/tenant_id` | JWT claim name for the tenant UUID |
| `DEFAULT_RATE_LIMIT` | `600` | requests/minute per tenant — distinct from session-extension rate limit (4/min/session) |

## Compliance notes

- **NIST 800-63B-4 (Jan 2026)** — implicit "user genuinely absent"
  semantics for inactivity timeouts. Forge's session model honors
  this by treating only real user-interaction events as activity,
  not background API traffic. See platform's RFC for the trade-off
  analysis.
- **SOC 2 / ISO 27001** — common controls mandate idle-session
  termination at 15-30 min plus an absolute cap. Forge's defaults
  (30 min idle / 12 h absolute) sit at the strict end of that range
  and are configurable per-tenant.
- **OWASP 2024-2025 SaaS cookie guidance** — `SameSite=Lax` +
  `HttpOnly` + `Secure` + API-layer JSON enforcement. CSRF is
  mitigated at the API layer (Content-Type + CORS preflight) since
  `Lax` doesn't fully block cross-site form posts.
- **RFC 8693 token-exchange** — full implementation of the
  on-behalf-of grant, with `act` chain validation enforced via
  `MayActPolicy`.
- **RFC 9068 (JWT Profile for OAuth 2.0 Access Tokens)** — required
  claims (`iss`, `aud`, `sub`, `exp`, `iat`, `jti`) enforced at
  AuthGuard verification time.

## Migration from legacy

The pre-Phase-2 stack used Keycloak as the issuer directly with
forge's older Gatekeeper acting as a header-injecting ForwardAuth
proxy. The migration to the new model goes through:

1. `forge --update --mode=merge` — picks up the new fragment trees
   (SDK + token-authority Gatekeeper + session-timeout frontend).
2. `forge --migrate auth-keycloak-to-platform-auth` (Phase 10
   codemod) — replaces per-backend auth modules, swaps the
   gatekeeper image, updates the realm.json with the
   `https://forge/tenant_id` mapper + service-account flag, renames
   `KEYCLOAK_*` env vars to `GATEKEEPER_*` where the key has moved
   owner. User edits collide as `.forge-merge` sidecars.
3. `docker compose up --build` — `gatekeeper-keygen` runs first and
   writes ECDSA P-256 keys to the shared volume; `gatekeeper`
   starts; backends boot with the new SDK.

For the migration procedure step-by-step, see `UPGRADING.md`.

## Cutover status (in-flight)

The auth-stack rebuild ships in two waves. **Wave 1** is complete: all
eleven fragments are registered, the SDKs ship per-language, the
session-timeout composables ship per-frontend, the cross-SDK parity
gate is live. **Wave 2** — the load-bearing replacement of the legacy
service-template auth modules — is still in flight.

Because Wave 2 is a coordinated multi-file refactor that touches the
caller graph of every backend's IOC, lifecycle, endpoints, and tests in
lockstep, it lands as an explicit, separately-reviewable change rather
than as part of the SDK rollout. Today the SDK + middleware fragments
are shipped but **dormant for backend wiring**: `auth.mode=generate`
enables 6 of 11 fragments (the three SDKs + the three frontend session-
timeout integrations); the four backend middleware fragments and the
two gatekeeper-as-token-authority fragments are registered but not yet
opted-in by default.

| Wave-2 follow-up | Blocker | Surface area |
| --- | --- | --- |
| `platform_auth_python_middleware` cutover | replace `service/security/providers/{keycloak,dev}.py` and update its 11 callers in lifecycle / IOC / endpoints / repos / tests | python-service-template |
| `platform_auth_node_middleware` cutover | replace `middleware/tenant.ts` and update ~47 `TenantContext` references | node-service-template |
| `platform_auth_rust_middleware` cutover | replace `middleware/tenant.rs` and update its `TenantContext` extractor consumers | rust-service-template |
| `platform_auth_gatekeeper` + `_keygen` cutover | remove imperative gatekeeper service block + `forge/templates/infra/gatekeeper/` legacy tree; declarative compose fragments take over | infra |

Until Wave 2 lands, a generated project that opts into `auth.mode=generate`
gets the new SDKs + session-timeout SPA pieces alongside the legacy
backend middleware. The SDKs are usable directly (a project owner can
wire `AuthGuard` themselves), but the templated middleware path still
runs through the pre-port code. The Phase 10 codemod
(`forge --migrate auth-keycloak-to-platform-auth`) targets the *post*-
Wave-2 state — running it before the cutover lands is correct only for
the SDK + frontend deltas; the backend middleware rewrite portion is
a no-op until the new fragments are wired.

## Out of scope (follow-up tickets)

Per the platform RFC, these are intentionally deferred. The forge
plan inherits the same scope split:

- **Step-up auth for sensitive operations** — `require_auth_freshness`
  + `auth_time` claim + re-auth UI.
- **Session-id rotation on privilege change** — OWASP fixation
  defense.
- **IETF Shared Signals (RFC 8417 SSE) / CAEP** — real-time session
  revocation across systems. Depends on Keycloak SSE support.
- **Risk-adaptive timeouts** — shorter sessions for admin role / new
  device / geo anomaly.
- **Concurrent-session limits** — "max 3 concurrent sessions per
  user."
- **Mobile / native client refresh** — non-browser clients need an
  explicit refresh-token model. Flutter's native target ships a stub
  that bypasses session-timeout enforcement until that workstream
  lands.
- **Alternative `KEY_BACKEND`s** — `aws_kms`, `vault`, `gcp_kms`.
- **`@forge/platform-auth-web` shared SPA SDK** — currently each
  frontend gets its own copy of `useSessionTimeout` +
  `SessionTimeoutModal`; factoring out a shared cross-framework SDK
  is a follow-up.
