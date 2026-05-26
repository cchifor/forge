# Production Deployment Guide

This guide covers deploying a forge-generated project to production.

## Required Environment Variables

Every production deployment **must** set these variables. The generated
service will refuse to start if they are missing or insecure.

### All backends

| Variable | How to generate | Notes |
| --- | --- | --- |
| `ENV` | Set to `production` | Controls fail-closed behavior for secrets |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` | Must not be `CHANGEME` in production |

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
- [ ] `SECRET_KEY` is a strong random value (not `CHANGEME`)
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
