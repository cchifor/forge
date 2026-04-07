# Gatekeeper

OIDC ForwardAuth middleware for Traefik. Validates JWT tokens from Keycloak
and forwards user identity headers to backend services.

## Headers Forwarded

| Header | Description |
|--------|-------------|
| `X-Gatekeeper-User-Id` | Keycloak subject UUID |
| `X-Gatekeeper-Email` | User email address |
| `X-Gatekeeper-Tenant` | Tenant/realm identifier |
| `X-Gatekeeper-Roles` | Comma-separated realm roles |
| `X-Gatekeeper-Auth-Method` | Authentication method used |

## Development

```bash
pdm install
pdm run python src/__main__.py server run
```
