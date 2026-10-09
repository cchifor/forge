# Service-to-service communication

Services communicate directly over their configured internal URLs. Gatekeeper
issues credentials; it does not forward the business request. This guide covers
the generated Gatekeeper provider. Other issuers need their own token contract.

## Configure dependencies

```yaml
project_name: shop
include_keycloak: true
options:
  auth.service_discovery: true
backends:
  - name: orders
    language: python
    server_port: 5020
    depends_on: [inventory]
  - name: inventory
    language: python
    server_port: 5030
```

Generation emits `GATEKEEPER_CLIENT_ID`, `GATEKEEPER_CLIENT_SECRET`,
`GATEKEEPER_TOKEN_ENDPOINT` and `INTERNAL_SERVICE_URL_INVENTORY` for orders.
The registry grants `svc-orders` access to target `svc-inventory`, initially with
`inventory:read` and `inventory:write`. Review and narrow grants for deployment.
Dependencies describe allowed targets; they do not implement an ordering workflow
or enforce network isolation. Development secrets are deterministic: provision
unpredictable production credentials and update their registry hashes.

## Choose the identity deliberately

| Operation | Grant | Identity and limits |
| --- | --- | --- |
| Autonomous job or service operation | `client_credentials` | `sub=svc-orders`; explicit tenant ID; scopes limited by registry. |
| Work on behalf of a user | RFC 8693 token exchange | Preserves user subject and tenant; records service actor; permissions intersect registry, subject scopes and any requested subset. |

The Python project SDK supports both paths:

```python
import os
from platform_auth import S2SClient

client = S2SClient(
    audience="svc-inventory",  # requested registry target
    token_endpoint=os.environ["GATEKEEPER_TOKEN_ENDPOINT"],
    client_id=os.environ["GATEKEEPER_CLIENT_ID"],
    client_secret=os.environ["GATEKEEPER_CLIENT_SECRET"],
)

# Machine work: tenant_id must come from an authorized job/context.
response = await client.get(
    os.environ["INTERNAL_SERVICE_URL_INVENTORY"] + "/api/v1/items",
    tenant_id=authorized_tenant_id,
)

# User-delegated work: pass the verified bearer token, WITHOUT "Bearer ".
response = await client.get(
    os.environ["INTERNAL_SERVICE_URL_INVENTORY"] + "/api/v1/items",
    on_behalf_of=verified_user_token,
)
# Reuse the client across requests; close it during application shutdown.
await client.aclose()
```

These are integration examples: `authorized_tenant_id` and `verified_user_token`
come from the calling application's trusted context. The generated CRUD scaffold
does not execute these calls automatically. Python's client caches machine tokens
per tenant and delegated tokens by subject-token identity. Check the selected
language SDK's public API; do not assume identical method signatures.

User delegation additionally requires `may_act_for_audiences` in the service
registry and an appropriate receiving `MayActPolicy`. A plain `depends_on` edge
does not grant user impersonation. Subject tokens must carry scopes; roles alone
are insufficient. API-key and service-account tokens are rejected as user
subjects. Never turn an arbitrary incoming operation into a privileged machine
call: first authorize the application operation and tenant explicitly.

## Receiving-service obligations

Verify signature, expiry, issuer and accepted audience. Enforce the operation's
scope (for example `inventory:read`) and tenant/resource ownership. A valid token
alone is not permission to perform every operation.

The token request's `audience=svc-inventory` selects registry grants; the emitted
JWT currently has the shared `aud=forge-services`. `platform_target_service`
records the intended service, but shared-audience verification alone does not
restrict recipients. Use service-specific scopes and resource policy; implement
an explicit target check where required. Neither the registry nor Compose
`depends_on` is a network access policy.

A synchronous exchanged token cannot outlive its subject token. Long-lived user
work uses separately authorized delegation grants: they retain the original
scope ceiling, are bound to the issuing client and target, and can outlive the
initial access token only within their explicit grant lifetime. Exchanged JWTs
cannot outlive that grant. Revoking credentials/grants does not retract already
issued JWTs; their remaining expiry and verifier clock tolerance bound that window.

## Deployment and reliability

Use HTTPS or an appropriately authenticated/encrypted internal transport and keep
private services inaccessible from public ingress. Configure timeout budgets,
retry only safe/idempotent operations, and propagate correlation IDs. Event-bus
provisioning does not implement durable workflows, replay, or an outbox; choose
those semantics explicitly. See [deployment](../operations/deployment.md).
