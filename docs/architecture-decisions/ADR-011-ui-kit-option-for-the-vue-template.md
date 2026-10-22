# ADR-011: A UI kit option for the Vue template

- Status: Proposed
- Author: forge team
- Date: 2026-10-22
- Scope: `forge/ui_kits.py`, `FrontendConfig.ui_kit`, `forge/layout_variants.py`
  and the Vue `layout.toml` files, `[feature.component]` in component
  manifests, `Fragment.ui_kits`, `forge/capability_resolver.py`,
  `forge/templates/apps/vue-frontend-template/`
- Related: [plan](../../plans/2026-10-22-vue-ui-kit-nuxt-ui.md);
  [[ADR-006]] (provenance), [[ADR-007]] (separate frontend templates),
  [[ADR-010]] (layered component model)

## Context

The Vue template ships shadcn-vue as its only component kit. The ownership
model keeps that kit in every generated tree: `src/shared/ui/` is
`generated`, the screens around it are `scaffold`, and the layouts and
component features import it.

A project that wants Nuxt UI 4 today installs it beside the generated kit and
hooks scaffold files to make the two coexist. Both kits define the same
Tailwind colour utilities from different tokens. The generated settings store
and Nuxt UI's colour mode both write `.dark`, each from its own storage key.
The generated screens keep rendering on shadcn-vue. Every hook is an edited
scaffold file, so every generator update proposes it again as a sidecar.

Those clashes exist only because the template has one kit. Nuxt UI is a
complete kit with its own theming, colour mode, icons and overlay layer; it
works best adopted by its documented model, not adapted to shadcn-vue's.

## Decision

1. **One option, Vue only.** `frontend.ui_kit` takes `shadcn` (the default)
   or `nuxt-ui`. It travels like `frontend.layout`: `FrontendConfig.ui_kit`,
   the stack file, `--ui-kit`, the interactive prompt, the Copier variable
   `ui_kit`, `[forge.frontend] ui_kit` in `forge.toml` and the recipe. It is
   not an option-registry path, so `forge --schema` does not list it. Svelte
   and Flutter keep their kits; the asymmetry is deliberate, as in ADR-007.
2. **A registry of kits.** `forge/ui_kits.py` records each kit's frameworks,
   whether it is selectable, whether the AI chat UI renders on it, and the
   colour schemes it accepts. `nuxt-ui` is registered unselectable until the
   template renders it, the way a layout can be registered with
   `supported = false`.
3. **Compatibility is declared where each artifact lives.** A layout lists
   its kits in `layout.toml` (`ui_kits`), a component feature in
   `[feature.component]` (`ui_kits`, plus `replaced_by` naming the component a
   kit offers instead), a fragment on `Fragment.ui_kits`. Layouts and
   components default to `shadcn` only; fragments default to any kit. A
   declaration is checked against its files: a tree that claims `nuxt-ui`
   may not import the shadcn kit or use its colour classes.
4. **Refusals happen at plan time.** Before anything is written, forge refuses
   an unknown or unselectable kit, a kit on a template without kits, a layout
   that does not list the kit, chat on a kit without the chat UI, a colour
   scheme the kit does not accept, a component the kit cannot render (or a
   child it pulls in, reported through the selected component), and a
   fragment declaring other kits.
5. **Kit-specific files sit side by side.** The base template carries both
   kits under Copier conditional file names, and `src/shared/ui/` sits under a
   conditional directory name, so both variants of a screen are reviewed in
   one place and the shared plumbing stays single.
6. **Nuxt UI is adopted by the book.** Under `nuxt-ui`, Nuxt UI's colour mode
   is the one writer of `.dark`, the palette is fixed per project, and nothing
   of the shadcn-era theming (the settings store, `.oled`, the runtime
   schemes, the text-size axis) is carried over.
7. **Content security is repaired first.** `security.csp` serves a working
   per-request nonce policy for both kits, and the `nuxt-ui` wiring passes the
   nonce to `UApp` and to the head manager that inserts Nuxt UI's palette.

## Alternatives considered

### The kit as a layout overlay

Rejected. An overlay renders after the base and cannot remove the base's
`src/shared/ui/`, so the base would need the conditional anyway. A third
render stage would also have to interleave with the layout overlays.

### A separate Vue template for Nuxt UI

Rejected. ADR-007 separates templates because frameworks differ in idiom.
Two Vue templates would duplicate the router, auth, API client, stores, mocks
and tests to vary only the component layer.

### Nuxt UI wired by each consumer

Rejected. Consumer hooks are edited scaffold, which every update re-proposes
as sidecars, and the generated screens would stay on shadcn-vue.

### Keeping the shadcn-era theming under Nuxt UI

Rejected. Turning Nuxt UI's colour mode off so the settings store keeps
writing `.dark` adapts the kit to a clash that only exists with shadcn-vue,
and leaves Nuxt UI's colour-mode components inert.

## Consequences

- Existing projects render as before. Their recipe gains the `ui_kit` field
  and their manifest a `ui_kit` line on the next update.
- New layouts and component features render with `shadcn` until they declare
  more, so a new kit can never be selected for something that ignores it.
- The kit-free components are fewer than their imports suggest: StatCard,
  StatusDot and ChatFirst use shadcn colour classes, so they declare `shadcn`
  only.
- Plugin layouts render with `shadcn` until `add_frontend_layout` accepts
  `ui_kits`.
- Nuxt UI is pinned as a forge constant with a caret on the major; the
  vendored Nuxt UI agent skill follows its minor.

## References

- `plans/2026-10-22-vue-ui-kit-nuxt-ui.md` — the plan, its sequencing (F-01 to
  F-03) and the Nuxt UI facts it rests on.
- `forge/ui_kits.py` — the registry and the frontend checks.
- `tests/test_ui_kits.py`, `tests/test_ui_kit_coverage.py` — the refusals and
  the declaration lint.
- Nuxt UI's Vue installation guide, `https://ui.nuxt.com/docs/getting-started/installation/vue`.
