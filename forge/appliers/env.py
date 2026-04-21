"""Applier for ``.env.example`` appends.

Each ``(key, value)`` pair a fragment declares is appended to
``<backend_dir>/.env.example`` unless an entry for ``key`` is already
present. Idempotent — running a fragment twice doesn't duplicate.

Epic A scaffold: delegates to the existing
``forge.feature_injector._add_env_var``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.appliers.plan import FragmentPlan
    from forge.fragment_context import FragmentContext


class FragmentEnvApplier:
    """Idempotent appends to ``<backend_dir>/.env.example``."""

    def apply(self, ctx: FragmentContext, plan: FragmentPlan) -> None:
        if not plan.env_vars:
            return
        from forge.feature_injector import _add_env_var  # noqa: PLC0415

        env_file = ctx.backend_dir / ".env.example"
        for key, value in plan.env_vars:
            _add_env_var(env_file, key, value)
