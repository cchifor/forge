"""FeatureManifest dataclass + TOML parser for feature.toml files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tomlkit

from forge.errors import (
    FEATURE_MANIFEST_INVALID,
    FEATURE_MANIFEST_MISSING,
    PluginError,
)


@dataclass(frozen=True)
class FeatureManifest:
    """Typed representation of a feature.toml manifest."""

    name: str
    version: str
    summary: str
    category: str
    depends: dict[str, str]
    provides_options: tuple[str, ...]
    provides_fragments: tuple[str, ...]
    module_path: str
    manifest_path: str
    # Optional, additive (layered-component model). Absent in non-component
    # features. ``component_layer`` is the TOML ``[feature].layer`` (1/2/3); the
    # field is named distinctly to avoid confusion with the orthogonal
    # ``fragments._spec.ParityTier`` ({1,2,3} cross-backend coverage).
    component_layer: int | None = None
    stability: str | None = None


def parse_feature_manifest(path: Path, *, module_path: str) -> FeatureManifest:
    """Parse a feature.toml file into a FeatureManifest."""
    if not path.exists():
        raise PluginError(
            f"Feature manifest not found: {path}",
            code=FEATURE_MANIFEST_MISSING,
            context={"path": str(path)},
        )

    try:
        text = path.read_text(encoding="utf-8")
        doc = tomlkit.parse(text)
    except Exception as exc:
        raise PluginError(
            f"Failed to parse {path}: {exc}",
            code=FEATURE_MANIFEST_INVALID,
            context={"path": str(path)},
        ) from exc

    feature = doc.get("feature")
    if not isinstance(feature, dict):
        raise PluginError(
            f"Missing [feature] table in {path}",
            code=FEATURE_MANIFEST_INVALID,
            context={"path": str(path)},
        )

    missing = [k for k in ("name", "version", "summary", "category") if k not in feature]
    if missing:
        raise PluginError(
            f"Missing required fields in [feature]: {', '.join(missing)}",
            code=FEATURE_MANIFEST_INVALID,
            context={"path": str(path), "missing": missing},
        )

    for field in ("name", "version", "summary", "category"):
        if not str(feature[field]).strip():
            raise PluginError(
                f"[feature].{field} must not be empty",
                code=FEATURE_MANIFEST_INVALID,
                context={"path": str(path), "field": field},
            )

    # Optional additive fields (layered-component model). Absent ⇒ None, so
    # every existing manifest parses unchanged.
    component_layer: int | None = None
    if "layer" in feature:
        layer_raw = feature["layer"]
        # bool is an int subclass — reject it explicitly. The TOML key accepts
        # only the integers 1, 2, 3 (Layer-1/2/3 component tiers).
        if (
            isinstance(layer_raw, bool)
            or not isinstance(layer_raw, int)
            or layer_raw not in (1, 2, 3)
        ):
            raise PluginError(
                f"[feature].layer must be 1, 2, or 3 (got {layer_raw!r})",
                code=FEATURE_MANIFEST_INVALID,
                context={"path": str(path), "layer": layer_raw},
            )
        component_layer = int(layer_raw)

    stability_raw = feature.get("stability")
    stability = str(stability_raw) if stability_raw is not None else None

    depends_raw = feature.get("depends", {})
    if not isinstance(depends_raw, dict):
        raise PluginError(
            f"[feature.depends] must be a table, got {type(depends_raw).__name__}",
            code=FEATURE_MANIFEST_INVALID,
            context={"path": str(path)},
        )

    provides = feature.get("provides", {})
    if not isinstance(provides, dict):
        raise PluginError(
            f"[feature.provides] must be a table, got {type(provides).__name__}",
            code=FEATURE_MANIFEST_INVALID,
            context={"path": str(path)},
        )

    options_raw = provides.get("options", [])
    fragments_raw = provides.get("fragments", [])
    if not isinstance(options_raw, list):
        raise PluginError(
            "provides.options must be a list",
            code=FEATURE_MANIFEST_INVALID,
            context={"path": str(path)},
        )
    if not isinstance(fragments_raw, list):
        raise PluginError(
            "provides.fragments must be a list",
            code=FEATURE_MANIFEST_INVALID,
            context={"path": str(path)},
        )

    return FeatureManifest(
        name=str(feature["name"]),
        version=str(feature["version"]),
        summary=str(feature["summary"]),
        category=str(feature["category"]),
        depends={str(k): str(v) for k, v in depends_raw.items()},
        provides_options=tuple(str(o) for o in options_raw),
        provides_fragments=tuple(str(f) for f in fragments_raw),
        module_path=module_path,
        manifest_path=str(path),
        component_layer=component_layer,
        stability=stability,
    )


def validate_manifest_contracts(
    manifest: FeatureManifest,
    registered_options: frozenset[str],
    registered_fragments: frozenset[str],
) -> list[str]:
    """Check that provides.options and provides.fragments match actual registrations."""
    errors: list[str] = []
    for opt in manifest.provides_options:
        if opt not in registered_options:
            errors.append(
                f"Feature {manifest.name!r} claims option {opt!r} but it is not registered"
            )
    for frag in manifest.provides_fragments:
        if frag not in registered_fragments:
            errors.append(
                f"Feature {manifest.name!r} claims fragment {frag!r} but it is not registered"
            )
    return errors
