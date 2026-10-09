# Maintainer onboarding

This guide helps a new co-maintainer reach independent merge capability
within about a week. It's written assuming the reader is a competent
Python/TypeScript/Rust engineer new to this specific codebase.

## Mental model

Forge is a **project generator**, not a framework. It composes:

1. **Templates** (`forge/templates/`) — Copier-rendered backend +
   frontend project skeletons.
2. **Fragments** (`forge/features/<ns>/templates/`) — optional features
   applied on top of a base template via code injection. Each feature
   namespace owns its options, fragments, and template trees under
   `forge/features/<ns>/`; this mirrors how third-party plugins ship
   their own features (see `docs/guides/plugins.md`).
3. **A resolver** (`forge/capability_resolver.py`) — turns a user's
   option choices into an ordered fragment plan.
4. **Appliers** (`forge/appliers/`) — apply each fragment via a
   four-phase pipeline: copy files, inject snippets at markers, add
   deps, append env vars. (Decomposed from the pre-Epic-A
   `forge/feature_injector.py`.)
5. **Provenance** (`forge/sync/provenance.py`) — records who wrote each
   file so `forge --update` can merge template upgrades into
   user-customized projects.

Read these docs before changing generation:

- [`docs/architecture/generator.md`](../architecture/generator.md) — one-page dataflow.
- [`docs/rfcs/RFC-006-cross-backend-fragment-contract.md`](../rfcs/RFC-006-cross-backend-fragment-contract.md) —
  parity tiers explain why features fan out to N backends.
- [Generator coverage](../coverage-policy.md) and [generated-code quality](../operations/generated-code-quality.md) — separate repository and application gates.
- [Agent workflow](agentic-usage.md) — the shared canonical skill for Codex and Claude.

## Your first week

1. **Setup** — `make install-dev` then `make check`. If both pass, your
   environment is good.
2. **Run a generation** — `uv run forge --project-name demo --backend-language python
   --frontend vue --yes --no-docker --output-dir /tmp/forge-onboarding`. Read the generated project tree. Note
   `forge.toml` records provenance.
3. **Read a fragment** — pick `observability_otel/python/` and trace
   how it wires in. Note the three moving parts: `files/`,
   `inject.yaml`, `deps.yaml`.
4. **Read one RFC end-to-end** — RFC-006 is a good starting point.
5. **Review a small PR** using the [review checklist](#reviewing-prs)
   below — even if you're not ready to merge, walking through the
   checklist builds fluency.

## Key invariants

Touch these only with RFC-002 change-contract review:

- **Fragment parity tier ↔ implementations** (validated at
  `Fragment.__post_init__`, see RFC-006).
- **Error envelope shape** across Python / Node / Rust (RFC-007).
- **Config loading layer order** (RFC-008).
- **Provenance record schema** (`forge.toml [forge.provenance]`).

## Reviewing PRs

Checklist for a typical PR:

- [ ] **Tests**: does `make check` pass on the PR branch?
- [ ] **Coverage**: per-module floors in `tests/test_coverage_gates.py`
  not regressed. For PRs touching mutation-scoped modules
  (`forge/appliers/*`, `forge/sync/{merge,provenance}.py`,
  `forge/injectors/*_ast.py`, `forge/sync/forge_to_project/updater/*`;
  the live list is in `pyproject.toml [tool.mutmut].paths_to_mutate`),
  inspect the scoped PR gate when relevant. The `breaking-change` label also
  triggers a broader advisory run; see [mutation testing](../operations/mutation-testing.md).
- [ ] **Template changes**: if `forge/templates/**` or `generator.py`
  changed, inspect any golden diff and test rendered applications with their
  native tools. Regenerate snapshots only for intentional output changes;
  snapshot text alone does not prove runtime behavior or coverage.
- [ ] **RFC impact**: if the PR changes a public contract (option
  paths, CLI flags, error codes, config schema, provenance), confirm
  the corresponding RFC is updated *in the same PR* and
  `UPGRADING.md` has a migration note.
- [ ] **Release posture**: if `CHANGELOG.md` is updated, the entry is
  under the correct Unreleased section, follows the existing `-
  feat:` / `- fix:` conventions, and links to the RFC when relevant.

Agents should load the [shared forge-platform skill](../../forge/templates/_common/skills/forge-platform/SKILL.md) and report evidence for this checklist. A skill does not replace code review or required checks.

## Release cadence

- **Alpha → beta → stable** follows RFC-001 (versioning + branching).
- **Distribution is GitHub-only** — no registry publishing. A `vX.Y.Z` tag
  triggers `release.yml`, which cuts a GitHub Release (built sdist+wheel,
  CycloneDX SBOM, and `[Unreleased]` changelog notes). See `RELEASING.md`.
- **Breaking-change policy**: see RFC-002. Any option path removal,
  CLI flag removal, or error code removal requires one full release
  cycle of deprecation warnings before the remove lands.

## Escalation

- **Production incident in a generated project**: first triage
  whether the issue is in forge's generated code (our fix) vs the
  application customization. Provenance identifies ownership and origin,
  not the cause: a user-owned call site can expose a generated runtime bug.
  Reproduce the behavior before assigning the fix.
- **Security report**: respond within 48h. RFC-007 error codes for
  sensitive paths (`AUTH_REQUIRED`, `PERMISSION_DENIED`) never surface
  stack traces; audit against that promise when triaging.
- **CI outage**: local tests help diagnose the failure but do not replace
  required CI, rendered-native checks, or branch protection. Restore the
  affected check and follow repository policy before merging.

## Growing into the role

Month 1: merge PRs that touch a single fragment or add a self-contained
option. Pair-review architecture-sensitive PRs.

Month 2: drive one RFC end-to-end (propose → gather feedback → land
the implementation). Run one release rehearsal.

Month 3: cut a release as the primary maintainer with oversight. Own
one section of the option catalogue (see section markers in
`forge/options/`) — you're the default reviewer for PRs touching it.
