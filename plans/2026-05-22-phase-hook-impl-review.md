# Implementation review — feat/phase-hook-protocol — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 11 findings; 8 ACCEPT, 2 PUSHBACK (1 addressed via new test, 1 noted), 1 QUESTION) -->

## Codex verdict

**ACCEPT** with 2 PUSHBACK items + 1 QUESTION. One PUSHBACK addressed via
this commit (missing edge-case test); the other PUSHBACK (58-char commit
subject) is noted as a lesson learned — adding a no-op "rename commit" to
fix the subject is uglier than the 8-char overrun, and CLAUDE.md prefers
new commits over --amend.

## Findings + responses

### 1. Protocol shape — duration_ms / ctx (ACCEPT)
`duration_ms: int` consistent with existing log_event; truncation from
perf_counter() float is intentional. `ctx: dict` not TypedDict — fine for
v1 (heterogeneous fields across phases).

### 2. Exception swallowing contract (ACCEPT)
All `_fire_*` helpers wrap hook calls in `try/except Exception`. Tests
validate sibling hooks still fire when one raises.

### 3. Missing edge-case test (PUSHBACK → ADDRESSED)
**Codex's gap:** no explicit test for "phase fails AND a hook raises
inside on_phase_end(error=...)". Each property tested separately, never
combined.

**Response:** added `test_phase_error_plus_hook_error_in_on_phase_end_reraises_phase`
to `tests/test_phase_hooks.py::TestPhaseTimerFiresHooks`. Asserts the
ORIGINAL phase exception re-raises (not the hook's error) — proves the
exception-handling contract holds under the combined scenario. 14 tests
now pass (was 13).

### 4. BaseException vs Exception filter (QUESTION → noted)
`phase_timer` catches BaseException for logging but forwards only
Exception subclasses to hooks. Tradeoff: avoid polluting plugins with
control-flow signals (KeyboardInterrupt/SystemExit) vs lose visibility
for graceful Ctrl-C cleanup. Codex flags both sides; recommended
documenting the tradeoff. Already documented in the `phase_timer`
docstring + protocol docstring; no change.

### 5. phase_timer location (ACCEPT)
Lives in `forge/logging.py:225` (correct per agent's catch of the brief's
mis-statement). No duplicate in generator.py.

### 6. `_fire_generate_complete` placement (ACCEPT)
At very end of `generate()` after `_finalize` + optional `_populate_report`,
immediately before return. Happy path only.

### 7. `on_generate_complete` success-only semantics (ACCEPT)
Documented in protocol docstring + plugin guide. Failure telemetry remains
at phase-level via `on_phase_end(error=...)`. Reasonable design.

### 8. SDK 1.2 coordination (QUESTION → noted)
A.1 (PR #81) + A.2 (in flight) + A.3 (this PR) all bump SDK_VERSION to 1.2.
Trivial rebase conflict on `forge/api.py` + `tests/test_sdk_version.py`
when the second/third PR merges. `docs/SDK_CHANGELOG.md` 1.2 section will
need aggregation once all three pillars land. Tracked for follow-up.

### 9. `plugins.reset_for_tests()` hook reset (ACCEPT)
Docstring scopes test-only use, explains rationale. No stability concern.

### 10. Per-call local import performance (ACCEPT)
`from forge.hooks import _fire_*` inside `phase_timer` is hot-path but
Python import caching makes overhead negligible. Not a blocker absent
profiling evidence.

### 11. Commit subject length 58 chars (PUSHBACK → NOTED, not amended)
**Codex's flag:** `feat(plugins): add PhaseHook protocol for generator phases`
is 58 chars vs CLAUDE.md's ≤50 limit.

**Response:** acknowledged as a lesson learned for future Pillar A
commits. NOT amending: CLAUDE.md explicitly prefers new commits over
--amend, and adding a no-op "rename commit" commit just to shorten the
subject is uglier than the 8-char overrun. Future commits in this branch
+ across Pillar A target ≤50 chars exact.

## Convergence

11 findings — 8 ACCEPT, 2 PUSHBACK (1 addressed via new test, 1 noted),
1 QUESTION. No round 2 dispatched — codex's PUSHBACK for the test gap
was actionable and is fixed; the subject-length finding is style not
correctness.

## Diff stat (final)

```
 CHANGELOG.md               |  16 +++
 docs/SDK_CHANGELOG.md      |  23 +++
 docs/plugin-development.md |  25 ++++
 forge/api.py               |  50 ++++++-
 forge/generator.py         |   8 ++
 forge/hooks.py             | 207 +++++++++++++++++++++++++++
 forge/logging.py           |  21 ++-
 forge/plugins.py           |   8 +-
 tests/test_phase_hooks.py  | 380 +++++++++++++++++++++++++++++++++++++++++++++
 tests/test_sdk_version.py  |   7 +-
 10 files changed, 741 insertions(+), 4 deletions(-)
```

Plus this impl-review file.
