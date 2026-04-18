"""Forge error hierarchy.

Lives in its own module (rather than generator.py) so docker_manager.py, cli.py,
and tests can all import it without pulling in generator's Copier dependency.
"""

from __future__ import annotations


class GeneratorError(RuntimeError):
    """Raised when a step required to produce a usable project fails.

    Callers (CLI main) catch this and surface it as a clean error message
    or a JSON error envelope, instead of leaking a stack trace.
    """
