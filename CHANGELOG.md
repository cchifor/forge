# Changelog

All notable changes to forge are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0a4] - unreleased

> Fourth alpha. Closes the plugin SDK story (command dispatcher wired, frontends pluggable, fragments shippable from plugin packages), adds runtime canvas-prop lint across Vue / Svelte / Flutter, ships the MCP approval-token + audit-log middleware, and lifts the first canvas component (`Report`) into the published packages as the extraction reference.

### Breaking

- **`/mcp/invoke` now requires a valid `approval_token` when the tool's mode is not `auto`**. Frontend ApprovalDialog code must first POST `/mcp/approval/mint` and include the returned token on the next invoke. Tokens are HMAC-signed with `MCP_APPROVAL_SIGNING_KEY` and bound to (server, tool, input-hash). Generated projects without the env var fall back to the service name — logged as a warning; not safe for production.

### Added

- **Plugin command dispatcher** (A4-2): `ForgeAPI.add_command(name, handler)` now registers into `COMMAND_REGISTRY`; `_build_parser` walks it and injects `--<name>` flags; main.py dispatches to the handler with the full argparse Namespace. Collisions with core flags are silently skipped so a malformed plugin can't break the CLI.
- **Plugin fragment path resolver** (A4-3): `FragmentImplSpec.fragment_dir` now accepts absolute paths — plugins can ship fragments from their own package tree (`Path(__file__).parent / "fragments" / ...`) instead of being restricted to forge's `_fragments/` directory.
- **Plugin-defined frontends** (A4-4): `ForgeAPI.add_frontend(value, FrontendSpec)` + `_PluginFramework` sentinel + `resolve_frontend_framework`, mirroring the 1.0.0a2 backend-plugin story. Plugins can ship Solid, Qwik, Remix, etc.
- **Canvas runtime lint** (A4-5): `lintProps` / `warnOnLintIssues` in every canvas package. `CanvasRegistry.lintAndResolve(name, props)` validates props against the component's JSON Schema in dev mode and emits `console.warn` / `debugPrint` on drift. Tree-shaken in prod.
- **MCP audit log + approval tokens** (A4-6): `app/mcp/audit.py` in generated projects — HMAC-SHA256-signed approval tokens bound to (server, tool, input-hash), append-only `audit.jsonl` recording every invocation with user_id + decision + error. New `POST /mcp/approval/mint` endpoint for frontend token exchange.
- **Canvas Report component extracted** (A4-7): `Report.vue`, `Report.svelte`, `report.dart` now live in the published `@forge/canvas-vue`, `@forge/canvas-svelte`, and `forge_canvas` packages. The Vue + Svelte versions ship with `marked` + `DOMPurify` as runtime deps; Flutter uses `flutter_markdown`. Packages bumped to `1.0.0-alpha.4`.

### Changed

- `api.py` adds `add_frontend`; `config.py` adds `FrontendSpec`, `PLUGIN_FRAMEWORKS`, `FRONTEND_SPECS`, `_PluginFramework`, `register_frontend_framework`, `resolve_frontend_framework`.
- `feature_injector._resolve_fragment_dir` extracts the path-resolution policy so plan.py and the injector share it.
- `plugins.py` adds `COMMAND_REGISTRY`; `reset_for_tests` clears it.
- MCP router: `/mcp/invoke` now verifies approval tokens, writes audit entries, and returns 401 on token failure.

### Tests

646 passing, 1 skipped (up from 618). New suites: `test_plugin_commands.py` (6), `test_plugin_fragment_paths.py` (4), `test_plugin_frontend.py` (8), `test_mcp_audit.py` (10).

---

## [1.0.0a3] - 2026-04-20

> Third alpha. Three-way merge runtime (`merge` zone is now semantically real), real MCP subprocess spawning + tool discovery, Svelte and Flutter MCP UI parity, and the TypeSpec compiler bridge for domain entities.

### Breaking

- **`merge` zone now emits `.forge-merge` sidecars on conflict.** Previously aliased to `generated`. If you had `zone: merge` in a fragment's inject.yaml, a user edit + fragment change during `forge --update` now produces a sidecar instead of silently overwriting. Pre-1.0.0a3 projects that don't have `[forge.merge_blocks]` in their `forge.toml` fall back to `generated` behavior on first apply, then record a baseline going forward.
- **MCP endpoints return real data.** `/mcp/tools` spawns configured servers and aggregates their advertised tools; `/mcp/invoke` proxies real tool calls. The 1.0.0a1 placeholder response is gone. Projects without `mcp.config.json` see an empty tool list.

### Added

- `forge/merge.py` — pure three-way-decision helpers (`three_way_decide`, `write_sidecar`, `sha256_of_text`, `MergeBlockCollector`). No I/O in the decision function; callers handle disk writes.
- `[forge.merge_blocks]` table in `forge.toml` — per-block SHA baseline keyed by `{rel_path}::{feature_key}:{marker}`. Enables true three-way compare between baseline / current / new.
- Python MCP stdio JSON-RPC client (`app/mcp/client.py` in generated projects): `McpStdioClient` speaks newline-delimited JSON-RPC 2.0, completes the initialize handshake, and handles `tools/list` + `tools/call`. `McpRegistry` manages per-server subprocess lifecycle; app shutdown hook terminates children cleanly.
- **Svelte MCP UI** (`mcp_ui_svelte` fragment): `ToolRegistry.svelte` with runes-based fetch, `ApprovalDialog.svelte` with `$props()` rune, `use-mcp-tools.svelte.ts` client-side hook with session-approval cache.
- **Flutter MCP UI** (`mcp_ui_flutter` fragment): `tool_registry.dart` `FutureBuilder`-backed list, `approval_dialog.dart` Material dialog returning `ApprovalResult`, `mcp_client.dart` ties them together with session-approval cache.
- `forge/domain/typespec.py` — TypeSpec compiler bridge via `npx tsp compile`. `typespec_available()` for toolchain detection; `compile_tsp()` + `extract_entities()` produce YAML-DSL-compatible entity dicts from `.tsp` sources so the existing emitters (Pydantic / Zod / sqlx / OpenAPI) consume either format.

### Changed

- `_apply_zoned_injection` threads `project_root` + `collector` through so `merge` zone can look up baselines and record new ones.
- `generator._write_forge_toml` and `updater._restamp_forge_toml` now emit `[forge.merge_blocks]` alongside `[forge.provenance]`.
- MCP fragment (`mcp_server/python`) gains `client.py`, a shutdown hook injection, and real `/mcp/tools` + `/mcp/invoke` implementations.
- Fragment registry grows from 47 → 51 entries (`mcp_ui_svelte`, `mcp_ui_flutter`).

### Tests

634 passing, 1 skipped (up from 594). New suites: `test_three_way_merge.py` (12), `test_mcp_client.py` (4), `test_typespec_bridge.py` (8).

---

## [1.0.0a2] - 2026-04-20

> Second alpha. Completes the ports-and-adapters refactor (6 RAG adapters, 4 LLM providers, queue + object-store ports) and adds plugin-extensible `BackendLanguage`, the ts-morph AST sidecar, Node base-template anchors for reliability auto-wire, and retires the hand-rolled Flutter SSE client in favor of the `forge_canvas` package.

### Breaking

- **`rag.backend` now enables the port+adapter pair** instead of the legacy `rag_<name>` fragments. Generated projects get `vector_store_port` + `vector_store_<provider>` in their plan. Runtime-swappable via env. Migration for pre-1.0.0a2 projects: `forge --migrate --migrate-only adapters`.

### Added

- **Full RAG port+adapter catalogue:** `vector_store_chroma`, `vector_store_pinecone`, `vector_store_milvus`, `vector_store_weaviate`, `vector_store_postgres` join the 1.0.0a1 Qdrant reference.
- **LLM provider port** (`llm_port`) + four adapters: `llm_openai`, `llm_anthropic`, `llm_ollama`, `llm_bedrock`. New `llm.provider` option.
- **Queue port** (`queue_port`) with Redis-list + AWS SQS adapters. New `queue.backend` option.
- **Object-store port** (`object_store_port`) with S3 (+ S3-compatible) and local-filesystem adapters. New `object_store.backend` option.
- **Plugin-extensible `BackendLanguage`** — plugins can add new backend languages (e.g. Go, Java) via `api.add_backend("go", spec)`. Built on a `_PluginLanguage` sentinel + `resolve_backend_language(value)` helper.
- **ts-morph subprocess sidecar** (`forge/injectors/ts-morph-helper.mjs` + `ts_morph_sidecar.py`). Opt-in via `FORGE_TS_AST=1`; falls back to the regex injector when ts-morph or Node isn't available.
- **Node base-template markers** — `FORGE:PRISMA_CLIENT_INIT` anchors the reliability_connection_pool auto-wire so `reliability.connection_pool=true` produces a working generated project without hand-edits.
- **Flutter hand-rolled SSE deprecation notice** + migration target (`forge_canvas` package). `forge --migrate --migrate-only ui-protocol` renames the legacy file to `.legacy`.

### Changed

- `rag.backend` enum's `enables` map now points at vector_store_* fragments; legacy `rag_<provider>` fragments remain in the registry for backward-compat but aren't selected by the Option.
- Fragment registry grows from 35 → 47 entries (ports + adapters + LLM/queue/object-store).
- Option registry grows from 27 → 30 (`llm.provider`, `queue.backend`, `object_store.backend`).

### Tests

594 passing, 1 skipped (up from 571). New test files: `test_plugin_backend_language.py`, `test_ts_morph_sidecar.py`.

---

## [1.0.0a1] - 2026-04-20

> First alpha of the **1.0 clean-break** series. See `RELEASING.md` for the release process and `UPGRADING.md` for migration guidance.

### Breaking

- **CLI entry point moved** — `forge.cli:main` → `forge.cli.main:main`. The `forge` console script is unchanged; only direct Python imports of private helpers need to update.
- **`forge.toml` gains `[forge.provenance]`** — per-file origin + SHA-256 + fragment version. Old projects receive a one-time backfill on first `forge --update` in 1.0.

### Added

**Phase 0 — foundations:**
- `forge/cli/` package (decomposed from the 1,361-line cli.py) with command-object dispatch.
- `forge/provenance.py` — CRLF-normalized SHA-256 + classify/record primitives; written to `[forge.provenance]` on every generate, consumed by `forge --update`.
- `forge/api.py` + `forge/plugins.py` — entry-point plugin host (group `forge.plugins`), `ForgeAPI` facade, `forge plugins list` command.
- `forge --plan` (ordered fragment plan + mutation tree, ASCII-safe on Windows) and `forge --dry-run`.

**Phase 1 — schema-first core:**
- `forge/codegen/ui_protocol.py` emits TS + Dart + Pydantic from 7 JSON schemas under `forge/templates/_shared/ui-protocol/`.
- `forge/codegen/canvas_contract.py` + 5 canvas component props schemas; `forge --canvas lint` validates payloads.
- `forge/domain/` — YAML entity DSL with Pydantic / Zod / sqlx / OpenAPI emitters (TypeSpec adoption: 1.0.0a2).
- `forge/codegen/enums.py` — Python / TS / Zod / Rust / Dart emitters for shared enums.
- `forge/codegen/pipeline.py` — integration point: runs every emitter during `forge new` so each project ships with regenerated types per-frontend and per-backend.

**Phase 2 — extensibility:**
- `forge/injectors/python_ast.py` — LibCST-anchored Python injection that survives Ruff / Black reformatting; falls back to text markers on syntax errors.
- `forge/injectors/ts_ast.py` — regex-anchor + sentinel injector for `.ts/.tsx/.js/.jsx/.mjs`; dispatched automatically by extension.
- Three-zone merge — `generated`, `user`, and `merge` semantics on every `inject.yaml` entry.
- Reference port+adapter pair: `vector_store_port` + `vector_store_qdrant` (rest of RAG refactor: 1.0.0a2).
- `docs/architecture-decisions/ADR-001-pragmatic-hexagonal.md`, `ADR-002-ports-and-adapters.md`.
- `docs/plugin-development.md` + `examples/forge-plugin-example/` reference plugin.

**Phase 3 — agentic UI:**
- Published package scaffolds: `@forge/canvas-vue`, `@forge/canvas-svelte`, `forge_canvas` (pub.dev), each with Vite library build / tsconfig / svelte.config / analysis_options so they can actually `npm publish` / `flutter pub publish`.
- Dart `AgUiClient` — exponential-backoff reconnect + `Last-Event-ID` resume + SSE chunk parsing.
- `ForgeTheme` — shadcn-flavored Material 3 matching the web design language.
- MCP scaffolds: `mcp_server` (FastAPI router for `/mcp/tools` + `/mcp/invoke`) + `mcp_ui` (Vue ToolRegistry + ApprovalDialog).
- `docs/mcp.md` + `mcp.config.example.json` + JSON Schema at `forge/templates/_shared/mcp/mcp_config_schema.json`.

**Phase 4 — production polish:**
- Reliability fragments across **Python / Node / Rust**: `reliability_connection_pool`, `reliability_circuit_breaker`, with auto-wire injections.
- `observability_otel` fragment across **Python / Node / Rust** (OTLP exporter + FastAPI / `@opentelemetry/sdk-node` / `tracing-opentelemetry` bridges).
- Security fragments: `security_csp` (strict CSP nginx include), `security_sbom` (CycloneDX workflow).
- `forge/common_files.py` drops `.editorconfig`, `.gitignore`, `.pre-commit-config.yaml`, and per-backend CI workflows into every project.
- `forge/doctor.py` — toolchain / Docker / port / `forge.toml` integrity diagnostics via `forge --doctor [--json]`.
- New CLI verbs: `forge --new-entity-name`, `--add-backend-language`, `--preview`, `--migrate [--migrate-only] [--migrate-skip]`.
- `forge/migrations/` — three codemods (`migrate-ui-protocol`, `migrate-entities`, `migrate-adapters`) + umbrella runner.
- Golden snapshot test suite (`UPDATE_GOLDEN=1` regenerates).
- `.github/workflows/release.yml` — coordinated PyPI + npm + pub.dev publish on tag push (TestPyPI for pre-releases, PyPI for stable).

### Changed

- `forge/cli.py` (1,361 lines) decomposed into `forge/cli/` package.
- `capability_resolver.resolve()` returns a richer plan consumed by `forge --plan` and `forge --dry-run`.
- `updater.update_project()` classifies each tracked file as unchanged / user-modified / missing using the provenance manifest.
- Fragment registry grows from 27 → 35 entries (vector-store ports, reliability / observability / security, MCP).
- Option registry grows from 22 → 27 with `reliability.connection_pool`, `reliability.circuit_breaker`, `observability.otel`, `security.csp`, `security.sbom`, `platform.mcp`.

### Tests

571 passing, 1 skipped (up from 367). 13 new test files covering provenance, plugins, --plan/--dry-run, codegen pipeline, canvas contract, domain DSL, enum codegen, UI-protocol codegen, Python + TS AST injection, three-zone merge, doctor, migrations, new CLI verbs, common files, golden snapshots, and end-to-end generation with reliability + observability options enabled.

---

## [Unreleased — 0.x maintenance]

### Added — Svelte + Flutter frontend parity

- **Copier configuration parity**: Svelte gains `include_openapi`, `default_color_scheme`, `app_title`, `api_proxy_target`, and hidden multi-backend vars (`backend_features`, `proxy_targets`, `vite_proxy_config`). Flutter gains `default_color_scheme`, `app_title`, and `backend_features`. `forge.variable_mapper.svelte_context` / `flutter_context` extended to emit them.
- **Multi-backend awareness in generated frontends**: Svelte `_build/post_generate.py` patches per-feature `api/{name}.ts` to call `/api/{backend}/v1/...` and injects `vite_proxy_config` into `vite.config.ts`. Flutter `_tasks/post_generate.py` patches generated `*_repository.dart` HTTP paths and writes `lib/src/core/config/backend_routes.dart`.
- **Svelte AG-UI chat core** (`apps/svelte-frontend-template/template/src/lib/features/chat/`): full port of the Vue `ai_chat` module — `agent-client.svelte.ts` wrapping `@ag-ui/client`, streaming text deltas, tool-call lifecycle, HITL prompts, JSON-Patch state reducer, model selector, approval mode toggle, soft-imported auth so the chat compiles in `include_auth=false` projects too. New deps: `@ag-ui/client`, `@ag-ui/core`, `@modelcontextprotocol/ext-apps`, `fast-json-patch`, `marked`, `dompurify`.
- **Flutter Dart-native AG-UI chat core** (`apps/flutter-frontend-template/{{project_slug}}/lib/src/features/chat/`): pure Dart implementation of the AG-UI protocol — `AgUiClient` consuming Dio SSE streams, sealed `AgUiEvent` union, pure `reduce()` function applying RFC 6902 JSON Patch via `json_patch`, Riverpod `ChatNotifier` + selectors, widgets for chat panel / message bubble / tool-call chip / user-prompt card / agent status bar. New deps: `flutter_markdown`, `markdown`, `json_patch`, `shimmer`. Reducer covered by a 12-case unit test.
- **Workspace pane parity** (both frameworks): `WorkspacePane` + registry pattern, `FileExplorer`, `CredentialForm`, `ApprovalReview`, `UserPromptReview`, `FallbackActivity`, plus `AgUiEngine` and `McpExtEngine`. The Flutter MCP engine renders activities natively (no iframe sandbox — explicit deferral).
- **Canvas pane parity** (both frameworks): `CanvasPane` + registry, `DynamicForm`, `DataTable`, `Report` (markdown), `CodeViewer`, `WorkflowDiagram` (minimum-viable diagram), `Fallback`.

### Changed

- Svelte chat state model rewritten from a 1.5s setTimeout simulation to the AG-UI agent client (`chat.svelte.ts` exposes the same `getChatStore()` surface, but messages now stream from a real agent endpoint).
- Flutter `ChatMessage` freezed model lost the `timestamp` field (AG-UI messages don't carry one) and gained `isStreaming` semantics; existing chat_message_test updated.
- Generated READMEs gain a "Chat & agentic UI" section with usage and registry-extension examples.

### Added — Static analysis & CI hardening (prior)

- `ruff` + `ty` strict-ish config, `.pre-commit-config.yaml`, `.github/workflows/ci.yml` matrix (Linux + Windows × Python 3.11/3.12/3.13). Coverage floor raised to 75%.
- **`GeneratorError`** propagates clean error messages through `--json` (single-line envelope, exit 2) and stderr (`Generation failed: ...`, exit 2). `_run_backend_cmd(..., required=True)` raises on failure; `_git_init` checks every step.
- **End-to-end harness** (`tests/e2e/test_full_generation.py`): scaffolds python+vue, node+svelte, rust+none, and the multi-backend python+node+rust+vue+keycloak case, then runs the generated scaffold's native test suite. Marked `@pytest.mark.e2e`; nightly workflow at `.github/workflows/e2e.yml`.
- **`BACKEND_REGISTRY`** in `forge/config.py` drives language dispatch (CLI prompts, generator, variable mapper). Adding a 4th backend is now a one-day task — see [docs/adding-a-backend.md](docs/adding-a-backend.md).
- **`forge.toml`** stamped into every generated project (forge version + per-language template paths) so projects can be re-rendered with `copier update`.
- **Keycloak realm validation**: `render_keycloak_realm` parses the rendered JSON and asserts essential top-level keys before writing. Jinja typos fail generation immediately rather than at Keycloak boot.
- **`--verbose`** flag overrides `--quiet` for full Copier + subprocess output (works in JSON mode too — diagnostic output goes to stderr).
- **`forge --completion bash|zsh|fish`** prints a shell completion script.
- **Documentation**: `docs/architecture.md` (Mermaid diagram), `docs/adding-a-backend.md`, `CONTRIBUTING.md`, this changelog.

### Changed

- `ProjectConfig.validate` split into `_validate_backend_uniqueness`, `_validate_features_against_reserved`, `_validate_ports`, `_validate_keycloak_ports`. Behavior preserved.
- Interactive prompts unified — every backend now prompts for its language version (was previously skipped on the second-and-later backends).
- `backend_context` / `node_backend_context` / `rust_backend_context` collapsed to one function driven by `BACKEND_REGISTRY`. The legacy names remain as aliases.
- `_build_config` (105 lines) split into `_build_backends_from_cfg`, `_build_frontend_from_cfg`, and a slim orchestrator.

### Fixed

- `_git_init` previously ran three `subprocess.run` calls without `check=True`; a failed commit produced a "successful" generation with no commit. Each step is now checked.
- `_generate_frontend` / `render_frontend_dockerfile` no longer assume `config.frontend` is non-None — both now raise `GeneratorError` if called without a frontend.
- `BackendConfig` import was missing at module level in `forge/generator.py`; types now resolve under `ty check`.
- Stale tests in `tests/test_generator.py` (expected `<root>/test_app-e2e`) and `tests/test_e2e_templates.py` (expected old test descriptors) updated to match current template output.

## [0.1.0] - Initial release

- CLI scaffolds full-stack projects via Copier + uv.
- Backends: Python (FastAPI), Node.js (Fastify), Rust (Axum). Multi-backend per project.
- Frontends: Vue 3, Svelte 5, Flutter web.
- Optional Keycloak + Gatekeeper auth with multi-tenant isolation.
- Headless mode via `--config`, `--yes`, `--json` for CI and AI-agent integration.
- Auto-generated Playwright e2e suite per project.
