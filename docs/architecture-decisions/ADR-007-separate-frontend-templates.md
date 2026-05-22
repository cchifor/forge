# ADR-007: Three separate frontend templates instead of one with adapters

- Status: Accepted
- Author: forge team
- Date: 2026-05-22
- Scope: `forge/templates/apps/vue-frontend-template/`,
  `forge/templates/apps/svelte-frontend-template/`,
  `forge/templates/apps/flutter-frontend-template/`
- Related: Pillar B of the 1.2.0 roadmap (cross-stack canvas core)

## Context

forge generates frontends in three frameworks: **Vue 3** (TypeScript +
Vite + Pinia + Vue Router), **Svelte 5** (TypeScript + SvelteKit +
runes + adapter-node), and **Flutter** (Dart + Riverpod + go_router).
Each lives under its own directory tree:

```
forge/templates/apps/
  vue-frontend-template/template/...
  svelte-frontend-template/template/...
  flutter-frontend-template/template/...
```

The three trees are largely parallel — same product surface (chat UI,
auth flow, telemetry hooks, settings panel), three full implementations.
A new contributor looking at this on their first day will ask the
obvious DRY question:

> Why isn't there one shared `frontend-template/` with framework
> adapters? Surely the components, routes, and state stores can be
> abstracted?

It comes up often enough that we want a written answer to point at.

This ADR is that answer.

## Decision driver

**Frontend frameworks differ at every architectural layer, not just at
the leaves.** "Adapt" them with shared abstractions and the abstraction
is always bigger than the per-stack file it replaces.

Concretely, the disagreement is total:

| Layer | Vue 3 | Svelte 5 | Flutter |
|---|---|---|---|
| File shape | `<script setup lang="ts">` SFC | `<script lang="ts">` runes mode | Dart classes |
| Entry point | `src/main.ts` + `App.vue` | `src/routes/+layout.svelte` | `lib/main.dart` |
| Routing | Vue Router (declared in JS) | SvelteKit file-system routing | go_router (declared in Dart) |
| State | Pinia stores | `$state` runes | Riverpod providers |
| Reactivity | Proxy-based (`ref`, `computed`) | Compiler-based (`$state`, `$derived`) | Observable-based (Provider, StreamProvider) |
| Build tool | Vite | Vite (via SvelteKit) | `flutter build` |
| Testing | Vitest + Vue Test Utils | Vitest + svelte/testing-library | flutter_test + golden_toolkit |
| Forms | v-model + composables | bind: + actions | TextEditingController + Form |
| Async data | `<Suspense>`, composables | `+page.ts` load + `await` | FutureProvider + AsyncValue |
| SSR | optional (Nuxt or vite-ssr) | first-class (SvelteKit) | n/a (mobile/desktop) |

A "shared component" that wraps each of those would have a per-stack
adapter for *every* layer. The abstraction wouldn't reduce code; it
would multiply it (one shared interface + three adapters where two
existed before) while making each stack harder to debug because the
real code is now hidden behind a generic wrapper.

We tried it during the 0.x prototyping era. It bounced.

## Decision

**Each frontend framework gets its own complete template tree.** Vue,
Svelte, and Flutter each own `forge/templates/apps/<stack>-frontend-template/`
end-to-end, with no shared per-component abstraction layer.

What *is* shared lives at the protocol level, not the framework level:

- **`@forge/canvas-core` (TypeScript / pub)** — framework-agnostic
  AG-UI SSE client, MCP approval client, MCP bridge interface. Owned by
  no UI stack. Consumed by `@forge/canvas-vue` and
  `@forge/canvas-svelte` (TypeScript) and `forge_canvas_core` (Dart, for
  Flutter).
- **`@forge/canvas-vue` / `@forge/canvas-svelte` / `forge_canvas`
  (Flutter)** — thin per-stack bindings around the core protocol. They
  expose framework-native primitives (Vue composables, Svelte runes,
  Flutter widgets / Riverpod providers) without forcing a shared
  component API.

The split is **PROTOCOL is shared; FRAMEWORK CODE is per-stack.** That
is the layer at which sharing pays for itself: the AG-UI reducer logic
is identical in every stack, framework-independent, and benefits from a
single canonical implementation. Above it, each framework wants its
own idioms.

### What "complete template tree" includes

Each `<stack>-frontend-template/` carries its own:

- Build config (`vite.config.ts`, `svelte.config.js`, `pubspec.yaml`).
- Linter / formatter config (`.eslintrc`, `analysis_options.yaml`).
- Test runner setup (Vitest, flutter_test).
- Docker image recipe (multi-stage with the framework's native build).
- Compose snippet (Traefik labels, healthcheck, service deps).
- CI workflow shard.
- README scoped to that stack's developer experience.

No file in any tree imports from any other tree. The tradeoff is
deliberate: duplication where the frameworks disagree, sharing where
they don't.

## Alternatives considered

### One shared template with framework adapters

A single `frontend-template/` tree using `{% if framework == "vue" %}`
Jinja blocks (or per-file adapters) to emit Vue / Svelte / Flutter
flavours.

Rejected because:

- The differences are total at every layer (see the table above). The
  Jinja blocks become 80% of every "shared" file, at which point the
  shared file is a worse version of three separate files.
- Routing alone breaks the abstraction: Vue Router's declarative
  config, SvelteKit's file-system routes, and go_router's GoRoute tree
  have no common surface. Forcing one inevitably picks a winner and
  papers over the other two with adapter cruft.
- Per-framework debugging gets harder. A bug in the Svelte runes flow
  now lives inside a template that also has to compile for Vue and
  Flutter; the local reasoning chain extends across stacks the user
  never selected.

### Shared "atoms" library, per-stack templates

Keep separate templates but factor out a shared design-token + atom
library (Button, Input, Card) implemented per stack with a common API.

Rejected because:

- A "shared API" that's implemented three times is still three
  implementations to maintain — with the extra constraint that they
  must agree on signatures.
- Native UI patterns in each ecosystem disagree on what a "Button"
  even is. (Vue Quasar's `<q-btn>`, Svelte's slot-based composition,
  Flutter's Material 3 `FilledButton` vs `OutlinedButton` vs
  `TextButton` family — none of these can be hidden behind a single
  `Button` API without choosing which ecosystem wins.)
- The cost we'd be paying — adding a shared design-system layer —
  buys consistency that the *target users of forge-generated apps*
  don't ask for. forge generates starting points, not finished
  products; the user picks their preferred UI library after
  generation.

### Pick one frontend, ship adapters for the others later

Bet on one framework (e.g. Vue), ship a complete template, and add
Svelte / Flutter as adapter layers on top.

Rejected because:

- "Ship adapters later" is how you get a first-class Vue template and
  two second-class derivatives. We want all three to feel native.
- The choice of frontend is one of forge's headline pluralism
  decisions; pinning one as primary undermines that.

### Web Components as the shared surface

Build the shared layer as Web Components; each framework consumes them.

Rejected because:

- Doesn't reach Flutter (no Web Components in Dart / mobile).
- Adds a build step (custom-element bundler) every stack has to wire
  up.
- Solves a problem we don't have at the layer we don't share. The
  layer we *do* share (AG-UI protocol) is not a UI concern; it's a
  network / state concern. Web Components don't help there.

## Consequences

### Positive

- **Each stack reads as a normal app in its own idiom.** A Vue
  contributor sees `<script setup>` SFCs and Vue Router; a Svelte
  contributor sees runes and SvelteKit conventions; a Flutter
  contributor sees Riverpod providers. No one is reading a
  forge-specific dialect of their own framework.
- **Per-stack upgrades are local.** Vue 3.4 → Vue 3.5 touches only
  the Vue tree. Svelte 4 → Svelte 5 was a multi-week migration that
  did not block Vue or Flutter work.
- **Stack-specific tooling stays first-class.** ESLint configs,
  Vitest plugins, flutter analyzer rules — each stack uses its
  ecosystem's tooling as a normal user would.
- **Shared concerns land at the right layer.** The AG-UI reducer
  (Pillar B) is genuinely shared because it's a *protocol*
  implementation, not a UI implementation. The split lets us extract
  it cleanly without touching per-stack code.

### Negative

- **Three implementations to maintain.** Adding a new top-level
  feature (e.g. "settings page") means writing it three times.
  Mitigated by: features are added rarely; the implementations stay
  small; per-stack tests catch regressions independently.
- **Three sets of dependencies to keep current.** Per-stack Dependabot
  / Renovate noise. Mitigated by the weekly upgrade-probe workflows
  per stack — divergence is detected on a schedule, not at release
  time.
- **Easy to accidentally diverge.** Vue gets a feature; nobody adds
  it to Svelte or Flutter. Mitigated by golden snapshot tests per
  stack and an explicit "feature parity matrix" tracked in
  `docs/matrix-status.md`.
- **Discoverability cost.** A user comparing the three has to read
  three READMEs. We accept this; the alternative (one README that
  papers over the differences) hides decisions the user needs to see.

### Neutral

- The split is not absolute: any genuinely framework-agnostic logic
  (protocol clients, schema validators, shared types) is welcome at
  the package level (`packages/canvas-core/`, `packages/canvas-vue/`,
  etc.), it just doesn't live inside the templates themselves.

## References

- `forge/templates/apps/{vue,svelte,flutter}-frontend-template/` — the
  three trees this ADR is about.
- `packages/canvas-core/` (TypeScript), `packages/forge-canvas-core-dart/`
  (Dart) — the protocol-layer sharing this ADR endorses.
- `docs/adding-a-frontend.md` — the contributor guide that implicitly
  encodes this decision; new stacks get their own tree.
- 1.2.0-targeted Pillar B work (canvas-core / forge_canvas_core split)
  in `CHANGELOG.md` — the canonical example of "share at the protocol
  layer, not the framework layer."
