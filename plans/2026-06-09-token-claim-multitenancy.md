# Make `token_claim` multitenancy function — the **platform-faithful** way

> Rewritten to mirror platform (`/home/c4/platform`, github.com/cchifor/platform),
> which runs this design in production. Supersedes the earlier "Option B+/D"
> drafts. Two codex rounds on those drafts confirmed the root cause and surfaced
> the double-verify / resolver-reconciliation / fail-closed issues that the
> platform approach resolves by construction.

## How platform does it (the reference chain, verified in code)

Platform has **no `tenant_resolution` / `tenant_claim_path` / resolver / tenant
middleware / engine-begin-listener at all.** The tenant flows on ONE path:

1. **Global `AuthContextMiddleware`** (`services/*/src/app/main.py:55`,
   `middleware/auth_context.py`) runs before route handlers: calls
   `authenticate_request(request)` → verifies the bearer JWT, extracts the tenant
   from the configured claim (`AuthGuard.tenant_id_claim`, default
   `https://platform/tenant_id`), and stashes `request.state.identity` +
   `request.state.user` + sets `customer_id_context`/`user_id_context` ContextVars.
   Fail-open on no token (anonymous continues), fail-closed (401) on a bad token.
2. **DI reads the cached identity — no re-verify.** `SecurityProvider.get_current_user`
   (`ioc/security.py:31-33`): `cached = getattr(request.state, "user", None); user
   = cached if cached is not None else await authenticate_request(request)`. This is
   how platform has BOTH a global middleware AND DI without double-verification.
3. **Tenant-scoped UoW from the account.** `get_auth_uow` builds
   `Account(customer_id=user.customer_id, …)` → `AsyncUnitOfWork(account=…)`;
   `get_public_uow` builds `AsyncUnitOfWork(account=None)` (`ioc/security.py:38-53`).
4. **GUC bound at the UoW, inside the transaction.** `AsyncUnitOfWork.__aenter__` →
   `_apply_session_gucs` → `set_tenant_context(session, account.customer_id)` →
   `SELECT set_config('app.current_tenant', :t, true)` (`uow/aio.py:26-41`). RLS
   policies filter on `app.current_tenant`. `account=None` (PublicUnitOfWork) binds
   nothing → RLS **fails closed** (zero rows).

The tenant is the **authenticated** tenant, set ONCE in the auth layer's claim
config. No second source, no pre-auth resolution, no spoofable header.

## Why forge's token_claim is broken (root cause, codex-confirmed)

forge bolted a *parallel* mechanism on top of an already-working account path:
- forge_core's UoW already binds `app.current_tenant` from `account.customer_id`
  post-auth (so shared_rls works — `unit_of_work.py:118,131,64`), but the
  multitenancy fragment ALSO ships a `TenantResolver` + tenant middleware + engine
  begin-listener that run **pre-auth** (`tenant_rls.py:56`, `resolver.py:114`) and
  no-op for token_claim, because forge **never registers** the `AuthContextMiddleware`
  it ships (no inject.yaml), and forge's DI **re-verifies** instead of reading a
  cached identity. `schema_per_tenant` has *only* the broken pre-auth path (no UoW
  search_path hook) → fully non-functional.

## Plan: adopt platform's chain on forge's seams

### P1 — Register `AuthContextMiddleware` + read the cached identity in DI
- Add the missing **inject.yaml** to `platform_auth_python_middleware` registering
  `app.add_middleware(AuthContextMiddleware)` at `FORGE:MIDDLEWARE_REGISTRATION`,
  ordered so it runs **before** route handlers (binds `request.state.identity`/`.user`).
  Gate to `auth.mode=generate` (the fragment is already in that enables-tuple).
  Keep its `_DEFAULT_EXCLUDED_PATHS` (health/docs/metrics/redoc); fail-open on
  no-token (public routes still work → PublicUnitOfWork → fail-closed at DB).
- Add the **cached-identity short-circuit** to forge's `SecurityProvider.get_current_user`
  (`ioc/security.py`) — read `request.state.user` if present, else `authenticate_request`.
  This is platform's exact pattern and **eliminates the double-verification** codex
  flagged. (Also harmless if the middleware is absent — falls back to verifying.)
- Confirm forge's `authenticate_request` sets `request.state.user` (not only
  `.identity`) so the cached read works; align if needed.

### P2 — shared_rls: keep the account-based GUC bind (already correct)
- No change: `_apply_session_gucs` binds `app.current_tenant = account.customer_id`
  (UUID; RLS policy casts `::uuid`). With P1, the account is the authenticated
  token-claim tenant → token_claim shared_rls works end-to-end.
- **Remove the fragment's pre-auth request-path binding** (tenant middleware +
  engine begin-listener) — platform has none and it only double-sets/ no-ops.
  Keep the imperative `TenantRLSHook` as the explicit out-of-band/worker API.

### P3 — schema_per_tenant: add the UoW search_path binder (platform-pattern, fail-closed)
- Platform has no schema_per_tenant (it's forge-originated), so apply platform's
  *pattern*: bind at the UoW `__aenter__` from the account. Add a pluggable
  `session_binder` on forge_core's `AsyncUnitOfWork` that `_apply_session_gucs`
  always invokes with `account | None`; the schema fragment supplies a binder:
  - `account.customer_id` set → `SET LOCAL search_path TO "<schema_name_for(id)>", public`
  - `account is None` → `SET LOCAL search_path TO ''` (**fail-closed**, per codex)
- Install the binder at the UoW construction site in `ioc/security.py` via a new
  base-template marker (e.g. `FORGE:UOW_SESSION_BINDERS`). Remove schema_per_tenant's
  pre-auth listener reliance for the request path; keep `TenantSchemaHook` for workers.

### P4 — One canonical tenant claim (the only real config work)
- Platform sets the tenant claim ONCE (`AuthGuard.tenant_id_claim`). forge has the
  same knob (`AuthConfig.tenant_id_claim`, `domain/config.py:64`) but it isn't wired
  uniformly: the guard does **literal** claim lookup only (`guard.py:213`, no
  dot-path); **gatekeeper** doesn't pass it into `platform_auth.AuthGuard` and
  hard-codes `https://forge/tenant_id` (internal_token/service_token/compose/realm);
  **oidc_generic** has two divergent sources; defaults disagree (`tenant_id` vs
  `https://forge/tenant_id`).
- **Decision (needs your input):** pick ONE canonical generated claim value and wire
  it through verifier + issuer + gatekeeper minting + Keycloak mapper + env + tests.
  Recommend **keep `https://forge/tenant_id`** (matches gatekeeper/realm today, least
  churn; it's already the normalized namespace per the t1 fix) and make
  `database.tenant_claim_path` a thin alias that *feeds* `AuthConfig.tenant_id_claim`
  (gated to `multitenancy!=none + token_claim`, so non-multitenant auth is untouched).
  Keep auth **literal-claim-only** (drop the parallel resolver's dot-path promise for
  the request path).
- Per-provider: oidc_generic/in_memory carry raw claims → literal claim works;
  gatekeeper injects `IdentityContext` (no raw claims) → tenant = `identity.tenant_id`
  (already the gatekeeper namespace). Wire gatekeeper to pass `tenant_id_claim`.

### P5 — Resolver bug-fixes (independently correct; keeps header/subdomain viable)
Even though the platform path doesn't use the resolver, fix the real bugs codex
found so the (now non-default) header/subdomain strategies aren't silently wrong:
- `resolver.py` reads `identity.claims` but `IdentityContext` exposes **`.raw_claims`**
  (`identity.py:40`) → fix; gatekeeper fallback returns `None` for URL-shaped paths → fix.
- header/subdomain become **explicitly lower-trust, non-default**: validate the
  resolved tenant against the authenticated identity (reject on mismatch), and note
  shared_rls needs slug→UUID mapping (policy casts `::uuid`) — descoped.

## Verification (unit + integration + e2e)
1. **Unit:** cached-identity short-circuit (no re-verify when `request.state.user` set);
   AuthContextMiddleware registered + excluded paths; schema binder issues correct
   `SET LOCAL search_path` and `''` for `account=None`; claim wired into all providers;
   resolver `.raw_claims`/gatekeeper-fallback fixed.
2. **Integration (real Postgres):** request with stub identity (tenant T) → inside a
   UoW txn `current_setting('app.current_tenant')==T` (shared_rls) / `current_schema`
   ∈ tenant_T (schema_per_tenant); PublicUnitOfWork → zero rows / empty search_path;
   second tenant cannot read the first's rows.
3. **e2e (docker):** `shared_rls`+`token_claim`+`oidc_generic` and a `schema_per_tenant`
   variant; two JWTs, different tenant claims; assert physical cross-tenant isolation
   on a CRUD endpoint.
4. **Matrix:** `py_*` scenarios for both isolation strategies × token_claim;
   generate+verify must keep generated-api `ty check` green (ty 0.0.46).
5. **Golden:** P1 (middleware inject + cached read) and P3 (base UoW binder + IoC
   marker) change base/auth output → **goldens regenerate, not byte-identical**
   (the diff is the audit). Multitenancy/auth render tests update.
6. **docker-smoke typing on py3.13**; respect `excluded_app_templates=("tenant-management-service",)`.

## Round-3 (platform-faithful) validation — mandatory refinements before coding

codex confirmed the architecture is correct and the request path has no other
`request.state.tenant_id` consumers, the UoW seam + `account=None`→`search_path=''`
fail-closed is sound (health does `SELECT 1`, unaffected), and canonical
`https://forge/tenant_id` already matches core defaults / Keycloak mapper /
gatekeeper env. Make these explicit:

- **[Blocker] Align the auth stack.** The shipped `AuthContextMiddleware` imports
  `service.security.auth` (`auth_context.py:21`) while the base lifecycle/DI uses
  `forge_core.security.auth` (`lifecycle.py:13,53`) — different `AuthError`
  classes → invalid-token handling diverges. The middleware must call the SAME
  auth module/provider stack the app initializes. Reconcile (point the middleware
  at `forge_core.security.auth`, or unify the two modules) before registering it.
- **[Blocker] Cached-read in EVERY current-user dependency, not just DI.** Several
  feature routers use `forge_core.security.auth.get_current_user` /
  `_get_user_dependency` directly (`auth.py:189`), which always re-verifies. The
  `cached = getattr(request.state, "user", None)` short-circuit must be added there
  too, or double-verification persists for those routes.
- **[High] DI must be side-effect-free.** forge's `get_current_user` currently
  mutates ContextVars (`ioc/security.py:31`); platform's DI does not (the
  middleware owns ContextVar lifetime). Remove the DI ContextVar writes (the
  registered middleware now owns them) — avoids unreset/leaked context.
- **[High] Excluded-path + invalid-token policy.** Add `/api/v1/health/*` to the
  middleware exclusions (`auth_context.py:25` only lists unprefixed health; the
  real router is prefixed, `api.py.jinja:8`). Decide: a *bad* bearer on an excluded
  path — 401 or ignore? (Recommend: ignore on excluded paths; the middleware's
  no-token fail-open already lets them through.)
- **[Medium] Audit `PublicUnitOfWork` endpoints that touch tenant tables.** Under
  `schema_per_tenant`, `account=None` now fails closed (empty search_path), so
  feature endpoints using `PublicUnitOfWork` against tenant tables (e.g.
  `platform/webhooks/.../webhooks.py:31`) will break unless migrated to an
  authenticated/tenant-scoped UoW or explicitly handled. Enumerate + migrate.
- **P3 binder signature** is `(session, account | None)` — not account-only.
- **P4 loose ends:** flip the multitenancy option default off `tenant_id`
  (`options.py:142`) to the canonical (or make `tenant_claim_path` purely feed
  `AuthConfig.tenant_id_claim` and **not** be independently user-overridable for the
  auth path); reconcile OIDC's separate `AUTH_PROVIDER_TENANT_CLAIM`/`ClaimMapper`
  (`oidc_config.py:52`, `oidc_auth.py:105`) with the guard's `AuthConfig.tenant_id_claim`
  so they can't diverge. gatekeeper `internal_token.py:37` hard-codes the canonical
  claim — fine **iff** canonical is fixed.
- **`TenantContextMiddleware`** (header `customer_id`/`user_id` shim,
  `tenant_context.py:17`) is unrelated to tenant *resolution*; it STAYS as-is
  (document that it's header-context only, not the RLS binder).

## Golden impact (corrected, broader than first stated)
P1 (middleware + cached-read) and P3 (base `forge_core` UoW + IoC marker) touch
base files present in **`python_minimal`, `multi_backend`, `full_feature`,
`full_feature_max`** snapshots — all regenerate (NOT byte-neutral). Also update
`tests/test_features_multitenancy.py:130` (expects `tenant_id`).

## Sequencing
1. P4 contract: canonical claim value (your call), literal-only, provider/env wiring map.
2. P5 resolver fixes (small, independent).
3. P1 register AuthContextMiddleware + DI cached-identity short-circuit (the platform core).
4. P4 wire the claim through all providers (verifier/issuer/gatekeeper minting/Keycloak/env).
5. P3 schema_per_tenant UoW binder (fail-closed) + IoC seam; P2 cleanup (drop pre-auth
   request-path binding; keep imperative hooks for workers).
6. Regenerate/review goldens; unit+integration+e2e+matrix tests; codex review of the
   diff (2 rounds).

**Open decision for you:** the canonical claim value — keep `https://forge/tenant_id`
(recommended, least churn) or switch to `tenant_id`.
