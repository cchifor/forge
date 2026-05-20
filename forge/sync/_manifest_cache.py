"""Per-invocation cache for parsed ``forge.toml`` data.

Initiative #6 (scoped) — the merge-zone applier called
:func:`forge.sync.manifest.read_forge_toml` once per merge-zone
injection from :func:`forge.appliers.injection._load_merge_baseline`,
which meant a fragment with N merge blocks paid N full
``tomlkit.parse`` round trips even though the manifest is frozen
for the duration of the run (it's only re-stamped at the very end
of ``forge --update`` / ``forge --harvest``).

This module exposes a :func:`cached_read_forge_toml` shim plus a
:func:`manifest_cache_scope` context manager. Inside the scope the
shim memoises results by resolved path; outside the scope it
delegates straight to :func:`read_forge_toml` so call sites that
don't opt in see no behaviour change.

Scope reset semantics: ``manifest_cache_scope()`` always installs a
fresh empty cache for the duration of the ``with`` block. CLI entry
points wrap their work in the scope so a single ``forge --update``
or ``forge --harvest`` invocation gets exactly one parse per
manifest path, and the cache is dropped on exit so the next
invocation (e.g. a long-running daemon, or back-to-back tests in the
same process) starts clean. ``write_forge_toml`` is the only re-
stamp path and it runs AFTER all applier work in the same call, so
no stale-read window exists.

The cache is keyed by ``Path.resolve()`` to collapse symlinks and
relative variants of the same on-disk file. Values are
:class:`forge.sync.manifest.ForgeTomlData` instances; the read path
already produces immutable-ish dataclasses, but callers should
treat returned data as read-only (mutating it would poison the
cache for the rest of the invocation).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.sync.manifest import ForgeTomlData


# ContextVar default of None means "no scope installed" — the shim
# falls through to a direct read in that case. A non-None value is
# the active per-invocation cache (a plain dict keyed by resolved
# path). ContextVar (rather than a module global) keeps the scope
# thread-local and asyncio-task-local, so a hypothetical future
# concurrent ``forge --update`` invocation per task wouldn't share
# state.
_active_cache: ContextVar[dict[Path, ForgeTomlData] | None] = ContextVar(
    "forge_manifest_cache",
    default=None,
)


@contextmanager
def manifest_cache_scope() -> Iterator[None]:
    """Install a fresh per-invocation cache for the duration of the block.

    Idempotent / nestable: a nested scope shadows the outer cache for
    the inner block's duration and restores the outer cache on exit
    (ContextVar reset token semantics). The common case is a single
    top-level scope per CLI invocation.
    """
    token = _active_cache.set({})
    try:
        yield
    finally:
        _active_cache.reset(token)


def cached_read_forge_toml(path: Path) -> ForgeTomlData:
    """Parse ``forge.toml`` once per invocation, then return the cached parse.

    Cache key is ``path.resolve()`` to collapse equivalent paths
    (relative vs absolute, with/without symlinks). Outside a
    :func:`manifest_cache_scope` block this is a straight pass-through
    to :func:`read_forge_toml`, so legacy call sites that haven't
    been ported see no behaviour change.

    Re-raises the same exceptions as :func:`read_forge_toml`
    (``FileNotFoundError`` on a missing manifest, ``ValueError`` on a
    malformed one). Exceptions are NOT cached — a subsequent call
    after the underlying file appears or is fixed will re-attempt the
    parse.
    """
    # Lazy import keeps this module free of the manifest module at
    # import time — `forge/sync/__init__.py` imports both manifest
    # and (eventually) this cache, and we want zero cycles.
    from forge.sync.manifest import read_forge_toml  # noqa: PLC0415

    cache = _active_cache.get()
    if cache is None:
        # No active scope — passthrough.
        return read_forge_toml(path)

    key = path.resolve()
    cached = cache.get(key)
    if cached is not None:
        return cached

    data = read_forge_toml(path)
    cache[key] = data
    return data


def _peek_cache_size() -> int:
    """Test-only helper: report how many entries the active cache holds.

    Returns ``-1`` when no scope is active. Used by
    :mod:`tests.test_manifest_cache` to assert that
    :func:`cached_read_forge_toml` actually populated the cache after
    the first call.
    """
    cache = _active_cache.get()
    if cache is None:
        return -1
    return len(cache)
