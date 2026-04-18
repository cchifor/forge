"""`forge update` — re-apply features to an existing forge-generated project.

Phase 1 scope: re-run the feature injector against each backend in the
project. With B2.3's sentinel-wrapped snippets, injections become
idempotent — running this repeatedly is a no-op when nothing changed, and
a clean in-place update when a fragment's snippet was modified or a new
feature was enabled. Also re-stamps ``forge.toml`` with the current
forge version and feature state.

Intentionally out of scope for Phase 1:
  - Template-level Copier updates (base template changes). Users who want
    those can ``cd <backend>/`` and run ``copier update`` directly —
    ``.copier-answers.yml`` (written by B2.1) is the input.
  - Detecting renamed feature keys. The plan's B3.2 follow-up handles that
    via a future ``aliases`` field on ``FeatureSpec``.
  - Automatically deleting files from disabled fragments. Needs the B3.1
    provenance manifest first.
"""

from __future__ import annotations

import logging
from importlib import metadata
from pathlib import Path

from forge.capability_resolver import resolve
from forge.config import BACKEND_REGISTRY, BackendConfig, BackendLanguage, ProjectConfig
from forge.errors import GeneratorError
from forge.feature_injector import apply_features, apply_project_features
from forge.features import FeatureConfig
from forge.forge_toml import read_forge_toml, write_forge_toml

logger = logging.getLogger(__name__)


def update_project(project_root: Path, quiet: bool = False) -> dict[str, object]:
    """Re-apply features to the project at ``project_root``.

    Returns a summary dict with ``backends``, ``features_applied``, and
    ``forge_version_before`` / ``forge_version_after`` keys. Raises
    ``GeneratorError`` if ``project_root`` isn't a forge-generated project
    (no ``forge.toml``) or if the registry no longer recognises one of the
    recorded features.
    """
    manifest = project_root / "forge.toml"
    if not manifest.is_file():
        raise GeneratorError(
            f"No forge.toml at {project_root}. Is this a forge-generated project?"
        )

    data = read_forge_toml(manifest)
    try:
        current_version = metadata.version("forge")
    except metadata.PackageNotFoundError:
        current_version = "0.0.0+unknown"

    if data.legacy_features_format and not quiet:
        print(
            "  [forge.toml] legacy [forge.features] flat-list detected; "
            "upgrading to per-feature table shape."
        )

    # Reconstruct the minimum ProjectConfig the resolver needs — we only
    # care about backends + features, not frontend/Keycloak/port details,
    # since the injector is the only thing we re-run.
    backends = _infer_backends(project_root)
    if not backends:
        raise GeneratorError(
            f"No services/<backend>/ directories found under {project_root}. "
            "Nothing to update."
        )

    feature_selections: dict[str, FeatureConfig] = {}
    for key, spec in data.features.items():
        feature_selections[key] = FeatureConfig(
            enabled=bool(spec.get("enabled", False)),
            options=dict(spec.get("options", {})),
        )

    config = ProjectConfig(
        project_name=data.project_name or project_root.name,
        backends=tuple(backends),
        features=feature_selections,
    )

    try:
        plan = resolve(config)
    except GeneratorError as e:
        raise GeneratorError(
            f"Cannot resolve feature plan from forge.toml: {e}. "
            "A feature key may have been removed or renamed since this project "
            "was generated."
        ) from e

    features_applied: list[str] = []
    for bc in config.backends:
        backend_dir = project_root / "services" / bc.name
        if not backend_dir.is_dir():
            continue
        if not quiet:
            print(f"  [update] re-applying features to {bc.name} ({bc.language.value}) ...")
        apply_features(
            bc, backend_dir, plan.ordered, quiet=quiet, skip_existing_files=True
        )

    if not quiet:
        print("  [update] re-applying project-scope features ...")
    apply_project_features(project_root, plan.ordered, quiet=quiet, skip_existing_files=True)

    for rf in plan.ordered:
        if rf.spec.key not in features_applied:
            features_applied.append(rf.spec.key)

    # Re-stamp forge.toml with current version + canonical (non-legacy) shape.
    _restamp_forge_toml(
        manifest=manifest,
        project_name=data.project_name or project_root.name,
        backends=config.backends,
        features_applied=features_applied,
        selections=feature_selections,
        current_version=current_version,
    )

    return {
        "backends": [bc.name for bc in config.backends],
        "features_applied": features_applied,
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
    features_applied: list[str],
    selections: dict[str, FeatureConfig],
    current_version: str,
) -> None:
    """Write forge.toml with the current version + updated feature state."""
    templates: dict[str, str] = {}
    for lang in sorted({bc.language for bc in backends}, key=lambda L: L.value):
        templates[lang.value] = BACKEND_REGISTRY[lang].template_dir

    features: dict[str, dict[str, object]] = {}
    for key in features_applied:
        cfg = selections.get(key, FeatureConfig(enabled=True))
        features[key] = {
            "enabled": cfg.enabled,
            "options": dict(cfg.options),
        }

    write_forge_toml(
        manifest,
        version=current_version,
        project_name=project_name,
        templates=templates,
        features=features,
    )
