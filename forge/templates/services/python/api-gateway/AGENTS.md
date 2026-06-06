# `api-gateway` backend variant (Python)

Two-stage Copier variant: renders the shared
`services/python-service-template` base, then overlays a thin gateway delta.

## What the overlay adds

- `src/app/gateway/downstreams.py` — reads `INTERNAL_SERVICE_URL_<NAME>` env
  vars (injected into the gateway container by P4.2 synthesis) into a
  `{service_name_lower: internal_url}` map. Read live on each call; pure stdlib.
- `src/app/gateway/s2s_client.py` — async client-credentials token client.
  Reads `GATEKEEPER_CLIENT_ID` / `GATEKEEPER_CLIENT_SECRET` /
  `GATEKEEPER_TOKEN_ENDPOINT`, mints + in-memory caches a bearer token (re-mints
  near expiry), and exposes `auth_header(audience=...)`. Returns `{}` when creds
  are absent so the gateway degrades gracefully. Depends only on `httpx` +
  stdlib (no `platform_auth` SDK).
- `src/app/api/v1/endpoints/gateway.py` — FastAPI router with
  `GET /gateway/downstreams` (the registry) and `GET|POST
  /gateway/api/{service}/{path:path}` (httpx proxy: 404 unknown service, 502 on
  transport error). Dependency-light — no auth requirement, builds in any
  config.

## The one base file the overlay owns

`src/app/api/v1/api.py.jinja` is overwritten: identical to the base plus
`gateway` in the endpoint import and a `gateway.router` registration at
`/gateway`, before the `# FORGE:API_ROUTER_REGISTRATION` marker. Keep it in
sync with the base file (the only base file this overlay re-owns).

`httpx>=0.28.0` is already a base dependency, so no `pyproject` overlay is
needed.
