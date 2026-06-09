# Schema-per-tenant isolation

This service was generated with `database.multitenancy=schema_per_tenant`. Each
tenant gets its own Postgres **schema** (`tenant_<id>`) holding the full table
set; requests are routed to the caller's schema by binding the connection's
`search_path` for the request transaction.

## How it works

| Piece | Role |
|-------|------|
| `app/core/tenancy/config.py` | env-driven `TenancySettings` (resolution strategy, claim/header, schema prefix) |
| `app/core/tenancy/resolver.py` | resolves the per-request tenant id (token claim / header / subdomain) — identical to the `shared_rls` resolver |
| `app/core/tenancy/schema.py` | `schema_name_for` (validate + name), `register_search_path_listener` (always-on fail-closed default), `bind_tenant_search_path` (post-auth account override), `provision_tenant_schema`, `TenantSchemaHook` (workers) |
| `app/middleware/tenant_schema.py` | resolves the tenant (header/subdomain) and sets `current_tenant_var` at the request edge |

The `search_path` is bound by **two composed seams**, both transaction-scoped
(`SET LOCAL`, so a pooled connection never leaks one tenant's path to the next):

1. **The engine `begin` listener (`register_search_path_listener`)** — the
   always-on default. On *every* transaction (including raw/non-UoW sessions —
   workers, direct `session_factory` use) it binds from the edge-resolved
   `current_tenant_var` (set by the middleware for `header`/`subdomain`), or
   `search_path = ''` when unset (**fail closed** — nothing falls open to
   `public`).
2. **The UoW binder (`bind_tenant_search_path`)** — installed on the request
   Unit-of-Work via the `FORGE:UOW_SESSION_BINDER` seam in
   `app/core/ioc/security.py`. It runs inside the handler transaction **after
   auth resolves** and, *only when an authenticated account is present*,
   OVERWRITES the listener's binding with `SET LOCAL search_path TO
   "tenant_<account.customer_id>", public`. **This is the `token_claim` path**
   (the pre-auth listener can't see a token claim). With no account it is a
   no-op, leaving the listener's binding (a `PublicUnitOfWork` under `token_claim`
   therefore fails closed). The authenticated account is authoritative: an edge
   header claiming a different tenant is ignored (logged).

Workers / code outside the request UoW use the imperative `TenantSchemaHook`
(`await hook.bind(session, tenant)`) for an explicit, tenant-scoped session.

## Provisioning a tenant

Schemas are created on demand, not by a migration. Bootstrap one with:

```python
from app.core.tenancy.schema import provision_tenant_schema
from app.data.models import Base

await provision_tenant_schema(db.engine, tenant_id, metadata=Base.metadata)
```

This issues `CREATE SCHEMA IF NOT EXISTS "tenant_<id>"` then materializes the
ORM tables inside it via `schema_translate_map`.

## Operational notes / hardening

- **Fail-closed on a missing tenant.** When no tenant is bound, the engine
  listener sets `search_path` to the **empty string**, so unqualified app tables
  (`items`) don't resolve and the query errors instead of silently reading
  `public`/shared data — the same fail-closed posture as `shared_rls` (zero
  rows). Non-tenant operations that don't touch app tables (a health `SELECT 1`)
  are unaffected.
- **`token_claim` binds via the UoW (post-auth), not the middleware.** The
  tenant middleware runs before `call_next`, so it can't see the token claim
  (`request.state.identity` is bound later by the per-route auth dependency).
  Instead the request UoW's binder reads the authenticated `account.customer_id`
  inside the handler transaction and overrides the listener's binding — so
  `token_claim` works for any endpoint whose handler uses an `AuthUnitOfWork`
  (the standard CRUD path). `header`/`subdomain` continue to resolve at the edge
  via the middleware/listener.
- **Endpoints using `PublicUnitOfWork` against tenant tables.** A public
  (unauthenticated) endpoint has no account, so the binder is a no-op and the
  request fails closed (empty `search_path`) under `token_claim`. If such an
  endpoint must touch tenant tables (e.g. an inbound webhook), it has to resolve
  the tenant itself — use an `AuthUnitOfWork`/tenant-scoped session or call
  `TenantSchemaHook.bind(session, tenant)` explicitly. It will not be
  auto-scoped.
- **Multiple commits in one UoW block.** `SET LOCAL` is transaction-scoped, so
  after an explicit `uow.commit()` the next query begins a new transaction and
  the binder (which runs once, at `__aenter__`) does NOT re-apply — the listener
  re-binds the fail-closed/edge default. Open a fresh UoW per logical
  transaction, or re-bind, if you commit-then-query within one block.
- **Tenant-id safety.** `schema_name_for` accepts only `[A-Za-z0-9_-]` ids
  (UUIDs and slugs) and rejects anything else rather than sanitizing — a lossy
  substitution could collide two tenants onto one schema. For the same reason
  it does **not** lowercase or trim the id (both are lossy: `A`/`a` and
  ` a `/`a` would collapse), so the mapping stays injective; the name is
  double-quoted at the call site, preserving case. It also enforces the
  Postgres 63-byte identifier limit.
- **Provision before serving.** The bound `search_path` is `"tenant_<id>",
  public`. If a tenant's schema is missing a table, the query falls THROUGH to
  `public.<table>` — so a tenant served before its schema is provisioned would
  read/write shared data. Always `provision_tenant_schema` a tenant before
  routing traffic to it, and keep `public` free of tenant rows (it exists for
  shared types/extensions and as the template the per-tenant schemas clone).
- **Migrations.** `provision_tenant_schema` is a bootstrap convenience. For
  ongoing schema evolution across many tenant schemas, run Alembic per schema
  with `version_table_schema=<schema>` and a `schema_translate_map`, iterating
  over the provisioned tenants — don't rely on `create_all` for upgrades.
- **Connection pooling.** All tenants share one engine/pool; isolation is per
  transaction via `search_path`, not per pool. This trades hard
  connection-level isolation for efficiency. If a deployment needs separate
  pools/databases per tenant, that is the (still-deferred) `db_per_tenant`
  strategy.
