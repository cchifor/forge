"""Declarative fragment specs — :class:`~forge.appliers.renderers.FragmentRenderer`
implementations that a :class:`~forge.fragments.Fragment` ships alongside its
``inject.yaml`` to express ceremony declaratively rather than as per-backend
hand-written YAML.

The first inhabitant is :class:`MiddlewareSpec` (originally
``forge.middleware_spec``, Epic K); :class:`PortSpec` (Pillar A.4) is the
second. Future inhabitants — ``ServiceRegistrationSpec`` (RFC-009),
``ErrorCodeSpec`` (RFC-007), ``LifespanHookSpec`` — all conform to the
same :class:`FragmentRenderer` protocol so :meth:`FragmentPlan.from_impl`
can iterate them uniformly.
"""

from __future__ import annotations

from forge.specs.middleware import (
    MiddlewareSpec,
    render_axum_layer,
    render_fastapi_middleware,
    render_fastify_plugin,
    render_middleware_injections,
)
from forge.specs.port import (
    PortSpec,
    detect_port_cycle,
    render_axum_port,
    render_fastapi_port,
    render_fastify_port,
)

__all__ = [
    "MiddlewareSpec",
    "PortSpec",
    "detect_port_cycle",
    "render_axum_layer",
    "render_axum_port",
    "render_fastapi_middleware",
    "render_fastapi_port",
    "render_fastify_plugin",
    "render_fastify_port",
    "render_middleware_injections",
]
