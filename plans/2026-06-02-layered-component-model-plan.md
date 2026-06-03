# Forge: composable three-layer component model (Vue 3 first)

## Context

Forge today is a flat **option → fragment** generator: user-facing `Option`s
(dotted-path knobs) compile via `Option.enables` into `Fragment`s, which a
resolver topo-sorts and appliers emit into a project, with idempotent
re-generation through a three-way-merge/provenance/sentinel `sync` stack. There
is **no** notion of a *component* as a first-class, dependency-graphed,
re-generatable artifact, and **no** template-as-blueprint concept (the Vue app
shell + routes + nav are hand-authored Copier template files).

We want to evolve Forge into a **three-layer component model** — Layer-1 basic
components, Layer-2 composed components, Layer-3 templates (full-app blueprints)
— where each layer is a first-class artifact in a cross-layer dependency graph,
can be generated/re-generated at any layer, and reaches backend data only
through a **data contract**. First (and only, this iteration) framework target:
**Vue 3**. The same contract model must serve both greenfield (Forge emits the
backend slice) and brownfield (bind to an existing OpenAPI backend — the
motivating use case: present 3rd-party-integration workflow results in a
Console app with an agent chat + reports).

**This is a brownfield extension task.** The dominant failure mode is
reinventing machinery Forge already ships. Grounding below confirms that almost
every primitive needed already exists; the work is additive extension, not a
parallel generator.

---

## §0 Grounding map — requirement → existing subsystem it extends

Source of truth (read at `master @ 88d5d61`): the forge generator is installed
only as a `uv` git checkout at
`/home/c4/.cache/uv/git-v0/checkouts/977bfc3332d1492f/88d5d61` — **there is no
writable dev clone in the workspace** (see "Open: implementation location").

| Requirement | Extends (file:symbol) | Status today |
|---|---|---|
| Per-artifact manifest = graph node | `feature_manifest.py:FeatureManifest` / `parse_feature_manifest` | parser **ignores unknown `[feature]` keys** → `layer`/component-deps are purely additive |
| Component version specs | `feature.toml [feature.depends]` (name→spec string) + `version` | specs **stored but never satisfied** — range-satisfaction is new (tiny) |
| Dependency graph + cycle detection | `capability_resolver.py:_topo_sort` (Kahn) → `OPTIONS_DEP_CYCLE`; `fragments/_registry.py:_find_cycle_path` (DFS path) | forward dep-expansion only; **no reverse/dependents traversal** (new) |
| Data contract (UI + data) | `codegen/canvas_contract.py:CanvasComponentSpec` (`*.props.schema.json`, `canvas.manifest.json`, `lint_payload`, `forge canvas lint`) | props/UI only — **operations layer is new, but built on it** |
| Contract op input/output types | `codegen/ui_protocol.py:_ts_type_for/_pydantic_type_for/_dart_type_for` (object/str/int/num/bool/array/enum/const/nested/required/addlProps; out-of-scope: `$ref`,`oneOf/anyOf/allOf`,conditionals,discriminated unions) | reuse **verbatim**; extend ui_protocol only if a contract needs more |
| Multi-target / framework-agnostic seam | `frontends.py:FrontendLayout` + `register_frontend_layout`/`get_frontend_layout` (Epic O); `codegen/pipeline.py:run_codegen` | emit-path registry per framework already decouples targets |
| Idempotent regeneration | `sync/forge_to_project/updater:update_project` → `_merge_driver:_apply_fragment` → `appliers/pipeline:FragmentPipeline` → `copy_files`/`_apply_zoned_injection` → `merge.py:three_way_decide`/`file_three_way_decide` | full path exists; **do not build a new one** |
| Region semantics | `injectors/sentinels.py` (`FORGE:BEGIN/END <tag> fp:<hex8>`); inject zones `generated`/`user`/`merge` (`appliers/injection.py`) | inside-sentinel = Forge-owned, outside = user-owned; conflict → `.forge-merge` sidecar |
| Provenance / determinism | `sync/provenance.py:ProvenanceRecord/MergeBlockRecord/ProvenanceCollector`; `forge.toml [forge.provenance]`/`[forge.merge_blocks]`; ADR-006; `--reapply-baseline`, `--verify` | per-file + per-block SHA baselines; no-op = zero writes |
| Brownfield external backend | `config/_frontend.py` (`api_base_url`,`include_openapi`,`effective_mode`), `options/layers.py` (`frontend.mode` generate\|external\|none, `frontend.api_target.{type,url}`), `variable_mapper:_frontend_api_urls`, Vue `openapi-ts.config.ts.jinja` (@hey-api/openapi-ts) | external-URL + typed-client gen **already ship**; only contract↔op binding is new |
| OpenAPI parse / emit (shared contract seam) | `domain/typespec.py:compile_tsp`(→`openapi_spec` dict), `domain/emitters.py:emit_openapi` | greenfield emits entity→OpenAPI; brownfield parses external spec |
| Agent chat (AG-UI) | `features/agent` (`agent.mode` none\|llm_only\|tool_calling\|multi_agent; WS `/api/v1/ws/agent`; `AgentEvent` union); `codegen/event_union.py`; Vue `features/ai_chat/canvas/registry.ts` (`registerCanvasComponent`) | streaming idiom + canvas registry **already ship** — reuse, no 2nd transport |
| CLI verbs + scaffold | `cli/parser.py:_build_parser`, `cli/main.py` if-chain + `_exit_code_for`; `commands/{plan,plan_update,features,plugins,canvas,reapply_baseline}.py`; `cli/scaffold/` Jinja skeletons; `reports/` | subcommand + plan-only + scaffold patterns ready to extend |
| Errors / exit codes | `errors.py` (`OPTIONS_DEP_CYCLE`→2, `FEATURE_CONTRACT_VIOLATION`/`FEATURE_DEPENDENCY_MISSING`→6, `MERGE_CONFLICT`→4) + `_exit_code_for` | every new failure mode maps to an **existing** code/exit |
| Telemetry / logs | `telemetry.py:emit` + `EVENT_*`; `--telemetry`/`--log-json`/`--log-level`; `docs/telemetry.md` | add `EVENT_*` constants per verb |
| Templates / generate pipeline | `generator.py:_generate_into` (8 phases) / `_generate_frontend`; `templates/apps/vue-frontend-template/` (`router/index.ts.jinja` has `// --- feature routes ---` anchors; `shared/layouts/MainLayout.vue` shell); ADR-007 | app shell/routes hand-authored — Layer-3 makes them manifest-driven |

**Confirmed genuinely new (small, additive):** (a) `layer` field + component-dep
parsing, (b) the contract **operations** descriptor, (c) a component-tier graph
+ layering rules + reverse-dependents traversal, (d) component→fragment
compilation, (e) brownfield contract↔operationId binding + validation, (f)
Layer-3 manifest-driven shell/route/nav composition, (g) two seed templates.
Everything else is reuse.

### §0.1 HEAD re-verification (execution, `ba6abaa` — newer ancestor of `88d5d61`)
Re-checked the ~22 commits since grounding; all favorable, none conflicting:
- `capability_resolver.py` gained config-time validation passes
  `_check_value_backend_support` / `_check_security_constraints` invoked from
  `resolve()` — the **precedent** §A/§C component-layer + version + layering
  checks mirror (validation passes raising existing `OptionsError`/`PluginError`).
  `_topo_sort`/`resolve` extension points are intact.
- `provenance.py:_utc_now_iso` now honors `SOURCE_DATE_EPOCH` → byte-identical
  `forge.toml`; **strengthens** §D determinism / `--verify`-clean tests.
- `migration_chain.rechain_backend_migrations` now runs inside `_update_locked`
  before restamping — a clean precedent for where component-regen codegen hooks.
- **canvas_contract.py / ui_protocol.py / `_shared/canvas-components/` unchanged**
  → §B contract seam intact. The `feat/vendor-canvas-core` (#156) change vendors
  the AG-UI client into the *generated* Vue app
  (`features/ai_chat/canvas-core/{ag_ui_client,events,reducer,mcp_bridge}.ts` +
  `composables/useAgentClient.ts`) — §F's chat component binds to this vendored
  in-project client; the brownfield stub is a flag `useAgentClient` reads
  (aligns with §F `capabilities.ts`).

---

## Approach

### Terminology (used consistently)
**Artifact** = any node in the dependency graph: a Layer-1/2/3 component, a
backend feature, or a data contract. The source files an artifact emits are its
**outputs**, not artifacts.

### A. Additive manifest schema (`feature_manifest.py`, `feature_loader.py`, `plan_validator.py`)
One manifest = one artifact = one graph node; identity key is **`name`**. A
component is its own `feature.toml` with `layer` set. Add **optional** fields to
`FeatureManifest` (frozen dataclass, immutable defaults) and parse them only if
present so every existing manifest parses unchanged:
- `[feature].layer = 1|2|3` (absent ⇒ non-component feature). **Terminology
  (codex):** the TOML key stays `layer` (per spec) but the code symbol is
  `component_layer` and all messages say "component layer" — never "tier" —
  because `fragments/_spec.py:99` already ships `ParityTier = Literal[1,2,3]`
  (RFC-006 cross-backend coverage), an orthogonal concept sharing the {1,2,3}
  number space. A new ADR documents the orthogonality.
- `[feature].stability` (already in 10+ manifests, currently unparsed) — parse now.
- `[feature.component]` table for components:
  - `contract = "<ContractName>"` — the single data contract a Layer-1 consumes (optional ⇒ pure-UI, empty data-dependency set — a legal, representable state).
  - `children = ["FilterBar@^1.0", "DataTable@*"]` — child components (L2/L3), **reusing the `[feature.depends]` name→version-spec form**.
  - `aggregates = ["ReportingContract"]` — contracts a Layer-2 aggregates.
  - For `layer = 3`: `pages`, `routes`, `nav`, `shell` composition tables (see H).
- "Compatible" = semver **range satisfaction** over the spec string (`*`, `^1.0`, ranges). Add a tiny satisfier (none exists today; prefer `packaging.specifiers` if vendored, else minimal). Unsatisfiable ⇒ `FEATURE_DEPENDENCY_MISSING`.

`parse_feature_manifest` gains optional-key parsing; `validate_manifest_contracts`
+ a new `plan_validator._check_component_graph` enforce: layer ∈ {1,2,3},
**layering rule** (a dependency may only point same-or-lower layer; upward edges
1→2 / 2→3 rejected; **same-layer: 2→2 allowed (cycle-checked), 3→3 disallowed**),
referenced contracts exist, version specs satisfiable. Layering/contract
violations raise `PluginError(code=FEATURE_CONTRACT_VIOLATION)`.

### B. Data contract = extend canvas_contract + ui_protocol (no second emitter)
A contract is a sibling `<Component>.contract.json` next to the existing
`<Component>.props.schema.json` under `templates/_shared/canvas-components/`:
```jsonc
{ "component": "EntityList",
  "operations": [
    { "name": "list", "kind": "read",
      "input":  { "type":"object", "properties": { "page": {"type":"integer"} } },
    "output": { "type":"object", "properties": { "items": {"type":"array", "items": {...}} }, "required":["items"] } }
  ] }
```
- `kind ∈ {read, write, subscribe}`. `input`/`output` are expressed in the
  **ui_protocol JSON-Schema subset** — emitted to TS (Vue), Pydantic, Dart by
  **reusing `ui_protocol._ts_type_for` / `_pydantic_type_for` / `_dart_type_for`
  verbatim**. If a contract needs an out-of-scope feature, **extend
  `ui_protocol.py`**, never hand-roll a second emitter.
- Extend `CanvasComponentSpec` with optional `contract: DataContract | None`;
  extend `load_components` to load the sibling; extend `build_manifest` to add an
  optional `contract` key in `canvas.manifest.json` and **bump its `version` 1→2**
  when any component carries a contract (old readers warn-not-error on the unknown
  field). Absent/empty operations ⇒ pure-UI (representable). Validated through the
  **existing `forge canvas lint`** entrypoint (`lint_payload`/`cli_lint`), extended
  to load op schemas via ui_protocol (raising on out-of-scope) and to check
  op→binding compatibility.
- **Contract-model alignment (codex):** component data contracts are
  *orthogonal* to the RFC-005/006 **TypeSpec port contracts**
  (`templates/_shared/ports/*.tsp`). Ports describe *backend service interfaces*
  (queue/llm/object_store) compiled TypeSpec→OpenAPI; component contracts declare
  a *UI component's data dependency* and deliberately reuse the **canvas-props
  JSON-Schema + ui_protocol** path they sit next to — not TypeSpec — because
  canvas components already express props as JSON Schema. Brownfield binding
  reuses OpenAPI *parsing*, comparing external operation shapes against the
  contract's JSON-Schema op shapes (see §E). This is a deliberate choice, not an
  oversight; the ADR records why.

### C. Graph & resolver — **two graphs that compose** (`capability_resolver.py`, new `components/_registry.py`)
1. **Component graph (new tier).** A parallel `COMPONENT_REGISTRY` (mirrors
   `OPTION_REGISTRY`/`FRAGMENT_REGISTRY`), populated by `feature_loader` from
   component manifests. Nodes = components (+ contracts as leaves). Edges =
   `children`/`aggregates`. A new `resolve_components(selection)`:
   (a) validates layering + version satisfaction; (b) topo-sorts via a
   **generalized Kahn helper extracted from `_topo_sort`** (same algorithm),
   raising the **existing `OPTIONS_DEP_CYCLE`** with an SCC/cycle-path
   enrichment in `context` (reusing `_find_cycle_path`); (c) builds a
   **reverse-dependents index** `dependents[X] = {Y : Y depends on X}` —
   precomputed at resolve time, **transitive closure**, **including same-layer
   (2→2) edges** (covered by a test on an L1→L2→L3 fixture).
2. **Fragment graph (existing).** Each selected component **compiles to
   fragments** (its Vue emitter fragment, contract-type fragment, typed-client
   fragment, route/nav injection fragment) — exactly like an `Option.enables`
   fan-out. These feed the **unchanged** `resolve()`/`_topo_sort`. Composition:
   `ProjectConfig.components` selection (additive, alongside `options`) →
   component-graph resolve → emit fragment set → existing fragment resolve. The
   layered model is purely additive; flat option/fragment usage is untouched.

Components compile to `Fragment`/`FragmentImplSpec` for emission — **no new
emission engine**. **Fragment keying (codex):** a Vue component does *not* need
a new frontend-keyed Fragment model. Its emitter compiles to a **project-scoped
fragment** (`scope="project"`) gated by `target_frontends=(FrontendFramework.VUE,)`
— the exact mechanism `features/auth` and `features/platform` already use to ship
`.vue` files (`auth/fragments.py:198–201`; `_spec.py:186` comment). `FragmentImplSpec`
keeps its `BackendLanguage` key; `apply_project_features` applies it once at the
project root via a `proxy = BackendConfig(name="project", language=lang)`. For
frontend-only/brownfield projects (no real backend), the **existing
`_frontend_only` synth bridge (Initiative #3, `updater/__init__.py:205,487`)**
carries frontend-targeted fragments. Framework-agnostic by construction; Vue-only
registered now.

### D. Generation & regeneration — thread through `sync` (do not build a new path)
- **A component's outputs map onto existing appliers:**
  - Whole-file `.vue`/`.ts` component files → emitted as fragment `files_dir`
    content → `copy_files()` → `file_three_way_decide()` + provenance
    `origin='fragment'`. The whole file is Forge-owned. **(Critical: `.vue` is
    NOT in the sentinel comment-prefix map, so `.vue` components must be
    whole-file artifacts, never sentinel-injected; add a guard that *rejects*
    sentinel injection into unsupported extensions rather than silently
    falling back to the `#` prefix.)**
  - Cross-cutting registration (router routes, nav items, canvas registry) →
    fragment `inject.yaml` snippets into `.ts` files (`router/index.ts` via the
    existing `// --- feature routes ---` anchors, nav config, `registry.ts`),
    zone `merge` (user-editable) or `generated`. `.ts` is sentinel-supported.
- **Idempotent update** flows through `update_project()` → `_apply_fragment()` →
  `FragmentPipeline` → appliers → `three_way_decide` → provenance, surfaced via
  the existing `--update` / `--plan-update` / `--reapply-baseline` verbs.
- **Region semantics (explicit):** inside Forge sentinels = Forge-owned,
  overwritten on regen and shown in `--plan-update`; outside = user-owned, never
  touched; true merge conflict = fail loud + emit `.forge-merge` sidecar
  (`MERGE_CONFLICT`), never silent overwrite. Whole-file components: the file is
  Forge-owned (origin=fragment); user edits resolve via `file_three_way_decide`
  (merge / sidecar).
- **`.vue` drift safety (codex):** because generated `.vue` files are
  three-way-merged (not always-overwritten), a user can customize one. To prevent
  *silent* runtime breakage when a contract later changes, contract op
  input/output types are emitted as **TS interfaces (via ui_protocol) that the
  `.vue` imports**, so a drifted/incompatible customization is caught at build
  time by `vue-tsc` / `npm run build` in the pre-validation gate (§J) and the
  verify-smoke — never silently at runtime. The recommended extension pattern
  (steered by the scaffold + docs) is **composition/slots around the generated
  component**, not in-place edits.
- **Re-generation scope (reframed per codex — correctness vs. optimization):**
  - *Correctness comes from the existing whole-plan idempotent re-apply.*
    `update_project` resolves the full plan once and re-applies **every** fragment
    (`updater/__init__.py:225,455`); there is no per-fragment subset filter today
    beyond the frontend-only bridge. Idempotency makes this safe: unchanged
    fragments hit `skipped-idempotent` and write nothing. So the spec's required
    *observable* outcome — "change `EntityList` ⇒ the page (its dependent)
    regenerates; unrelated files + `EntityList`'s own deps/backend stay
    byte-identical" — **emerges naturally**: only outputs that actually changed get
    written; everything else is a no-op.
  - *The reverse-dependents index powers two things on top of that:* (1) the
    `--plan-update` **create/update/skip diff** (which artifacts *will* change =
    the changed set ∪ its `dependents[]` closure, annotated with reasons); and
    (2) an **optional targeted-regen filter** (`--component-cmd regenerate <name>`
    / a `--reapply-fragment`-style narrowing of `plan.ordered`) for speed — a
    *small additive filter* slotting beside the existing `_frontend_only`
    `project_apply_plan` filter (`updater/__init__.py:487`), **not** a new path.
  - Change-detection that drives the diff/targeted-regen records a **per-component
    manifest+contract SHA in `[forge.provenance]`** (additive, analogous to
    `template_version`) — an optimization/reporting aid, *not* a correctness gate.
- **Determinism:** a no-op re-run produces zero writes (existing
  `skipped-idempotent` path) regardless of user edits to user-owned regions, and
  passes `forge --verify` clean — because re-applying unchanged fragments is a
  no-op and the per-component SHA matches its recorded baseline.
- **Targeted generation at any layer:** new entrypoints select a subset (a whole
  template / one composed component / one basic component, or *add* one into an
  existing project), compile those + transitive **dependencies** into the fragment
  plan, then run the **existing** generate pipeline; for *re*-generation into an
  existing project they use the whole-plan re-apply above (optionally narrowed via
  the targeted filter).

### E. Brownfield — bind a contract to an existing OpenAPI backend (§5)
Reuse what ships: `frontend.mode=external` + `frontend.api_target.url` already
point a generated Vue app at an external base URL and generate a typed client via
`@hey-api/openapi-ts`. **New delta only:**
- Add option `frontend.openapi_spec_url` (additive in `options/layers.py`).
- Ingest the OpenAPI/Swagger spec (URL or file); parse via the existing OpenAPI
  handling in `domain/` (the `openapi_spec` dict path).
- **`$ref` flattening (codex):** real-world specs use `$ref` heavily, which
  ui_protocol rejects today. Extend **ui_protocol** with **internal `$ref`
  resolution** (`#/components/schemas/...` → inline, ~tens of LOC) so external
  schemas reduce to the supported subset before comparison — honoring the spec's
  "extend ui_protocol, don't hand-roll a second emitter" rule. Genuinely
  unsupported constructs (`oneOf/anyOf/allOf`, conditionals, discriminated unions)
  still **fail loud** with a clear message and surface the op as *unbindable* in
  the mapping artifact.
- Emit a **mapping artifact** (TOML, mirroring `_forge_template.toml` shape):
  `[contract_bindings]` proposing `contract-op → operationId` + schema refs. **It
  is emitted as a fragment file (`origin='fragment'`)**, so it flows through
  `file_three_way_decide()`: user hand-edits to bindings are preserved unless the
  contract itself changes (then three-way merge / sidecar). Forge **fails loud**
  (`FEATURE_CONTRACT_VIOLATION`) if a required contract op has no binding, or if
  the bound shape (after the transform below) does not satisfy the contract op's
  schema.
- **Transform DSL (user-selected — replaces exact-shape v1).** Each binding may
  carry a declarative, **non-Turing-complete** transform that maps field-level
  renames + scalar coercions + nested/array path remapping between the contract
  op's request/response schema and the upstream operation's. Shape:
  ```toml
  [contract_bindings.list]
  operation_id = "listItems"
  [contract_bindings.list.response]          # upstream response -> contract output
  "items"      = "data"                       # rename
  "items[].id" = "data[].item_id"             # nested/array-element path rename
  "count"      = { from = "total", coerce = "int" }   # rename + coercion
  [contract_bindings.list.request]           # contract input -> upstream request
  "page"       = { from = "page", coerce = "int" }
  ```
  - **Paths:** dotted with `[]` array-element segments (a restricted JSONPath
    subset) — no wildcards/filters/recursion.
  - **Coercions:** a *closed whitelist* (`int`,`float`,`str`,`bool`,
    `iso8601<->epoch`, `null_default`); unknown coercion ⇒ `FEATURE_CONTRACT_VIOLATION`.
  - **Out of scope (YAGNI):** arbitrary expressions, conditionals, cross-field
    synthesis, computed values. Stated explicitly so the DSL stays validatable +
    deterministic.
  - **Emission:** the DSL compiles to a thin **TS adapter** wrapping the
    `@hey-api/openapi-ts` client (Vue/TS now), emitted as a whole-file fragment
    artifact (`origin='fragment'`, participates in provenance/merge). Type
    comparison still reuses **ui_protocol (with `$ref` flattening)**: the
    *post-transform* shape must satisfy the contract op schema — renames never
    bypass type-checking.
- Greenfield (emit backend slice from contract via `emit_openapi`) and brownfield
  (bind to external OpenAPI) **share one contract model** — the contract is the
  seam. The mapping artifact + generated client participate in the
  provenance/merge path like any other output.

### F. Agent chat = reusable Layer-2 component (§6)
The chat surface (Console right panel / Chat-first bottom dock) is a Layer-2
component bound to the existing `features/agent` via the **AG-UI streaming
idiom** (WS `/api/v1/ws/agent` + `AgentEvent` union + `event_union.py` codegen +
Vue `ai_chat/canvas/registry.ts`). **No second transport — AG-UI only
(confirmed).** Its contract = the agent endpoint + the result schemas it may read.
- **Greenfield:** including chat pulls in `features/agent` (backend) → live panel.
- **Brownfield (concrete mechanism, codex):** the binding step writes a generated
  `capabilities.ts` carrying `agentTransport: "external" | "stub"` — `"external"`
  iff an agent op binds in the mapping. The chat component reads it at mount: when
  `"stub"`, it disables the input and shows "Agent not available in this
  deployment" (an inert stub transport, no live WS). Flipping a binding on and
  re-running `forge --update` regenerates `capabilities.ts` and the panel goes
  live — it is **not** runtime-polled. A test covers the stub→live transition.
  This keeps the "runnable app" acceptance criterion independent of an unconfirmed
  transport.

### G. CLI surface & authoring (§7)
New top-level flags in `parser.py:_build_parser()`, dispatched in `main.py`'s
if-chain, following the `--features-cmd` / `--plugins` / `--canvas` subcommand
pattern; reuse `--project-path` + the exit-code taxonomy + telemetry flags:
- `--component-cmd {list,add,regenerate,scaffold}` and `--template-cmd {list,add,scaffold}` — generate/add a component or template into a project and regenerate at a target layer. (codex: `--component`/`--template` are unreserved today — no collision; a CLI lint test asserts no new flag clashes with an existing one.)
- Each write verb has a **plan-only variant routed through the existing
  plan/plan_update reports** (`_dispatch_plan`/`_build_preview`/`_print_tree`,
  `_run_plan_update`). `--plan-update` shows the create/update/skip set with
  reasons = the dependency-graph diff (the reverse-edge closure).
- **Authoring** extends `features scaffold` (`_scaffold_feature`) +
  `plugins scaffold-fragment` (`_scaffold_fragment`/`_render_skeleton`) to emit a
  layer-aware skeleton — a `feature.toml` with `layer`, a `*.props.schema.json` +
  `*.contract.json` stub, a Vue emitter stub — placed under `forge/features/*` or
  `forge/templates/_shared/canvas-components/`. New skeleton dir
  `cli/scaffold/component_skeleton/`.

### H. Pre-validated Layer-3 templates (§3, §8)
A Layer-3 template = a `feature.toml` with `layer=3` declaring `children`
(L2/L1) + page/route/nav/shell composition. The manifest drives: (a) per-page
whole-file `.vue` emission; (b) route injection into `router/index.ts` via the
existing anchors; (c) nav-item injection into nav config; (d) shell selection
(a `MainLayout.vue` variant). Reuse `FrontendLayout` emit paths; **Vue-only
emitters now** (Svelte/Flutter follow once proven).

**Seed templates:**
- **Console** — left-nav menu + home/dashboard + reports page + right-hand agent chat panel.
- **Chat-first** — single page, agent chat docked bottom + results surface above.

**"Pre-validated" means:** each template manifest carries a
`validation`status/version; its CI gate (build + smoke/e2e + brownfield
mock-server) is green for that version; and a freshly generated app passes
`forge --verify` clean on a no-op re-run (ties to D's determinism).

### I. Errors & telemetry (§8) — no new exit codes
| New failure mode | ForgeError code (existing) | Exit |
|---|---|---|
| Component dep cycle | `OPTIONS_DEP_CYCLE` (+ SCC context) | 2 |
| Unsatisfiable version | `FEATURE_DEPENDENCY_MISSING` | 6 |
| Contract↔operation mismatch | `FEATURE_CONTRACT_VIOLATION` | 6 |
| Layering violation (upward edge) | `FEATURE_CONTRACT_VIOLATION` | 6 |
| Regeneration conflict | `MERGE_CONFLICT` / `FILE_MERGE_CONFLICT` | 4 |

New verbs emit `EVENT_*` telemetry + structured logs via `telemetry.emit`,
honoring `--telemetry`/`--log-json`/`--log-level`; update `docs/telemetry.md` +
`_MINIMAL_ALLOWED_FIELDS`.

### J. CI validation profiles (§8)
- **Greenfield:** full docker compose (Traefik + backend + per-backend Postgres + migration containers + Vue app); health-check `/api/<backend>/v1/health/live`.
- **Brownfield / frontend-only (`frontend.mode=external`):** Vue app + a mock server serving the OpenAPI spec; no Postgres/migration containers; health-check = mock-server readiness + app build/smoke.

---

## Critical files (extend, do not replace)
- Manifest: `forge/feature_manifest.py`, `forge/feature_loader.py`, `forge/plan_validator.py`
- Contract: `forge/codegen/canvas_contract.py`, `forge/codegen/ui_protocol.py`, `forge/codegen/canvas_lint.py`, `forge/templates/_shared/canvas-components/*`
- Graph: `forge/capability_resolver.py`, `forge/options/_registry.py`, `forge/fragments/{_spec.py,_registry.py}`, **new** `forge/components/_registry.py`
- Sync (reuse only): `forge/sync/forge_to_project/updater/*`, `forge/appliers/{files.py,injection.py,pipeline.py}`, `forge/sync/{merge.py,provenance.py}`, `forge/injectors/sentinels.py`
- Generate/frontend: `forge/generator.py`, `forge/frontends.py`, `forge/codegen/pipeline.py`, `forge/variable_mapper.py`, `forge/config/_frontend.py`, `forge/options/layers.py`
- Brownfield: `forge/domain/{typespec.py,emitters.py}`, Vue `openapi-ts.config.ts.jinja`
- Agent: `forge/features/agent/*`, `forge/codegen/event_union.py`, Vue `features/ai_chat/canvas/registry.ts`
- CLI/errors/telemetry: `forge/cli/parser.py`, `forge/cli/main.py`, `forge/cli/commands/*`, `forge/cli/scaffold/*`, `forge/reports/*`, `forge/errors.py`, `forge/telemetry.py`
- Templates: `forge/templates/apps/vue-frontend-template/*` (router, MainLayout, pages)

## Phasing (strict TDD: failing test first at each step)
0. **Contract model** — ui_protocol/canvas_contract op extension + `component_layer` field parsing + `canvas.manifest.json` v2; ADR (layer ⊥ parity_tier). *Unit.*
1. **Component graph** — `COMPONENT_REGISTRY`, `resolve_components`, layering + cycle (`OPTIONS_DEP_CYCLE`) + version errors, transitive reverse-dependents index. *Unit + integration.*
2. **Compile + regen** — component→fragment compilation (project-scope + `target_frontends`); per-component provenance SHA; whole-plan idempotent re-apply + optional targeted filter; `--plan-update` dependency-graph diff; `--verify` clean on no-op. *Integration.*
3. **Vue emitters + seed L1/L2** — `EntityList`, `FilterBar`, `DataTable`-bound, chat L2 panel; whole-file `.vue` + `.ts` injection; emitted TS contract types + `vue-tsc` drift gate; sentinel-unsupported-extension guard. *Integration + e2e.*
4. **L3 templates + CLI** — Console + Chat-first manifests; `--component-cmd`/`--template-cmd` + plan-only + scaffold + CLI no-collision lint. *e2e greenfield.*
5. **Brownfield** — `frontend.openapi_spec_url`, OpenAPI ingest, ui_protocol `$ref` flattening, mapping artifact (origin=fragment), **transform DSL** (renames + whitelisted coercions → TS adapter) + post-transform contract validation, chat `capabilities.ts` stub. *e2e brownfield w/ mock server (incl. a renamed/coerced-field binding case).*
6. **CI + pre-validation gate + telemetry + docs** — both profiles green; `EVENT_*`; `docs/FEATURES.md` + new ADR/RFC.

## Verification (end-to-end)
- Generate **each seed template** (Console, Chat-first) in **both greenfield and brownfield** modes → a runnable Vue 3 app (`npm run build` + smoke; brownfield against the mock OpenAPI server).
- Add/update a single basic **or** composed component in an existing generated project; assert its transitive **dependents** regenerate, unrelated files + user-owned regions stay byte-identical, and `forge --verify` is clean on a subsequent no-op re-run.
- Force a dependency cycle → assert `OPTIONS_DEP_CYCLE`; force an unsatisfiable version spec → assert it is reported (`FEATURE_DEPENDENCY_MISSING`).
- `forge --plan-update` shows the create/update/skip set with reasons (the dependency-graph diff).
- Both seed templates pass their pre-validation gate (both CI profiles).
- Tests at **unit + integration + e2e** layers (standing test discipline).

## Codex cross-review (per user request)
**Round 1 (done, plan-mode, read-only):** two codex agents cross-reviewed this
plan against the source from distinct lenses (architecture/reuse-fidelity;
regeneration/idempotency/brownfield). They verified all six §0 grounding claims
and raised findings now **incorporated above**: (1) reframed regen as whole-plan
idempotent re-apply + reverse-dependents diff + optional targeted filter — the
existing `update_project` has no subset filter (§D); (2) component fragments are
project-scoped + `target_frontends`, not a new frontend-keyed model (§C); (3)
`.vue` drift caught by emitted TS types + `vue-tsc`, composition over in-place
edits (§D); (4) brownfield needs ui_protocol `$ref` flattening for real specs
(§E); (5) concrete chat-stub `capabilities.ts` mechanism (§F); (6) `layer` vs
`parity_tier` terminology + `canvas.manifest.json` v2 + mapping-artifact
provenance + reverse-index spec. No pushbacks; convergence in one round.

**Phase A (done, in-repo, verifiable real codex):** `codex exec -m gpt-5.5`
re-confirmed this plan against HEAD. **Verdict: Phase 0 SAFE** — no
BLOCKER/IMPORTANT; all four Phase-0 safety claims confirmed with file:line
(`canvas_contract.py:22,49,67`, `ui_protocol.py:145,252,369`,
`feature_manifest.py:59,75,83,106`), HEAD delta confirmed non-conflicting. One
NIT: the conditional `canvas.manifest.json` v1→v2 bump must keep contract-less
manifests at v1 so `tests/test_canvas_contract.py:37,58` (version-1 assertions)
stay green — the plan's bump is already conditional-on-contract-present, so no
change to contract-less manifests.

**Codex model availability (honest note):** in this environment the ChatGPT-account
auth rejects `gpt-5.3-codex`/`gpt-5-codex` (the `review` profile's model); only
`gpt-5.5` is reachable. So the *real* codex reviews use `gpt-5.5` (the
`plan-review` profile / explicit `-m gpt-5.5`). Per-phase **Phase B** impl reviews
will likewise run `codex exec -m gpt-5.5` (not the `review` profile) until codex
model access is fixed. The earlier round-1 subagent reviews were corroborated by
this verifiable direct run.

## Decisions (confirmed with user)
1. **Agent transport:** AG-UI-over-`features/agent` **only** — no second transport stack (§F).
2. **Brownfield mapping richness:** **transform DSL now** — declarative field renames + whitelisted scalar coercions + nested/array path remapping (non-Turing-complete), specified in §E.
3. **Implementation location:** **clone `github.com/cchifor/forge` fresh** into `/workspace/c4/forge` on branch `feat/layered-component-model` (execution Step 0); the read-only `uv` cache checkout was used only for grounding.

## Execution Step 0 (before any code)
`gh repo clone cchifor/forge /workspace/c4/forge` → `git switch -c
feat/layered-component-model` → confirm clean tree → move this plan into
`forge/plans/` and run **codex-reviewed-planning Phase A** (re-confirm), then TDD
the phases above with **Phase B** codex review per phase.

<!-- codex-review-status: finalized -->
<!-- phase-A verdict: Phase 0 SAFE (codex gpt-5.5, HEAD ba6abaa) -->
<!-- phase-B model: codex exec -m gpt-5.5 (gpt-5.3-codex blocked for this account) -->
