# Matrix-Nightly CI Failure Analysis & Improvement Plan

## Context

The nightly matrix CI job on `cchifor/forge` (run [26076244446], 2026-05-19) failed with **15 of 23 matrix legs red** while every prerequisite gate / aggregator job succeeded. PR #53 (merged 2026-05-18) fixed 3 pre-existing bugs but explicitly left at least 3 more open — those have surfaced again in the latest nightly along with two additional root causes that PR #53 didn't enumerate. This plan groups the 15 failures into **4 root-cause clusters** and proposes the minimal fix per cluster.

| Lane / Scenario | Symptom | Cluster |
|---|---|---|
| smoke (rust_svelte_min, rust_vue_full, multi_all_three) | `mkdir -p services//src/bin` — empty service slug | A |
| smoke (node_vue_full, multi_py_node) | `npx prisma generate` exit 1 (wrong WORKDIR) | A |
| smoke (node_svelte_min) | `npm install --workspaces` exit 1 (wrong WORKDIR) | A |
| smoke (py_svelte_min, py_vue_noauth, py_vue_full) | `container <…>-api-1 exited (3)` | C |
| roundtrip (node_only_headless) | diff first file: `services/api/node_modules/.prisma/client/edge.js` | B |
| roundtrip (node_svelte_min, py_svelte_min, rust_svelte_min) | diff first file: `apps/frontend/.svelte-kit/generated/server/internal.js` | B |
| roundtrip (multi_py_node) | diff first file: `apps/frontend/scripts/__pycache__/feature_templates.cpython-314.pyc` | B |
| roundtrip (stateless_py) | `FR1 violation: 1 block/files candidate: pii_redaction/src/app/core/lifecycle.py` | D |

---

## Cluster A — `project_slug` not propagated to backend Copier contexts (6 smoke failures)

### Diagnosis
- `forge/variable_mapper.py:34-63` `backend_context()` builds the Copier data dict for **every** backend template but does not set `project_slug`.
- The three frontend builders at lines 164 / 200 / 237 *do* set `"project_slug": config.frontend_slug,`.
- The Rust + Node + Python Dockerfile templates all reference `{{ project_slug }}`:
  - `forge/templates/services/rust-service-template/template/Dockerfile.jinja:13,34,40-44,49-50` → renders as `services//src/...` (empty), causing `cargo build --workspace` to exit 101.
  - `forge/templates/services/node-service-template/template/Dockerfile.jinja:14,30,38,58,63-66,83` → renders as `WORKDIR /workspace/services/` (no service dir), so `npm install --workspaces` and `npx prisma generate` run in the wrong tree and fail.
  - Five other template files reference `{{ project_slug }}` too: `Cargo.toml.jinja`, `config/{defaults,testing}.yaml.jinja`, `docker-compose.fragment.yaml.jinja` under both rust + node service templates.
- `BackendConfig` (`forge/config/_backend.py:179-198`) does not own a `slug` field; the Rust/Node Dockerfile comments make it clear that `project_slug` in this context means the *backend service slug* (i.e. `bc.name`).

### Fix
Add a single key to `backend_context()`:

```python
# forge/variable_mapper.py:47-55 (inside backend_context)
ctx: dict[str, Any] = {
    "project_name": bc.name,
    "project_slug": bc.name,           # <-- ADD; backend service slug for Dockerfile + Cargo
    "project_description": bc.description,
    ...
}
```

Rationale: backend names are already validated as slug-safe (lowercase + dashes/underscores) by `forge/config/_validators.py`, so a separate `slug` derivation isn't needed.

### Test
- `tests/test_variable_mapper.py` — extend the `test_backend_context_*` cases to assert `project_slug == bc.name` for all three languages.
- Re-render the 3 Rust/Node smoke scenarios locally (`uv run python tests/matrix/runner.py --scenario rust_svelte_min --lane smoke`) and confirm `docker compose up --wait` reaches healthy.

---

## Cluster B — Roundtrip lane lacks exclusions for build-generated artefacts (5 roundtrip failures)

### Diagnosis
- `tests/matrix/runner.py:924-1007` `_diff_project_trees_normalized` walks `project_a` vs `project_b` with `p.rglob("*")` and applies `is_excluded()` (lines 950-953) which **only** filters `.git/` + `.copier-answers.yml`.
- The Svelte / Vue / Python post-generate scripts run `npm install`, `npm run build`, and Python feature codegen — producing `node_modules/`, `.svelte-kit/`, `.prisma/`, `__pycache__/`, `build/`, `dist/`, etc. These artefacts are non-deterministic across two consecutive generates (timestamps, source maps, hashes).
- The exact same problem was already solved for golden snapshots — `tests/test_golden_snapshots.py:88-126` carries a comprehensive exclusion list. The fix is to mirror it.

### Fix
Extract the exclusion predicate into a shared helper so the runner and golden-snapshot tests can't drift again:

1. Add `tests/_artefact_filters.py` (new file, ~35 lines) exporting `is_generated_artefact(rel: str) -> bool`. Body: copy the predicate body from `tests/test_golden_snapshots.py:88-125` verbatim, with a module docstring documenting why each exclusion is non-deterministic.
2. Update `tests/test_golden_snapshots.py:85-126` to call `is_generated_artefact(rel)` and `continue` on `True`.
3. Update `tests/matrix/runner.py:950-953` `is_excluded` to delegate to the same helper (keep the existing `.git/` + `.copier-answers.yml` branches; add `is_generated_artefact(rel)`).

Locating the helper at `tests/_artefact_filters.py` (not `tests/matrix/_path_filters.py`) keeps it discoverable to non-matrix consumers like `test_golden_snapshots.py` without creating a `tests.matrix.*` import out of a sibling test module.

### Test
- New unit test in `tests/matrix/test_runner_diagnostics.py` (already exists from PR #53): assert that `_diff_project_trees_normalized` returns `[]` when one tree has only stripped paths (`node_modules/foo`, `.svelte-kit/bar`) that the other lacks.
- Re-run lane D for `py_svelte_min` and `multi_py_node` locally.

---

## Cluster C — Two stripper gaps prevent Python API container start (3 smoke failures)

PR #53 documented both bugs as out-of-scope follow-ups. They're the cause of the `container <…>-api-1 exited (3)` failures.

### C1 — `cli/__init__.py` keeps imports of deleted `cli/db.py`

`forge/strippers.py:52-81` `_PYTHON_DB_TARGETS` includes `src/app/cli/db.py` (deleted at line 58) but `strip_python_database()` (lines 335-353) never rewrites `src/app/cli/__init__.py`. The shipped file contains:

```python
# forge/templates/services/python-service-template/template/src/app/cli/__init__.py
from app.cli.db import db_app                                   # line 3 — dangling import
from app.cli.server import server_app
...
cli.add_typer(db_app, name="db", help="Database migrations")    # line 9 — dangling reference
```

When `python -m app` runs, importing `app.cli` raises `ModuleNotFoundError: No module named 'app.cli.db'` immediately. The uvicorn launcher catches this and Python exits with code 3.

**Fix:** Add `_strip_cli_init()` after `_strip_loader_db_refs` in `forge/strippers.py`, then wire it into `strip_python_database`:

```python
# forge/strippers.py — new function
_CLI_DB_IMPORT_RE = re.compile(r"^from app\.cli\.db import [^\n]*\n", re.MULTILINE)
_CLI_DB_REGISTER_RE = re.compile(r"^cli\.add_typer\(\s*db_app[^\n]*\n", re.MULTILINE)

def _strip_cli_init(path: Path) -> None:
    """Drop the ``app.cli.db`` import + Typer registration from cli/__init__.py."""
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = _CLI_DB_IMPORT_RE.sub("", text)
    text = _CLI_DB_REGISTER_RE.sub("", text)
    path.write_text(text, encoding="utf-8")

# strip_python_database (line 353):
_strip_loader_db_refs(backend_dir / "src/app/core/config/loader.py")
_strip_cli_init(backend_dir / "src/app/cli/__init__.py")   # <-- ADD
```

### C2 — `_strip_loader_db_refs` misses qualified field reference in `loader.py`

The shipped loader file (`forge/templates/services/python-service-template/template/src/app/core/config/loader.py:29`) declares:

```python
db: domain.DbConfig = domain.DbConfig()
```

`_strip_config_domain` (lines 491-512) already removes the `DbConfig` class from `domain.py`. But `_strip_loader_db_refs` (lines 515-524) only strips IMPORT lines (regex anchored at `^from … import …DbConfig`). It misses line 29 because:
- loader.py imports via `from . import domain, sources` (no direct `DbConfig` name).
- The field is referenced as the qualified `domain.DbConfig`, which the import-line regex doesn't match.

At runtime `domain.DbConfig` no longer exists → `AttributeError` at module load → exit 3.

**Fix:** Extend `_strip_loader_db_refs` to also strip the field assignment (mirrors the regex already used in `_strip_config_domain:511`):

```python
# forge/strippers.py:515-524 — extend _strip_loader_db_refs
def _strip_loader_db_refs(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^from [^\n]*import[^\n]*DbConfig[^\n]*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r",\s*DbConfig\b", "", text)
    text = re.sub(r"\bDbConfig,\s*", "", text)
    # NEW: also strip the qualified field on Settings — ``db: domain.DbConfig = …``
    text = re.sub(r"^[ \t]+db:\s*(?:domain\.)?DbConfig[^\n]*\n", "", text, flags=re.MULTILINE)
    path.write_text(text, encoding="utf-8")
```

### Test
- New unit cases in `tests/test_strippers.py`:
  - `test_strip_cli_init_drops_db_app_import_and_registration`
  - `test_strip_loader_db_refs_drops_qualified_field`
- Re-run smoke for `py_svelte_min` locally; assert container reaches healthy. The compose-log diagnostic capture (cc905cf) will surface any residual python-startup issue.

---

## Cluster D — `stateless_py` FR1 violation on `lifecycle.py` (1 roundtrip failure)

### Diagnosis (confirmed via code trace)
- `tests/matrix/runner.py:736-753` runs `harvest_project()` immediately after fresh-generate and asserts the harvester emits zero `block` or `files` candidates (FR1).
- For `stateless_py`, `harvest_project()` returns exactly one `kind="files"` candidate for `src/app/core/lifecycle.py` because of a **manifest-vs-disk hash mismatch**:
  1. `forge/generator.py:147-153` `_record_tree()` records every base-template file (including the original DB-backed `lifecycle.py`) into the `ProvenanceCollector` with its SHA-256.
  2. `forge/generator.py:177-181` calls `strip_python_database(backend_dir)`, which `_write_stateless_replacements` (`forge/strippers.py:365-378`) overwrites `src/app/core/lifecycle.py` (and four sibling IoC modules) with the `_STATELESS_LIFECYCLE` / `_STATELESS_INFRA` / `_STATELESS_SECURITY` / `_STATELESS_SERVICES` / `_STATELESS_IOC_INIT` / `_STATELESS_HEALTH_ENDPOINT` constants — but the collector is **not** updated.
  3. `forge/generator.py:348` writes `forge.toml` from the now-stale collector with the *original* hashes.
  4. At harvest time, `FileExtractor._extract_one()` (`forge/extractors/files.py:113-129`) re-reads each file from disk, computes a fresh SHA-256, and compares against the manifest's baseline. The hashes differ → `kind="files"` candidate emitted. FR1 fails.
- This affects six files, not just `lifecycle.py` — the FR1 check stops at the first offender, so the other five are masked until `lifecycle.py` is fixed.

### Fix
Thread the `ProvenanceCollector` into the stripper and have it re-record the rewritten files:

1. `forge/strippers.py:335` change signature:
   ```python
   def strip_python_database(backend_dir: Path, *, collector: ProvenanceCollector | None = None) -> None:
   ```
2. `forge/strippers.py:365-378` extend `_write_stateless_replacements` to also accept `collector` and call `collector.record_file(backend_dir / rel, rewritten_text)` after each `target.write_text(...)`. (The `record_file` method already exists — `_record_tree` is the bulk wrapper; the single-file path is what we need here.)
3. `forge/generator.py:180` pass the collector through:
   ```python
   strip_python_database(backend_dir, collector=collector)
   ```
4. Keep `collector=None` as the default so existing callers / unit tests don't break.

The trailing `# FORGE:LIFECYCLE_STARTUP` comment inside `_STATELESS_LIFECYCLE` (`forge/strippers.py:182`, just before the closing `'''`) is a paired-sentinel marker, not an unattributed standalone — the harvester only emits `block` candidates from `FORGE:BEGIN`/`FORGE:END` pairs, so the comment is inert and can stay.

### Test
- New unit case in `tests/test_strippers.py`: invoke `strip_python_database(backend_dir, collector=fake_collector)`; assert `fake_collector` has the post-strip hash for `src/app/core/lifecycle.py` (and the other 5 rewritten files).
- New integration case in `tests/matrix/test_runner_diagnostics.py`: run `generate()` + `harvest_project()` on a synthetic stateless config; assert `[c for c in bundle.candidates if c.kind in ("block", "files")] == []`.

---

## Sequencing & Verification

**PR shape:** all four clusters land in a single PR titled `fix(matrix): unblock all 15 nightly red lanes (project_slug, runner exclusions, stripper gaps)`. Mirrors PR #53's "one CI-fix bundle" pattern; keeps the nightly red for exactly one merge cycle. Implementation order inside the PR can be A → C → D → B (the smaller product-code changes first so they're easy to revert if a regression appears, then the test-runner change last).

| Step | Cluster | File(s) touched | Verifies which scenarios |
|---|---|---|---|
| 1 | A | `forge/variable_mapper.py`, `tests/test_variable_mapper.py` | rust_svelte_min, rust_vue_full, multi_all_three, node_svelte_min, node_vue_full, multi_py_node (smoke) |
| 2 | C | `forge/strippers.py`, `tests/test_strippers.py` | py_svelte_min, py_vue_noauth, py_vue_full (smoke) |
| 3 | D | `forge/strippers.py`, `forge/generator.py`, `tests/test_strippers.py`, `tests/matrix/test_runner_diagnostics.py` | stateless_py (roundtrip) |
| 4 | B | `tests/_artefact_filters.py` (NEW), `tests/test_golden_snapshots.py`, `tests/matrix/runner.py` | node_only_headless, node_svelte_min, py_svelte_min, rust_svelte_min, multi_py_node (roundtrip) |

After all four land, expected nightly state: **all 23 matrix legs green**. Two follow-up items worth flagging but **out of scope**:
1. The `[FAIL] Linting (eslint)` warnings in many `post_generate.py` outputs are pre-existing template-quality noise, not CI failures (they don't propagate up to `runner.py`'s exit code). Worth a separate cleanup PR.
2. The Cluster A fix may surface a secondary `keycloak_client_id` mismatch in compose fragments — verify the fragment rendering once Cluster A is applied.

### End-to-end verification

```bash
# Unit tests for each cluster (fast — runs in seconds)
uv run pytest tests/test_variable_mapper.py tests/test_strippers.py tests/matrix/test_runner_diagnostics.py -x

# Run the full nightly grid manually against the worktree (slow — ~25 min total)
uv run python tests/matrix/runner.py --lane smoke
uv run python tests/matrix/runner.py --lane roundtrip
uv run python tests/matrix/runner.py --lane update     # regression check — already passing

# Trigger nightly on the draft PR by adding label `ci:matrix-smoke`
gh pr edit <pr-number> --add-label ci:matrix-smoke
```

Each lane should report `OK` for every scenario; the `matrix-status-grid` artifact published by `publish-dashboard` should show no red cells.

## Critical Files Referenced

- `forge/variable_mapper.py:34-63` (Cluster A)
- `forge/templates/services/{rust,node,python}-service-template/template/Dockerfile.jinja` (Cluster A — already correctly templated)
- `forge/config/_backend.py:179-198` (BackendConfig — already has `bc.name`)
- `tests/matrix/runner.py:924-1007` (Cluster B)
- `tests/test_golden_snapshots.py:85-126` (Cluster B — reference exclusion list to mirror)
- `forge/strippers.py:335-353` `strip_python_database` (Cluster C — orchestrator to extend)
- `forge/strippers.py:515-524` `_strip_loader_db_refs` (Cluster C2)
- `forge/templates/services/python-service-template/template/src/app/cli/__init__.py` (Cluster C1 — file rewritten by new `_strip_cli_init`)
- `forge/templates/services/python-service-template/template/src/app/core/config/loader.py:29` (Cluster C2 — field stripped by extended regex)
- `forge/strippers.py:88-184` `_STATELESS_LIFECYCLE` + `_write_stateless_replacements` (Cluster D)
- `tests/matrix/runner.py:736-753` FR1 check (Cluster D — alternative fix locus)

<!-- codex-review-status: pending -->
