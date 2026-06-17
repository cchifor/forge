# Operational Runbook

Procedures for forge maintainers. Each section is self-contained: context paragraph, then numbered steps with exact commands.

---

## 1. Recovering from a failed release

forge is distributed **GitHub-only** — `release.yml` publishes to no registry
(no PyPI/npm/pub.dev). A tag push runs a single `github-release` job that builds
the sdist+wheel, generates a CycloneDX SBOM, and cuts a GitHub Release from the
`[Unreleased]` CHANGELOG section, gated by the tag\u2194version check.

### 1.1 If the `github-release` job fails

1. Open **Actions > Release** for the tag's run and read the failed step:
   - **Check tag matches package version** — the tag and `forge/__init__.py`
     `__version__` disagree. Fix the version (or retag) so they match.
   - **Extract changelog section** — the `[Unreleased]` section is empty/missing.
     Add notes, recommit, retag.
   - **Build / SBOM** — a packaging error; reproduce locally with `uv build`.
2. The job is idempotent — re-running it (or re-pushing the tag) recreates the
   GitHub Release. Nothing was published to a registry, so there is **no
   partial-publish state** to reconcile.

### 1.2 Rolling back a release

Delete the GitHub Release and the tag (`git push --delete origin vX.Y.Z`).
Because nothing is published to a registry, no version is "stuck" downstream —
users install from source via `./install`, so a bad tag simply isn't installed.

## 2. Debugging a plugin that modifies generated output

Plugins register via the `forge.plugins` entry-point group (defined in each plugin package's `pyproject.toml`). At startup, `forge/plugins.py:load_all()` discovers every entry point, instantiates a `ForgeAPI` handle, and calls the plugin's `register` callable. Plugins can add fragments, options, backends, commands, emitters, and extractors. The loaded roster is stored in `LOADED_PLUGINS`; failures land in `FAILED_PLUGINS`.

### 2.1 Identify the offending plugin via provenance

1. Open the generated project's `forge.toml`. Each file entry under `[forge.provenance]` records its origin:
   ```toml
   [forge.provenance."src/auth/middleware.py"]
   origin = "fragment"
   fragment_name = "auth_jwt"
   fragment_version = "1.2.0"
   sha256 = "abc123..."
   ```

2. The `fragment_name` tells you which fragment authored the file. To find which plugin registered that fragment:
   ```bash
   forge --plugins list
   ```
   Each loaded plugin shows its registered fragments. Match `fragment_name` to the plugin's `fragments_added` list.

3. For JSON-parseable output:
   ```bash
   forge --plugins list --json | jq '.loaded[] | select(.fragments_added > 0)'
   ```

### 2.2 Run generation with plugins disabled

4. There is no `--no-plugins` flag. To generate without third-party plugins, isolate the environment:
   ```bash
   # Create a clean venv with only forge (no plugin packages):
   uv venv /tmp/forge-clean
   uv pip install --python /tmp/forge-clean/bin/python forge
   /tmp/forge-clean/bin/forge <your-args> --output-dir /tmp/output-no-plugins
   ```

5. Alternatively, uninstall the suspect plugin temporarily:
   ```bash
   uv pip uninstall forge-plugin-<name>
   forge <your-args> --output-dir /tmp/output-no-plugins
   uv pip install forge-plugin-<name>
   ```

### 2.3 Compare output with/without the plugin

6. Generate both variants into separate directories:
   ```bash
   # With plugin (normal environment):
   forge <your-config-args> --output-dir /tmp/with-plugin

   # Without plugin (clean venv, see step 4):
   /tmp/forge-clean/bin/forge <your-config-args> --output-dir /tmp/without-plugin

   # Diff:
   diff -rq /tmp/with-plugin /tmp/without-plugin
   diff -ru /tmp/without-plugin /tmp/with-plugin | less
   ```

7. For a non-destructive preview, use `--dry-run` (generates to a tempdir, does not write to `--output-dir`):
   ```bash
   forge <your-config-args> --dry-run
   ```

8. Use `--plan` to see the resolved fragment plan without running generation:
   ```bash
   forge <your-config-args> --plan
   forge <your-config-args> --plan --graph   # Mermaid dependency graph
   ```

### 2.4 Inspect plugin metadata

9. List all plugins with full metadata:
   ```bash
   forge --plugins list
   ```
   Output shows for each plugin: name, version, module path, and counts of options/fragments/backends/commands/emitters/extractors added.

10. Check for failed plugins (entry-point load errors, broken `register()` calls):
    ```bash
    forge --plugins list --json | jq '.failed'
    ```
    Each failure records the plugin name and error message (e.g. `"load failed: ImportError: ..."`).

11. If the fragment registry itself is inconsistent (orphan `depends_on`, cycles), `load_all()` records a `<registry audit>` failure in `FAILED_PLUGINS`. This surfaces in `forge --plugins list` output.

---

## 3. Recovering from corrupt forge.toml

The `forge.toml` manifest at a generated project's root tracks every file's provenance (origin, SHA-256 baseline, fragment/template metadata) and merge-block records. Corruption -- from merge conflicts, hand-edits, or interrupted writes -- breaks `forge --update`, `forge --verify`, and `forge --harvest`.

### 3.1 Handling merge conflicts in forge.toml

1. After a `git merge` or `git rebase` that conflicts in `forge.toml`, resolve manually:
   ```bash
   # See the conflict markers:
   grep -n '<<<<<<\|======\|>>>>>>' forge.toml
   ```

2. For `[forge.provenance]` entries, keep the **newer** side (the branch with more recent generation). For `[forge.merge_blocks]` entries, keep the side whose `sha256` matches the current on-disk file content.

3. Validate the result parses as TOML:
   ```bash
   python -c "import tomlkit; tomlkit.parse(open('forge.toml').read()); print('OK')"
   ```

4. Run the doctor check to verify structural integrity:
   ```bash
   forge doctor
   ```

### 3.2 Regenerating forge.toml from scratch

5. There is no standalone "regenerate forge.toml" command. The manifest is written during `forge new` (initial generation) and updated during `forge --update`. To regenerate from scratch:
   ```bash
   # Back up the current project state
   git stash   # or commit your work

   # Delete the old manifest
   rm forge.toml

   # Re-run generation with the same config into the existing project dir.
   # Use --dry-run first to preview:
   forge <original-config-args> --dry-run

   # Then for real (this overwrites forge.toml but NOT user-edited files
   # when using merge mode):
   forge <original-config-args> --output-dir . --update --mode merge
   ```

6. After regeneration, diff to verify nothing unexpected changed:
   ```bash
   git diff forge.toml
   git diff   # check all files
   ```

### 3.3 When it is safe to delete sections

7. **`[forge.provenance."<path>"]`** -- safe to delete an entry if the corresponding file no longer exists in the project. The next `forge --update` will re-record any files it emits.

8. **`[forge.merge_blocks."<key>"]`** -- safe to delete an entry if the corresponding BEGIN/END sentinel block has been removed from the target file. Deleting the entry while the block still exists means `forge --update` will treat that block as new on the next run.

9. **`[forge.template_versions]`** -- do not delete. If missing, `forge --update` loses track of which template versions were last applied. If corrupted, set values to `"unknown"` and let the next update re-stamp them.

10. **`[forge.frontend]`** -- do not delete unless the project genuinely has no frontend. Missing frontend metadata causes `forge --update` to skip frontend template re-rendering.

11. **`schema_version`** under `[forge]` -- never delete. If missing, forge treats the manifest as v1 and the provenance-v2 migration will attempt to upgrade it.

### 3.4 The provenance v2 migration

12. The `provenance-v2` migration (`forge/migrations/migrate_provenance_v2.py`) upgrades pre-1.2 manifests to schema v2. It enriches entries with `fragment_version`, `fragment_name`, `template_versions`, and adds `fp:<hex8>` fingerprints to BEGIN sentinels in source files.

13. Run it explicitly:
    ```bash
    # Preview (no writes):
    forge --migrate --migrate-only provenance-v2 --dry-run

    # Apply:
    forge --migrate --migrate-only provenance-v2

    # JSON output for scripting:
    forge --migrate --migrate-only provenance-v2 --json
    ```

14. The migration is idempotent -- running it on a v2+ manifest skips with `"forge.toml is already schema vN"`.

15. If a fragment referenced in the manifest is no longer in the registry (plugin uninstalled, fragment renamed), the migration logs a warning and leaves `fragment_version` absent. The harvester tolerates this.

16. All available migrations, in application order:
    ```
    ui-protocol          1.0.x -> 1.1.0
    entities             1.0.x -> 1.1.0
    adapters             1.0.x -> 1.1.0
    rename-options       1.0.x -> 1.1.0
    layer-modes          1.0.x -> 1.1.0
    adopt-baseline       1.0.x -> 1.1.0
    provenance-v2        1.1.x -> 1.2.0
    auth-keycloak-to-platform-auth  1.1.x -> 1.2.0
    ```

17. Run all applicable migrations at once:
    ```bash
    forge --migrate --dry-run                 # preview all
    forge --migrate                           # apply all
    forge --migrate --migrate-skip adapters   # skip one
    ```

### 3.5 Stale `.forge/lock` files

18. If `forge --update` fails with `"Another forge --update is running"` but no other process is active, the lock file is stale (crashed previous run):
    ```bash
    cat .forge/lock   # shows {"pid": ..., "started": "..."}
    # Verify the PID is dead:
    ps -p <pid> || echo "dead"
    rm .forge/lock
    ```
    Note: forge automatically reclaims stale locks when the owning PID is no longer alive. Manual removal is only needed if PID liveness detection fails (e.g., the PID was recycled).

---

## 4. CI failure triage

Three workflow families drive CI: `ci.yml` (every push/PR to main), `matrix-nightly.yml` (03:00 UTC nightly + on-demand via labels), and `release.yml` (tag-triggered — cuts a GitHub Release; no registry publishing). Each has a distinct failure profile.

### 4.1 ci.yml: lint, typecheck, test hierarchy

The PR/push pipeline runs these jobs. A failure in one does not cancel the others (`fail-fast: false` on the test matrix).

1. **`lint`** -- `ruff check forge/` + `ruff format --check forge/`:
   ```bash
   uv run ruff check forge/
   uv run ruff format --check forge/
   # Auto-fix:
   uv run ruff check forge/ --fix
   uv run ruff format forge/
   ```

2. **`typecheck-forge`** -- `ty check forge/`. A failure here is a forge typing regression:
   ```bash
   uv run ty check forge/
   ```

3. **`typecheck-ty-canary`** -- `pytest tests/test_ty_canary.py`. A failure here is an upstream `ty` regression. If `typecheck-forge` also fails, investigate the canary first -- forge errors are likely secondary:
   ```bash
   uv run pytest tests/test_ty_canary.py -v --no-cov
   ```
   If the canary alone fails, the fix is bumping the `ty` pin in `pyproject.toml` via the `ty-upgrade` workflow.

4. **`test`** -- pytest on ubuntu + windows, Python 3.13. Excludes `e2e`, `package_integrity`, `fuzz`, and `golden_snapshot` markers:
   ```bash
   uv run pytest -m "not e2e and not package_integrity and not fuzz and not golden_snapshot" -n auto
   ```

5. **`coverage`** -- same test suite but with `--cov`. Enforces project-wide `fail_under = 75` and per-module floors via `tests/test_coverage_gates.py`:
   ```bash
   uv run pytest -m "not e2e and not package_integrity and not fuzz" -n auto \
     --cov=forge --cov-report=json:coverage.json --cov-report=term
   uv run pytest tests/test_coverage_gates.py -v --no-cov
   ```
   If the per-module gate fails, it names the specific module that dropped below its floor.

6. **`package-integrity`** -- builds sdist + wheel, asserts sentinel template files are present and no build clutter leaked in:
   ```bash
   uv run pytest -m package_integrity -v --no-cov
   ```

7. **`matrix-generate`** (lane A) -- generates each scenario from `tests/matrix/scenarios.yaml`:
   ```bash
   uv run python tests/matrix/runner.py --scenario <name> --lane generate
   ```

8. **`matrix-verify`** (lane B) -- toolchain verification per scenario (uv, node/npm, cargo):
   ```bash
   uv run python tests/matrix/runner.py --scenario <name> --lane verify
   ```

9. **`matrix-smoke-fast`** -- lane C smoke for `py_svelte_min` and `node_svelte_min` only (docker compose up + HTTP contract). On failure, download the `compose-logs-<scenario>` artifact for container logs:
   ```bash
   uv run python tests/matrix/runner.py --scenario py_svelte_min --lane smoke
   ```

### 4.2 matrix-nightly.yml: lanes C, D, E

Runs at 03:00 UTC. Also triggered by PR labels `ci:matrix-smoke` (full fan-out) or `ci:compose-smoke` (fast subset only).

10. **Lane C (smoke)** -- RFC-006 HTTP contract. Full scenario fan-out (all scenarios with `smoke` in their `lanes` list). ~10 min/scenario. Timeout: 25 min/job:
    ```bash
    FORGE_MATRIX_LOG_DIR=./compose-logs \
      uv run python tests/matrix/runner.py --scenario <name> --lane smoke
    ```
    On failure, compose logs are uploaded as `compose-logs-<scenario>` artifacts.

11. **Lane D (roundtrip)** -- bidirectional-sync round-trip. Generates twice with a harvest/apply-back cycle. ~2 min/scenario. Tests the FR1 invariant (fresh generate emits zero candidates):
    ```bash
    uv run python tests/matrix/runner.py --scenario <name> --lane roundtrip
    ```

12. **Lane E (update)** -- `forge --update` + `forge --harvest` end-to-end. Tests all three update modes (`merge`, `skip`, `overwrite`) against an edited fragment-authored file. ~2-4 min/scenario:
    ```bash
    uv run python tests/matrix/runner.py --scenario <name> --lane update
    ```

13. **`publish-dashboard`** -- aggregates per-scenario JSON status artifacts into a markdown grid on the workflow summary. If it reports "no lanes ran", all lanes were cancelled or filtered out -- check individual job logs.

### 4.3 release.yml: the GitHub Release job

14. **`github-release`** is the only job. A tag push builds the sdist+wheel,
    generates a CycloneDX SBOM, and cuts a GitHub Release from the
    `[Unreleased]` CHANGELOG section, attaching `dist/*` + the SBOM. forge
    publishes to no registry, so there are no publish credentials and no
    pre-publish dry-run gate — only two fail-closed checks:
    - **Check tag matches package version** — the tag and `forge/__init__.py`
      `__version__` must agree.
    - **Extract changelog section** — `[Unreleased]` must be non-empty.

### 4.4 Common false positives

19. **`typecheck-ty-canary` fails, `typecheck-forge` passes** -- upstream `ty` regression, not a forge bug. Wait for the `ty-upgrade` workflow or bump the pin manually.

20. **`matrix-smoke-fast` timeout** -- a hung docker compose stack. Check the uploaded `compose-logs-*` artifact. Common cause: port conflict on the runner, or a service healthcheck that never passes. Re-run the job; if it persists, check `docker-compose.yml` in the generated project.

21. **`coverage` fails but `test` passes** -- a module dropped below its per-module floor (not a test failure). Run `tests/test_coverage_gates.py` locally to see which module and by how much:
    ```bash
    uv run pytest tests/test_coverage_gates.py -v --no-cov
    ```

22. **`package-integrity` fails** -- a template file was removed or a build artefact leaked into the wheel. Check `tests/test_package_integrity.py` for the sentinel list and contaminant whitelist.

23. **`Extract changelog section` fails in `release.yml`** -- the `[Unreleased]` section in `CHANGELOG.md` is empty or missing. Add release notes under `[Unreleased]` and retag.

24. **Nightly `publish-dashboard` shows "no lanes ran"** -- the `gate` job filtered everything out. Check whether `scenarios.yaml` has scenarios with the expected `lanes` entries, or whether a label-triggered run used the wrong label.
