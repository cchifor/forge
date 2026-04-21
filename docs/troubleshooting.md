# Troubleshooting

Common issues contributors + users hit when installing, generating, or
updating forge projects. Each entry lists the symptom, the root cause,
and the resolution.

## Installation + CLI

### `forge: command not found` after `uv tool install forge`

**Symptom.** `uv tool install forge` succeeds but `forge --version` reports
`command not found`.

**Cause.** `uv` installs console scripts into `~/.local/bin/` (Linux/macOS)
or `%USERPROFILE%\.local\bin\` (Windows) and that directory isn't on
your PATH.

**Fix.** Run `uv tool update-shell` once; it adds the `uv` tool bin to
your shell profile. Then restart your terminal.

### `ty` typechecker errors on a clean `uv sync`

**Symptom.** `uv run ty check forge/` reports unfamiliar rule names or
different diagnostic counts from what the docs describe.

**Cause.** ty is Astral's alpha typechecker — breaking changes between
alphas are expected. Epic X pins ty to an exact version in
`pyproject.toml`; `>=` constraints let uv resolve to a newer alpha that
might have regressed.

**Fix.** Verify `uv.lock` has the pinned version (`ty==0.0.29` as of
1.1.0-alpha.1). Re-run `uv sync --all-extras --dev`. If the error
persists, open the `Release dry-run` workflow or run
`tests/test_ty_canary.py` locally — a canary failure indicates ty
regressed, a forge typecheck failure indicates forge code needs updates.

## Generation

### Windows long-path errors during `forge new`

**Symptom.** `OSError: [WinError 206] The filename or extension is too
long` during Copier template render.

**Cause.** Windows's legacy MAX_PATH limit (260 chars). forge templates
can exceed this in deeply-nested fragment trees.

**Fix.**
1. Run the elevated PowerShell command once per machine:
   `Set-ItemProperty -Path HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem -Name LongPathsEnabled -Type DWORD -Value 1`
2. Configure git: `git config --system core.longpaths true`
3. Restart explorer.exe.

See [Microsoft's long-path enablement docs](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation?tabs=registry).

### Flutter post-generate fails with "SDK not found"

**Symptom.** `forge new --frontend flutter` reaches post-generate and
fails with `Could not find an option named "--sdk"` or similar.

**Cause.** No Flutter SDK on PATH, or a Flutter version mismatch. forge
supports Flutter ≥ 3.19.

**Fix.** Install Flutter via [`fvm`](https://fvm.app/) or the official
installer; `flutter doctor` should print a green summary. Re-run
generation — the post-generate step re-runs `flutter pub get` + `flutter
analyze`.

### Keycloak port conflict on `docker compose up`

**Symptom.** `keycloak_1 exited with code 1: Address already in use
(18080)` or similar.

**Cause.** Another service (often Tomcat, JDownloader, or a prior
Keycloak container) is bound to port 18080.

**Fix.** Either shut down the conflicting service, or regenerate with
a different Keycloak port: edit `forge.toml`'s `[forge.options]` to set
`keycloak.host_port` (for interactive mode) or regenerate with
`forge new --config stack.yaml` where `keycloak.port: 28080`.

### Generator hangs on first Copier prompt

**Symptom.** `forge new` prints the project-name prompt and stalls
indefinitely.

**Cause.** Copier's interactive mode needs a real TTY. You've piped
input or are running in an environment without a terminal (CI job with
no `--yes`, Emacs `compile-mode` shell).

**Fix.** Use the headless path: `forge --config stack.yaml --yes
--no-docker` or `forge --json --yes` for agent-driven generation. See
`docs/GETTING_STARTED.md` for the full headless recipe.

## `forge --update`

### "Another forge --update is running" (lock held)

**Symptom.** `forge --update` fails with:
`Another forge --update is running on <path> (pid 12345, started ...).
Wait for it to finish or remove <path>/.forge/lock if the other process
has crashed.`

**Cause.** Epic H's `.forge/lock` file — a live update is in progress in
another terminal, or a previous update crashed and left the lock
behind with a live-looking PID.

**Fix.**
- If another update is actually running: wait for it.
- If nothing else is running and the lock is stale: delete
  `<project_root>/.forge/lock` manually.
- Emergency escape hatch (use sparingly): `forge --update --no-lock`
  skips the lock entirely. Only safe when you're certain no other
  process is writing.

### Sentinel audit reports `orphan-begin` / `duplicate-begin` / `nested-pair`

**Symptom.** `forge --update` fails before applying any fragments:
`Sentinel audit found N issue(s) before re-applying fragments`.

**Cause.** Epic H's pre-apply sentinel integrity check — a hand-edit
has broken a `FORGE:BEGIN` / `FORGE:END` pair in a generated file.
Re-injecting over a broken pair silently double-injects, so forge
refuses.

**Fix.** Open each file + tag named in the error, restore the matching
BEGIN/END pair. The CHANGELOG's Epic H entry documents each issue
kind. A future release adds `forge --repair-sentinels` for automatic
remediation.

### Deprecation warning: "deprecated alias for ..."

**Symptom.** Warning log during `forge --update`:
`Option path 'rag.backend_name' is a deprecated alias for 'rag.backend'.
Run forge migrate-rename-options to rewrite forge.toml.`

**Cause.** Epic G — the option's canonical path was renamed. Your
`forge.toml` still has the old name; the resolver rewrites transparently
but nags until the file is persisted.

**Fix.** Run `forge migrate-rename-options` once. The codemod is
idempotent — safe to re-run.

## Docker + runtime

### `docker compose up` fails on first run with "pull access denied"

**Cause.** The `init-db` service or the generated backend image refers
to a private registry you haven't authenticated with.

**Fix.** `docker login <registry>` first; if the reference is wrong,
edit `deploy/docker-compose.yml` to point at the right registry.

### Services come up but `/health` returns 503

**Cause.** `observability.health` returns aggregate health — Postgres,
Redis, and (if enabled) Keycloak must all be reachable. One of them is
still booting or misconfigured.

**Fix.** Watch `docker compose logs -f` for the slow service (typically
Keycloak — 40s cold start). If the 503 persists, hit
`/health/details` (if the feature is enabled) for per-dependency
status.

## Packaging + release

### `uv build` includes unwanted cache files

**Symptom.** sdist or wheel contains `.ruff_cache/`, `.mypy_cache/`,
`__pycache__/`, or `node_modules/`.

**Cause.** Cache accumulation in your working tree outside the
standard exclusions. Epic DD's `tests/test_package_integrity.py`
catches this on every `package-integrity` CI run.

**Fix.**
1. Check `MANIFEST.in` has `recursive-exclude forge/templates */.<cache>/*`
   for the contaminant type.
2. Also check `pyproject.toml`'s
   `[tool.setuptools.exclude-package-data]`.
3. If you just want the bad build gone: `rm -rf dist/ build/
   forge.egg-info/` and retry.

### Release blocked: "No successful release-dryrun/ok check-run"

**Symptom.** Tagging a release triggers `release.yml` which fails
immediately in the `preflight-dryrun` job.

**Cause.** Epic Z requires a successful `release-dryrun.yml` run on
the same SHA within 72h before tagging.

**Fix.**
1. Actions → "Release dry-run" → Run workflow → wait for green.
2. Re-push the tag. `preflight-dryrun` consumes the check-run the
   rehearsal wrote and lets the publish proceed.

Emergency escape: set repo variable `SKIP_DRYRUN_GATE=true` in
Settings → Secrets and variables → Actions → Variables. Reset (or
delete) after the emergency release — the variable change is
auditable in the repo log.

## Contributing

### Test suite too slow on my machine

`make test` runs 700+ tests in ~5 min. For faster iteration:

- `uv run pytest tests/test_<module>.py` — single-file.
- `uv run pytest -k "name"` — filter by substring.
- `uv run pytest -x --no-cov` — stop on first failure, skip coverage.
- Integration tests are marked `@pytest.mark.e2e`,
  `@pytest.mark.package_integrity`, `@pytest.mark.runtime_smoke` —
  exclude with `-m "not e2e and not package_integrity"` (the default
  `test` CI job uses exactly this filter).

### ruff / ty disagreements between my editor and CI

- **Editor uses bundled ruff that's a year old** — `uv run ruff check` uses
  the pinned project version. Point your editor's "format on save" at
  the project's `uv`-managed ruff.
- **ty 0.0.x upgrades are deliberate** — see Epic X and `docs/troubleshooting.md`'s
  ty section above.
