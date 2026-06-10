"""PhaseHook protocol — plugin observability of generator phases.

Pillar A.3 of the architectural improvement plan
(``.claude/plans/deep-gliding-mccarthy.md``). Lets plugins observe
generation phases without forking ``forge.generator``: telemetry sinks,
SBOM emitters, supply-chain signers, post-``forge new`` shell scripts.

Hooks fire from the existing :func:`forge.logging.phase_timer` context
manager that already wraps every generator phase — no plumbing
changes to ``generator.py`` beyond two lines in ``phase_timer`` itself
plus a one-line ``_fire_generate_complete`` call at the end of
:func:`forge.generator.generate`. A hook implements three callbacks:

* :meth:`PhaseHook.on_phase_start` — fires when a ``phase_timer``
  ``with`` block enters.
* :meth:`PhaseHook.on_phase_end` — fires when the block exits, with
  the measured duration and any exception (``None`` on success).
* :meth:`PhaseHook.on_generate_complete` — fires once at the end of
  :func:`forge.generator.generate`, with the populated
  :class:`forge.reports.GenerationReport` when one was supplied
  (else ``None``).

Plugins register hooks via :meth:`forge.api.ForgeAPI.add_hook`. The
fire helpers (``_fire_*``) iterate the registry in registration
order and **swallow per-hook exceptions** — one buggy plugin must not
take down generation. Exceptions are logged at ``WARNING`` with the
hook class name + phase name so the operator can diagnose.

This module lives at ``forge.hooks`` (not ``forge.plugins._hooks``)
because ``forge.plugins`` is a single-module shim, not a package.
The brief allows either; the leaf-module form keeps imports flat
and avoids restructuring the existing plugins surface.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from forge.reports import GenerationReport

__all__ = [
    "PhaseHook",
    "register_hook",
    "registered_hooks",
    "reset_hooks_for_tests",
    "unregister_hook",
]


_logger = logging.getLogger("forge.hooks")


@runtime_checkable
class PhaseHook(Protocol):
    """Callbacks a plugin implements to observe generator phases.

    Every method is mandatory at the type-checker level — concrete
    hooks should implement them as no-ops when they don't care about
    a given callback. The fire helpers still call each method
    defensively (a hook that raises is logged + skipped) so a
    plugin that ships only ``on_phase_end`` and stubs the other two
    as ``pass`` is the recommended minimal shape.

    ``ctx`` is the structured-event payload that
    :func:`forge.logging.phase_timer` forwards into the log record
    (``backend``, ``language``, ``framework`` etc.). It is the SAME
    dict instance the timer constructs; hooks MUST treat it as
    read-only — mutations leak into the emitted log event and into
    every subsequently-fired hook.
    """

    def on_phase_start(self, name: str, ctx: dict[str, Any]) -> None:
        """Called when a ``phase_timer`` block enters.

        ``name`` is the phase event identifier (e.g.
        ``"generate.copier.backend"``). ``ctx`` is the kwargs dict
        the caller passed to :func:`phase_timer`.
        """
        ...

    def on_phase_end(
        self,
        name: str,
        ctx: dict[str, Any],
        duration_ms: int,
        error: Exception | None,
    ) -> None:
        """Called when a ``phase_timer`` block exits.

        ``duration_ms`` is the measured wall time. ``error`` is the
        exception that bubbled out of the block (``None`` on success).
        The hook is called BEFORE the exception re-raises, so a hook
        observing failures cannot suppress them.
        """
        ...

    def on_generate_complete(self, report: GenerationReport | None) -> None:
        """Called once at the end of a generation that ran to completion.

        ``report`` is the populated :class:`forge.reports.GenerationReport`
        when the caller supplied one to :func:`forge.generator.generate`,
        else ``None``. Hooks driving SBOM / signing pipelines typically
        require a report and should guard with ``if report is None: return``.

        Not called when generation raised before completing — phase
        exceptions surface through ``on_phase_end(error=...)`` and
        re-raise; ``on_generate_complete`` only fires on the happy
        path so plugins can treat it as the "all phases done, project
        on disk" signal.
        """
        ...


# Module-level registry. Hooks fire in registration order. The list
# is mutable (plugin discovery appends during ``ForgeAPI.add_hook``)
# but treated as immutable by the fire helpers: they snapshot via
# ``list(_HOOKS)`` before iterating so a hook that calls back into
# ``register_hook`` mid-iteration doesn't observe its own addition.
_HOOKS: list[PhaseHook] = []


def register_hook(hook: PhaseHook) -> None:
    """Append ``hook`` to the firing registry.

    Plugins call this indirectly via :meth:`forge.api.ForgeAPI.add_hook`.
    Direct callers (tests, in-tree wiring) are supported but rare —
    the API surface is the supported entry point.
    """
    _HOOKS.append(hook)


def unregister_hook(hook: PhaseHook) -> None:
    """Remove ``hook`` from the firing registry if present (idempotent).

    Used to scope a hook to a single operation — e.g. the generator
    registers a phase-timings collector for one ``generate()`` call and
    removes it in a ``finally`` so it never leaks into the next."""
    with contextlib.suppress(ValueError):
        _HOOKS.remove(hook)


def registered_hooks() -> tuple[PhaseHook, ...]:
    """Return the current registry as a tuple snapshot."""
    return tuple(_HOOKS)


def reset_hooks_for_tests() -> None:
    """Clear the hook registry. Use ONLY from tests.

    Test isolation: pytest-xdist runs collect each test into a fresh
    process so the registry is naturally clean per worker, but within
    a worker a test that appends a hook would leak into the next.
    Call this in fixtures (``autouse=True`` is fine) or at test
    setup. :func:`forge.plugins.reset_for_tests` already calls this
    so test suites using the plugin reset fixture don't need to call
    it separately.
    """
    _HOOKS.clear()


def _fire_phase_start(name: str, ctx: dict[str, Any]) -> None:
    """Iterate hooks and call ``on_phase_start``; swallow + log errors.

    A hook that raises is logged at WARNING with the hook class name
    + phase name and skipped — the contract is "buggy plugin doesn't
    crash generation". Other hooks still fire; generation continues.
    """
    for hook in list(_HOOKS):
        try:
            hook.on_phase_start(name, ctx)
        except Exception:  # noqa: BLE001 — contract: one buggy hook can't break generation
            _logger.warning(
                "phase hook %s.on_phase_start raised for phase %r; skipping",
                type(hook).__name__,
                name,
                exc_info=True,
            )


def _fire_phase_end(
    name: str,
    ctx: dict[str, Any],
    duration_ms: int,
    error: Exception | None,
) -> None:
    """Iterate hooks and call ``on_phase_end``; swallow + log errors.

    Same exception-swallow contract as :func:`_fire_phase_start`.
    ``error`` is the exception that bubbled out of the timed block
    (``None`` on success); the fire helper does NOT re-raise on
    behalf of the block — the phase_timer's own ``raise`` re-raises
    the original after the fire returns.
    """
    for hook in list(_HOOKS):
        try:
            hook.on_phase_end(name, ctx, duration_ms, error)
        except Exception:  # noqa: BLE001
            _logger.warning(
                "phase hook %s.on_phase_end raised for phase %r; skipping",
                type(hook).__name__,
                name,
                exc_info=True,
            )


def _fire_generate_complete(report: GenerationReport | None) -> None:
    """Iterate hooks and call ``on_generate_complete``; swallow + log errors."""
    for hook in list(_HOOKS):
        try:
            hook.on_generate_complete(report)
        except Exception:  # noqa: BLE001
            _logger.warning(
                "phase hook %s.on_generate_complete raised; skipping",
                type(hook).__name__,
                exc_info=True,
            )
