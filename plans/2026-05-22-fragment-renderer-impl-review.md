# Implementation review — feat/fragment-renderer-protocol — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 9 findings; 8 ACCEPT, 1 QUESTION noted, 0 PUSHBACK) -->

## Codex verdict

**ACCEPT**. Backwards compatibility preserved, protocol design forward-
thinking, 18 tests covering the contract. One QUESTION flagged on
jinja_env threading — design debt for RFC-009, not a per-PR blocker.

## Findings + responses

### 1. Protocol shape (ACCEPT)
`name`, `backend`, `attach_zone`, `render(*, backend, feature_key, jinja_env=None) -> tuple[_Injection, ...]`
at `forge/appliers/renderers.py:49-75`. `@runtime_checkable` decorator
enables `isinstance()` checks. Covers MiddlewareSpec's multi-injection
return and has room for ServiceRegistrationSpec / ErrorCodeSpec.

### 2. MiddlewareSpec migration (ACCEPT)
`forge/specs/middleware.py` (lines 76-142) byte-equivalent to old
location. `attach_zone: InjectionZone = "generated"` default preserves
historical behavior. Shim at `forge/middleware_spec.py` is a clean 1-line
re-export with `TODO: remove in 2.0`. All per-backend render functions
preserved.

### 3. Backwards compatibility (ACCEPT)
`merged_renderers = renderers + tuple(middlewares)` at `forge/appliers/plan.py:294`
preserves insertion order. Sync-layer call sites in
`forge/sync/forge_to_project/{updater,plan}` pass `middlewares=` and work
unchanged. **Zero touches to sync/ code itself** — adapter layer handles
the fold. Epic K plugins keep importing from `forge.middleware_spec`
via shim.

### 4. `_render_all` dispatch — jinja_env not threaded (QUESTION → noted)
**Codex's design debt flag:** at `forge/appliers/plan.py:338`:
```python
out.extend(renderer.render(backend=backend, feature_key=feature_key))
```
No `jinja_env` passed. Protocol allows it as optional, so MiddlewareSpec
(which doesn't need jinja) works today. But RFC-009 ServiceRegistrationSpec
will render through `_shared/service_registration/{python,node,rust}.jinja`
macros and WILL need `jinja_env: jinja2.Environment`.

**Response:** acknowledged as RFC-009 follow-up work. When that lands,
add `jinja_env` parameter to `from_impl()`, thread through `_render_all()`
to `renderer.render()`. Alternative — ServiceRegistrationSpec constructs
its own env — is wasteful + not thread-safe; preferred path is threading
the existing env through.

This is design debt, not a bug in this PR. MiddlewareSpec works
correctly. Documented here so the next person touching `_render_all`
knows the shape change is coming.

### 5. Test coverage (ACCEPT)
18 tests (417 LOC) cover:
- Protocol conformance (MiddlewareSpec satisfies via `isinstance(_, FragmentRenderer)`)
- Round-trip parity (old MiddlewareSpec behavior preserved through new
  dispatch)
- Heterogeneous dispatch (one middleware + one stub
  ServiceRegistrationSpec)
- Backend filtering (renderers gated by `backend == feature_backend`)
- Ordering (per-renderer `order` field + name tiebreaker)
- Empty fallback (`renderers=()` no-op)
- Legacy import shim (still importable from `forge.middleware_spec`)
- Per-backend targets

Stub `_StubServiceRegistrationSpec` is a good stand-in for RFC-009.
One low-priority edge case not tested: a renderer returning `()` for
non-backend reasons (e.g., a feature-flag check inside render).

### 6. Package layout (ACCEPT)
`forge/specs/` is the right home for future specs per
deep-gliding-mccarthy.md:95. Per-backend Jinja templates live under
`forge/templates/_shared/<spec-name>/`; protocol declarations in
`forge/specs/`. Clean split.

### 7. CHANGELOG (ACCEPT)
Honest entry naming the protocol, future inhabitants, shim, one-release
legacy keyword.

### 8. SDK_VERSION (ACCEPT — NOT bumped)
`forge/api.py` still at 1.1. Correct — protocol is internal infra, not
public API surface. Sibling PRs #79 (A.3) + #81 (A.1) bump to 1.2 for
their new `add_hook` / `add_injector` SDK methods; this PR adds no SDK
surface so no bump.

### 9. Commit subject + style (ACCEPT)
`feat(appliers): add FragmentRenderer protocol` = 45 chars (within
CLAUDE.md ≤50 limit). Conventional Commits, no AI co-author trailer.
No touches to `forge/sync/`, `forge/generator.py`, or
`forge/capability_resolver.py`.

## Convergence

9 findings — 8 ACCEPT, 1 QUESTION (jinja_env threading, RFC-009
follow-up), 0 PUSHBACK. No round 2 dispatched — no actionable feedback;
the QUESTION is a known-coming design change tracked here for the next
PR that lands ServiceRegistrationSpec.

## Sibling PR coordination

- **PR #81 (A.1 ApplierRegistry)** + **PR #79 (A.3 PhaseHook)** both bump
  `SDK_VERSION` 1.1 → 1.2. This PR does NOT bump. No conflict with
  either sibling.
- **PR #80 (B.5 canvas-core MCP helper)** is TypeScript-only — no
  conflict with this Python-only PR.
- **PR #78 (C.1 domain emitters)** touches `forge/domain/` —
  non-overlapping with `forge/appliers/` + `forge/specs/`.

## Diff stat (unchanged)

```
 CHANGELOG.md                    |  17 ++
 forge/appliers/__init__.py      |   2 +
 forge/appliers/pipeline.py      |  25 ++-
 forge/appliers/plan.py          |  78 ++++++--
 forge/appliers/renderers.py     |  75 ++++++++
 forge/middleware_spec.py        | 259 +++----------------------
 forge/specs/__init__.py         |  29 +++
 forge/specs/middleware.py       | 298 ++++++++++++++++++++++++++++
 tests/test_fragment_renderer.py | 417 ++++++++++++++++++++++++++++++++++++++++
 9 files changed, 940 insertions(+), 260 deletions(-)
```

Plus this impl-review file.
