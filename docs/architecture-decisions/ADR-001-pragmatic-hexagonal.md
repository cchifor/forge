# ADR-001: Pragmatic hexagonal architecture for generated backends

- Status: Accepted
- Author: forge team
- Date: 2026-04-20
- Scope: backend templates (Python/FastAPI, Node/Fastify, Rust/Axum) in `forge/templates/services/`

## Context

Every forge-generated backend currently follows a layered architecture: `routes → services → repositories → database`. This is a pragmatic default and works well for CRUD. As Phase 2.3 introduces ports-and-adapters for swappable integrations (vector store, LLM provider, object store, queue), we need to clarify how far we push hexagonal purity before it becomes boilerplate.

Two forces pull in opposite directions:

1. **Testability and swappability.** Every external dependency should sit behind an interface so unit tests can mock it and production can swap providers. This is the value of hexagonal architecture.
2. **Ceremony avoidance.** Strict hexagonal (ports around every service, use-case classes, command-bus, DTOs at every layer) produces ten files where three would do. Small teams reject it; maintainers fight it.

A decision framework, codified once, saves every future contributor the same debate.

## Decision

**forge templates adopt pragmatic hexagonal: ports only at I/O edges.**

- **Ports exist for every external dependency.** Database, HTTP clients, message bus, LLM provider, vector store, object store, queue — each has a `src/app/ports/<capability>.py` (or equivalent) declaring the contract.
- **Adapters implement ports** in `src/app/adapters/<capability>/<provider>.py`. Multiple adapters can coexist; the container wires the one the user selected.
- **Domain and services stay plain classes.** No command bus, no use-case classes, no CQRS scaffolding. A `CreateItemService.handle(cmd)` is overkill when `ItemService.create(item)` reads the same.
- **No DTOs between domain and services.** Pydantic / Zod / serde structs flow through the layers. A DTO layer buys nothing on a CRUD scaffold.
- **Controllers (routes) can construct requests directly.** FastAPI's `Depends`, Fastify's route schemas, Axum's extractors already enforce shape at the boundary; a middleman factory is waste.

### Where the line sits

```
┌──────────────────────────────────────────────────────────────────┐
│  HTTP / message transport                                        │
└──────────────────────┬───────────────────────────────────────────┘
                       │
              ┌────────▼────────┐
              │    routes/      │  (adapter for HTTP — stays thin)
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │   services/     │  (business logic — plain classes)
              └────────┬────────┘
                       │
   ┌───────────────────┼────────────────────────┐
   │                   │                        │
┌──▼───────┐    ┌──────▼──────┐       ┌────────▼────────┐
│ ports/   │    │ ports/      │       │ ports/          │
│ item_    │    │ vector_     │       │ llm.py          │
│ repo.py  │    │ store.py    │       │                 │
└──┬───────┘    └──────┬──────┘       └────────┬────────┘
   │                   │                       │
┌──▼─────────┐  ┌──────▼──────────┐    ┌──────▼──────────────┐
│ adapters/  │  │ adapters/       │    │ adapters/           │
│ db_sql.py  │  │ vector_store/   │    │ llm/                │
│            │  │  qdrant.py      │    │  openai.py          │
│            │  │  chroma.py      │    │  anthropic.py       │
│            │  │  pinecone.py    │    │  ollama.py          │
└────────────┘  └─────────────────┘    └─────────────────────┘
```

Ports **only** at the I/O boundary. Inside the hexagon (domain + services), there's no ceremony.

## Alternatives considered

### Strict hexagonal

Every inter-layer call goes through an interface. Command bus routes requests to use-case handlers. DTOs convert between representations at every boundary.

**Rejected** because:
- CRUD scaffolds don't need the indirection; it's solving a problem the user doesn't have yet.
- Future maintainers will either fight it (deleting it layer by layer as they extend the scaffold) or give up and duplicate logic around it.
- Teams we talked to found strict hexagonal templates harder to extend, not easier.

### Onion architecture

Domain at the core, application services in a ring, infrastructure in the outermost ring. Conceptually similar to hexagonal but with explicit dependency-inversion direction.

**Rejected** because it's a rename of hexagonal with extra diagrams. No material difference at the 80/20 line.

### Layered only (current state)

What forge ships today: routes → services → repositories → DB, no ports. Repositories are concrete `ItemRepository` classes, not interfaces. Integrations live alongside services (e.g. `services/qdrant_client.py`).

**Rejected going forward** because it can't support provider swapping at runtime (Phase 2.3's goal) without a compat shim that ends up being a port anyway.

## Consequences

### Positive

- Tests can mock any port in 3 lines. `fake_vector_store = FakeVectorStore(); container[VectorStorePort] = fake_vector_store`.
- Swap Qdrant → Pinecone in production via `.env` + container config. No regeneration.
- Plugins (Phase 0.3 hook; Phase 2.3 rollout) can provide new adapters without forking forge.
- ADRs settle the question once; new contributors don't re-litigate layer shapes in every PR.

### Negative

- Users who want a single-file backend for a tiny project will see more structure than they need. Mitigated by: the generated project is a starting point; they can flatten it if they want.
- Ports + adapters adds two directories per integration. In exchange for swappability and testability. We judge this trade worth it.

### Neutral

- The existing templates need one refactor pass to move integrations behind ports (Phase 2.3). Non-breaking at the public API; affects internal imports in generated projects.

## How to tell if a file should have a port

A file should sit behind a port if **any** of:

1. It makes a network call (HTTP, SQL, gRPC, SSE).
2. It opens a file from the filesystem for reasons outside configuration bootstrap.
3. It reads wall-clock time where tests would benefit from injecting a fake clock.
4. The user might plausibly want to swap its provider without regenerating.

If **none** apply, it's domain/service code — plain class, no port, no ceremony.

## References

- Alistair Cockburn, *Hexagonal Architecture* (2005).
- Vaughn Vernon, *Implementing Domain-Driven Design* (2013), chapters on application services.
- Forge Phase 2.3 (ports-and-adapters refactor) — see `docs/rfcs/RFC-002-breaking-change-contract.md` and the master plan.
