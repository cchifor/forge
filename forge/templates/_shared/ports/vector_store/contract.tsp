// vector_store_port — TypeSpec contract for the vector-search port.
//
// Source of truth: RFC-005 § "Port Contracts" → vector_store_port.
// The `interface VectorStore` block matches the RFC verbatim. Supporting
// `model` declarations (Vector, Match, Filter) are introduced here because
// the RFC referenced them by name without defining the bodies — the shapes
// mirror the Python reference at
// `forge/features/rag/templates/vector_store_port/python/files/src/app/ports/vector_store.py`
// (VectorHit + the `(id, embedding, text, metadata)` tuple form of `upsert`).
//
// Spec-only. No code is generated from this file today.
//
// Reconciliation notes:
//   * The Python reference threads `tenant_id` through every call (a forge-
//     specific multi-tenancy convention). The RFC's cross-language contract
//     uses `collection: string` — adapters MAY namespace collections by
//     tenant (`<tenant>__<collection>`) to recover the Python behaviour.
//   * The Python reference exposes `ensure_collection(tenant_id, dim)`;
//     the RFC omits this — provisioning is intentionally left to per-
//     adapter setup (some providers create collections lazily on first
//     upsert; others require explicit DDL).
//   * Metadata filtering (`filters: dict[str, Any]` in Python) is added as
//     an optional `Filter` model below; the RFC's `search` signature lacks
//     it, but every credible provider supports the pattern and omitting it
//     here would force every caller into a non-standard extension.

import "@typespec/openapi3";

@service(#{ title: "Vector Store Port" })
namespace ForgeVectorStore;

@doc("One vector to upsert: id + embedding + the source text + arbitrary metadata.")
model Vector {
  @doc("Stable id for this vector; re-upserting the same id replaces the prior record.")
  id: string;
  @doc("Embedding values; length MUST match the collection's configured dimension.")
  values: float32[];
  @doc("Source text the embedding was computed from. MAY be empty for binary embeddings.")
  text?: string;
  @doc("Arbitrary metadata; adapters MAY restrict supported value types per their backend.")
  metadata?: Record<unknown>;
}

@doc("One hit from a similarity search.")
model Match {
  @doc("Id of the matched vector.")
  id: string;
  @doc("Similarity score; higher is more similar. Scale is provider-specific.")
  score: float32;
  @doc("Source text recorded on upsert; absent if the upsert omitted it.")
  text?: string;
  @doc("Metadata recorded on upsert.")
  metadata?: Record<unknown>;
}

@doc("Metadata filter applied to a `search` call; value semantics are adapter-specific.")
model Filter {
  @doc("Metadata key the filter applies to.")
  key: string;
  @doc("Match operator — `eq`, `neq`, `in`, `gt`, `gte`, `lt`, `lte`.")
  operator: string;
  @doc("Comparison value; type depends on the metadata key's value type.")
  value: unknown;
}

@doc("Cross-language vector-store capability — upsert, search, delete.")
interface VectorStore {
  @doc("Upsert a batch of vectors into `collection`. Idempotent by `Vector.id`.")
  upsert(collection: string, vectors: Vector[]): void;

  @doc("Return the `topK` most similar vectors to `query` from `collection`.")
  search(collection: string, query: float32[], topK: int32, filters?: Filter[]): Match[];

  @doc("Remove vectors by id. Idempotent — deleting missing ids is not an error.")
  delete(collection: string, ids: string[]): void;
}
