# Production Deployment Guide

This guide covers deploying a forge-generated project to production.

## Required Environment Variables

Every production deployment **must** set these variables. The generated
service will refuse to start if they are missing or insecure.

### All backends

| Variable | How to generate | Notes |
| --- | --- | --- |
| `ENV` | Set to `production` | Controls fail-closed behavior for secrets |
| `APP__SECURITY__SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` | Bound via `APP__` env prefix (`config.SettingsConfigDict`). Production refuses to boot if unset, blank, a `CHANGEME…` placeholder, or shorter than 32 chars. |

### Auth-enabled projects (Gatekeeper)

| Variable | How to generate | Notes |
| --- | --- | --- |
| `GATEKEEPER_CLIENT_SECRET` | Random string, 32+ chars | Must not be empty or `super-secret-string` |
| `COOKIE_SECURE` | `true` | Defaults to `true`; set `false` only for non-HTTPS dev envs |
| `SESSION_FERNET_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | Required for BFF session encryption |
| `DELEGATION_GRANT_FERNET_KEY` | Same as above | Required for delegation grants |
| `SIGNING_KEY_DIR` | Path to directory containing `.pem` files | Gatekeeper keygen init-container creates these |

### MCP-enabled projects

| Variable | How to generate | Notes |
| --- | --- | --- |
| `MCP_APPROVAL_SIGNING_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` | Required in production; service fails to start without it |

## Production Checklist

Before going live, verify:

- [ ] `ENV=production` is set on all services
- [ ] `APP__SECURITY__SECRET_KEY` is a strong random value (>= 32 chars, not a `CHANGEME…` placeholder)
- [ ] `APP__SECURITY__AUTH__CLIENT_SECRET` is the real OIDC client secret (not `changeme`) when auth is enabled
- [ ] `GATEKEEPER_CLIENT_SECRET` is set (not empty, not `super-secret-string`)
- [ ] `COOKIE_SECURE=true` is set (or omitted — defaults to `true`)
- [ ] `SESSION_FERNET_KEY` is set (if using BFF sessions)
- [ ] `MCP_APPROVAL_SIGNING_KEY` is set (if using MCP tool invocations)
- [ ] Signing key PEM files exist in `SIGNING_KEY_DIR`
- [ ] Redis is accessible via `REDIS_URL`
- [ ] Database connection string is production-grade (not SQLite)
- [ ] Health check endpoints (`/api/v1/health/live`, `/api/v1/health/ready`) are monitored
- [ ] Body size limits are appropriate for your workload (Python: `audit.max_body_size`, Node/Rust: 1MB default)

## Key Rotation

### Fernet keys (session + delegation grants)

1. Generate a new Fernet key
2. Update `SESSION_FERNET_KEY` / `DELEGATION_GRANT_FERNET_KEY`
3. Restart gatekeeper
4. **Impact:** All outstanding sessions are invalidated. Users must re-authenticate.

### Signing keys (ES256 JWTs)

1. Generate a new EC P-256 key pair:
   ```bash
   openssl ecparam -name prime256v1 -genkey -noout -out new-key.pem
   ```
2. Place the new `.pem` in `SIGNING_KEY_DIR`
3. Restart gatekeeper — it picks up all `.pem` files and uses the newest for signing
4. **Impact:** Existing JWTs remain valid until expiry (default 5 min TTL). No downtime.

### Client secrets

1. Rotate in your identity provider (Keycloak)
2. Update `GATEKEEPER_CLIENT_SECRET`
3. Restart gatekeeper

## Docker Production Profile

For hardened deployments:

```yaml
services:
  api:
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    deploy:
      resources:
        limits:
          memory: 512M
```

### Non-compose deployments

If deploying with `docker run` or Kubernetes (without the compose template),
you must set `COOKIE_SECURE=false` explicitly for non-HTTPS environments.
The default is `true` — cookies will not be sent over plain HTTP.

## Kubernetes (Helm)

Generating with `deploy.target=kubernetes` emits a **topology-aware Helm
umbrella chart** under `deploy/helm/`. The chart mirrors your project: one
Deployment + Service + HorizontalPodAutoscaler per backend, the frontend, an
Ingress, and a per-backend ConfigMap + Secret. Its `values.yaml` is rendered
from the project's deployment topology, so it always reflects the real set of
backends, ports, and the frontend.

### Quick start

```bash
# Lint + render (raw manifests, derived from the chart — never hand-edited):
make helm-lint
make k8s-manifests          # writes deploy/k8s/rendered.yaml

# Install (copy the example first and fill in your overrides):
cp deploy/helm/values-prod.yaml.example deploy/helm/values-prod.yaml
make helm-install           # helm upgrade --install ... -f deploy/helm/values-prod.yaml
```

`values.yaml` is **forge-owned** — it is re-rendered (and three-way merged) on
every `forge --update`. Put your per-environment overrides in
`values-prod.yaml`, which forge **never** tracks or overwrites.

### Datastores

Postgres / Redis / Keycloak are **external by default** (the production
posture): point `externalServices.*` at your managed instances. For a throwaway
dev cluster (kind / minikube), set `infra.inCluster=true` to spin up in-cluster
stand-ins (Postgres StatefulSet + PVC, Redis, Keycloak) — these are **not**
production-grade.

### Secrets (read this before production)

forge ships **only placeholders** in each workload's `secretEnv` (DB URLs,
client secrets carry `CHANGEME`). It never bakes a real or deterministic
credential into the chart. Before going live, either:

- override `secretEnv` in `values-prod.yaml`, or
- delete the generated `Secret`s and wire an `ExternalSecret` / SealedSecret /
  CSI volume of the same name (the Deployment's `secretRef` is `optional`, so an
  externally-managed Secret takes over).

**Auth caveat:** the local stack derives gatekeeper service-to-service secrets
deterministically and stores their **argon2 hashes** in
`infra/gatekeeper/secrets/service_registry.yaml`. If you rotate the S2S Secret
in the cluster you must regenerate that registry too, or S2S auth will reject
the new credential. The gatekeeper keygen / realm-sync init Jobs the compose
stack runs are **not** emitted by the chart yet — run them out-of-band (or
supply your own) until a later release moves that tooling under `deploy/`.

### Migrations

Each backend that ships migrations gets a `Job` annotated as a
`pre-install,pre-upgrade` Helm hook, so the schema is current before the
Deployment rolls. A failed migration blocks the release (intended). All migrate
Jobs share one hook weight and therefore run **in parallel** — safe because each
backend owns its own database (so migrations never collide). If you point
multiple backends at a single shared database, give those Jobs distinct
ascending `helm.sh/hook-weight`s so Helm serialises them.

### Ingress

A standard `networking.k8s.io/v1` Ingress routes `/api/<backend>` to each
backend Service and `/` to the frontend. `ingress.className` and
`ingress.host` are values you set per environment. The default rewrite
annotation is **nginx-ingress specific** — for a different controller (Traefik
Middleware CRD, Gateway API, ...) change `ingress.className` and
`ingress.annotations` accordingly.

### Keeping the chart current

`forge --update` re-renders `deploy/helm/values.yaml` from the current
topology: add a backend, change a port, or add the frontend and the chart picks
it up. Your `values-prod.yaml` is never touched; edits to the forge-owned files
are preserved via three-way merge (or surfaced as a `.forge-merge` sidecar on a
genuine conflict).

## Monitoring

Generated projects include:

- **Health checks:** `/api/v1/health/live` (liveness) and `/api/v1/health/ready` (readiness)
- **Structured logging:** JSON format with correlation IDs
- **OpenTelemetry:** Enable with `observability.tracing=true` and set `OTEL_EXPORTER_OTLP_ENDPOINT`
- **MCP audit log:** Append-only JSONL at `MCP_AUDIT_LOG` path (default: `audit.jsonl`)

## Known Limitations

See [known-issues.md](known-issues.md) for the full list. Key production-relevant items:

- PII redaction is Python-only (Node/Rust backends don't filter sensitive data from logs)
- Vector store adapters are Python-only
- Admin panel has no RBAC — all authenticated users see all models
