# Generated application quality implementation

Base: 387a22b23ee0540b23cbb31d678becc3839dcd05.

Requested scope: remove Claude attribution; repair important implementation
issues; protect generic generated code across upgrades; enforce greater than
80% changed-code coverage across unit/integration/E2E; distribute a shared
Claude/Codex skill and capability-aware technology recommendations.

Implementation sequence:

1. Repair dependency locks, generated CI, test discovery, required codegen errors.
2. Prevent attribution and prepare a tree-verified historical rewrite.
3. Add explicit ownership, regeneration and dependency gates, safe updates.
4. Add native coverage collection, strict report validation and changed-line gates.
5. Add shared agent skill and deterministic capability recommendations.
6. Validate generated projects and existing tests, document migration, create PR.

Historical rewrite publication changes commit identities and remains a separate
maintenance operation; its verified mirror and mapping must exist first.

## Implemented

- Frozen root installs and dependency locks; generated CI matrices use actual
  service paths. Required built-in and plugin codegen errors fail generation.
  Python formatting precedes provenance and preserves fragment sentinels.
- Claude attribution settings, new-commit CI policy and a verified history
  cleanup command. The repository's contributor API currently lists the two
  human accounts, Dependabot and GitHub Actions; Claude is absent there already.
- Portable generation recipes; generated/scaffold/user ownership; independent
  regeneration and static dependency/mutation checks; transactional updates,
  conflict proposals, headless resolution and a legacy migration report.
- Native unit/integration/E2E execution, strict source-hashed report validation,
  changed-line coverage greater than 80% per application/shared package, and
  the stable `generated-quality` workflow status.
- Shared Claude/Codex skill and capability-constrained technology recommendations.
  Python has an explicit application-provider composition hook. Node pool settings
  now configure Prisma, and Rust internal errors are redacted in public responses.

## Validation (2026-10-08)

Focused acceptance tests cover native execution, provenance, upgrades and
recommendations. Packaging and documentation checks pass. The full `make check`
regression before the final Windows encoding fix passed 5,110 tests (39 skipped),
with 85.62% overall coverage; the PR records subsequent focused and CI results.
Six generation snapshots were deliberately refreshed and verified. Root lint,
format and type checks pass; native Rust formatting/Clippy and Node/Python build
checks pass. The Node reference runtime dependency audit reports no vulnerabilities
after the patched Prisma transitive dependency override.

Fresh generated backend validation used real native coverage reports, PostgreSQL
for Node/Rust integration tests, SQLite for Python integration tests, and actual
listening services for E2E tests:

| Target | Unit / integration / E2E tests | Combined executable-line coverage |
| --- | --- | --- |
| Python application | 351 / 4 / 1 | 1214 / 1407 = 86.28% |
| Python shared SDK | Measured independently from consumer suites | 1109 / 1198 = 92.57% |
| Node application | 37 / 18 / 1 | 232 / 284 = 81.69% |
| Rust application | 5 / 4 / 3 | 659 / 762 = 86.48% |
| Vue frontend | 160 / 7 / 2 | 1045 / 1280 = 81.64% |
| Svelte frontend | 100 / 2 / 2 | 648 / 779 = 83.18% |

The generated applications pass independent architecture/regeneration checks.
Real cargo-llvm-cov execution also confirmed that local path-dependency coverage
is retained for the shared-package gate. Three authentication SDK Rust contract
tests and six Helm/kubeconform deployment checks pass.

Browser coverage exercises real Chromium navigation, responsive layouts and
generated CRUD against stateful HTTP fixtures. Regression tests exposed and
fixed missing Svelte backend routing/navigation, dropped Vue mutation bodies on
session retry, and confirmation cancellation races. Fresh Node 22 installs pass
with the Vitest peer override; the locked Python dependency audit is clean.
The stateless Python variant passes native lint, type and unit checks.
The wheel includes the TypeScript injector helper, and a packaging regression
test verifies that installed and checkout generator fingerprints match. The
tenant-service lifecycle accepts custom providers and uses string trust-map keys.
Rust authentication middleware passes Clippy on Rust 1.99.
Quality files and subprocess output explicitly use UTF-8. Coverage uses Git's
NUL-delimited filenames so accented or quoted paths cannot escape changed-line
checks. The required policy lane runs on both Linux and Windows, with a local
regression fixture that simulates a legacy Windows default encoding.

## Rollout limits and remaining maintenance

- Flutter adapter execution is covered by runner contract tests, but this worker
  has no Flutter SDK/device. Its emitted workflow installs Flutter and desktop
  dependencies; native Flutter validation remains necessary before rollout.
- Authentication and other optional feature combinations can need dedicated
  issuer/service fixtures. Default backend validation is not a claim that every
  option combination passes the new threshold.
- Historical cleanup is prepared, not published. The verified mirror and full
  backup are outside the worktree at
  `/workspace/c4/forge-maintenance/attribution-verified-2026-10-07/`.
  All 1,443 commit trees and human identities/dates were verified; 1,383 commit
  IDs change. Main maps from `387a22b23ee0540b23cbb31d678becc3839dcd05` to
  `b0e8d3cd4f0f83b0de81b773efe1346496963ae0`, with an unchanged tree. Publishing
  this rewrite remains a separate, coordinated maintenance operation.
- Main now requires the successful `generated-quality` GitHub Actions status,
  with strict branch checks and administrator enforcement. Generated downstream
  repositories must configure protection themselves; recipe and workflow
  upgrades should receive owner review.
