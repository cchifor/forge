# Implementation review — topology-aware-helm — round 1

<!-- codex-impl-review-status: finalized -->
<!-- converged round 1: 1 important finding (parallel migrate-Job safety) ADDRESSED in source
     (jobs.yaml comment + DEPLOYMENT.md note); 2 nits codex concluded need no action. -->
<!-- phase-B model: codex exec -m gpt-5.5 -->

## Resolution

- **Parallel migrate-Job safety (important)** — ADDRESSED. `jobs.yaml` and
  `docs/DEPLOYMENT.md` now document that the shared hook-weight runs migrate Jobs
  in parallel, which is safe because each backend owns its own database, with
  guidance to use ascending weights for a shared DB.
- **keycloak_port unused / zero-path Ingress (nits)** — no action: codex itself
  concluded both are intentional / not realizable under forge's invariants.

## Summary

- **Overall quality:** The implementation is solid and closely adheres to the plan. The topology module correctly extracts shared logic for both compose and Helm, and the fragment-based approach elegantly piggybacks on the existing three-way-merge and provenance infrastructure, eliminating the need for a new renderer.
- **Hybrid approach correctness:** The deviation from "per-backend loops inside chart templates" to "Jinja renders values.yaml, pure Go templates range over .Values.workloads" is architecturally sounder and validated by helm lint + kubeconform tests. Go templates can be linted by Helm; the hybrid boundary is cleanly separated and preserved in tests.
- **Keep-current mechanism:** The updater correctly recovers `server_port` from `.copier-answers.yml` via defensive type checking (explicit bool rejection), and topology is computed in both generation and update paths. Idempotent update tests + port re-render + user-edit preservation tests all pass.
- **Security posture:** Secrets are CHANGEME placeholders (never baked); the gatekeeper S2S keygen/realm-sync defer is documented in code. Ingress path rewrite is nginx-specific but values-gated; the limitation is acknowledged in the plan.
- **One risk:** Migration hook Jobs all run at weight -5, executing in parallel across backends. This is safe only because each backend has its own database; the plan should document this assumption.

## Findings

### Migration Job hooks execute in parallel — safe due to per-backend databases
**Location:** jobs.yaml:20–21 (helm.sh/hook-weight: "-5")
**Severity:** important

### Keycloak realm/keycloak_port in topology computed but port unused
**Location:** forge/config/_topology.py:159, values.yaml.jinja:129–131
**Severity:** nit

### One potential edge case: zero-path Ingress
**Location:** ingress.yaml:23–32
**Severity:** nit

### Verified-correct (no action)
The remaining round-1 findings were codex CONFIRMATIONS, not critiques — each verified against the source and tests, no change required:
- Service selector ↔ Deployment labels ↔ HPA scaleTargetRef coupling is consistent (services/deployments/hpa.yaml).
- Ingress backends reference emitted Services; ConfigMap/Secret per-backend env split is sound.
- Go-template syntax survives Jinja verbatim (templates carry no `.jinja` suffix; tested).
- The hybrid Jinja-values + pure-Go-templates approach is sound and gated by helm lint + kubeconform.
- `_recovered_server_port` is type-safe (rejects bool, handles missing/unparseable answers).
- Frontend presence toggles correctly; infra in-cluster toggle gates StatefulSet/Deployment emission (both branches tested).
- init-db.sh relocation updates the compose mount; golden snapshots show only that relocation; non-deploy byte-identity preserved.
- The chart rides the existing `apply_project_features` three-way-merge/provenance rail (idempotency + user-edit preservation tested).
- Deferred Wave-2/3/4 work is documented in code + plan + CHANGELOG (no silent omissions).
- `deploy-helm` CI gate runs helm lint + helm template + kubeconform -strict across 6 scenarios.

## Diff stat

```
 .github/workflows/ci.yml                           |  23 +++
 CHANGELOG.md                                       |  32 ++++
 README.md                                          |  12 +-
 docs/DEPLOYMENT.md                                 |  75 ++++++++++
 forge/appliers/files.py                            |   6 +
 forge/config/_topology.py                          | 162 ++++++++++++++++++++
 forge/docker_manager.py                            |  76 ++++------
 forge/features/deploy/__init__.py                  |  25 ++--
 forge/features/deploy/feature.toml                 |   6 +-
 forge/features/deploy/fragments.py                 |  72 +++------
 forge/features/deploy/options.py                   |  30 ++--
 .../deploy_helm_chart/all/files/Makefile.jinja     |  36 +++++
 .../all/files/deploy/helm/values.yaml.jinja        | 153 +++++++++++++++++++
 forge/fragment_context.py                          |  11 ++
 forge/generator.py                                 |   4 +
 forge/sync/forge_to_project/updater/__init__.py    |  98 ++++++++----
 .../sync/forge_to_project/updater/_merge_driver.py |   2 +
 forge/templates/deploy/docker-compose.yml.j2       |   2 +-
 tests/golden/snapshots/full_feature_max.json       |  16 +-
 tests/golden/snapshots/multi_backend.json          |  18 +--
 tests/test_deploy_feature.py                       | 156 ++++++++++---------
 tests/test_deploy_helm_validation.py               |  88 +++++++++++
 tests/test_deploy_keep_current.py                  |  76 ++++++++++
 tests/test_deploy_topology.py                      | 138 +++++++++++++++++
 55 files changed, 1615 insertions(+), 730 deletions(-)
```
