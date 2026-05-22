# Implementation review — feat/typespec-port-contracts — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 11 findings; 11 ACCEPT, 0 PUSHBACK, 0 QUESTION) -->

## Codex verdict

**ACCEPT — MERGE IMMEDIATELY.** Codex's recommendation: "No blockers. The
spec-only foundation is solid, RFC-faithful, and ready for plugin authors
to build against."

## Findings + responses (all ACCEPT)

### 1. RFC-005 queue port fidelity
Verbatim Job model + Queue interface. `EnqueueOptions` defined where
RFC referenced but didn't define body (delaySeconds + dedupKey,
justified in contract header). Python `receipt` vs RFC `jobId` split
documented per RFC-012.

### 2. RFC-005 object_store port fidelity
All five interface methods (put, get, delete, presignGet, presignPut)
match RFC exactly. `ObjectData` supporting type defined where RFC
referenced but didn't define body. Python-only `stream()` omitted
(streaming is language-specific); `presignUrl(method=...)` split to
two methods (per RFC enum). Honest header comments.

### 3. RFC-005 llm port fidelity
LlmChunk model exact match. Supporting types (ChatPrompt, ChatMessage,
Tool, ToolCallChunk, ChatRole enum, LlmOptions) inferred sensibly where
RFC referenced but didn't define. Streaming-only contract correct (RFC
specifies "streaming semantics are the hard part"). **Field rename:**
`LlmOptions.modelId` (TypeSpec reserved keyword on `model`) — RFC didn't
define body, safe rename.

### 4. RFC-005 vector_store port fidelity
All three interface methods (upsert, search, delete) match RFC. Vector,
Match, Filter inferred where RFC referenced but didn't define.
**Documented additions:** optional `filters?: Filter[]` in search()
(RFC omitted but every credible provider supports it; comment justifies
"prevents downstream non-standard extensions"). **Documented omissions:**
`tenant_id` (forge-specific multi-tenancy, not RFC), `ensure_collection`
(per-adapter provisioning). **Field rename:** `Filter.operator` (TypeSpec
reserved keyword on `op`) — RFC didn't define body, safe rename.

### 5. TypeSpec syntax validity
All 4 contracts parseable by `tsp compile --emit @typespec/openapi3`.
Correct keyword use (`model`, `interface`, `op`, namespaces). Imports
correct (`@typespec/openapi3`). Comprehensive `@doc` annotations.
Local verification: `@typespec/compiler@0.66.0` accepts all 4.

### 6. CLI command shape (`forge --ports-validate`)
- Discovery-based (walks `_shared/ports/<port>/`, doesn't hardcode names)
- Sorted output (deterministic)
- npx skip semantics correct (exit 0 with helpful message)
- Three terminal paths: no contracts → exit 0 + warning, npx missing →
  exit 0 + skip, any invalid → exit 1
- Text + JSON output supported

### 7. CLI wire-up
`--ports-validate` flag registered with `dest="ports_validate"`,
placed after `--doctor` in parser (logical grouping). main.py dispatch
after `--verify` before `--harvest` (consistent ordering). Lazy import
for the dispatcher.

### 8. Test coverage (36 tests)
Right scope for spec-only feature. Does NOT call real `tsp compile`
(would force node + TypeSpec on every contributor). Tests:
- All 4 contract files exist (4 tests)
- Structural checks: namespace, interface, model keywords per port (9 tests)
- CLI flag wired (3 tests)
- Discovery sorted + handles missing root (3 tests)
- Skips cleanly without npx (2 tests)
- Skips cleanly without contracts (1 test)
- Dispatch exit codes (3 tests)
- Plus per-port RFC signature presence (enqueue/poll/ack/nack for queue,
  put/get/delete/presignGet/presignPut for object_store, etc.)

### 9. README accuracy
Spec-only nature explicit. Validation opt-in documented. Future work
(TS→bindings POC, Featured Plugin CI) referenced honestly. Plugin
author guidance clear.

### 10. Public-API stability
All deviations scoped + justified in contract headers. Unlikely to
change in 1.x once published.

### 11. Commit style
`feat(ports): add TypeSpec contracts for 4 ports` (45 chars) ✓.
CHANGELOG entry honest.

## Convergence

11 findings — **11 ACCEPT, 0 PUSHBACK, 0 QUESTION.** No round 2
dispatched — no actionable feedback; codex explicitly recommends
"MERGE IMMEDIATELY."

## Diff stat (unchanged)

```
 CHANGELOG.md                                            |  18 ++
 forge/cli/commands/ports.py                             | 213 ++++++++++++++
 forge/cli/main.py                                       |   5 +
 forge/cli/parser.py                                     |  18 ++
 forge/templates/_shared/ports/README.md                 |  80 ++++++
 forge/templates/_shared/ports/llm/contract.tsp          | 109 +++++++
 forge/templates/_shared/ports/object_store/contract.tsp |  54 ++++
 forge/templates/_shared/ports/queue/contract.tsp        |  62 ++++
 forge/templates/_shared/ports/vector_store/contract.tsp |  76 +++++
 tests/test_typespec_contracts.py                        | 313 +++++++++++++++++++++
 10 files changed, 948 insertions(+)
```

Plus this impl-review file.
