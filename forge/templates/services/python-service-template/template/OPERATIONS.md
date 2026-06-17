# Operations runbook

Operator-facing notes for running this Python/FastAPI service in production.
See `OBSERVABILITY.md` for tracing, metrics, and logging.

## Configuration order

Settings load lowest-to-highest priority (later wins):

1. Pydantic model defaults (in code).
2. `config/default.yaml`.
3. `config/{ENV}.yaml` — selected by the `ENV` env var (default `development`).
4. `.secrets.yaml` — gitignored local overrides.
5. `APP__*` environment variables — nested with `__`, e.g.
   `APP__DB__URL`, `APP__SERVER__PORT`, `APP__SECURITY__AUTH__ENABLED`.

`config/production.yaml` references deployment values via `${VAR}` placeholders
that resolve from the environment. **Env vars always win**, so prefer them for
secrets and per-environment values; keep `config/*.yaml` for shape and defaults.

On startup the loader logs which sources it found and their precedence — check
that line first when a value isn't what you expect.

## Database migrations & advisory lock

Migrations run automatically on container start via `entrypoint.sh`:

```sh
alembic upgrade head      # then: python -m app server run
```

Alembic's `env.py` takes a Postgres **transaction-level advisory lock**
(`pg_advisory_xact_lock`) before upgrading, so when several replicas boot at
once exactly one applies the migration and the rest wait, then no-op. The run
is idempotent — re-running on an up-to-date database is a no-op.

For a SQLite dev database the startup path creates tables directly when the
database is empty (no Alembic needed).

To run migrations out-of-band (e.g. a pre-deploy job) run `alembic upgrade head`
against the target `DATABASE_URL` and start the app with migrations already
applied.

## Graceful shutdown

The app uses a FastAPI lifespan context manager. Uvicorn translates `SIGTERM`
(rollout) and `SIGINT` (Ctrl-C) into lifespan teardown: in-flight requests
drain, then `_on_shutdown()` closes the DI container and logs
`Shutdown complete`. Give the container a termination grace period long enough
for your slowest request (Kubernetes `terminationGracePeriodSeconds`, default
30s, is usually fine).

## Health checks

The service exposes liveness and readiness endpoints under
`/api/v1/health/` (`/live`, `/ready`). Wire `/live` to the container liveness
probe (process up) and `/ready` to the readiness probe (dependencies — DB,
Redis, etc. — reachable) so traffic is only routed once dependencies are up.

## Workers & scaling

`server.max_workers` (default 4 in `production.yaml`) sets the Uvicorn worker
count per container. Scale horizontally with replicas; the advisory lock keeps
concurrent boots migration-safe.
