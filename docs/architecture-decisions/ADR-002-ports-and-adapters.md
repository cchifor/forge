# ADR-002: Ports-and-adapters for integrations

- Status: Accepted
- Author: forge team
- Date: 2026-04-20
- Supersedes: existing bespoke integrations (rag_qdrant, rag_chroma, …)
- Depends on: ADR-001 (pragmatic hexagonal)

## Context

Forge 0.x ships integrations as one-fragment-per-provider: `rag_qdrant`, `rag_chroma`, `rag_milvus`, `rag_pinecone`, `rag_weaviate`, `rag_postgresql`, `rag_embeddings_voyage`. Each carries its own Python module that the backend imports directly.

Consequences:

- **Mutually exclusive by construction.** A project that wants Qdrant in dev and Pinecone in prod must re-run forge when switching — the integration code is hard-wired at generation time.
- **Drift across providers.** Interface shapes aren't enforced; a user adding a seventh vector store must reverse-engineer what the other six look like.
- **Plugin authors can't add a provider.** Third parties must fork forge and mimic the existing fragment layout.

Phase 2.3 of the 1.0 roadmap introduces ports-and-adapters as the default pattern for every external integration.

## Decision

**Every integration capability becomes a `(port, adapters)` pair.**

- The **port** is a Python Protocol (or equivalent in Node/Rust) declaring the capability's surface. Always emitted into the project when any adapter is selected.
- **Adapters** implement the port for specific providers. Exactly one adapter per capability is wired into the dependency container at boot.
- **Swapping providers** happens in `.env` + container config, not regeneration.

### Capability inventory (Phase 2.3 rollout)

| Capability | Port module | Adapters |
|---|---|---|
| vector store | `src/app/ports/vector_store.py` | qdrant, chroma, milvus, pinecone, weaviate, postgres (pgvector) |
| LLM provider | `src/app/ports/llm.py` | openai, anthropic, ollama, bedrock |
| object store | `src/app/ports/object_store.py` | s3, gcs, minio, local |
| queue / scheduler | `src/app/ports/queue.py` | redis, sqs, rabbit, hatchet |

### Fragment structure

Before:

    _fragments/
      rag_qdrant/python/{files,inject.yaml}
      rag_chroma/python/{files,inject.yaml}
      ...

After:

    _fragments/
      vector_store_port/python/{files,inject.yaml}        # always applied
      vector_store_qdrant/python/files/                   # adapter only
      vector_store_chroma/python/files/
      ...

The `vector_store_port` fragment emits `ports/vector_store.py`. Each adapter emits one file under `adapters/vector_store/`. The adapter's `inject.yaml` registers the concrete implementation with the container (dishka in Python) — a ~3-line injection at a `# forge:anchor container.registrations` anchor.

### Selection at generation-time

A single Option — `rag.backend` — still drives which adapter lands. The option's `enables` map now points at `("vector_store_port", "vector_store_<name>")` instead of `("rag_<name>",)`. The port is always in the fragment plan alongside the adapter, so deps resolve transparently.

### Runtime swappability

Once generated, the project's container reads the adapter choice from `.env`:

```python
# src/app/core/container.py
from app.ports.vector_store import VectorStorePort

if settings.vector_store_provider == "qdrant":
    container.register(VectorStorePort, QdrantAdapter)
elif settings.vector_store_provider == "pinecone":
    container.register(VectorStorePort, PineconeAdapter)
# ...
```

The user edits `.env`, restarts the service, and the app routes through the new adapter. **No regeneration.**

### Plugin authors

Third-party plugins can add adapters (e.g. `forge-plugin-vector-opensearch`) by registering a fragment whose `inject.yaml` wires a new adapter into the container's provider switch. The port stays owned by forge core; adapters are the extension point.

## Migration plan (per-capability)

1. **Create the port fragment** — emits the Python Protocol (or Node interface, Rust trait).
2. **Refactor each existing integration** — split into an adapter-only fragment; the port becomes shared.
3. **Rewire the Option** — `rag.backend=qdrant` now enables `(vector_store_port, vector_store_qdrant)`.
4. **Ship a `forge migrate-adapters` codemod** that rewrites existing generated projects to the new structure.

## Phase 2.3 scope vs follow-up

**This alpha (1.0.0a1) lands:**

- This ADR, codifying the pattern.
- The `forge/templates/_fragments/ports/` directory convention.
- A reference port+adapter pair for **vector store** with Qdrant as the first adapter.

**1.0.0a2 lands:**

- Full refactor of the remaining RAG fragments (chroma, milvus, pinecone, weaviate, postgres).
- LLM provider ports and 4 adapters.
- `forge migrate-adapters` codemod.

**1.0.0a3 lands:**

- Object store ports + 4 adapters.
- Queue / scheduler ports + 4 adapters.
- Dependency container best-practices ADR for Node and Rust (dishka is Python-only).

Running the refactor over three alphas keeps each PR reviewable — a big-bang across 7 capabilities would be a ~3000-line diff.

## Consequences

### Positive

- One swap = one env var; no regeneration.
- Plugin authors have a clear contract for new providers.
- Tests can mock a port in 3 lines; end-to-end tests can run against an in-memory adapter.
- New capabilities (e.g. "cache layer") follow the same pattern, which is now well-worn.

### Negative

- Two directories per capability instead of one. In exchange for swappability.
- Port + adapter coordination adds a small mental cost for fragment authors.
- Existing pre-1.0 projects need a one-time migration (scripted via `forge migrate-adapters`).

### Neutral

- Fragment count grows (one port + N adapters replaces N bespoke integrations). The `forge --list` output absorbs this via the category grouping; no UX regression.
