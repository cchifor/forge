# RFC-003: Published-package naming and ownership

- Status: **Superseded (2026-06-11)** — forge is distributed **GitHub-only**; no
  packages are published to any registry, so naming/ownership is moot. Retained
  as the historical record of *why* registry publishing was dropped (the PyPI
  `forge` collision and the Atlassian-owned `@forge` npm scope made publishing
  costly for no benefit given source-install via `./install`). See `RELEASING.md`.
- Author: forge team
- Created: 2026-04-20
- Updated: 2026-06-11
- Target: 1.2.0 (first public release)

## Decision (2026-06-10)

The original draft assumed `forge` was an available PyPI name and reserved an
`@forge` npm scope. Both assumptions were wrong: PyPI `forge` is an unrelated
third-party package, and the npm `@forge` scope belongs to Atlassian. The
canvas vendoring decision (generated projects flatten canvas SOURCE into their
own tree rather than depend on published packages) also removed the need to
publish the canvas libraries for generated projects to work. Accordingly:

1. **PyPI distribution name: `forge-cli`.** The installed console command stays
   `forge` (`[project.scripts] forge = "forge.cli:main"`). This is the only
   name change users see, and only when they `pip install forge-cli`.
2. **Release scope for 1.2.0: the CLI only.** The standalone canvas npm/pub.dev
   packages are NOT part of the 1.2.0 release — generated projects vendor the
   canvas source, so nothing external is required for them to build. The
   `packages/` trees remain in-repo (they are codegen targets + a future
   standalone-publish option) but their publish jobs do not run for 1.2.0.
3. **npm scope deferred.** If the standalone canvas packages are ever published,
   they need a new scope (e.g. `@forge-canvas` or a personal scope); `@forge`
   is unavailable. This decision is deferred until there is demand for the
   standalone packages.
4. **GitHub org deferred (Option B for now).** Everything stays personal-owned
   under `github.com/cchifor/forge` until a succession/governance need arises.

The sections below are the original draft, retained for context; where they
conflict with the Decision above, the Decision wins.

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
