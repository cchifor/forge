"""``kind="env"`` apply handler — rewrite FragmentImplSpec.env_vars tuples.

Split out from the original ``apply_bundle.py`` god module — see
:mod:`forge.sync.project_to_forge.apply_bundle` for the public surface.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import TYPE_CHECKING

from forge.fragments import FRAGMENT_REGISTRY
from forge.sync.project_to_forge.apply_bundle._dispatch import ApplyBundleEntry
from forge.sync.project_to_forge.apply_bundle._shared import (
    _detect_indent_for_kwarg,
    _find_fragment_source_file,
    _find_register_fragment_block,
    _KwargSpan,
    _matching_paren,
    _repr_str,
    _RewriteResult,
    _scan_kwarg_tuple_span,
)

if TYPE_CHECKING:
    from forge.extractors.pipeline import CandidatePatch


def _apply_env_candidate(
    cand: CandidatePatch,
    *,
    forge_repo: Path,
    quiet: bool,
) -> ApplyBundleEntry:
    """Apply a ``kind="env"`` candidate to fragments.py.

    Mirrors :func:`_apply_deps_candidate` but operates on the
    ``env_vars=((...),)`` tuple-of-tuples. Unlike deps the language
    is not inferred from ``rel_path`` (env vars are always in
    ``.env.example`` regardless of backend); instead the applier
    rewrites every impl that declares the key. If no impl declares
    the key (the ``added`` action), the applier picks the first
    language the fragment registers — env vars are conventionally
    shared across all languages, so this matches the convention.
    """
    fragment = FRAGMENT_REGISTRY.get(cand.fragment)
    if fragment is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"fragment {cand.fragment!r} not in registry",
        )

    try:
        payload = json.loads(cand.diff)
    except (ValueError, json.JSONDecodeError) as e:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"env candidate diff is not valid JSON: {e}",
        )
    if not isinstance(payload, dict):
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error="env candidate diff payload must be a JSON object",
        )

    action = payload.get("action")
    key = payload.get("key")
    fragment_value = payload.get("fragment_value")
    project_value = payload.get("project_value")

    if action not in ("added", "removed", "modified"):
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"env candidate action {action!r} not in {{added, removed, modified}}",
        )
    if not isinstance(key, str) or not key:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error="env candidate missing env key",
        )

    source_path = _find_fragment_source_file(cand.fragment, forge_repo=forge_repo)
    if source_path is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=(
                f"could not locate fragments.py registering fragment {cand.fragment!r} "
                f"under forge_repo={forge_repo}"
            ),
        )

    try:
        result = _rewrite_fragment_env_vars(
            source_path=source_path,
            fragment_name=cand.fragment,
            action=action,
            key=key,
            fragment_value=fragment_value,
            project_value=project_value,
        )
    except OSError as e:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            target=str(source_path),
            error=f"write failed: {e}",
        )

    if not quiet and result.status == "applied":
        print(f"  [apply-bundle] env {cand.fragment}/{key} → {source_path}")

    return ApplyBundleEntry(
        fragment=cand.fragment,
        kind=cand.kind,
        rel_path=cand.rel_path,
        status=result.status,
        target=str(source_path),
        error=result.reason,
    )


def _rewrite_fragment_env_vars(
    *,
    source_path: Path,
    fragment_name: str,
    action: str,
    key: str,
    fragment_value: str | None,
    project_value: str | None,
) -> _RewriteResult:
    """Rewrite the ``env_vars=((...),)`` tuple-of-tuples for ``fragment_name``.

    Env vars are typically the same across the per-language impls of
    a fragment, so this rewrites EVERY language impl that ships an
    ``env_vars=(...)`` tuple. The result is ``applied`` when at least
    one impl was rewritten; ``skipped-unchanged`` when every impl
    already carries the post-state; ``deferred`` when at least one
    impl's expression is non-literal; ``errored`` for action-specific
    payload issues.

    The tuple-of-tuples shape is ``((KEY, VALUE), (KEY, VALUE), ...)``.
    Single-element shape is ``((KEY, VALUE),)`` (trailing comma for the
    outer tuple). Empty shape is ``()``.
    """
    source = source_path.read_text(encoding="utf-8")

    # Find EVERY env_vars span inside the matching register_fragment
    # block. Each one corresponds to one FragmentImplSpec(...) inside
    # the implementations={} dict. We rewrite all of them so the
    # fragment's per-language impls stay in sync.
    spans, non_literal = _locate_all_env_vars_spans(source, fragment_name=fragment_name)
    if non_literal is not None:
        # At least one impl carries a non-literal env_vars expression.
        # We defer the whole apply — partial mutation would leave the
        # fragment's per-language impls inconsistent, and the
        # documented contract is "fall back to manual edit when the
        # tuple isn't a Python literal".
        return _RewriteResult(
            status=non_literal.status,
            reason=non_literal.reason,
        )
    if not spans:
        return _RewriteResult(
            status="errored",
            reason=(
                f"no FragmentImplSpec with an env_vars=(...) tuple found for "
                f"fragment {fragment_name!r}; fragment may not declare env vars"
            ),
        )

    # First pass — parse every span; bail to deferred on the first
    # non-literal so we don't mutate any file we'd later refuse to
    # finish.
    parsed: list[tuple[int, int, list[tuple[str, str]]]] = []
    for start, end in spans:
        raw = source[start:end]
        try:
            current = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            return _RewriteResult(
                status="deferred",
                reason=(
                    f"env_vars expression for fragment {fragment_name!r} "
                    f"is not a literal tuple; manual edit required"
                ),
            )
        if not isinstance(current, tuple):
            return _RewriteResult(
                status="deferred",
                reason=(
                    f"env_vars expression for fragment {fragment_name!r} "
                    f"is not a tuple; manual edit required"
                ),
            )
        pairs: list[tuple[str, str]] = []
        for item in current:
            if not (isinstance(item, tuple) and len(item) == 2):
                return _RewriteResult(
                    status="deferred",
                    reason=(
                        f"env_vars contains a non-2-tuple item for fragment "
                        f"{fragment_name!r}; manual edit required"
                    ),
                )
            pairs.append((str(item[0]), str(item[1])))
        parsed.append((start, end, pairs))

    # Mutate every span. ``unchanged_count`` lets us emit
    # ``skipped-unchanged`` when every impl already carries the
    # post-state.
    mutated_spans: list[tuple[int, int, list[tuple[str, str]]]] = []
    unchanged_count = 0
    for start, end, pairs in parsed:
        existing_keys = {k for k, _ in pairs}
        if action == "added":
            if project_value is None:
                return _RewriteResult(
                    status="errored",
                    reason="env 'added' candidate missing project_value",
                )
            if key in existing_keys and (key, project_value) in pairs:
                unchanged_count += 1
                mutated_spans.append((start, end, pairs))
                continue
            if key in existing_keys:
                # The key already exists but with a different value
                # — treat as modified semantically. Replace.
                pairs = [(k, project_value if k == key else v) for k, v in pairs]
            else:
                pairs = [*pairs, (key, project_value)]
        elif action == "removed":
            if fragment_value is None:
                return _RewriteResult(
                    status="errored",
                    reason="env 'removed' candidate missing fragment_value",
                )
            if (key, fragment_value) not in pairs and key not in existing_keys:
                unchanged_count += 1
                mutated_spans.append((start, end, pairs))
                continue
            pairs = [(k, v) for k, v in pairs if k != key]
        else:  # action == "modified"
            if fragment_value is None or project_value is None:
                return _RewriteResult(
                    status="errored",
                    reason="env 'modified' candidate missing fragment_value or project_value",
                )
            if (key, project_value) in pairs and (key, fragment_value) not in pairs:
                unchanged_count += 1
                mutated_spans.append((start, end, pairs))
                continue
            if key not in existing_keys:
                return _RewriteResult(
                    status="errored",
                    reason=(
                        f"env key {key!r} not found in current tuple for fragment "
                        f"{fragment_name!r}; current: {pairs!r}"
                    ),
                )
            pairs = [(k, project_value if k == key else v) for k, v in pairs]
        mutated_spans.append((start, end, pairs))

    if unchanged_count == len(parsed):
        return _RewriteResult(
            status="skipped-unchanged",
            reason=f"env_vars for {key!r} already at expected state",
        )

    # Apply mutations in reverse order so byte offsets stay valid as
    # we splice each replacement in.
    new_source = source
    for start, end, pairs in reversed(mutated_spans):
        new_text = _format_env_vars_tuple(
            pairs,
            leading_indent=_detect_indent_for_kwarg(source, start),
        )
        new_source = new_source[:start] + new_text + new_source[end:]
    source_path.write_text(new_source, encoding="utf-8")
    return _RewriteResult(status="applied")


def _locate_all_env_vars_spans(
    source: str,
    *,
    fragment_name: str,
) -> tuple[list[tuple[int, int]], _KwargSpan | None]:
    """Return every ``env_vars=(...)`` tuple span inside the fragment's
    register_fragment block, one per ``FragmentImplSpec(...)``.

    The order mirrors the source-code order so the rewriter can
    splice in reverse and keep byte offsets stable.

    Returns ``(spans, non_ok_span)``:

    * ``spans`` — list of ``(start, end)`` byte spans for every
      ``FragmentImplSpec`` that has a LITERAL ``env_vars=(...)``
      tuple. Empty when none of the impls declare env_vars.
    * ``non_ok_span`` — the first :class:`_KwargSpan` (status !=
      ``"ok"``) encountered. ``None`` if every impl that declared
      env_vars was a literal tuple. Caller surfaces this to the
      operator so a fragment with a non-literal env_vars expression
      lands as ``deferred`` rather than silently skipping the impl.
    """
    reg_start, reg_end = _find_register_fragment_block(source, fragment_name)
    if reg_start < 0:
        return [], None
    spans: list[tuple[int, int]] = []
    first_non_ok: _KwargSpan | None = None
    # Walk every FragmentImplSpec( opening inside the block.
    cursor = reg_start
    while True:
        open_idx = source.find("FragmentImplSpec(", cursor, reg_end)
        if open_idx < 0:
            break
        paren_open = source.find("(", open_idx, reg_end)
        paren_close = _matching_paren(source, paren_open)
        if paren_close < 0:
            break
        span = _scan_kwarg_tuple_span(
            source,
            scope_start=paren_open + 1,
            scope_end=paren_close,
            kwarg="env_vars",
        )
        if span.status == "ok" and span.start is not None and span.end is not None:
            spans.append((span.start, span.end))
        elif span.status == "deferred" and first_non_ok is None:
            # The kwarg exists but isn't a literal tuple — record so
            # the caller can surface it. We DON'T treat the
            # ``errored`` shape ("FragmentImplSpec has no env_vars
            # keyword") as a non-ok span: a fragment can omit
            # env_vars entirely on a per-language impl, which is
            # legitimate and shouldn't poison the others.
            first_non_ok = span
        cursor = paren_close + 1
    return spans, first_non_ok


def _format_env_vars_tuple(
    pairs: list[tuple[str, str]],
    *,
    leading_indent: str,
) -> str:
    """Format ``((KEY, VALUE), ...)`` for the env_vars kwarg.

    Single-element tuple keeps the trailing comma on the OUTER tuple
    (``((KEY, VAL),)``) to match the source convention. Empty tuple
    is ``()``. Multi-element wraps onto multiple lines.
    """
    if not pairs:
        return "()"
    if len(pairs) == 1:
        k, v = pairs[0]
        return f"(({_repr_str(k)}, {_repr_str(v)}),)"
    body_indent = leading_indent + "    "
    lines = ["("]
    for k, v in pairs:
        lines.append(f"{body_indent}({_repr_str(k)}, {_repr_str(v)}),")
    lines.append(f"{leading_indent})")
    return "\n".join(lines)
