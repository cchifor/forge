# Tenant Management Service — production hardening

This service is a faithful port of a production tenant-provisioning service. Its
provisioning **saga** gives you Keycloak-realm compensation on the external-call
step and a transactional outbox for domain events. A few robustness and security
concerns are **deliberately left to you** — they depend on your deployment
topology (single vs. multi-instance), your Keycloak setup, and your gatekeeper
contract. Review these before running in production.

## Provisioning saga — partial-failure windows

- **Dedicated-realm leak on client-create failure.** `provision()` marks the
  realm as "ours to compensate" only *after* `_provision_dedicated_realm()`
  returns. If `create_client()` fails after `create_realm()` succeeds, the realm
  is created but not compensated. Harden by tracking realm ownership the moment
  `create_realm()` succeeds (e.g. have it return a `created: bool`) and
  compensating inside `_provision_dedicated_realm()`.
- **No compensation after DB failure.** The Keycloak user (and, for the
  enterprise tier, the dedicated realm) is created *before* the DB transaction.
  If the DB create/update/outbox commit fails, those Keycloak objects are
  orphaned. Harden by reserving the tenant row in `pending` status first, or by
  adding post-DB-failure compensation (delete the user; delete an owned realm).
- **409 vs. idempotent create.** If `create_realm()` treats a Keycloak `409` as
  success, make sure compensation never deletes a realm this saga did not create.

## Shared-realm secret

- `_ensure_shared_realm_in_db()` persists `client_secret="managed-by-keycloak"`
  as a placeholder, and `_build_route_config()` publishes whatever is in the DB
  to Redis. The **documented primary flow works**: create a realm with a real
  `client_secret` via `POST /realms`, then provision tenants into it — the real
  secret is published. The **auto-provision fallback** (no shared realm exists
  yet) ships the placeholder; if you rely on it, update the realm row with the
  real secret returned by `create_client()` before tenants authenticate.

## Concurrency

- **Shared-realm assignment is check-then-act.** Capacity is read in one
  transaction and the tenant is created in a later one, so concurrent provisions
  can overfill a realm; `_ensure_shared_realm_in_db()` is likewise a
  check-then-insert on a unique name. Harden with a single locked transaction
  (`SELECT … FOR UPDATE SKIP LOCKED`) or an upsert/retry.
- **Outbox relay assumes a single publisher.** `OutboxRelay` selects unpublished
  rows without row locks. If you run more than one instance/worker, every
  process starts a relay and they can double-publish. Run the relay as a
  singleton (a dedicated worker) or add `SELECT … FOR UPDATE SKIP LOCKED` with
  guarded status updates. (At-least-once downstream consumers should dedupe on
  the event id regardless.)

## Suspend → Redis reconciliation

- `suspend()` removes the tenant's Redis route best-effort. `POST /sync-redis`
  only **re-publishes active** tenants — it does not remove stale routes for
  suspended ones. If a suspend's Redis delete fails, the route lingers. Harden by
  reconciling deletes (maintain a route index, or publish route *status* and have
  the gatekeeper deny inactive tenants).

## Keycloak security

- Realms are created with `sslRequired: "none"` and clients with wildcard
  redirect URIs / web origins — convenient for local dev, unsafe for production.
  The `tms.keycloak_ssl_required` config exists (`"external"` in
  `production.yaml`) but is **not yet threaded into `keycloak_admin`**. Pass it
  through and pin exact gatekeeper redirect origins before going live.

## Configuration

- `production.yaml` uses `${KEYCLOAK_ADMIN_URL}` / `${REDIS_URL}` etc. These are
  **config-reference placeholders**, not shell env interpolation: the loader
  resolves `${path}` against the merged config tree, and the higher-priority
  `APP__…` env source overrides them first. Supply the real values via
  `APP__TMS__KEYCLOAK_ADMIN_URL`, `APP__TMS__REDIS_URL`,
  `APP__TMS__KEYCLOAK_ADMIN_PASSWORD`, etc. Do not ship the `admin/admin` dev
  defaults to production.
