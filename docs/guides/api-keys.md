# Optional third-party API keys

Use API keys for an external machine integration that needs selected application
operations. Keys identify the integration, not its creating administrator.
Gatekeeper authenticates the key; the destination service authorizes the feature
and tenant/resource access. No additional application service is needed.

## Enable the feature

API keys are disabled by default in every preset. Enable them explicitly:

```yaml
project_name: partner-api
include_keycloak: true
options:
  auth.api_keys: true
backends:
  - name: orders
    language: python
    server_port: 5020
```

This requires `auth.mode=generate` and `auth.provider=gatekeeper` (the defaults
when Keycloak is included). Unsupported combinations fail configuration validation.
Generated Compose sets Gatekeeper's `API_KEYS_ENABLED=true`. For another deployment,
set that environment variable explicitly. When disabled, the management routes
are absent and requests presenting `X-API-Key` are rejected, even if they also
present a browser session.

The runtime modules ship with Gatekeeper but remain inactive when disabled.
This option does not generate a key-management UI or application permission rules.

## Issue a key

An administrator signs in and calls Gatekeeper's `POST /api/v1/api-keys` with the
verified session cookie and same-origin CSRF context:

```json
{
  "name": "warehouse-reports",
  "scopes": ["orders:read"],
  "expires_in_seconds": 2592000
}
```

The administrator needs the configured `ADMIN_ROLE` (default `admin`) AND every
requested scope in their verified OIDC token's `scope` claim. Configure those
scopes in the identity provider; an admin role alone does not grant all features.
Scope entries are explicit `resource:action` names; wildcards and whitespace are
rejected. Optional roles must also be a subset of the administrator's own roles;
prefer scope checks for third-party API operations.

The tenant comes from the verified session/token and must match the resolved
host's tenant route. A hostname slug is not a tenant UUID. TMS routes supply the
mapping; the configured default realm uses `DEFAULT_TENANT_ID`.

The response includes `api_key`, `key_id`, granted scopes and `expires_at` (Unix
seconds). Copy the secret once: only its SHA-256 hash and metadata are stored in
Redis. The default lifetime is 30 days, capped by `API_KEY_MAX_TTL_SECONDS`
(default 90 days). Use durable, protected Redis for production key records.

The management paths belong to Gatekeeper. The development Compose publishes
its port, but does not create a dedicated public management ingress route.
Configure protected same-origin access deliberately; do not expose the whole
auth service just to enable key administration.

## Call an application API

```http
GET /api/orders/v1/items HTTP/1.1
Host: app.example.com
X-API-Key: <secret returned at creation>
```

Use HTTPS. The tenant host must resolve to the key's tenant. The edge calls
Gatekeeper's ForwardAuth endpoint, which checks the stored key, expiry and tenant,
applies tenant-level rate limiting, then returns an internal JWT. The edge sends
that JWT to the domain service. Its subject is `api-key:<key_id>` and its `scope`
claim contains the key's permissions. Generated Compose removes the original `X-API-Key` header after ForwardAuth.
Preserve that middleware ordering in other deployments and redact credentials
in ingress/auth logs.

The destination must verify the JWT and enforce the required scope plus object
ownership. With Python's platform-auth SDK, `require_scope("orders:read")` runs
after `AuthGuard` has bound the verified request identity. Implement those guards
on the appropriate application routes: the stock CRUD scaffold does not infer
feature permissions from key names. An `orders:read` credential must fail writes,
other feature access and reads of another tenant's objects.

API-key JWTs cannot be exchanged as user-delegation subjects. If processing the
request requires a downstream machine operation, authorize that business action
first and use the service's own narrowly granted credentials. Do not silently
replace integration permissions with broader service privileges.

## List, revoke and rotate

- `GET /api/v1/api-keys` lists active metadata for the verified administrator's tenant.
- `DELETE /api/v1/api-keys/{key_hash}` revokes a key using its listed hash. Cross-tenant revocation is denied.
- Rotate by issuing a replacement, updating the integration, then revoking the old key.

Revocation or disabling API keys stops new key authentication. Existing internal
JWTs remain valid until their expiry (normally at most five minutes, plus verifier
clock tolerance); JWT expiry is also bounded by key expiry. Protect direct backend
access and use an enforced revocation mechanism if immediate bearer invalidation
is required. Old records without scopes or expiry must be reissued.

Per-key quotas, an automatic rotation service and a management UI are not generated.
Rate limits currently apply per tenant. See [deployment](../operations/deployment.md)
and [auth architecture](../auth-architecture.md).
