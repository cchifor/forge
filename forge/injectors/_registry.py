"""Pluggable per-suffix injector dispatch (Pillar A.1 of the codegen
extensibility seams initiative).

Before this module landed, :func:`forge.appliers.injection._dispatch_injector`
hardcoded an ``if/elif`` chain over ``Path.suffix`` to pick between the
Python LibCST injector, the TypeScript regex/ts-morph injector, and the
text-marker fallback. Adding a new file type — ``.go``, ``.rs``,
``.kt`` — meant editing forge itself.

The registry generalises that dispatch. Built-in suffixes seed a
module-level dict at import time, and plugins extend it via
:meth:`forge.api.ForgeAPI.add_injector`. The applier consults
:func:`lookup_injector` instead of pattern-matching, so a Go-backend
plugin can register a ``.go`` AST injector without forking forge.

Injector contract
-----------------

Every injector — built-in or plugin-supplied — satisfies the
:class:`Injector` protocol::

    def inject(file: Path,
               feature_key: str,
               marker: str,
               snippet: str,
               position: str) -> None: ...

The signature mirrors the pre-registry ``inject_python`` /
``inject_ts`` / ``_inject_snippet`` shape so the call site in
``forge/appliers/injection.py`` is a one-line swap. The injector
mutates the file at ``file`` in place.

Wildcard fallback
-----------------

Suffix lookups that miss the dict fall back to the ``"*"`` entry,
seeded with the sentinel-based text injector. The fallback is
**registered**, not hardcoded, so plugins that want a different
catch-all (e.g. a smarter regex engine) can call
``register_injector("*", my_injector)`` to override it. Last-write
wins; the contract is intentionally simple — the registry is
single-process and the codegen pipeline mutates it from a single
thread.

Thread safety
-------------

The registry dict is populated once during import and then mutated
only via :func:`register_injector`. Forge's generator runs in a
single process; there's no need for locking. If a future async
codegen path ever wants concurrent registration, wrap
:func:`register_injector` in a lock at that boundary — the dict
itself doesn't need one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Injector(Protocol):
    """Callable contract every per-suffix injector satisfies.

    The protocol is intentionally permissive: any callable with the
    matching positional signature works, including the bare module-level
    functions the built-in injectors expose
    (``inject_python`` / ``inject_ts`` / ``_inject_snippet``). Plugins
    can supply a function, a bound method, or a class with ``__call__``
    — all three pass :func:`isinstance` against the protocol when
    structural typing is on, and the registry never inspects the object
    beyond invoking it.
    """

    def __call__(
        self,
        file: Path,
        feature_key: str,
        marker: str,
        snippet: str,
        position: str,
    ) -> None: ...


# Wildcard key for the catch-all entry. Kept as a constant so plugin
# code that wants to override the fallback can spell it without
# guessing at the dict's internal sentinel.
WILDCARD_SUFFIX = "*"


# Module-level registry. Populated once at import time by
# :func:`_seed_builtin_injectors`; subsequent mutations go through
# :func:`register_injector`. Keys are lowercase suffixes including
# the leading dot (``".py"``, ``".ts"``) plus the literal ``"*"``
# wildcard. Values are :class:`Injector`-shaped callables.
_REGISTRY: dict[str, Injector] = {}


def _inject_python_adapter(
    file: Path,
    feature_key: str,
    marker: str,
    snippet: str,
    position: str,
) -> None:
    """Thin adapter forwarding to :func:`forge.injectors.python_ast.inject_python`.

    The indirection keeps LibCST imports lazy — the registry module is
    imported before plugin discovery, and forcing LibCST resolution at
    that point would pull a ~1MB dependency tree into every ``forge --plugins
    list`` invocation. The adapter defers the import until the first
    Python file actually needs injecting.
    """
    from forge.injectors.python_ast import inject_python  # noqa: PLC0415

    inject_python(file, feature_key, marker, snippet, position)


def _inject_ts_adapter(
    file: Path,
    feature_key: str,
    marker: str,
    snippet: str,
    position: str,
) -> None:
    """Thin adapter forwarding to :func:`forge.injectors.ts_ast.inject_ts`.

    Same lazy-import rationale as :func:`_inject_python_adapter` — the
    TS injector pulls in the ts-morph sidecar plumbing, which we don't
    want to evaluate until a ``.ts`` / ``.tsx`` file is actually being
    touched.
    """
    from forge.injectors.ts_ast import inject_ts  # noqa: PLC0415

    inject_ts(file, feature_key, marker, snippet, position)


def _inject_text_adapter(
    file: Path,
    feature_key: str,
    marker: str,
    snippet: str,
    position: str,
) -> None:
    """Wildcard fallback adapter wrapping :func:`forge.injectors.sentinels._inject_snippet`.

    The sentinel-based text injector is the original pre-LibCST path and
    still handles every file type forge hasn't migrated to AST
    injection (``.rs``, ``.toml``, ``.yaml``, etc.). Keeping the
    adapter local to the registry module means the wildcard entry is
    obvious in :func:`_seed_builtin_injectors`, and any plugin
    overriding ``"*"`` knows exactly what the previous behaviour was.
    """
    from forge.injectors.sentinels import _inject_snippet  # noqa: PLC0415

    _inject_snippet(file, feature_key, marker, snippet, position)


def _seed_builtin_injectors() -> None:
    """Populate :data:`_REGISTRY` with the built-in per-suffix routing.

    Called exactly once at module import. The seed is deliberately a
    direct dict write rather than going through :func:`register_injector`
    so the built-ins don't have to compete with themselves on
    last-write-wins ordering — built-ins land first, plugins layer on
    top via :func:`register_injector`.

    Seeded entries (must stay in sync with the pre-registry dispatch
    at ``forge/appliers/injection.py``):

    * ``.py`` / ``.pyi`` → LibCST-backed Python injector
    * ``.ts`` / ``.tsx`` / ``.js`` / ``.jsx`` / ``.mjs`` / ``.cjs`` →
      TypeScript regex/ts-morph injector
    * ``*`` (wildcard) → sentinel-based text injector

    Add a new built-in here only if forge itself ships an AST injector
    for that language. Plugin-supplied injectors register via
    :meth:`forge.api.ForgeAPI.add_injector`.
    """
    for suffix in (".py", ".pyi"):
        _REGISTRY[suffix] = _inject_python_adapter
    for suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        _REGISTRY[suffix] = _inject_ts_adapter
    _REGISTRY[WILDCARD_SUFFIX] = _inject_text_adapter


def register_injector(suffix: str, injector: Injector) -> None:
    """Register ``injector`` as the handler for files ending in ``suffix``.

    ``suffix`` may be a real file extension (``".go"``, ``".kt"``) or
    the wildcard literal ``"*"`` to override the catch-all fallback.
    The leading dot is required for real suffixes — bare ``"go"`` is
    a different key from ``".go"`` and won't match anything
    :func:`lookup_injector` derives from a path. The match is
    case-insensitive: ``register_injector(".GO", ...)`` is stored as
    ``".go"`` so ``foo.GO`` and ``foo.go`` both resolve.

    Last-write wins on collision — re-registering an existing suffix
    silently replaces the previous handler. The contract is intentional:
    plugin authors who want to layer over a built-in injector
    (e.g. add a logging wrapper) can just call ``register_injector``
    with their wrapped version; tracking "first-write wins" would force
    a more complicated override API for no real gain on a single-process
    generator.

    Raises ``ValueError`` if ``suffix`` is empty or contains characters
    that can't appear in a real file suffix (whitespace, path
    separators) — better to fail at registration than to silently
    accept a key :func:`lookup_injector` will never produce.
    """
    if not suffix:
        raise ValueError("suffix must be non-empty (use '*' for the wildcard fallback)")
    if suffix != WILDCARD_SUFFIX:
        if not suffix.startswith("."):
            raise ValueError(
                f"suffix {suffix!r} must start with '.' (e.g. '.go') "
                f"or be the wildcard '{WILDCARD_SUFFIX}'"
            )
        if any(ch.isspace() for ch in suffix) or "/" in suffix or "\\" in suffix:
            raise ValueError(
                f"suffix {suffix!r} contains characters that cannot appear in a file suffix"
            )
    if not callable(injector):
        raise ValueError(
            f"injector for suffix {suffix!r} must be callable; got {type(injector).__name__}"
        )
    key = suffix if suffix == WILDCARD_SUFFIX else suffix.lower()
    _REGISTRY[key] = injector


def lookup_injector(filename: str | Path) -> Injector | None:
    """Return the injector registered for ``filename``'s suffix, or
    the wildcard fallback, or ``None`` if neither is registered.

    The suffix is derived via :class:`pathlib.Path` so the lookup is
    OS-agnostic (``"foo/bar.PY"`` → ``".py"``). Suffix matching is
    case-insensitive: ``.PY`` and ``.py`` both resolve to the Python
    injector.

    ``None`` is reachable only if a caller has explicitly removed the
    wildcard entry — :func:`_seed_builtin_injectors` always seeds it,
    and :func:`register_injector` doesn't support deletion. Returning
    ``None`` rather than raising lets the call site decide whether
    that's an error or a "skip this file" signal; today the only
    caller (``_dispatch_injector``) treats ``None`` as a hard error
    by way of the wildcard always being present.
    """
    suffix = Path(filename).suffix.lower()
    if suffix and suffix in _REGISTRY:
        return _REGISTRY[suffix]
    return _REGISTRY.get(WILDCARD_SUFFIX)


def _registry_snapshot() -> dict[str, Injector]:
    """Return a copy of the current registry. Test-only helper.

    Production code should not need to introspect the registry — the
    public API is :func:`register_injector` and :func:`lookup_injector`.
    Tests use this to assert built-ins are present and to restore the
    registry to a known state after monkey-patching it.
    """
    return dict(_REGISTRY)


# Seed at import time. The module-level call is intentional — the
# registry must be populated before any caller imports it, and the
# alternative (lazy seeding inside :func:`lookup_injector`) would
# complicate the test surface for no real benefit.
_seed_builtin_injectors()
