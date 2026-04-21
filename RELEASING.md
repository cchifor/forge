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
4. **Run the dry-run rehearsal** — see *Pre-release dry-run protocol* below. **Required** before the tag push.
5. **Tag** — `git tag -a v1.0.0a1 -m "forge 1.0.0a1"`.
6. **Push the tag** — `release.yml` triggers; its `preflight-dryrun` job consumes the check-run the rehearsal produced.
7. **GitHub release** — the workflow creates this automatically from the CHANGELOG section.
8. **Bump next dev** — on `1.0-dev`, bump version to `1.0.0a2.dev0`.

## Pre-release dry-run protocol

Every tagged release goes through a rehearsal first. The rehearsal exercises every publish path (PyPI build + metadata, forge CLI install smoke, canvas-vue npm dry-run, canvas-svelte npm dry-run, forge_canvas pub.dev dry-run, CHANGELOG extraction) without touching a live registry. On green it writes a `release-dryrun/ok` check-run on the rehearsed SHA; `release.yml`'s `preflight-dryrun` job refuses to publish unless that check-run exists and is <72h old.

### Running the rehearsal

1. **Ensure CHANGELOG is finalised** for the release version (dated section, not `[Unreleased]`). The rehearsal validates the section extraction; a stale CHANGELOG fails the `changelog-extract` job.
2. **Push the release commit** to the branch you intend to tag from.
3. **Open GitHub → Actions → "Release dry-run"** and click **Run workflow**. Leave `ref` blank to rehearse the default branch, or supply a specific SHA.
4. **Wait for all 6 jobs to go green.** Typical runtime ~8 minutes.
5. **Verify the check-run** — the final job writes `release-dryrun/ok` as a GitHub check on the commit. You'll see it in the commit's checks panel.
6. **Tag within 72h.** `release.yml` treats the check-run as expired after that.

### When a rehearsal fails

Each job's failure points at a specific class of problem:

| Failed job                | Typical cause                                                                                  |
| ------------------------- | ---------------------------------------------------------------------------------------------- |
| `build-python`            | `twine check` rejects package metadata (bad README content-type, missing classifier).          |
| `install-smoke`           | Wheel is missing template files, or `forge --list` fails due to a broken plugin/option registration. |
| `npm-canvas-vue`          | `package.json` `files:` glob misses a built artefact, or `access` is set incorrectly.          |
| `npm-canvas-svelte`       | Same shape as canvas-vue.                                                                      |
| `pub-dev-canvas-dart`     | `flutter analyze` warnings, or `pubspec.yaml` missing required fields for pub.dev publish.     |
| `changelog-extract`       | No dated `## [X.Y.Z]` section in CHANGELOG.md (still `[Unreleased]`).                          |

Fix, push a new commit, re-run the rehearsal. Tag the fixed commit — the check-run is SHA-specific.

### Escape hatch (use sparingly)

Emergency fix with no time for a rehearsal? Set the repo variable `SKIP_DRYRUN_GATE=true` in **Settings → Secrets and variables → Actions → Variables**. `preflight-dryrun` emits a warning but lets the release proceed. **Reset the variable to `false` (or delete it) after the emergency release** — variable mutations are recorded in the repo log, so a lingering `true` is easy to spot in an audit.

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
