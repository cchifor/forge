# platform-auth SDK tests

Tests for the platform-auth SDK: bearer-token verification (`AuthGuard`), JWKS cache, RFC 8693 `act` chains, in-memory testing helpers (`platform_auth.testing`).

## Layout

| Dir | Count | What |
|---|---|---|
| `unit/` | 11 | AuthGuard verification paths (happy + every rejection branch), JWKS cache lifecycle, may-act policies, testing helpers self-test. |

## Run

```sh
cd sdks/platform-auth
uv run pytest                              # all
uv run pytest -m unit
uv run pytest -m benchmark                 # opt-in performance benchmarks
```

## Dependencies

- **None**: every test wires its own JWKS via `httpx.MockTransport`; no real network.

## Coverage floor

- Today: **85%** (already at the strictest tier). Target: **85%** (T1; already there).

> This SDK is consumed by every service's verified-auth test path (e.g. deepagent's `verified_test_app` fixture imports `auth_env`). Stability of the testing helpers matters as much as the AuthGuard itself.

## Skip / xfail

None.

## See also

- `sdks/platform-auth/src/platform_auth/testing.py` — fixtures + token-builder consumed by services.
- `services/deepagent/tests/web/conftest.py` — example of a service wiring `auth_env` + `verified_test_app`.
