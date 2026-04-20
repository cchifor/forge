# RFC-003: Published-package naming and ownership

- Status: Draft
- Author: forge team
- Created: 2026-04-20
- Updated: 2026-04-20
- Target: 1.0.0a4 (when canvas packages first publish)

## Summary

Reserve npm, pub.dev, and PyPI identities for the packages forge 1.0 will publish externally: `@forge/canvas-vue`, `@forge/canvas-svelte`, `forge_canvas` (Dart), and a `forge-plugin-*` PyPI namespace convention for third-party plugins. This RFC is Draft pending decisions about GitHub org ownership and scope reservation.

## Motivation

Phase 3.1 extracts canvas components into published packages so generated projects depend on them rather than copying them in. Publishing requires:

- Registered scope/org on each registry
- Consistent naming across registries
- A governance story for who can publish
- A convention for third-party plugins to avoid namespace collisions

Reserving names before code is written prevents squatting and ambiguity.

## Design

### Proposed names

| Kind | Registry | Name | Owner |
|---|---|---|---|
| Vue canvas lib | npm | `@forge/canvas-vue` | GitHub org `forge-project` (TBD) |
| Svelte canvas lib | npm | `@forge/canvas-svelte` | same |
| Flutter/Dart canvas lib | pub.dev | `forge_canvas` | verified publisher `forge-project.dev` (TBD) |
| CLI | PyPI | `forge` | existing — already registered |
| Plugin convention | PyPI | `forge-plugin-<name>` | community, unreserved |
| Reference plugin | PyPI | `forge-plugin-example` | forge-project |

### GitHub org vs personal-owned

Two options:

**Option A — Create a GitHub org (`forge-project`).** npm scope `@forge` owned by the org. pub.dev verified publisher tied to a domain the org controls. Benefits: long-term governance, transfer-friendly, multiple maintainers. Cost: one-time setup, domain purchase, ongoing admin.

**Option B — Keep everything personal-owned.** npm scope could be `@cchifor/forge-*`. pub.dev package as `forge_canvas` under a personal publisher. Benefits: zero setup cost. Cost: bus factor 1, harder to hand off if the project grows.

**Recommendation: Option A**, with the caveat that it's a ~$50 one-time cost (domain) and ~1 day of setup. Go with Option B only if 1.0 is explicitly framed as a solo-maintainer project with no succession plan.

### Versioning coordination

All four published packages (Python CLI + three canvas libs) version in lockstep with `forge` major versions:

- `forge 1.0.0` ↔ `@forge/canvas-vue@1.0.0` ↔ `@forge/canvas-svelte@1.0.0` ↔ `forge_canvas: 1.0.0`

Minor and patch versions can diverge — a bug in the Vue canvas can release independently as `@forge/canvas-vue@1.0.1` without touching the others. But major versions are coordinated (a new major of `forge` implies new majors for all canvas libs).

Tooling: `semantic-release` in the monorepo at `C:\Users\chifo\work\forge\`, configured to release all changed packages on every merge to `1.0-dev` or `main`.

### Plugin naming convention

Third-party forge plugins adopt the `forge-plugin-<name>` convention on PyPI:

- `forge-plugin-go-echo` — a Go/Echo backend
- `forge-plugin-rag-opensearch` — an OpenSearch adapter
- `forge-plugin-deploy-fly` — a Fly.io deployment fragment

Each plugin installs a `forge.plugins` entry point (see RFC-004 when written) and is discovered by forge at runtime.

`forge-plugin-example` is the reference implementation, published and maintained by the forge project.

### Publishing workflow

GitHub Actions at `.github/workflows/release.yml`:

- Triggered on tag push matching `v*.*.*`
- Builds all four packages
- Publishes in order: PyPI first (forge CLI), then npm (both canvas packages), then pub.dev (Flutter)
- On any failure, halts and surfaces which registry errored

Secrets required:

- `PYPI_API_TOKEN`
- `NPM_AUTH_TOKEN`
- `PUB_DEV_CREDENTIALS` (JSON blob from `flutter pub token add`)

## Alternatives considered

### `@forgelabs/*` or `@forge-kit/*` npm scope

If `@forge` is already taken on npm (needs verification), these are fallbacks. Prefer the shortest available option that reads unambiguously as "forge the project".

### Put canvas libs under the main `forge` npm package

Monorepo all the way: `forge/canvas-vue` as a path inside the `forge` npm package. Rejected because the Python CLI doesn't ship via npm, so there's no `forge` npm package to extend. A separate scope is the correct level of abstraction.

### Flutter package named `forge`

pub.dev package `forge` (short). Rejected — `forge_canvas` signals the specific responsibility; a future `forge_core` Dart package could complement it without overloading a single name.

## Drawbacks

- GitHub org setup is one-time toil.
- Domain ownership adds an ongoing (~$15/year) cost.
- Lockstep major versioning across four packages creates coordination overhead for each major bump — even when one of them had no breaking changes.

Mitigation: minor/patch versions decouple, so lockstep only binds at majors, which are rare.

## Open questions

- **GitHub org name availability.** Is `forge-project`, `forgetools`, or similar free on GitHub? Needs verification.
- **npm `@forge` scope availability.** Must check before committing to this name.
- **pub.dev verified-publisher domain.** Does the project need a dedicated domain, or can it piggyback on an existing one?
- **Solo-maintainer fallback.** If Option A (GitHub org) is too much ceremony for the current team size, is Option B (personal-owned) acceptable as a starting point with plans to migrate to an org later?
