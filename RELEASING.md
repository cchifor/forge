# Releasing forge

This document describes branching, versioning, and release cadence for forge as it works toward **1.0**.

## Branch model

- **`main`** — 0.x maintenance. Backports and fixes only. Tagged `v0.x-final` at the start of 1.0 work.
- **`1.0-dev`** — 1.0 development. All breaking changes land here. Protected: PRs only, CI must pass.
- **`spike/*`** — throwaway de-risking branches. Not merged; extracted learnings land as proper PRs into `1.0-dev`.
- **Release branches** — cut from `1.0-dev` when a named alpha/beta is locked (`release/1.0.0a1`, `release/1.0.0b1`, ...).

## Versioning

We follow [Semantic Versioning 2.0](https://semver.org/). 1.0 work uses pre-release identifiers:

| Version | Meaning | Cadence |
|---|---|---|
| `0.x.y` | Current stable, maintained on `main` only | Patches as needed |
| `1.0.0a1..aN` | Alpha — feature-incomplete, breaking changes expected | Every completed phase |
| `1.0.0b1..bN` | Beta — feature-complete, no new breaking changes | Every 2 weeks |
| `1.0.0rc1..rcN` | Release candidate — frozen feature set, bugfixes only | Weekly |
| `1.0.0` | Stable 1.0 | One-time |

### When does each phase cut an alpha?

- **`1.0.0a1`** — Phase 0 complete (CLI decomposition, provenance, plugins, --plan)
- **`1.0.0a2`** — Phase 1 complete (schema-first core)
- **`1.0.0a3`** — Phase 2 complete (extensibility core)
- **`1.0.0a4`** — Phase 3 complete (agentic UI upgrade)
- **`1.0.0b1`** — Phase 4 complete (production polish) — feature freeze
- **`1.0.0`** — beta hardens; cut from the final `release/1.0.0` branch

## Release process

Each release follows the same steps:

1. **CHANGELOG.md** — move entries from `## [Unreleased]` into a dated version section. Every breaking change must have an entry under `### Breaking`.
2. **pyproject.toml** — bump `version`.
3. **Create release branch** — e.g. `git checkout -b release/1.0.0a1 1.0-dev`.
4. **Tag** — `git tag -a v1.0.0a1 -m "forge 1.0.0a1"`.
5. **Build + publish** — `uv build`, `uv publish`. For alphas, publish to TestPyPI first.
6. **GitHub release** — copy the CHANGELOG section as the release notes.
7. **Bump next dev** — on `1.0-dev`, bump version to `1.0.0a2.dev0`.

## Breaking-change policy

**Alpha phase (`1.0.0aN`):** breaking changes are allowed without deprecation cycles, but every one must:

1. Appear under `### Breaking` in CHANGELOG.md.
2. Include a migration note in `UPGRADING.md`.
3. Ship with a `forge migrate-<name>` codemod when mechanically applicable, or documented manual steps otherwise.

**Beta phase (`1.0.0bN`):** no new breaking changes. Only bugfixes, docs, and polish.

**Post-1.0:** breaking changes require a deprecation cycle — one minor release warning, then removal in the next minor. Dropping Python versions is a major bump.

## 0.x → 1.0 migration

The `0.x-final` tag is the stable reference for pre-1.0 projects. `main` keeps accepting security fixes and critical bugfixes to `0.x-final` until `1.0.0` ships.

Users upgrading from 0.x should follow `UPGRADING.md`. The `forge migrate` umbrella command (Phase 1+ deliverable) automates the mechanical parts.

## Publishing identities

| Registry | Identity | Notes |
|---|---|---|
| PyPI | `forge` | Existing package |
| TestPyPI | `forge` | Alphas smoke-test here first |
| npm | `@forge/*` (proposed) | canvas-vue, canvas-svelte — see RFC-003 |
| pub.dev | `forge_canvas` (proposed) | See RFC-003 |

Ownership and scope registration is tracked in RFC-003.

## Emergency releases

For security fixes on the stable branch (`main`, 0.x):

1. Branch from `main`: `fix/security-<CVE>`.
2. Fix, add a regression test.
3. Cut a patch release `0.x.(y+1)`.
4. Publish to PyPI.
5. Post-mortem documented under `docs/security-advisories/`.
