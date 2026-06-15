"""``deploy.*`` features — topology-aware Helm chart deployment.

Adds a ``deploy.target`` option. When set to ``kubernetes`` it emits a
single topology-aware Helm umbrella chart under ``deploy/helm/``: one
Deployment/Service/HPA per backend, the frontend, an Ingress, and per-backend
ConfigMap/Secret, with optional in-cluster datastores behind an
``infra.inCluster`` values toggle. The default (``none``) and
``docker-compose`` emit nothing here, so projects that don't opt in are
byte-identical to before.

The chart's ``values.yaml`` is rendered at generate AND ``forge --update``
time from the project's deployment topology (the ``topology`` Jinja
variable, see :func:`forge.config._topology.compute_topology`), so the chart
stays current as backends/ports/frontend change. The chart's
``templates/*.yaml`` are pure Go-templates copied verbatim and resolve at
``helm install`` time.
"""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.deploy import fragments, options

    options.register_all(api)
    fragments.register_all(api)
