# Matrix-Nightly CI Failure Analysis & Improvement Plan

## Context

The nightly matrix CI job on `cchifor/forge` (run [26076244446], 2026-05-19) failed with **15 of 23 matrix legs red** while every prerequisite gate / aggregator job succeeded. PR #53 (merged 2026-05-18) fixed 3 pre-existing bugs but left more open. This plan, after a Codex round-1 review and on-codebase verification, groups the 15 failures into **4 fix clusters plus 1 investigation cluster**:

- **A** — `project_slug` not propagated to backend Copier contexts (Rust + Node only). 6 smoke fixes.
- **B** — Roundtrip lane lacks exclusions for build-generated artefacts. 5 roundtrip fixes.
- **C** — Stripper completeness for stateless Python (cli/__init__ + qualified loader.py field). 0 nightly fixes today (latent bug — stateless_py is not on the smoke lane). Worth fixing in this PR because it unblocks future `stateless_py` smoke and proves the stateless surface is internally consistent.
- **D** — `stateless_py` roundtrip FR1 violation: stripper destroys fragment injection on `lifecycle.py` and leaves manifest stale. 1 roundtrip fix + 1 silent-security-regression fix.
- **E** (investigation, not a fix on this PR) — `py_svelte_min / py_vue_noauth / py_vue_full` smoke: api-1 exits 3 for reasons currently undiagnosable. Requires the compose-log artifacts from the next nightly (PR #53 cc905cf landed the diagnostic capture; this run was BEFORE that artifact path was wired into the nightly workflow → no logs to inspect yet).

**Verified fix coverage on this PR: 12 of 15 nightly red legs.** The remaining 3 (Cluster E) are explicitly deferred to a follow-up after diagnostic data arrives.

| Lane / Scenario | Symptom | Cluster |
|---|---|---|
| smoke (rust_svelte_min, rust_vue_full, multi_all_three) | `mkdir -p services//src/bin` — empty service slug | A |
| smoke (node_vue_full, multi_py_node) | `npx prisma generate` exit 1 (wrong WORKDIR) | A |
| smoke (node_svelte_min) | `npm install --workspaces` exit 1 (wrong WORKDIR) | A |
| smoke (py_svelte_min, py_vue_noauth, py_vue_full) | `container <…>-api-1 exited (3)` (NOT a stripper failure — these scenarios use `database.mode=generate`) | **E** |
| roundtrip (node_only_headless) | diff first file: `services/api/node_modules/.prisma/client/edge.js` | B |
| roundtrip (node_svelte_min, py_svelte_min, rust_svelte_min) | diff first file: `apps/frontend/.svelte-kit/generated/server/internal.js` | B |
| roundtrip (multi_py_node) | diff first file: `apps/frontend/scripts/__pycache__/feature_templates.cpython-314.pyc` | B |
| roundtrip (stateless_py) | `FR1 violation: 1 block/files candidate from fragment 'pii_redaction': src/app/core/lifecycle.py` | D |

---

## Cluster A — `project_slug` not propagated to backend Copier contexts (6 smoke fixes)

### Diagnosis
- `forge/variable_mapper.py:34-63` `backend_context()` does not set `project_slug`. The frontend builders at lines 164 / 200 / 237 *do* set `"project_slug": config.frontend_slug,`.
- Concrete render breakage by language:
  - **Rust** — `forge/templates/services/rust-service-template/template/Dockerfile.jinja:13,34,40-44,49-50` renders `services//src/...` (empty slug); `cargo build --workspace` exits 101.
  - **Node** — `forge/templates/services/node-service-template/template/Dockerfile.jinja:14,30,38,58,63-66,83` renders `WORKDIR /workspace/services/`; `npm install --workspaces` and `npx prisma generate` run in the wrong tree and fail.
  - **Python** — the Dockerfile uses `{{ project_slug }}` **only inside a header comment** (line 8: `-t {{ project_slug }} .`), not in any path. The Python compose fragment and entrypoint paths, however, do consume the variable for hyphenated service names (e.g. `py-svc` in `multi_py_node`). Python smoke isn't observably broken by this in the current nightly because the failing Python smoke legs (Cluster E) crash long after the build succeeds.
- `BackendConfig` (`forge/config/_backend.py:179-198`) has no `slug` field. `forge/generator.py` directories its backends as `services/<bc.name>` (per Codex's verification), so `bc.name` is the path slug.
- **Validation-drift edge case:** `BackendConfig.name` allows underscores while the per-language `copier.yml` validators enforce kebab-case on `project_name`. A backend named `py_svc` would pass `BackendConfig` validation, render under `services/py_svc/`, but fail downstream copier validation. None of the failing scenarios trip this today (all use `api` or hyphenated names like `py-svc`), but the test added below pins it.

### Fix
Add one key to `backend_context()`:

```python
# forge/variable_mapper.py:47-55 (inside backend_context)
ctx: dict[str, Any] = {
    "project_name": bc.name,
    "project_slug": bc.name,           # <-- ADD; backend service slug for Dockerfile + Cargo + compose
    "project_description": bc.description,
    ...
}
```

### Test
- `tests/test_variable_mapper.py` — extend the `test_backend_context_*` cases to assert `project_slug == bc.name` for all three languages.
- Add `test_backend_context_rejects_underscore_name_pre_copier_validation` (or extend the validator's tests) — pin the validation-drift edge case so a future plugin backend can't slip in an underscore-named slug.
- Re-render the 3 Rust/Node smoke scenarios locally:
  ```bash
  uv run python tests/matrix/runner.py --scenario rust_svelte_min --lane smoke
  uv run python tests/matrix/runner.py --scenario node_svelte_min --lane smoke
  uv run python tests/matrix/runner.py --scenario multi_py_node --lane smoke   # hyphenated py-svc + node-svc
  ```
  All three should reach `docker compose up --wait` healthy.

---

## Cluster B — Roundtrip lane lacks exclusions for build-generated artefacts (5 roundtrip fixes)

### Diagnosis
- `tests/matrix/runner.py:924-1007` `_diff_project_trees_normalized` only filters `.git/` + `.copier-answers.yml` (`is_excluded`, lines 950-953).
- Frontend `post_generate.py` runs `npm install` / `npm run build` and the multi-backend Python codegen runs `python scripts/feature_templates.py` — producing `node_modules/`, `.svelte-kit/`, `.prisma/`, `__pycache__/`, etc. These are non-deterministic across two consecutive generates (timestamps, source maps, dependency-resolution order).
- The golden snapshot test (`tests/test_golden_snapshots.py:88-126`) carries an exclusion list, but mirroring it verbatim is wrong:
  - **It's incomplete for FR2.** It omits `.svelte-kit/`, which is the very first offender in 3 of 5 failing roundtrip legs. It also omits `.venv/`, `.pytest_cache/`, `.mypy_cache/`, `build/`, `dist/` (Vue), all of which can leak from post-generate.
  - **Some golden entries hide real FR2 drift** if propagated. Specifically, `/api/generated/` (hey-api openapi-ts output) and `auto-imports.d.ts` (Vue codegen) are deterministic when produced on the same host; if they differ between project_a and project_b, that's a real bug. `package-lock.json` is host-deterministic with frozen lockfiles and shouldn't be ignored in FR2 either.
- The shared helper needs care: `tests/matrix/runner.py` is invoked as `uv run python tests/matrix/runner.py` (script mode). The file's own docstring notes the repo root isn't on `sys.path` initially. Co-locating the helper inside the `tests/` package without a `sys.path` prepend would silently fail at the first `from tests._artefact_filters import ...`.

### Fix
1. **New file** `tests/_artefact_filters.py` — explicit, curated list with rationale per entry:
   ```python
   """Path-exclusion predicates shared between FR2 (matrix roundtrip) and
   golden-snapshot tests. Each entry is documented with the reason it's
   non-deterministic across two generates on the same host.
   """
   def is_generated_artefact(rel: str) -> bool:
       # VCS internals
       if rel == ".git" or rel.startswith(".git/") or "/.git/" in rel:
           return True
       # Copier internals — _commit + _src_path drift across re-runs
       if rel.endswith(".copier-answers.yml"):
           return True
       # Python bytecode + tool caches (timestamp-dependent)
       if "/__pycache__/" in rel or rel.startswith("__pycache__/"):
           return True
       if rel.endswith(".pyc"):
           return True
       for cache in ("/.ruff_cache/", "/.pytest_cache/", "/.mypy_cache/", "/.venv/"):
           if cache in rel or rel.startswith(cache.lstrip("/")):
               return True
       # Node — npm install resolution order + Prisma codegen are unstable
       if "/node_modules/" in rel or rel.startswith("node_modules/"):
           return True
       # SvelteKit generated output (build-time only, regenerated each `npm run build`)
       if "/.svelte-kit/" in rel or rel.startswith(".svelte-kit/"):
           return True
       # Frontend build output
       for build in ("/build/", "/dist/"):
           if build in rel:
               return True
       # Cargo target/ — present only if a previous cargo build leaked it
       if "/target/" in rel or rel.startswith("target/"):
           return True
       return False
   ```
   Note: this list is **narrower than the golden-snapshot list**. Specifically, we do NOT include `package-lock.json`, `auto-imports.d.ts`, or `/api/generated/` — those are deterministic on the same CI host, and a genuine FR2 drift in them is exactly the kind of bug roundtrip should catch.

2. Update `tests/test_golden_snapshots.py:85-126` to also call `is_generated_artefact()` as the first check inside the loop (continue on True), but keep the additional `package-lock.json` / `auto-imports.d.ts` / `/api/generated/` exclusions inline as snapshot-only (with a clarifying comment) — those are legitimately host-asymmetric for snapshots, just not for FR2.

3. Update `tests/matrix/runner.py` — both the `is_excluded` in `_diff_project_trees_normalized` (line 950) and the import. Because `runner.py` runs in script mode, prepend the repo root to `sys.path` before importing:
   ```python
   import sys
   from pathlib import Path
   _REPO_ROOT = Path(__file__).resolve().parents[2]
   if str(_REPO_ROOT) not in sys.path:
       sys.path.insert(0, str(_REPO_ROOT))
   from tests._artefact_filters import is_generated_artefact  # noqa: E402
   ```
   (Mirror this in golden-snapshots; pytest already puts the repo root on `sys.path`, but the prepend is harmless.)

### Test
- New unit test in `tests/matrix/test_runner_diagnostics.py` (file already exists from PR #53): seed two scratch directories where one has only `node_modules/x`, `.svelte-kit/y`, `__pycache__/z.pyc`, the other empty; assert `_diff_project_trees_normalized()` returns `[]`.
- Re-run lane D for `py_svelte_min`, `multi_py_node`, `rust_svelte_min`, `node_svelte_min`, `node_only_headless` locally; all five should return `OK`.

---

## Cluster C — Stripper completeness for stateless Python (latent bug, not on red legs today)

These are the two follow-ups PR #53 documented. **Neither bug is on the failing-leg list today** — `py_svelte_min / py_vue_noauth / py_vue_full` all use the default `database.mode=generate` (see `tests/matrix/scenarios.yaml:30-83,297-317`), so `strip_python_database()` is never called for them. Their smoke failures (Cluster E) come from somewhere else.

What these fixes DO unblock: when the team eventually opts `stateless_py` into the smoke lane, the container needs to start cleanly. Today, both bugs would crash it before uvicorn binds. They also tighten the stateless contract — an internally inconsistent stateless build is a footgun.

### C1 — `cli/__init__.py` keeps imports of deleted `cli/db.py`
`forge/strippers.py:52-81` `_PYTHON_DB_TARGETS` deletes `src/app/cli/db.py` but no stripper rewrites `src/app/cli/__init__.py`, which contains:
```python
from app.cli.db import db_app                            # line 3
...
cli.add_typer(db_app, name="db", help="Database migrations")   # line 9
```
At first `python -m app` import → `ModuleNotFoundError: No module named 'app.cli.db'`. Plain Python exits 1 (not uvicorn's 3) per Codex's clarification, which further confirms this is not the cause of the observed exit-3 smoke failures.

**Fix** — add `_strip_cli_init()`:
```python
_CLI_DB_IMPORT_RE = re.compile(r"^from app\.cli\.db import [^\n]*\n", re.MULTILINE)
_CLI_DB_REGISTER_RE = re.compile(r"^cli\.add_typer\(\s*db_app[^\n]*\n", re.MULTILINE)

def _strip_cli_init(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = _CLI_DB_IMPORT_RE.sub("", text)
    text = _CLI_DB_REGISTER_RE.sub("", text)
    path.write_text(text, encoding="utf-8")

# strip_python_database(...) — after _strip_loader_db_refs():
_strip_cli_init(backend_dir / "src/app/cli/__init__.py")
```

### C2 — `_strip_loader_db_refs` misses qualified field reference in `loader.py`
`loader.py:29` declares `db: domain.DbConfig = domain.DbConfig()`. `_strip_config_domain` removes the class from `domain.py`; `_strip_loader_db_refs` only strips IMPORT lines and doesn't match the qualified `domain.DbConfig` reference. At runtime → `AttributeError` at module load. **This path is the most plausible exit-3 source for any future stateless smoke run** (Codex notes `server.py` swallows `get_settings` failures via try/except, and uvicorn then re-imports `app.main` which loads loader → exit 3).

**Fix** — extend `_strip_loader_db_refs`:
```python
def _strip_loader_db_refs(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^from [^\n]*import[^\n]*DbConfig[^\n]*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r",\s*DbConfig\b", "", text)
    text = re.sub(r"\bDbConfig,\s*", "", text)
    # NEW — strip the qualified Settings field too
    text = re.sub(r"^[ \t]+db:\s*(?:domain\.)?DbConfig[^\n]*\n", "", text, flags=re.MULTILINE)
    path.write_text(text, encoding="utf-8")
```

### Test
- `tests/test_strippers.py`:
  - `test_strip_cli_init_drops_db_app_import_and_registration`
  - `test_strip_loader_db_refs_drops_qualified_field`
- Stateless smoke verification is **out of scope** for this PR — `stateless_py` is roundtrip-only in `scenarios.yaml`, and adding it to the smoke lane would also need the Dockerfile/alembic side adjusted (the Python Dockerfile unconditionally copies `alembic/`, which doesn't exist after the stripper runs). Leave that for the follow-up that opts stateless into smoke.

---

## Cluster D — `stateless_py` FR1 violation: stripper destroys fragment injection on `lifecycle.py` (1 roundtrip fix + silent-security-regression fix)

### Diagnosis (confirmed via code trace + Codex round-1 review)
- The FR1 check (`tests/matrix/runner.py:736-753`) calls `harvest_project(project_a)` and asserts `[c for c in candidates if c.kind in ("block", "files")] == []`. The single offender's `fragment` is `pii_redaction` (per the observed error message), not `base-template`.
- `forge/features/middleware/templates/pii_redaction/python/inject.yaml` injects, BEFORE the `FORGE:LIFECYCLE_STARTUP` marker in `src/app/core/lifecycle.py`:
  ```python
  from app.core.pii_redaction import install_pii_filter
  install_pii_filter()
  ```
- Pipeline order in `forge/generator.py`:
  1. (~line 147) `_record_tree()` records every base-template file with `origin="base-template"` and its SHA.
  2. Feature/fragment application — the `pii_redaction` fragment runs `record(path, origin="fragment", fragment_name="pii_redaction", ...)` on `lifecycle.py` *after* injecting the two-line snippet. Manifest now has the **fragment** as the owner of `lifecycle.py`.
  3. (~line 180) `strip_python_database(backend_dir)` overwrites `src/app/core/lifecycle.py` with `_STATELESS_LIFECYCLE` (a hand-written constant in `forge/strippers.py:88-184`). **This silently erases the pii_redaction injection**, including the `# FORGE:LIFECYCLE_STARTUP` marker comment which is an *injection point*, not a paired sentinel (Codex critique 13 — verified).
  4. (~line 348) `forge.toml` is written from the now-stale collector — the manifest still says "this file is owned by fragment `pii_redaction`, with hash `<original>`".
- At harvest time, the `FileExtractor` sees a fragment-origin row whose recorded hash doesn't match the disk content → `kind="files"` candidate. FR1 fails.

The "naïve fix" (have the stripper call `collector.record(...)` again to refresh the hash) would make FR1 pass **but would not restore the lost `install_pii_filter()` call** — a silent security regression where the default-enabled PII redaction stops actually filtering logs. That's worse than the current red CI signal.

### Fix
Re-apply compatible fragment injections after the stripper runs. Two implementation shapes:

**D1 (preferred — reorder the generator pipeline)**

Move `strip_python_database()` to BEFORE fragment application in `forge/generator.py`:
```
1. _record_tree(base template)
2. strip_python_database(backend_dir, collector=collector)     # was step 3
3. apply features/fragments                                    # was step 2 — now sees stateless lifecycle.py
4. write forge.toml
```
Then in `strip_python_database`, after each `target.write_text(content)`, call:
```python
collector.record(
    target,
    origin="base-template",
    template_name=template_name,     # propagate from the caller in generator.py
    template_version=template_version,
)
```
The actual `ProvenanceCollector.record(...)` signature (`forge/sync/provenance.py:111`) takes keyword args: `path, *, origin, fragment_name=None, fragment_version=None, template_name=None, template_version=None`. There is no `record_file(path, text)` method — Codex critique 12, verified by reading the class definition. The function also auto-computes `sha256_of(path)` and `emitted_at`, so the stripper just needs to call it after writing.

After this reorder, fragments like `pii_redaction` apply their injection on top of the stateless lifecycle.py. The injection still lands BEFORE the `FORGE:LIFECYCLE_STARTUP` marker — the stateless replacement keeps that marker at the end of `_setup_logging` (`forge/strippers.py:182`). The fragment's `record(origin="fragment", fragment_name="pii_redaction")` call then becomes the manifest's owner of the final lifecycle.py, with the correct hash including the injection.

Required code changes:
- `forge/generator.py` — move the `strip_python_database` call up to just after `_record_tree`. Pass `collector` and the base-template name+version (already available locally).
- `forge/strippers.py:335` — extend signature: `def strip_python_database(backend_dir: Path, *, collector: ProvenanceCollector | None = None, template_name: str | None = None, template_version: str | None = None)`. Keep all three keyword args optional so existing test callers don't break.
- `forge/strippers.py:365-378` — after each `target.write_text(content)`, if `collector is not None`, call the proper `collector.record(target, origin="base-template", template_name=..., template_version=...)`.

**D2 (fallback — keep the order, re-apply compatible injections post-strip)**

If the reorder is too invasive (e.g. another fragment depends on seeing the DB-backed lifecycle to do something else), keep the current order and have the stripper rescan applied fragments for a "compatible-with-stateless" allowlist (just `pii_redaction` today), then re-apply their injection into the stateless file before re-recording. This is more code and more surface for drift; only fall back to it if D1 surfaces an ordering dependency.

### Test
1. **Unit (correct API)** — `tests/test_strippers.py::test_strip_python_database_records_provenance_with_collector`:
   - Construct a fake `ProvenanceCollector(project_root=tmp_path)`.
   - Run `strip_python_database(backend_dir, collector=collector, template_name="python-service-template", template_version="1.0.0")`.
   - Assert `collector.records["services/api/src/app/core/lifecycle.py"]` exists with `origin="base-template"` and a non-empty sha.

2. **Functional (security regression guard)** — `tests/test_strippers.py::test_strip_python_database_preserves_pii_redaction_injection`:
   - Run the full `generate()` for a synthetic config matching `stateless_py` (with default `middleware.pii_redaction`).
   - Assert the rendered `src/app/core/lifecycle.py` contains both `from app.core.pii_redaction import install_pii_filter` AND `install_pii_filter()`. Without this guard, D1 could regress silently if the pipeline reorder breaks the injection point.
   - Bonus: assert harvesting the rendered project yields zero `kind in ("block","files")` candidates.

3. **Integration** — `tests/matrix/test_runner_diagnostics.py::test_stateless_py_roundtrip_fr1_passes`:
   - Drive `run_lane_roundtrip(stateless_py_scenario)` end-to-end; assert `status == "ok"`.

---

## Cluster E (investigation, NOT a fix on this PR) — `py_svelte_min / py_vue_noauth / py_vue_full` smoke exit 3

### Why this isn't fixed in this PR
The compose-log diagnostic capture (PR #53 commit cc905cf) landed AFTER the 2026-05-19 nightly was scheduled, so the failing run has no captured container logs. The next nightly will capture them; we revisit then.

What we know already:
- All three scenarios use `database.mode=generate` (default). Strippers are NOT called → Cluster C fixes don't apply.
- For `py_svelte_min`: postgres healthy, **`api-migrate` exited**, then `api-1 exited (3)`. The migrate-container exit is suspicious — it precedes the api-1 failure and could be the proximate cause.
- For `py_vue_noauth`: frontend healthy, `api-1 exited (3)`.
- For `py_vue_full`: keycloak healthy (last status reported); no `api` status shown in the truncated log, may share root cause.

### Strongest hypotheses (to verify with the next nightly's compose logs)
1. **Auth config validation fails in `ENV=production`.** Both `py_svelte_min` and `py_vue_noauth` have `include_keycloak: false`, so no auth fragment injects credentials. The Dockerfile sets `ENV=production` (`forge/templates/services/python-service-template/template/Dockerfile.jinja:81`), so `production.yaml` loads — and the shipped file only contains `security.auth.enabled: true` with no `server_url`, `realm`, `client_id`, etc. If `weld.core.domain.config.AuthConfig` requires those fields, pydantic validation raises during `Settings()` instantiation. Uvicorn then exits 3 because the ASGI factory `app.main:app` failed to import (`server.py:24` catches the `get_settings()` exception, but `uvicorn.run("app.main:app", ...)` re-loads the app, which calls `get_settings()` again unprotected — see Codex critique 8).
2. **alembic migration fails.** The `api-migrate` exit on `py_svelte_min` could be from `alembic upgrade head` failing (e.g. postgres connection string, missing migration file, etc.). Worth checking the migrate container's logs first.

### Verification step (post-next-nightly)
After the next nightly run lands, pull the `compose-logs-py_svelte_min` (and `_py_vue_noauth`, `_py_vue_full`) artifacts, inspect `api-1`'s stderr, and open a follow-up PR. Suggested investigation commands:
```bash
gh run download <run-id> --name compose-logs-py_svelte_min
ls compose-logs/
cat compose-logs/api-1.log
cat compose-logs/api-migrate-1.log
```

---

## Sequencing & Verification

**PR shape:** all four fix clusters (A, B, C, D) land in a single PR titled `fix(matrix): unblock 12 of 15 nightly red lanes (project_slug, FR2 exclusions, stripper completeness, stateless lifecycle pipeline)`. Cluster E stays open as a follow-up issue; the PR description references it explicitly so reviewers don't conflate "12 fixes" with "100% green".

Implementation order inside the PR:
1. **Cluster A** (`forge/variable_mapper.py` + `tests/test_variable_mapper.py`) — smallest change, blocks the most legs.
2. **Cluster C** (`forge/strippers.py` + `tests/test_strippers.py`) — small, self-contained, but useful baseline before D since D extends the same module.
3. **Cluster D** (`forge/generator.py` reorder + `forge/strippers.py` collector hook + functional test) — biggest behaviour change; do it after C so the diff is easier to read.
4. **Cluster B** (`tests/_artefact_filters.py` NEW + `tests/test_golden_snapshots.py` + `tests/matrix/runner.py`) — test-runner only; land last because it can mask real product drift if the exclusion list is too broad.

| Step | Cluster | File(s) touched | Verifies which scenarios |
|---|---|---|---|
| 1 | A | `forge/variable_mapper.py`, `tests/test_variable_mapper.py` | rust_svelte_min, rust_vue_full, multi_all_three, node_svelte_min, node_vue_full, multi_py_node (smoke) |
| 2 | C | `forge/strippers.py`, `tests/test_strippers.py` | (no current red leg; latent stateless smoke unblocker) |
| 3 | D | `forge/generator.py`, `forge/strippers.py`, `tests/test_strippers.py`, `tests/matrix/test_runner_diagnostics.py` | stateless_py (roundtrip), + PII-redaction security guard |
| 4 | B | `tests/_artefact_filters.py` (NEW), `tests/test_golden_snapshots.py`, `tests/matrix/runner.py` | node_only_headless, node_svelte_min, py_svelte_min, rust_svelte_min, multi_py_node (roundtrip) |

### End-to-end verification

```bash
# Step 1 — fast unit tests for each cluster
uv run pytest tests/test_variable_mapper.py tests/test_strippers.py tests/test_golden_snapshots.py tests/matrix/test_runner_diagnostics.py -x

# Step 2 — scenario-specific probes that cover each fix
uv run python tests/matrix/runner.py --scenario stateless_py     --lane roundtrip   # Cluster D
uv run python tests/matrix/runner.py --scenario py_svelte_min    --lane roundtrip   # Cluster B
uv run python tests/matrix/runner.py --scenario multi_py_node    --lane roundtrip   # Cluster B + hyphenated slugs
uv run python tests/matrix/runner.py --scenario node_svelte_min  --lane smoke       # Cluster A (node WORKDIR)
uv run python tests/matrix/runner.py --scenario rust_svelte_min  --lane smoke       # Cluster A (rust paths)
uv run python tests/matrix/runner.py --scenario multi_all_three  --lane smoke       # Cluster A (3 backends)

# Step 3 — full matrix run (slow — ~25 min total) to catch regressions
uv run python tests/matrix/runner.py --lane smoke
uv run python tests/matrix/runner.py --lane roundtrip
uv run python tests/matrix/runner.py --lane update    # regression check — should stay green

# Step 4 — log-aware probe for the deferred Cluster E scenarios
FORGE_MATRIX_LOG_DIR=$PWD/compose-logs \
  uv run python tests/matrix/runner.py --scenario py_svelte_min --lane smoke
ls compose-logs/   # confirms PR #53's diagnostic capture is working; logs go into the follow-up
```

Expected post-PR nightly state: **12 of 15 previously red legs green**; the remaining 3 (Cluster E) red with `compose-logs-*` artifacts populated. Out-of-scope items kept on the follow-up backlog:
1. `[FAIL] Linting (eslint)` warnings in many `post_generate.py` outputs — pre-existing template noise, not a runner.py exit code.
2. The Cluster A fix may surface a secondary `keycloak_client_id` mismatch in compose fragments (the Vue/Svelte builders fall back to `frontend_slug` when the per-frontend client id is unset). Verify after Cluster A renders correctly.
3. Adding `stateless_py` to the smoke lane requires Dockerfile/alembic adjustments not in this PR.

## Critical Files Referenced

- `forge/variable_mapper.py:34-63` (A — `backend_context()`)
- `forge/templates/services/{rust,node}-service-template/template/Dockerfile.jinja` (A — paths consume `project_slug`)
- `forge/templates/services/python-service-template/template/Dockerfile.jinja:8` (A — Python only references `project_slug` in a header comment, so it's not the cause of Python smoke failures)
- `forge/config/_backend.py:179-198` (A — `BackendConfig` with `bc.name` as path slug)
- `tests/matrix/runner.py:924-1007` (B — `_diff_project_trees_normalized` + `is_excluded`)
- `tests/test_golden_snapshots.py:85-126` (B — reference exclusion list, NOT a verbatim mirror target)
- `forge/strippers.py:335-353` `strip_python_database` (C/D — orchestrator)
- `forge/strippers.py:515-524` `_strip_loader_db_refs` (C2)
- `forge/templates/services/python-service-template/template/src/app/cli/__init__.py` (C1 — rewritten by new `_strip_cli_init`)
- `forge/templates/services/python-service-template/template/src/app/core/config/loader.py:29` (C2 — field stripped by extended regex)
- `forge/strippers.py:88-184` `_STATELESS_LIFECYCLE` + `_write_stateless_replacements` (D — clobbers fragment injection)
- `forge/sync/provenance.py:111-146` `ProvenanceCollector.record(...)` (D — actual API surface)
- `forge/features/middleware/templates/pii_redaction/python/inject.yaml` (D — injection that the stripper destroys today)
- `forge/generator.py:147-181,348` (D — pipeline order to reverse)
- `tests/matrix/runner.py:736-753` FR1 check (D — assertion being unblocked)
- `tests/matrix/scenarios.yaml:30-83,297-317,389-407` (E and C scope — confirms which scenarios run strippers)

<!-- codex-review-status: complete -->
