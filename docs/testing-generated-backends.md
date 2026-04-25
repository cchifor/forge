# Testing generated backends

Forge ships test utilities into every generated backend so authors of
fragments and downstream services can write their own tests in the
same idiom forge does. The contracts below are stable across the
three backend languages — once you've learned the Python helpers,
the Node and Rust equivalents read identically.

## Shared concepts

| Concept | Purpose |
| --- | --- |
| `tenant_factory` | Build a `TenantContext` with sane defaults — supply only the fields under test. |
| `authenticated_request_headers` | Map of headers (`X-Gatekeeper-User-Id` etc.) that the global tenant middleware extracts. Mount on test requests to simulate Gatekeeper. |
| `with_repository_mock` | (P2.3) Inject an in-memory repository into a service for unit tests; bypass the real database entirely. |
| `request_correlation_id` | (RFC-007) Header builder used in error-envelope tests so assertions can pin the `correlation_id` field of the response. |

## Python (pytest)

```python
from tests.utils.tenant import tenant_factory, authenticated_headers
from tests.utils.errors import assert_error_envelope

def test_returns_403_when_read_only(client):
    headers = authenticated_headers()
    resp = client.delete("/api/v1/items/abc", headers=headers)
    assert_error_envelope(resp, code="READ_ONLY", status=403)
```

The Python test-utils module ships at `tests/utils/`. Its public
surface is documented in the module docstring; tests should never
reach past those exports.

## Node (vitest)

```ts
import { describe, it, expect } from "vitest";
import { tenantFactory, authenticatedHeaders } from "../utils/tenant.js";
import { assertErrorEnvelope } from "../utils/errors.js";

describe("DELETE /items/:id", () => {
  it("returns 403 READ_ONLY when the entity is locked", async () => {
    const res = await app.inject({
      method: "DELETE",
      url: "/api/v1/items/abc",
      headers: authenticatedHeaders(),
    });
    assertErrorEnvelope(res, { code: "READ_ONLY", statusCode: 403 });
  });
});
```

## Rust (cargo test)

```rust
use crate::utils::tenant::{authenticated_headers, tenant_factory};
use crate::utils::errors::assert_error_envelope;

#[tokio::test]
async fn returns_403_when_read_only() {
    let resp = client
        .delete("/api/v1/items/abc")
        .headers(authenticated_headers().build())
        .send()
        .await?;
    assert_error_envelope(resp, "READ_ONLY", 403).await;
}
```

## Why this matters

- **Fragment authors don't reinvent the wheel.** Adding a fragment
  that gates a route on a new permission means writing one test per
  backend; the boilerplate is the same in each.
- **Test stability.** When the tenant middleware or error envelope
  evolves (RFC-007 / RFC-008), only the helper module changes —
  every fragment's tests keep passing.
- **Onboarding.** A contributor can learn the test contract once and
  apply it across all three languages.

## Adding a new helper

Helpers belong in `tests/utils/<topic>.py|.ts|.rs`. The contract
is:

1. Pure helpers — no global state, no module-level side effects.
2. Stable signatures across the three languages where it makes sense.
3. Documentation in the module docstring with a tiny working example.
4. A test file under `tests/utils/test_<topic>.{py,ts,rs}` that
   exercises the helper itself (so a refactor of the helper doesn't
   silently break every consuming test).

When in doubt, mirror the existing Python helper as the reference.
