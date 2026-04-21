"""Applier for a fragment's ``files/`` tree.

Copies every file under ``plan.files_dir`` into ``ctx.backend_dir``
preserving structure. Respects ``ctx.skip_existing_files`` for the
``forge --update`` path. Raises :class:`FragmentError` with
``FRAGMENT_FILES_OVERLAP`` on a collision during fresh generation —
fragments must not clobber base-template files silently.

Epic A scaffold: delegates to the existing
``forge.feature_injector._copy_files`` function. A follow-up moves
the body into this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.appliers.plan import FragmentPlan
    from forge.fragment_context import FragmentContext


class FragmentFileApplier:
    """Copies a fragment's ``files/`` tree into the target dir."""

    def apply(self, ctx: FragmentContext, plan: FragmentPlan) -> None:
        if plan.files_dir is None:
            return
        from forge.feature_injector import _copy_files  # noqa: PLC0415

        _copy_files(
            plan.files_dir,
            ctx.backend_dir,
            skip_existing=ctx.skip_existing_files,
            collector=ctx.provenance,
            fragment_name=plan.feature_key,
        )
