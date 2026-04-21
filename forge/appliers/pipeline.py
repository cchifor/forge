"""Orchestrator composing the four appliers in the canonical order.

``FragmentPipeline.default()`` reproduces the pre-Epic-A
``_apply_fragment`` behaviour: build a :class:`FragmentPlan`, run
files → injection → deps → env in that order. The order matters —
inject.yaml can reference files a fragment just copied, and
dependency files (``pyproject.toml``, ``package.json``) are
themselves injection targets, so deps must run after injection.

Swap an applier by constructing a pipeline with your own instance:

    pipeline = FragmentPipeline(
        files=FragmentFileApplier(),
        injection=MyMiddlewareInjectionApplier(),
        deps=FragmentDepsApplier(),
        env=FragmentEnvApplier(),
    )
    pipeline.run(ctx, impl, feature_key)

Epic K uses this swap for its ``MiddlewareSpec``-aware injection
applier that synthesises injections on the fly from a fragment's
declared middlewares.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from forge.appliers.deps import FragmentDepsApplier
from forge.appliers.env import FragmentEnvApplier
from forge.appliers.files import FragmentFileApplier
from forge.appliers.injection import FragmentInjectionApplier
from forge.appliers.plan import FragmentPlan

if TYPE_CHECKING:
    from forge.fragment_context import FragmentContext
    from forge.fragments import FragmentImplSpec
    from forge.middleware_spec import MiddlewareSpec


@dataclass(frozen=True)
class FragmentPipeline:
    """Four-applier orchestrator. Instantiate via :meth:`default` for
    the standard ordering; swap fields when extending."""

    files: FragmentFileApplier = field(default_factory=FragmentFileApplier)
    injection: FragmentInjectionApplier = field(default_factory=FragmentInjectionApplier)
    deps: FragmentDepsApplier = field(default_factory=FragmentDepsApplier)
    env: FragmentEnvApplier = field(default_factory=FragmentEnvApplier)

    @classmethod
    def default(cls) -> FragmentPipeline:
        """Factory for the standard pipeline."""
        return cls()

    def run(
        self,
        ctx: FragmentContext,
        impl: FragmentImplSpec,
        feature_key: str,
        *,
        middlewares: tuple[MiddlewareSpec, ...] = (),
    ) -> None:
        """Build the plan + apply each phase in the canonical order.

        ``middlewares`` (Epic K) are expanded into injections at plan-
        build time using the renderer for the current backend. Fragments
        with no middleware declarations pass ``()`` and the plan looks
        identical to the pre-Epic-K shape.
        """
        plan = FragmentPlan.from_impl(
            impl,
            feature_key,
            options=ctx.options,
            middlewares=middlewares,
            backend=ctx.backend_config.language,
        )
        self.files.apply(ctx, plan)
        self.injection.apply(ctx, plan)
        self.deps.apply(ctx, plan)
        self.env.apply(ctx, plan)
