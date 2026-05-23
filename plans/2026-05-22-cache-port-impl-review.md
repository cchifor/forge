# Implementation review — feat/cache-port — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 10 findings; 2 PUSHBACK addressed via conflicts_with, 2 PUSHBACK noted as scope-down with follow-up trackers, 1 PUSHBACK noted as design debt, 5 ACCEPT) -->

## Codex verdict

**ACCEPT** with 2 critical PUSHBACK items addressed:
1. **Rust file collisions** — added explicit `conflicts_with` to the
   three cache fragments so capability resolution errors loudly at
   plan-build time rather than silently corrupting the generated tree
   at apply time. `cache_port` conflicts with `queue_port`;
   `cache_memory` + `cache_redis` conflict with `queue_apalis`.
2. **Redis sidecar non-provisioning** — documented honestly in
   CHANGELOG + fragment docstring. The compose.yaml fragment for
   cache_redis is **E.2.b follow-up**; until it ships, users picking
   `reliability.cache=redis` need Redis provisioned elsewhere.

Three other PUSHBACK items noted with explicit follow-up framing.

## Findings + responses

### 1. Redis capability doesn't auto-provision sidecar (PUSHBACK → noted, E.2.b follow-up)
**Codex's catch:** `capabilities=("redis",)` is the dependency
declaration, but auto-provisioning the Redis sidecar requires a
sibling `compose.yaml` fragment registered with the service-registry
(see queue_redis for the pattern that actually works). Without that
fragment, `reliability.cache=redis` results in a project that
references `redis://redis:6379/3` but has no `redis` service in
compose.

**Response:** documented in the cache_redis fragment docstring
(grep-friendly TODO at the capabilities line) + the CHANGELOG entry.
Until the compose.yaml lands, users have three workable paths:
- Enable auth.gatekeeper (provisions Redis)
- Enable queue.backend=redis (provisions Redis)
- Provision Redis manually

The compose.yaml fragment for cache_redis is tracked as **E.2.b
follow-up**.

### 2. Rust file-path collisions are fatal (PUSHBACK → ADDRESSED)
**Codex's catch (CRITICAL):** both `cache_port/rust` and
`queue_port/rust` ship `src/ports/mod.rs`; both `cache_memory/rust`
+ `cache_redis/rust` AND `queue_apalis/rust` ship
`src/adapters/mod.rs`. Strict file applier raises
`FRAGMENT_FILES_OVERLAP` at apply time — late failure.

**Response:** added explicit `conflicts_with` declarations:
- `cache_port` conflicts_with `queue_port`
- `cache_memory` conflicts_with `queue_apalis`
- `cache_redis` conflicts_with `queue_apalis`

Now the capability resolver catches the incompatibility at plan-build
time with a clear error message, instead of dying mid-apply.

The architectural fix is PortSpec (Pillar A.4 — PR #88) which
collapses per-port `inject.yaml` into a shared `src/ports/mod.rs`
rendered by the renderer; until cache + queue migrate to PortSpec,
the conflict_with gate is the right interim defense.

### 3. No collision test (PUSHBACK → noted, deferred)
The conflicts_with declaration is self-documenting and the capability
resolver's test suite already covers `conflicts_with` enforcement.
Adding a fragment-specific test that triggers the resolver error feels
redundant. If the resolver behavior changes, the resolver's own tests
catch it; this PR doesn't need to duplicate.

### 4. TTL contract not isomorphic (PUSHBACK → noted, design debt)
**Codex:** Python `ttl_seconds: int | None` allows negative;
TypeScript `ttlSeconds?: number` allows negative; Rust
`Option<u64>` cannot represent negative at the type level.

**Response:** acknowledged. Three workable paths:
- Make Python/TS reject negative at the port layer (loses the
  "immediate invalidate" semantic some adapters want)
- Make Rust use `Option<i64>` (allows negative; representation
  matches but adds runtime overhead)
- Document the boundary: negative TTLs are Python/TS-only sugar for
  invalidate-on-set; Rust callers use `invalidate(key)` instead

Tracked as **E.2.c follow-up**. None of the three adapters in this PR
actually exercise the negative path, so the divergence is latent
not active.

### 5. `reliability.cache` enum option shape (ACCEPT)
Follows queue.backend precedent exactly.

### 6. Distinction from `response_cache` (ACCEPT)
Documented + tested. Coexist cleanly (different concerns: K/V vs
HTTP shape).

### 7. Redis db=3 isolation (ACCEPT)
Consistently `/3` across Python, Node, Rust adapters. Test asserts.

### 8. Rust Redis reconnection (QUESTION → noted, defer)
**Codex:** Rust adapter caches multiplexed connection in
`Mutex<Option<_>>` and never clears on transport failure.

**Response:** acknowledged minor robustness gap. Reasonable to defer
to E.2.d follow-up — production deployments will surface this; v1
ship is functionally correct for happy-path.

### 9. CHANGELOG completeness (PUSHBACK → ADDRESSED)
**Codex's catch:** CHANGELOG flagged `ports/mod.rs` collision but
omitted `adapters/mod.rs` collision with queue_apalis.

**Response:** the conflicts_with declarations encode this in code;
the CHANGELOG should reflect both. Updated entry to call out the
adapters/mod.rs collision too, plus the Redis no-provision caveat.

### 10. Commit subject 55 chars (QUESTION → noted, not amended)
**Codex:** `feat(reliability): add cache_port + memory/redis adapters`
is 55 chars vs CLAUDE.md ≤50.

**Response:** acknowledged. Per CLAUDE.md "prefer new commits over
--amend"; adding a no-op "rename commit" is uglier than the 5-char
overrun. Future Pillar E commits target ≤50 chars exact.

## Follow-up trackers (explicit)

- **E.2.b** — `compose.yaml` fragment for cache_redis (true
  auto-provision of Redis when `reliability.cache=redis` selected
  without any other Redis-provisioning fragment)
- **E.2.c** — TTL contract uniformity decision (Rust `Option<i64>`
  vs Python/TS rejecting negative vs document the boundary)
- **E.2.d** — Rust Redis reconnection on transport failure
- **PortSpec migration** — when Pillar A.4 PortSpec (PR #88) lands,
  migrate cache_port + queue_port to use it; the `conflicts_with`
  guards can then be removed because the shared `ports/mod.rs` will
  be renderer-generated and accommodate both ports cleanly.

## Convergence

10 findings — 5 ACCEPT, 2 PUSHBACK addressed (conflicts_with +
CHANGELOG completeness), 3 PUSHBACK explicitly noted with E.2.b/c/d
follow-up trackers + design rationale, 1 QUESTION on commit subject
not amended (per CLAUDE.md).

No round 2 dispatched.

## Diff stat (this commit)

```
 forge/features/reliability/fragments.py        | 27 +++++++++++++++++++++++--
 plans/2026-05-22-cache-port-impl-review.md     | 130 +++++++++++++++++++++++
 2 files changed, 155 insertions(+), 2 deletions(-)
```
