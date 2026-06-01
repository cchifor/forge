"""``deploy.*`` features — Kubernetes/Helm deployment scaffolding.

Adds a ``deploy.target`` option. When set to ``kubernetes`` it emits
Kubernetes-native manifests (Deployment, Service, ConfigMap) per backend
plus a project-level HorizontalPodAutoscaler and a Helm chart under
``helm/``. The default (``none``) and ``docker-compose`` emit nothing here,
so projects that don't opt in are byte-identical to before.

The emitted manifests are static (verbatim-copied): the Helm chart carries
per-environment values in ``values.yaml`` and resolves them at ``helm
install`` time via Go-templates, and the raw ``k8s/`` manifests use generic
labels + an ``envFrom`` ConfigMap so image/namespace are set at apply time.
This keeps the fragment a pure file-copy (no generation-time templating).
"""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.deploy import fragments, options

    options.register_all(api)
    fragments.register_all(api)
