# Implementation review — topology-aware-helm waves 2-4 — round 1

<!-- codex-impl-review-status: finalized -->
<!-- converged round 1: codex gpt-5.5 verdict PASS, no blockers, zero actionable findings
     (every finding was a "confirmed passing" verification). -->

## Summary

- **Wave 2 (sdks→packages): PASS with high confidence.** The rename is atomic across all dimensions: host directories, docker build-context name, in-image COPY destinations, python/node/rust workspace member lists, path-dep resolvers (`appliers/deps.py`), and golden snapshots. No orphaned `sdks/` references; backend-local `services/<svc>/sdks/forge-core` correctly left untouched. Consistent application across `Cargo.toml.j2`, `package.json.j2`, the service Dockerfiles, and the compose `additional_contexts` gate ensures host and in-image layouts cannot drift.
- **Wave 3 (nginx.conf mounting): PASS.** Frontend Dockerfiles (node + flutter) drop `COPY nginx.conf`; compose bind-mounts the file; the chart defines a ConfigMap with `subPath` mount; the SPA fallback is correct and routing is delegated to the Ingress.
- **Wave 4 (infra→deploy/infra) + in-cluster gatekeeper: PASS.** Auth infra moved `files/infra/` → `files/deploy/infra/`; all three gatekeeper `compose.yaml` services updated; `keygen.py`/`realm_sync.py` comments updated. The chart's gatekeeper Deployment (keygen initContainer → pod-shared emptyDir) + post-install realm-sync Job (reads the bundled realm via `.Files.Get`) are correctly gated on `infra.inCluster` AND `infra.gatekeeper.enabled`, off by default.
- **Golden snapshots: PASS.** All 6 re-baselined; `files/packages/*` structure confirmed; no unintended drift.
- **No blockers; production-ready for the Wave 2-4 merge** (subject to the CI compose-smoke build gate, since cargo/npm/uv builds need network unavailable in the dev sandbox).

## Verified-correct (no action)

Every round-1 finding was a codex confirmation, each checked against the source and tests:
- Wave 2: `Cargo.toml.j2` rust workspace members → `packages/platform-auth-rs` (matches the in-image `COPY --from=packages . ./packages/`); `deps.py` resolves `workspace:*` → `file:../packages/<name>` (works host + in-docker); the python Dockerfile `sed` rewrites `../../packages/platform-auth` → `packages/platform-auth` (the dependency-confusion guard); `full_feature_max.json` shows `files/packages/*`, no orphaned `sdks/*`.
- Wave 3: nginx ConfigMap `mountPath=/etc/nginx/conf.d/default.conf` + `subPath=default.conf`, data key `default.conf`; compose bind-mount fail-fast on missing host file.
- Wave 4: `keycloak-realm.json` rendered to `deploy/infra/` then copied to `deploy/helm/files/` for `.Files.Get`; keygen initContainer command `python scripts/keygen.py` (script in-image at `/project/scripts/`); realm-sync `post-install` hook (weight 5) runs after main workloads and reads the realm ConfigMap; `gatekeeper.enabled` defaults `false` (production posture).

## Diff stat

```
264 files changed, 893 insertions(+), 783 deletions(-)
```
(Full per-file stat in the codex run output; dominated by the `files/{sdks => packages}/**` and
`files/{ => deploy}/infra/**` renames plus the chart/template/test edits and the 6 golden re-baselines.)
