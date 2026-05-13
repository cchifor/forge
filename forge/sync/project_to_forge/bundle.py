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
    """
    grouped: dict[str, list[CandidatePatch]] = defaultdict(list)
    for cand in candidates:
        grouped[cand.fragment].append(cand)

    for fragment_name, fragment_candidates in sorted(grouped.items()):
        frag_dir = patches_dir / _safe_dirname(fragment_name)
        frag_dir.mkdir(parents=True, exist_ok=True)
        _write_fragment_meta(frag_dir / "meta.json", fragment_name, fragment_candidates)
        for index, cand in enumerate(fragment_candidates, start=1):
            patch_name = _patch_filename(index, cand)
            (frag_dir / patch_name).write_text(_patch_body(cand), encoding="utf-8")


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
