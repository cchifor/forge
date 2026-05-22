"""Generic :class:`FragmentRenderer` protocol (Pillar A.2, 1.3.0).

Generalises the Epic K :class:`~forge.specs.middleware.MiddlewareSpec`
contract so :class:`~forge.appliers.plan.FragmentPlan.from_impl` can
iterate over a heterogeneous tuple of declarative specs and dispatch
each one's renderer uniformly. RFC-007 ``ErrorCodeSpec``, RFC-009
``ServiceRegistrationSpec``, the future ``LifespanHookSpec``, and the
``PortSpec`` introduced in Pillar D / E all conform to this protocol.

The protocol intentionally does NOT mandate the Jinja-environment
parameter — :class:`MiddlewareSpec` renders its snippets verbatim from
string fields, while RFC-009 ``ServiceRegistrationSpec`` will render
through the macros under
``forge/templates/_shared/service_registration/{python,node,rust}.jinja``.
Both shapes are valid; the protocol receives ``jinja_env`` as a keyword
and renderers ignore it when they don't need one.

Contract recap (what every implementer must expose):

- ``name: str`` — fragment-scoped identifier, used in
  ``FORGE:BEGIN``/``FORGE:END`` sentinels.
- ``backend: BackendLanguage`` — which backend this spec targets;
  ``FragmentPlan.from_impl`` filters by backend before dispatch.
- ``attach_zone: str`` — the :class:`~forge.appliers.plan.InjectionZone`
  every injection this renderer emits should land in. ``"generated"``
  (the default for :class:`MiddlewareSpec`) preserves the historical
  re-generation-overwrites behaviour; renderers whose output is
  user-tweakable post-generation (e.g. service-registration providers)
  pick ``"user"``; renderers whose injections want three-way merge
  semantics pick ``"merge"``.
- ``render(*, backend, feature_key, jinja_env=None) -> tuple[_Injection, ...]``
  — produce the concrete injection records. Returns ``()`` when the
  spec doesn't apply to ``backend`` (so callers can dispatch
  unconditionally without filtering upfront — though the plan layer
  does filter for short-circuit clarity).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import jinja2

    from forge.appliers.plan import InjectionZone, _Injection
    from forge.config import BackendLanguage


@runtime_checkable
class FragmentRenderer(Protocol):
    """Common shape for every declarative fragment renderer.

    See module docstring for the contract; this Protocol exists so
    ``isinstance(spec, FragmentRenderer)`` works in adapter code and so
    static type checkers can flag drift in renderer implementations.
    """

    name: str
    backend: BackendLanguage
    attach_zone: InjectionZone

    def render(
        self,
        *,
        backend: BackendLanguage,
        feature_key: str,
        jinja_env: jinja2.Environment | None = None,
    ) -> tuple[_Injection, ...]:
        """Emit the injection records this renderer contributes.

        Implementations MUST return ``()`` (not raise) when ``backend``
        doesn't match ``self.backend`` — the plan layer's dispatch
        loop relies on this to stay simple.
        """
        ...
