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
| `app/core/tenancy/schema.py` | `schema_name_for` (validate + name), `register_search_path_listener` (per-tx `SET LOCAL search_path`), `provision_tenant_schema`, `TenantSchemaHook` (workers) |
| `app/middleware/tenant_schema.py` | resolves the tenant and sets the `current_tenant_var` ContextVar the listener reads |

On every transaction `begin`, the engine listener runs:

```sql
SET LOCAL search_path TO "tenant_<id>", public
```

`SET LOCAL` is transaction-scoped, so a pooled connection never carries one
tenant's `search_path` into the next request.

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
- **`token_claim` does not resolve at middleware time in this template.** The
  tenant middleware runs before `call_next`, but `request.state.identity` is
  bound by a per-route auth **dependency** (the generated template does not
  register an auth *middleware*). So with `database.tenant_resolution=token_claim`
  (the default) the middleware sees no identity, resolves `None`, and every
  request fails closed (empty `search_path`) — i.e. the app can't reach tenant
  data. **For schema_per_tenant, use `database.tenant_resolution=header` or
  `subdomain`** (both read the request directly at middleware time), have your
  gateway inject the tenant header, or register an auth middleware that binds
  `request.state.identity` *before* `TenantSchemaMiddleware`. (`shared_rls`
  shares this timing constraint, but degrades to zero-rows rather than errors.)
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
