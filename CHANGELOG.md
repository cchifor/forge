# Changelog

All notable changes to forge are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — targeting 1.1.0-alpha.1

> First wave of the 12-month post-1.0 roadmap (see `plans/role-expertise-you-sprightly-nova.md`). Foundation epics that unblock the rest: structured error hierarchy (D), registry freeze + symmetry audit (I), FragmentContext plumbing (E), feature_injector decomposition (A), MiddlewareSpec abstraction (K), coverage gate (S), ty pin + canary (X), release dry-run workflow (Z).

### Added — Epic Z (release dry-run rehearsal + 72h preflight)

- **`.github/workflows/release-dryrun.yml`** (`workflow_dispatch`-only) — rehearses every publish path against dry-run endpoints / offline validators: Python sdist+wheel build + `twine check`, `forge` CLI install smoke from the built wheel (`forge --version / --help / --list`), `npm publish --dry-run` for canvas-vue and canvas-svelte, `flutter pub publish --dry-run` + `flutter analyze` for forge_canvas, CHANGELOG section extraction. On green, writes a `release-dryrun/ok` check-run on the rehearsed SHA.
- **`preflight-dryrun` job in `release.yml`** — queries the GitHub Checks API for `release-dryrun/ok` on the tagged commit, fails fast unless a successful rehearsal completed within 72h. Every publish-* job now depends on this preflight, so a broken build or misconfigured registry never reaches PyPI / npm / pub.dev.
- **Escape hatch** — repo variable `SKIP_DRYRUN_GATE=true` bypasses the preflight with a CI warning. Mutations are in the repo log, so an accidental lingering bypass is visible in audit.
- **`RELEASING.md` "Pre-release dry-run protocol"** section — step-by-step protocol, per-job failure taxonomy, escape-hatch usage.

### Added — Epic X (ty pin + upstream regression canary)

- **ty pinned to exact version** (`0.0.29`) in `pyproject.toml`. The old `>=0.0.1a7` constraint let uv resolve to whatever Astral had released — handy for bug fixes, dangerous for CI stability. New ty bumps now go through `.github/workflows/ty-upgrade.yml` (scheduled monthly + `workflow_dispatch`), which runs the canary + forge typecheck before opening a PR with the lock churn.
- **`tests/fixtures/ty_canary/`** — 12 small Python files exercising the 5 enabled ty rules (`unresolved-import`, `invalid-argument-type`, `invalid-return-type`, `missing-argument`, `unknown-argument`) plus `TypedDict` and generic `Protocol` inference smoke tests. Each file has a `# expect: error[<rule>]` or `# expect: ok` header.
- **`tests/test_ty_canary.py`** — 13 tests that subprocess-invoke `ty check` against each fixture and assert the reported diagnostic rule matches the header. A divergence means ty's behaviour changed — the CI failure surfaces as "upstream ty regression" rather than "forge typing regression".
- **Split `typecheck` job in `ci.yml`** into `typecheck-forge` and `typecheck-ty-canary`. Running in parallel. A green `typecheck-ty-canary` with a failing `typecheck-forge` points at forge code; the reverse points at ty.
- **`.github/workflows/ty-upgrade.yml`** — scheduled bot. First Monday of each month (or `workflow_dispatch`) bumps ty to the latest alpha, runs canary + forge typecheck, opens a labelled PR with the bump. Humans review + merge.

### Fixed — Epic X (pre-existing ty diagnostics)

- Seven typechecker diagnostics that ty 0.0.29 surfaces on the forge codebase (the old `>=0.0.1a7` constraint was resolving to a newer ty in practice, but the diagnostics weren't being enforced — CI was running whatever uv cached). Each is suppressed with a targeted `# ty:ignore[<rule>]` comment and a rationale. Sites: `forge/cli/interactive.py:106` (BackendLanguage + plugin-sentinel union), `forge/codegen/enums.py:104, 109` (narrowed dict.get), `forge/domain/typespec.py:111` (optional-import-shim), `forge/generator.py:19, 20, 217` (Windows stdout reconfigure + provenance origin assignment). These are intentional pragmatic suppressions; a future epic tightens the relevant dataclass types to remove them.

### Fixed — Epic X (pre-existing ruff diagnostics)

- Ruff 0.15.11 (refreshed via `uv sync` during Epic X) surfaces ~37 pre-existing UP037 / UP035 diagnostics — quoted type annotations that `from __future__ import annotations` makes unnecessary, plus `typing.Callable` → `collections.abc.Callable` migrations. All auto-fixed by `ruff check --fix`; the resulting diffs are mechanical.
- Three style fixes that ruff flags but can't auto-fix: SIM108 ternary in `forge/domain/emitters.py` (ternary applied); SIM102 nested-if in `forge/feature_injector.py` (combined with `and`); UP042 `str + Enum` in `forge/domain/spec.py` (kept with a targeted `noqa` — StrEnum changes `==` semantics and the YAML loader depends on the current behaviour).
- `uv.lock` refreshed for the new ty pin + the current ruff.

### Added — Epic S (per-module coverage gates)

- **`tests/test_coverage_gates.py`** — per-module coverage floors for the critical path (`capability_resolver`, `feature_injector`, `merge`, `provenance`, both AST injectors, `updater`). Parametrized across the gate table so a CI failure names the exact module that regressed instead of just "coverage low".
- **`coverage` job in `.github/workflows/ci.yml`** — ubuntu × Python 3.13 only; runs pytest with `--cov-report=xml,json`, re-runs the per-module gate against the fresh report, uploads XML to Codecov (OIDC for the public repo, `CODECOV_TOKEN` honoured if set).
- **`docs/coverage-policy.md`** — documents the two-layer gate (project-wide `fail_under` + per-module floors), the ratchet policy, and how to add or lower a floor with RFC-002 justification.

### Changed — Epic S

- Measured baseline at the start of Epic S was 83.5% project-wide — well above the existing `fail_under = 75`. The exploration assumption of 26% was stale. Project-wide floor stays at 75 as the coarse safety net; the new per-module floors lock in the actual 80–97% critical-path coverage with a 2pp safety margin so small incidental drops don't block unrelated PRs.
- `.gitignore` now ignores `coverage.json` and `coverage.xml` so the CI-generated reports don't accidentally land on a feature branch.

### Breaking

### Breaking

- **Epic D — Error hierarchy.** `GeneratorError` is now an alias for the new `ForgeError` base class; six typed subclasses (`OptionsError`, `FragmentError`, `InjectionError`, `MergeError`, `ProvenanceError`, `PluginError`) replace the single flat error type. `except GeneratorError:` keeps catching every forge failure so call sites outside the project are unaffected. Assertions that compare `type(err).__name__ == "GeneratorError"` or rely on exact-type equality break — migrate to `isinstance(err, ForgeError)` or the specific subclass. No codemod; the search-and-replace is too coupled to the local test style to mechanise safely. See `UPGRADING.md`.

### Added

- **`forge.errors.ForgeError`** with fields `message`, `code`, `hint`, `context` and an `as_envelope()` helper the CLI uses for the `--json` error envelope.
- **Machine-readable error codes** (`OPTIONS_UNKNOWN_PATH`, `FRAGMENT_DIR_MISSING`, `INJECTION_ANCHOR_NOT_FOUND`, `MERGE_CONFLICT`, `PROVENANCE_MANIFEST_MISSING`, `PLUGIN_COLLISION`, etc.) exported from `forge.errors` so plugins + tests can branch on `err.code` without regex-matching message strings.
- **Subclass-aware exit codes** in the CLI: injection failures exit 3, merge 4, provenance 5, plugin 6; options/fragment/generator stay at 2. 0 remains success.
- **`--json` envelope extension.** The error envelope now includes `code`, `hint` (when present), and `context` (when non-empty). The legacy `{"error": "<message>"}` shape is preserved for config-parse errors that surface as raw `ValueError` / `KeyError`.
- **`tests/test_errors.py`** — 18 new tests covering the hierarchy, alias identity, envelope serialisation, and exit-code mapping.

### Changed

- Every `raise GeneratorError(...)` in the core control plane (`capability_resolver`, `feature_injector`, `injectors/python_ast`, `injectors/ts_ast`, `updater`, `api`) now raises the most specific subclass with a named `code`. Generator-orchestration raises in `forge/generator.py` continue to raise via the `GeneratorError` alias (= `ForgeError`) — they'll migrate to a future `GenerationError` subclass in a follow-up.
- Bare `ValueError` / `FileNotFoundError` raises in the AST injectors are promoted to `InjectionError` with codes (`INJECTION_TARGET_MISSING`, `INJECTION_ANCHOR_NOT_FOUND`, `INJECTION_ANCHOR_AMBIGUOUS`, `INJECTION_MARKER_MISSING`) so CLI + tests see a uniform error surface.

---

## [1.0.0] - 2026-04-20

> **forge 1.0 — stable.** First stable release of the clean-break 1.0 series. Every capability shipped across the five alphas (a1–a5) + beta (b1) + release candidate (rc1) is now under the normal SemVer contract: breaking changes require a major bump, minor bumps add features, patches fix bugs. See `RELEASING.md` for the post-1.0 deprecation policy.

### Summary of the 1.0 series

- **Schema-first core** — single YAML or TypeSpec source drives every language's domain models + OpenAPI + enums.
- **AST-aware injection** — LibCST for Python, regex (or ts-morph subprocess) for TypeScript, with three-zone (generated / user / merge) semantics and `.forge-merge` conflict sidecars.
- **Provenance manifest** — `forge.toml` records SHA-256 + origin per file; `forge --update` classifies user-modified vs unchanged vs fragment-modified.
- **Ports-and-adapters** — vector store (6 providers), LLM (4 providers), queue (2 providers), object store (2 providers) — swappable via env, no regeneration.
- **Plugin SDK** — third parties ship `forge-plugin-*` packages that add options, fragments, backends, frontends, commands, or emitters via entry points.
- **Canvas packages** — `@forge/canvas-vue`, `@forge/canvas-svelte`, `forge_canvas` publish 5 canvas components + AG-UI streaming client + runtime prop lint.
- **Real MCP integration** — stdio JSON-RPC subprocess client, tool discovery + invoke endpoints, HMAC-signed approval tokens, append-only audit log.
- **30 options × 51 fragments × 662 tests** — full coverage across the registry.

### Version

- `pyproject.toml` version `1.0.0`.
- Canvas packages held at `1.0.0-alpha.5` until the first post-1.0 bump (their own lifecycle; see RFC-003).

### Post-1.0 policy

- Breaking changes require a major bump and a deprecation cycle (one minor release warning → removal in the next).
- Dropping a Python / Node / Rust / Flutter version is breaking; backport fixes to the last minor that supported it for one year.
- RFC-002's codemod contract remains in force — every breaking change ships with a `forge migrate-<name>` codemod or a documented manual step.

---

## [1.0.0rc1] - 2026-04-20

> First release candidate. Feature-frozen since 1.0.0b1 with no new changes — this RC exists to exercise the full release-rehearsal pipeline (RFC-004) against every registry (TestPyPI, npm `alpha` tag, pub.dev `--dry-run`) before the v1.0.0 tag push. Promoted to stable 1.0.0 if the rehearsal completes without rollbacks.

### Changed

- `pyproject.toml` version pinned to the RC identifier (no `.dev0` suffix) so `uv build` emits installable `forge-1.0.0rc1` artefacts for the rehearsal.

### Tests

662 passing, 1 skipped (no change from b1).

---

## [1.0.0b1] - 2026-04-20

> First beta — **feature freeze**. No new features accepted from this point; only bug fixes, doc polish, and release-rehearsal hardening.

### Added

- **Expanded CI matrix** (`.github/workflows/e2e.yml`): forge's own tests run on Python 3.11 / 3.12 / 3.13; generated-project suites (python-vue, node-svelte, rust-none, multi-backend-keycloak) run on every template-touching PR; canvas-packages build + typecheck for `@forge/canvas-vue`, `@forge/canvas-svelte`, `forge_canvas` on every commit.
- **`docs/ARCHITECTURE.md`** — rewritten to document the post-1.0 design: registry triad, generation pipeline, injector backends, provenance + merge blocks, codegen layer, canvas packages, plugin architecture, testing surface.
- **`docs/GETTING_STARTED.md`** — 10-minute tour from install to a running project, including headless YAML invocation, incremental-change verbs, codemods, and agent-friendly stdin/json patterns.
- **`docs/rfcs/RFC-004-release-rehearsal.md`** — pre-1.0 rehearsal policy, dry-run mechanics, lockstep version check, rollback asymmetries per registry.
- **`release.yml` dry-run trigger** — `workflow_dispatch` inputs `dry_run` (default true) and `target` so maintainers can rehearse the full PyPI + npm + pub.dev pipeline without tagging.

### Changed

- **README visuals** — placeholder image slots removed; replaced with a real Mermaid architecture diagram + links to `ARCHITECTURE.md` and `GETTING_STARTED.md`.

### Tests

662 passing, 1 skipped (no change from a5 — feature freeze).

---

## [1.0.0a5] - 2026-04-20

> Fifth alpha — **feature-complete**. Lifts the remaining 4 canvas components (CodeViewer, DataTable, DynamicForm, WorkflowDiagram) into the published `@forge/canvas-vue`, `@forge/canvas-svelte`, and `forge_canvas` packages. Ships beta-gate testing infrastructure: 4 golden-snapshot presets (python/node/rust/multi-backend), OpenAPI contract tests for the domain DSL, and mutation testing scoped to the fragment-injector critical path.

### Added

- **4 canvas components extracted** across all three frameworks (A5-1 through A5-4):
  - `CodeViewer` — syntax-highlighted code with filename header + line numbers. highlight.js (web) / flutter_highlight (mobile).
  - `DataTable` — sortable columns + client-side pagination.
  - `DynamicForm` — JSON-schema-driven form dispatching by field type (text/number/password/email/select/checkbox/textarea).
  - `WorkflowDiagram` — DAG layout with topological-depth row assignment, status badges (pending/running/completed/error/skipped), straight-line edge routing.
- **Golden-snapshot presets** extended from 1 to 4: `python_minimal`, `node_minimal`, `rust_minimal`, `multi_backend`. Regenerate with `UPDATE_GOLDEN=1`.
- **OpenAPI contract tests** (`tests/test_openapi_contract.py`): every entity's emitted OpenAPI has typed properties, correct required-vs-optional split, format declarations for uuid/date-time, `$ref` for enums. 13 tests.
- **Mutation testing configuration** — `[tool.mutmut]` in pyproject.toml scoped to `feature_injector`, `merge`, `provenance`, `injectors/*`, `updater`. New `docs/mutation-testing.md` documents the kill-rate baseline + the "run locally on breaking-change PRs" policy.
- **Vue / Svelte dependencies** — `highlight.js@^11.10.0` for CodeViewer.
- **Dart dependencies** — `flutter_highlight@^0.7.0` for CodeViewer, `http@^1.2.0` for MCP client.

### Changed

- Published packages bumped to `1.0.0-alpha.5`. `@forge/canvas-vue` + `@forge/canvas-svelte` + `forge_canvas` now export all 5 canvas components.

### Tests

662 passing, 1 skipped (up from 646).

---

## [1.0.0a4] - 2026-04-20

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
