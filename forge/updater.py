"""`forge --update` — re-apply options to an existing forge-generated project.

Reads the ``[forge.options]`` stamp from ``forge.toml``, runs the current
resolver against it, re-applies every fragment to each discovered
backend, then re-stamps ``forge.toml`` with the current forge version
and the fully-defaulted option map. Injections are idempotent (B2.3
sentinels), so running this repeatedly is a no-op when nothing changed
and a clean in-place update when a fragment snippet was modified or a
new Option was added.

Provenance classification (1.0.0a1+):
  Before re-applying, ``classify_project_state`` compares each recorded
  file's SHA to the on-disk content and returns a per-path state:
    * ``unchanged`` — safe to re-emit
    * ``user-modified`` — preserve; skip fragment files, warn on injection targets
    * ``missing`` — user deleted; re-emit

The classification is exposed in the summary dict and used to guide
``skip_existing_files`` decisions. Full three-way merge lands in Phase 2.2.

Out of scope (still):
  - Template-level Copier updates (base template changes). Users who want
    those can ``cd <backend>/`` and run ``copier update`` directly —
    ``.copier-answers.yml`` is the input.
  - Deleting files from Options that were turned off. Needs the provenance
    manifest follow-up — partial in this alpha; full in 1.0.0a3.
"""

from __future__ import annotations

import logging
from importlib import metadata
from pathlib import Path
from typing import Any

from forge.capability_resolver import resolve
from forge.config import BACKEND_REGISTRY, BackendConfig, BackendLanguage, ProjectConfig
from forge.errors import (
    PROVENANCE_MANIFEST_MISSING,
    ForgeError,
    OptionsError,
    ProvenanceError,
)
from forge.feature_injector import apply_features, apply_project_features
from forge.forge_toml import read_forge_toml, write_forge_toml
from forge.provenance import FileState, ProvenanceCollector, ProvenanceRecord, classify

logger = logging.getLogger(__name__)


def update_project(project_root: Path, quiet: bool = False) -> dict[str, object]:
    """Re-apply option-driven fragments to the project at ``project_root``.

    Returns a summary dict with ``backends``, ``fragments_applied``, and
    ``forge_version_before`` / ``forge_version_after`` keys. Raises
    :class:`ProvenanceError` if ``project_root`` isn't a forge-generated
    project (no ``forge.toml``) or if the registry no longer recognises
    a recorded option path.
    """
    manifest = project_root / "forge.toml"
    if not manifest.is_file():
        raise ProvenanceError(
            f"No forge.toml at {project_root}. Is this a forge-generated project?",
            code=PROVENANCE_MANIFEST_MISSING,
            context={"project_root": str(project_root)},
        )

    data = read_forge_toml(manifest)
    try:
        current_version = metadata.version("forge")
    except metadata.PackageNotFoundError:
        current_version = "0.0.0+unknown"

    backends = _infer_backends(project_root)
    if not backends:
        raise ProvenanceError(
            f"No services/<backend>/ directories found under {project_root}. Nothing to update.",
            context={"project_root": str(project_root)},
        )

    config = ProjectConfig(
        project_name=data.project_name or project_root.name,
        backends=list(backends),
        options=dict(data.options),
    )

    try:
        plan = resolve(config)
    except ForgeError as e:
        # Preserve the underlying error's code/context when re-raising so the
        # CLI envelope stays informative about which option path was at fault.
        raise OptionsError(
            f"Cannot resolve option plan from forge.toml: {e.message}. "
            "An option path or fragment may have been removed since this project "
            "was generated.",
            code=e.code,
            hint=e.hint,
            context={**e.context, "project_root": str(project_root)},
        ) from e

    # Classify every provenance-tracked file BEFORE re-applying. The
    # classification feeds the summary (user visibility) and warns about
    # user-modified files that are about to be left alone by the
    # skip_existing_files=True apply path.
    classification = classify_project_state(project_root, data.provenance)
    user_modified = [p for p, s in classification.items() if s == "user-modified"]
    if user_modified and not quiet:
        print(f"  [update] {len(user_modified)} file(s) modified since last generate:")
        for p in user_modified[:10]:
            print(f"    * {p}")
        if len(user_modified) > 10:
            print(f"    ... and {len(user_modified) - 10} more")
        print(
            "  [update] skip_existing_files=True — these files are preserved. "
            "Three-zone merge lands in 1.0.0a3."
        )

    # Fresh collector for the post-update provenance re-stamp. Carries over
    # any prior records we can't re-derive (user-labeled files).
    collector = ProvenanceCollector(project_root=project_root)
    for rel, entry in data.provenance.items():
        if entry.get("origin") == "user":
            collector.records[rel] = ProvenanceRecord(
                origin="user",
                sha256=str(entry.get("sha256", "")),
            )

    fragments_applied: list[str] = []
    for bc in config.backends:
        backend_dir = project_root / "services" / bc.name
        if not backend_dir.is_dir():
            continue
        if not quiet:
            print(f"  [update] re-applying fragments to {bc.name} ({bc.language.value}) ...")
        apply_features(
            bc,
            backend_dir,
            plan.ordered,
            quiet=quiet,
            skip_existing_files=True,
            collector=collector,
        )

    if not quiet:
        print("  [update] re-applying project-scope fragments ...")
    apply_project_features(
        project_root,
        plan.ordered,
        quiet=quiet,
        skip_existing_files=True,
        collector=collector,
    )

    for rf in plan.ordered:
        if rf.fragment.name not in fragments_applied:
            fragments_applied.append(rf.fragment.name)

    _restamp_forge_toml(
        manifest=manifest,
        project_name=data.project_name or project_root.name,
        backends=tuple(config.backends),
        option_values=plan.option_values,
        current_version=current_version,
        provenance=collector.as_dict(),
        merge_blocks=collector.merge_blocks_as_dict(),
    )

    return {
        "backends": [bc.name for bc in config.backends],
        "fragments_applied": fragments_applied,
        "forge_version_before": data.version,
        "forge_version_after": current_version,
        "classification": {p: s for p, s in classification.items()},
        "user_modified_count": len(user_modified),
    }


def classify_project_state(
    project_root: Path, provenance_tbl: dict[str, dict[str, str]]
) -> dict[str, FileState]:
    """Classify every recorded file as unchanged / user-modified / missing.

    Files not in the provenance table are invisible to this pass — the
    updater assumes the user created them on purpose. When the provenance
    table is empty (old pre-1.0 project), returns an empty classification
    and the updater falls back to its legacy skip_existing behavior.
    """
    out: dict[str, FileState] = {}
    for rel, entry in provenance_tbl.items():
        sha = str(entry.get("sha256", ""))
        if not sha:
            continue
        path = project_root / rel
        rec = ProvenanceRecord(origin="base-template", sha256=sha)
        out[rel] = classify(path, rec)
    return out


def _infer_backends(project_root: Path) -> list[BackendConfig]:
    """Discover backends from on-disk layout.

    Each ``services/<name>/`` is a backend. Language is inferred from the
    language-specific marker file present: ``pyproject.toml`` → python,
    ``package.json`` → node, ``Cargo.toml`` → rust.
    """
    services = project_root / "services"
    if not services.is_dir():
        return []

    markers: dict[str, BackendLanguage] = {
        "pyproject.toml": BackendLanguage.PYTHON,
        "package.json": BackendLanguage.NODE,
        "Cargo.toml": BackendLanguage.RUST,
    }

    out: list[BackendConfig] = []
    for backend_dir in sorted(services.iterdir()):
        if not backend_dir.is_dir():
            continue
        for marker, lang in markers.items():
            if (backend_dir / marker).is_file():
                out.append(
                    BackendConfig(
                        name=backend_dir.name,
                        project_name=project_root.name,
                        language=lang,
                    )
                )
                break
    return out


def _restamp_forge_toml(
    manifest: Path,
    *,
    project_name: str,
    backends: tuple[BackendConfig, ...],
    option_values: dict[str, Any],
    current_version: str,
    provenance: dict[str, dict[str, str]] | None = None,
    merge_blocks: dict[str, dict[str, str]] | None = None,
) -> None:
    """Write forge.toml with the current version + options + provenance + merge blocks."""
    templates: dict[str, str] = {}
    for lang in sorted({bc.language for bc in backends}, key=lambda L: L.value):
        templates[lang.value] = BACKEND_REGISTRY[lang].template_dir

    write_forge_toml(
        manifest,
        version=current_version,
        project_name=project_name,
        templates=templates,
        options=dict(option_values),
        provenance=provenance,
        merge_blocks=merge_blocks,
    )
