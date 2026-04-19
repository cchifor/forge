"""`forge --update` — re-apply options to an existing forge-generated project.

Reads the ``[forge.options]`` stamp from ``forge.toml``, runs the current
resolver against it, re-applies every fragment to each discovered
backend, then re-stamps ``forge.toml`` with the current forge version
and the fully-defaulted option map. Injections are idempotent (B2.3
sentinels), so running this repeatedly is a no-op when nothing changed
and a clean in-place update when a fragment snippet was modified or a
new Option was added.

Out of scope:
  - Template-level Copier updates (base template changes). Users who want
    those can ``cd <backend>/`` and run ``copier update`` directly —
    ``.copier-answers.yml`` is the input.
  - Deleting files from Options that were turned off. Needs the provenance
    manifest follow-up first.
"""

from __future__ import annotations

import logging
from importlib import metadata
from pathlib import Path
from typing import Any

from forge.capability_resolver import resolve
from forge.config import BACKEND_REGISTRY, BackendConfig, BackendLanguage, ProjectConfig
from forge.errors import GeneratorError
from forge.feature_injector import apply_features, apply_project_features
from forge.forge_toml import read_forge_toml, write_forge_toml

logger = logging.getLogger(__name__)


def update_project(project_root: Path, quiet: bool = False) -> dict[str, object]:
    """Re-apply option-driven fragments to the project at ``project_root``.

    Returns a summary dict with ``backends``, ``fragments_applied``, and
    ``forge_version_before`` / ``forge_version_after`` keys. Raises
    ``GeneratorError`` if ``project_root`` isn't a forge-generated
    project (no ``forge.toml``) or if the registry no longer recognises
    a recorded option path.
    """
    manifest = project_root / "forge.toml"
    if not manifest.is_file():
        raise GeneratorError(f"No forge.toml at {project_root}. Is this a forge-generated project?")

    data = read_forge_toml(manifest)
    try:
        current_version = metadata.version("forge")
    except metadata.PackageNotFoundError:
        current_version = "0.0.0+unknown"

    backends = _infer_backends(project_root)
    if not backends:
        raise GeneratorError(
            f"No services/<backend>/ directories found under {project_root}. Nothing to update."
        )

    config = ProjectConfig(
        project_name=data.project_name or project_root.name,
        backends=list(backends),
        options=dict(data.options),
    )

    try:
        plan = resolve(config)
    except GeneratorError as e:
        raise GeneratorError(
            f"Cannot resolve option plan from forge.toml: {e}. "
            "An option path or fragment may have been removed since this project "
            "was generated."
        ) from e

    fragments_applied: list[str] = []
    for bc in config.backends:
        backend_dir = project_root / "services" / bc.name
        if not backend_dir.is_dir():
            continue
        if not quiet:
            print(f"  [update] re-applying fragments to {bc.name} ({bc.language.value}) ...")
        apply_features(bc, backend_dir, plan.ordered, quiet=quiet, skip_existing_files=True)

    if not quiet:
        print("  [update] re-applying project-scope fragments ...")
    apply_project_features(project_root, plan.ordered, quiet=quiet, skip_existing_files=True)

    for rf in plan.ordered:
        if rf.fragment.name not in fragments_applied:
            fragments_applied.append(rf.fragment.name)

    _restamp_forge_toml(
        manifest=manifest,
        project_name=data.project_name or project_root.name,
        backends=tuple(config.backends),
        option_values=plan.option_values,
        current_version=current_version,
    )

    return {
        "backends": [bc.name for bc in config.backends],
        "fragments_applied": fragments_applied,
        "forge_version_before": data.version,
        "forge_version_after": current_version,
    }


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
) -> None:
    """Write forge.toml with the current version + fully-defaulted options."""
    templates: dict[str, str] = {}
    for lang in sorted({bc.language for bc in backends}, key=lambda L: L.value):
        templates[lang.value] = BACKEND_REGISTRY[lang].template_dir

    write_forge_toml(
        manifest,
        version=current_version,
        project_name=project_name,
        templates=templates,
        options=dict(option_values),
    )
