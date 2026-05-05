"""Applier for source-snippet injections described by ``inject.yaml``.

Owns the largest and trickiest chunk of the pre-Epic-A ``_apply_fragment``
body: zone dispatch (``generated`` / ``user`` / ``merge``), sentinel
block detection, three-way merge integration, and per-suffix routing to
the LibCST Python injector, the TS regex/ts-morph injector, or the
text-marker fallback.

Epic A scaffold: delegates to the existing
``forge.feature_injector._apply_zoned_injection``. A follow-up moves
the body plus :mod:`forge.injectors` dispatch into this module;
Epic K's ``MiddlewareSpec`` subclass then hooks by extending this
applier's ``apply()`` with synthesized middleware injections.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.appliers.plan import FragmentPlan
    from forge.fragment_context import FragmentContext


class FragmentInjectionApplier:
    """Applies every ``_Injection`` in the plan via the zoned dispatcher."""

    def apply(self, ctx: FragmentContext, plan: FragmentPlan) -> None:
        if not plan.injections:
            return
        from forge.feature_injector import _apply_zoned_injection  # noqa: PLC0415

        for inj in plan.injections:
            target = ctx.backend_dir / inj.target
            applied = _apply_zoned_injection(
                target,
                inj,
                project_root=ctx.project_root,
                collector=ctx.provenance,
            )
            if applied and ctx.provenance is not None:
                ctx.provenance.record(target, origin="fragment", fragment_name=plan.feature_key)
