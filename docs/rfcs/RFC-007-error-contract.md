# RFC-007 — Error response contract

| Field | Value |
| --- | --- |
| Status | Accepted |
| Author | Architecture review 2026-04 |
| Epic | 1.0.0-ga |
| Supersedes | — |
| Replaces | — |

## Summary

Define the canonical error-response contract every forge-generated backend
(Python / Node / Rust) must emit, covering: a machine-readable **error code**
(stable string enum), HTTP status mapping, envelope shape, correlation-id
propagation, and a fragment-registrable domain-error hook.

Before this RFC, the three backends drift: Python carries a 13-class
hierarchy with a registrable mapper and `{message, type, detail}` envelope;
Node exposes 4 error classes with `{statusCode, error, message}` and no code
field; Rust has an `AppError` enum with 4 variants collapsing database /
validation / logic into `AppError::Internal` and a third envelope shape.

Frontends consume OpenAPI-generated clients, but error bodies are
framework-specific — so the Vue, Svelte, and Flutter clients each need
per-backend error handling. This defeats the unified-client promise.

## The envelope

Every error response body is a single JSON object:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Item 'abc-123' not found",
    "type": "NotFoundError",
    "context": {},
    "correlation_id": "01H..."
  }
}
```

Field semantics:

| Field | Type | Required | Purpose |
| --- | --- | --- | --- |
| `code` | string enum | ✅ | Machine-readable, stable across versions. Use to branch in clients. |
| `message` | string | ✅ | Human-readable. Safe to surface in UI. Never contains stack or PII. |
| `type` | string | ✅ | Concrete error class name (for diagnostic UIs / support tickets). |
| `context` | object | ✅ | Freeform structured data (e.g. `{"field": "email"}` for validation). Empty object `{}` when not applicable. |
| `correlation_id` | string | ✅ | Request correlation ID (echoes the `X-Correlation-Id` header or the server-assigned one). Enables log-join from the client. |

The `error` field is always the top-level key. Servers MUST NOT return bare
error bodies (e.g. `{"message": "..."}`) or framework-default shapes
(Fastify's `{statusCode, error, message}`, Axum's `String`, FastAPI's
`{detail: "..."}`). All exception handlers MUST emit the envelope.

## Canonical error codes

These codes are reserved. Fragments SHOULD reuse them when semantically
equivalent; fragments MAY register additional codes via the per-backend
registration hook (see below) as long as they follow the naming
convention (`UPPER_SNAKE_CASE`, ≤40 chars).

| Code | HTTP | Meaning |
| --- | --- | --- |
| `AUTH_REQUIRED` | 401 | Tenant context missing from an authenticated route. |
| `PERMISSION_DENIED` | 403 | Authenticated but not authorized for this action. |
| `READ_ONLY` | 403 | Resource exists but cannot be mutated in current mode. |
| `NOT_FOUND` | 404 | Resource does not exist (or is invisible to this tenant). |
| `ALREADY_EXISTS` | 409 | Uniqueness constraint violated at service layer. |
| `DUPLICATE_ENTRY` | 409 | Uniqueness constraint violated at repository layer. |
| `FOREIGN_KEY_VIOLATION` | 409 | Referenced entity does not exist. |
| `CONSTRAINT_VIOLATION` | 409 | Other database constraint violated. |
| `VALIDATION_FAILED` | 422 | Input failed server-side validation. |
| `INVALID_INPUT` | 422 | Structurally valid but semantically rejected input. |
| `RATE_LIMITED` | 429 | Too many requests; retry after. |
| `INTERNAL_ERROR` | 500 | Unexpected server condition; operator should investigate. |
| `DATABASE_UNAVAILABLE` | 503 | Database connection failed / pool exhausted. |
| `DATABASE_TIMEOUT` | 503 | Database query exceeded the deadline. |
| `DEPENDENCY_UNAVAILABLE` | 503 | A downstream service (cache, queue, LLM) is unreachable. |

## Per-backend implementation

Each backend MUST ship:

1. A typed error base with `code`, `status_code`, and a structured
   `context` field.
2. A central exception handler that serializes any known error into the
   envelope and any unknown error into `{code: INTERNAL_ERROR, status: 500}`
   with a redacted message.
3. A registration hook — `register_domain_error` (Python), `registerErrorCode`
   (Node), or `register_error_code!` (Rust macro) — so fragments can
   introduce their own `code` / `status` pairs at import time. Conflicting
   registrations MUST raise at load time.

## Correlation-id propagation

Every backend already runs a correlation middleware that echoes or mints
`X-Correlation-Id`. The error handler MUST read the current correlation id
from the request and copy it into `error.correlation_id`. This lets
frontends and oncall link a user-visible error back to log lines without
the user having to copy-paste trace ids.

## Migration

- Python: extend the existing `Error` envelope in `service.utils.fastapiutils`
  with `code` and `correlation_id` fields (backwards-compatible — new fields
  are ignored by old consumers).
- Node: replace `{statusCode, error, message}` with the envelope. This is a
  breaking change for any existing consumer; documented in `UPGRADING.md`.
- Rust: replace `{error, message}` with the envelope. Also expand `AppError`
  so database, validation, and logic errors no longer share `Internal`.

Frontends generated by forge consume the envelope via a shared
`apiError.ts` / `api_error.dart` helper (introduced alongside this RFC).

## Alternatives considered

- **RFC 7807 Problem+JSON**: The `application/problem+json` standard is
  well-known but bakes in URIs (`type`) as the primary discriminator.
  Forge's consumers are internal clients reading OpenAPI-generated types;
  a string enum is more ergonomic. We keep the field names (`type`,
  `detail` → `context`) reminiscent enough that adopting 7807 later is
  not a breaking change.
- **Bake gRPC status codes into HTTP**: considered but rejected — most
  Traefik / Gatekeeper setups in forge's auth stack strip/alias status
  codes on the wire.
- **Status-only (no `code` enum)**: a 404 may mean "not found" or
  "invisible to tenant," which clients often want to distinguish without
  parsing message text. A dedicated `code` enum avoids that.
