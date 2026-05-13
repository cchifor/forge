# Round-trip sync — bidirectional invariants

forge's bidirectional sync moves changes in two directions:

* **Forward** (``forge --update``): re-emit fragment intent into a
  generated project. Resolver → :class:`FragmentPlan` per fragment →
  applier pipeline (files / injections / deps / env).
* **Reverse** (``forge --harvest``): extract user edits from a
  generated project as candidate fragment patches. Manifest →
  :class:`ExtractionPlan` per fragment → extractor pipeline.

Phase 5 of the bidirectional-sync plan codifies the load-bearing
invariants of this cycle as automated tests and adds a nightly CI
lane that exercises them end-to-end.

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

This is the user-facing guarantee: anything the user changes in a
generated project, the harvest cycle can promote into the fragment
source so a future regenerate produces the same output.

**v1 status: parked as ``xfail``.** Phase 5's
:func:`forge.sync.project_to_forge.apply_bundle_to_fragments` supports
``kind="files"`` only; rewriting ``inject.yaml`` snippets for ``block``
candidates needs ``CandidatePatch.current_body`` (Phase 6 follow-up).
FR2 passes automatically once Phase 6 wires block apply-back.

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

**v1 status: parked as ``xfail``.** Same reason as FR2 — depends on
block apply-back.

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
  zero FORGE-sentinel blocks (e.g. a Python service with no auth and
  no rate-limit fragments enabled) is round-trip-vacuous. The matrix
  lane D runner surfaces this as ``ok`` (with a vacuity note in
  ``details``) — FR1 still passes, there's just no block to exercise
  the apply-back smoke.

## Matrix lane D — round-trip CI gate

Lane D wires the invariants into ``tests/matrix/runner.py``. v1
contract for each opted-in scenario:

1. Generates into ``project-a``.
2. Harvests ``project-a``, asserts FR1 (zero block/files candidates).
   This is the only hard contract lane D enforces today.
3. If a FORGE-sentinel block is present: stage a synthetic edit,
   re-harvest, and call
   :func:`apply_bundle_to_fragments` against a tmp clone of the forge
   tree. Block candidates land as ``deferred`` (files-only v1); the
   smoke verifies the orchestration doesn't explode.
4. The full project-a vs. project-b directory diff is **parked** until
   Phase 6 introduces a generator forge-root override flag — without
   it the second ``generate()`` would read the *live* forge tree, not
   the apply-back-modified clone, and the diff would always be
   vacuously different. The placeholder for the post-Phase-6 contract
   lives in ``tests/test_harvest_invariants.py`` (FR2 / RF1, xfail).

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
  applies a bundle back to the fragment tree (Phase 5: files-only).
* :class:`forge.extractors.CandidatePatch` — per-edit harvest output.
* :class:`forge.sync.merge.reverse_three_way_decide` /
  :class:`forge.sync.merge.reverse_file_three_way_decide` — the
  classification primitives the extractors call.
