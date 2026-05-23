# Port Contracts (TypeSpec)

This directory holds the language-neutral contract files for forge's
four "pragmatic hexagonal" ports — see ADR-002 and
[RFC-005](../../../docs/rfcs/RFC-005-polyglot-ports.md) § "Port
Contracts" for the why.

```
_shared/ports/
  queue/contract.tsp          # async work — enqueue / poll / ack / nack
  object_store/contract.tsp   # blob I/O — put / get / delete + presigned URLs
  llm/contract.tsp            # LLM provider — streaming chat + embeddings
  vector_store/contract.tsp   # similarity search — upsert / search / delete
```

## What these files are

**Spec files**, written in [TypeSpec](https://typespec.io/). They define
the cross-language port shape every adapter (Python today; Node / Rust /
future plugin languages tomorrow) must conform to. RFC-005 § "Port
Contracts" is the canonical source — the bodies here are copied
verbatim where the RFC provides them, with supporting `model`
declarations added where the RFC referenced a type by name without
defining its body. Reconciliation notes (Python reference vs. RFC) live
in a comment header inside each `contract.tsp`.

## What these files are NOT

**They do not generate code.** There is no `forge` codegen step that
consumes these files today. The Python port references at
`forge/features/{async_work,object_store,agent,rag}/templates/.../python/...`
are hand-written and remain authoritative for Python adapters. Node and
Rust adapters do not exist yet (RFC-005 defers the work to 2.x); plugin
authors writing their own Node / Rust adapters can validate
implementation shape against these `.tsp` files independently.

A "TypeSpec → language bindings" POC is planned for 1.4 (see plan
Pillar D point 3) — if it lands cleanly, these contracts become the
generator input; if it doesn't, they stay as documentation. Either
outcome is fine.

## Validating the contracts

Run `forge --ports-validate` to compile every `contract.tsp` under this
directory through `@typespec/compiler` + the `@typespec/openapi3`
emitter:

```console
$ forge --ports-validate
queue        VALID
object_store VALID
llm          VALID
vector_store VALID
```

The command shells out to `npx -y @typespec/compiler ...`. If `npx` is
not on `$PATH` it skips cleanly with a warning — node is not a hard
forge dependency. CI environments that want contract-validation
coverage need to provision node alongside python.

## For plugin authors

If you are shipping a Node or Rust port adapter outside the forge core,
treat the matching `contract.tsp` as the spec your implementation must
satisfy. Today validation is by inspection (run `forge
--ports-validate` to confirm the spec parses, then implement against
the shape it documents). The Featured Plugin CI tier (plan Pillar D
point 4) will eventually run a fitness suite against your adapter
against these contracts.

## Future work

- **TypeSpec → bindings POC** (1.4, plan Pillar D point 3) — emit
  `queue.ts` + `queue.rs` from `queue/contract.tsp` via a new
  `forge/codegen/typespec_bindings.py` module.
- **Featured Plugin CI tier** (1.4, plan Pillar D point 4) — exercise
  curated plugins against these contracts in CI.
- **`vector_store` polyglot deferred** — `chromadb-rs` is immature per
  RFC-005 § "Adapter inventory"; entry pending in
  `docs/known-issues.md`.
