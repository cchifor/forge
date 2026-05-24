# Operational Runbook

Procedures for forge maintainers. Each section is self-contained: context paragraph, then numbered steps with exact commands.

---

## 1. Recovering from a botched release

The release pipeline (`release.yml`) publishes in strict order: PyPI first, then npm packages (`@forge/canvas-vue`, `@forge/canvas-svelte`) in parallel, then pub.dev (`forge_canvas_core` before `forge_canvas`). A GitHub Release is created only after all registries succeed. If a mid-pipeline job fails, earlier registries already have the version and later ones do not.

### 1.1 Identify which registries succeeded

1. Open **Actions > Release** for the tag's workflow run. Each publish job has its own status:
   - `publish-pypi` -- PyPI (OIDC trusted publishing, no token)
   - `publish-npm-canvas-vue` -- npm `@forge/canvas-vue`
   - `publish-npm-canvas-svelte` -- npm `@forge/canvas-svelte`
   - `publish-pub-dev-core` -- pub.dev `forge_canvas_core` (Dart, no Flutter)
   - `publish-pub-dev` -- pub.dev `forge_canvas` (Flutter)
   - `github-release` -- GitHub Release from CHANGELOG section

2. Cross-check with the registries directly:
   ```bash
   # PyPI
   curl -s https://pypi.org/pypi/forge/json | jq '.releases["1.0.0a1"]'

   # npm
   npm view @forge/canvas-vue@1.0.0-alpha.1 version 2>/dev/null
   npm view @forge/canvas-svelte@1.0.0-alpha.1 version 2>/dev/null

   # pub.dev
   curl -s https://pub.dev/api/packages/forge_canvas_core | jq '.versions[].version' | grep 1.0.0
   curl -s https://pub.dev/api/packages/forge_canvas | jq '.versions[].version' | grep 1.0.0
   ```

### 1.2 Manual publish to a failed registry

3. Check out the tagged commit:
   ```bash
   git checkout v1.0.0a1
   ```

4. **PyPI** (failed `publish-pypi`):
   ```bash
   uv build
   # Stable release:
   uv publish
   # Pre-release (tag contains '-'):
   UV_PUBLISH_URL=https://test.pypi.org/legacy/ uv publish
   ```

5. **npm canvas-vue** (failed `publish-npm-canvas-vue`):
   ```bash
   cd packages/canvas-vue
   npm ci && npm run build
   # Stable:
   npm publish --access public
   # Alpha:
   npm publish --tag alpha --access public
   # Beta:
   npm publish --tag beta --access public
   ```

6. **npm canvas-svelte** (failed `publish-npm-canvas-svelte`) -- same pattern:
   ```bash
   cd packages/canvas-svelte
   npm ci && npm run build
   npm publish --access public
   ```

7. **pub.dev forge_canvas_core** (failed `publish-pub-dev-core`):
   ```bash
   cd packages/forge-canvas-core-dart
   # Credentials: place pub-credentials.json from 1Password/vault
   mkdir -p ~/.config/dart
   cp /path/to/pub-credentials.json ~/.config/dart/pub-credentials.json
   dart pub get && dart analyze && dart test
   dart pub publish --force
   ```

8. **pub.dev forge_canvas** (failed `publish-pub-dev`) -- requires `forge_canvas_core` already on pub.dev:
   ```bash
   cd packages/forge-canvas-dart
   mkdir -p ~/.config/dart
   cp /path/to/pub-credentials.json ~/.config/dart/pub-credentials.json
   flutter pub get && flutter analyze
   flutter pub publish --force
   ```

9. **GitHub Release** (failed `github-release`) -- extract the CHANGELOG section and create manually:
   ```bash
   VERSION="1.0.0a1"
   awk -v v="$VERSION" \
     '/^## \[/ { in_section=0 } $0 ~ "^## \\[" v "\\]" { in_section=1; next } in_section' \
     CHANGELOG.md > release-notes.md
   gh release create "v${VERSION}" --notes-file release-notes.md
   ```

### 1.3 Version rollback

10. Registry packages are immutable -- you cannot unpublish and re-push the same version to PyPI or pub.dev (npm has a 72h unpublish window). If the released artefact is broken:
    ```bash
    # Yank from PyPI (hides from install, does not delete):
    uv tool run --from twine twine yank forge 1.0.0a1

    # Deprecate on npm:
    npm deprecate @forge/canvas-vue@1.0.0-alpha.1 "broken release, use 1.0.0-alpha.2"

    # pub.dev: retract via the web UI (pub.dev > Your packages > Retract version)
    ```

11. Cut a patch release immediately (e.g. `v1.0.0a2`) with the fix. Follow the normal release process in `RELEASING.md`.

### 1.4 When `SKIP_DRYRUN_GATE` is acceptable

12. The `preflight-dryrun` job in `release.yml` requires a `release-dryrun/ok` check-run on the tagged SHA within 72 hours. If you need to ship an emergency fix and cannot wait for a dry-run cycle:
    ```
    Settings > Secrets and variables > Actions > Variables
    Set: SKIP_DRYRUN_GATE = true
    ```

13. The bypass is auditable -- variable mutations appear in the repo audit log. After the emergency release:
    ```
    Settings > Secrets and variables > Actions > Variables
    Delete or set: SKIP_DRYRUN_GATE = false
    ```

14. A lingering `SKIP_DRYRUN_GATE=true` silently disables the safety gate for all future releases. Check it after every emergency.

---

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
    forge migrate --only provenance-v2 --dry-run

    # Apply:
    forge migrate --only provenance-v2

    # JSON output for scripting:
    forge migrate --only provenance-v2 --json
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
    forge migrate --dry-run        # preview all
    forge migrate                  # apply all
    forge migrate --skip adapters  # skip one
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

Three workflow files drive CI: `ci.yml` (every push/PR to main), `matrix-nightly.yml` (03:00 UTC nightly + on-demand via labels), and `release.yml` / `release-dryrun.yml` (tag-triggered). Each has a distinct failure profile.

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

### 4.3 release.yml: pre-publish gates

14. **`preflight-dryrun`** -- queries the `release-dryrun/ok` check-run on the tagged SHA. Fails unless a successful dry-run completed within 72 hours:
    - Fix: run **Actions > Release dry-run > Run workflow** against the commit, wait for green, re-push the tag.
    - Escape hatch: set repo variable `SKIP_DRYRUN_GATE=true` (see section 1.4).

15. **`publish-pypi`** depends on `preflight-dryrun`. Uses OIDC trusted publishing (no API token). Pre-releases (tag contains `-`) go to TestPyPI.

16. **`publish-npm-*`** depends on `publish-pypi`. Both npm packages publish in parallel. Requires `NPM_AUTH_TOKEN` secret.

17. **`publish-pub-dev-core`** depends on `publish-pypi`. **`publish-pub-dev`** depends on `publish-pub-dev-core` (ordering matters: `forge_canvas` declares `forge_canvas_core` as a runtime dep). Both require `PUB_DEV_CREDENTIALS` secret.

18. **`github-release`** depends on all five publish jobs. Extracts the CHANGELOG section and creates the GitHub Release.

### 4.4 Common false positives

19. **`typecheck-ty-canary` fails, `typecheck-forge` passes** -- upstream `ty` regression, not a forge bug. Wait for the `ty-upgrade` workflow or bump the pin manually.

20. **`matrix-smoke-fast` timeout** -- a hung docker compose stack. Check the uploaded `compose-logs-*` artifact. Common cause: port conflict on the runner, or a service healthcheck that never passes. Re-run the job; if it persists, check `docker-compose.yml` in the generated project.

21. **`coverage` fails but `test` passes** -- a module dropped below its per-module floor (not a test failure). Run `tests/test_coverage_gates.py` locally to see which module and by how much:
    ```bash
    uv run pytest tests/test_coverage_gates.py -v --no-cov
    ```

22. **`package-integrity` fails** -- a template file was removed or a build artefact leaked into the wheel. Check `tests/test_package_integrity.py` for the sentinel list and contaminant whitelist.

23. **`changelog-extract` fails in release-dryrun** -- `CHANGELOG.md` still has `[Unreleased]` instead of a dated `## [X.Y.Z]` section. Finalize the changelog before re-running the rehearsal.

24. **Nightly `publish-dashboard` shows "no lanes ran"** -- the `gate` job filtered everything out. Check whether `scenarios.yaml` has scenarios with the expected `lanes` entries, or whether a label-triggered run used the wrong label.
