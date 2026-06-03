"""The loader auto-registers each component manifest's emitter fragment into
FRAGMENT_REGISTRY (computing the template dir from the manifest location), so a
selected component's .vue files are emitted by the existing appliers."""

from __future__ import annotations

from forge.components import register_component_fragments
from forge.feature_manifest import FeatureManifest


def _manifest(name, *, layer, manifest_path, children=None):
    return FeatureManifest(
        name=name,
        version="1.0.0",
        summary="s",
        category="component",
        depends={},
        provides_options=(),
        provides_fragments=(),
        module_path=f"forge.features.{name}",
        manifest_path=manifest_path,
        component_layer=layer,
        component_children=children or {},
    )


def test_registers_emitter_fragment_with_template_dir_from_manifest() -> None:
    reg: dict = {}
    comp = _manifest(
        "StatCard", layer=1, manifest_path="/repo/forge/features/stat_card/feature.toml"
    )
    plain = FeatureManifest(
        name="auth", version="1", summary="s", category="security", depends={},
        provides_options=(), provides_fragments=(), module_path="m", manifest_path="p",
    )
    names = register_component_fragments([comp, plain], registry=reg)
    assert names == ["component_StatCard"]
    frag = reg["component_StatCard"]
    # fragment_dir resolves to the feature's templates/<fragment>/all dir.
    assert frag.implementations  # non-empty impls
    impl = next(iter(frag.implementations.values()))
    # Normalise separators — fragment_dir is OS-native (backslashes on Windows).
    assert impl.fragment_dir.replace("\\", "/").endswith(
        "forge/features/stat_card/templates/component_StatCard/all"
    )
    assert impl.scope == "project"


def test_child_emitter_fragment_dependencies() -> None:
    reg: dict = {}
    panel = _manifest(
        "Panel", layer=2, manifest_path="/r/forge/features/panel/feature.toml",
        children={"StatCard": "*"},
    )
    register_component_fragments([panel], registry=reg)
    assert reg["component_Panel"].depends_on == ("component_StatCard",)
