"""Copy shared quality-signal files into every generated project.

Phase 4.4 of the 1.0 roadmap. Ensures every ``forge new`` project ships
with ``.editorconfig``, ``.gitignore``, ``.pre-commit-config.yaml``, and a
language-appropriate CI workflow. Existing per-template files take
precedence — this pass only fills in paths that haven't been provided by
the backend or frontend template.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.config import BackendConfig, ProjectConfig
    from forge.provenance import ProvenanceCollector


COMMON_DIR = Path(__file__).resolve().parent / "templates" / "_common"


def apply_common_files(
    config: ProjectConfig,
    project_root: Path,
    collector: ProvenanceCollector | None = None,
) -> None:
    """Drop shared quality-signal files at the project root if absent.

    Never overwrites an existing file — respects templates that already
    ship their own .editorconfig or .gitignore.
    """
    _copy_if_absent(COMMON_DIR / "editorconfig", project_root / ".editorconfig", collector)
    _copy_if_absent(COMMON_DIR / "gitignore", project_root / ".gitignore", collector)
    _copy_if_absent(
        COMMON_DIR / "pre-commit-config.yaml",
        project_root / ".pre-commit-config.yaml",
        collector,
    )
    # CI workflow: pick the backend-language-appropriate template for the
    # first backend. Projects with multiple backends get the first one's
    # workflow; mixed-stack CI is a follow-up.
    if config.backends:
        bc = config.backends[0]
        ci_src = _ci_source_for(bc)
        if ci_src is not None:
            ci_dst = project_root / ".github" / "workflows" / "ci.yml"
            _copy_if_absent(ci_src, ci_dst, collector)


def _ci_source_for(bc: BackendConfig) -> Path | None:
    """Return the CI workflow template for the backend's language, if any."""
    from forge.config import BackendLanguage  # noqa: PLC0415

    mapping = {
        BackendLanguage.PYTHON: COMMON_DIR / "ci_python.yml",
    }
    return mapping.get(bc.language)


def _copy_if_absent(src: Path, dst: Path, collector: ProvenanceCollector | None) -> None:
    if dst.exists():
        return
    if not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if collector is not None:
        collector.record(dst, origin="base-template")
