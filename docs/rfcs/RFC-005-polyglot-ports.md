# RFC-005 — Polyglot Ports Roadmap

- **Status:** Deferred — revisit Q2 2027
- **Author:** cchifor
- **Created:** 2026-04-21
- **Version scope:** 1.1.x design document; implementation target 2.x

## Summary

ADR-002 ("pragmatic hexagonal — ports and adapters for vector_store,
llm, queue, object_store") defined four interface ports and shipped
Python implementations of all four. Node and Rust ship none. This RFC
specifies the cross-language contract shape, enumerates the adapters
we'd need to reach polyglot parity, and — based on realistic resource
estimates — **defers implementation to the 2.x line** in favour of
deepening Python capabilities in 1.x.

## Context

The 1.0 polyglot narrative was "three backends with equal feature
coverage." Reality today (per `tests/test_options.py` + a fragment
coverage audit):

| Category | Python | Node | Rust |
| --- | --- | --- | --- |
| Reliability middleware | 6 fragments | 3 | 3 |
| Observability | 3 | 2 | 2 |
| Conversational AI (agent, chat persistence, streaming, tools) | 4 | 0 | 0 |
| Knowledge / RAG (backend, embeddings, reranker, top_k) | 8 | 0 | 0 |
| Ports (llm, queue, vector_store, object_store) | 4 | 0 | 0 |
| LLM providers (anthropic, openai, google, openrouter) | 4 | 0 | 0 |
| MCP | 2 | 0 | 0 |
| **Total** | **31** | **5** | **5** |

Epic J (1.1.x) closes the ops-parity gap — reliability, observability,
and middleware fragments backfilled for Node + Rust via Epic K's
`MiddlewareSpec`. **This RFC is about everything else.**

## Goals

1. Specify port contracts as language-neutral TypeSpec definitions so
   every adapter (Python, Node, Rust, any future plugin language)
   conforms to one source of truth.
2. Enumerate the per-port + per-backend + per-provider work items so
   the scope is honest.
3. Decide whether to invest in the work now, later, or not at all.

## Non-goals

- Designing the ports themselves — ADR-002 did that.
- Backfilling conversational AI or RAG fragments for Node/Rust. Those
  are out of scope for a "ports" RFC because the work is dominated by
  orchestration logic, not port shape.

## Port Contracts (proposed)

Each port gets one TypeSpec file under `forge/templates/_shared/ports/`:

```
_shared/ports/
  queue/contract.tsp
  object_store/contract.tsp
  llm/contract.tsp
  vector_store/contract.tsp
```

### queue_port

```typespec
@service({ title: "Queue Port" })
namespace ForgeQueue;

@doc("A durable async job.")
model Job {
  id: string;
  topic: string;
  body: bytes;
  attempts: int32;
  scheduledFor?: utcDateTime;
}

interface Queue {
  enqueue(topic: string, body: bytes, options?: EnqueueOptions): string;
  poll(topic: string, maxMessages: int32): Job[];
  ack(jobId: string): void;
  nack(jobId: string, requeue?: boolean): void;
}
```

### object_store_port

```typespec
interface ObjectStore {
  put(bucket: string, key: string, body: bytes, metadata?: Record<string>): void;
  get(bucket: string, key: string): ObjectData;
  delete(bucket: string, key: string): void;
  presignGet(bucket: string, key: string, ttlSeconds: int32): string;
  presignPut(bucket: string, key: string, ttlSeconds: int32): string;
}
```

### llm_port

Streaming semantics are the hard part — needs a shared chunk shape across
Python `AsyncIterator`, Node `AsyncIterable`, and Rust `futures::Stream`.

```typespec
model LlmChunk {
  delta: string;
  finishReason?: string;
  toolCall?: ToolCallChunk;
}

interface LLM {
  @doc("Streaming chat completion. Implementations MUST emit chunks as they arrive.")
  complete(prompt: ChatPrompt, options: LlmOptions): LlmChunk[];  // stream
  embed(texts: string[]): float32[][];
}
```

### vector_store_port

```typespec
interface VectorStore {
  upsert(collection: string, vectors: Vector[]): void;
  search(collection: string, query: float32[], topK: int32): Match[];
  delete(collection: string, ids: string[]): void;
}
```

## Adapter inventory

| Port | Python (shipped) | Node (new) | Rust (new) |
| --- | --- | --- | --- |
| queue | `port` + redis + sqs | `bullmq` | `apalis` |
| object_store | `port` + s3 + local | `@aws-sdk/client-s3` | `aws-sdk-s3` |
| llm | `port` + openai + anthropic + bedrock + ollama | `ai-sdk` / vercel + anthropic-ts | `rig` / `async-openai` + anthropic-rs |
| vector_store | `port` + qdrant + chroma + pinecone + milvus + weaviate + pgvector + postgresql | `@qdrant/js-client-rest` + `chromadb` | `qdrant-client` + `chromadb-rs` (immature) |

**Total new adapters:** 2 (queue) + 2 (object_store) + 8 (LLM providers ×
2 languages) + 4 (vector_store providers × 2 languages, where mature
clients exist) = **16 new adapter fragments minimum.**

Each adapter needs:
1. Port trait/interface definition in the target language (generated
   from TypeSpec).
2. Adapter implementation calling the vendor SDK.
3. Configuration wiring (env vars, DI).
4. Unit tests against a mock backend.
5. Integration tests against a live instance (Docker test containers).

**Per-adapter effort estimate:** 3-5 engineer-days.

**Total effort:** 16 × 4 days = ~13 engineer-weeks of focused work.

## Options considered

### Option A — full polyglot ports in 1.1.x

- Pros: Delivers on the "three backends, one feature set" promise.
- Cons: ~13 engineer-weeks, dominating the 1.1.x runway. Displaces
  everything else on the roadmap. Requires per-language expertise
  (async streaming in Rust is hard; Node's AsyncIterable ergonomics
  around error handling need care).

### Option B — phased rollout (queue + object_store in 1.1, LLM + vector_store in 1.2)

- Pros: Gets the simpler ports done first, buys time to stabilise the
  LLM streaming contract.
- Cons: Still ~5 engineer-weeks in 1.1.x alone. The "simpler" ports
  are the least differentiating — users pick forge for the AI stack
  more than for the queue abstraction.

### Option C — deepen Python, defer polyglot ports to 2.x ✅ **RECOMMENDED**

- Pros: 1.1.x budget goes to observable wins (reliability backfill,
  auth flexibility, codegen semantic tests, MiddlewareSpec adoption).
  When polyglot ports land in 2.x, the Python adapters have stabilised
  + the contract is informed by real Python usage.
- Cons: Node + Rust remain "pure HTTP service" backends until 2.x
  ships. Users who want an agentic app in Node/Rust wait.

### Option D — drop Node + Rust polyglot aspiration

- Pros: Simplifies the roadmap.
- Cons: Breaks explicit 1.0 promises. The value is in the polyglot
  story — most competitors are single-language.

## Recommendation

**Option C.** Accept that 1.0 overclaimed parity; document the gap
honestly (done — `docs/known-issues.md` has a row); ship the Python
depth + ops parity that's genuinely close; revisit polyglot ports in
2.x when the port shapes are settled by 12+ months of Python
production use.

When 2.x planning starts, this RFC is the starting point.

## Consequences

- `docs/FEATURES.md` should clarify per-feature backend coverage (the
  current table lists backends per Option but reads as "all supported"
  because the enabled/disabled distinction is buried). Tracked as a
  P2 doc task.
- Epic J (Node + Rust ops parity) is the only cross-language work in
  1.1.x. Everything else Python-centric.
- Plugin authors who need LLM/vector-store access in Node today can
  ship their own `forge-plugin-<provider>-<language>` package; the
  plugin SDK already supports it. Their adapters don't conform to a
  standardised port contract yet — that's the whole point of this RFC.

## Decision

**Deferred to 2.x.**

A narrower follow-up in 1.x: publish the TypeSpec contract files
(spec-only, no adapters) under `forge/templates/_shared/ports/` so
plugin authors writing Node/Rust adapters independently have something
to conform to. That's ~2 engineer-days and worth doing. Tracked as a
P2 epic in `plans/`.
