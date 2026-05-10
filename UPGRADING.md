# Upgrading forge

This document lists breaking changes per version and the migration steps for each.

## 1.0 → 1.1

The 1.1 series opens the 12-month post-1.0 roadmap. Early alphas are additive except where called out below.

### 1.1.0-alpha.1 — structured error hierarchy (Epic D)

`GeneratorError` is no longer a distinct class. It is now an **alias** for the new `ForgeError` base, and every internal raise site has been promoted to one of six typed subclasses:

| Subclass | When it's raised | Exit code |
|---|---|---|
| `OptionsError` | Unknown option path, dep cycle, fragment conflict | 2 |
| `FragmentError` | Fragment dir missing, malformed `inject.yaml`, missing `deps.yaml` | 2 |
| `InjectionError` | Missing anchor, ambiguous marker, corrupt sentinel | 3 |
| `MergeError` | Three-way merge conflict (reserved for Epic F/H) | 4 |
| `ProvenanceError` | Missing `forge.toml`, manifest corruption | 5 |
| `PluginError` | Plugin load or registration collision | 6 |

Each error carries `code: str`, `hint: str | None`, and `context: dict[str, Any]`. The CLI's `--json` envelope emits all four fields.

**Impact on your code:**

- `except GeneratorError:` continues to catch every forge failure — the alias makes this safe. You don't need to change anything if you only catch the base class.
- `except ValueError:` around `inject_python` / `inject_ts` **breaks** — those injectors used to raise `ValueError` / `FileNotFoundError` and now raise `InjectionError`. Change your handler to `except forge.errors.InjectionError:` (or `except forge.errors.ForgeError:` to catch all forge failures).
- `type(err).__name__ == "GeneratorError"` **breaks** — use `isinstance(err, forge.errors.ForgeError)` or the specific subclass.
- `pytest.raises(GeneratorError, match="...")` continues to work because the subclass is-a `GeneratorError`, and the matched text is unchanged. Tests that want tighter coverage should migrate to `pytest.raises(forge.errors.OptionsError)` (or whichever fits) and `assert err.value.code == OPTIONS_UNKNOWN_PATH`.

**Machine-readable codes.** If you consume forge's `--json` error envelope, the new `code` field lets you switch on specific failure kinds without string matching:

```python
import json, subprocess
result = subprocess.run(["forge", "--config", "stack.yaml", "--json"], capture_output=True)
if result.returncode != 0:
    envelope = json.loads(result.stdout)
    match envelope.get("code"):
        case "OPTIONS_UNKNOWN_PATH":
            ...   # user typo — suggest forge --list
        case "INJECTION_ANCHOR_NOT_FOUND":
            ...   # base template needs an anchor comment
        case "PROVENANCE_MANIFEST_MISSING":
            ...   # wrong directory; not a forge project
```

No codemod ships for this migration — the changes are too coupled to local test style to mechanise safely. Grep your code for `GeneratorError`, decide whether each site wants the base class or a specific subclass, and update in place.

---

## 0.x → 1.0

forge 1.0 is a clean-break release. The high-level shifts:

1. **Schema-first core** — TypeSpec drives CRUD entities; JSON Schema drives the agentic-UI protocol. Hand-written domain and protocol types are replaced by generated files.
2. **AST-aware injection** — text-marker injection is replaced by LibCST (Python) and ts-morph (TypeScript). Users can now reformat generated code freely.
3. **Three-zone merge** — `forge --update` respects user-owned regions. No more silent overwrites or silent skips.
4. **Ports-and-adapters** — integrations are swappable at runtime. Config change, not regeneration.
5. **Plugin surface** — third parties can ship backends, frontends, fragments, commands, and emitters via `importlib.metadata` entry points.

The overall migration path:

```bash
# 1. Pin your current forge version
forge --version                            # note this

# 2. Re-generate or migrate
forge migrate                              # new 1.0 umbrella command (when available)
#   OR, for a clean break:
forge new --config forge.yaml              # regenerate in a fresh directory
```

## Per-phase breaking changes

This section is populated as each 1.0 alpha ships.

### 1.0.0a1 — Phase 0 foundations (unreleased)

- **CLI entry point** — `forge.cli:main` → `forge.cli.main:main` (same `forge` console script). Code importing `from forge.cli import main` should continue to work via re-export, but code importing private helpers (`_build_parser`, `_Resolver`, etc.) must update to the new paths.
- **`forge.toml`** — new `[forge.provenance]` table. Old projects lacking it will receive a one-time backfill with a warning on the first `forge --update` in 1.0.

### 1.0.0a2 — Phase 1 schema-first (unreleased)

_To be populated when Phase 1 alpha ships._

### 1.0.0a3 — Phase 2 extensibility (unreleased)

_To be populated when Phase 2 alpha ships._

### 1.0.0a4 — Phase 3 agentic-UI upgrade (unreleased)

_To be populated when Phase 3 alpha ships._

### 1.0.0b1 — Phase 4 polish (unreleased)

_To be populated when Phase 4 beta ships._

---

## 1.1 → 1.2 — auth-stack rebuild (unreleased)

The 1.2 release replaces the legacy Keycloak-direct auth stack with
the platform-auth model: Gatekeeper as sole token authority (ES256
internal JWTs), per-language verifier SDKs (Python / Node / Rust),
BFF Redis sessions with a single opaque cookie, inactivity-based
session timeout, and frontend session-timeout composables for Vue /
Svelte / Flutter. See `docs/auth-architecture.md` for the model;
this section is the migration procedure.

This is a **breaking change** for projects generated under 1.1.x —
both the source layout (new `sdks/platform-auth*/` directories,
new gatekeeper modules) and the env-var shape (some `KEYCLOAK_*`
keys move to `GATEKEEPER_*`).

### Migration steps

```bash
# 1. Bump forge.
uv tool upgrade forge

# 2. Plan the migration — dry run, no writes.
cd <generated-project>
forge --plan-migrate auth-keycloak-to-platform-auth

# Reports:
#   - Files to add (sdks/platform-auth/, sdks/platform-auth-node/,
#     sdks/platform-auth-rs/, expanded infra/gatekeeper/)
#   - Files to replace (per-backend service/security/auth.* modules,
#     middleware/tenant.{ts,rs} → middleware/auth.{ts,rs})
#   - infra/keycloak-realm.json additive changes (tenant-id mapper,
#     serviceAccountsEnabled on gatekeeper client, dev user attribute)
#   - docker-compose.yml service changes (gatekeeper-keygen init,
#     extended gatekeeper env block)
#   - Env var renames (KEYCLOAK_* → GATEKEEPER_* per the table below)

# 3. Apply the codemod. Three-way merge against your edits;
#    .forge-merge sidecars on conflict (resolve by hand).
forge --migrate auth-keycloak-to-platform-auth

# 4. Inspect any sidecars produced.
git status | grep .forge-merge

# 5. Rebuild + boot.
docker compose up --build
#   - gatekeeper-keygen runs first, generates ECDSA P-256 keys
#   - gatekeeper boots, /auth/jwks serves the public key
#   - backends pick up the new SDK from sdks/platform-auth*/
#   - browser flow: login at Keycloak, callback issues session_id cookie
```

### Env var renames

| Before (1.1.x) | After (1.2.x) | Notes |
| --- | --- | --- |
| `KEYCLOAK_BASE_URL` | `KEYCLOAK_BASE_URL` | Still consumed by gatekeeper for the OIDC bridge. |
| `KEYCLOAK_REALM` | (gone) | Encoded in `KEYCLOAK_BASE_URL` path now. |
| `KEYCLOAK_CLIENT_ID` | `GATEKEEPER_CLIENT_ID` | Was the per-service client; now the gatekeeper's confidential client. |
| `KEYCLOAK_CLIENT_SECRET` | `GATEKEEPER_CLIENT_SECRET` | Same scope shift. |
| `APP__SECURITY__AUTH__SERVER_URL` | `GATEKEEPER_ISSUER` | Backends verify against gatekeeper's JWKS, not Keycloak's. |
| `APP__SECURITY__AUTH__REALM` | (gone) | Subsumed by `GATEKEEPER_ISSUER` (single trusted issuer). |
| (new) | `INTERNAL_TOKEN_AUDIENCE` | aud claim on minted JWTs. Defaults to `forge-services`. |
| (new) | `SESSION_FERNET_KEY` | Required. Generate via `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`. Rotation invalidates all live sessions. |
| (new) | `SESSION_TIMEOUT_ENABLED` | Defaults to `true`. Set `false` to skip idle/absolute checks (still issues internal JWTs). |
| (new) | `DEFAULT_IDLE_TIMEOUT_SECONDS` | Default `1800` (30 min). Per-tenant overridable via `TenantConfig`. |
| (new) | `DEFAULT_ABSOLUTE_TIMEOUT_SECONDS` | Default `43200` (12 h). |
| (new) | `SESSION_WARN_AT_SECONDS` | Default `60`. SPA modal threshold. |
| (new) | `SERVICE_REGISTRY_PATH` | argon2id-hashed S2S client secrets. |
| (new) | `KEY_BACKEND` | `file` (default). `aws_kms` / `vault` are follow-ups. |
| (new) | `SIGNING_KEY_DIR` | Where `gatekeeper-keygen` writes keys. Default `/run/secrets/gatekeeper-signing`. |

### Cookie changes

The browser cookie surface contracts from two cookies to one:

| Before | After | Notes |
| --- | --- | --- |
| `tenant_session=<jwt>` | (gone) | Access tokens no longer leave the server. |
| `tenant_refresh=<jwt>` | (gone) | Refresh tokens stay in Redis. |
| (new) | `tenant_session_id=<24-byte-random>` | `HttpOnly`, `Secure`, `SameSite=Lax`, `Max-Age=absolute_timeout_seconds`. |

`SameSite=Lax` (not `Strict`) — preserves deep-linking from external
tools. CSRF is mitigated at the API layer via
`Content-Type: application/json` enforcement on mutating endpoints.
If your project added a non-JSON mutating endpoint, audit it before
upgrading or you'll lose the CSRF guard silently.

### Hard cutover, NOT dual-mode

The codemod replaces the auth stack atomically — no flag toggles
the old vs new behaviour. Existing sessions are invalidated at
deploy. Schedule a maintenance window and announce it; the new
stack boots in under a minute on a warm machine.

### Rollback

If something breaks post-migration, the cleanest rollback is:

```bash
git checkout <pre-migration-commit>
forge --update                # re-applies the 1.1.x baseline
docker compose up --build
```

`forge --update` is idempotent and respects user edits via
`.forge-merge` sidecars, so this is safe even with concurrent
in-progress work.

### Behavioural changes engineers should know

1. **`/auth` does NOT extend the session.** Every authenticated route
   passes through `/auth` (Traefik's ForwardAuth), but the call is
   read-only — no idle-TTL touch. Sessions extend exclusively when
   the SPA POSTs `/auth/session` on real user activity (mouse,
   keyboard, scroll, visibility). New code that polls a backend in
   the background has zero session impact, by design. Document this
   in your `AGENTS.md` / `CLAUDE.md` so a future contributor "fixing"
   an unexpected logout by adding a heartbeat poll doesn't defeat
   the compliance posture.
2. **Internal JWT TTL is 5 minutes.** A token revoked upstream stays
   verifiable for up to 5 minutes after `/logout` —
   `internal_token_cache.evict_for_sub` is best-effort. Engineers
   building features with hard revocation requirements (e.g.,
   financial-impact actions) need to gate on the session itself,
   not the bearer.
3. **Scope-based authz is now first-class.** Endpoints can declare
   `requireScope("things:read")` (or the language-equivalent) and
   AuthGuard rejects with a typed `ScopeRequired` error carrying
   the missing scopes. Wildcards (`things:*`, `*`) are honored.
4. **S2S calls go through `S2SClient`**, not raw `httpx`/`fetch`/`reqwest`.
   The client handles client_credentials and RFC 8693 token-exchange
   automatically and caches the resulting tokens.

---

## Codemods and tooling

When a mechanical migration is possible, forge ships a `forge migrate-<x>` codemod:

| Codemod | Availability | What it does |
|---|---|---|
| `forge migrate` | Post-1.0.0a1 | Umbrella — runs all applicable migrations for a project |
| `forge migrate-entities` | Post-1.0.0a2 | Translate hand-written domain/*.py, prisma/schema.prisma, models.rs to a generated `domain/*.tsp` |
| `forge migrate-ui-protocol` | Post-1.0.0a2 | Delete hand-written `types.ts` / `chat.types.ts` / `agent_state.dart`; re-run generator |
| `forge migrate-adapters` | Post-1.0.0a3 | Restructure `src/app/rag/` into `src/app/ports/` + `src/app/adapters/vector_store/` |

Each codemod is idempotent and safe to re-run.

## Rollback

If an upgrade fails, every alpha/beta retains an installable identity on PyPI. Rollback is:

```bash
uv pip install "forge==0.X.Y"    # your last working version
```

and discard the `1.0-dev` workspace. The `0.x-final` tag is the stable reference.
