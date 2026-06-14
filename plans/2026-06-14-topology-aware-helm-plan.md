# Forge: topology-aware Helm chart generation + app/deploy folder separation

## Context

Forge already ships a `deploy.target=kubernetes` feature, but it is hollow:

- The generated Helm chart (`forge/features/deploy/templates/deploy_helm_chart/`) is a
  **single generic `app` service** — one Deployment/Service/HPA for a container literally
  named `api`. It is **static-copied** (only `values.yaml.jinja` carries one `{{ server_port }}`).
- It therefore **does not model the real generated topology**: N backends (each needs its own
  Deployment+Service), the frontend, and the platform services that `docker-compose.yml.j2`
  wires (postgres, redis, keycloak, gatekeeper + keygen/realm-sync init jobs, traefik).
- Because it is static, it **cannot stay up to date**: add a backend, change a port, enable
  auth → the chart is unchanged. The HPA is a `REPLACE_WITH_BACKEND` placeholder; the image is
  hardcoded `ghcr.io/example/app`. **No** `helm lint`/`kubeconform` runs in CI and **no**
  scenario exercises `deploy.target=kubernetes`.
- Meanwhile `docker-compose.yml.j2` **is** fully topology-aware and is the de-facto source of
  truth for the deployment topology.

Separately, deployment artifacts are **scattered** in generated projects (`helm/` at root,
`k8s/hpa.yaml` at root, per-backend `services/<be>/k8s/`, root `docker-compose.yml`/`init-db.sh`,
frontend `nginx.conf`, auth-owned `infra/`), with no clean app-vs-deploy boundary; and in forge
*source*, deploy templating is split across `forge/templates/deploy/` (compose/Dockerfiles) and
`forge/features/deploy/` (helm/k8s).

**Goal:** make forge generate a **topology-accurate Helm umbrella chart** that **stays current on
`forge --update`**, and establish a **clean `deploy/` boundary** in both the generated project and
forge source — without destabilizing the existing auth/platform stack or the golden-snapshot
byte-identity contract.

**Decisions confirmed with the user:**
1. **Datastores posture:** chart renders **app workloads always** (per-backend + frontend); Postgres/
   Redis/Keycloak are **external-by-default** via values, with an `infra.inCluster` toggle that emits
   in-cluster StatefulSet/Deployments + keygen/realm-sync Jobs for kind/minikube.
2. **Generated folder layout:** idiomatic monorepo — `apps/`, `services/`, `packages/` (replacing
   `sdks/`), and a strict `deploy/{helm,k8s,infra,compose}` boundary; `docker-compose.yml` + `Makefile`
   stay at root.
3. **Engagement:** codex-reviewed plan → implement on approval → codex Phase-B impl review (full
   lifecycle).

## Target folder structure

**Generated project (target):**
```
<project>/
  apps/<frontend>/{src/, Dockerfile, nginx.conf}   # nginx.conf stays = frontend build asset (Wave 3 → ConfigMap)
  services/<backend>/{src/, Dockerfile}            # backend code + build def
  packages/                                        # shared/vendored libs (← rename of sdks/; Wave 2)
  deploy/
    helm/         # topology-aware umbrella chart (the deployment source of truth)
    k8s/          # raw manifests = `helm template`-derived (Makefile target), not separately authored
    infra/        # NEW deploy IaC (k8s Secret/ExternalSecret stubs, realm-import). Auth infra/ moves here later (Wave 4)
    compose/      # init-db.sh (genuine compose mount)
  infra/          # auth-owned keycloak/ + gatekeeper/ — UNCHANGED until Wave 4
  docker-compose.yml   # local-dev entrypoint (stays at root; build-contexts unaffected)
  Makefile             # NEW — wraps helm lint/template/kubeconform + compose up
  forge.toml  README.md
```
`catalog-info.yaml`, `.devcontainer/`, `terraform/`, `mobile-app/` are **deferred** (net-new
features, not folder moves).

**Forge source (target):** the `deploy` feature is the single owner of deployment templating.
Wave 1 relocates the helm/k8s fragment trees under `deploy/`; the **physical** merge of the compose
Jinja (`forge/templates/deploy/*.j2`) into the feature is deferred (avoids a churny `_jinja_env`
loader change racing the layout move) — ownership documented now, moved later.

## Approach (recommended)

**Make the Helm chart a topology-aware, project-scoped fragment whose `.jinja` files render from an
enriched render context**, so it rides the existing update/merge/provenance rail.

### Why fragment, not a new renderer (resolved architectural fork — validate in codex Phase A)
- A project-scope fragment is **already re-applied by both** `generator._apply_project_scope` **and**
  `update_project` (`apply_project_features` in `sync/forge_to_project/updater/_merge_driver.py`),
  through `FragmentFileApplier` → `copy_files` with `update_mode="merge"` → `file_three_way_decide`
  → `.forge-merge` sidecars + provenance. So **"keep up to date" + user-edit safety come for free**.
- A dedicated `render_helm_chart` (like `render_compose`) would have to be **hand-wired into
  `update_project`** (which does **not** re-run docker_manager renderers today — `render_compose`
  itself is only called at `forge new`) **and** re-implement merge/provenance, or it would silently
  clobber user edits to `values.yaml`. Rejected.
- The only real objection to the fragment path — "one proxy render can't emit one file per backend" —
  dissolves: **emit per-backend resources as Jinja `{% for be in topology.backends %}` loops inside
  single chart template files** (Helm accepts multi-document `---` YAML per file).

### The one load-bearing forge-core change: enrich the project-scope render context
Today `appliers/files.py:_build_render_context` exposes only `options` + `project_slug/name/
description/server_port`, built from a synthetic `BackendConfig(name="project")` proxy
(`_merge_driver.py:198`). It cannot see `config.backends`, the frontend, or keycloak. Thread a
topology object through:

1. **NEW `forge/config/_topology.py`** — `DeployTopology` dataclass + `compute_topology(config, plan)`
   pure builder, extracting the `backends_ctx` / `has_frontend` / `render_postgres` /
   `include_keycloak` / `database_mode` / `keycloak_port` logic from `docker_manager.render_compose`.
   Extract a shared `compute_render_postgres(...)` so `docker_manager` and the topology builder can't
   drift.
2. **`forge/fragment_context.py`** — add optional `project_topology: dict | None = None` to
   `FragmentContext` (+ `FragmentContext.filtered(...)`).
3. **`forge/appliers/files.py:_build_render_context`** — when `ctx.project_topology` is set, add
   `context["topology"] = ctx.project_topology`.
4. **`forge/sync/forge_to_project/updater/_merge_driver.py:apply_project_features`** — add optional
   `topology=` param, pass to `FragmentContext.filtered(project_topology=...)`.
5. **Call sites pass topology (both paths):** `generator._apply_project_scope` and
   `updater/__init__.py:_update_locked` each call `compute_topology(config, plan)` (the updater already
   reconstructs `config.backends`) and pass `topology=`.

**Byte-identity safety:** non-deploy projects are unaffected — only the helm fragment references
`topology.*`; `StrictUndefined` catches typos; existing golden snapshots (none enable
`deploy.target=kubernetes`) stay byte-identical. The topology param is optional, so all existing
`FragmentContext`/`apply_project_features` callers and test mocks compile unchanged.

### Chart design (rendered from `topology` at generate/update time)
Chart lives at `deploy/helm/`. **Jinja (generate/update time)** materializes *structure* from topology;
**Go-template (`{{ .Values.* }}`, helm-install time)** carries *per-environment knobs* only. Jinja wraps
Go syntax in `{% raw %}…{% endraw %}` (the boundary `test_helm_go_templates_survive_verbatim` guards).

Chart tree (each `*.jinja` rendered by the fragment applier; loops over `topology.backends`):
```
deploy/helm/
  Chart.yaml.jinja
  values.yaml.jinja                 # forge-owned: topology defaults (re-rendered, 3-way merged)
  values-prod.yaml.example.jinja    # shipped once; user copies → values-prod.yaml (forge never tracks it)
  templates/
    _helpers.tpl                    # fullname/labels/selectors
    deployments.yaml.jinja          # {% for be %} one Deployment per backend (probes, env, securityContext)
    services.yaml.jinja             # one Service per backend
    hpa.yaml.jinja                  # one HPA per backend (replaces the placeholder)
    frontend.yaml.jinja             # frontend Deployment+Service (+ nginx ConfigMap, Wave 3)
    ingress.yaml.jinja              # standard Ingress; path /api/<be> → <be> Service, / → frontend
    configmap.yaml.jinja            # per-backend non-secret env
    secret.yaml.jinja               # per-backend secret STUB (placeholder) + externalsecret.yaml stub
    infra.yaml.jinja                # postgres StatefulSet+PVC / redis / keycloak — {{- if .Values.infra.inCluster }}
    jobs.yaml.jinja                 # migrate (pre-install/pre-upgrade hook) + keygen/realm-sync (infra-gated)
```
- **values.yaml schema** — *forge-filled (topology):* `workloads:` map keyed by backend name
  `{image, containerPort=server_port, replicaCount, resources, autoscaling{…}, env{language-correct
  keys}}`; `frontend{image,port:80,…}`; `ingress{enabled,className,host,paths}`;
  `externalServices{postgres{host,port,database per backend}, redis, keycloak}` (default);
  `infra{inCluster:false, postgres{storage}, redis, keycloak{realm,clientId}}`. *User-override
  (values-prod.yaml.example):* image tags, replicas/autoscaling bounds, resources, `ingress.host/
  className`, `infra.inCluster`, secret refs.
- **env → k8s:** split each backend's compose env into a **ConfigMap** (non-secret: `ENV`/`NODE_ENV`/
  `RUST_LOG`, `APP__SERVER__PORT`/`PORT`, `APP__SECURITY__AUTH__*`, `GATEKEEPER_ISSUER`,
  `SERVICE_AUDIENCE`, `INTERNAL_SERVICE_URL_*` rewritten to Service DNS) and a **Secret** (`APP__DB__URL`/
  `DATABASE_URL`, `GATEKEEPER_CLIENT_SECRET`, keycloak admin). Deployment uses `envFrom:
  [configMapRef, secretRef]`.
- **service-DNS rewrite:** `postgres:5432`/`redis:6379`/`keycloak:8080`/`gatekeeper:5000` →
  `.Values.externalServices.*` when external, `<release>-<svc>` when `infra.inCluster`;
  `INTERNAL_SERVICE_URL_*` (`<callee>:<port>`) → `http://<release>-<callee>:<port>` (always in-chart).
- **init one-shots → Helm hooks:** `<be>-migrate` as `pre-install`/`pre-upgrade` hook Jobs (hook-weight
  ordered); keygen/realm-sync as hooks gated by `infra.inCluster`. Document failure semantics +
  `hook-delete-policy`.
- **Ingress replaces dev Traefik:** standard `networking.k8s.io/v1` Ingress; the Traefik
  `replacepathregex` maps to a controller-specific rewrite annotation behind a values flag (default
  nginx `rewrite-target`) — **documented as the least-portable mapping**.
- **raw `deploy/k8s/`:** derived, not separately authored — `Makefile` target
  `helm template deploy/helm > deploy/k8s/rendered.yaml`, so raw manifests can never drift from the
  chart (this also answers the long-standing "why both helm AND k8s?" question; the static
  `deploy_kubernetes` + `deploy_k8s_hpa` fragments are retired).

## Critical files

- **Forge-core (the enrichment):** `forge/config/_topology.py` (NEW), `forge/fragment_context.py`,
  `forge/appliers/files.py` (`_build_render_context`), `forge/sync/forge_to_project/updater/
  _merge_driver.py` (`apply_project_features`), `forge/sync/forge_to_project/updater/__init__.py`
  (`_update_locked`), `forge/generator.py` (`_apply_project_scope`), `forge/docker_manager.py`
  (extract `compute_render_postgres`).
- **Chart templates:** `forge/features/deploy/templates/deploy_helm_chart/all/files/deploy/helm/**`
  (rewritten topology-aware tree).
- **Deploy feature wiring:** `forge/features/deploy/{fragments.py,options.py,feature.toml}` — retire
  static helm/`deploy_kubernetes`/`deploy_k8s_hpa`; add `deploy.kubernetes.*` sub-options
  (ingress.className/host, image.registry, namespace) consumed via `reads_options`.
- **Folder moves:** `forge/docker_manager.py` (`render_init_db` → `deploy/compose/`; `sdks:`→`packages`
  host path keeping the `sdks` build-context *name*), `forge/templates/deploy/docker-compose.yml.j2`
  (init-db mount, `./packages`), `forge/appliers/deps.py` (npm `sdks`→`packages`), auth
  `platform_auth_sdk_*` + `shared_lib` `files/sdks/`→`files/packages/` (77 files), service
  `Dockerfile.jinja`/`pyproject.toml.jinja` host paths, `tests/matrix/runner.py` weld stubs +
  `tests/matrix/fixtures/sdks/`.
- **Tests/CI:** `tests/test_deploy_feature.py` (repoint paths), `tests/test_golden_snapshots.py`
  (+ new `deploy_k8s` preset), `tests/matrix/scenarios.yaml` (+ `py_vue_k8s`),
  `.github/workflows/ci.yml` (+ `deploy-helm-lint` job), `tests/golden/snapshots/full_feature_max.json`
  (Wave-2 re-baseline).
- **Docs:** `docs/DEPLOYMENT.md` (k8s/Helm section), `README.md` (folder tree + roadmap).

## Phasing (each wave independently green; never leaves generation red)

- **Wave 1 — topology-aware chart + enriched context + helm/k8s relocation + CI (LOW risk, core).**
  Forge-core enrichment; rewrite chart as topology-aware fragment at `deploy/helm/`; retire static
  k8s/hpa fragments; `init-db.sh`→`deploy/compose/`; new `deploy_k8s` golden preset (zero existing
  snapshots enable deploy, so no existing-snapshot churn); add `helm lint` + `helm template |
  kubeconform` CI job + `py_vue_k8s` scenario; Makefile + `deploy/k8s` derived target;
  `docs/DEPLOYMENT.md`. **This is the user's actual ask.**
- **Wave 2 — `sdks/`→`packages/` (HIGH risk, atomic, isolated commit).** Keep the Docker build-context
  identifier literally `sdks` (only its host source dir → `./packages`) to slash blast radius; move
  the 77 fragment `files/sdks/` trees, deps resolver, compose context, matrix fixtures, and
  re-baseline `full_feature_max.json` together. Matrix-smoke (lane C) is the gate.
- **Wave 3 — nginx baked-COPY → mounted ConfigMap (MEDIUM).** Drop `COPY nginx.conf` from frontend
  Dockerfiles; compose bind-mount `apps/<fe>/nginx.conf`; add a frontend nginx ConfigMap+volumeMount
  to the chart.
- **Wave 4 / DEFER — `infra/`→`deploy/infra/`.** Cross-feature (auth fragment trees + in-file runtime
  path refs + `infra/nginx-csp.conf` in all 6 snapshots); high snapshot churn, low payoff — separate
  coordinated change past the core deliverable.

## Risks & limitations (carry into docs)

- **Deterministic HMAC S2S secrets are dev-only** (`synthesis/platform.py`): the chart must **not**
  bake them into a k8s Secret — ship a placeholder Secret + ExternalSecret stub. The gatekeeper
  `service_registry.yaml` stores **argon2 hashes** of those plaintexts, so rotating the Secret without
  regenerating the registry breaks S2S — document the joint procedure; the chart alone can't fix it.
- **Ingress path-rewrite** has no portable cross-controller form (nginx annotation vs Traefik
  Middleware CRD) — values-gated annotation, documented.
- **Frontend baked API origin / host-network e2e** — out of chart scope; e2e service is intentionally
  omitted from the chart; document.
- **`infra.inCluster` path is the less-tested branch** — cover both branches (external default →
  no StatefulSet; in-cluster → StatefulSet+PVC) in tests.
- **Golden re-baselines** must be diffed by hand to prove only the intended paths moved.

## Verification (end-to-end)

- **Unit:** `compute_topology` shape (single/multi-backend, no-frontend, keycloak on/off, db none);
  `_build_render_context` exposes `topology` only when set; byte-identity unchanged for non-deploy
  fragments.
- **Integration:** generate a `python+node+vue` project with `deploy.target=kubernetes` → assert one
  Deployment/Service/HPA per backend + frontend + Ingress + per-backend ConfigMap/Secret; assert
  `infra.inCluster=false` emits **no** StatefulSet and `--set infra.inCluster=true` emits postgres
  StatefulSet+PVC + keygen/realm-sync Jobs; assert S2S secret is a stub, not hardcoded.
- **Keep-up-to-date (the headline):** generate → `forge --update` after adding a backend / changing a
  port → chart re-renders with the new workload; user edits to `deploy/helm/values.yaml` survive via
  `.forge-merge`; `values-prod.yaml` is never touched; `forge --verify` clean on a no-op re-run.
- **Chart validity (new CI gate):** `helm lint deploy/helm` + `helm template deploy/helm | kubeconform
  -strict -summary -kubernetes-version 1.29.0` for the `py_vue_k8s` scenario; `kubeconform -strict
  deploy/k8s/**`. (kind-based apply smoke is **optional/nightly**, not a PR gate.)
- **Golden:** new `deploy_k8s` snapshot captures `deploy/helm/**` + `deploy/k8s/**`; existing 6
  snapshots byte-identical in Wave 1.
- Tests at **unit + integration + e2e** layers (standing discipline).

## Process — codex-reviewed lifecycle (per user request)

On approval (exit plan mode): create a feature branch off `main`; move this plan to
`forge/plans/2026-06-14-topology-aware-helm-plan.md`; run **codex-reviewed-planning Phase A**
(`codex exec -m gpt-5.5` — the only model reachable for this account; `gpt-5.3-codex` is blocked) to
adjudicate the **fragment-vs-renderer fork** and the chart design, incorporate, finalize. Then
implement Wave 1 with strict TDD, running **codex Phase-B** impl review per wave. Conventional Commits,
no AI-coauthor trailers.

<!-- codex-review-status: pending -->
