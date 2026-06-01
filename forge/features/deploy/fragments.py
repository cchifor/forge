"""Kubernetes/Helm deployment fragments.

Three fragments realise ``deploy.target=kubernetes``:

  1. ``deploy_kubernetes`` — per-backend Deployment + Service + ConfigMap
     under the backend's ``k8s/``. Backend-scoped so each service ships its
     own manifests.
  2. ``deploy_k8s_hpa`` — a HorizontalPodAutoscaler manifest at the project
     root ``k8s/``. Project-scoped (emitted once).
  3. ``deploy_helm_chart`` — a Helm chart at ``helm/``. Project-scoped and
     language-agnostic.

All files are static and copied verbatim (no generation-time Jinja). The
Helm chart's Go-template ``{{ .Values.* }}`` syntax resolves at
``helm install`` time, and the raw ``k8s/`` manifests use generic labels +
an ``envFrom`` ConfigMap so image/namespace are supplied at apply time.
"""

from __future__ import annotations

from pathlib import Path

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


def register_all(api: ForgeAPI) -> None:
    # Per-backend raw Kubernetes manifests (Deployment + Service + ConfigMap).
    api.add_fragment(
        Fragment(
            name="deploy_kubernetes",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("deploy_kubernetes", "python"),
                ),
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("deploy_kubernetes", "node"),
                ),
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("deploy_kubernetes", "rust"),
                ),
            },
        )
    )

    # Project-scoped HPA at the project root.
    api.add_fragment(
        Fragment(
            name="deploy_k8s_hpa",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("deploy_k8s_hpa", "all"),
                    scope="project",
                ),
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("deploy_k8s_hpa", "all"),
                    scope="project",
                ),
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("deploy_k8s_hpa", "all"),
                    scope="project",
                ),
            },
        )
    )

    # Project-scoped Helm chart (language-agnostic). Lands at ``<project>/helm/``.
    api.add_fragment(
        Fragment(
            name="deploy_helm_chart",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("deploy_helm_chart", "all"),
                    scope="project",
                ),
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("deploy_helm_chart", "all"),
                    scope="project",
                ),
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("deploy_helm_chart", "all"),
                    scope="project",
                ),
            },
        )
    )
