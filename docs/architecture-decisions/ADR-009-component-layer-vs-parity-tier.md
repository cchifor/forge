# ADR-009: `component_layer` is orthogonal to `ParityTier`

- Status: Accepted
- Author: forge team
- Date: 2026-06-02
- Scope: `forge/feature_manifest.py` (`FeatureManifest.component_layer`),
  `forge/fragments/_spec.py` (`ParityTier`), the layered-component model
- Related: 2026-06-02 layered-component-model plan (Phase 0)

## Context

The layered-component model adds a `[feature].layer = 1|2|3` field to
`feature.toml` to classify an artifact as a **Layer-1 basic component**,
**Layer-2 composed component**, or **Layer-3 template**. These are *composition
levels* in the UI dependency graph: a dependency may only point at the same or a
lower layer.

The codebase already ships `ParityTier = Literal[1, 2, 3]` in
`forge/fragments/_spec.py` (RFC-006). A fragment's parity tier describes its
**cross-backend coverage**:

- Tier 1 — implemented on every built-in backend (Python, Node, Rust).
- Tier 2 — best-effort subset, with a documented migration path.
- Tier 3 — Python-only, honest about its scope.

Both concepts use the integer set `{1, 2, 3}`. A reader who sees a `2` in a
manifest could reasonably mistake one for the other, and an error message that
says "tier 2" is ambiguous.

## Decision

1. The **TOML key stays `layer`** (the user-facing spelling in `feature.toml`),
   because that is what the layered-component model is about.
2. The **dataclass field and all code/log/error surfaces use `component_layer`**
   and the words "component layer" — never "tier". `ParityTier` keeps "tier".
3. The two are **orthogonal axes** and never share validation, ordering, or
   defaulting logic:
   - `component_layer` constrains *which artifacts may depend on which* (graph
     shape) and is `None` for non-component features.
   - `parity_tier` constrains *which backends an implementation must cover* and
     is auto-derived from `Fragment.implementations`.
   A Layer-2 component can compile to fragments of any parity tier; a Tier-1
   fragment has no component layer.

## Consequences

- `FeatureManifest` gains an optional `component_layer: int | None` that defaults
  to `None`, so every existing manifest parses unchanged (the parser already
  ignores unknown `[feature]` keys).
- Error messages reference "component layer N", keeping them unambiguous against
  parity-tier diagnostics.
- No shared enum: deliberately *not* reusing `ParityTier` for `component_layer`,
  even though both are `{1,2,3}`, to keep the two axes from coupling as the model
  grows (e.g. if component layers ever extend past 3, or parity gains a tier 0).
