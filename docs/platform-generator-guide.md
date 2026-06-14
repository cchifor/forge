# Platform generator guide (`--platform`)

Most forge invocations scaffold one backend (and maybe a frontend). The
**platform presets** scaffold a *system*: several services wired together with
shared auth, service-to-service (S2S) trust, an optional event bus, and — for
the SaaS preset — per-tenant data isolation. One flag stands the whole topology
up:

```bash
forge --platform microservices --project-name shop
```

This guide covers which preset to pick, what each one assembles, how the
multi-service auth and multitenancy actually work, and — importantly — the
**dev-posture credentials you must rotate before deploying.**

> A preset is just the lowest-priority configuration layer. It is deep-merged
> *under* your CLI flags and `--config` file, so every preset value is a
> default you can override (`--set auth.provider=oidc_generic`, a custom
> `backends:` list, etc.). With no `--platform`, generation is byte-identical
> to the single-service path.

## Choosing a preset

`forge --platform` accepts four presets (the choices are discovered from
`forge/templates/platforms/*/platform.toml`):

| Preset | Shape | Keycloak | S2S auth | Multitenancy | Use it when |
| --- | --- | --- | --- | --- | --- |
| **`monolithic`** | 1 Python CRUD backend + Vue (sidebar) | no | no | no | You want the classic single-service app with a UI and no auth-server overhead. |
| **`microservices`** | API `gateway` + `orders` + `inventory` CRUD services + Vue, with an event bus | yes | yes | no | You have several services that must call each other and emit events. |
| **`headless-api`** | API `gateway` + `orders` CRUD service, **no frontend** | yes | yes | no | You want the S2S service stack as a pure API (mobile/3rd-party clients). |
| **`multitenant-saas`** | `tms` control plane + RLS-isolated `app` CRUD service + Vue, behind the Gatekeeper | yes | yes | **shared-RLS** | You're building multi-tenant SaaS and need per-tenant row isolation + tenant provisioning. |

Everything except `monolithic` brings up Keycloak + the Gatekeeper edge-auth
stack + Redis — a substantial stack. Start with `monolithic` if you don't yet
need cross-service auth.

A worked invocation:

```bash
forge --platform microservices --project-name shop --output-dir ./shop
cd shop
docker compose up --build         # gateway:5010, orders:5020, inventory:5030,
                                  # keycloak, gatekeeper, redis, postgres, vue
```

The generated `docker-compose.yml` is a flat monorepo (`services/`, `apps/`,
`sdks/`). Each backend gets its own image; the gateway `depends_on` its
downstreams so it boots last.

## How multi-service auth works (synthesis)

When a preset sets `auth.service_discovery=true` and the project has more than
one backend, forge **synthesizes** an S2S trust mesh
(`forge/synthesis/platform.py`). Two things are generated:

1. **A service registry** (`infra/gatekeeper/secrets/service_registry.yaml`) —
   one entry per backend with a `client_id` (`svc-<name>`), a client secret,
   and the set of audiences (callee → scopes) it may request. Those audience
   grants are derived directly from each backend's `depends_on` edges, so a
   service can only mint tokens for the peers it declared.
2. **Per-service env** injected into each compose service:
   `GATEKEEPER_CLIENT_ID` / `GATEKEEPER_CLIENT_SECRET` /
   `GATEKEEPER_TOKEN_ENDPOINT`, and an `INTERNAL_SERVICE_URL_<PEER>` for every
   in-network callee.

At runtime: a caller exchanges its client id+secret at the Gatekeeper's token
endpoint for a short-lived (≈5 min) ES256 JWT scoped to the audience
`forge-services`; the callee verifies that JWT against the Gatekeeper's JWKS
endpoint before trusting the request. The Gatekeeper — not Keycloak — is the
sole internal issuer; Keycloak is the upstream identity provider for *end
users*. See [`docs/auth-architecture.md`](auth-architecture.md) for the full
token/JWKS/BFF-session design.

> The synthesized service secrets are **deterministic** (derived from the
> project slug + service name) so `forge --update` is idempotent. That's a
> dev convenience, **not** production-grade randomness — see rotation below.

## Multitenancy (`multitenant-saas`)

The `multitenant-saas` preset sets `database.multitenancy=shared_rls` and
`database.tenant_resolution=token_claim`. The chain:

1. A Keycloak user carries a `tenant_id` attribute; a realm protocol-mapper
   projects it into the `https://forge/tenant_id` access-token claim.
2. The Gatekeeper verifies the user token and carries that claim into the
   internal JWT it mints.
3. The app's tenancy middleware resolves the tenant from the verified claim and
   binds it per-transaction with `SET LOCAL app.current_tenant = '<uuid>'`.
4. Postgres **row-level security** policies (`USING customer_id =
   current_setting('app.current_tenant')::uuid`) then filter every query to
   that tenant automatically — application code stays tenant-agnostic.

The `tms` (tenant-management-service) control plane provisions tenants (Keycloak
realm/user + the routing entries the Gatekeeper reads). It is **exempt** from
the RLS policy (it's listed in the RLS fragment's `excluded_app_templates`): TMS
isolates by *realm*, not by Postgres row, and keeps its own migration chain.

Resolution is **fail-closed**: an unbound tenant binds an empty scope and RLS
returns zero rows rather than leaking across tenants.

## Auth providers

`auth.provider` (meaningful when `auth.mode=generate`) selects the token
authority. No preset overrides it, so all four default to `gatekeeper`; change
it with `--set auth.provider=<value>`:

| Provider | What it generates | For |
| --- | --- | --- |
| **`gatekeeper`** (default) | The Gatekeeper edge-auth service + Keycloak realm + the one-shot keygen and realm-sync sidecars | The full production-shaped stack. |
| **`in_memory`** | A zero-dependency in-process issuer that mints test JWTs | Local dev / tests. **Refuses to start under production posture.** |
| **`oidc_generic`** | OIDC-discovery wiring against an external issuer (Auth0, Cognito, Okta, …) | Bring-your-own IdP. |
| **`none`** | No token authority | Bring-your-own issuer / public service. |

## Security: dev-posture defaults you must rotate

**The generated compose is a turnkey *development* stack.** It boots with no
manual secret setup, which means it ships well-known default credentials. Before
any non-local deployment, rotate every item below. The relevant files are
`forge/templates/deploy/docker-compose.yml.j2`, the Gatekeeper provider compose
(`forge/features/auth/templates/platform_auth_gatekeeper/`), and the generated
`infra/gatekeeper/secrets/service_registry.yaml`.

- **Keycloak admin password** and **Postgres credentials** — shipped as
  `admin` / `postgres`. Replace with managed secrets; don't reuse the same
  Postgres password across services.
- **Gatekeeper session/delegation keys** (Fernet) and the **dev client secret**
  — regenerate; do not ship the in-tree example values.
- **Synthesized S2S secrets** in `service_registry.yaml` — deterministic in dev;
  replace with unpredictable values (the file documents the re-hash flow).
- **Signing keys** — the keygen sidecar writes an ECDSA P-256 keypair to a
  named volume on first boot; rotate by deleting the volume and re-running.
- **`ENV`** — flip from `development` to `production` to activate the
  fail-closed guards.

**Fail-closed guards (intentional).** With `ENV=production`, the realm-sync
sidecar refuses to run while the Keycloak admin password is still the `admin`
default, so a stack that still carries dev secrets will not boot into a
production posture. `in_memory` auth likewise refuses production. Treat a
crash-loop here as the guard doing its job — supply real secrets.

**Trust boundary / ports.** Datastores are bound to loopback only
(`127.0.0.1:15432→postgres`, `127.0.0.1:6379→redis`); services reach them over
the compose network (`postgres:5432`, `redis:6379`). The Gatekeeper (`:5000`),
Keycloak, and Traefik (`:80`) are host-exposed for the dev/test stack. In a real
deployment, front the stack with Traefik (or your ingress) and do not publish
the datastore or admin ports.

See [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) for the production checklist and
[`docs/OPERATIONAL_RUNBOOK.md`](OPERATIONAL_RUNBOOK.md) for operator workflows.

## Where to go next

- [`docs/auth-architecture.md`](auth-architecture.md) — the full auth stack
  (Keycloak IdP, Gatekeeper authority, JWT/JWKS, BFF sessions, tenant claims).
- [`docs/FEATURES.md`](FEATURES.md) — the option registry: every knob a preset
  sets (`auth.*`, `database.*`, `infrastructure.*`) with its type and default.
- [`docs/GETTING_STARTED.md`](GETTING_STARTED.md) — first-project walkthrough.
