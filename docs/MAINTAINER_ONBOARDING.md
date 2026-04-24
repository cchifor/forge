# Maintainer onboarding

This guide helps a new co-maintainer reach independent merge capability
within about a week. It's written assuming the reader is a competent
Python/TypeScript/Rust engineer new to this specific codebase.

## Mental model

Forge is a **project generator**, not a framework. It composes:

1. **Templates** (`forge/templates/`) — Copier-rendered backend +
   frontend project skeletons.
2. **Fragments** (`forge/templates/_fragments/`) — optional features
   applied on top of a base template via code injection.
3. **A resolver** (`forge/capability_resolver.py`) — turns a user's
   option choices into an ordered fragment plan.
4. **An injector** (`forge/feature_injector.py`) — applies each
   fragment (copy files, inject snippets at markers, add deps).
5. **Provenance** (`forge/provenance.py`) — records who wrote each file
   so `forge --update` can merge template upgrades into user-customized
   projects.

Read these three docs before touching code:

- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — one-page dataflow.
- [`docs/rfcs/RFC-006-cross-backend-fragment-contract.md`](rfcs/RFC-006-cross-backend-fragment-contract.md) —
  parity tiers explain why features fan out to N backends.
- [`docs/coverage-policy.md`](coverage-policy.md) — the two-layer
  coverage gate you'll enforce on PRs.

## Your first week

1. **Setup** — `make install-dev` then `make check`. If both pass, your
   environment is good.
2. **Run a generation** — `uv run forge --yes --preset python-vue
   --output-dir /tmp/demo`. Read the generated project tree. Note
   `forge.toml` records provenance.
3. **Read a fragment** — pick `observability_otel/python/` and trace
   how it wires in. Note the three moving parts: `files/`,
   `inject.yaml`, `deps.yaml`.
4. **Read one RFC end-to-end** — RFC-006 is a good starting point.
5. **Review a small PR** using the [review skill](#reviewing-prs)
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
  (`feature_injector`, `merge`, `provenance`, `updater`,
  `injectors/*_ast`), confirm the `breaking-change` label is applied
  so CI runs mutation testing.
- [ ] **Template changes**: if `forge/templates/**` or `generator.py`
  changed, golden snapshots must be regenerated (`UPDATE_GOLDEN=1
  pytest tests/test_golden_snapshots.py`) and the PR description
  explicitly justifies the diff.
- [ ] **RFC impact**: if the PR changes a public contract (option
  paths, CLI flags, error codes, config schema, provenance), confirm
  the corresponding RFC is updated *in the same PR* and
  `UPGRADING.md` has a migration note.
- [ ] **Release posture**: if `CHANGELOG.md` is updated, the entry is
  under the correct Unreleased section, follows the existing `-
  feat:` / `- fix:` conventions, and links to the RFC when relevant.

Use `/review` in Claude Code to run the checklist automatically.

## Release cadence

- **Alpha → beta → stable** follows RFC-001 (versioning + branching).
- **Every release** is preceded by a dry-run rehearsal
  (`.github/workflows/release-dryrun.yml`). The 72h validity window is
  enforced by `release.yml`'s preflight gate.
- **Breaking-change policy**: see RFC-002. Any option path removal,
  CLI flag removal, or error code removal requires one full release
  cycle of deprecation warnings before the remove lands.

## Escalation

- **Production incident in a generated project**: first triage
  whether the issue is in forge's generated code (our fix) vs the
  user's customization (their fix). `forge.toml`'s provenance answers
  that — if the problem file's origin is `user`, the bug is in user
  code.
- **Security report**: respond within 48h. RFC-007 error codes for
  sensitive paths (`AUTH_REQUIRED`, `PERMISSION_DENIED`) never surface
  stack traces; audit against that promise when triaging.
- **CI outage**: `make test` is the local equivalent of the main CI
  gate; if it passes on your machine, you can merge with the
  CI-required status overridden (document why in the PR body).

## Growing into the role

Month 1: merge PRs that touch a single fragment or add a self-contained
option. Pair-review architecture-sensitive PRs.

Month 2: drive one RFC end-to-end (propose → gather feedback → land
the implementation). Run one release rehearsal.

Month 3: cut a release as the primary maintainer with oversight. Own
one section of the option catalogue (see section markers in
`forge/options.py`) — you're the default reviewer for PRs touching it.
