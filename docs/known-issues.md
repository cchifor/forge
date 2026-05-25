# Known Issues

Bugs + limitations the team is aware of. Each row is either deferred
(tracked for a future release) or gated on external dependencies we
can't reasonably fix ourselves.

If you're tempted to add a workaround to your generated project, please
check here first — a known issue usually has an official workaround or
is about to land fixed in an upcoming release.

## Template + generator

| Issue | Impact | Workaround | Tracking |
| --- | --- | --- | --- |
| Svelte + chat path's `@ag-ui/client` e2e test (`svelte_chat_on_typechecks`) is skipped | Svelte chat flow isn't exercised in nightly CI. | Generate + test manually; the Vue chat path is covered (Flutter chat is also skipped — see below). | Tracked upstream — `@ag-ui/client` type drift. Re-enable when the chat scaffolding under `forge/templates/apps/svelte-frontend-template/template/src/lib/features/chat/` is updated to the current `@ag-ui/client` 0.0.51 API. |
| Flutter + chat path's e2e test (`test_flutter_full_analyzes`) is skipped | Flutter chat (auth + chat + openapi) isn't exercised in nightly CI. | Generate + run `flutter analyze` manually with a `dependency_overrides` block pointing `forge_canvas` at `packages/forge-canvas-dart/` via `path:`. | Tracked under RFC-003 — un-skip once `forge_canvas` ships to pub.dev (today the generated pubspec pins `^1.0.0-alpha.6`, which isn't published; the template comment under `forge/templates/apps/flutter-frontend-template/{{project_slug}}/pubspec.yaml:36` documents the workaround). |

## Platform

| Issue | Impact | Workaround | Tracking |
| --- | --- | --- | --- |
| Rust cold-build times in CI exceed 5 min on first run | Nightly e2e has a 40-min budget; a cold cargo cache can push close. | `Swatinem/rust-cache@v2` warms across runs. The first run after a cache invalidation is painful but recovers. | Fresh-runner perf is out of our control. |
| Flutter SDK first-run install adds ~90s to CI | Adds a constant overhead to every job that needs Flutter. | `subosito/flutter-action@v2` with `cache: true` reduces this to ~5s on subsequent runs. | n/a. |
| macOS not in nightly e2e | Rust/cargo behaviour differences on macOS won't be caught until a user hits them. | Run `make test` locally on macOS if you contribute macOS-specific code. | Epic W adds a macOS leg — deferred to Q4. |

## Polyglot (Node/Rust)

| Issue | Impact | Workaround | Tracking |
| --- | --- | --- | --- |
| Node + Rust ship only 8 of the 54 fragments (15%) | Node and Rust lack the agent/RAG/LLM/MCP/admin stack that Python has. | Python remains the canonical "rich" backend. Node/Rust are for pure-service workloads. | Epic J backfills the ops fragments in 1.1.x. Full AI/RAG parity is design-only (RFC-Q) pending polyglot port investment. |
| `observability.tracing` is a no-op on Node + Rust | The option registers but the fragment doesn't emit tracing code. | Set it to `false` on non-Python backends to silence the option from `forge --list` noise. | Epic J Phase 3 (observability backfill). |
| `llm.provider` ships **only OpenAI** on Node + Rust; Anthropic / Ollama / Bedrock are Python-only (1.x) | Picking `llm.provider=anthropic` / `ollama` / `bedrock` on a Node or Rust backend resolves the abstract `llm_port` but no adapter — the service starts without an LLM wired and fails at first invocation. | Use `llm.provider=openai` on Node / Rust; install Anthropic / Ollama / Bedrock as plugins (Featured Plugin tier — `forge-plugin-anthropic-node`, etc.) once those exist; or pick `backend.language=python` for non-OpenAI providers. | Pillar D.2 — full polyglot provider matrix deferred to 2.x. The plan is honestly scoped: OpenAI's TS (`@ai-sdk/openai`) + Rust (`async-openai`) SDK ecosystems are mature enough for in-tree adapters; the others aren't, and the Python-first SDK ecosystem (anthropic-python, ollama-python, aioboto3) doesn't have peer cross-language libraries that meet forge's quality bar. |
| `middleware.pii_redaction` is **Python-only** (1.x) | Node + Rust backends don't apply email/token/API-key regex filters to logs. | Node/Rust logging middleware doesn't log request bodies by default, limiting blast radius. For sensitive workloads, use `backend.language=python`. | Deferred to 1.3.x. |
| `vector_store` polyglot is **NOT** in 1.x | The vector-store port + adapters are Python-only. Node / Rust projects needing RAG can't co-resident a vector store today. | Python remains the canonical backend for RAG workloads. Cross-language teams can run a Python sidecar service exposing the vector-store via HTTP. | Tracked for 2.x — `chromadb-rs` is too immature per RFC-005 §"Adapter inventory", and the JS/TS vector-store SDK landscape is too fragmented for a forge default. |

### `vector_store_*` fragments are Python-only in 1.x

This is a deliberate scope cut, not a TODO and not "coming soon". The 1.x
line ships `vector_store_*` fragments only for the Python backend.

Per [RFC-005 §"Adapter inventory"](rfcs/RFC-005-polyglot-ports.md#adapter-inventory),
the Rust client for ChromaDB (`chromadb-rs`) is assessed as immature for
production use. Pinecone, Weaviate, and Qdrant Node and Rust clients do
exist, but the supervisory pattern forge implements — embeddings →
vector write → recall on retrieval — requires three coordinated
implementations per provider × per language. That work is out of scope
for 1.x and is deferred to the 2.x line per the forge architectural
roadmap.

**Workaround for Node and Rust users:** generate the Python service
with `rag.backend=qdrant` (or your provider of choice) and deploy it as
a sidecar. Call it over HTTP from your Node or Rust services. The
Python service owns the vector-store interaction; your polyglot service
owns the rest.

## Tooling

| Issue | Impact | Workaround | Tracking |
| --- | --- | --- | --- |
| `ty` is an alpha typechecker; upgrade cadence is aggressive | An upstream ty release could regress forge's typecheck without a forge code change. | Epic X's `typecheck-ty-canary` CI job isolates ty regressions from forge regressions. `ty-upgrade.yml` opens a PR monthly — manual review + merge. | n/a (Astral-side). |
| `mutmut` PR-gate is scoped to high-consequence modules only | Full-suite mutation testing takes too long for PR feedback. Advisory nightly runs the full critical-path set. | PR-gate covers `capability_resolver`, `sync/provenance`, `sync/forge_to_project/resolver`. Nightly covers all `[tool.mutmut].paths_to_mutate`. | PR #101 landed the PR-gate; Epic U (full gate) deferred. |
| `pytest -m package_integrity` builds the wheel on every run (~30s) | Test suite time grows by ~30s if run in main pass. | Gated behind `-m "not package_integrity"` in the default `test` CI job. Runs on its own `package-integrity` CI job. | n/a (inherent cost of the check). |

---

If you hit something that isn't here, open an issue at
[github.com/cchifor/forge/issues](https://github.com/cchifor/forge/issues)
and we'll either fix it or add a row.
