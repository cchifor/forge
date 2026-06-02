"""Tests for feature_manifest: TOML parsing and contract validation."""

from __future__ import annotations

import pytest

from forge.errors import (
    FEATURE_MANIFEST_INVALID,
    FEATURE_MANIFEST_MISSING,
    PluginError,
)
from forge.feature_manifest import (
    FeatureManifest,
    parse_feature_manifest,
    validate_manifest_contracts,
)

MINIMAL_TOML = """\
[feature]
name = "auth"
version = "1.0.0"
summary = "JWT authentication"
category = "security"
"""

FULL_TOML = """\
[feature]
name = "observability"
version = "2.1.0"
summary = "Structured logging and metrics"
category = "ops"

[feature.depends]
auth = ">=1.0.0"
core = ">=0.5.0"

[feature.provides]
options = ["obs.log_level", "obs.metrics_port"]
fragments = ["obs_logging", "obs_metrics"]
"""


@pytest.fixture()
def _write_toml(tmp_path):
    """Return a helper that writes TOML content to tmp_path/feature.toml."""

    def _write(content: str):
        p = tmp_path / "feature.toml"
        p.write_text(content, encoding="utf-8")
        return p

    return _write


class TestParseFeatureManifest:
    def test_parses_valid_minimal_manifest(self, tmp_path, _write_toml) -> None:
        path = _write_toml(MINIMAL_TOML)
        m = parse_feature_manifest(path, module_path="forge.features.auth")

        assert m.name == "auth"
        assert m.version == "1.0.0"
        assert m.summary == "JWT authentication"
        assert m.category == "security"
        assert m.depends == {}
        assert m.provides_options == ()
        assert m.provides_fragments == ()
        assert m.module_path == "forge.features.auth"
        assert m.manifest_path == str(path)

    def test_parses_full_manifest(self, tmp_path, _write_toml) -> None:
        path = _write_toml(FULL_TOML)
        m = parse_feature_manifest(path, module_path="forge.features.obs")

        assert m.name == "observability"
        assert m.version == "2.1.0"
        assert m.summary == "Structured logging and metrics"
        assert m.category == "ops"
        assert m.depends == {"auth": ">=1.0.0", "core": ">=0.5.0"}
        assert m.provides_options == ("obs.log_level", "obs.metrics_port")
        assert m.provides_fragments == ("obs_logging", "obs_metrics")

    def test_missing_file_raises(self, tmp_path) -> None:
        path = tmp_path / "nonexistent" / "feature.toml"
        with pytest.raises(PluginError, match="not found") as exc_info:
            parse_feature_manifest(path, module_path="m")
        assert exc_info.value.code == FEATURE_MANIFEST_MISSING

    def test_missing_feature_table_raises(self, tmp_path, _write_toml) -> None:
        path = _write_toml("[metadata]\nkey = 'value'\n")
        with pytest.raises(PluginError, match=r"Missing \[feature\] table") as exc_info:
            parse_feature_manifest(path, module_path="m")
        assert exc_info.value.code == FEATURE_MANIFEST_INVALID

    def test_missing_required_fields_raises(self, tmp_path, _write_toml) -> None:
        path = _write_toml("[feature]\nname = 'x'\n")
        with pytest.raises(PluginError, match="Missing required fields") as exc_info:
            parse_feature_manifest(path, module_path="m")
        assert exc_info.value.code == FEATURE_MANIFEST_INVALID
        assert set(exc_info.value.context["missing"]) == {"version", "summary", "category"}

    def test_invalid_depends_type_raises(self, tmp_path, _write_toml) -> None:
        toml = MINIMAL_TOML + '\n[feature]\ndepends = "not-a-table"\n'
        # tomlkit merges [feature] tables, so use inline form instead
        path = _write_toml(
            '[feature]\n'
            'name = "x"\n'
            'version = "1"\n'
            'summary = "s"\n'
            'category = "c"\n'
            'depends = "not-a-table"\n'
        )
        with pytest.raises(PluginError, match="must be a table") as exc_info:
            parse_feature_manifest(path, module_path="m")
        assert exc_info.value.code == FEATURE_MANIFEST_INVALID

    def test_invalid_provides_type_raises(self, tmp_path, _write_toml) -> None:
        path = _write_toml(
            '[feature]\n'
            'name = "x"\n'
            'version = "1"\n'
            'summary = "s"\n'
            'category = "c"\n'
            'provides = "not-a-table"\n'
        )
        with pytest.raises(PluginError, match="must be a table") as exc_info:
            parse_feature_manifest(path, module_path="m")
        assert exc_info.value.code == FEATURE_MANIFEST_INVALID

    def test_provides_options_must_be_list(self, tmp_path, _write_toml) -> None:
        path = _write_toml(
            '[feature]\n'
            'name = "x"\n'
            'version = "1"\n'
            'summary = "s"\n'
            'category = "c"\n'
            '\n'
            '[feature.provides]\n'
            'options = "not-a-list"\n'
        )
        with pytest.raises(PluginError, match="options must be a list") as exc_info:
            parse_feature_manifest(path, module_path="m")
        assert exc_info.value.code == FEATURE_MANIFEST_INVALID

    def test_provides_fragments_must_be_list(self, tmp_path, _write_toml) -> None:
        path = _write_toml(
            '[feature]\n'
            'name = "x"\n'
            'version = "1"\n'
            'summary = "s"\n'
            'category = "c"\n'
            '\n'
            '[feature.provides]\n'
            'fragments = 42\n'
        )
        with pytest.raises(PluginError, match="fragments must be a list") as exc_info:
            parse_feature_manifest(path, module_path="m")
        assert exc_info.value.code == FEATURE_MANIFEST_INVALID


    def test_empty_name_rejected(self, tmp_path, _write_toml) -> None:
        path = _write_toml(
            '[feature]\n'
            'name = ""\n'
            'version = "1"\n'
            'summary = "s"\n'
            'category = "c"\n'
        )
        with pytest.raises(PluginError, match="must not be empty") as exc_info:
            parse_feature_manifest(path, module_path="m")
        assert exc_info.value.code == FEATURE_MANIFEST_INVALID

    def test_whitespace_only_name_rejected(self, tmp_path, _write_toml) -> None:
        path = _write_toml(
            '[feature]\n'
            'name = "  "\n'
            'version = "1"\n'
            'summary = "s"\n'
            'category = "c"\n'
        )
        with pytest.raises(PluginError, match="must not be empty") as exc_info:
            parse_feature_manifest(path, module_path="m")
        assert exc_info.value.code == FEATURE_MANIFEST_INVALID


class TestValidateContracts:
    @pytest.fixture()
    def _manifest(self) -> FeatureManifest:
        return FeatureManifest(
            name="obs",
            version="1.0.0",
            summary="s",
            category="c",
            depends={},
            provides_options=("obs.level", "obs.port"),
            provides_fragments=("obs_log", "obs_metric"),
            module_path="m",
            manifest_path="/fake/feature.toml",
        )

    def test_all_provides_registered_returns_empty(self, _manifest) -> None:
        errors = validate_manifest_contracts(
            _manifest,
            registered_options=frozenset({"obs.level", "obs.port"}),
            registered_fragments=frozenset({"obs_log", "obs_metric"}),
        )
        assert errors == []

    def test_missing_option_returns_error(self, _manifest) -> None:
        errors = validate_manifest_contracts(
            _manifest,
            registered_options=frozenset({"obs.level"}),  # obs.port missing
            registered_fragments=frozenset({"obs_log", "obs_metric"}),
        )
        assert len(errors) == 1
        assert "obs.port" in errors[0]
        assert "not registered" in errors[0]

    def test_missing_fragment_returns_error(self, _manifest) -> None:
        errors = validate_manifest_contracts(
            _manifest,
            registered_options=frozenset({"obs.level", "obs.port"}),
            registered_fragments=frozenset({"obs_log"}),  # obs_metric missing
        )
        assert len(errors) == 1
        assert "obs_metric" in errors[0]
        assert "not registered" in errors[0]

    def test_multiple_violations_returned(self, _manifest) -> None:
        errors = validate_manifest_contracts(
            _manifest,
            registered_options=frozenset(),
            registered_fragments=frozenset(),
        )
        # 2 missing options + 2 missing fragments = 4 errors
        assert len(errors) == 4
        mentioned = " ".join(errors)
        assert "obs.level" in mentioned
        assert "obs.port" in mentioned
        assert "obs_log" in mentioned
        assert "obs_metric" in mentioned


class TestComponentLayerField:
    """The additive `[feature].layer` (component_layer) + `stability` fields.

    These let a feature.toml double as a layered-component manifest. Both are
    optional so every existing manifest keeps parsing unchanged. The TOML key is
    `layer` (per spec); the dataclass field is `component_layer` to stay clearly
    distinct from `fragments._spec.ParityTier` (an orthogonal {1,2,3} concept).
    """

    def test_layer_absent_defaults_to_none(self, _write_toml) -> None:
        m = parse_feature_manifest(
            _write_toml(MINIMAL_TOML), module_path="forge.features.auth"
        )
        assert m.component_layer is None
        assert m.stability is None

    @pytest.mark.parametrize("layer", [1, 2, 3])
    def test_parses_valid_layer(self, _write_toml, layer: int) -> None:
        toml = (
            "[feature]\n"
            'name = "stat_card"\n'
            'version = "1.0.0"\n'
            'summary = "A KPI card"\n'
            'category = "component"\n'
            'stability = "beta"\n'
            f"layer = {layer}\n"
        )
        m = parse_feature_manifest(_write_toml(toml), module_path="m")
        assert m.component_layer == layer
        assert m.stability == "beta"

    @pytest.mark.parametrize("bad", [0, 4, 5, -1])
    def test_layer_out_of_range_rejected(self, _write_toml, bad: int) -> None:
        toml = (
            "[feature]\n"
            'name = "x"\n'
            'version = "1"\n'
            'summary = "s"\n'
            'category = "c"\n'
            f"layer = {bad}\n"
        )
        with pytest.raises(PluginError, match="layer") as exc:
            parse_feature_manifest(_write_toml(toml), module_path="m")
        assert exc.value.code == FEATURE_MANIFEST_INVALID

    def test_layer_non_integer_rejected(self, _write_toml) -> None:
        toml = (
            "[feature]\n"
            'name = "x"\n'
            'version = "1"\n'
            'summary = "s"\n'
            'category = "c"\n'
            'layer = "two"\n'
        )
        with pytest.raises(PluginError, match="layer") as exc:
            parse_feature_manifest(_write_toml(toml), module_path="m")
        assert exc.value.code == FEATURE_MANIFEST_INVALID
