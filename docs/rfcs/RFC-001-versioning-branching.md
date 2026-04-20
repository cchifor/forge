# RFC-001: Versioning and branching policy

- Status: Accepted
- Author: forge team
- Created: 2026-04-20
- Updated: 2026-04-20
- Target: all 1.0 work

## Summary

Codify the branch model, versioning scheme, and release cadence that will carry forge from its current 0.x state through the 1.0 clean-break release. `main` stays on 0.x for maintenance; `1.0-dev` hosts all breaking 1.0 work; alphas cut at every phase boundary.

## Motivation

The 1.0 plan introduces breaking changes across five phases (foundations, schema-first core, extensibility, agentic-UI upgrade, production polish). Without a branch policy up front:

- 0.x users have no stable reference after `main` starts accepting breaking changes.
- Contributors don't know where to target PRs.
- Alpha releases don't align with phase completions, making dogfooding informal.

This RFC resolves those ambiguities before any 1.0 code lands.

## Design

### Branch model

```
main           0.x maintenance (security + critical fixes)
  │
  ▼ v0.x-final tag cut here, before 1.0 work starts
  │
1.0-dev        All 1.0 development. Protected: PRs only, CI required
  │
  ├── spike/typespec-windows      throwaway
  ├── spike/libcst-rate-limit     throwaway
  ├── spike/provenance            throwaway
  │
  ├── release/1.0.0a1             cut at phase-0 completion
  ├── release/1.0.0a2             cut at phase-1 completion
  ├── ...
  └── release/1.0.0               cut at 1.0 GA
```

### Versioning

[SemVer 2.0](https://semver.org/) with pre-release identifiers. See `RELEASING.md` for the full table. Key points:

- `0.x.y` on `main` — patches only, no new features
- `1.0.0aN` on `1.0-dev` — alphas at each phase boundary
- `1.0.0bN` — feature freeze after Phase 4
- `1.0.0rcN` — bugfix-only RC cycle
- `1.0.0` — final release

### Release mechanics

Each alpha:

1. `CHANGELOG.md` — promote `[Unreleased]` entries to a dated `[1.0.0aN] - YYYY-MM-DD` section
2. `pyproject.toml` — bump version
3. Cut `release/1.0.0aN` branch from `1.0-dev`
4. Tag `v1.0.0aN`
5. Publish to TestPyPI first, then PyPI
6. GitHub release with CHANGELOG section as notes
7. Bump `1.0-dev` to `1.0.0a(N+1).dev0`

### 0.x maintenance

`main` accepts backports of:

- Security fixes (always)
- Critical bugfixes (crashes, data corruption, generator errors that block users)
- Dependency upgrades for CVEs

`main` rejects:

- New features (those go to `1.0-dev`)
- Non-critical bugfixes (deferred to 1.0)
- Refactors

## Alternatives considered

### Single-branch model (`main` only)

Keep doing 1.0 work on `main`, cut alphas from the same branch. Rejected because pre-1.0 users would have no stable tag to pin against mid-development, and emergency 0.x patches would require reverting 1.0 work.

### Trunk-based with feature flags

Put all 1.0 work behind flags, ship them incrementally on `main`. Rejected because the 1.0 shifts (schema-first core, ports-and-adapters) are structural — flags don't cleanly gate template restructures and generator-internal refactors.

### GitFlow with a separate `develop`

Traditional GitFlow. Rejected as heavyweight for a single-maintainer-friendly project. A simpler `main` + `1.0-dev` split achieves the same ends.

## Drawbacks

- Two active branches means two CI matrices and two sets of review burden.
- Backporting fixes from `1.0-dev` to `main` takes ongoing effort.
- Users on `main` during 1.0 development may feel "left behind" as features land on `1.0-dev`.

Mitigation: keep 0.x maintenance scope tight (security and critical fixes only), and communicate clearly that `1.0-dev` is where new work goes.

## Open questions

None at acceptance — all resolved in `RELEASING.md`.
