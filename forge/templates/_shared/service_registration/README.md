# Service-registration Jinja macros (RFC-009)

Three macros — one per backend — render an idiomatic service
registration from a single declarative spec. Fragment authors write
the spec once in `services.yaml`; the applier expands it into
backend-native code at template-render time.

The spec shape is documented in `docs/rfcs/RFC-009-service-registration.md`.

## Macros

### `python_provider.jinja`

Renders a `dishka.Provider` subclass. Scope translation:

| Spec scope     | Dishka scope    |
| ---            | ---             |
| `singleton`    | `Scope.APP`     |
| `request`      | `Scope.REQUEST` |
| `transient`    | `Scope.REQUEST` |

Usage from a Python backend template:

```jinja
{% from "_shared/service_registration/python_provider.jinja" import provider %}
{{ provider(service) }}
```

Where `service` is a dict matching the RFC-009 spec.

### `node_plugin.jinja.ts`

Renders a Fastify plugin (`fastifyPlugin`) that decorates the app or
the request with the service instance. Singletons use `app.decorate`;
request-scoped use `app.decorateRequest`.

### `rust_layer.jinja.rs`

Renders an Axum extension. Singletons become `Arc<T>` registered on
the router via `.layer(Extension(...))`; request-scoped services use
a per-request `FromRequestParts` extractor.

## Status

These are reference macros shipped alongside RFC-009. Concrete
fragment retrofits land in follow-up PRs — `llm_anthropic` and
`rag_qdrant` are the canonical first candidates.
