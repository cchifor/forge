"""Applier for a fragment's language-specific dependency adds.

Merges fragment-declared deps into the target backend's package
manifest (``pyproject.toml`` / ``package.json`` / ``Cargo.toml``) in a
way that preserves user-authored entries. Raises
:class:`FragmentError` when the manifest is missing, malformed, or the
fragment's spec string doesn't parse.

Epic A scaffold: delegates to the existing
``forge.feature_injector._add_dependencies``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.appliers.plan import FragmentPlan
    from forge.fragment_context import FragmentContext


class FragmentDepsApplier:
    """Adds fragment dependencies to the backend's package manifest."""

    def apply(self, ctx: FragmentContext, plan: FragmentPlan) -> None:
        if not plan.dependencies:
            return
        from forge.feature_injector import _add_dependencies  # noqa: PLC0415

        _add_dependencies(
            ctx.backend_config.language, ctx.backend_dir, plan.dependencies
        )
