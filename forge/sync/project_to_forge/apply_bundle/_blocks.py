"""``kind="block"`` apply handler — rewrite inject.yaml snippets.

Split out from the original ``apply_bundle.py`` god module — see
:mod:`forge.sync.project_to_forge.apply_bundle` for the public surface.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from forge.fragments import FRAGMENT_REGISTRY
from forge.sync.project_to_forge.apply_bundle._dispatch import ApplyBundleEntry
from forge.sync.project_to_forge.apply_bundle._shared import _resolve_fragment_dir_under

if TYPE_CHECKING:
    from forge.extractors.pipeline import CandidatePatch
    from forge.fragments import Fragment, FragmentImplSpec


def _apply_block_candidate(
    cand: CandidatePatch,
    *,
    forge_repo: Path,
    quiet: bool,
) -> ApplyBundleEntry:
    """Apply a ``kind="block"`` candidate to the fragment's inject.yaml.

    Locates the fragment's ``inject.yaml``, finds the entry whose
    ``target`` + ``marker`` match the candidate, and rewrites that
    entry's ``snippet:`` field with :attr:`CandidatePatch.current_body`.

    Match strategy:
      1. The fragment is resolved through :data:`FRAGMENT_REGISTRY`.
      2. Among the fragment's impls, we pick whichever one carries an
         ``inject.yaml`` containing an entry with the candidate's
         ``target`` and ``marker``. This lets one fragment with
         multiple language impls (rare for blocks today, but legal)
         route the back-port to the correct language.
      3. The matching YAML entry's snippet is rewritten in place; the
         file is fully re-serialised via :mod:`yaml.safe_dump`.

    Constraints + trade-offs:
      * ``current_body`` MUST be non-empty for a meaningful apply —
        an empty current body means "the user wiped the block" and
        we can't distinguish that from "an extractor that didn't
        populate the new field". Empty bodies surface as ``errored``.
      * Inline comments mid-list are NOT preserved by safe_dump. The
        file's leading comment block (everything up to the first
        non-comment/blank line) is preserved by reading the head and
        prepending it back. Per-entry comments are lost — this is the
        documented trade-off.
      * The match must be EXACT on (target, marker). A candidate that
        can't find its entry in ANY of the fragment's impls' inject.
        yaml files surfaces as ``errored`` — the harvest record points
        at something the fragment no longer ships, which the operator
        needs to know.
    """
    if not cand.current_body:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=(
                "block candidate has empty current_body; cannot rewrite "
                "inject.yaml snippet without the post-edit body"
            ),
        )
    if not cand.marker:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=(
                "block candidate missing marker field; cannot pin the inject.yaml entry to rewrite"
            ),
        )

    fragment = FRAGMENT_REGISTRY.get(cand.fragment)
    if fragment is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"fragment {cand.fragment!r} not in registry",
        )

    impl, fragment_dir, inject_yaml_path = _resolve_inject_yaml_for_block(
        fragment, cand, forge_repo=forge_repo
    )
    if impl is None or fragment_dir is None or inject_yaml_path is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=(
                f"no inject.yaml entry matches target={cand.rel_path!r} "
                f"marker={cand.marker!r} on fragment {cand.fragment!r}; "
                f"fragment may no longer ship this block"
            ),
        )

    try:
        rewrote = _rewrite_inject_yaml_snippet(
            inject_yaml_path=inject_yaml_path,
            target=cand.rel_path,
            marker=cand.marker,
            new_snippet=cand.current_body,
        )
    except OSError as e:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            target=str(inject_yaml_path),
            error=f"write failed: {e}",
        )
    if not rewrote:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            target=str(inject_yaml_path),
            error=(
                f"matching entry not found in {inject_yaml_path} for "
                f"target={cand.rel_path!r} marker={cand.marker!r}"
            ),
        )

    if not quiet:
        print(
            f"  [apply-bundle] {cand.fragment}/{cand.rel_path}#{cand.marker} → {inject_yaml_path}"
        )
    return ApplyBundleEntry(
        fragment=cand.fragment,
        kind=cand.kind,
        rel_path=cand.rel_path,
        status="applied",
        target=str(inject_yaml_path),
    )


def _resolve_inject_yaml_for_block(
    fragment: Fragment,
    cand: CandidatePatch,
    *,
    forge_repo: Path,
) -> tuple[FragmentImplSpec | None, Path | None, Path | None]:
    """Find the impl + inject.yaml path whose entry matches the candidate.

    Walks the fragment's impls in iteration order; for each, resolves
    the fragment_dir under ``forge_repo`` and parses any ``inject.yaml``
    present. Returns the first ``(impl, fragment_dir, inject_yaml)``
    triple whose YAML contains an entry with the candidate's
    ``(target, marker)``. Returns ``(None, None, None)`` when no impl
    matches.

    The lookup is read-only — we don't mutate the YAML here. The
    rewrite happens in :func:`_rewrite_inject_yaml_snippet` once the
    caller has confirmed which file to edit.
    """
    impls = fragment.implementations
    if not impls:
        return None, None, None

    for impl in impls.values():
        fragment_dir = _resolve_fragment_dir_under(
            forge_repo=forge_repo,
            fragment_dir_str=impl.fragment_dir,
        )
        if fragment_dir is None or not fragment_dir.is_dir():
            continue
        inject_yaml = fragment_dir / "inject.yaml"
        if not inject_yaml.is_file():
            continue
        try:
            doc = yaml.safe_load(inject_yaml.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(doc, list):
            continue
        for entry in doc:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("target", "")) != cand.rel_path:
                continue
            if str(entry.get("marker", "")) != cand.marker:
                continue
            return impl, fragment_dir, inject_yaml
    return None, None, None


def _rewrite_inject_yaml_snippet(
    *,
    inject_yaml_path: Path,
    target: str,
    marker: str,
    new_snippet: str,
) -> bool:
    """Rewrite the matching entry's ``snippet:`` field in ``inject_yaml_path``.

    Returns ``True`` when an entry was rewritten + the file was
    persisted; ``False`` when no entry matched (caller surfaces as
    ``errored``).

    Formatting contract (the trade-off documented at module level):
      * The leading comment block of the file (every consecutive line
        starting with ``#`` or empty, from the start of the file) is
        preserved verbatim by manual prepend.
      * Everything else is re-serialised via :mod:`yaml.safe_dump`
        with block-style output and ``allow_unicode=True``. Per-entry
        mid-list comments are lost. Block-literal snippets (``|`` /
        ``|-``) collapse to whatever safe_dump deems best — typically
        a ``|`` literal when the snippet contains newlines, or a
        plain string for single-line snippets.
      * Trailing newline is appended to match the original file's
        convention (every inject.yaml in the tree ends with one).
    """
    raw = inject_yaml_path.read_text(encoding="utf-8")
    doc = yaml.safe_load(raw)
    if not isinstance(doc, list):
        return False

    found = False
    for entry in doc:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("target", "")) != target:
            continue
        if str(entry.get("marker", "")) != marker:
            continue
        entry["snippet"] = new_snippet
        found = True
        break

    if not found:
        return False

    header = _extract_leading_comments(raw)
    body = yaml.safe_dump(
        doc,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=1_000_000,  # keep long snippets on one line when single-line
    )
    out = header + body
    if not out.endswith("\n"):
        out += "\n"
    inject_yaml_path.write_text(out, encoding="utf-8")
    return True


def _extract_leading_comments(raw: str) -> str:
    """Return the contiguous block of ``#``-comments + blanks at file start.

    Stops at the first line that's neither a comment nor blank. The
    returned string includes the trailing newline of the last comment
    line so the YAML body can be appended without joining onto a
    comment line.
    """
    lines = raw.splitlines(keepends=True)
    head: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            head.append(line)
            continue
        break
    return "".join(head)
