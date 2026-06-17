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
| Flutter + chat e2e (`test_flutter_full_analyzes`) is `xfail` on analyzer null-safety debt | Canvas is **vendored** into `packages/forge_canvas` + `packages/forge_canvas_core`, referenced via pubspec `path:` — `flutter pub get` resolves self-contained, no pub.dev publish needed. With a modern Dart (`channel: stable`; SDK env `>=3.8.0 <4.0.0`), `flutter analyze` then reports ~500 `unchecked_use_of_nullable_value` errors across ~46 files (templates access nullable API-response fields like `response.title` / `data['x']` without `?.`/`!`). The old 3.24.x pin (Dart 3.5.4) never ran analyze far enough to flag these. | The vendored canvas resolves out of the box; the analyzer findings are real template null-safety bugs. | A template null-safety sweep across the flutter-frontend-template `lib/src/**` widgets/controllers (add `?.`/`!`/null-guards on API-model access), then drop the `xfail`. |

## Platform

| Issue | Impact | Workaround | Tracking |
| --- | --- | --- | --- |
| Rust cold-build times in CI exceed 5 min on first run | Nightly e2e has a 40-min budget; a cold cargo cache can push close. | `Swatinem/rust-cache@v2` warms across runs. The first run after a cache invalidation is painful but recovers. | Fresh-runner perf is out of our control. |
| Flutter SDK first-run install adds ~90s to CI | Adds a constant overhead to every job that needs Flutter. | `subosito/flutter-action@v2` with `cache: true` reduces this to ~5s on subsequent runs. | n/a. |
| macOS not in nightly e2e | Rust/cargo behaviour differences on macOS won't be caught until a user hits them. | Run `make test` locally on macOS if you contribute macOS-specific code. | Epic W adds a macOS leg — deferred to Q4. |

## Polyglot (Node/Rust)

| Issue | Impact | Workaround | Tracking |
| --- | --- | --- | --- |
| Node ships 24 and Rust 23 of the 78 fragments (~30%); Python covers all 78 | Node and Rust lack the agent/RAG/LLM/MCP/admin stack that Python has. | Python remains the canonical "rich" backend. Node/Rust are for pure-service workloads. | Epic J backfills the ops fragments in 1.1.x. Full AI/RAG parity is design-only (RFC-Q) pending polyglot port investment. |
| `llm.provider` ships **only OpenAI** on Node + Rust; Anthropic / Ollama / Bedrock are Python-only (1.x) | Picking `llm.provider=anthropic` / `ollama` / `bedrock` on a project with no Python backend is **rejected at generation time** with a clear error. (Previously it silently resolved the abstract `llm_port` with no adapter — a service that started, then failed at the first LLM call.) The same config-time rejection applies to `rag.backend` (the vector-store stack is Python-only) and `platform.mcp` (the MCP server is Python-only). | Use `llm.provider=openai` on Node / Rust; install Anthropic / Ollama / Bedrock as plugins (Featured Plugin tier — `forge-plugin-anthropic-node`, etc.) once those exist; or add a `backend.language=python` backend for non-OpenAI providers / RAG / MCP. | Pillar D.2 — full polyglot provider matrix deferred to 2.x. The plan is honestly scoped: OpenAI's TS (`@ai-sdk/openai`) + Rust (`async-openai`) SDK ecosystems are mature enough for in-tree adapters; the others aren't, and the Python-first SDK ecosystem (anthropic-python, ollama-python, aioboto3) doesn't have peer cross-language libraries that meet forge's quality bar. |
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
| `mutmut` PR-gate can report "0 evaluable mutants (all timeouts)" | The PR-gate runner is `pytest -x` with no marker filter, so it inherits the default `addopts = --cov` **and collects the full tree (e2e scaffolds + golden full-generation)**. A *surviving* mutant runs that whole slow suite to completion; under CI load several survivors exceed the 15-min per-shard cap, so they're all recorded as `timeout` → `total_evaluable == 0` → the gate fails with no kill-rate signal, even absent a real regression. | A faithful fix is a fast runner (`--no-cov` + `-m "not e2e and not golden_snapshot and not package_integrity and not fuzz and not plugin_e2e and not bench"`), but that changes which tests count toward the floor and must be re-baselined; or precompute `.coverage` and pass `--use-coverage` in PR mode. Re-run is the current stop-gap. | Pre-existing (PR #101 era); orthogonal to product changes. Make the PR-mode runner fast + deterministic and re-measure `pr_gate_modules` floors. |
| `pytest -m package_integrity` builds the wheel on every run (~30s) | Test suite time grows by ~30s if run in main pass. | Gated behind `-m "not package_integrity"` in the default `test` CI job. Runs on its own `package-integrity` CI job. | n/a (inherent cost of the check). |

---

If you hit something that isn't here, open an issue at
[github.com/cchifor/forge/issues](https://github.com/cchifor/forge/issues)
and we'll either fix it or add a row.
