# RFC-009 — Cross-backend service registration contract

| Field | Value |
| --- | --- |
| Status | Accepted |
| Author | Architecture review 2026-04 |
| Epic | 1.0.0-ga |
| Supersedes | — |
| Replaces | — |

## Summary

Define a single declarative contract for "this fragment contributes a
runtime service" that fragment authors can express once and have
rendered idiomatically in every backend (Python / Dishka, Node /
Fastify, Rust / Axum). The contract does *not* force a shared DI
framework — it forces a shared way to *describe* what a service is,
while letting each backend emit its idiomatic registration code.

Complementary to RFC-008 (config loading) and the P0.4 capability→
docker-compose service registry: where the former is about *shape of
runtime config* and the latter is about *shape of sidecar
containers*, this RFC is about *how application-level services get
wired into the dependency graph*.

## Motivation

A fragment that adds an `AnthropicClient` today must hand-author three
idioms:

- Python: a `dishka.Provider` subclass with `@provide` method
  (`services/python-service-template/.../core/ioc/llm_anthropic.py`).
- Node: a service-locator export or Fastify decorator
  (`services/node-service-template/.../services/llm-anthropic.ts`).
- Rust: an `Axum::State<T>` extension registered on the router
  (`services/rust-service-template/.../services/llm_anthropic.rs`).

Each idiom diverges in scoping semantics (request vs singleton),
lifecycle (startup / shutdown hooks), and testability. New fragment
authors pay this tax three times. The cross-backend consistency of
these registrations is the single biggest DX gap flagged in the
architecture review.

## The contract

A fragment declares services in a YAML file
(`_fragments/<name>/services.yaml`) shaped like:

```yaml
services:
  - name: anthropic_client
    type: AnthropicClient
    scope: singleton        # singleton | request | transient
    dependencies: []        # names of other services this one needs
    config_key: llm.anthropic
    languages: [python, node, rust]
    startup: true           # instantiate eagerly on app boot
```

Fields:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `name` | string | ✅ | Snake-case identifier for the service. Used in injection and logs. |
| `type` | string | ✅ | Per-backend class / trait name. Expand via templates. |
| `scope` | enum | ✅ | `singleton` (one per process), `request` (one per HTTP request), `transient` (new every resolve). |
| `dependencies` | [string] | — | Names of other services whose handles this service takes as constructor args. |
| `config_key` | string | — | Dotted path into `AppConfig` whose sub-tree is injected as the service's config parameter. |
| `languages` | [string] | ✅ | Subset of `[python, node, rust]` the service ships for. |
| `startup` | bool | — | Eagerly instantiate on app boot (surfaces connection errors early). Default `false`. |
| `shutdown_hook` | string | — | Method name called on graceful shutdown. Default none. |

## Rendering

Each language ships a Jinja macro (`_shared/service_registration/
{python,node,rust}.jinja`) that consumes a service declaration and
emits idiomatic registration code:

- **Python**: a `dishka.Provider` subclass with `@provide` method,
  scope translated (`singleton` → `Scope.APP`, `request` →
  `Scope.REQUEST`, `transient` → `Scope.REQUEST` + `provides=...`).
- **Node**: a decorated Fastify plugin with `fastify.decorate('name',
  ...)` for singletons, `fastify.decorateRequest` for request-scoped.
- **Rust**: a `tower::Layer` or `Axum::State<Arc<T>>` declaration
  (singleton), or per-request extension (request-scoped).

The fragment provides the service implementation (a `class` /
`interface` / `struct`); the macro handles the wiring. Authors do not
see the Dishka / Fastify / Axum boilerplate.

## Implementation

This RFC is scoped as design-only in the first pass. Implementation
(the Jinja macros and a retrofit of 1–2 existing fragments) lands in
follow-up PRs. The P0.4 service registry already supplies the
capability → docker-compose mapping; this RFC covers the
application-level layer above it.

Macros will live at:
- `forge/templates/_shared/service_registration/python_provider.jinja`
- `forge/templates/_shared/service_registration/node_plugin.jinja.ts`
- `forge/templates/_shared/service_registration/rust_layer.jinja.rs`

The fragment's `services.yaml` is parsed by `feature_injector` (or a
new dedicated applier under `forge/appliers/`) and each entry triggers
a macro render into the target backend's service module.

## Backward compatibility

Existing fragments that hand-wrote their DI / service registration
continue to work unchanged. Adopting RFC-009 is opt-in per fragment;
the cost of migration is a single YAML declaration per service.

## Alternatives considered

- **Force a single DI framework cross-language**: rejected as a
  significant DX regression — Python users expect Dishka, Node users
  expect Fastify plugins, Rust users expect Axum state extractors. The
  chosen approach preserves each ecosystem's idiom.
- **Codegen per backend from a shared `.proto`-like IDL**: considered,
  rejected as overkill for what is ultimately declarative metadata
  rather than a contract that external systems need to consume.
- **Plugin-ship the templates instead of shared macros**: considered,
  but shared macros ensure every fragment author gets the same
  up-to-date idiomatic scaffolding when forge upgrades the backend
  templates.
