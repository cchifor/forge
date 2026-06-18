# Forge audit remediation — TDD report (2026-06-17)

Branch base: `main` @ `8c9381c7`. Audit: 48-agent adversarial sweep → 29 confirmed bugs.
Each entry: **Issue** (root cause), **Test** (failing-first Red), **Solution** (fix + why).

Validation harnesses used:
- Cross-SDK auth parity: `tests/contract/auth_sdk_parity/` (Rust via `cargo test --features testing --test parity_runner`; works on this host via wiremock JWKS). The Node vitest runner is non-functional on this host's Node 18 (jose binds `globalThis.fetch` before the runner's override → JWKS DNS failures on every fetch scenario); it runs in forge CI. Python runner needs PyJWT (absent here) but `test_oidc_trustmap.py` covers the Python path.
- Generator/config/validation: `uv run pytest` (in-process).
- Runtime (generated projects): `tests/matrix/runner.py --lane smoke` (real `docker compose up`). NOTE the stock `assert_contract` tolerates 4xx — extended with an authenticated CRUD probe to catch auth-layer regressions.

---

## PR-1 — Auth parity (Node/Rust)

### #1 (HIGH) — Node/Rust AuthGuards reject every authenticated request

**Issue.** `bootstrapAuth` (Node) / `init_auth` (Rust) always install an empty
`InMemoryIssuerTrustMap`. The Node/Rust SDK `AuthGuard` ran trust enforcement whenever a map was
present and unconditionally threw `unknown tenant` when the token's tenant had no record — with no
`strict_trust` escape hatch. Python's `AuthGuard` defaults `strict_trust=False` (accept missing
record). Net: a byte-identical project served 200 on Python but 401 on Node/Rust for every
authenticated request — the auth subsystem was unusable out of the box for two of three backend
languages. Files: `platform_auth_sdk_node/.../src/AuthGuard.ts` (`_enforceTrust`),
`platform_auth_sdk_rust/.../src/auth_guard.rs` (`enforce_trust`).

**Test (Red).** Added cross-SDK parity scenario `accept_unregistered_tenant_when_trust_map_present`
to `tests/contract/auth_sdk_parity/scenarios.py`: a non-empty trust map holding a *different* tenant,
token minted for the canonical tenant (absent from the map), expecting success.
- Rust: `PARITY_FIXTURES=… cargo test --features testing --test parity_runner` →
  `✗ accept_unregistered_tenant_when_trust_map_present: expected success, got invalid_token: unknown tenant …` (RED).
- Python: already permissive (reference) — scenario passes.

**Solution (Green).** Mirror Python: add `strictTrust`/`strict_trust` config (default `false`); on a
missing trust record, accept unless strict (strict raises `IssuerNotTrusted`, matching Python). After
fix: Rust parity runner all 23 scenarios pass (GREEN); `tsc` clean; 59 forge-side auth tests pass;
golden snapshots unchanged. Commit `6355312b`. Runtime (docker-compose authed-CRUD) sign-off batched
with #23.

### #23 (LOW) — Node/Rust home routes 401 despite being documented public

**Issue.** `/api/v1/` (welcome) and `/api/v1/info` are documented public service-info
endpoints, but were absent from the Node `DEFAULT_EXCLUDED_PATHS` (`plugin.ts`) and Rust
`EXCLUDED_PATHS` (`auth.rs`). Node/Rust enforce auth via a global hard-reject middleware, so with
auth enabled these 401'd — Python soft-passes + per-route deps, so its home stayed public.

**Test (Red).** New `tests/test_auth_public_home_routes.py` asserts both skip-lists contain
`/api/v1/` and `/api/v1/info` — 4 failures before the fix.

**Solution (Green).** Add the home paths (+ `/api/v1`) to both skip-lists. 4 pass; tsc clean; 71
node/rust middleware + route-auth tests pass. Commit `563cdd3e`. Runtime sign-off batched with #1.

### #17 (MEDIUM) — Rust auth guard accepts not-yet-valid (future-nbf) tokens

**Issue.** jsonwebtoken's `Validation` defaults `validate_nbf=false`, so the Rust SDK accepted a
token with a future `nbf` while Python (PyJWT) and Node (jose) reject it — the `ImmatureSignature ->
InvalidToken` mapping in `errors.rs` was dead code.

**Test (Red).** Parity scenario `reject_token_not_yet_valid` (far-future `nbf` via `extra_claims`,
expecting `invalid_token`). Rust runner: `✗ ... verify succeeded` (RED); all three map nbf →
`invalid_token`.

**Solution (Green).** `validation.validate_nbf = true;` in `auth_guard.rs`. Rust parity runner 24/24
pass. Commit (follows `563cdd3e`).

### #18 (MEDIUM) — Node JWKS cache had no stale-serve fallback

**Issue.** The Node `JWKSCache` delegated to jose's `createRemoteJWKSet`, which has no stale-on-error
fallback. `staleMaxSeconds` was validated + documented ("30 min stale-serve") but never honoured, so
a JWKS/IdP outage longer than the refresh interval rejected otherwise-valid tokens whose `kid` was
already cached — while the Rust + Python caches keep serving last-known-good.

**Test (Red).** New `test/jwks_stale_serve.test.ts` (injectable `fetchImpl` + fake clock): warm the
cache, induce an outage, assert the cached key still resolves within `staleMaxSeconds` and is rejected
beyond it. Proven RED by temporarily disabling the stale-serve branch (test fails at the outage step).

**Solution (Green).** Reimplement `JWKSCache` to own fetch + cache (jose `createLocalJWKSet` for key
matching) with refresh-after-lifespan, stale-serve within `staleMaxSeconds`, and in-flight dedup,
mirroring `rust/jwks.rs`. `fetchImpl` injectable for tests. tsc clean; new test green; 24 forge-side
node SDK tests pass. Commit `920f1c74`. (The `audit_callback`/`parity_runner` vitest failures on this
host are pre-existing Node-18/jose env issues — proven independent by reverting JWKSCache to HEAD.)

---

## PR-2 — Update / three-way merge

### #2 (HIGH) — forge --update orphaned component fragments at the project root
**Issue.** generate passed `frontend_dir=apps/<slug>` to `apply_project_features` so `component_*`
fragments emit into the frontend app; the updater passed it as `None`, so on `--update` every
component fragment's `files/src/...` tree was written to the project root (orphaned) instead of
`apps/<slug>/`. Component `.vue` files are fragment-emitted (not codegen), so codegen couldn't rescue
them.
**Test (Red).** `tests/test_update_component_placement.py` spies on the updater's
`apply_project_features` and asserts it receives `frontend_dir=apps/<slug>` — `got None` before fix.
**Solution (Green).** `_update_locked` computes + forwards `frontend_dir` exactly like the generator.
4 tests pass; updater regression suite (48) green. Commit (PR-2).

### #11 (MEDIUM) — plan-update mis-predicted .jinja fragment files
**Issue.** `_decide_for_fragment` walked `files/` with no jinja/ephemeral awareness: kept the `.jinja`
suffix (dst never exists → phantom `action="new"`), never decided the rendered file, hashed the raw
template, and surfaced `__pycache__`/`.pyc` artefacts.
**Test (Red).** `tests/test_plan_update_jinja.py` (connectors project): phantom `_service.py.jinja`
entry present before fix.
**Solution (Green).** Mirror `appliers/files.py::copy_files`: skip `_is_ephemeral_path`, strip
`.jinja`, hash the rendered body via the same FragmentContext render context. 17 plan tests pass.

### #12 (MEDIUM) — file_conflicts over-counted sidecars
**Issue.** `_count_file_sidecars` globbed every `.forge-merge`, counting presurface edit-trail
sidecars (clean merges) and stale prior-run sidecars as conflicts.
**Test (Red).** `tests/test_update_file_conflicts_count.py`: raw glob counts 3, real conflicts = 1.
**Solution (Green).** Snapshot pre-existing sidecars; subtract them + the presurfaced set;
`_count_new_file_conflicts` counts only genuinely-new conflicts.

### #22 (LOW) — record vs merge binary hash divergence
**Issue.** `provenance.sha256_of` CRLF-normalized unconditionally (no binary detection); the merge used
binary-aware `sha256_of_file`. A binary blob containing `0x0D0A` recorded a different baseline →
spurious `.forge-merge.bin` conflict on a bump.
**Test (Red).** `tests/test_provenance_binary_hash_parity.py`: record vs merge digests diverge on a
binary-with-CRLF before fix.
**Solution (Green).** `sha256_of` delegates to `sha256_of_file` (single binary-aware impl). 121
provenance/merge tests pass.

---

## PR-3 — Multitenancy / isolation

### #3 (HIGH) — shared_rls didn't cover tenant feature tables
**Issue.** RLS only enabled on items/audit_logs; TenantMixin feature tables
(conversations, conversation_messages, conversation_tool_calls, chat_files,
rag_document_chunks, rag_pg_document_chunks, webhooks) carried customer_id but had
no policy → cross-tenant leak on any query missing the predicate.
**Test (Red).** `tests/test_rls_feature_table_coverage.py` AST-scans every TenantMixin
feature model and asserts each table is RLS-covered — 7 missing before fix.
**Solution (Green).** New late, existence-guarded migration `0099_enable_rls_feature_tables.py`
(runs after every feature table-creation migration via the rechainer's numeric order;
to_regclass-guarded for disabled features). Drift guard added.

### #15 (MEDIUM) — token_claim resolver dead at middleware time
**Issue.** Resolver read request.state.identity for token_claim, but generate-mode auth
is a route dependency (not middleware), so identity was unset when the middleware ran →
always None; inject.yaml/docstrings falsely claimed an auth middleware bound it. (Isolation
held via the account-scoped GUC the UoW binds.)
**Test (Red).** `tests/test_rls_token_claim_resolution.py`: resolver lacked a post-auth
fallback; false ordering premise present.
**Solution (Green).** Fall back to forge_core's `customer_id_context` (authoritative post-auth
tenant); correct the false comments. Mirrored into the schema_per_tenant resolver (kept
byte-identical by an existing guard test).

### #29 (LOW) — schema_per_tenant public fallthrough (fail-open)
**Issue.** All three search_path binders bound `tenant_<id>, public`; an unprovisioned
tenant fell through to `public.items` (fail-open cross-tenant).
**Test (Red).** `tests/test_schema_per_tenant_fail_closed.py`: binders lacked existence checks.
**Solution (Green).** Each binder verifies the schema exists (`to_regnamespace`) before binding
`, public`; unprovisioned → empty search_path (fail closed).

---

## PR-4 — Stateless & config validation (#4,#9,#16,#19,#20,#21)

All six were silent-acceptance defects caught by a new `tests/test_config_validation_guards.py`
(11 cases, all red before fix). Fixes: hard-fail database.mode=none for non-Python backends (#4);
`requires_database=True` on connectors.enabled (#9); `agent.mode` added to the resolver's
`_PYTHON_ONLY_WHEN_ACTIVE` (#16); reserved-infra-name + derived-db_name uniqueness checks in
`_validate_backend_uniqueness` (#19/#20); collision-on-insert guard in
`infra_host_port_reservations` for keycloak_port (#21). 138 config/resolver tests green; ruff + ty clean.

---

## PR-5 — Deploy / Helm (#5,#6,#24)

- **#5 (HIGH).** Helm dropped per-backend S2S synthesis env (compute_topology called without
  `synthesis=`; values.yaml never looped `synthesis_env`). Threaded synthesis through
  `_apply_project_scope` → `compute_topology` (generator + updater) and added the
  `be.synthesis_env` loop to the Helm values env block. `tests/test_helm_synthesis_env.py`; deploy suite green.
- **#6 (HIGH).** External-DB migrate Job (pre-install hook) pulled config via a non-optional
  configMapRef to a main-phase ConfigMap absent on first install → CreateContainerConfigError.
  Annotated the per-backend ConfigMap+Secret as pre-install hooks (weight -10 < the -5 Job),
  `before-hook-creation` to persist. `tests/test_helm_migrate_hook_ordering.py`; helm lint/template green.
  *Live `helm install` ordering needs a kind cluster (unavailable) — flagged gap.*
- **#24 (MEDIUM).** Rust `create_pool` eagerly `.connect().await.expect()` → CrashLoopBackOff when
  Postgres unreachable at boot (Python/Node lazy + 503 self-heal). Switched to `connect_lazy`;
  readyz `SELECT 1` surfaces DB-down as 503. `tests/test_rust_lazy_pool.py`.

---

## PR-6 — Generated backend runtime (#8,#13,#14)

- **#8 (HIGH).** Rust rate limiter keyed every request on `"anonymous"` (ConnectInfo never wired) —
  global DoS. `axum::serve(.., into_make_service_with_connect_info::<SocketAddr>())`. cargo build green.
- **#13 (MEDIUM).** Rust list passed negative `?limit/?skip` to SQL -> 500. Reject with
  `AppError::Validation` (422), matching Python 422 / Node 400.
- **#14 (MEDIUM).** Node rate limiter had no trustProxy/XFF -> all clients collapsed to the proxy IP.
  `trustProxy:'uniquelocal'` + per-tenant/IP `keyGenerator`.

`tests/test_backend_runtime_guards.py`; rust validated via cargo (verify lane). Node tsc deferred to final e2e.

---

## PR-7 — Frontend chat / canvas (#7,#25,#27)

- **#7 (HIGH).** Svelte + Flutter chat clients lacked Vue's stale-run guard; a superseded run's
  late events re-added ghost messages after resetThread/editAndResend. Ported the `runGeneration`
  counter + `isCurrent()` guards (Flutter await-for `return` also cancels the stream).
- **#25 (MEDIUM).** Svelte canvas DataTable threw on a null row + no boundary. Null-safe rows/cells +
  `<svelte:boundary>` fallback in CanvasPane.
- **#27 (LOW).** Flutter DataTable with zero columns tripped Material's assert -> placeholder guard.

Gate: `tests/test_frontend_chat_canvas_guards.py` (grep) + the fix mirrors the tested Vue
implementation. *No dart/flutter or svelte app deps here — frontend runtime validation deferred.*

---

## PR-8 — Codegen / gatekeeper edge (#10,#26,#28)

- **#10 (MEDIUM).** Gatekeeper `exchange_code`/`refresh_tokens` wrapped in `@with_retry` -> a
  read-timeout replays the single-use code (invalid_grant) -> login fails. Dropped retry from the
  non-idempotent token operations.
- **#26 (LOW).** `ts_ast.inject_ts` lacked the `_ensure_trailing_newline` guard -> BEGIN sentinel
  fused onto an EOF anchor. Ported the guard (real ts_ast unit test).
- **#28 (LOW).** Gatekeeper `/callback` used `session_fp` without importing it -> NameError (500)
  instead of 400 on a corrupt auth-state envelope. Added the import.

`tests/test_codegen_gatekeeper_edge.py`; ts_ast/python_ast suites green; ruff+ty clean.

---

## Verification & status

**Branch:** `audit-remediation-2026-06` (18 commits off `main`, per-bug). All 29 confirmed bugs fixed,
each TDD (failing test first → fix → green).

**Full suite (`uv run pytest -m "not e2e and not fuzz" -n auto`):** 5004 passed, 38 skipped after the
audit fixes + two necessary fixups:
- golden snapshots regenerated (drift = exactly the edited service templates: node `app.ts`, rust
  `main.rs`/`db.rs`/`item_repository.rs`) — verified no unexpected files changed;
- `test_generated_ops_docs` switched off `database.mode=none` (now Python-only per #4).

`ruff check` + `ruff format --check` clean across 253 files; `ty check` clean on every changed module.

**Cross-language auth parity:** the cargo parity runner (`tests/contract/auth_sdk_parity`) is GREEN
(24/24) — including the two new scenarios `accept_unregistered_tenant_when_trust_map_present` (#1) and
`reject_token_not_yet_valid` (#17). Rust runtime changes (#8/#13/#24) compile via the cargo verify
lane (green).

**Known-failing on THIS host (pre-existing env, not regressions — evidence in commit notes):**
- `test_node_runner` — 2 of 24 node parity scenarios fail under this host's Node 18 / jose version:
  `reject_wrong_audience` (jose says `'unexpected "aud" claim value'`, scenario expects substring
  `'audience'`) and `reject_missing_tenant_claim` (the runner's brittle omit-claim minting). Neither
  scenario is in a file this work changed; the added scenarios pass. Passes on forge CI's toolchain.
- Flutter-runtime (#7-flutter, #25-flutter, #27) and Helm-on-cluster (#6, #24 Helm path): no
  dart/flutter and no kind here → validated by golden/grep + `helm lint`/`template`; live runtime
  confirmation deferred (flagged).

**Consolidated docker e2e:** `node_svelte_min` (real `docker compose up --build` via the matrix smoke
lane). The Node service image BUILT (npm install, **svelte-check**, vite build all green — Svelte
#7/#25 + node templates type-check) and **postgres + the migrate Job booted**; the full
`compose up --wait` then failed solely on the host conflict `traefik` cannot bind `:80`
(`address already in use` — a host service holds :80 here, a documented environment limitation, not a
code defect). Probing the booted API directly (bypassing traefik): `GET /api/v1/health/ready` → 200
(DB UP), `GET /api/v1/items` → **200**, `POST /api/v1/items` → **201**. So the generated Node stack
builds, boots (with #14's `trustProxy`), and serves CRUD end-to-end. Rust runtime is cargo-verified
(verify lane green); a full multi-stack smoke is blocked by the host `:80` conflict.
