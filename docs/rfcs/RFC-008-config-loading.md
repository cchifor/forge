# RFC-008 — Layered config loading

| Field | Value |
| --- | --- |
| Status | Accepted |
| Author | Architecture review 2026-04 |
| Epic | 1.0.0-ga |
| Supersedes | — |
| Replaces | — |

## Summary

Establish a single layered-config contract for every forge-generated
backend. Each service loads the same layer chain, in the same priority
order, with the same environment-variable naming convention — so
operators deploying Python, Node, or Rust services can reason about
configuration uniformly.

## Motivation

Before this RFC, only the Python backend supported a multi-layer config
chain (`config/<env>.yaml`, `.secrets.yaml`, `APP__*` env vars via
`pydantic-settings`). Node and Rust shipped `.env.example` + scattered
`process.env.X ?? default` / `std::env::var()` reads. Multi-environment
deployment (staging, prod, preview) was effectively unsupported on the
non-Python backends — operators had to hand-roll config loading for
every project, violating forge's "three backends, one mental model"
promise.

## The layer chain

Every backend loads and merges, in order of increasing priority:

| # | Layer | Purpose |
| --- | --- | --- |
| 1 | Struct / schema defaults | Baked into code. |
| 2 | `config/defaults.yaml` | Ship-shape baseline for any environment. |
| 3 | `config/<env>.yaml` | Environment-specific overrides (`development`, `testing`, `staging`, `production`). |
| 4 | `.secrets.yaml` (optional, gitignored) | Local dev secrets. |
| 5 | Env vars with `APP__` prefix | Runtime deploy-time overrides. |

Nested keys map to env vars with `__` as the delimiter:

```
APP__SERVER__PORT=8080            # sets server.port
APP__DB__URL=postgres://...       # sets db.url
APP__SECURITY__AUTH__ENABLED=true # sets security.auth.enabled
```

Environment selection:

1. Python: `ENV=<name>` (fallback `development`).
2. Node: `ENV` > `NODE_ENV` > `development`.
3. Rust: `ENV` > `APP_ENV` > `development`.

## Canonical shape

All three backends deserialize into an equivalent `AppConfig` tree:

```
app:
  name: string
  version: string
  env: enum [development | testing | staging | production]
server:
  host: string
  port: int
  cors:
    enabled: bool
    allow_origins: [string]
    allow_credentials: bool
    max_age: int
db:
  url: string
  pool_min: int
  pool_max: int
  statement_timeout_ms: int
logging:
  level: enum [trace | debug | info | warn | error | fatal]
  pretty: bool
security:
  auth:
    enabled: bool
    server_url: string?
    realm: string?
    client_id: string?
```

Fragments that need their own config sections extend the tree in their
own templates (e.g. `rag_qdrant` fragment adds `rag.qdrant.endpoint`).
The central schema validates unknown keys leniently so fragments can
attach without forcing a core-registry change.

## Implementation

- **Python**: `pydantic-settings` with `YamlConfigSettingsSource` plus the
  existing reference-resolving source. No code change — the 4-tier chain
  already exists; this RFC simply promotes it to contract.
- **Node**: `zod` schema + `yaml` loader + custom env-var overlay
  (`src/config/loader.ts`). Exports eagerly-loaded `appConfig`.
- **Rust**: `config` crate with layered sources (`src/config.rs`).
  Exposes `AppConfig::load()` and a backwards-compatible `Config`
  shim for older call sites reading just `port` + `database_url`.

All three read the same YAML field names (snake_case) so operators who
learn one backend's `config/production.yaml` can reuse it when they
switch languages.

## Migration

Existing forge services generated before this RFC continue to work —
the new layered loader falls back to struct defaults when config
files are absent. Operators wanting to adopt layered config:

1. Create `config/defaults.yaml` with whatever baseline settings apply.
2. Create `config/<env>.yaml` files for each deployment environment.
3. Replace `process.env.X` / `std::env::var()` reads with
   `appConfig.X` / `AppConfig::load()`.

`UPGRADING.md` documents the env-var naming convention for operators
moving from ad-hoc environment variables to the `APP__*` prefix.

## Alternatives considered

- **Single source (env vars only)**: rejected — YAML config files make
  multi-environment deploys auditable and diff-friendly in a way `.env`
  files don't scale to.
- **One shared cross-language config file**: rejected — the three
  ecosystems each have idiomatic validation libraries (pydantic, zod,
  serde); forcing a cross-language schema language (protobuf / JSON
  Schema) would add friction without meaningful benefit.
- **Remote config (Consul / etcd)**: out of scope — the RFC is
  about the local load order. A fragment can opt into remote config by
  populating layer 5 (env vars) from a remote source at startup.
