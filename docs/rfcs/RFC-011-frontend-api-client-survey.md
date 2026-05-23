# RFC-011 — Frontend API client survey

| Field | Value |
| --- | --- |
| Status | Accepted (1.2.0) |
| Author | Architecture review 2026-04 |
| Epic | 1.2.0 |
| Supersedes | — |
| Replaces | — |

## Summary

Audit how forge's three frontend templates consume the backend's
OpenAPI specification, and recommend whether to converge them.

## Current state

| Frontend | Generator | Output shape | State / cache layer |
| --- | --- | --- | --- |
| Vue 3 | `@hey-api/openapi-ts` | TS modules per tag in `src/api/generated/` | TanStack Query (Vue Query) |
| Svelte 5 | `@hey-api/openapi-ts` | TS modules per tag in `src/lib/api/generated/` | TanStack Query (Svelte Query) |
| Flutter | Retrofit codegen via `swagger_parser` + `build_runner` | Dart classes per tag in `lib/src/api/generated/<tag>/<tag>_client.dart` | Riverpod providers, no shared cache layer |

Vue and Svelte share an OpenAPI-TS pipeline and a TanStack-Query
state idiom. Flutter is the outlier: a different code generator
(Retrofit), a different state primitive (Riverpod providers, no
client-side cache), and a per-feature folder organization that
neither Vue nor Svelte mirror.

## Why convergence might be worth it

1. **Cross-project reasoning.** A developer maintaining both a Vue
   and a Flutter app today must learn two API client idioms. One
   shared mental model would reduce that cost.
2. **Feature parity in fragments.** A fragment that ships a frontend
   addition (e.g., a "live updates" hook) currently writes three
   different integrations because the state primitive differs.
3. **Streaming + pagination ergonomics.** Vue/Svelte get
   TanStack-Query's `infiniteQuery`, `mutate`, optimistic-update
   helpers automatically; the Flutter side doesn't.
4. **OpenAPI fidelity.** `@hey-api/openapi-ts` actively tracks the
   modern OpenAPI 3.1 spec (`oneOf`, discriminated unions); Retrofit
   for Dart is older and lossy on those constructs.

## Why convergence might be a bad idea

1. **Riverpod ≠ TanStack Query.** Flutter's idiomatic state
   management (Riverpod) already provides reactive caching, family
   providers, and dependency-injection-style overrides. Bolting a
   TanStack-Query-equivalent on top would duplicate primitives Flutter
   developers already use.
2. **Dart codegen for OpenAPI is less mature.** `openapi-generator`
   for Dart works but produces verbose code; community-favoured
   Retrofit feels more native. Migrating away increases generated
   code volume noticeably.
3. **Frontend audiences differ.** Mobile apps tend to want offline
   caching, conflict resolution, and persistence — concerns
   TanStack-Query doesn't address. A Flutter-specific layer is
   probably necessary regardless.
4. **One-time cost vs. ongoing benefit.** The convergence work is
   substantial (regenerate Flutter clients, rewrite Riverpod
   providers, retrain authors); the ongoing benefit is mainly
   "matching idiom across web + mobile." That benefit accrues mostly
   to teams that ship both.

## Survey recommendation

**Stop short of full convergence; close two specific gaps instead.**

1. **Adopt the RFC-007 error envelope handling consistently.**
   Vue/Svelte already get the envelope through TanStack-Query
   intercept hooks; Flutter's error_interceptor.dart should parse
   the same envelope shape (`error.code`, `error.context`,
   `error.correlation_id`) so cross-platform error UIs can branch on
   `code` uniformly. Concrete change: extend
   `src/api/client/error_interceptor.dart` to surface the structured
   fields rather than collapsing to `DioException.message`.

2. **Document the "frontend extension fragment" contract** so
   fragments adding a UI feature know to ship three siblings: a Vue
   composable, a Svelte hook, and a Flutter Riverpod provider — each
   wrapping its native state primitive over the same generated client
   call. Today the asymmetry is undocumented and fragment authors
   discover it only when their frontend addition fails on Flutter.
   Concrete change: a new section in
   `docs/plugin-development.md` titled "Frontend extensions" with a
   minimal three-frontend example.

The first reduces a real friction (RFC-007 alignment) without
reorganizing the toolchain. The second normalizes expectations
without forcing a tooling migration.

## Decision deferred

A full convergence (Flutter -> OpenAPI-TS-style + TanStack-Query-
equivalent state) should be revisited only if **two** of the
following become true:

- Forge ships a fragment whose Flutter integration is materially more
  expensive to write than its Vue/Svelte equivalent for non-stylistic
  reasons.
- A maintainer team forms with both web and mobile expertise willing
  to own the migration.
- A Dart-side TanStack-Query equivalent reaches the maturity of the
  TS one (today: not the case).

Until then, the asymmetry is a *cost we tolerate*, not a *bug to fix*.

## Acceptance

This RFC is accepted for the 1.2.0 cycle with the survey recommendation
adopted verbatim: **"close two specific gaps, do not pursue full
convergence"** — the Vue/Svelte (`@hey-api/openapi-ts` + TanStack Query)
vs Flutter (Retrofit + Riverpod) asymmetry costs less to tolerate than to
fix. `orval` / `riverpod_query` migration is explicitly classified as
gold-plating and is out of scope.

The two gaps closed under this acceptance are:

1. **Gap 1 — Flutter error envelope parsing.** Extend
   `forge/templates/apps/flutter-frontend-template/{{project_slug}}/lib/src/api/client/error_interceptor.dart`
   to parse the RFC-007 error envelope
   (`{error: {code, message, type, context, correlation_id}}`) into a
   typed `AppException` with structured fields instead of collapsing to
   `DioException.message`. Falls back to today's behavior when the
   response body does not match the envelope shape.

2. **Gap 2 — Three-frontend CI lint.** Add `tests/test_three_frontend_coverage.py`
   walking all fragments under `forge/features/*/templates/*/`. Any
   fragment shipping a Vue composable (`.vue` file or a composable `.ts`
   under a `vue/` directory) must have a sibling Svelte AND Flutter
   implementation, or carry an explicit `Fragment.frontend_skip_reason`
   marker (introduced in this cycle on `forge/fragments/_spec.py`). This
   keeps RFC-011's tolerated asymmetry from silently growing into a
   per-fragment Vue-only drift.

Full convergence remains deferred per the "Decision deferred" section
above. Revisit only when two of the three listed triggers fire.

See the forge improvement plan at
`/home/c4/.claude/plans/deep-gliding-mccarthy.md`, section
"RFC-011 frontend API client decision" (1.2.0 cycle), for the broader
rationale.
