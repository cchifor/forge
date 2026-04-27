# Changelog

All notable changes to forge are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — targeting 1.1.0-alpha.1

> First wave of the 12-month post-1.0 roadmap (see `plans/role-expertise-you-sprightly-nova.md`). Foundation epics that unblock the rest: structured error hierarchy (D), registry freeze + symmetry audit (I), FragmentContext plumbing (E), feature_injector decomposition (A), MiddlewareSpec abstraction (K), coverage gate (S), ty pin + canary (X), release dry-run workflow (Z). The architectural-review plan (`plans/role-expertise-you-lexical-sutherland.md`) lands its P0 + P1 items here: P0.1 file-level merge + Epic A finish, P0.2 plugin e2e gate, P1.1 options package split, P1.2 plan-update + remove-fragment verbs, P1.3 declarative compose snippets, P1.4 ts-morph instrumentation.

### Added — P2 opportunistic items (1.1.0-alpha.2)

These ship as opportunistic follow-ons to the P0 + P1 work in the
architectural-review plan. Each is small, additive, and unblocks a
specific operator / plugin-author pain point.

- **Fragment cycle path diagnostics** — `_FragmentRegistry._audit_no_cycles` now walks the dependency graph with a coloured DFS on cycle detection and reports the actual path (`a → b → c → a`) instead of just the unsorted set of fragments involved. `FragmentError.context` carries both the legacy `cycle_among` set and the new `cycle_path` list. 4 new tests in `tests/test_fragment_registry_freeze.py` lock in the diagnostic shape (two-node cycle, three-node cycle, DAG-isolation, legacy-context-preservation).
- **`forge --plan --graph`** — emits a Mermaid `graph TD` diagram showing every option that contributed to the resolved plan (with the chosen value), every fragment with its target backends, the option-→-fragment edges (`enables`), and the fragment-→-fragment depends_on edges (dotted-line variant). Pipe to `mermaid-cli`, paste into a GitHub Markdown ` ```mermaid ` fence, or render at mermaid.live. Closes the "why is fragment X applied?" support loop. 4 new tests in `tests/test_plan_and_dryrun.py` cover the wire format, option-node inclusion, depends_on-edge inclusion, empty-plan handling.
- **`forge --log-json` + `--log-level`** — top-level CLI overrides for `FORGE_LOG_FORMAT` / `FORGE_LOG_LEVEL`. `--log-json` emits NDJSON to stderr (one JSON object per line, complete with `ts` / `level` / `logger` / `event` / structured fields); `--log-level={DEBUG,INFO,WARNING,ERROR}` overrides the env-var default. A pre-parse scan of `sys.argv` ensures even plugin-load events captured before the full argparse pass honour the flags. 3 new tests in `tests/test_forge_logging.py` cover explicit-fmt-overrides-env, explicit-level-overrides-env, NDJSON line-shape contract.
- **ADR / RFC distinction documented in `CONTRIBUTING.md`** — clarifies that `docs/architecture-decisions/` covers decisions about the *shape forge generates* while `docs/rfcs/` covers decisions about *forge itself*. Two doc trees on purpose; the README in each was previously the only signal of the split.
- **Plugin author quickstart** in `docs/plugin-development.md` — 10-minute scaffold pointing at `examples/forge-plugin-example/` plus a "common gotchas the P0.2 CI gate catches" list. Each gotcha references the specific drift mode (Fragment-without-category, relative fragment_dir, files/-not-mirroring-backend-root, compose.yaml-location, missing-package-data) so the next plugin author hits zero of them.
- **Performance regression bench tests** at `tests/test_perf_merge_hot_paths.py`, `bench` pytest marker. Lightweight `time.perf_counter`-based budgets for the merge-mode hot paths — `file_three_way_decide` (~0.1 µs/op, budget 10 µs), `sha256_of_file` (~75 µs/op for 1 KiB, budget 5 ms), `is_binary_file` (~80 µs/op, budget 1 ms), `plan_update` walk (budget 30 s). No new dependencies (no `pytest-benchmark`); opt-in via `pytest -m bench`. Establishes a measurement floor; CI gating is a future ratchet move once historical data stabilises across machines.
- **Long / deep-path robustness tests** at `tests/test_long_path_update.py` exercise the merge-mode hot paths over a 6-level nested directory tree under `tmp_path`. Catches general path-handling bugs across platforms; an opt-in stress test (skipped by default) deliberately crosses Windows' 260-char `MAX_PATH` for verifying long-path support on machines with `LongPathsEnabled=1`. 5 active tests + 1 opt-in.
- **Canvas-contract test depth** — 18 new tests in `tests/test_canvas_contract.py` cover the previously-uncovered branches in `forge.codegen.canvas_contract`: missing/non-string `component_name`, missing/non-dict `props`, every `_check_type` branch (string / integer-rejects-bool / integer-rejects-string / number-rejects-bool / number-accepts-int+float / boolean / object-rejects-array / object-accepts-dict / enum-mismatch / enum-listed), and the `cli_lint` CLI handler (clean / dirty / unparseable JSON exit codes 0 / 1 / 2). `forge/codegen/canvas_contract.py` coverage 71.6% → 98%.
- **Coverage floors ratcheted** to reflect the new measured baselines. `merge` 85→92, `updater` 78→83, `capability_resolver` 95→96; `plan_update` (new module) gets its own floor at 83%/target 90%. Other modules unchanged. Updater and feature_injector both dipped briefly when the new merge-mode code paths landed; backfilled tests for `_copy_files` deprecation shim, mode-specific user-modified summary output, the disabled-fragment uninstall log path, and the resolve-failure → OptionsError re-raise (8 new tests in `tests/test_updater.py` + `tests/test_feature_injector.py`) brought both back above their floors. `tests/test_coverage_gates.py` and `docs/coverage-policy.md` updated together — the gate's docs-stay-in-sync test enforces the consistency.

### Added — P1.3 (declarative docker-compose snippets in fragments)

- **`forge/services/fragment_compose.py`** — loader + registrar for `<fragment>/compose.yaml`. Fragments can ship a YAML that the generator parses into a `ServiceTemplate` and registers under `SERVICE_REGISTRY` keyed by capability. Schema mirrors `ServiceTemplate` field-for-field (image, command, environment, ports, volumes, named_volumes, healthcheck, depends_on, networks, restart, extra). Top-level `capability:` keys the registry; `service:` block holds the docker-compose service definition.
- **`forge.services.fragment_compose.fragment_roots_from_plan`** — derives the fragment-root directory for each `ResolvedFragment` (one level above the per-language sub-dirs); fed into `register_fragment_services` to register every plan fragment's sidecar.
- **`forge.generator.generate`** — calls `register_fragment_services(fragment_roots_from_plan(plan.ordered))` before `render_compose` so fragment-declared sidecars land in the rendered docker-compose.yml alongside the existing imperative services. Additive: the existing `{% if X %}` blocks in `forge/templates/deploy/docker-compose.yml.j2` keep working; fragments adopt declarative compose at their own pace.
- **`FragmentComposeError`** — distinct from `FragmentError`; raised on malformed YAML, missing `capability` / `service` keys, or non-string `service.name` / `service.image`. Surfaces the offending file path so the operator can fix the YAML.
- **14 new tests** in `tests/test_fragment_compose.py` cover minimal + full schema parsing, every required-field error, dedup of repeated roots, idempotent re-registration with identical templates, and conflict-detection on differing templates.

### Added — P1.4 (ts-morph default instrumentation)

- **`forge.doctor.check_ts_morph_toolchain`** — surfaces whether `FORGE_TS_AST=1` AST-based TypeScript injection is reachable. Probes Node on PATH, executes `node -e "require('ts-morph')"` to verify the npm package resolves, checks the bundled helper script, and reports the env-var state. Status is `ok` when reachable (showing whether the env var is currently active), `warn` with an actionable fix otherwise. Wired into `forge --doctor` as the `ts-morph:toolchain` row.
- **`docs/troubleshooting.md`** — new section "TypeScript injection: regex anchors vs ts-morph AST" documenting the opt-in path, the toolchain requirements, the doctor surface, and the planned default flip.
- **5 new tests** in `tests/test_doctor.py` cover Node-missing, helper-missing, ts-morph-not-reachable, and reachable-with-/-without-env-var paths.
- **No code change** to the regex/ts-morph dispatch yet — instrumentation only this quarter, per the plan; the default flip is a stable-1.x conversation gated on telemetry.

### Added — P1.2 (`forge --plan-update` + `--remove-fragment`)

- **`forge.plan_update.plan_update`** — dry-run preview producing a structured `UpdatePlanReport` with per-file decisions (`applied` / `new` / `skipped-idempotent` / `skipped-no-change` / `no-baseline` / `conflict` / `error`) plus the list of fragments the next `--update` would uninstall. Reuses `file_three_way_decide` from P0.1 but doesn't write or emit sidecars. Mode-aware: `--mode merge|skip|overwrite|strict` colours the per-file `reason` field.
- **`UpdatePlanReport.as_dict`** — JSON-friendly view used by `forge --plan-update --json`. Includes a `summary` block with `applied`, `conflicts`, `total` counts so downstream tooling can branch on a clean re-apply vs. one with unresolved conflicts.
- **`forge --plan-update`** + **`forge --remove-fragment NAME`** CLI verbs. The first prints the dry-run report. The second finds the option whose `enables` map references the named fragment, flips that option to its default in `forge.toml`, then runs `update_project` so the existing Epic-F uninstaller cleans up. Errors out when zero or multiple options enable the fragment (`conversation_persistence`, for example, is enabled by ~four options — the user has to disable each explicitly).
- **`forge.cli.commands.plan_update`** + **`forge.cli.commands.remove_fragment`** — handlers; both honour `--quiet` and `--json` and inherit the `--mode` flag from the existing update parser.
- **12 new tests** in `tests/test_plan_update.py` and `tests/test_remove_fragment.py` cover refused-without-manifest, clean-project no-conflict, forced-conflict via baseline drift, all four mode dispatches, JSON round-trip, single/zero/multiple-enabling-option lookup.

### Added — P1.1 (split `forge/options.py` into a package)

- **`forge/options/`** package — refactor of the 1581-line `forge/options.py` monolith into one module per dotted-path namespace. Public surface (`Option`, `OptionType`, `FeatureCategory`, `OPTION_REGISTRY`, `OPTION_ALIAS_INDEX`, `register_option`, `resolve_alias`, `to_json_schema`, `ordered_options`, `options_by_namespace`, `get_option`, `CATEGORY_*`, `Stability`, `ObjectFieldSpec`) is re-exported from `forge.options.__init__`; every `from forge.options import X` import-site keeps working unchanged.
- **Modules:** `_registry` (types + registry + helpers), `_schema` (JSON Schema emitter), and one per namespace: `middleware`, `observability`, `async_work` (`async.*` + `queue.*`), `conversation`, `agent` (`agent.*` + `llm.*`), `chat`, `rag`, `platform_ops` (`platform.*` + `object_store.*` + `security.*`), `reliability`, `layers` (`backend.*` + `frontend.*` + `database.*`).
- **No behaviour change.** Every existing test passes. Future option additions land in a 100–250-line module instead of merging against a 1500+ line file.

### Added — P0.2 (plugin end-to-end CI gate)

- **`.github/workflows/plugin-e2e.yml`** — installs `examples/forge-plugin-example` against the working tree on every PR touching `forge/api.py`, `forge/plugins.py`, the option/fragment registries, the example, the workflow itself, or `pyproject.toml`. Runs `pytest -m plugin_e2e` against the live registry — discovery, registration, CLI list/schema, generation with the option enabled, update flow.
- **`tests/test_plugin_e2e.py`** + **`plugin_e2e` pytest marker** — 11 tests covering the discovery → registration → CLI introspection (`--plugins list` text + JSON, `--list --format json`, `--schema`) → generation (fragment files land + injection applies + provenance recorded) → update (idempotent re-apply) flow. Skips cleanly on environments where the example plugin isn't installed.
- **`forge/api.py`** — explicit "Stable Public API" annotation block in the module docstring with a per-symbol Since / Compatibility table. `add_option` / `add_fragment` / `add_backend` / `add_frontend` / `add_command` / `add_service` / `PluginRegistration` are stable; `add_emitter` is provisional.
- **Reference plugin fixed** — `examples/forge-plugin-example/` had three pre-P0.2 drift bugs the new gate caught: (1) `Fragment(category=...)` and `Fragment(summary=...)` kwargs no longer exist; (2) `inject.yaml` referenced the non-existent `FORGE:STARTUP_HOOKS` marker on `src/app/main.py`, should have been `FORGE:LIFECYCLE_STARTUP` on `src/app/core/lifecycle.py`; (3) the fragment file was at `files/hello.py` (lands at backend root, not importable) instead of `files/src/app/hello.py` (lands at `src/app/hello.py`, importable as `app.hello`). All fixed; `pyproject.toml` now declares `package-data` so wheel installs ship the fragment tree.
- **`docs/plugin-development.md`** — new "Stable API surface" section pointing at `forge/api.py`'s table + the CI gate, plus an updated Project structure layout reflecting the corrected fragment file paths and the absolute-vs-relative `fragment_dir` rule for plugins.

### Added — P0.1 (file-level three-way merge + Epic A finish)

### Added — P0.1 (file-level three-way merge + Epic A finish)

- **`forge.merge.file_three_way_decide`** — pure decision function over content hashes for `forge.appliers.files`. Mirrors `three_way_decide` for inline blocks; adds `applied` / `skipped-idempotent` / `skipped-no-change` / `no-baseline` / `conflict` action vocabulary covering the 7-row decision table. New helpers `sha256_of_file` (CRLF-normalising for text, raw bytes for binary), `is_binary_file` (null-byte heuristic on the first 8 KiB, matching Git), and `write_file_sidecar` (text → `<target>.forge-merge` with comment banner; binary → `<target>.forge-merge.bin` with no banner).
- **`forge.appliers.files.copy_files`** — Epic A finish. Body moved out of `forge.feature_injector._copy_files` into the applier module that owns it. Replaces the legacy `skip_existing: bool` parameter with `update_mode: Literal["strict","merge","skip","overwrite"]`. `_copy_files` remains as a deprecation shim translating the boolean to the enum; scheduled removal 2.0.
- **`forge.fragment_context.UpdateMode`** — new `Literal` exported from `fragment_context`. `FragmentContext.skip_existing_files: bool` is replaced by `FragmentContext.update_mode: UpdateMode` plus a `file_baselines: Mapping[str, str]` field that the applier reads for the merge decision. `FragmentContext.filtered()` accepts both as kwargs.
- **`apply_features` / `apply_project_features`** — replace `skip_existing_files: bool` with `update_mode: UpdateMode = "strict"`. Add `file_baselines: Mapping[str, str] | None = None`. Default stays "strict" so fresh generation continues to raise on fragment overlap.
- **`forge --update` defaults to `--mode merge`** — three-way decides every file-copy collision against the manifest baseline. The deferral comment ("Three-zone merge lands in 1.0.0a3") is gone. CLI flag `--mode={merge,skip,overwrite}` lets callers opt out: `skip` reproduces pre-1.1 behaviour, `overwrite` clobbers user edits.
- **`forge --update` summary** gains `update_mode` (the mode actually run) and `file_conflicts` (count of `.forge-merge` / `.forge-merge.bin` sidecars present after the apply pass) so callers can branch on a clean re-apply vs. a conflict-heavy one without parsing log output.
- **Updater seeds the new collector with every prior provenance record** (was: user-origin only). Files the applier legitimately skips — `skipped-no-change`, `no-baseline`, mode=skip — keep their prior baselines in the re-stamped manifest. Pre-P0.1, those baselines silently disappeared and every `--update` re-baselined from scratch.
- **`FILE_MERGE_CONFLICT` error code** in `forge.errors`. Distinct from the existing `MERGE_CONFLICT` (injection-block) so logs and downstream consumers can branch on the kind. Reserved for a future `--strict-conflicts` mode that escalates sidecars to a non-zero exit; not raised by the default merge path (which mirrors injection-zone behaviour: emit sidecar, continue).
- **`forge migrate-adopt-baseline` codemod** under `forge/migrations/migrate_adopt_baseline.py`. Walks `services/`, `apps/`, `tests/` and stamps current SHAs into `[forge.provenance]` with `origin="base-template"` so pre-P0.1 projects can adopt their tree as the merge baseline. Idempotent, dry-run aware, doesn't clobber existing records, skips `node_modules` / `.venv` / build dirs / forge-internal state. Strictly opt-in.
- **47 new tests** across `tests/test_file_three_way_merge.py` (27 — the 7-row decision table + binary detection + sidecar shape), `tests/test_updater.py` (8 integration tests covering merge/skip/overwrite mode behaviour, the no-baseline path, the forced-conflict scenario via baseline drift, and the user-deleted re-emit path), `tests/test_migrations.py` (6 covering adopt-baseline stamping, skip-list, idempotency, dry-run, no-manifest), and updates to `tests/test_feature_injector.py` (cover the three new copy_files modes), `tests/test_fragment_context.py` (the new field shape).

### Added — Epic F (provenance-driven uninstall)

- **`forge/uninstaller.py`** — ``uninstall_fragment(project_root, fragment_name, provenance_tbl, collector, removed_blocks_in_files=...)`` computes per-file classification for every provenance record tagged to a disabled fragment and acts on it: **unchanged files deleted**, **user-modified files preserved** with a warning, **missing files pruned from the manifest** silently. Empty parent directories left behind get pruned too.
- **Sentinel-block scrubber** — ``_remove_sentinel_block(file, feature_key, marker)`` removes a ``FORGE:BEGIN``/``FORGE:END`` pair from a file the fragment doesn't own outright. Returns ``"removed"`` on clean scrub, ``"missing"`` when the block isn't there, ``"conflicted"`` on orphan/duplicate/nested pairs (file untouched, user resolves).
- **`disabled_fragments(previous_provenance, current_plan_fragments)`** — set-diff helper identifying which fragments were previously present but aren't in the current resolved plan.
- **`forge --update` integration** — between the sentinel audit and the re-apply pass, computes disabled fragments from the previous provenance + current plan, runs ``uninstall_fragment`` per disabled. Summary payload gains an ``uninstalled`` key with per-fragment ``deleted/preserved/missing/removed_blocks/conflicted_blocks`` lists. Console output surfaces counts when not in quiet mode.
- **Escape hatch** — ``[forge.update].no_uninstall = true`` in ``forge.toml`` reverts to the pre-Epic-F behaviour (disabled fragments leave their files on disk). Read on every update; corrupt-manifest returns ``False``.
- **`MergeBlockCollector.parse_key`** — inverse of the canonical ``key_for``. Epic F walks ``[forge.merge_blocks]`` to derive ``(rel_path, feature_key, marker)`` triples for the disabled fragment's injections so sentinel-bounded blocks get scrubbed too, not just the fragment's ``files/`` outputs.
- **24 new tests** in `tests/test_uninstaller.py` cover disabled-fragment set-diff, unchanged/user-modified/missing file paths, fragment isolation (other fragments' files untouched), collector record pruning, sentinel block clean/missing/conflicted paths, ``UninstallOutcome`` serialisation, forge.toml no_uninstall flag with corrupt-manifest fallback, and ``MergeBlockCollector.key_for``/``parse_key`` round-trip.

### Added — Epic U (mutmut weekly workflow + breaking-change PR gate)

- **`.github/workflows/mutmut.yml`** — scheduled Monday 06:00 UTC full run on the critical-path modules, `workflow_dispatch` for ad-hoc re-runs, PR gate that fires on `breaking-change`-labelled PRs (skips if no critical-path file changed). Uploads `mutmut-results-*.txt` artefacts with 30-day retention.
- **`tests/mutmut_baselines.json`** — per-file kill-rate floors + survivor caps for `feature_injector`, `merge`, `provenance`, `updater`, `injectors/python_ast`, `injectors/ts_ast`. Ratchet policy mirrors coverage gates.
- **`.github/workflows/scripts/mutmut_enforce.py`** — post-run enforcer parses `mutmut results`, aggregates survivors per source file, compares against the baseline caps, fails the job with an actionable message when a module regresses. Skips silently when no mutmut cache exists (keeps the workflow valid before the first run).

### Added — Epic AA (full-feature golden snapshot preset)

- **`full_feature` preset in `tests/test_golden_snapshots.py`** — 5th golden preset exercising observability + reliability middleware + conversational-AI persistence + agent tools + chat attachments + webhooks + CLI extensions + AGENTS.md, plus a Vue frontend with auth + chat + OpenAPI. Generates ~3,600 files (vs. ~600 for `python_minimal`). Catches regressions in the "rich" Python-stack union that the 4 minimal presets miss.
- **Expanded snapshot-noise filter** — `.git/` at any depth (frontend templates run their own `git init`) + `__pycache__/` + `.pyc` files (frontend post-generate scripts byte-compile their modules). Without these filters, the frontend-inclusive preset was nondeterministic across runs. Keeps the four pre-Epic-AA presets byte-identical to their prior snapshots.
- **`ProjectConfig.options` threaded through the test's config-copy** so the preset's rich options actually reach the generator (pre-AA, the copy dropped `options=`, which wouldn't have mattered until the first preset that set anything — this one).

### Added — Epic CC (troubleshooting + known-issues docs)

- **`docs/troubleshooting.md`** — 12 entries covering install/CLI (uv PATH setup, ty alpha quirks), generation (Windows long paths, Flutter SDK, Keycloak ports, hung prompts), `forge --update` (Epic H lock + sentinel audit errors, Epic G alias deprecation warnings), Docker + runtime, and packaging + release (Epic DD contaminants, Epic Z release-dryrun gate).
- **`docs/known-issues.md`** — tracked limitations grouped by template/platform/polyglot/tooling. Each row has impact + workaround + tracking reference so contributors stop rediscovering the same gotchas.
- **README's Support section links both docs** so they're discoverable from the project front page.

### Added — Epic RFC-Q (polyglot ports roadmap — design only)

- **`docs/rfcs/RFC-005-polyglot-ports.md`** — design document specifying TypeSpec port contracts for `queue`, `object_store`, `llm`, `vector_store` cross-language, enumerating the adapter inventory (16 new adapters × 3-5 engineer-days each = ~13 engineer-weeks), and **deferring implementation to 2.x** so 1.1.x can focus on Python depth + Epic J ops parity.
- The narrower follow-up — publishing the TypeSpec spec files without adapters so plugin authors have something to conform to — is tracked as a P2 1.x item.
- `docs/rfcs/README.md` index updated with the RFC-005 row.

### Added — Epic H (updater lock + sentinel integrity audit)

- **`forge/updater_lock.py`** — ``acquire_lock(project_root, no_lock=False)`` context manager writes ``<project_root>/.forge/lock`` with PID + ISO-8601 timestamp on entry, removes on exit. Stale locks (owning PID no longer alive) are reclaimed transparently. Cross-platform liveness via ``os.kill(pid, 0)`` on POSIX and ``OpenProcess`` via ctypes on Windows — stdlib only, no psutil. Raises ``ProvenanceError(PROVENANCE_UPDATE_LOCK_HELD)`` when a live process already holds the lock. ``no_lock=True`` is a no-op escape hatch for read-only filesystems.
- **`forge/sentinel_audit.py`** — structural auditor for ``FORGE:BEGIN`` / ``FORGE:END`` pairs. Detects six issue kinds: ``orphan-begin``, ``orphan-end``, ``duplicate-begin``, ``duplicate-end``, ``nested-pair``, ``end-before-begin``. `audit_file`/`audit_targets` scan; `raise_if_corrupt` raises ``InjectionError(INJECTION_SENTINEL_CORRUPT)`` with file+tag+line details of the first 10 issues.
- **`forge --update` wraps the whole apply pass in ``acquire_lock`` + runs the sentinel audit pre-apply** so broken hand-edits surface with a pointed error before the injector runs (pre-Epic-H, they silently double-injected). The `no_lock` kwarg propagates through `update_project()` for tests + read-only-fs scenarios.
- **18 new tests** across `tests/test_updater_lock.py` — lock create/cleanup/exception paths, stale-PID reclaim, live-PID rejection, `no_lock=True` escape hatch, corrupt-lock resilience; sentinel audit clean/orphan-begin/end-before-begin/duplicate/nested-pair cases; `audit_targets` aggregation; `raise_if_corrupt` raises with the right code.

### Added — Epic O (FrontendLayout registry)

- **`forge/frontends.py`** with ``FrontendLayout(framework, ui_protocol_path, ui_protocol_emitter, canvas_manifest_path, shared_enums_dir, shared_enums_emitter)`` frozen dataclass and ``FRONTEND_LAYOUTS`` registry. Vue/Svelte/Flutter layouts registered at import time matching the pre-Epic-O paths byte-for-byte.
- **`codegen/pipeline.py` rewritten to loop over the registered layout** rather than carrying three hardcoded per-framework ``if/elif`` ladders. Adding a plugin-defined frontend is now "register a FrontendLayout"; the codegen pipeline picks it up without editing.
- **`register_frontend_layout(layout)` + `get_frontend_layout(framework)`** public API for plugins.
- **7 new tests** in `tests/test_frontend_layouts.py` assert every built-in framework has a registered layout whose paths match the pre-Epic-O hardcoded values, duplicate-registration rejection, plugin layout swap.

### Added — Epic DD (package integrity gate)

- **`tests/test_package_integrity.py`** — builds sdist + wheel via `uv build`, asserts every sentinel template file (one per backend, one per frontend, docker-compose, a cross-cutting fragment) is present in both artefacts, and no cache/build contamination (`.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/`, `node_modules/`, `.dart_tool/`, `.venv/`, `.pyc`, `.DS_Store`, etc.) leaked into either archive. The wheel test also verifies the `forge = forge.cli:main` entry point is registered.
- **Whitelist self-check** asserts every file under `forge/templates/` uses a known extension — a new file type (e.g. `.lua`) fails the test and forces an explicit decision about whether to add it to `KNOWN_TEMPLATE_EXTENSIONS` or to exclude it from templates.
- **`package-integrity` CI job** (`ubuntu-latest` × Python 3.13). Runs `pytest -m package_integrity`. Own job because the `uv build` costs ~30s; keeping it out of the main `test` matrix preserves wall-clock. Main `test` + `coverage` jobs now use `-m "not e2e and not package_integrity"` to mirror the carve-out.
- **`package_integrity` pytest marker** registered in `pyproject.toml`.

### Fixed — Epic DD

- **`MANIFEST.in`** now excludes `.ruff_cache/`, `.pytest_cache/`, `node_modules/`, `.venv/`, `htmlcov/`, `.next/`, `.svelte-kit/`, `dist/`, `build/`, `.dart_tool/`, `.DS_Store`, in addition to the pre-existing `__pycache__/` + `.mypy_cache/` exclusions. Previously these would ship in the sdist if they accumulated in a contributor's working tree.
- **`[tool.setuptools.exclude-package-data]`** applies the same exclusion list to the wheel's `forge.templates` package-data include so the wheel also stays clean.
- **Removed `forge/templates/infra/gatekeeper/src/app.log`** — stray dev log from running gatekeeper locally; not git-tracked, but would have been picked up by `uv build` on any contributor's machine where it exists.

### Added — Epic G (option aliases + rename-options codemod)

- **`Option.aliases: tuple[str, ...] = ()`** and **`Option.deprecated_since: str | None`** — an Option can declare deprecated paths that previously pointed at it. Aliases pass the same path-shape validation as the canonical path and cannot collide with any registered Option's path or alias.
- **`OPTION_ALIAS_INDEX: dict[str, str]`** + **`resolve_alias(path)`** — populated at registration, looked up by the resolver to rewrite user-supplied alias paths to canonical before validation.
- **`capability_resolver._apply_option_defaults` transparently rewrites aliases** with a `WARNING`-level log pointing at the `forge migrate-rename-options` codemod. If a user sets both the alias and the canonical path, the resolver raises `OptionsError(OPTIONS_UNKNOWN_PATH, context={alias, canonical})` so the conflict surfaces explicitly rather than silently dropping one.
- **`forge migrate-rename-options` codemod** (`forge/migrations/migrate_rename_options.py`) — parses `forge.toml`'s `[forge.options]` table via tomlkit (comment-preserving), rewrites aliased keys to canonical paths, saves. Idempotent; re-running after a successful rewrite returns `skipped_reason="No aliased option keys found in forge.toml"`. Registered in `discover_migrations()` so `forge migrate` + `forge migrate-rename-options` both find it.
- **20 new tests** in `tests/test_option_aliases.py` cover `Option.__post_init__` alias validation (self-conflict, duplicates, invalid path, `deprecated_since` without aliases), `register_option` collision detection (alias vs canonical, alias vs alias, canonical vs alias), resolver rewrites + deprecation warning, resolver raises on alias+canonical conflict, and the full codemod lifecycle (apply, dry-run, idempotent re-run, canonical-already-set short-circuit, missing manifest, missing options table, `discover_migrations` registration).

Unblocks Epic L's `forge migrate-auth-provider` codemod, which will rename existing option paths that gate Keycloak-specific behaviour (still Python-only but due to be renamed once auth becomes a first-class Option).

### Added — Epic K (MiddlewareSpec cross-language abstraction)

- **`forge/middleware_spec.py`** — frozen `MiddlewareSpec(name, backend, order, import_snippet, register_snippet, rust_mod_snippet=None)` dataclass. One spec == one middleware registration for one backend; a fragment supporting Python+Node+Rust ships three specs. Three per-backend renderers (`render_fastapi_middleware`, `render_fastify_plugin`, `render_axum_layer`) emit the `_Injection` records that the existing inject.yaml pipeline would have written by hand. `render_middleware_injections()` dispatches by `spec.backend` and sorts deterministically by `(order, name)`.
- **`Fragment.middlewares: tuple[MiddlewareSpec, ...] = ()`** — per-fragment middleware declarations. Default empty, so existing fragments are unaffected until they migrate.
- **`FragmentPlan.from_impl` + `FragmentPipeline.run`** gained `middlewares` + `backend` parameters. At plan time, specs matching the current backend are expanded into synthesised `_Injection` records and appended after any inject.yaml entries. Backward-compatible — callers that don't pass `middlewares` behave exactly as before.
- **`correlation_id/python` migrated** as the first proof: `inject.yaml` deleted, replaced by a single `MiddlewareSpec` literal on the Fragment. The generated project sees byte-identical output. Epic J (Node+Rust ops parity) migrates the remaining five middleware fragments (rate_limit, security_headers, observability, observability_otel, response_cache) and backfills Node+Rust specs for the Python-only ones.
- **13 new tests** in `tests/test_middleware_spec.py` — per-renderer shape, dispatch + filtering + ordering semantics, FragmentPlan integration (middleware-only fragment, absent-backend short-circuit, inject.yaml+middlewares combined), and a pair of sanity checks asserting the migrated `correlation_id` fragment has the expected MiddlewareSpec and that its legacy inject.yaml is gone.

### Added — Epic A (fragment applier decomposition)

- **`forge/appliers/` subpackage** — four single-responsibility applier classes each consuming a `FragmentContext` + `FragmentPlan`:
  - `FragmentPlan(fragment_dir, files_dir, injections, dependencies, env_vars, feature_key)` frozen dataclass; `FragmentPlan.from_impl(impl, feature_key, options=...)` is the resolution pass.
  - `FragmentFileApplier` — copies the fragment's `files/` tree.
  - `FragmentInjectionApplier` — runs `inject.yaml` entries through the zoned dispatcher.
  - `FragmentDepsApplier` — merges dependencies into `pyproject.toml` / `package.json` / `Cargo.toml`.
  - `FragmentEnvApplier` — appends env vars to `.env.example`.
- **`FragmentPipeline`** composes them in the canonical order (files → injection → deps → env). `FragmentPipeline.default()` is the factory; the pipeline is a frozen dataclass so plugins + downstream epics can swap a single applier without restating the rest (Epic K substitutes `FragmentInjectionApplier`).
- **`_apply_fragment` shrinks** from ~50 LOC orchestrator to 5 lines that dispatch into `FragmentPipeline.default().run(ctx, impl, feature_key)`. This is Phase 1 of the decomposition — the applier bodies still live in `feature_injector.py` and the appliers call through as thin wrappers, so behaviour is preserved byte-for-byte. A follow-up moves the helper bodies into the applier modules.
- **11 new tests** in `tests/appliers/` cover `FragmentPlan.from_impl` resolution (missing dir, files-only, inject-only, deps + env propagation, Jinja render) and `FragmentPipeline` ordering + short-circuit semantics on empty plan segments.

### Added — Epic E (FragmentContext + option_values plumbing)

- **`forge/fragment_context.py`** with a frozen `FragmentContext` dataclass bundling `backend_config`, `backend_dir`, `project_root`, filtered `options`, `provenance`, `skip_existing_files`. This is the sole input to `_apply_fragment` (Epic A's applier decomposition builds on it).
- **`FragmentContext.filtered()`** classmethod — builds a context where `options` is a read-only view restricted to the paths the impl declared in `FragmentImplSpec.reads_options`. A fragment cannot peek at option values it didn't declare.
- **`FragmentImplSpec.reads_options: tuple[str, ...] = ()`** — per-impl declaration of which option paths this fragment consumes at apply time. Most fragments leave it empty (pre-Epic-E behaviour).
- **`capability_resolver._validate_reads_options()`** pass — runs before `_topo_sort`, asserts every `reads_options` path resolves against `OPTION_REGISTRY`. Orphan paths surface as `OptionsError(OPTIONS_UNKNOWN_PATH, context={fragment, path})` at resolve time rather than silently missing at apply time.
- **`inject.yaml render: true`** flag — when set on an injection entry, the snippet is Jinja-rendered with `options={...}` in scope before injection. `StrictUndefined` semantics — a typo raises `FragmentError` with a hint to declare the path in `reads_options`.
- **`apply_features` / `apply_project_features` kwargs**: new optional `option_values` and `project_root` (backward-compatible — callers that haven't threaded the plan through yet keep working). `forge.generator.generate` and `forge.updater.update_project` pass both.
- **15 new tests** in `tests/test_fragment_context.py` cover direct + filtered construction, frozen-dataclass immutability, resolver validation of `reads_options`, Jinja rendering with `options` in scope, and end-to-end threading through `apply_features` via a captured context.

### Added — Epic I (FRAGMENT_REGISTRY freeze + startup audit)

- **`_FragmentRegistry` subclass of `dict`** — replaces the bare `dict[str, Fragment]` backing `forge.fragments.FRAGMENT_REGISTRY`. Adds a one-shot `freeze()` method and a `frozen: bool` flag. Before `freeze()` behaves like an ordinary dict; after `freeze()`, `__setitem__` / `__delitem__` raise `PluginError(PLUGIN_REGISTRY_FROZEN)` so late registrations don't silently slip past the audit.
- **Startup audit** runs four passes over the full registry:
  1. *Orphan `depends_on`* — hard error, surfacing a silently-renamed fragment at startup instead of mid-generation.
  2. *Orphan `conflicts_with`* — logs a warning (the "if this ever gets added, we conflict" pattern is legitimate).
  3. *Conflict symmetry* — warns when fragment A declares a conflict with B but B doesn't reciprocate. A future epic will tighten to a hard error with automatic promotion.
  4. *Cycle detection* — Kahn toposort dry-run; a cycle raises `FragmentError(cycle_among=[...])` with the affected fragment names.
- **`Fragment.__post_init__`** rejects self-consistency violations at construction: a fragment listing itself in `conflicts_with`, or the same name appearing in both `depends_on` and `conflicts_with`.
- **`plugins.load_all()` calls `FRAGMENT_REGISTRY.freeze()`** after the per-plugin loop. A failed audit captures into `FAILED_PLUGINS` as `<registry audit>` rather than crashing, so introspection verbs (`forge --list`, `forge --plugins`) still work for diagnosis.
- **17 new tests** in `tests/test_fragment_registry_freeze.py` cover every audit pass, freeze/thaw semantics, `Fragment.__post_init__`, and a sanity check that the shipped built-in registry audit passes.
- **`plugins.reset_for_tests()`** now also thaws the registry so the test-wide fixture that clears plugin state works in both orders.

### Added — Epic Z (release dry-run rehearsal + 72h preflight)

- **`.github/workflows/release-dryrun.yml`** (`workflow_dispatch`-only) — rehearses every publish path against dry-run endpoints / offline validators: Python sdist+wheel build + `twine check`, `forge` CLI install smoke from the built wheel (`forge --version / --help / --list`), `npm publish --dry-run` for canvas-vue and canvas-svelte, `flutter pub publish --dry-run` + `flutter analyze` for forge_canvas, CHANGELOG section extraction. On green, writes a `release-dryrun/ok` check-run on the rehearsed SHA.
- **`preflight-dryrun` job in `release.yml`** — queries the GitHub Checks API for `release-dryrun/ok` on the tagged commit, fails fast unless a successful rehearsal completed within 72h. Every publish-* job now depends on this preflight, so a broken build or misconfigured registry never reaches PyPI / npm / pub.dev.
- **Escape hatch** — repo variable `SKIP_DRYRUN_GATE=true` bypasses the preflight with a CI warning. Mutations are in the repo log, so an accidental lingering bypass is visible in audit.
- **`RELEASING.md` "Pre-release dry-run protocol"** section — step-by-step protocol, per-job failure taxonomy, escape-hatch usage.

### Added — Epic X (ty pin + upstream regression canary)

- **ty pinned to exact version** (`0.0.29`) in `pyproject.toml`. The old `>=0.0.1a7` constraint let uv resolve to whatever Astral had released — handy for bug fixes, dangerous for CI stability. New ty bumps now go through `.github/workflows/ty-upgrade.yml` (scheduled monthly + `workflow_dispatch`), which runs the canary + forge typecheck before opening a PR with the lock churn.
- **`tests/fixtures/ty_canary/`** — 12 small Python files exercising the 5 enabled ty rules (`unresolved-import`, `invalid-argument-type`, `invalid-return-type`, `missing-argument`, `unknown-argument`) plus `TypedDict` and generic `Protocol` inference smoke tests. Each file has a `# expect: error[<rule>]` or `# expect: ok` header.
- **`tests/test_ty_canary.py`** — 13 tests that subprocess-invoke `ty check` against each fixture and assert the reported diagnostic rule matches the header. A divergence means ty's behaviour changed — the CI failure surfaces as "upstream ty regression" rather than "forge typing regression".
- **Split `typecheck` job in `ci.yml`** into `typecheck-forge` and `typecheck-ty-canary`. Running in parallel. A green `typecheck-ty-canary` with a failing `typecheck-forge` points at forge code; the reverse points at ty.
- **`.github/workflows/ty-upgrade.yml`** — scheduled bot. First Monday of each month (or `workflow_dispatch`) bumps ty to the latest alpha, runs canary + forge typecheck, opens a labelled PR with the bump. Humans review + merge.

### Fixed — Epic X (pre-existing ty diagnostics)

- Seven typechecker diagnostics that ty 0.0.29 surfaces on the forge codebase (the old `>=0.0.1a7` constraint was resolving to a newer ty in practice, but the diagnostics weren't being enforced — CI was running whatever uv cached). Each is suppressed with a targeted `# ty:ignore[<rule>]` comment and a rationale. Sites: `forge/cli/interactive.py:106` (BackendLanguage + plugin-sentinel union), `forge/codegen/enums.py:104, 109` (narrowed dict.get), `forge/domain/typespec.py:111` (optional-import-shim), `forge/generator.py:19, 20, 217` (Windows stdout reconfigure + provenance origin assignment). These are intentional pragmatic suppressions; a future epic tightens the relevant dataclass types to remove them.

### Fixed — Epic X (pre-existing ruff diagnostics)

- Ruff 0.15.11 (refreshed via `uv sync` during Epic X) surfaces ~37 pre-existing UP037 / UP035 diagnostics — quoted type annotations that `from __future__ import annotations` makes unnecessary, plus `typing.Callable` → `collections.abc.Callable` migrations. All auto-fixed by `ruff check --fix`; the resulting diffs are mechanical.
- Three style fixes that ruff flags but can't auto-fix: SIM108 ternary in `forge/domain/emitters.py` (ternary applied); SIM102 nested-if in `forge/feature_injector.py` (combined with `and`); UP042 `str + Enum` in `forge/domain/spec.py` (kept with a targeted `noqa` — StrEnum changes `==` semantics and the YAML loader depends on the current behaviour).
- `uv.lock` refreshed for the new ty pin + the current ruff.

### Added — Epic S (per-module coverage gates)

- **`tests/test_coverage_gates.py`** — per-module coverage floors for the critical path (`capability_resolver`, `feature_injector`, `merge`, `provenance`, both AST injectors, `updater`). Parametrized across the gate table so a CI failure names the exact module that regressed instead of just "coverage low".
- **`coverage` job in `.github/workflows/ci.yml`** — ubuntu × Python 3.13 only; runs pytest with `--cov-report=xml,json`, re-runs the per-module gate against the fresh report, uploads XML to Codecov (OIDC for the public repo, `CODECOV_TOKEN` honoured if set).
- **`docs/coverage-policy.md`** — documents the two-layer gate (project-wide `fail_under` + per-module floors), the ratchet policy, and how to add or lower a floor with RFC-002 justification.

### Changed — Epic S

- Measured baseline at the start of Epic S was 83.5% project-wide — well above the existing `fail_under = 75`. The exploration assumption of 26% was stale. Project-wide floor stays at 75 as the coarse safety net; the new per-module floors lock in the actual 80–97% critical-path coverage with a 2pp safety margin so small incidental drops don't block unrelated PRs.
- `.gitignore` now ignores `coverage.json` and `coverage.xml` so the CI-generated reports don't accidentally land on a feature branch.

### Breaking

### Breaking

- **Epic D — Error hierarchy.** `GeneratorError` is now an alias for the new `ForgeError` base class; six typed subclasses (`OptionsError`, `FragmentError`, `InjectionError`, `MergeError`, `ProvenanceError`, `PluginError`) replace the single flat error type. `except GeneratorError:` keeps catching every forge failure so call sites outside the project are unaffected. Assertions that compare `type(err).__name__ == "GeneratorError"` or rely on exact-type equality break — migrate to `isinstance(err, ForgeError)` or the specific subclass. No codemod; the search-and-replace is too coupled to the local test style to mechanise safely. See `UPGRADING.md`.

### Added

- **`forge.errors.ForgeError`** with fields `message`, `code`, `hint`, `context` and an `as_envelope()` helper the CLI uses for the `--json` error envelope.
- **Machine-readable error codes** (`OPTIONS_UNKNOWN_PATH`, `FRAGMENT_DIR_MISSING`, `INJECTION_ANCHOR_NOT_FOUND`, `MERGE_CONFLICT`, `PROVENANCE_MANIFEST_MISSING`, `PLUGIN_COLLISION`, etc.) exported from `forge.errors` so plugins + tests can branch on `err.code` without regex-matching message strings.
- **Subclass-aware exit codes** in the CLI: injection failures exit 3, merge 4, provenance 5, plugin 6; options/fragment/generator stay at 2. 0 remains success.
- **`--json` envelope extension.** The error envelope now includes `code`, `hint` (when present), and `context` (when non-empty). The legacy `{"error": "<message>"}` shape is preserved for config-parse errors that surface as raw `ValueError` / `KeyError`.
- **`tests/test_errors.py`** — 18 new tests covering the hierarchy, alias identity, envelope serialisation, and exit-code mapping.

### Changed

- Every `raise GeneratorError(...)` in the core control plane (`capability_resolver`, `feature_injector`, `injectors/python_ast`, `injectors/ts_ast`, `updater`, `api`) now raises the most specific subclass with a named `code`. Generator-orchestration raises in `forge/generator.py` continue to raise via the `GeneratorError` alias (= `ForgeError`) — they'll migrate to a future `GenerationError` subclass in a follow-up.
- Bare `ValueError` / `FileNotFoundError` raises in the AST injectors are promoted to `InjectionError` with codes (`INJECTION_TARGET_MISSING`, `INJECTION_ANCHOR_NOT_FOUND`, `INJECTION_ANCHOR_AMBIGUOUS`, `INJECTION_MARKER_MISSING`) so CLI + tests see a uniform error surface.

---

## [1.0.0] - 2026-04-20

> **forge 1.0 — stable.** First stable release of the clean-break 1.0 series. Every capability shipped across the five alphas (a1–a5) + beta (b1) + release candidate (rc1) is now under the normal SemVer contract: breaking changes require a major bump, minor bumps add features, patches fix bugs. See `RELEASING.md` for the post-1.0 deprecation policy.

### Summary of the 1.0 series

- **Schema-first core** — single YAML or TypeSpec source drives every language's domain models + OpenAPI + enums.
- **AST-aware injection** — LibCST for Python, regex (or ts-morph subprocess) for TypeScript, with three-zone (generated / user / merge) semantics and `.forge-merge` conflict sidecars.
- **Provenance manifest** — `forge.toml` records SHA-256 + origin per file; `forge --update` classifies user-modified vs unchanged vs fragment-modified.
- **Ports-and-adapters** — vector store (6 providers), LLM (4 providers), queue (2 providers), object store (2 providers) — swappable via env, no regeneration.
- **Plugin SDK** — third parties ship `forge-plugin-*` packages that add options, fragments, backends, frontends, commands, or emitters via entry points.
- **Canvas packages** — `@forge/canvas-vue`, `@forge/canvas-svelte`, `forge_canvas` publish 5 canvas components + AG-UI streaming client + runtime prop lint.
- **Real MCP integration** — stdio JSON-RPC subprocess client, tool discovery + invoke endpoints, HMAC-signed approval tokens, append-only audit log.
- **30 options × 51 fragments × 662 tests** — full coverage across the registry.

### Version

- `pyproject.toml` version `1.0.0`.
- Canvas packages held at `1.0.0-alpha.5` until the first post-1.0 bump (their own lifecycle; see RFC-003).

### Post-1.0 policy

- Breaking changes require a major bump and a deprecation cycle (one minor release warning → removal in the next).
- Dropping a Python / Node / Rust / Flutter version is breaking; backport fixes to the last minor that supported it for one year.
- RFC-002's codemod contract remains in force — every breaking change ships with a `forge migrate-<name>` codemod or a documented manual step.

---

## [1.0.0rc1] - 2026-04-20

> First release candidate. Feature-frozen since 1.0.0b1 with no new changes — this RC exists to exercise the full release-rehearsal pipeline (RFC-004) against every registry (TestPyPI, npm `alpha` tag, pub.dev `--dry-run`) before the v1.0.0 tag push. Promoted to stable 1.0.0 if the rehearsal completes without rollbacks.

### Changed

- `pyproject.toml` version pinned to the RC identifier (no `.dev0` suffix) so `uv build` emits installable `forge-1.0.0rc1` artefacts for the rehearsal.

### Tests

662 passing, 1 skipped (no change from b1).

---

## [1.0.0b1] - 2026-04-20

> First beta — **feature freeze**. No new features accepted from this point; only bug fixes, doc polish, and release-rehearsal hardening.

### Added

- **Expanded CI matrix** (`.github/workflows/e2e.yml`): forge's own tests run on Python 3.11 / 3.12 / 3.13; generated-project suites (python-vue, node-svelte, rust-none, multi-backend-keycloak) run on every template-touching PR; canvas-packages build + typecheck for `@forge/canvas-vue`, `@forge/canvas-svelte`, `forge_canvas` on every commit.
- **`docs/ARCHITECTURE.md`** — rewritten to document the post-1.0 design: registry triad, generation pipeline, injector backends, provenance + merge blocks, codegen layer, canvas packages, plugin architecture, testing surface.
- **`docs/GETTING_STARTED.md`** — 10-minute tour from install to a running project, including headless YAML invocation, incremental-change verbs, codemods, and agent-friendly stdin/json patterns.
- **`docs/rfcs/RFC-004-release-rehearsal.md`** — pre-1.0 rehearsal policy, dry-run mechanics, lockstep version check, rollback asymmetries per registry.
- **`release.yml` dry-run trigger** — `workflow_dispatch` inputs `dry_run` (default true) and `target` so maintainers can rehearse the full PyPI + npm + pub.dev pipeline without tagging.

### Changed

- **README visuals** — placeholder image slots removed; replaced with a real Mermaid architecture diagram + links to `ARCHITECTURE.md` and `GETTING_STARTED.md`.

### Tests

662 passing, 1 skipped (no change from a5 — feature freeze).

---

## [1.0.0a5] - 2026-04-20

> Fifth alpha — **feature-complete**. Lifts the remaining 4 canvas components (CodeViewer, DataTable, DynamicForm, WorkflowDiagram) into the published `@forge/canvas-vue`, `@forge/canvas-svelte`, and `forge_canvas` packages. Ships beta-gate testing infrastructure: 4 golden-snapshot presets (python/node/rust/multi-backend), OpenAPI contract tests for the domain DSL, and mutation testing scoped to the fragment-injector critical path.

### Added

- **4 canvas components extracted** across all three frameworks (A5-1 through A5-4):
  - `CodeViewer` — syntax-highlighted code with filename header + line numbers. highlight.js (web) / flutter_highlight (mobile).
  - `DataTable` — sortable columns + client-side pagination.
  - `DynamicForm` — JSON-schema-driven form dispatching by field type (text/number/password/email/select/checkbox/textarea).
  - `WorkflowDiagram` — DAG layout with topological-depth row assignment, status badges (pending/running/completed/error/skipped), straight-line edge routing.
- **Golden-snapshot presets** extended from 1 to 4: `python_minimal`, `node_minimal`, `rust_minimal`, `multi_backend`. Regenerate with `UPDATE_GOLDEN=1`.
- **OpenAPI contract tests** (`tests/test_openapi_contract.py`): every entity's emitted OpenAPI has typed properties, correct required-vs-optional split, format declarations for uuid/date-time, `$ref` for enums. 13 tests.
- **Mutation testing configuration** — `[tool.mutmut]` in pyproject.toml scoped to `feature_injector`, `merge`, `provenance`, `injectors/*`, `updater`. New `docs/mutation-testing.md` documents the kill-rate baseline + the "run locally on breaking-change PRs" policy.
- **Vue / Svelte dependencies** — `highlight.js@^11.10.0` for CodeViewer.
- **Dart dependencies** — `flutter_highlight@^0.7.0` for CodeViewer, `http@^1.2.0` for MCP client.

### Changed

- Published packages bumped to `1.0.0-alpha.5`. `@forge/canvas-vue` + `@forge/canvas-svelte` + `forge_canvas` now export all 5 canvas components.

### Tests

662 passing, 1 skipped (up from 646).

---

## [1.0.0a4] - 2026-04-20

> Fourth alpha. Closes the plugin SDK story (command dispatcher wired, frontends pluggable, fragments shippable from plugin packages), adds runtime canvas-prop lint across Vue / Svelte / Flutter, ships the MCP approval-token + audit-log middleware, and lifts the first canvas component (`Report`) into the published packages as the extraction reference.

### Breaking

- **`/mcp/invoke` now requires a valid `approval_token` when the tool's mode is not `auto`**. Frontend ApprovalDialog code must first POST `/mcp/approval/mint` and include the returned token on the next invoke. Tokens are HMAC-signed with `MCP_APPROVAL_SIGNING_KEY` and bound to (server, tool, input-hash). Generated projects without the env var fall back to the service name — logged as a warning; not safe for production.

### Added

- **Plugin command dispatcher** (A4-2): `ForgeAPI.add_command(name, handler)` now registers into `COMMAND_REGISTRY`; `_build_parser` walks it and injects `--<name>` flags; main.py dispatches to the handler with the full argparse Namespace. Collisions with core flags are silently skipped so a malformed plugin can't break the CLI.
- **Plugin fragment path resolver** (A4-3): `FragmentImplSpec.fragment_dir` now accepts absolute paths — plugins can ship fragments from their own package tree (`Path(__file__).parent / "fragments" / ...`) instead of being restricted to forge's `_fragments/` directory.
- **Plugin-defined frontends** (A4-4): `ForgeAPI.add_frontend(value, FrontendSpec)` + `_PluginFramework` sentinel + `resolve_frontend_framework`, mirroring the 1.0.0a2 backend-plugin story. Plugins can ship Solid, Qwik, Remix, etc.
- **Canvas runtime lint** (A4-5): `lintProps` / `warnOnLintIssues` in every canvas package. `CanvasRegistry.lintAndResolve(name, props)` validates props against the component's JSON Schema in dev mode and emits `console.warn` / `debugPrint` on drift. Tree-shaken in prod.
- **MCP audit log + approval tokens** (A4-6): `app/mcp/audit.py` in generated projects — HMAC-SHA256-signed approval tokens bound to (server, tool, input-hash), append-only `audit.jsonl` recording every invocation with user_id + decision + error. New `POST /mcp/approval/mint` endpoint for frontend token exchange.
- **Canvas Report component extracted** (A4-7): `Report.vue`, `Report.svelte`, `report.dart` now live in the published `@forge/canvas-vue`, `@forge/canvas-svelte`, and `forge_canvas` packages. The Vue + Svelte versions ship with `marked` + `DOMPurify` as runtime deps; Flutter uses `flutter_markdown`. Packages bumped to `1.0.0-alpha.4`.

### Changed

- `api.py` adds `add_frontend`; `config.py` adds `FrontendSpec`, `PLUGIN_FRAMEWORKS`, `FRONTEND_SPECS`, `_PluginFramework`, `register_frontend_framework`, `resolve_frontend_framework`.
- `feature_injector._resolve_fragment_dir` extracts the path-resolution policy so plan.py and the injector share it.
- `plugins.py` adds `COMMAND_REGISTRY`; `reset_for_tests` clears it.
- MCP router: `/mcp/invoke` now verifies approval tokens, writes audit entries, and returns 401 on token failure.

### Tests

646 passing, 1 skipped (up from 618). New suites: `test_plugin_commands.py` (6), `test_plugin_fragment_paths.py` (4), `test_plugin_frontend.py` (8), `test_mcp_audit.py` (10).

---

## [1.0.0a3] - 2026-04-20

> Third alpha. Three-way merge runtime (`merge` zone is now semantically real), real MCP subprocess spawning + tool discovery, Svelte and Flutter MCP UI parity, and the TypeSpec compiler bridge for domain entities.

### Breaking

- **`merge` zone now emits `.forge-merge` sidecars on conflict.** Previously aliased to `generated`. If you had `zone: merge` in a fragment's inject.yaml, a user edit + fragment change during `forge --update` now produces a sidecar instead of silently overwriting. Pre-1.0.0a3 projects that don't have `[forge.merge_blocks]` in their `forge.toml` fall back to `generated` behavior on first apply, then record a baseline going forward.
- **MCP endpoints return real data.** `/mcp/tools` spawns configured servers and aggregates their advertised tools; `/mcp/invoke` proxies real tool calls. The 1.0.0a1 placeholder response is gone. Projects without `mcp.config.json` see an empty tool list.

### Added

- `forge/merge.py` — pure three-way-decision helpers (`three_way_decide`, `write_sidecar`, `sha256_of_text`, `MergeBlockCollector`). No I/O in the decision function; callers handle disk writes.
- `[forge.merge_blocks]` table in `forge.toml` — per-block SHA baseline keyed by `{rel_path}::{feature_key}:{marker}`. Enables true three-way compare between baseline / current / new.
- Python MCP stdio JSON-RPC client (`app/mcp/client.py` in generated projects): `McpStdioClient` speaks newline-delimited JSON-RPC 2.0, completes the initialize handshake, and handles `tools/list` + `tools/call`. `McpRegistry` manages per-server subprocess lifecycle; app shutdown hook terminates children cleanly.
- **Svelte MCP UI** (`mcp_ui_svelte` fragment): `ToolRegistry.svelte` with runes-based fetch, `ApprovalDialog.svelte` with `$props()` rune, `use-mcp-tools.svelte.ts` client-side hook with session-approval cache.
- **Flutter MCP UI** (`mcp_ui_flutter` fragment): `tool_registry.dart` `FutureBuilder`-backed list, `approval_dialog.dart` Material dialog returning `ApprovalResult`, `mcp_client.dart` ties them together with session-approval cache.
- `forge/domain/typespec.py` — TypeSpec compiler bridge via `npx tsp compile`. `typespec_available()` for toolchain detection; `compile_tsp()` + `extract_entities()` produce YAML-DSL-compatible entity dicts from `.tsp` sources so the existing emitters (Pydantic / Zod / sqlx / OpenAPI) consume either format.

### Changed

- `_apply_zoned_injection` threads `project_root` + `collector` through so `merge` zone can look up baselines and record new ones.
- `generator._write_forge_toml` and `updater._restamp_forge_toml` now emit `[forge.merge_blocks]` alongside `[forge.provenance]`.
- MCP fragment (`mcp_server/python`) gains `client.py`, a shutdown hook injection, and real `/mcp/tools` + `/mcp/invoke` implementations.
- Fragment registry grows from 47 → 51 entries (`mcp_ui_svelte`, `mcp_ui_flutter`).

### Tests

634 passing, 1 skipped (up from 594). New suites: `test_three_way_merge.py` (12), `test_mcp_client.py` (4), `test_typespec_bridge.py` (8).

---

## [1.0.0a2] - 2026-04-20

> Second alpha. Completes the ports-and-adapters refactor (6 RAG adapters, 4 LLM providers, queue + object-store ports) and adds plugin-extensible `BackendLanguage`, the ts-morph AST sidecar, Node base-template anchors for reliability auto-wire, and retires the hand-rolled Flutter SSE client in favor of the `forge_canvas` package.

### Breaking

- **`rag.backend` now enables the port+adapter pair** instead of the legacy `rag_<name>` fragments. Generated projects get `vector_store_port` + `vector_store_<provider>` in their plan. Runtime-swappable via env. Migration for pre-1.0.0a2 projects: `forge --migrate --migrate-only adapters`.

### Added

- **Full RAG port+adapter catalogue:** `vector_store_chroma`, `vector_store_pinecone`, `vector_store_milvus`, `vector_store_weaviate`, `vector_store_postgres` join the 1.0.0a1 Qdrant reference.
- **LLM provider port** (`llm_port`) + four adapters: `llm_openai`, `llm_anthropic`, `llm_ollama`, `llm_bedrock`. New `llm.provider` option.
- **Queue port** (`queue_port`) with Redis-list + AWS SQS adapters. New `queue.backend` option.
- **Object-store port** (`object_store_port`) with S3 (+ S3-compatible) and local-filesystem adapters. New `object_store.backend` option.
- **Plugin-extensible `BackendLanguage`** — plugins can add new backend languages (e.g. Go, Java) via `api.add_backend("go", spec)`. Built on a `_PluginLanguage` sentinel + `resolve_backend_language(value)` helper.
- **ts-morph subprocess sidecar** (`forge/injectors/ts-morph-helper.mjs` + `ts_morph_sidecar.py`). Opt-in via `FORGE_TS_AST=1`; falls back to the regex injector when ts-morph or Node isn't available.
- **Node base-template markers** — `FORGE:PRISMA_CLIENT_INIT` anchors the reliability_connection_pool auto-wire so `reliability.connection_pool=true` produces a working generated project without hand-edits.
- **Flutter hand-rolled SSE deprecation notice** + migration target (`forge_canvas` package). `forge --migrate --migrate-only ui-protocol` renames the legacy file to `.legacy`.

### Changed

- `rag.backend` enum's `enables` map now points at vector_store_* fragments; legacy `rag_<provider>` fragments remain in the registry for backward-compat but aren't selected by the Option.
- Fragment registry grows from 35 → 47 entries (ports + adapters + LLM/queue/object-store).
- Option registry grows from 27 → 30 (`llm.provider`, `queue.backend`, `object_store.backend`).

### Tests

594 passing, 1 skipped (up from 571). New test files: `test_plugin_backend_language.py`, `test_ts_morph_sidecar.py`.

---

## [1.0.0a1] - 2026-04-20

> First alpha of the **1.0 clean-break** series. See `RELEASING.md` for the release process and `UPGRADING.md` for migration guidance.

### Breaking

- **CLI entry point moved** — `forge.cli:main` → `forge.cli.main:main`. The `forge` console script is unchanged; only direct Python imports of private helpers need to update.
- **`forge.toml` gains `[forge.provenance]`** — per-file origin + SHA-256 + fragment version. Old projects receive a one-time backfill on first `forge --update` in 1.0.

### Added

**Phase 0 — foundations:**
- `forge/cli/` package (decomposed from the 1,361-line cli.py) with command-object dispatch.
- `forge/provenance.py` — CRLF-normalized SHA-256 + classify/record primitives; written to `[forge.provenance]` on every generate, consumed by `forge --update`.
- `forge/api.py` + `forge/plugins.py` — entry-point plugin host (group `forge.plugins`), `ForgeAPI` facade, `forge plugins list` command.
- `forge --plan` (ordered fragment plan + mutation tree, ASCII-safe on Windows) and `forge --dry-run`.

**Phase 1 — schema-first core:**
- `forge/codegen/ui_protocol.py` emits TS + Dart + Pydantic from 7 JSON schemas under `forge/templates/_shared/ui-protocol/`.
- `forge/codegen/canvas_contract.py` + 5 canvas component props schemas; `forge --canvas lint` validates payloads.
- `forge/domain/` — YAML entity DSL with Pydantic / Zod / sqlx / OpenAPI emitters (TypeSpec adoption: 1.0.0a2).
- `forge/codegen/enums.py` — Python / TS / Zod / Rust / Dart emitters for shared enums.
- `forge/codegen/pipeline.py` — integration point: runs every emitter during `forge new` so each project ships with regenerated types per-frontend and per-backend.

**Phase 2 — extensibility:**
- `forge/injectors/python_ast.py` — LibCST-anchored Python injection that survives Ruff / Black reformatting; falls back to text markers on syntax errors.
- `forge/injectors/ts_ast.py` — regex-anchor + sentinel injector for `.ts/.tsx/.js/.jsx/.mjs`; dispatched automatically by extension.
- Three-zone merge — `generated`, `user`, and `merge` semantics on every `inject.yaml` entry.
- Reference port+adapter pair: `vector_store_port` + `vector_store_qdrant` (rest of RAG refactor: 1.0.0a2).
- `docs/architecture-decisions/ADR-001-pragmatic-hexagonal.md`, `ADR-002-ports-and-adapters.md`.
- `docs/plugin-development.md` + `examples/forge-plugin-example/` reference plugin.

**Phase 3 — agentic UI:**
- Published package scaffolds: `@forge/canvas-vue`, `@forge/canvas-svelte`, `forge_canvas` (pub.dev), each with Vite library build / tsconfig / svelte.config / analysis_options so they can actually `npm publish` / `flutter pub publish`.
- Dart `AgUiClient` — exponential-backoff reconnect + `Last-Event-ID` resume + SSE chunk parsing.
- `ForgeTheme` — shadcn-flavored Material 3 matching the web design language.
- MCP scaffolds: `mcp_server` (FastAPI router for `/mcp/tools` + `/mcp/invoke`) + `mcp_ui` (Vue ToolRegistry + ApprovalDialog).
- `docs/mcp.md` + `mcp.config.example.json` + JSON Schema at `forge/templates/_shared/mcp/mcp_config_schema.json`.

**Phase 4 — production polish:**
- Reliability fragments across **Python / Node / Rust**: `reliability_connection_pool`, `reliability_circuit_breaker`, with auto-wire injections.
- `observability_otel` fragment across **Python / Node / Rust** (OTLP exporter + FastAPI / `@opentelemetry/sdk-node` / `tracing-opentelemetry` bridges).
- Security fragments: `security_csp` (strict CSP nginx include), `security_sbom` (CycloneDX workflow).
- `forge/common_files.py` drops `.editorconfig`, `.gitignore`, `.pre-commit-config.yaml`, and per-backend CI workflows into every project.
- `forge/doctor.py` — toolchain / Docker / port / `forge.toml` integrity diagnostics via `forge --doctor [--json]`.
- New CLI verbs: `forge --new-entity-name`, `--add-backend-language`, `--preview`, `--migrate [--migrate-only] [--migrate-skip]`.
- `forge/migrations/` — three codemods (`migrate-ui-protocol`, `migrate-entities`, `migrate-adapters`) + umbrella runner.
- Golden snapshot test suite (`UPDATE_GOLDEN=1` regenerates).
- `.github/workflows/release.yml` — coordinated PyPI + npm + pub.dev publish on tag push (TestPyPI for pre-releases, PyPI for stable).

### Changed

- `forge/cli.py` (1,361 lines) decomposed into `forge/cli/` package.
- `capability_resolver.resolve()` returns a richer plan consumed by `forge --plan` and `forge --dry-run`.
- `updater.update_project()` classifies each tracked file as unchanged / user-modified / missing using the provenance manifest.
- Fragment registry grows from 27 → 35 entries (vector-store ports, reliability / observability / security, MCP).
- Option registry grows from 22 → 27 with `reliability.connection_pool`, `reliability.circuit_breaker`, `observability.otel`, `security.csp`, `security.sbom`, `platform.mcp`.

### Tests

571 passing, 1 skipped (up from 367). 13 new test files covering provenance, plugins, --plan/--dry-run, codegen pipeline, canvas contract, domain DSL, enum codegen, UI-protocol codegen, Python + TS AST injection, three-zone merge, doctor, migrations, new CLI verbs, common files, golden snapshots, and end-to-end generation with reliability + observability options enabled.

---

## [Unreleased — 0.x maintenance]

### Added — Svelte + Flutter frontend parity

- **Copier configuration parity**: Svelte gains `include_openapi`, `default_color_scheme`, `app_title`, `api_proxy_target`, and hidden multi-backend vars (`backend_features`, `proxy_targets`, `vite_proxy_config`). Flutter gains `default_color_scheme`, `app_title`, and `backend_features`. `forge.variable_mapper.svelte_context` / `flutter_context` extended to emit them.
- **Multi-backend awareness in generated frontends**: Svelte `_build/post_generate.py` patches per-feature `api/{name}.ts` to call `/api/{backend}/v1/...` and injects `vite_proxy_config` into `vite.config.ts`. Flutter `_tasks/post_generate.py` patches generated `*_repository.dart` HTTP paths and writes `lib/src/core/config/backend_routes.dart`.
- **Svelte AG-UI chat core** (`apps/svelte-frontend-template/template/src/lib/features/chat/`): full port of the Vue `ai_chat` module — `agent-client.svelte.ts` wrapping `@ag-ui/client`, streaming text deltas, tool-call lifecycle, HITL prompts, JSON-Patch state reducer, model selector, approval mode toggle, soft-imported auth so the chat compiles in `include_auth=false` projects too. New deps: `@ag-ui/client`, `@ag-ui/core`, `@modelcontextprotocol/ext-apps`, `fast-json-patch`, `marked`, `dompurify`.
- **Flutter Dart-native AG-UI chat core** (`apps/flutter-frontend-template/{{project_slug}}/lib/src/features/chat/`): pure Dart implementation of the AG-UI protocol — `AgUiClient` consuming Dio SSE streams, sealed `AgUiEvent` union, pure `reduce()` function applying RFC 6902 JSON Patch via `json_patch`, Riverpod `ChatNotifier` + selectors, widgets for chat panel / message bubble / tool-call chip / user-prompt card / agent status bar. New deps: `flutter_markdown`, `markdown`, `json_patch`, `shimmer`. Reducer covered by a 12-case unit test.
- **Workspace pane parity** (both frameworks): `WorkspacePane` + registry pattern, `FileExplorer`, `CredentialForm`, `ApprovalReview`, `UserPromptReview`, `FallbackActivity`, plus `AgUiEngine` and `McpExtEngine`. The Flutter MCP engine renders activities natively (no iframe sandbox — explicit deferral).
- **Canvas pane parity** (both frameworks): `CanvasPane` + registry, `DynamicForm`, `DataTable`, `Report` (markdown), `CodeViewer`, `WorkflowDiagram` (minimum-viable diagram), `Fallback`.

### Changed

- Svelte chat state model rewritten from a 1.5s setTimeout simulation to the AG-UI agent client (`chat.svelte.ts` exposes the same `getChatStore()` surface, but messages now stream from a real agent endpoint).
- Flutter `ChatMessage` freezed model lost the `timestamp` field (AG-UI messages don't carry one) and gained `isStreaming` semantics; existing chat_message_test updated.
- Generated READMEs gain a "Chat & agentic UI" section with usage and registry-extension examples.

### Added — Static analysis & CI hardening (prior)

- `ruff` + `ty` strict-ish config, `.pre-commit-config.yaml`, `.github/workflows/ci.yml` matrix (Linux + Windows × Python 3.11/3.12/3.13). Coverage floor raised to 75%.
- **`GeneratorError`** propagates clean error messages through `--json` (single-line envelope, exit 2) and stderr (`Generation failed: ...`, exit 2). `_run_backend_cmd(..., required=True)` raises on failure; `_git_init` checks every step.
- **End-to-end harness** (`tests/e2e/test_full_generation.py`): scaffolds python+vue, node+svelte, rust+none, and the multi-backend python+node+rust+vue+keycloak case, then runs the generated scaffold's native test suite. Marked `@pytest.mark.e2e`; nightly workflow at `.github/workflows/e2e.yml`.
- **`BACKEND_REGISTRY`** in `forge/config.py` drives language dispatch (CLI prompts, generator, variable mapper). Adding a 4th backend is now a one-day task — see [docs/adding-a-backend.md](docs/adding-a-backend.md).
- **`forge.toml`** stamped into every generated project (forge version + per-language template paths) so projects can be re-rendered with `copier update`.
- **Keycloak realm validation**: `render_keycloak_realm` parses the rendered JSON and asserts essential top-level keys before writing. Jinja typos fail generation immediately rather than at Keycloak boot.
- **`--verbose`** flag overrides `--quiet` for full Copier + subprocess output (works in JSON mode too — diagnostic output goes to stderr).
- **`forge --completion bash|zsh|fish`** prints a shell completion script.
- **Documentation**: `docs/architecture.md` (Mermaid diagram), `docs/adding-a-backend.md`, `CONTRIBUTING.md`, this changelog.

### Changed

- `ProjectConfig.validate` split into `_validate_backend_uniqueness`, `_validate_features_against_reserved`, `_validate_ports`, `_validate_keycloak_ports`. Behavior preserved.
- Interactive prompts unified — every backend now prompts for its language version (was previously skipped on the second-and-later backends).
- `backend_context` / `node_backend_context` / `rust_backend_context` collapsed to one function driven by `BACKEND_REGISTRY`. The legacy names remain as aliases.
- `_build_config` (105 lines) split into `_build_backends_from_cfg`, `_build_frontend_from_cfg`, and a slim orchestrator.

### Fixed

- `_git_init` previously ran three `subprocess.run` calls without `check=True`; a failed commit produced a "successful" generation with no commit. Each step is now checked.
- `_generate_frontend` / `render_frontend_dockerfile` no longer assume `config.frontend` is non-None — both now raise `GeneratorError` if called without a frontend.
- `BackendConfig` import was missing at module level in `forge/generator.py`; types now resolve under `ty check`.
- Stale tests in `tests/test_generator.py` (expected `<root>/test_app-e2e`) and `tests/test_e2e_templates.py` (expected old test descriptors) updated to match current template output.

## [0.1.0] - Initial release

- CLI scaffolds full-stack projects via Copier + uv.
- Backends: Python (FastAPI), Node.js (Fastify), Rust (Axum). Multi-backend per project.
- Frontends: Vue 3, Svelte 5, Flutter web.
- Optional Keycloak + Gatekeeper auth with multi-tenant isolation.
- Headless mode via `--config`, `--yes`, `--json` for CI and AI-agent integration.
- Auto-generated Playwright e2e suite per project.
