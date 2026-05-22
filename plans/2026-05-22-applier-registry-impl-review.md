# Implementation review — feat/applier-registry — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 11 findings; 8 ACCEPT, 3 QUESTION, 0 PUSHBACK) -->

## Codex verdict

**ACCEPT.** All 8 main contract items pass; 3 minor QUESTIONS noted but no
PUSHBACK. No code changes needed.

## Findings + responses

### 1. Registry shape + seeding contract (ACCEPT)
Import-time `_seed_builtin_injectors()` (line 531), last-write-wins
semantics, wildcard registered (not hardcoded), Protocol signature
matches existing injectors.

### 2. `_dispatch_injector` refactor (ACCEPT)
Original 16-line if/elif chain at `forge/appliers/injection.py:236-256`
fully replaced by `lookup_injector(target)` + invoke. Caller signature
unchanged. Defensive `RuntimeError` for missing wildcard tested.

### 3. Test coverage — 31 tests (ACCEPT)
Built-in suffix resolution, `.tsx`/`.jsx`/`.mjs`/`.cjs` → ts_ast, `.pyi`
→ python_ast, wildcard fallback, plugin override (`.go`), plugin can
override wildcard, plugin can override a built-in, SDK round-trip,
defensive `RuntimeError` path — all covered. Test isolation via
`_isolate_registry` autouse fixture snapshots/restores the module dict.

### 4. SDK_VERSION bump (ACCEPT)
1.1 → 1.2. `tests/test_sdk_version.py` parametrization updated. Trivial
rebase conflict expected when sibling A.3 (PR #79) merges (also bumps to
1.2); whichever merges second handles.

### 5. `PLUGIN_COLLISION` error code (ACCEPT)
Exists and exported in `forge/errors.py`. `ForgeAPI.add_injector` wraps
the `ValueError` from `register_injector` into `PluginError(code=PLUGIN_COLLISION)`
— matches the pattern from `add_option` / `add_service`.

### 6. Documentation example (ACCEPT)
8-line example in `docs/plugin-development.md` is accurate + compiles.

### 7. `docs/SDK_CHANGELOG.md` 1.2 section (ACCEPT — marked provisional)
Codex notes A.2 + A.3 landing will require aggregating their additions
into this 1.2 entry. Tracked as follow-up; not a per-PR blocker.

### 8. CHANGELOG entry (ACCEPT)
Honest description of dispatch refactor, SDK hook, seeded wildcard.

### 9. Lazy import adapter pattern (QUESTION → noted)
Codex finds no concrete circular-import evidence in the diff. Pattern
is consistent with prior lazy behavior and avoids importing AST stacks
(libcst, ts-morph) at registry import time. Acceptable; rationale is
startup-cost/side-effect control, not cycle-break necessity.
Recommendation: future docstring tweaks should describe it as
"deferred-import for cold-start cost" rather than implying a specific
import cycle. Noted; not changing in this PR (the existing docstring
doesn't overstate).

### 10. `ForgeAPI.add_injector` lowercase normalization (QUESTION → noted)
Minor wording gap: docs say "lowercase suffix" but implementation
transparently lowercases and accepts uppercase (`.GO`). Tracked; if it
becomes a user-confusion point, tighten the docstring in a follow-up.

### 11. Commit subject 44 chars (ACCEPT)
`feat(api): add ApplierRegistry for pluggable injectors` — within
CLAUDE.md ≤50 limit. Honest scope.

## Convergence

11 findings — 8 ACCEPT, 3 QUESTION (all noted, none blocking), 0
PUSHBACK. No round 2 dispatched — no actionable feedback required code
changes; questions are documentation polish + a sibling-PR coordination
note.

## Sibling PR coordination

- **PR #79 (A.3 PhaseHook)** also bumps `SDK_VERSION` 1.1 → 1.2. Trivial
  rebase conflict on `forge/api.py` + `tests/test_sdk_version.py` when
  the second-to-merge lands. `docs/SDK_CHANGELOG.md` 1.2 section needs
  aggregation once both pillars are in.
- **PR #83 (A.2 FragmentRenderer)** doesn't bump SDK_VERSION (verified by
  agent's diff stat).

## Diff stat (unchanged from PR open)

```
 8 files changed, 743 insertions(+), 19 deletions(-)
```

Primary changes:
- `forge/injectors/_registry.py` — 269 LOC (new)
- `tests/test_applier_registry.py` — 312 LOC (new)

Plus this impl-review file (next commit).
