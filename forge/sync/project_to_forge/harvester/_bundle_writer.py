"""Bundle data class + serialization helpers.

Split out from the original ``harvester.py`` god module — see
:mod:`forge.sync.project_to_forge.harvester` for the public surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forge.extractors.pipeline import CandidatePatch


@dataclass(frozen=True)
class HarvestBundle:
    """One harvest run's output — what to write to disk.

    Attributes:
        bundle_id: Unique identifier of the form
            ``harvest-<UTC-timestamp>-<8-char-hash>``. Stable enough to
            disambiguate concurrent harvests of the same project root.
        project_root: Absolute path to the project the candidates were
            extracted from. Recorded so reviewers can trace back to the
            source tree without re-running the harvest.
        forge_version: ``forge``'s own package version at harvest time.
            Lets a maintainer reject candidates from an older forge if
            the fragment registry has moved.
        candidates: Every :class:`CandidatePatch` the extractor pipeline
            emitted, post-scope-filter and post-include-filter.
    """

    bundle_id: str
    project_root: Path
    forge_version: str
    candidates: list[CandidatePatch]

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly view for ``forge --harvest --harvest-out=-``.

        ``current_body`` / ``feature_key`` / ``marker`` are only emitted
        when populated — keeping the JSON shape minimal for the common
        ``files`` / ``deps`` / ``env`` cases that don't carry them. The
        apply-back path reads these fields directly off the in-memory
        bundle, so on-disk serialisation is for review/diagnostics only.
        """
        out: list[dict[str, Any]] = []
        for c in self.candidates:
            row: dict[str, Any] = {
                "fragment": c.fragment,
                "backend": c.backend,
                "kind": c.kind,
                "rel_path": c.rel_path,
                "target_path": c.target_path,
                "diff": c.diff,
                "baseline_sha": c.baseline_sha,
                "current_sha": c.current_sha,
                "risk": c.risk,
                "rationale": c.rationale,
            }
            if c.current_body:
                row["current_body"] = c.current_body
            if c.feature_key:
                row["feature_key"] = c.feature_key
            if c.marker:
                row["marker"] = c.marker
            out.append(row)
        return {
            "bundle_id": self.bundle_id,
            "project_root": str(self.project_root),
            "forge_version": self.forge_version,
            "candidates": out,
        }

    def write(self, out_dir: Path) -> None:
        """Write the bundle to ``out_dir`` per the round-trip spec.

        Layout::

            <out_dir>/
              manifest.json
              README.md
              patches/
                <fragment-name>/
                  meta.json
                  0001-block-<safe_key>.patch
                  0002-files-<safe_key>.patch
                  ...

        ``manifest.json`` carries the full candidate list (same shape
        as :meth:`to_dict`). Each per-fragment ``meta.json`` records
        the fragment name + version (when known) and the extractor
        kinds that produced patches. ``README.md`` is a placeholder
        that links to ``docs/round-trip.md`` (full workflow doc is a
        Phase 4b follow-up).
        """
        # Delayed import — keeps the orchestrator module light when
        # callers only use it for the in-memory bundle (e.g. tests).
        from forge.sync.project_to_forge.bundle import write_bundle  # noqa: PLC0415

        write_bundle(self, out_dir)


# Reserved placeholder; ``field`` is imported above for downstream call sites
# that may extend HarvestBundle. Quiets unused-import lints.
_ = field
