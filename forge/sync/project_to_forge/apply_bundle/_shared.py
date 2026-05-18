"""Shared helpers used by 2+ apply_bundle handler modules.

Split out from the original ``apply_bundle.py`` god module — see
:mod:`forge.sync.project_to_forge.apply_bundle` for the public surface.
This module collects:

* Fragment-tree resolution helpers (files / blocks / deps / env all
  need to locate the fragment dir on disk).
* The ``fragments.py`` source-finder used by deps + env.
* Low-level Python-source parsing primitives (paren matching, string-
  literal skipping, kwarg-span scanning) used by both deps and env
  rewriters.
* The ``_RewriteResult`` / ``_KwargSpan`` dataclasses shared between
  deps and env rewriters.

The helpers here are intentionally private (leading underscore); they
are not part of the package's public surface. Only the dispatcher in
``__init__.py`` re-exports user-facing names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.extractors.pipeline import CandidatePatch
    from forge.fragments import Fragment, FragmentImplSpec


def _resolve_impl_for_candidate(
    fragment: Fragment, cand: CandidatePatch
) -> FragmentImplSpec | None:
    """Pick the fragment impl whose ``files/`` tree carries ``cand.rel_path``.

    The harvester records a ``backend`` label (``api`` / ``project``)
    on the candidate but not the underlying ``BackendLanguage``, so we
    can't index ``fragment.implementations`` directly. Instead, we
    enumerate the available impls and prefer one whose ``files/``
    subtree already contains the rel-path on disk. Failing that we
    fall back to the first registered impl — the user-added-file case.

    Returns the matching :class:`FragmentImplSpec`, or ``None`` when
    the fragment has no implementations registered.
    """
    impls = fragment.implementations
    if not impls:
        return None
    # First pass: prefer an impl whose files_dir already carries the
    # rel_path. That's the typical "fragment file the user edited" case.
    from forge.fragments import _resolve_fragment_dir  # noqa: PLC0415

    for impl in impls.values():
        try:
            fragment_dir = _resolve_fragment_dir(impl.fragment_dir)
        except Exception:  # noqa: BLE001 — registry-level path resolution glitch.
            continue
        if (fragment_dir / "files" / cand.rel_path).is_file():
            return impl
    # Fallback: take the first impl. New fragment file case — the
    # operator added a file the fragment didn't previously ship. We
    # land it on whatever impl is first registered.
    return next(iter(impls.values()))


def _resolve_fragment_dir_under(
    *,
    forge_repo: Path,
    fragment_dir_str: str,
) -> Path | None:
    """Resolve a fragment's directory relative to a user-supplied forge_repo.

    Mirrors :func:`forge.feature_injector._resolve_fragment_dir`, but
    re-roots paths so tests (and CLI invocations against an alternate
    forge checkout) can target a tmp_path clone of the source tree
    without mutating the real installed package.

    Two layouts are honoured:

    * **Relative paths** (``"<fragment>"``) — built-in fragments under
      ``forge/templates/_fragments/<fragment>``. Resolved by joining
      against ``forge_repo / forge / templates / _fragments``.
    * **Absolute paths** under the live forge package — feature
      fragments registered with ``str(_TEMPLATES / name / lang)``.
      We remap by detecting the substring ``forge/features/`` (or
      ``forge\\features\\``) inside the absolute path and re-rooting
      the matching ``forge/features/...`` tail under ``forge_repo``.
      A pure plugin path (anything else) is honoured verbatim — the
      caller's forge_repo doesn't apply.

    Returns ``None`` when nothing resolves; the caller surfaces this
    as an ``errored`` apply entry rather than crashing.
    """
    path = Path(fragment_dir_str)
    if path.is_absolute():
        # Feature fragments (``forge/features/<area>/...``) live inside
        # the forge package and need re-rooting to the clone so apply-
        # back doesn't mutate the real installed package. Detect the
        # boundary by walking up the absolute path until we hit a
        # parent named ``forge`` whose child named ``features`` exists.
        # If we find one, rebase the tail under ``forge_repo``.
        parts = path.parts
        for i in range(len(parts) - 1, -1, -1):
            if parts[i] == "forge" and i + 1 < len(parts) and parts[i + 1] == "features":
                tail = parts[i:]
                rebased = forge_repo.joinpath(*tail)
                if rebased.is_dir():
                    return rebased
                # If the rebased path doesn't exist on the clone yet
                # (uncommon — the clone mirrors the full tree), fall
                # back to the absolute path so the apply still lands
                # somewhere predictable.
                return rebased
            if parts[i] == "forge" and i + 1 < len(parts) and parts[i + 1] == "templates":
                tail = parts[i:]
                rebased = forge_repo.joinpath(*tail)
                if rebased.is_dir():
                    return rebased
                return rebased
        # Plugin / absolute fragment dir outside the forge package —
        # honour verbatim. The caller's forge_repo doesn't apply.
        return path

    # Built-in fragments under templates/_fragments/. The relative
    # path stored on the impl spec is interpreted against the
    # templates/_fragments/ root.
    candidate = forge_repo / "forge" / "templates" / "_fragments" / fragment_dir_str
    if candidate.is_dir():
        return candidate

    # Fall through: try without the ``forge/`` prefix in case the
    # caller passed the inner ``forge`` package as forge_repo.
    candidate2 = forge_repo / "templates" / "_fragments" / fragment_dir_str
    if candidate2.is_dir():
        return candidate2

    return None


def _find_fragment_source_file(fragment_name: str, *, forge_repo: Path) -> Path | None:
    """Locate the ``fragments.py`` module that registers ``fragment_name``.

    Walks the conventional locations:

    * ``<forge_repo>/forge/features/*/fragments.py`` — built-in
      feature fragments. This is where ~95% of registrations live.
    * Plugin paths: any ``*.py`` directly under ``<forge_repo>`` whose
      contents include the registration pattern. Tests pass a
      synthetic forge_repo containing inline ``fragments.py`` files
      so this catch-all picks them up without a registry plumbing
      pass.

    The match is a literal-string grep for ``name="<fragment_name>"``
    or ``name='<fragment_name>'`` appearing inside a
    ``register_fragment(`` call. A fragment registered via a constant-
    expression name (``Fragment(name=NAME, ...)``) is NOT matched —
    that's the documented limitation, the applier falls back to
    ``deferred`` in callers when this returns ``None``.

    Returns the absolute path to the registering file, or ``None``
    when no match found.
    """
    # Build the candidate haystack. Conventional registrations come
    # from forge/features/*/fragments.py (built-ins). Tests + plugins
    # may also register from any .py under forge_repo; the catch-all
    # glob keeps the discovery uniform.
    candidates: list[Path] = []
    feature_dir = forge_repo / "forge" / "features"
    if feature_dir.is_dir():
        candidates.extend(feature_dir.glob("*/fragments.py"))
    # Plugin / inline registrations. We don't recurse into every
    # subdirectory by default (that would scan the whole project
    # tree); we honour the top-level *.py files of forge_repo, which
    # covers the test scaffold pattern (a tmp_path with an inline
    # fragments.py at the root).
    candidates.extend(forge_repo.glob("*.py"))
    # Also accept fragments.py inside one-level-deep subdirs of
    # forge_repo (catches plugin packages laid out as
    # ``<plugin>/fragments.py`` in tests).
    candidates.extend(forge_repo.glob("*/fragments.py"))

    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _source_registers_fragment(text, fragment_name):
            return path
    return None


def _source_registers_fragment(source: str, fragment_name: str) -> bool:
    """Return True if ``source`` contains a ``register_fragment`` call
    registering ``fragment_name`` (literal-string match)."""
    # Match name="<x>" or name='<x>' anywhere in the source — we
    # narrow further by re-checking the register_fragment boundary
    # inside the rewriters.
    pattern_dq = f'name="{fragment_name}"'
    pattern_sq = f"name='{fragment_name}'"
    return pattern_dq in source or pattern_sq in source


@dataclass(frozen=True)
class _RewriteResult:
    """Outcome of an in-place fragments.py rewrite.

    Attributes:
        status: ``"applied"`` / ``"skipped-unchanged"`` / ``"deferred"``
            / ``"errored"``. Caller maps to the ``ApplyBundleEntry``.
        reason: Free-form note for the operator. Empty when applied.
    """

    status: str
    reason: str = ""


@dataclass(frozen=True)
class _KwargSpan:
    """Result of looking up a kwarg's tuple-expression span.

    ``status`` is ``"ok"`` when the span is valid; otherwise it's the
    ``ApplyBundleEntry`` status the caller should emit and ``reason``
    explains it.
    """

    status: str
    reason: str = ""
    start: int | None = None
    end: int | None = None


def _scan_kwarg_tuple_span(
    source: str,
    *,
    scope_start: int,
    scope_end: int,
    kwarg: str,
) -> _KwargSpan:
    """Find the ``<kwarg>=`` keyword inside ``[scope_start, scope_end)``
    and return the matching parenthesised tuple span."""
    pattern = re.compile(rf"\b{re.escape(kwarg)}\s*=\s*")
    for match in pattern.finditer(source, scope_start, scope_end):
        # We need to be sure this match is at the kwarg-list level
        # of the FragmentImplSpec call, not nested inside another
        # tuple. Check the immediately-preceding non-whitespace char
        # is either ``,`` (a prior kwarg) or ``(`` (the call opener).
        prev_idx = match.start() - 1
        while prev_idx >= scope_start and source[prev_idx] in " \t\n":
            prev_idx -= 1
        if prev_idx < scope_start:
            continue
        if source[prev_idx] not in ",(":
            continue
        eq_end = match.end()
        if eq_end >= scope_end:
            continue
        # Find the opening ``(``. The kwarg value must start with a
        # ``(`` for us to treat it as a literal tuple. Anything else
        # (an identifier, a function call, a list comprehension) we
        # defer.
        # Skip whitespace after ``=``.
        idx = eq_end
        while idx < scope_end and source[idx] in " \t\n":
            idx += 1
        if idx >= scope_end or source[idx] != "(":
            return _KwargSpan(
                status="deferred",
                reason=(f"{kwarg} value is not a literal tuple expression; manual edit required"),
            )
        close = _matching_paren(source, idx)
        if close < 0 or close >= scope_end:
            return _KwargSpan(
                status="errored",
                reason=f"{kwarg} tuple has unbalanced parentheses",
            )
        return _KwargSpan(status="ok", start=idx, end=close + 1)
    return _KwargSpan(
        status="errored",
        reason=f"FragmentImplSpec(...) has no {kwarg}=(...) keyword",
    )


def _find_register_fragment_block(source: str, fragment_name: str) -> tuple[int, int]:
    """Return the ``(open_paren, close_paren)`` span of the
    ``register_fragment(...)`` call that registers ``fragment_name``.

    Walks every ``register_fragment(`` occurrence; for each, finds its
    matching close paren and checks whether the enclosed text mentions
    ``name="<fragment_name>"`` (or single-quoted). Returns the first
    matching span. Returns ``(-1, -1)`` when none match.

    The matching close-paren includes the OUTER ``)`` of
    ``register_fragment(Fragment(name=..., ...))``, so callers can
    use ``[open+1, close)`` as the scope for kwarg lookups inside.
    """
    pattern_dq = f'name="{fragment_name}"'
    pattern_sq = f"name='{fragment_name}'"
    pos = 0
    while True:
        idx = source.find("register_fragment(", pos)
        if idx < 0:
            return -1, -1
        open_paren = source.find("(", idx)
        close_paren = _matching_paren(source, open_paren)
        if close_paren < 0:
            return -1, -1
        block_text = source[open_paren : close_paren + 1]
        if pattern_dq in block_text or pattern_sq in block_text:
            return open_paren, close_paren
        pos = close_paren + 1


def _matching_paren(source: str, open_idx: int) -> int:
    """Return the index of the ``)`` matching the ``(`` at ``open_idx``.

    Respects nested parentheses, brackets, and braces, and skips
    parentheses appearing inside string literals (single, double,
    and triple-quoted). Returns ``-1`` on unbalanced input.
    """
    if open_idx < 0 or open_idx >= len(source) or source[open_idx] != "(":
        return -1
    depth = 0
    i = open_idx
    n = len(source)
    while i < n:
        ch = source[i]
        if ch in ("'", '"'):
            quote, end = _skip_string_literal(source, i)
            if end < 0:
                return -1
            i = end
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return i
        elif ch == "#":
            # Comment to end of line.
            nl = source.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        i += 1
    return -1


def _skip_string_literal(source: str, start: int) -> tuple[str, int]:
    """Advance past a Python string literal starting at ``source[start]``.

    Handles single/double-quoted single-line strings, triple-quoted
    multi-line strings, and ``r``/``b``/``f`` prefix combinations
    via the caller already pointing at the opening quote. Returns
    ``(quote_char, index_after_closing_quote)``. Returns
    ``(quote, -1)`` if the literal is unterminated.
    """
    quote = source[start]
    if start + 2 < len(source) and source[start : start + 3] == quote * 3:
        # Triple-quoted.
        close = source.find(quote * 3, start + 3)
        if close < 0:
            return quote, -1
        return quote, close + 3
    # Single-quoted. Handle backslash escapes.
    i = start + 1
    n = len(source)
    while i < n:
        ch = source[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == quote:
            return quote, i + 1
        if ch == "\n":
            # Single-line literal closed unexpectedly — treat as
            # unterminated.
            return quote, -1
        i += 1
    return quote, -1


def _detect_indent_for_kwarg(source: str, kwarg_open_idx: int) -> str:
    """Return the indentation prefix of the line containing
    ``source[kwarg_open_idx]``.

    Used by the tuple formatter to align continuation lines with the
    original kwarg's column. A multi-line tuple keeps the indent
    convention even after rewrite.
    """
    line_start = source.rfind("\n", 0, kwarg_open_idx) + 1
    indent_chars: list[str] = []
    i = line_start
    while i < kwarg_open_idx and source[i] in " \t":
        indent_chars.append(source[i])
        i += 1
    return "".join(indent_chars)


def _repr_str(s: str) -> str:
    """Render ``s`` as a Python string literal.

    Uses double quotes when the string contains no double quotes, else
    falls back to single quotes — mirrors the convention forge's own
    fragments.py modules use (most strings double-quoted; specs that
    embed quotes single-quoted).
    """
    if '"' not in s:
        return f'"{s}"'
    if "'" not in s:
        return f"'{s}'"
    # Both quote chars appear — fall back to double-quoting with
    # escapes. Rare in practice.
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
