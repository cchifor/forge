"""On-disk persistence layer for the harvest bundle (Phase 4).

A harvest bundle is the maintainer-facing output of ``forge --harvest``:
a structured directory containing the manifest JSON, per-fragment patch
sets, and a placeholder README pointing at the round-trip workflow doc.

Layout::

    <out_dir>/
      manifest.json
      README.md
      patches/
        <fragment-name>/
          meta.json
          0001-block-<safe_key>.patch
          0002-files-<safe_key>.patch

The patch files are unified diffs the maintainer can ``git apply`` (or
review by eye) against the corresponding fragment source. The
``meta.json`` per fragment records the fragment's name + version when
known and the extractor kinds that produced patches.

A Phase 4b PR (``--accept-harvested``) will read this layout back and
apply the candidates to the fragment tree; the format here is the
serialised contract for that workflow.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.extractors.pipeline import CandidatePatch
    from forge.sync.project_to_forge.harvester import HarvestBundle


# Filename-safe characters in a manifest key. Everything else gets
# replaced with ``_`` for the per-candidate patch filename.
_SAFE_KEY_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def write_bundle(bundle: HarvestBundle, out_dir: Path) -> None:
    """Serialise a :class:`HarvestBundle` to ``out_dir`` on disk.

    Creates ``out_dir`` (and parents) if missing. Idempotent in the
    sense that a second call with the same bundle id overwrites the
    same paths — but bundle ids carry a timestamp prefix, so a second
    harvest of the same project lands in a different out_dir by
    default.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest_json(bundle, out_dir / "manifest.json")
    _write_readme(out_dir / "README.md")
    patches_dir = out_dir / "patches"
    patches_dir.mkdir(exist_ok=True)
    _write_patches(bundle.candidates, patches_dir)


def _write_manifest_json(bundle: HarvestBundle, path: Path) -> None:
    """Emit the bundle's top-level ``manifest.json``.

    The shape is the same as :meth:`HarvestBundle.to_dict` — keeping
    one canonical serialisation means the streaming-stdout JSON mode
    and the bundle-on-disk mode use the same envelope.
    """
    path.write_text(json.dumps(bundle.to_dict(), indent=2) + "\n", encoding="utf-8")


def _write_readme(path: Path) -> None:
    """Emit the bundle's placeholder README.

    The full round-trip workflow doc lives in ``docs/round-trip.md``
    (Phase 4b follow-up); the bundle README links there so a
    maintainer who picks up a bundle has a starting point.
    """
    body = (
        "# forge harvest bundle\n"
        "\n"
        "This directory contains candidate patches extracted from a generated\n"
        "project against the fragment templates that emitted them. See\n"
        "`manifest.json` for the per-candidate metadata and `patches/` for\n"
        "the unified diffs grouped by fragment.\n"
        "\n"
        "Full workflow doc: `docs/round-trip.md` (Phase 4b — TODO).\n"
    )
    path.write_text(body, encoding="utf-8")


def _write_patches(candidates: list[CandidatePatch], patches_dir: Path) -> None:
    """Materialise per-fragment patch directories.

    Each fragment gets a subdirectory under ``patches/`` with a
    ``meta.json`` and one ``NNNN-<kind>-<safe_key>.patch`` file per
    candidate. The four-digit prefix preserves emission order from
    the pipeline so a maintainer can apply patches in the same order
    the extractor produced them.

    RFC-006 ``cross-lang-suggest`` candidates land alongside the real
    patches but use a different filename pattern
    (``0099-cross-lang-suggest-<lang>.txt`` — no ``.patch`` suffix
    because they're textual hints, not patches) and a different body
    (the candidate's ``diff`` hint + ``rationale``, no header).
    Suggestions emit AFTER the real patches so the numeric prefix
    sorts them last in directory listings.

    Item-6 ``option-promote`` side-cars: when a ``block`` candidate
    carries a non-empty ``option_promotion`` field
    (see :mod:`forge.codegen.literal_finder`), an extra
    ``NNNN-option-promote-<safe_key>.patch`` file is written
    alongside the main candidate using the same ``NNNN`` index. The
    file is a textual hint — a proposed :class:`Option` declaration
    plus an ``inject.yaml`` diff swapping the literal for
    ``{{ options["..."] }}`` — so the maintainer can review and
    convert the hardcoded value to a typed option.
    """
    grouped: dict[str, list[CandidatePatch]] = defaultdict(list)
    for cand in candidates:
        grouped[cand.fragment].append(cand)

    for fragment_name, fragment_candidates in sorted(grouped.items()):
        frag_dir = patches_dir / _safe_dirname(fragment_name)
        frag_dir.mkdir(parents=True, exist_ok=True)
        _write_fragment_meta(frag_dir / "meta.json", fragment_name, fragment_candidates)
        # Split into real patches + suggestions so each gets its own
        # filename pattern + body shape.
        real = [c for c in fragment_candidates if c.kind != "cross-lang-suggest"]
        suggestions = [c for c in fragment_candidates if c.kind == "cross-lang-suggest"]
        for index, cand in enumerate(real, start=1):
            patch_name = _patch_filename(index, cand)
            (frag_dir / patch_name).write_text(_patch_body(cand), encoding="utf-8")
            # Side-car option-promote patch — same index, different
            # filename pattern. Only emitted when the candidate carries
            # a non-empty ``option_promotion`` payload (block kinds with
            # detected literal swaps).
            if cand.option_promotion:
                promote_name = _option_promote_filename(index, cand)
                (frag_dir / promote_name).write_text(_option_promote_body(cand), encoding="utf-8")
        # Number suggestions from 0099 onward so they sort after the
        # real patches but still carry a stable order. Disambiguate by
        # backend (e.g. ``0099-cross-lang-suggest-node.txt``,
        # ``0100-cross-lang-suggest-rust.txt``).
        for index, cand in enumerate(suggestions, start=99):
            suggest_name = _suggest_filename(index, cand)
            (frag_dir / suggest_name).write_text(_suggest_body(cand), encoding="utf-8")


def _write_fragment_meta(
    path: Path,
    fragment_name: str,
    candidates: list[CandidatePatch],
) -> None:
    """Write the per-fragment ``meta.json`` summary."""
    kinds = sorted({c.kind for c in candidates})
    risks = sorted({c.risk for c in candidates})
    payload = {
        "fragment_name": fragment_name,
        "extractor_kinds": kinds,
        "risks_present": risks,
        "candidate_count": len(candidates),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _patch_filename(index: int, cand: CandidatePatch) -> str:
    """Build a deterministic ``NNNN-<kind>-<safe_key>.patch`` filename."""
    safe_key = _safe_filename(cand.rel_path)
    return f"{index:04d}-{cand.kind}-{safe_key}.patch"


def _suggest_filename(index: int, cand: CandidatePatch) -> str:
    """Build a ``NNNN-cross-lang-suggest-<lang>.txt`` filename.

    The ``.txt`` suffix distinguishes suggestions from real patches:
    ``.patch`` files imply a ``git apply``-able diff; suggestions are
    textual hints the maintainer reads and acts on manually.
    """
    lang = _safe_filename(cand.backend) or "unknown"
    return f"{index:04d}-cross-lang-suggest-{lang}.txt"


def _suggest_body(cand: CandidatePatch) -> str:
    """Render a cross-lang-suggest file's body.

    Carries the candidate's diff text (the human-readable hint emitted
    by the harvester's parity pass) followed by the rationale on a
    separate line. No header — suggestions are short enough to keep
    legibility without one.
    """
    lines = [cand.diff or "(no hint provided)"]
    if cand.rationale:
        lines.append("")
        lines.append(cand.rationale)
    return "\n".join(lines).rstrip("\n") + "\n"


def _patch_body(cand: CandidatePatch) -> str:
    """Render the patch file content.

    A short comment header lets a human reader see the risk +
    rationale before the diff itself. The body is the candidate's
    ``diff`` verbatim — empty diffs (sentinel-corrupt conflicts) get
    a placeholder note.
    """
    header_lines = [
        f"# forge harvest candidate — risk={cand.risk}",
        f"# fragment={cand.fragment} kind={cand.kind}",
        f"# target={cand.target_path}",
        f"# baseline_sha={cand.baseline_sha} current_sha={cand.current_sha}",
    ]
    if cand.rationale:
        header_lines.append(f"# rationale: {cand.rationale}")
    header = "\n".join(header_lines) + "\n\n"
    body = cand.diff if cand.diff else "# (no diff available — see rationale)\n"
    return header + body


def _option_promote_filename(index: int, cand: CandidatePatch) -> str:
    """Build a ``NNNN-option-promote-<safe_key>.patch`` filename.

    Uses the same ``NNNN`` index as the corresponding main patch so the
    pair sorts next to each other in a directory listing. The
    ``.patch`` suffix is retained for consistency with ``git apply``
    expectations, even though the body is a structured textual hint
    rather than a unified diff — the comment header marks it clearly so
    a reviewer doesn't try to ``git apply`` it directly.
    """
    safe_key = _safe_filename(cand.rel_path)
    return f"{index:04d}-option-promote-{safe_key}.patch"


def _option_promote_body(cand: CandidatePatch) -> str:
    """Render an option-promote side-car patch body.

    The body is a structured comment-block + a proposed
    :class:`forge.options.Option` declaration + an ``inject.yaml`` diff
    swapping the literal for ``{{ options["<key>"] }}``. Maintainers
    read this, pick the final key name, and copy the snippet into the
    fragment's options module — the harvester deliberately doesn't
    apply it automatically (the key namespace + summary text are
    judgement calls the human owns).

    When the candidate carries multiple :class:`LiteralEdit` records,
    each gets its own ``Option(...)`` + ``inject.yaml`` diff block in
    the order the finder emitted them.
    """
    header_lines = [
        "# Option-promotion suggestion — needs-review",
        f"# Fragment: {cand.fragment} ({cand.backend} impl)",
        f"# Target file: {cand.target_path}",
        f"# Marker: {cand.marker}",
        "#",
        "# The user changed one or more literal values in this block.",
        "# Promoting each to an Option lets the same setting flow",
        "# through to every sibling-language impl of the fragment.",
        "",
    ]

    section_lines: list[str] = []
    for n, edit in enumerate(cand.option_promotion, start=1):
        proposed_key = _propose_option_key(cand, edit, n)
        option_type = _option_type_token(edit.kind)
        default_repr = _default_repr(edit)
        section_lines.extend(
            [
                f"# ----- Literal #{n}: {edit.kind} swap "
                f"({edit.old_value} → {edit.new_value}) -----",
                f"# Detected at line {edit.line}, column {edit.col} of the block body.",
                "",
                "# Proposed Option declaration (add to forge/<feature>/options.py):",
                "",
                "Option(",
                f'    path="{proposed_key}",',
                f"    type=OptionType.{option_type},",
                f"    default={default_repr},",
                f'    summary="TODO: one-sentence summary of {edit.kind} option.",',
                '    description="TODO: longer description of why this option exists.",',
                "    category=FeatureCategory.TODO,",
                ")",
                "",
                "# inject.yaml diff for ALL parallel impls:",
                "",
                f"-    {edit.old_value}",
                f'+    {{{{ options["{proposed_key}"] }}}}',
                "",
            ]
        )
    return "\n".join(header_lines + section_lines).rstrip("\n") + "\n"


def _option_type_token(kind: str) -> str:
    """Map a :class:`LiteralKind` to the canonical ``OptionType`` member."""
    return {
        "int": "INT",
        "float": "INT",  # forge currently models numeric options as INT.
        "str": "STR",
        "bool": "BOOL",
    }.get(kind, "STR")


def _default_repr(edit: object) -> str:
    """Render the suggested Option's ``default=`` value as Python source.

    For ``bool`` literals the libcst-reported value is ``"True"`` /
    ``"False"`` — already valid Python. For ``str`` literals the value
    carries its own quoting (libcst preserves the original delimiter).
    Numeric literals are emitted verbatim.
    """
    kind = getattr(edit, "kind", "str")
    value = getattr(edit, "new_value", "")
    if kind == "str":
        # Already self-quoted by libcst (e.g. ``'"world"'``).
        return value
    return value


def _propose_option_key(cand: CandidatePatch, edit: object, n: int) -> str:
    """Suggest a dotted option key for the promotion patch.

    The proposed key is ``<feature_key>.<edit_slug>`` where ``edit_slug``
    derives from the literal's position and kind — e.g.
    ``middleware_cors.literal_3``. The numeric suffix disambiguates
    multiple literals on the same block; the human reviewer will pick
    the final name.
    """
    feature = _option_key_slug(cand.feature_key or cand.fragment or "fragment")
    kind = getattr(edit, "kind", "literal")
    return f"{feature}.literal_{kind}_{n}"


def _option_key_slug(text: str) -> str:
    """Lower-case identifier slug suitable for the leading path segment."""
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", text).strip("_").lower()
    return cleaned or "fragment"


def _safe_filename(key: str) -> str:
    """Sanitize a manifest key (``rel::feature:marker``) into a filename.

    Replaces ``/``, ``:``, ``::``, spaces, and other non-portable
    characters with ``_``. Idempotent — strings already filename-safe
    pass through unchanged.
    """
    return _SAFE_KEY_PATTERN.sub("_", key) or "untitled"


def _safe_dirname(name: str) -> str:
    """Same-substitution for a fragment-name directory."""
    return _SAFE_KEY_PATTERN.sub("_", name) or "fragment"
