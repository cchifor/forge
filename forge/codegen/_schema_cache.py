"""In-process JSON-schema cache keyed by absolute path + mtime.

Initiative #6 (scoped) — the codegen pipeline loads every shipped
``forge/templates/_shared/**/*.schema.json`` file on every codegen
pass:

* :func:`forge.codegen.ui_protocol.load_schema` parses each
  ``ui-protocol/*.schema.json`` on every invocation.
* :func:`forge.codegen.canvas_contract.load_components` does the same
  for the canvas component props schemas.
* :func:`forge.codegen.event_union.load_event_schemas` walks the same
  ui-protocol set a second time.

A single :func:`forge.codegen.pipeline.run_codegen` call can read the
same schema 3-5 times. The schemas are deterministic, on-disk JSON;
caching them in-process eliminates the redundant ``json.loads`` work
without changing observable behaviour.

The cache is keyed by ``Path.resolve()`` + ``Path.stat().st_mtime_ns``
(nanosecond resolution). That makes test mutations safe: a test that
rewrites a schema mid-run gets a fresh parse on the next call, and
forge itself never overwrites these schemas at runtime so mtime
churn is bounded by what the developer is doing.

Thread-safety: the cache is process-global. Concurrent writers to
the same path would race on the dict update, but the worst-case is
a redundant parse — never a wrong result, since the value stored is
always a fresh ``json.loads`` of the on-disk bytes. forge's
single-process / single-threaded codegen pipeline never exercises
that race today; flagging it as a known constraint for any future
parallel-codegen refactor (deferred — see Initiative #6 full plan).
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

# (mtime_ns, parsed_payload) keyed by resolved absolute path. The
# mtime_ns field is the cache-invalidation handle — when the on-disk
# file's stat() differs from the cached one we re-parse and overwrite
# the entry. Cleared by :func:`clear` (test-only).
_cache: dict[Path, tuple[int, Any]] = {}
_lock = threading.Lock()


def load_json_schema(path: Path) -> Any:
    """Return the parsed JSON payload at ``path``, cached by path + mtime.

    Equivalent to ``json.loads(path.read_text(encoding="utf-8"))`` plus
    in-process memoisation. The cache key is
    ``(path.resolve(), path.stat().st_mtime_ns)`` so mutating the
    file on disk (typical in tests) transparently invalidates the
    entry. Missing files raise ``FileNotFoundError`` from the
    underlying ``stat()`` — exceptions are NOT cached.

    Callers receive a deep copy of the cached payload, never the
    cached object itself. Pre-Init-6 the schema loaders called
    ``json.loads`` directly, so every read produced a fresh dict;
    callers were free to mutate the returned value (annotate it,
    pop fields, etc.) without affecting later reads. Preserving
    that contract via :func:`copy.deepcopy` means a misbehaving
    caller can't poison the cache for everyone else — including
    poisoning across threads, since the cache is process-global.
    """
    key = path.resolve()
    # stat() outside the lock — it's a cheap syscall and we want to
    # minimise the critical section. If a concurrent writer races,
    # the worst case is a doubled parse (harmless).
    mtime_ns = path.stat().st_mtime_ns

    cached = _cache.get(key)
    if cached is not None and cached[0] == mtime_ns:
        # Deep copy isolates the caller from the cache and from
        # every other consumer. Cost is bounded by schema size
        # (schemas ship at ~1 KiB each, far cheaper than re-parsing).
        return copy.deepcopy(cached[1])

    # Cache miss or mtime mismatch — re-parse.
    payload = json.loads(path.read_text(encoding="utf-8"))
    with _lock:
        _cache[key] = (mtime_ns, payload)
    # Same isolation rule applies on a fresh load — the cache holds
    # the canonical instance; the caller gets their own copy.
    return copy.deepcopy(payload)


def clear() -> None:
    """Drop every cached entry. Test-only.

    Useful when a test mutates a schema file in a way that doesn't
    change the mtime (rare — happens with mocked filesystems or
    sub-microsecond test cycles on filesystems that round mtime).
    Production code should never need to call this.
    """
    with _lock:
        _cache.clear()


def _peek_size() -> int:
    """Test-only helper: how many entries are currently cached."""
    return len(_cache)
