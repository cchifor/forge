# Round-trip sync — bidirectional invariants

forge's bidirectional sync moves changes in two directions:

* **Forward** (``forge --update``): re-emit fragment intent into a
  generated project. Resolver → :class:`FragmentPlan` per fragment →
  applier pipeline (files / injections / deps / env).
* **Reverse** (``forge --harvest``): extract user edits from a
  generated project as candidate fragment patches. Manifest →
  :class:`ExtractionPlan` per fragment → extractor pipeline.

The round-trip tests and nightly matrix lane exercise the invariants below.
This guide describes fragment contribution and the legacy sync machinery.
Projects with `.forge/quality.json` also enforce [file ownership and safe
updates](../operations/generated-code-quality.md); harvesting does not permit
local overrides of protected generated runtime.

## Invariants

### FR1 — fresh-generate has nothing to harvest

> Immediately after :func:`forge.generator.generate` emits a project,
> :func:`forge.sync.project_to_forge.harvest_project` MUST find zero
> ``"block"`` and zero ``"files"`` candidates.

Equivalent statement: a user who runs ``forge`` and then runs
``forge --harvest`` without touching the project sees nothing to
back-port.

The strict-zero check is scoped to ``block`` and ``files`` candidates
because the deps and env extractors legitimately surface base-template
dependencies that no fragment owns (e.g. the copier-template's own
``aiosqlite`` / ``alembic`` deps). Phase 6 will introduce a
base-template-deps allow-list so the deps/env contract can tighten to
"every candidate is attributable to a fragment".

Codified in:
* ``tests/test_harvest_invariants.py::test_fr1_fresh_generate_has_no_block_or_files_candidates_fast``
  — ``py_only_headless`` only; runs on every PR.
* ``tests/test_harvest_invariants.py::test_fr1_fresh_generate_has_no_block_or_files_candidates_e2e``
  — parametrized over ``node_vue_full`` and ``rust_svelte_min``;
  gated behind the ``e2e`` marker (nightly via matrix lane D).
* Matrix lane D — checks FR1 as the first step of every round-trip run.

### FR2 — forward-then-reverse round-trip

> Generate → user edits → harvest → apply the bundle to fragments →
> regenerate. The second generate must byte-equal the first
> generate-after-edit (LF-normalized).

This contract covers eligible, attributable fragment edits. It is not a
guarantee that arbitrary application changes or Jinja-dependent snippets can
be translated back into generator source automatically.

**Implemented for eligible literal blocks and files.** Apply-back supports
block bodies through `CandidatePatch.current_body`; the named FR2 tests run
real assertions. Interpolated snippets and scenarios without an editable block
still have the limitations described below.

Codified in:
* ``tests/test_harvest_invariants.py::test_fr2_forward_then_reverse_round_trip``
* ``tests/test_roundtrip.py::test_roundtrip_py_only_headless``

### RF1 — reverse-then-forward promotes edits to baseline

> Generate → user edits → harvest → apply-back → ``update_project``.
> After re-application, :func:`forge.sync.forge_to_project.classify_project_state`
> MUST report zero user-modified files.

The user's text became part of the fragment baseline; the manifest's
SHA now matches what's on disk. This is the contract that lets a
maintainer pull harvest patches into the fragment tree and ship a new
release with the user's improvement upstream.

**Implemented and asserted by tests.** Block apply-back promotes reviewed
changes into the upstream baseline. This does not authorize changing ownership
or accepting a protected runtime override in a recipe-managed project.

Codified in:
* ``tests/test_harvest_invariants.py::test_rf1_reverse_then_forward_promotes_edits_to_baseline``

## Where the invariants relax

* **Jinja interpolation drift.** A fragment's ``inject.yaml`` snippet
  can be a Jinja template (``{{ option_value }}`` etc). A user edit
  inside such a block can't always be safely back-ported as a
  literal — the harvester downgrades the candidate from ``safe-apply``
  to ``needs-review`` rather than auto-applying. FR2 over such blocks
  fails by design; the reviewer has to encode the right Jinja edit
  themselves.

* **Whitespace normalization.** The directory-match helper in
  :mod:`tests.test_harvest_invariants` (``_dirs_match_lf_normalized``)
  collapses CRLF→LF before comparing text files. Cross-platform CI
  (Windows + Linux) means raw byte equality is the wrong contract;
  LF-normalized equality is the one that holds.

* **Cross-version drift.** The invariants are version-pinned: a
  harvest bundle produced by forge ``X.Y.Z`` is only guaranteed to
  apply cleanly against forge ``X.Y.Z`` fragments. The bundle's
  manifest records ``forge_version`` so a maintainer accepting a
  bundle from an older forge can detect the version skew explicitly.

* **Deps / env coarser than block / files.** As noted under FR1, the
  deps and env extractors flag any divergence as ``needs-review``.
  The strict-zero FR1 contract only covers block + files candidates.

* **Block-less scenarios.** A scenario whose generated project ships
  zero eligible FORGE-sentinel blocks is round-trip-vacuous. The matrix
  runner permits this only when the scenario explicitly sets
  `expect_candidates: false`; otherwise missing candidates fail the lane.
  A permitted empty result is annotated and does not prove apply-back coverage.

## Interactive review — ``--harvest-interactive``

By default ``forge --harvest`` runs headless: every candidate the
extractor pipeline emits lands in the bundle. Passing
``--harvest-interactive`` opts into a per-candidate review loop:

```
Candidate 3 of 7
Fragment: middleware_cors  (backend: api)
File:     services/api/src/app/main.py
Kind:     block  risk: safe-apply
Diff:     +3 -1

    --- a/services/api/src/app/main.py
    +++ b/services/api/src/app/main.py
    @@ -12,1 +12,3 @@
    -log.info("starting")
    +log.info("starting up", extra={"version": __version__})

Decision: > accept / skip / view full diff / quit
```

Selecting ``accept`` keeps the candidate in the bundle; ``skip`` drops
it (and any RFC-006 cross-language suggestions derived from it);
``view full diff`` renders the untruncated unified diff and re-prompts
on the same candidate; ``quit`` aborts the harvest cleanly — no bundle
directory is materialised, and the CLI exits with code 130
(SIGINT-shaped, distinguishable from the regular ``0`` / ``11``
outcomes a CI gate may key on).

The review prompt is wired through ``harvest_project``'s
``prompt_callback`` parameter; tests substitute a deterministic stub
to drive the loop without a real TTY (see
``tests/test_harvest_interactive.py``). The flag is mutually
compatible with ``--harvest-scope`` and ``--harvest-include``: those
filter the candidate set BEFORE the prompt loop runs, so the operator
only sees candidates inside the requested scope.

## Matrix lane D — round-trip CI gate

Lane D wires the invariants into `tests/matrix/runner.py`. Its current contract:

1. Generate the scenario into `project-a`.
2. Harvest the fresh project and assert FR1 (zero block/files candidates), then
   verify that its recorded source has no day-zero drift.
3. Edit an eligible literal sentinel block, harvest it, and apply the bundle to
   an isolated Forge source sandbox.
4. Regenerate `project-b` in a subprocess using that modified sandbox and compare
   the project trees with documented normalization/exclusions for metadata and
   transient artifacts. This exercises the FR2 output contract.

An expected candidate disappearing is a failure. A scenario can explicitly set
`expect_candidates: false` to permit a block-less/vacuous round-trip result; the
report records that condition. The named FR2/RF1 invariant tests are active
assertions, not pending `xfail` placeholders.

Scenarios opt in via the ``lanes`` list in
``tests/matrix/scenarios.yaml``. Run locally with:

```
uv run python tests/matrix/runner.py --scenario py_only_headless --lane roundtrip
```

The lane is excluded from PR CI; it runs nightly via
``.github/workflows/matrix-nightly.yml``.

## See also

* :class:`forge.sync.project_to_forge.HarvestBundle` —
  in-memory bundle the harvester returns.
* :func:`forge.sync.project_to_forge.apply_bundle_to_fragments` —
  applies supported file and literal-block candidates back to the fragment tree.
* :class:`forge.extractors.CandidatePatch` — per-edit harvest output.
* :class:`forge.sync.merge.reverse_three_way_decide` /
  :class:`forge.sync.merge.reverse_file_three_way_decide` — the
  classification primitives the extractors call.
* [`docs/operations/validation-matrix.md`](../operations/validation-matrix.md) — broader nightly
  scenarios × lanes grid. Lane D's round-trip status surfaces there
  alongside lane E (``forge --update`` + ``forge --harvest`` CLI e2e),
  which exercises the same harvest substrate via the dispatcher path
  that real users hit.
