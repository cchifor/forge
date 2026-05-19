# Plan — Improve `cchifor/forge` CI Health

<!-- codex-review-status: finalized -->

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

   *Fix:* run `uv run ruff check --fix` against ONLY the three failing
   files to keep P0's diff minimal — `forge/sync/forge_to_project/resolver/__init__.py`,
   `forge/sync/forge_to_project/resolver/_sidecar_parser.py`, and
   `forge/sync/forge_to_project/updater/__init__.py`. For the `_open_editor`
   re-export, add it to an `__all__` tuple (or `# noqa: F401` with the
   existing explanatory comment on lines 80-84 of the resolver `__init__.py`).
   Inspect the diff before committing to confirm no unrelated changes.

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

3. **Conflict-marker sidecar CRLF translation on Windows.**
   `tests/test_apply_bundle_files_structural.py::test_conflict_writes_user_text_and_emits_sidecar`
   asserts `upstream_body in sidecar_content` (line 212). On Windows the
   sidecar's content has extra blank lines, caused by text-mode write
   translating an already-CRLF payload into `\r\r\n`. The exercised path is
   `forge/sync/project_to_forge/apply_bundle/_files_structural.py` calling
   `forge.sync.merge.write_file_sidecar` — NOT `template_update.py`.

   *Fix:* preserve the upstream payload byte-for-byte by adding
   `newline="\n"` to the `write_text` call inside `write_file_sidecar`
   (and to any matching `read_text` in the test if it's also affected).
   Do NOT collapse blank lines — the sidecar's job is to carry the
   upstream payload verbatim so a maintainer can resolve the conflict.
   Add a small CRLF regression test that asserts `\r\r\n` never appears
   in a sidecar produced from CRLF input.

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

1. **Prisma generated-client non-determinism — REPRODUCE FIRST.**
   The failing nightly (run 26076244446) reports
   `services/api/node_modules/.prisma/client/edge.js` as the first
   differing file in the roundtrip diff. However, `tests/_artefact_filters.py`
   already excludes `node_modules/`, and `tests/matrix/test_runner_diagnostics.py`
   explicitly covers this exact path. The failure may be from a stale main
   run (pre-Cluster-B) or a different diff codepath that doesn't go
   through the artefact filter.

   *Fix:* (a) reproduce the failure locally by re-running
   `python tests/matrix/runner.py --scenario node_only_headless --lane roundtrip`
   on `main` HEAD. (b) If the filter is genuinely missing the path,
   extend `tests/_artefact_filters.py` (not `tests/matrix/runner.py` —
   the filter lives in the dedicated module). (c) If the path is filtered
   but a separate diff codepath bypasses it, find that codepath via
   `grep -nR services/api/node_modules tests/matrix/` and route it through
   the existing filter. Do NOT add a parallel filter.

2. **Lane E pre-existing resolver bug for Node-only / Rust-only scenarios.**
   `matrix-nightly.yml` lines 107-110 + `tests/matrix/scenarios.yaml`
   lines 13-17 both document the symptom: the Python-only
   `correlation_id` middleware fragment is persisted into `forge.toml`
   during generation, even when the project has no Python backend. On
   `forge --update` the resolver re-applies the fragment, which fails
   because no Python service exists to inject into.

   *Fix scope correction:* manifest.py is the WRONG layer — it only
   serializes tables, and `Fragment` (`forge/fragments/_spec.py:120`) has
   no `lang` attribute; it stores per-backend impls in `implementations:
   dict[BackendLanguage, FragmentImplSpec]`. The real fix layer is the
   resolver/applier. Origin-aware default skipping ALREADY EXISTS in
   `forge/capability_resolver.py` (see `_is_user_selected` around line 303
   and the `origins.get(path, "user")` check around line 364), in
   `forge/sync/forge_to_project/updater/__init__.py`, and in
   `forge/generator.py`. Regression tests live in `tests/test_updater.py`
   and `tests/test_capability_resolver.py`.

   *Investigation, then fix:* (a) reproduce locally with
   `python tests/matrix/runner.py --scenario node_only_headless --lane update`
   to capture the actual failing call stack. (b) Determine whether the
   bug is "Python-only fragment got persisted with `origin=user`" (then
   the fix is in the option-origin assignment at generation time, NOT
   the resolver) OR "resolver applies persisted fragment without checking
   the implementation exists for present backends" (then add a
   `fragment.implementations.keys() & project.backend_langs` filter at
   the resolver call site). (c) Update the regression tests in
   `tests/test_capability_resolver.py` and/or `tests/test_updater.py`
   to cover the Node-only / Rust-only case.

   *Scope:* this PR opts in exactly two scenarios to lane E:
   `node_only_headless` and `rust_only_headless` (the two named in the
   matrix-nightly.yml comment). Other non-Python scenarios stay opted-out
   in this PR and are filed as a follow-up so unrelated
   toolchain/template failures don't expand P1's blast radius.

   *Decision point:* if reproduction shows the fix requires touching
   `forge/options/layers.py` or rewriting fragment-spec metadata (a
   `langs:` field on Fragment), fall back to gating-only and file a
   follow-up issue. Time-box the investigation to one day.

### P2 - Workflow hardening (one PR, multiple `.github/workflows/*.yml`)

Pure CI-config changes; no Python code touched.

1. **Add `PYTHONIOENCODING=utf-8` env to `ci.yml` `test` job.** Belt-and-
   braces in case more test code emits non-ASCII via stdout/stderr and the
   xdist worker dies decoding it. One-line addition to the job env at
   `ci.yml:62`-ish.

2. **Add `concurrency:` to three workflows.**
   - `release.yml` (tag pushes — races publish artefacts): use a
     **workflow-level group without `github.ref`** so two different tag
     versions globally serialize: `group: release-publish`,
     `cancel-in-progress: false`.
   - `mutmut.yml` (scheduled — clobbers check-run writes): use
     `group: ${{ github.workflow }}-${{ github.ref }}`, `cancel-in-progress: true`.
   - `ty-upgrade.yml` (scheduled monthly + manual dispatch): same
     pattern as mutmut.

3. **Pin floating action versions to SHAs** in `e2e.yml`, `plugin-e2e.yml`,
   `release.yml`, `release-dryrun.yml`, `ty-upgrade.yml`, AND `mutmut.yml`
   (also has floating checkout/setup-uv/upload/download).

   *Per-major SHA lookup, not copy from `ci.yml`:* `ci.yml`/`matrix-nightly.yml`
   pin `setup-uv@caf0cab` (v3.2.4) but `e2e.yml`/`release.yml`/`release-dryrun.yml`
   use `setup-uv@v4`. Pinning v4 workflows to the v3.2.4 SHA would
   downgrade them and may break input/cache compatibility. For each
   action+major, look up the actual SHA via
   `gh api /repos/<owner>/<repo>/git/refs/tags/v<major>` and pin to the
   current tip of that major. Add `# vX.Y.Z` trailing comment per
   convention so renovate/dependabot can read it. Apply the same per-major
   approach to all non-`@v*` third-party actions
   (`dtolnay/rust-toolchain`, `subosito/flutter-action`,
   `softprops/action-gh-release`, `peter-evans/create-pull-request`).

4. **Add `timeout-minutes:`** to `plugin-e2e` (`plugin-e2e.yml`) and
   `probe` (`ty-upgrade.yml`). `e2e.yml`'s `e2e-core` already has
   `timeout-minutes: 15` (verified at line 33); don't change it. Use
   20 / 15. Release jobs are explicitly OUT OF scope (they have implicit
   bounds via per-step actions; revisit if a stuck publish ever
   materialises).

### P3 - Resilience polish (one PR, smallest)

1. **`ty-upgrade.yml:48` PyPI fetch with safe fallback.** Wrap the
   `urlopen('https://pypi.org/pypi/ty/json')` call with a 10 s timeout
   and a try/except. On failure, set `steps.target.outputs.version` to
   the **current pinned ty version** (so downstream regex-rewrite and PR
   creation become no-ops) and `echo "::warning::PyPI unreachable, skipping
   ty bump"`. Critical: do NOT exit 0 with an empty
   `steps.target.outputs.version` — downstream `peter-evans/create-pull-request`
   would interpret empty as "bump to empty" and open a broken PR.
   Alternatively, set an `outputs.skip=true` and gate every subsequent
   step on `if: steps.target.outputs.skip != 'true'`.

2. **scenarios.yaml schema validation — reuse, don't reinvent.**
   `tests/matrix/runner.py::load_scenarios` and
   `tests/matrix/test_scenarios_schema.py` already provide richer
   validation than a jq check. Add a workflow step that invokes
   `python -c "from tests.matrix.runner import load_scenarios;
   load_scenarios()"` (or a tiny CLI wrapper) at the top of `gate` in
   `matrix-nightly.yml:82` and `matrix-setup` in `ci.yml:182`. Single
   source of truth — no second schema to drift.

3. **Empty-artifact guard in `publish-dashboard`.** Guard both:
   (a) the `actions/download-artifact` step itself — `continue-on-error:
   true` so a missing artefact pattern doesn't fail the step, OR an
   explicit `if: needs.smoke.result != 'skipped'` etc. on the dashboard
   job. (b) the Python renderer at `matrix-nightly.yml:345-353` — check
   the artefact count post-download; if zero, emit a "no lanes ran"
   markdown summary instead of an empty grid. Without (a), the action
   fails before `matrix-status-raw` is reachable.

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

- `forge/sync/forge_to_project/resolver/__init__.py` — lint (I001, F401)
- `forge/sync/forge_to_project/resolver/_sidecar_parser.py` — lint (I001)
- `forge/sync/forge_to_project/updater/__init__.py` — lint (I001)
- `tests/test_event_union_codegen.py:222-224` — add `encoding="utf-8"` to three `write_text` calls
- `forge/sync/merge.py::write_file_sidecar` — add `newline="\n"` to the sidecar `write_text` call (this is the actual writer, confirmed via the test's import path through `forge/sync/project_to_forge/apply_bundle/_files_structural.py`)
- `tests/test_apply_bundle_files_structural.py` — add a CRLF regression test (sidecar from CRLF input never contains `\r\r\n`)
- `tests/test_coverage_gates.py:72` — update MODULE_FLOORS key to `forge/sync/forge_to_project/updater/__init__.py`
- `docs/coverage-policy.md` — corresponding row update

P1 (matrix nightly):

- `tests/_artefact_filters.py` (primary, NOT `tests/matrix/runner.py`) — extend ONLY if reproduction shows the path leaks through; do not blindly add patterns
- `forge/capability_resolver.py` (primary candidate for Lane E fix) — the origin-aware `_is_user_selected` path at ~L296-364 is the most likely site; verify whether persisted-Python-only fragments are being applied without checking their `implementations.keys() & project.backend_langs`
- `forge/sync/forge_to_project/updater/__init__.py` — secondary fix site (the updater orchestrates the apply pass)
- `forge/generator.py` — also has origin-aware skipping; verify it handles the generation-time write into `forge.toml` correctly
- `tests/test_capability_resolver.py` + `tests/test_updater.py` — add Node-only and Rust-only regression tests for the Lane E bug
- `tests/matrix/scenarios.yaml` — opt `node_only_headless` and `rust_only_headless` (exactly these two) into `lanes: [..., update]`
- `.github/workflows/matrix-nightly.yml` lines 107-110 + `tests/matrix/scenarios.yaml` lines 13-17 — strip the documented-bug comments once fixed

P1 (do NOT touch): `forge/sync/manifest.py` (only serializes; `Fragment` has no `lang` attribute, so a manifest-level guard would be the wrong layer)

P2 (hardening):

- `.github/workflows/ci.yml` — `PYTHONIOENCODING=utf-8` on test job env
- `.github/workflows/release.yml` — add **workflow-level** `concurrency: release-publish` (NO `github.ref` so different tags serialise) + pin SHAs
- `.github/workflows/mutmut.yml` — add `concurrency:` + pin SHAs (also has floating actions)
- `.github/workflows/ty-upgrade.yml` — add `concurrency:` + `timeout-minutes: 15` on `probe` + pin SHAs
- `.github/workflows/e2e.yml` — pin SHAs (timeout already present on e2e-core)
- `.github/workflows/plugin-e2e.yml` — pin SHAs + `timeout-minutes: 20`
- `.github/workflows/release-dryrun.yml` — pin SHAs

P3 (resilience):

- `.github/workflows/ty-upgrade.yml:48` - timeout + try/except on `urlopen`
- `.github/workflows/matrix-nightly.yml:82` - scenarios.yaml schema check
- `.github/workflows/ci.yml:182` - scenarios.yaml schema check (or share via composite action)
- `.github/workflows/matrix-nightly.yml:345-353` - empty-artefact guard in `publish-dashboard`

## Reuse / don't reinvent

- The artefact-filter helper lives in `tests/_artefact_filters.py` (NOT
  `tests/matrix/runner.py`). It already excludes `node_modules/`. Only
  extend it if reproduction shows a path actually leaks through.
- `ci.yml` and `matrix-nightly.yml` pin `setup-uv` to v3.2.4 SHA. Other
  workflows use v4 — look up CURRENT-major SHAs via
  `gh api /repos/<owner>/<repo>/git/refs/tags/v<major>` rather than
  copying the v3.2.4 SHA across. Same for `actions/checkout`,
  `actions/setup-node`, `actions/upload-artifact`,
  `actions/download-artifact`.
- `_load_per_file_coverage` in `tests/test_coverage_gates.py:83` already
  normalises Windows backslashes to POSIX. Don't add a second normaliser
  when fixing the path key.
- `tests/matrix/runner.py::load_scenarios` and
  `tests/matrix/test_scenarios_schema.py` already validate scenarios
  schema. Workflow gate steps should call into that path rather than
  duplicating with jq.

## Verification

After each phase merges to `main`, the corresponding workflow(s) should be
green on the next push. Specific commands to run locally before each PR:

**P0:**

```powershell
# Lint: target only the three affected files
uv run ruff check forge/sync/forge_to_project/resolver/__init__.py forge/sync/forge_to_project/resolver/_sidecar_parser.py forge/sync/forge_to_project/updater/__init__.py

# Coverage gate: match CI's marker so the run shape matches CI.
# Step 1: generate coverage.json from the same marker set CI uses.
uv run pytest -m "not e2e and not package_integrity and not fuzz and not golden_snapshot" --cov --cov-report=json:coverage.json

# Step 2: re-run the gate test alone WITHOUT --cov (matches ci.yml's
# coverage job which consumes the existing coverage.json).
uv run pytest tests/test_coverage_gates.py -v --no-cov

# Em-dash / Unicode fix (Windows-only failure mode)
uv run pytest tests/test_event_union_codegen.py::TestEmitPydantic::test_pydantic_union_validates_at_runtime -v

# Sidecar CRLF regression
uv run pytest tests/test_apply_bundle_files_structural.py -v
```

Then push the PR branch (NOT direct to main), wait for the `ci` workflow
to go green on the PR before merging.

**P1:**

```powershell
# Reproduce the Lane E bug BEFORE writing the fix.
# `forge new --preset` doesn't exist; drive via the matrix runner instead.
uv run python tests/matrix/runner.py --scenario node_only_headless --lane update
# Expect (pre-fix): non-zero exit, error referencing correlation_id /
#   missing Python service.

# Same for Rust-only:
uv run python tests/matrix/runner.py --scenario rust_only_headless --lane update

# After applying the fix, re-run both — expect exit 0.

# Roundtrip determinism check (Prisma exclusion already in place; this
# guards the no-regression case):
uv run pytest tests/matrix/test_runner_diagnostics.py -v

# Full matrix dispatch — run against the PR BRANCH first, not main:
gh workflow run "Matrix nightly (lane C smoke + lane D roundtrip + lane E update)" --repo cchifor/forge --ref worktree-fix-matrix-ci-pre-existing-bugs
# Once finished:
gh run list --workflow="Matrix nightly (lane C smoke + lane D roundtrip + lane E update)" --repo cchifor/forge --limit 1
# Then after merge, re-run on `--ref main` to confirm.
```

Expect: all lanes green on the PR-branch dispatch; publish-dashboard
shows Lane E running for `node_only_headless` + `rust_only_headless`
with green outcomes; no `services/api/node_modules/.prisma/...` diffs.

**P2 + P3:**

- Install actionlint with a pinned binary instead of `uv tool install`
  (which is for Python packages — actionlint is a Go binary). Use the
  release artefact:
  `curl -sSL https://github.com/rhysd/actionlint/releases/download/v1.7.7/actionlint_1.7.7_windows_amd64.zip -o actionlint.zip`
  (or the Linux/macOS variant), unpack, and run
  `./actionlint .github/workflows/*.yml`. Even better: add an actionlint
  step to `ci.yml` itself so workflow syntax becomes a CI gate.
- `gh workflow run` each modified workflow against the PR branch
  (`--ref <pr-branch>`) before merging; confirm green.
- For `release.yml` concurrency: cannot test without a real tag push;
  rely on actionlint for syntax. The semantic check is "two simultaneous
  tag pushes are serialised", which only manifests in production.

**Cross-cutting:**

After the four PRs land, check the `gh run list --repo cchifor/forge
--status failure --limit 20` baseline. Goal: no `main`-targeting failures
in the most recent 20 runs across `CI`, `E2E`, `Matrix nightly`.