"""Fragment appliers — single-responsibility decomposition of ``_apply_fragment``.

Each applier owns one mutation kind (files, injection, deps, env) and
consumes a :class:`~forge.fragment_context.FragmentContext`. A
:class:`FragmentPipeline` composes them in order; the default pipeline
reproduces the pre-Epic-A ``_apply_fragment`` behaviour byte-for-byte.

Epic A (1.1.0-alpha.1) lands the class structure as thin wrappers over
the existing :mod:`forge.feature_injector` helpers. A follow-up moves
the helper bodies wholesale into the applier modules, at which point
``feature_injector`` shrinks to the public API + shared constants.

The plug-points:

- Epic K (``MiddlewareSpec``) swaps :class:`FragmentInjectionApplier`
  with a subclass that synthesises injections from the spec.
- Epic F (provenance-driven uninstall) adds a removal path alongside
  :class:`FragmentFileApplier`.
- Third-party plugins can swap an applier by constructing their own
  :class:`FragmentPipeline` — useful for audit-logging injections,
  dry-run mode, or deferred apply strategies.
"""

from __future__ import annotations

from forge.appliers.deps import FragmentDepsApplier
from forge.appliers.env import FragmentEnvApplier
from forge.appliers.files import FragmentFileApplier
from forge.appliers.injection import FragmentInjectionApplier
from forge.appliers.pipeline import FragmentPipeline
from forge.appliers.plan import FragmentPlan

__all__ = [
    "FragmentDepsApplier",
    "FragmentEnvApplier",
    "FragmentFileApplier",
    "FragmentInjectionApplier",
    "FragmentPipeline",
    "FragmentPlan",
]
