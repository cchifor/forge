"""Backend toolchain protocol and built-in implementations.

Before Epic S's toolchain refactor, ``generator.generate()`` dispatched
post-template-render steps via a hardcoded ``dict[BackendLanguage,
Callable]`` in ``generator.py`` plus an ``if bc.language ==
BackendLanguage.NODE`` branch for the mandatory ``npm install`` step.
Adding a fourth language meant editing the generator. Plugin backends
registered via :func:`forge.api.ForgeAPI.add_backend` had no way to
attach a post-generation hook at all — the plugin SDK could register
the template but not the setup steps that go with it.

This module defines the :class:`BackendToolchain` Protocol that
``BackendSpec.toolchain`` stores. The generator now calls
``spec.toolchain.install(...)`` and ``spec.toolchain.verify(...)``
uniformly for every backend, built-in or plugin. Built-ins live under
``forge/toolchains/{python,node,rust}.py``; plugins supply their own
implementation when they register.

The module deliberately has **no import from** ``forge.config`` — the
Protocol is pure ``pathlib.Path`` in / ``Check`` out, so plugging it
into ``BackendSpec`` does not create an import cycle. ``BackendSpec``
stores the toolchain as an ``Any`` field populated by a lazy
``default_factory`` pointing at :data:`NOOP_TOOLCHAIN`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "BackendToolchain",
    "Check",
    "CheckStatus",
    "NOOP_TOOLCHAIN",
    "NoopToolchain",
]


CheckStatus = Literal["ok", "warn", "fail", "skip"]


@dataclass(frozen=True)
class Check:
    """A single diagnostic result emitted by :meth:`BackendToolchain.verify`.

    Attributes:
        name: A short human-readable label (e.g. ``"ruff check"``,
            ``"npm test"``). Displayed by ``forge doctor`` and the
            matrix runner.
        status: ``"ok"`` (passed), ``"warn"`` (passed with issues),
            ``"fail"`` (did not pass), or ``"skip"`` (prerequisite
            missing — e.g. a CLI tool not on PATH).
        details: Free-form detail. Keep short; the matrix runner
            reports it inline. Use ``stderr`` tails or exit codes.
        duration_ms: Optional wall-clock duration of the check. Used
            for time-budget tracking in the matrix runner. Omit when
            the toolchain can't measure it meaningfully.
    """

    name: str
    status: CheckStatus
    details: str = ""
    duration_ms: int | None = None

    def is_failure(self) -> bool:
        return self.status == "fail"


@runtime_checkable
class BackendToolchain(Protocol):
    """Per-backend post-generation actions + verification.

    Instances attach to :class:`forge.config.BackendSpec` and are
    invoked by :func:`forge.generator.generate` after the base
    template is rendered and fragments are applied. Built-in
    instances live under ``forge/toolchains/{python,node,rust}.py``;
    plugin-registered backends supply their own.

    The three methods correspond to three generator phases:

    - :meth:`install` — runs once the base template + fragments have
      landed. Use for steps that produce artifacts the rest of the
      generation depends on (e.g. ``npm install`` producing a
      lockfile that Docker uses). Runs when ``not dry_run``. May be
      a no-op for languages whose templates ship working manifests.
    - :meth:`verify` — runs the toolchain's lint / type-check / test
      harness and returns a structured result. Called by the
      interactive setup path (when ``not quiet and not dry_run``),
      the matrix runner (lane B), and ``forge doctor``. Returning
      an empty list is allowed for a toolchain that has no
      meaningful checks.
    - :meth:`post_generate` — optional finalization hook (formatting
      passes, sidecar files). Always runs when ``not dry_run``.
      Default implementation should be a no-op.

    ``name`` is a short identifier used in diagnostic output. It
    should match the ``BackendLanguage.value`` or the plugin's wire
    string (``"python"``, ``"go"``, etc.).
    """

    name: str

    def install(self, backend_dir: Path, *, quiet: bool = False) -> None: ...

    def verify(self, backend_dir: Path, *, quiet: bool = False) -> list[Check]: ...

    def post_generate(self, backend_dir: Path, *, quiet: bool = False) -> None: ...


class NoopToolchain:
    """Toolchain that does nothing. Used as :class:`BackendSpec`'s default.

    Plugin backends that don't need post-generation hooks can rely on
    this; :meth:`verify` returning an empty list signals "nothing to
    check here" rather than "all checks passed", which is the honest
    answer when a plugin ships a template with no defined toolchain.
    """

    name = "noop"

    def install(self, backend_dir: Path, *, quiet: bool = False) -> None:
        return None

    def verify(self, backend_dir: Path, *, quiet: bool = False) -> list[Check]:
        return []

    def post_generate(self, backend_dir: Path, *, quiet: bool = False) -> None:
        return None


NOOP_TOOLCHAIN: BackendToolchain = NoopToolchain()


def default_toolchain_factory() -> BackendToolchain:
    """Lazy default factory for :class:`forge.config.BackendSpec.toolchain`.

    Returns :data:`NOOP_TOOLCHAIN`. Exposed as a module-level function
    so ``dataclasses.field(default_factory=...)`` can reference it
    without pulling the toolchains module in at config-import time
    (the factory is called when a ``BackendSpec(...)`` is instantiated,
    by which point the toolchains module is safely importable).
    """
    return NOOP_TOOLCHAIN
