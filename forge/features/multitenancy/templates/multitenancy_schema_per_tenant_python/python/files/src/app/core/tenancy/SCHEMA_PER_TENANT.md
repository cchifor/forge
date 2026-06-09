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

- **Fail mode differs from `shared_rls`.** RLS fails *closed* (an unbound GUC
  yields zero rows). Schema routing has no such default: when no tenant is bound
  the `search_path` stays at `public`. **Pair this strategy with auth** so an
  unidentified request is rejected (401) before it opens a transaction, and keep
  tenant rows out of `public` — treat `public` as the canonical/template schema
  that `provision_tenant_schema` clones per tenant.
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
