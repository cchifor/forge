# Changelog

All notable changes to forge are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
