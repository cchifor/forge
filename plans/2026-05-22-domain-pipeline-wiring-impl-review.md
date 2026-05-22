# Implementation review — feat/domain-pipeline-wiring — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 12 findings; 7 ACCEPT, 2 PUSHBACK addressed via doc edits, 3 QUESTION (2 addressed via code, 1 noted)) -->

## Codex verdict

**ACCEPT** with 2 PUSHBACK addressed (CHANGELOG honesty + grep-friendly
TODO marker) and 2 QUESTIONS addressed (narrowed exception in enum
loader). 1 QUESTION noted (alembic multiple-heads needs operator docs;
deferred to RELEASING.md follow-up).

## Findings + responses

### 1. Provenance-origin workaround — metadata-only (PUSHBACK → ADDRESSED via doc fix)
**Codex's verification:** the 3 sync sites the agent named (`updater`,
`reapply_baseline`, `verify`) do NOT drop files — unknown origins coerce
to `"base-template"`. BUT the harvester at
`forge/sync/project_to_forge/harvester/_orchestrator.py:262-267` only
buckets `origin == "fragment"` and explicitly ignores base-template
rows. So the synthetic `template_name="_domain_emitter"` is currently
metadata-only — not functionally routed by harvest.

**Response:** the CHANGELOG was overstating "harvest can route". Updated
to be honest:
- Marker is **forward-compat metadata**, currently descriptive
- Full RFC-010 compliance requires coordinated read-side updates in
  `forge/sync/{forge_to_project,project_to_forge}/`
- Deferred to a follow-up PR explicitly scoped to those cross-cutting
  sync sites

Also added grep-friendly `TODO(domain-emitter-origin)` marker to the
`_DOMAIN_TEMPLATE_NAME` docstring pointing at the specific files that
need touching (extending `ProvenanceOrigin` literal + the 3 narrow
Literal casts + the harvester orchestrator's bucket logic).

### 2. Output paths (ACCEPT)
Match the `_emit_shared_enums` backend layout. Verified at file:line.

### 3. `known_enums` sourcing — broad exception swallowing (QUESTION → ADDRESSED)
**Codex's concern:** `except Exception` at `pipeline.py:462` swallows
IO/permission/runtime faults too, masking them as later
`UnknownEnumReferenceError` with misattributed root cause.

**Response:** narrowed to `except (yaml.YAMLError, ValueError, KeyError)`
— the actual failure surface for `load_enum_yaml`. IO/permission errors
now surface uncaught (they should — that's a real environmental bug,
not a malformed YAML). Added `logging.warning` for the narrow swallow
path so malformed YAMLs leave a CI trail.

### 4. Sentinel wrapping (ACCEPT)
Matches injector sentinel regex format exactly.

### 5. Alembic gating (ACCEPT)
Python backend + `database_mode != "none"`. Tests cover both gates.

### 6. Alembic revision metadata (QUESTION → noted, no code change)
**Codex's concern:** `down_revision=None` creates multiple alembic
heads in projects with existing migration chains. Operators need
manual merge/chain management.

**Response:** acknowledged. Operator-facing docs (RELEASING.md or a
new `docs/domain-entities-migrations.md`) are a follow-up. For v1 the
expectation is that operators who use RFC-010 entities take ownership
of the alembic chain (the emitter generates entity-shape, not chain
metadata). Not blocking this PR.

### 7. Generalized `_write` with `template_name` (ACCEPT)
Backwards-compat: default `template_name="_codegen"` preserves
existing behavior. Legacy `_emit_shared_enums` callers unchanged.

### 8. Backwards compat (ACCEPT)
Empty/missing `domain/` → no emit, no error. Test covers both paths.

### 9. Test coverage 17 tests / 7 classes (ACCEPT)
All key paths tested. No gaps.

### 10. Commit message (ACCEPT)
`feat(codegen): wire domain emitters into pipeline` = 49 chars ✓.

### 11. CHANGELOG overclaim (PUSHBACK → ADDRESSED)
**Codex's concern:** CHANGELOG line 34 said "harvest can route" but
that's not yet true.

**Response:** updated entry to be honest about metadata-only status
+ deferred-follow-up framing (see Finding #1).

### 12. Missing TODO marker (QUESTION → ADDRESSED)
**Codex's concern:** no grep-friendly tracking marker.

**Response:** added `TODO(domain-emitter-origin)` to the
`_DOMAIN_TEMPLATE_NAME` docstring with a file-pointer to the sync
sites that need touching.

## Convergence

12 findings — 7 ACCEPT, 2 PUSHBACK addressed (CHANGELOG honesty +
TODO marker), 2 QUESTION addressed (narrowed exception swallowing),
1 QUESTION noted (alembic multiple-heads needs operator docs, deferred).

No round 2 dispatched. All actionable feedback addressed.

## Follow-up tickets (tracked here, not blocking this PR)

1. **`origin="domain-emitter"` first-class literal** — cross-cutting PR
   touching `forge/sync/{forge_to_project,project_to_forge}/` (4 sites:
   `ProvenanceOrigin` literal + 3 narrow Literal casts in updater/
   reapply_baseline/verify + the harvester orchestrator's bucket logic).
   Grep-marker `TODO(domain-emitter-origin)` at the synthetic-tag site.

2. **Operator docs for alembic multiple heads under RFC-010** — new
   `docs/domain-entities-migrations.md` or section in `RELEASING.md`.

## Diff stat (this commit)

```
 CHANGELOG.md              |  10 ++--
 forge/codegen/pipeline.py |  37 ++++++++-
 2 files changed, 41 insertions(+), 6 deletions(-)
```

Plus this impl-review file.
