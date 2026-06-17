# Operations runbook

Operator-facing notes for running this Rust/Axum service in production.
See `OBSERVABILITY.md` for tracing, metrics, and logging.

## Configuration order

Settings load lowest-to-highest priority (later wins):

1. Serde struct defaults (`#[serde(default)]`, in code).
2. `config/defaults.yaml`.
3. `config/{ENV}.yaml` — selected by `ENV` (or `APP_ENV`), default `development`.
4. `.secrets.yaml` — loaded if present.
5. `APP__*` environment variables — nested with `__`, e.g.
   `APP__DB__URL`, `APP__SERVER__PORT`. Values are type-parsed before binding.

**Env vars always win.** As a final fallback the `db.url` field also reads the
standard `DATABASE_URL` env var, matching the runtime connection pool.

## Database migrations

Unlike the Python/Node templates, migrations are **not** run automatically on
server startup. A dedicated `migrate` binary (built from `src/bin/migrate.rs`)
applies them via `sqlx::migrate!("./migrations")`:

```sh
# one-shot, before rolling out the app:
DATABASE_URL=... /app/migrate
# or, in compose, run the bundled one-shot migrate service:
docker compose run --rm <service>-migrate
```

Run the migrate step to completion before (or as an init container alongside)
the app rollout. `sqlx`'s migrator records applied versions, so re-running is a
no-op — safe to run on every deploy.

## Graceful shutdown

`main` serves with `axum::serve(...).with_graceful_shutdown(shutdown_signal())`.
`shutdown_signal()` awaits `SIGINT` (Ctrl-C) or `SIGTERM` (rollout); on either,
Axum stops accepting new connections and drains in-flight requests before
exiting, logging `shutdown signal received — draining connections`. Set the
container termination grace period to exceed your slowest request.

## Health checks

The service exposes liveness/readiness endpoints under `/api/v1/health/`
(`/live`, `/ready`). Wire `/live` to the liveness probe and `/ready` to the
readiness probe so traffic only routes once dependencies are reachable.
