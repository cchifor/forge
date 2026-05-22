"""Declarative fragment specs — :class:`~forge.appliers.renderers.FragmentRenderer`
implementations that a :class:`~forge.fragments.Fragment` ships alongside its
``inject.yaml`` to express ceremony declaratively rather than as per-backend
hand-written YAML.

The first inhabitant is :class:`MiddlewareSpec` (originally
``forge.middleware_spec``, Epic K). Future inhabitants — ``ServiceRegistrationSpec``
(RFC-009), ``ErrorCodeSpec`` (RFC-007), ``LifespanHookSpec``, ``PortSpec`` —
all conform to the same :class:`FragmentRenderer` protocol so
:meth:`FragmentPlan.from_impl` can iterate them uniformly.
"""

from __future__ import annotations

from forge.specs.middleware import (
    MiddlewareSpec,
    render_axum_layer,
    render_fastapi_middleware,
    render_fastify_plugin,
    render_middleware_injections,
)

__all__ = [
    "MiddlewareSpec",
    "render_axum_layer",
    "render_fastapi_middleware",
    "render_fastify_plugin",
    "render_middleware_injections",
]
