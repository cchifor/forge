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
    from forge.sync.provenance import ProvenanceCollector


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
    # CI workflows: emit one per distinct backend language. The first
    # language keeps the canonical ``ci.yml`` name (back-compat + golden
    # stability for single-backend projects); each additional language gets
    # ``ci-<lang>.yml`` so a multi-backend project ships a workflow per stack
    # instead of only the first backend's.
    workflows_dir = project_root / ".github" / "workflows"
    seen_languages: set[object] = set()
    is_first = True
    for bc in config.backends:
        if bc.language in seen_languages:
            continue
        seen_languages.add(bc.language)
        ci_src = _ci_source_for(bc)
        if ci_src is None:
            continue
        filename = "ci.yml" if is_first else f"ci-{bc.language.value}.yml"
        is_first = False
        _copy_if_absent(ci_src, workflows_dir / filename, collector)


def _ci_source_for(bc: BackendConfig) -> Path | None:
    """Return the CI workflow template for the backend's language, if any."""
    from forge.config import BackendLanguage  # noqa: PLC0415

    mapping = {
        BackendLanguage.PYTHON: COMMON_DIR / "ci_python.yml",
        BackendLanguage.NODE: COMMON_DIR / "ci_node.yml",
        BackendLanguage.RUST: COMMON_DIR / "ci_rust.yml",
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
        # template_name points at the shared "_common" tree under
        # forge/templates/_common/, which isn't a Copier template (no
        # copier.yml, no version field) — it's a flat directory of
        # fallback quality-signal files. template_version is None for
        # the same reason; harvest can still distinguish these from
        # backend-template files by template_name.
        # TODO: revisit when forge gains a formal "asset bundle" concept
        # with its own semver.
        collector.record(
            dst,
            origin="base-template",
            template_name="_common",
            template_version=None,
        )
