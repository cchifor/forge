# ADR-010: Composable three-layer component model

- Status: Accepted
- Author: forge team
- Date: 2026-06-02
- Scope: `forge/components/`, `forge/codegen/{canvas_contract,ui_protocol,openapi_binding}.py`,
  `forge/feature_manifest.py`, `forge/capability_resolver.py`, `forge/cli/commands/components.py`,
  `forge/features/{stat_card,console_template,chatfirst_template}/`
- Related: 2026-06-02 layered-component-model plan; [[ADR-006]] (provenance),
  [[ADR-007]] (separate frontend templates), [[ADR-009]] (component_layer ⊥ ParityTier),
  RFC-005/006 (ports), RFC-011 (frontend client survey)

## Context

Forge generated projects from a flat **Option → Fragment** model: there was no
first-class notion of a *component* with a dependency graph, no *template* as a
composable app blueprint, and no *data contract* decoupling a UI component from
the backend it reads. We needed a model where Layer-1 (basic), Layer-2
(composed), and Layer-3 (template) artifacts are graph nodes that can be
generated and idempotently re-generated at any layer, reaching backend data only
through a contract — and where the same contract works greenfield (Forge emits
the backend slice) or brownfield (bind to an existing OpenAPI backend).

The overriding constraint: **extend the machinery Forge already ships; do not
build a parallel generator.**

## Decision

1. **A component is a feature.** One `feature.toml` = one artifact = one graph
   node (identity = `name`). A component sets `[feature].layer = 1|2|3` and an
   optional `[feature.component]` table (`contract`, `children` name→version-spec,
   `aggregates`). All fields are additive; existing manifests parse unchanged.

2. **Two graphs that compose.** A new `COMPONENT_REGISTRY` + `resolve_components`
   own the component tier — layering enforcement (a dependency may only point at
   the same or a lower layer; upward illegal; 2→2 allowed, 3→3 disallowed; L1 has
   no child components), version satisfaction (`packaging`, incl. caret),
   cycle detection (reusing `OPTIONS_DEP_CYCLE`), and a transitive reverse-
   dependents index. Selected components **compile to project-scoped, frontend-
   targeted Fragments** (`component_<Name>`) that flow through the *existing*
   resolver/applier/provenance path — no new emission engine.

3. **The data contract extends the canvas system, but lives feature-local.** A
   `<Component>.contract.json` adds `operations` (`read`/`write`/`subscribe`,
   each with input/output schemas in the **ui_protocol JSON-Schema subset**).
   Types are emitted via the existing `ui_protocol` emitters as a self-contained
   `<Component>.contract.ts` the component's `.vue` imports (so a contract change
   is caught at build time by `vue-tsc`, not silently at runtime). Pure-UI
   components have no contract — a legal, representable state.

   **Refinement (2026-06-03):** the plan placed the contract as a sibling in the
   shared `templates/_shared/canvas-components/` dir. That is *not* where seed
   contracts live, because `build_manifest` flips the whole `canvas.manifest.json`
   to **v2** the moment any canvas component carries a contract, and
   `_emit_canvas_manifests` writes *all* canvas components into *every* project —
   so a single seed contract would flip every generated project's manifest and
   churn the golden snapshots. Instead a component's contract is **feature-local**
   (`forge/features/<feature>/<Component>.contract.json`), resolved per selected
   component via its `FeatureManifest.manifest_path`. The manifest stays v1; a
   contract only affects projects that select the component.

4. **Regeneration threads through `sync`.** Component `.vue`/`.ts` files are
   whole-file Forge-owned artifacts emitted into `apps/<frontend_slug>/` via the
   existing file applier + three-way merge + provenance. `forge --plan-update`
   reports the create/update/skip diff = the changed set ∪ its transitive
   *dependents* (never its dependencies). Determinism: a no-op re-run writes
   nothing and passes `forge --verify`.

5. **Brownfield binds via the same contract.** When `frontend.openapi_spec_url`
   is set, the contract operations bind to upstream `operationId`s through an
   editable `[contract_bindings]` mapping artifact + a non-Turing-complete
   transform DSL (field renames + a closed whitelist of scalar coercions).
   `forge/codegen/openapi_binding.py` flattens `$ref`s, validates bindings
   (fail loud, `FEATURE_CONTRACT_VIOLATION` → exit 6), and compiles transforms
   to a TS adapter over the `@hey-api` client.

6. **Errors reuse the existing hierarchy/exit-code map.** Cycle →
   `OPTIONS_DEP_CYCLE` (2); version-incompatible → `FEATURE_DEPENDENCY_MISSING`
   (6); contract↔op mismatch / layering violation → `FEATURE_CONTRACT_VIOLATION`
   (6, via `PluginError`); regeneration conflict → `MERGE_CONFLICT` (4). No new
   exit codes.

7. **First framework: Vue 3.** The model is framework-agnostic (it reuses the
   `FrontendLayout` registry); component emitters set RFC-011
   `frontend_skip_reason` ("Vue-first") until Svelte/Flutter emitters land.

## Consequences

- Components/templates are discoverable + authorable via `--component-cmd` /
  `--template-cmd` (list/scaffold) and selectable via a project's `components: []`.
- Seed artifacts ship as features: `StatCard` (L1, pure-UI), `EntityList` (L1,
  contract-bearing), `Console` + `ChatFirst` (L3).
- Contract artifacts (`<Component>.contract.ts`, `contract-bindings.toml`,
  `capabilities.ts`, `transform-adapters.ts`) emit into `apps/<frontend_slug>/
  src/shared/api/` — the real built app, where the component `.vue` lives and
  `vue-tsc`/`npm build` run — via `_frontend_api_dir`. (Note: the *other*
  `run_codegen` frontend outputs — `canvas.manifest.json`, `ui_protocol.gen.ts`,
  shared enums — still write to the legacy `project_root/<frontend_slug>/` tree;
  reconciling that pre-existing split is tracked as a separate follow-up.)
- Brownfield agent transport: a generated `capabilities.ts` carries
  `agentTransport: "external" | "stub"` — `"external"` iff a `subscribe`-kind op
  is bound (a default stub is written on the first/proposal run so a chat import
  always resolves).
- The flat option/fragment surface is untouched — the layered model is purely
  additive and guarded (empty `components` ⇒ byte-identical to the old flow).
- Pre-validation gate (plan §H/§J): each seed template + contract-bearing
  component is generated and `vue-tsc`-checked in CI (`e2e.yml` presets
  `console-template`, `chatfirst-template`, `entitylist`); the brownfield lane
  also fills a binding, re-runs codegen, and type-checks the emitted adapters.
- Telemetry: the `--component-cmd` / `--template-cmd` verbs emit `component.ran`
  / `template.ran` (bounded `action` vocabulary), documented in `telemetry.md`.
- Known v1 boundaries: L3 route/nav auto-wiring (router uses Copier `// ---`
  anchors, not `FORGE:` sentinels); brownfield transform paths are flat/dotted
  (no array-element remapping); the brownfield **runtime** docker CI profile (a
  live mock-OpenAPI server smoke, beyond the static `vue-tsc` gate) and the
  legacy `project_root/<slug>` vs `apps/<slug>` codegen-output split are tracked
  as follow-ups.
