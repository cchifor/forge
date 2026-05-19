# Plan - Improve `cchifor/forge` CI Health

## Codex Review

- The phased split is sound: P0 is correctly scoped to getting `main` green, while P1-P3 separate nightly correctness, workflow hardening, and resilience.
- P0 is mostly actionable, but the sidecar failure diagnosis names the wrong payload and risks changing conflict content instead of fixing Windows newline translation.
- P1 needs re-checking against the current worktree: the Prisma artefact filter and origin-aware Lane E resolver path already exist outside the files the plan highlights.
- P2 has useful hardening goals, but the action-pinning and concurrency scopes leave gaps that should be explicit before implementation.
- P3 should reuse existing scenario validation and guard the artifact download path itself, not only the dashboard-rendering Python.

<!-- codex-review-status: complete -->

## Context

`main` is currently red. CI #192 (the post-merge commit of PR #58 onto `main`,
SHA f69bcc0, 2026-05-19) fails on three jobs: `lint`, `test (windows-latest,
3.13)`, and `coverage`. Independent of that, the scheduled `Matrix nightly`
workflow has now failed **17 consecutive times on `main`** (every run for ~10
days), and several workflow files have fragility smells (no concurrency on
release, floating action versions, missing `PYTHONIOENCODING` on Windows).

Recent merges to `main` (PRs #45, #47, #53, #58) each fixed a slice of
"pre-existing matrix CI bugs" but landed lint/Windows/coverage regressions of
their own. We need a structured pass that (a) gets `main` green, (b) gets the
nightly matrix green, and (c) hardens the workflows so the next batch of
fixes doesn't reintroduce the same class of failure.

The user explicitly asked for Codex-reviewed planning and Codex-reviewed PRs,
so this plan is executed through the `codex-reviewed-planning` skill (this
file → repo `plans/` → codex review → iterate → finalize) and each
implementation PR is reviewed by a Codex subagent before merge.

## Approach

Four phased PRs, each scoped to a single root-cause cluster, each
independently reviewable and revertible. Land in the order P0 → P1 → P2 → P3.
P0 is the only one that blocks `main`; the rest can land sequentially over
the next few days.

### P0 - Unblock `main` CI (one PR, four small commits)

Four pre-existing bugs landed on `main` with PR #58. Each is isolated and
has an obvious fix:

1. **Ruff `I001` / `F401` in three files.**
   The first-merged file under `forge/sync/forge_to_project/resolver/`
   subpackage has an unsorted import block, and `_open_editor` is re-imported
   at package level for test monkeypatching but not in `__all__`, so ruff
   flags it `F401`.

   *Fix:* run `uv run ruff check --fix forge/` to auto-resort imports; for
   the `_open_editor` re-export, add it to an `__all__` tuple (or `# noqa:
   F401` with the existing explanatory comment on lines 80-84 of
   `forge/sync/forge_to_project/resolver/__init__.py`). Same treatment for
   `_sidecar_parser.py` and `updater/__init__.py`.
   <!-- codex: `ruff check --fix forge/` is broader than the three failing files and can create unrelated churn in P0. Prefer targeting the affected files first, or inspect the diff carefully before committing. -->

2. **Windows UTF-8 import failure in `test_event_union_codegen.py`.**
   The test writes generated Pydantic code to a tmp file via
   `write_text(emit_pydantic(...))` (lines 222-224 of
   `tests/test_event_union_codegen.py`) **without** `encoding="utf-8"`. On
   Windows `write_text` defaults to the locale encoding (cp1252), which
   encodes the banner's `—` (U+2014) as byte `0x97`. Python then imports
   that file using PEP 263's UTF-8 default and the parser explodes on
   `0x97`. The production emitter at `forge/codegen/event_union.py:360`
   already writes with `encoding="utf-8"`; this is a test-only bug.

   *Fix:* add `encoding="utf-8"` to the three `write_text` calls in the
   test. Two-line change.

3. **Conflict-marker sidecar whitespace assertion.**
   `tests/test_apply_bundle_files_structural.py::test_conflict_writes_user_text_and_emits_sidecar`
   asserts `user_body in sidecar_content`. On Windows the written sidecar
   has extra blank lines between body lines (line-ending normalization
   diff). The sidecar writer is in `forge/sync/merge.py` (or possibly
   `forge/sync/forge_to_project/template_update.py` - verify via the test's
   import). Both are in the candidate list.
   <!-- codex: Verified current test code asserts `upstream_body in sidecar_content`, not `user_body`. The exercised path is `forge/sync/project_to_forge/apply_bundle/_files_structural.py` calling `forge.sync.merge.write_file_sidecar`, not `template_update.py`. -->

   *Fix:* either (a) collapse repeated blank lines when emitting the user
   body block in the sidecar writer, or (b) normalize newlines in the body
   before the `in`-assertion in the test. (a) is the correct fix because
   the goal is byte-identical sidecars across OSes; (b) only papers over
   it. Go with (a) and add a `newline="\n"` parameter to the sidecar
   `write_text` call to prevent CRLF expansion on Windows.
   <!-- codex: Avoid collapsing blank lines because the sidecar must preserve the upstream payload. The likely Windows bug is text-mode translation of an already-CRLF payload into `\r\r\n`; use `newline="\n"` in the relevant sidecar writer(s) and add a CRLF regression. -->

4. **Coverage floor key references a moved module.**
   `tests/test_coverage_gates.py:72` gates
   `forge/sync/forge_to_project/updater.py`, but PR #58 turned `updater`
   into a package (`updater/__init__.py`). coverage.py reports the new path,
   so the gate sees no data for the old key and fails.

   *Fix:* update the `MODULE_FLOORS` key to
   `forge/sync/forge_to_project/updater/__init__.py` AND the corresponding
   row in `docs/coverage-policy.md` (the docs↔gate sync test
   `test_docs_table_stays_in_sync` will otherwise fail). The same comment
   block at lines 58-67 of `test_coverage_gates.py` already documents the
   relocation; just update the path.

### P1 - Stabilize the Matrix nightly (one PR)

Two issues, both nightly-only (no `main` impact):

1. **Prisma generated-client non-determinism.** The roundtrip lane diffs
   `project_a` against `project_b` after `forge update` and trips on
   `services/api/node_modules/.prisma/client/edge.js`, which Prisma's code
   generator emits non-deterministically across runs. Six of ~20 nightly
   lanes hit this.

   *Fix:* extend the shared artefact-filter helper introduced by Cluster B
   (`tests/matrix/runner.py` per the recent commit `778389a`) to exclude
   `**/node_modules/**` from roundtrip diffs. `node_modules` is regenerated
   artefacts, not source - diffing it has never been meaningful.
   Verify by listing existing filter patterns in the helper and adding
   `node_modules/**` + `**/.prisma/**` to the deny-list.
   <!-- codex: In this worktree, `tests/_artefact_filters.py` already excludes `node_modules/`, and `tests/matrix/test_runner_diagnostics.py` explicitly covers `services/api/node_modules/.prisma/client/edge.js`. If CI still reports this path, reproduce first; the bug is likely a stale main run or a different diff path, not a missing pattern in `runner.py`. -->

2. **Lane E pre-existing resolver bug for Node-only / Rust-only scenarios.**
   `matrix-nightly.yml` lines 107-110 + `tests/matrix/scenarios.yaml`
   lines 13-17 both document the symptom: the Python-only
   `correlation_id` middleware fragment is persisted into `forge.toml`
   during generation, even when the project has no Python backend. On
   `forge --update` the resolver re-applies the fragment, which fails
   because no Python service exists to inject into.

   *Fix:* the bug is in the fragment-persistence path between
   `forge/middleware_spec.py` and `forge/features/middleware/fragments.py`
   (the `correlation_id` definition at `fragments.py:32` is keyed to
   python only; somewhere downstream it's being written to `forge.toml`
   without filtering by present-backends). Trace the writer that emits
   the `[forge.option_origins]` / fragment manifest table (most likely in
   `forge/sync/manifest.py` - `persisted` keyword appears at lines 10,
   57, 81, 85, 195, 349), and add a `if fragment.lang not in
   project.backend_langs: skip` guard at the persistence point. Then opt
   `node_only_headless`, `rust_only_headless`, and any other non-Python
   scenarios into `lanes: [..., update]` in
   `tests/matrix/scenarios.yaml`.
   <!-- codex: Current code already has origin-aware default skipping in `generator.py`, `forge/sync/forge_to_project/updater/__init__.py`, and `forge/capability_resolver.py`, with regression tests in `tests/test_updater.py` and `tests/test_capability_resolver.py`. `manifest.py` only serializes tables and `Fragment` has no `lang` attribute, so a manifest-level backend guard is likely the wrong layer. -->
   <!-- codex: "Any other non-Python scenarios" can turn P1 into a broad nightly expansion and surface unrelated toolchain/template failures. Name the exact scenarios for this PR, then broaden separately if that is still desired. -->

   This sub-step has uncertain depth - if the fix balloons past ~1 day
   of investigation, fall back to gating per the original deferred-fix
   plan and file a follow-up issue. Decision point: if the writer is in
   `forge/sync/manifest.py` it's likely small; if the persistence
   actually happens during `forge/options/layers.py` resolution it's
   bigger.

### P2 - Workflow hardening (one PR, multiple `.github/workflows/*.yml`)

Pure CI-config changes; no Python code touched.

1. **Add `PYTHONIOENCODING=utf-8` env to `ci.yml` `test` job.** Belt-and-
   braces in case more test code emits non-ASCII via stdout/stderr and the
   xdist worker dies decoding it. One-line addition to the job env at
   `ci.yml:62`-ish.

2. **Add `concurrency:` to three workflows.** `release.yml` (tag pushes -
   races publish artefacts), `mutmut.yml` (scheduled - clobbers check-run
   writes), `ty-upgrade.yml` (scheduled monthly - could race a
   manual-dispatch run). Use `group: ${{ github.workflow }}-${{ github.ref
   }}`; `cancel-in-progress: false` for `release.yml` (never cancel a
   release mid-flight), `true` for the schedulers.
   <!-- codex: `group: ${{ github.workflow }}-${{ github.ref }}` does not serialize two different release tags, so it may not prevent cross-version publish races. If releases must be globally serialized, use a release workflow-level group that omits `github.ref`. -->

3. **Pin floating action versions to SHAs** in `e2e.yml`, `plugin-e2e.yml`,
   `release.yml`, `release-dryrun.yml`, `ty-upgrade.yml`. `ci.yml` and
   `matrix-nightly.yml` already do this - match those SHAs to keep things
   consistent. Floating `@v4` tags are a supply-chain risk and a
   stealth-breaking-change vector.
   <!-- codex: `mutmut.yml` also has floating checkout/setup-uv/upload/download actions but is not in this pinning list; `e2e.yml` and release workflows also leave non-`@v4` third-party actions floating. Either pin all Actions dependencies or document the intentional exclusions. -->
   <!-- codex: Copying `ci.yml`'s `astral-sh/setup-uv` SHA would pin workflows currently using setup-uv `@v4` to the older `v3.2.4` SHA. Verify input/cache compatibility or pin the current major intentionally. -->

4. **Add `timeout-minutes:`** to `e2e-core` (`e2e.yml`), `plugin-e2e`
   (`plugin-e2e.yml`), and `probe` (`ty-upgrade.yml`). All three currently
   default to 6 hours. Pick something proportional (45 / 20 / 15).
   <!-- codex: In this worktree, `e2e-core` already has `timeout-minutes: 15`, so it is not defaulting to six hours. The missing timeout here is `plugin-e2e`, plus `ty-upgrade`'s `probe`; decide explicitly whether release jobs remain out of scope. -->

### P3 - Resilience polish (one PR, smallest)

1. **`ty-upgrade.yml:48` PyPI fetch.** Wrap the `urlopen('https://pypi.org/
   pypi/ty/json')` call with a 10 s timeout and a try/except that falls
   back to logging + exit-0. The workflow runs first-Monday-of-the-month;
   if PyPI is briefly down we should not page anyone.
   <!-- codex: If the fetch fallback exits 0 without setting `steps.target.outputs.version`, later steps may treat an empty version as a real bump target. Set the output to the current pin, gate subsequent steps, or stop the job before mutation. -->

2. **scenarios.yaml schema validation.** Add a quick check step (jq or a
   tiny Python script) to `gate` in `matrix-nightly.yml:82` and
   `matrix-setup` in `ci.yml:182` so a malformed YAML fails the gate
   cleanly with a useful message rather than burying the error inside a
   Python heredoc.
   <!-- codex: `tests/matrix/runner.py::load_scenarios` and `tests/matrix/test_scenarios_schema.py` already provide richer validation than a new jq check. Reuse that path in workflows to avoid a second schema definition drifting. -->

3. **Empty-artifact guard in `publish-dashboard`.** `matrix-nightly.yml:345
   -353` happily emits an empty dashboard markdown if all lanes are
   cancelled. Detect zero artefacts and emit an explicit
   "no lanes ran" message instead. Keeps the nightly status comment
   honest.
   <!-- codex: Guard the `actions/download-artifact` step as well as the Python renderer; if no `matrix-status-*` artifacts match, the action can fail before `matrix-status-raw` exists. Use `continue-on-error` or an explicit post-download existence check. -->

## Codex review workflow

The user asked for Codex review of both the plan and the implementation
PRs.

**Plan review** (via the `codex-reviewed-planning` skill, after this plan
is approved and ExitPlanMode is called):

1. Copy this plan from `~/.claude/plans/.` to `<repo>/plans/2026-05-19-forge-ci-health-plan.md`.
2. Commit on the current feature branch (`worktree-fix-matrix-ci-pre-existing-bugs`).
3. Dispatch `Agent(subagent_type="codex", prompt="profile=plan-review .")` with the prompt template in the skill body.
4. Codex emits the reviewed file as its final message; we write it back, commit `codex: review round 1`.
5. Classify each `<!-- codex: . -->` marker as ACCEPT / PUSHBACK / ESCALATE; commit `opus: address codex review round 1`.
6. If pushback markers remain and round < 2, iterate once more. Hard cap at 2 rounds.
7. Finalize, then start implementation.

**Per-PR review** (after each phase PR is opened):

For each of P0-P3, after pushing the PR branch and opening the PR:

1. `Agent(subagent_type="codex", prompt="Review the diff of PR #N for cchifor/forge. Look for: regressions in non-Windows behaviour, missed edge cases in the lint fix, sidecar normalisation, coverage gate update; for the workflow PRs, breaking changes in CI semantics. Output ACCEPT / REQUEST CHANGES with concrete bullets. Read-only.")`.
2. Apply any requested changes; force-push to the PR branch.
3. Re-dispatch Codex if changes were substantive. Same 2-round cap.
4. Merge when both Codex and CI are green.

## Critical files

P0 (unblock main):

- `forge/sync/forge_to_project/resolver/__init__.py` - lint (I001, F401)
- `forge/sync/forge_to_project/resolver/_sidecar_parser.py` - lint (I001)
- `forge/sync/forge_to_project/updater/__init__.py` - lint (I001)
- `tests/test_event_union_codegen.py` - add `encoding="utf-8"` to three `write_text` calls at lines 222-224
- `forge/sync/merge.py` or `forge/sync/forge_to_project/template_update.py` - sidecar whitespace + `newline="\n"` (verify which one the failing test exercises)
- `tests/test_coverage_gates.py:72` - update MODULE_FLOORS key to `forge/sync/forge_to_project/updater/__init__.py`
- `docs/coverage-policy.md` - corresponding row update

P1 (matrix nightly):

- `tests/matrix/runner.py` - add `node_modules/**` and `.prisma/**` to artefact filter
- `forge/sync/manifest.py` (primary candidate) - add `lang ∉ project.backend_langs` guard at the fragment-persistence point; check `persisted` references at lines 10, 57, 81, 85, 195, 349
- `forge/features/middleware/fragments.py` - possibly add a `langs:` attribute to the fragment spec if one doesn't exist, so the manifest writer can filter
- `forge/middleware_spec.py` - wiring between the two
- `tests/matrix/scenarios.yaml` - opt `node_only_headless` and `rust_only_headless` into `lanes: [..., update]` once the resolver bug is fixed; remove the Lane E header note
- `.github/workflows/matrix-nightly.yml` lines 107-110 - strip the documented-bug comment once fixed

P2 (hardening):

- `.github/workflows/ci.yml` - `PYTHONIOENCODING=utf-8` on test job env
- `.github/workflows/release.yml` - add `concurrency:` block + pin SHAs
- `.github/workflows/mutmut.yml` - add `concurrency:` block
- `.github/workflows/ty-upgrade.yml` - add `concurrency:` + `timeout-minutes:` + SHA pins
- `.github/workflows/e2e.yml` - pin SHAs + `timeout-minutes: 45` on `e2e-core`
- `.github/workflows/plugin-e2e.yml` - pin SHAs + `timeout-minutes: 20`
- `.github/workflows/release-dryrun.yml` - pin SHAs

P3 (resilience):

- `.github/workflows/ty-upgrade.yml:48` - timeout + try/except on `urlopen`
- `.github/workflows/matrix-nightly.yml:82` - scenarios.yaml schema check
- `.github/workflows/ci.yml:182` - scenarios.yaml schema check (or share via composite action)
- `.github/workflows/matrix-nightly.yml:345-353` - empty-artefact guard in `publish-dashboard`

## Reuse / don't reinvent

- The artefact-filter helper added in commit `778389a` (Cluster B) already
  exists in `tests/matrix/runner.py`. Extend it; don't introduce a parallel
  filter.
- `ci.yml` and `matrix-nightly.yml` already pin actions by SHA - copy the
  SHAs from there into the other workflow files. Don't pick new SHAs.
- `_load_per_file_coverage` in `tests/test_coverage_gates.py:83` already
  normalises Windows backslashes to POSIX. Don't add a second normaliser
  when fixing the path key.

## Verification

After each phase merges to `main`, the corresponding workflow(s) should be
green on the next push. Specific commands to run locally before each PR:

**P0:**

```powershell
# Lint
uv run ruff check forge/

# Coverage gate (the test that was failing)
uv run pytest -m "not e2e" --cov --cov-report=json:coverage.json
uv run pytest tests/test_coverage_gates.py -v
```
<!-- codex: The coverage command is broader than CI because it includes `package_integrity` and `fuzz`; mirror CI's marker (`not e2e and not package_integrity and not fuzz`). The gate rerun should also use `--no-cov`, matching `ci.yml`, so it consumes the existing `coverage.json` instead of starting another coverage run. -->

```powershell
# Em-dash / Unicode fix (Windows-only failure mode)
uv run pytest tests/test_event_union_codegen.py::TestEmitPydantic::test_pydantic_union_validates_at_runtime -v

# Sidecar whitespace fix
uv run pytest tests/test_apply_bundle_files_structural.py -v
```

Then push, wait for `ci` workflow to go green on PR + on `main` after merge.

**P1:**

```powershell
# Local reproduction of the Lane E resolver bug, BEFORE the fix:
# Generate a Node-only project, inspect forge.toml for the bad fragment.
uv run python -m forge new --preset node_only_headless /tmp/forge-lane-e-repro
Get-Content /tmp/forge-lane-e-repro/forge.toml | Select-String correlation_id
# Expect: should be EMPTY after the fix (no Python-only fragment persisted).

# Then drive an --update against the generated project:
uv run python -m forge --update --mode merge /tmp/forge-lane-e-repro
# Expect: exits 0 cleanly (no resolver re-resolution failure).
```
<!-- codex: The current parser has no `forge new` subcommand, no `--preset` flag, and `--update` expects `--project-path`; this reproduction will not exercise the bug. Use `uv run python tests/matrix/runner.py --scenario node_only_headless --lane update` and the rust equivalent, or generate from the scenario config through the runner. -->

```powershell
# Roundtrip determinism (Prisma exclusion):
uv run pytest tests/matrix/test_runner_diagnostics.py -v

# Full matrix dispatch:
gh workflow run "Matrix nightly (lane C smoke + lane D roundtrip + lane E update)" --repo cchifor/forge --ref main
# Once finished:
gh run list --workflow="Matrix nightly (lane C smoke + lane D roundtrip + lane E update)" --repo cchifor/forge --limit 1
```
<!-- codex: For pre-merge validation, dispatching `--ref main` will not test the PR's workflow/scenario changes. Run against the PR branch first, then repeat on `main` after merge. -->

Expect: all lanes green; publish-dashboard summary shows no `node_modules`
diffs and Lane E now runs for `node_only_headless` + `rust_only_headless`
scenarios with green outcomes.

**P2 + P3:**

- For each modified workflow, validate YAML via `actionlint .github/workflows/*.yml` (install via uv if not present; `uv tool install actionlint`).
<!-- codex: `uv tool install actionlint` is a hidden dependency risk because actionlint is not declared as a repo Python tool here. Specify a known installer or pinned binary source, and prefer adding actionlint itself to CI if workflow syntax is part of the hardening. -->
- `gh workflow run` each modified workflow manually before merging the PR; confirm green.
- For `release.yml` concurrency: cannot test without a real tag push, but actionlint catches syntactic issues.

**Cross-cutting:**

After the four PRs land, check the `gh run list --repo cchifor/forge
--status failure --limit 20` baseline. Goal: no `main`-targeting failures
in the most recent 20 runs across `CI`, `E2E`, `Matrix nightly`.