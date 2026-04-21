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
| Full-feature golden preset (`platform.admin` + `agent.llm` + `rag.reranker` enabled) fails generation with `Injection target not found: src/app/core/container.py` | The most-ambitious combination of options doesn't scaffold cleanly on `main`. Pairs of options individually work. | Use a subset (see `tests/test_golden_snapshots.py::PRESETS['full_feature']` for a curated large preset that does generate). | Epic F (provenance-driven uninstall) + cross-fragment dep tightening tracked for 1.1.0-beta. |
| Svelte + chat path's `@ag-ui/client` e2e test (`svelte_chat_on_typechecks`) is skipped | Svelte chat flow isn't exercised in nightly CI. | Generate + test manually; the Vue + Flutter chat paths are covered. | Tracked upstream — `@ag-ui/client` type drift. Re-enable when 1.0 stable. |

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

## Tooling

| Issue | Impact | Workaround | Tracking |
| --- | --- | --- | --- |
| `ty` is an alpha typechecker; upgrade cadence is aggressive | An upstream ty release could regress forge's typecheck without a forge code change. | Epic X's `typecheck-ty-canary` CI job isolates ty regressions from forge regressions. `ty-upgrade.yml` opens a PR monthly — manual review + merge. | n/a (Astral-side). |
| `mutmut` isn't in CI — kill-rate enforcement is manual | Mutation-testing regressions can slip. | Run `uvx mutmut run` locally on breaking-change PRs. | Epic U adds a scheduled mutmut workflow (deferred). |
| `pytest -m package_integrity` builds the wheel on every run (~30s) | Test suite time grows by ~30s if run in main pass. | Gated behind `-m "not package_integrity"` in the default `test` CI job. Runs on its own `package-integrity` CI job. | n/a (inherent cost of the check). |

---

If you hit something that isn't here, open an issue at
[github.com/cchifor/forge/issues](https://github.com/cchifor/forge/issues)
and we'll either fix it or add a row.
