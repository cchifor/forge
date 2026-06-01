"""``deploy.*`` options — Kubernetes/Helm deployment targets."""

from __future__ import annotations

from forge.api import ForgeAPI
from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
)


def register_all(api: ForgeAPI) -> None:
    api.add_option(
        Option(
            path="deploy.target",
            type=OptionType.ENUM,
            default="none",
            options=("none", "docker-compose", "kubernetes"),
            summary="Deployment target — none, docker-compose, or Kubernetes + Helm.",
            description="""\
Selects the deployment infrastructure scaffold.

- ``none`` (default): no deployment files beyond the standard generated
  ``docker-compose.yml`` forge already emits for local dev.
- ``docker-compose``: reserved for explicit compose-targeted tweaks; today
  identical to ``none`` since compose is always generated.
- ``kubernetes``: emits Kubernetes-native manifests under each backend's
  ``k8s/`` (Deployment + Service + ConfigMap), a project-level
  HorizontalPodAutoscaler, AND a Helm chart under ``helm/`` for templated,
  multi-environment promotion.

KUBERNETES manifests wire liveness/readiness probes to ``/health``, set
resource requests/limits, and run as a non-root user. Per-environment
values (image, replicas, namespace) live in the Helm chart's
``values.yaml`` and resolve at ``helm install`` time; the raw ``k8s/``
manifests use generic labels + an ``envFrom`` ConfigMap so they apply
cleanly with ``kubectl apply -k`` / kustomize overlays.

BACKENDS: python, node, rust (tier 1 — manifests are language-agnostic).""",
            category=FeatureCategory.PLATFORM,
            stability="beta",
            enables={
                "kubernetes": (
                    "deploy_kubernetes",
                    "deploy_k8s_hpa",
                    "deploy_helm_chart",
                ),
                "docker-compose": (),
                "none": (),
            },
        )
    )
