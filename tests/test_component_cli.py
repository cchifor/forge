"""`forge --component-cmd ...` / `--template-cmd ...` CLI verbs (Phase 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge import feature_loader
from forge.cli.commands.components import (
    _dispatch_components,
    _dispatch_templates,
    _scaffold_component,
)


@pytest.fixture()
def _loaded():
    feature_loader.reset_for_tests()
    feature_loader.load_builtin_features()
    yield
    feature_loader.reset_for_tests()


class TestComponentList:
    def test_list_json_includes_statcard(self, _loaded, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            _dispatch_components("list", json_output=True)
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out.strip())
        assert isinstance(data, list)
        by_name = {e["name"]: e for e in data}
        assert "StatCard" in by_name
        assert by_name["StatCard"]["layer"] == 1
        # every entry carries the component-model fields
        for e in data:
            assert {"name", "layer", "version"} <= set(e)

    def test_list_text_runs(self, _loaded, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            _dispatch_components("list", json_output=False)
        assert exc.value.code == 0
        assert "StatCard" in capsys.readouterr().out

    def test_unknown_subcommand_exits_2(self, _loaded) -> None:
        with pytest.raises(SystemExit) as exc:
            _dispatch_components("bogus")
        assert exc.value.code == 2


class TestTemplateList:
    def test_template_list_only_layer3(self, _loaded, capsys) -> None:
        # StatCard is layer 1, so it must NOT appear in the template list.
        with pytest.raises(SystemExit) as exc:
            _dispatch_templates("list", json_output=True)
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out.strip())
        assert all(e["layer"] == 3 for e in data)
        assert "StatCard" not in {e["name"] for e in data}


class TestScaffoldComponent:
    def test_scaffold_emits_layer_aware_skeleton(self, tmp_path: Path) -> None:
        _scaffold_component("MenuItem", layer=1, root=tmp_path)
        feat = tmp_path / "menu_item"
        assert (feat / "feature.toml").is_file()
        toml = (feat / "feature.toml").read_text()
        assert "layer = 1" in toml
        assert 'name = "MenuItem"' in toml
        # emitter .vue stub + props schema stub
        assert (feat / "templates" / "component_MenuItem" / "all" / "files" / "src"
                / "shared" / "components" / "MenuItem.vue").is_file()
        assert (feat / "MenuItem.props.schema.json").is_file()

    def test_scaffold_rejects_bad_name(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            _scaffold_component("not a pascal name!", layer=1, root=tmp_path)

    @pytest.mark.parametrize("layer", [2, 3])
    def test_scaffold_honours_layer(self, tmp_path: Path, layer: int) -> None:
        _scaffold_component("Panel", layer=layer, root=tmp_path)
        assert f"layer = {layer}" in (tmp_path / "panel" / "feature.toml").read_text()

    def test_dispatch_scaffold_threads_layer(self, tmp_path, monkeypatch) -> None:
        # --component-cmd scaffold --component-layer N must reach _scaffold_component.
        import forge.cli.commands.components as mod

        seen = {}
        monkeypatch.setattr(
            mod, "_scaffold_component", lambda name, *, layer=1, **kw: seen.update(name=name, layer=layer)
        )
        with pytest.raises(SystemExit):
            mod._dispatch_components("scaffold", name="Panel", layer=2)
        assert seen == {"name": "Panel", "layer": 2}


class TestLayer3Templates:
    def test_seed_templates_present(self, _loaded) -> None:
        from forge.components import COMPONENT_REGISTRY

        templates = {n for n, c in COMPONENT_REGISTRY.items() if c.layer == 3}
        assert {"Console", "ChatFirst"} <= templates

    def test_console_composes_statcard(self, _loaded) -> None:
        # Selecting the Console L3 template pulls in its StatCard child,
        # ordered child-first.
        from forge.components import COMPONENT_REGISTRY, resolve_components

        res = resolve_components(["Console"], COMPONENT_REGISTRY)
        assert set(res.ordered) == {"Console", "StatCard"}
        assert res.ordered.index("StatCard") < res.ordered.index("Console")


class TestTelemetry:
    """The component/template verbs emit one bounded-vocabulary event each."""

    def _local_sink(self, tmp_path: Path) -> Path:
        from forge import telemetry

        sink = tmp_path / "telemetry.jsonl"
        telemetry.configure(telemetry.TelemetryConfig(mode="local", sink_path=sink))
        return sink

    def _events(self, sink: Path) -> list[dict]:
        from forge import telemetry

        telemetry.shutdown(wait=True)
        return [json.loads(line) for line in sink.read_text().splitlines() if line.strip()]

    def test_component_list_emits_component_ran(self, _loaded, capsys, tmp_path) -> None:
        from forge import telemetry

        sink = self._local_sink(tmp_path)
        with pytest.raises(SystemExit):
            _dispatch_components("list", json_output=True)
        capsys.readouterr()
        events = self._events(sink)
        assert [e["event"] for e in events] == [telemetry.EVENT_COMPONENT_RAN]
        assert events[0]["action"] == "list"

    def test_template_list_emits_template_ran(self, _loaded, capsys, tmp_path) -> None:
        from forge import telemetry

        sink = self._local_sink(tmp_path)
        with pytest.raises(SystemExit):
            _dispatch_templates("list", json_output=True)
        capsys.readouterr()
        events = self._events(sink)
        assert [e["event"] for e in events] == [telemetry.EVENT_TEMPLATE_RAN]
        assert events[0]["action"] == "list"
