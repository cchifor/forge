"""Tests for :class:`PortSpec` — Pillar A.4's port-declaration analog of
:class:`MiddlewareSpec`.

Covers:

- :class:`PortSpec` satisfies the
  :class:`~forge.appliers.renderers.FragmentRenderer` Protocol at
  runtime (``isinstance(spec, FragmentRenderer)``).
- Each per-backend renderer emits the expected target + marker +
  import-statement shape, modelled on the existing ``queue_port``
  fragment that PortSpec is designed to subsume.
- ``attach_zone`` propagates from spec → every emitted ``_Injection``.
- Heterogeneous renderer dispatch: a fragment shipping both a
  :class:`MiddlewareSpec` and a :class:`PortSpec` produces both
  sets of injections in deterministic ``(order, name)`` order
  through the same :func:`forge.appliers.plan._render_all` loop.
- Round-trip through :meth:`FragmentPipeline.run` — the spec flows
  to disk-mutating injections via the public applier surface, not
  just the raw plan API.
- Cycle detection — :func:`detect_port_cycle` flags
  ``port_dependencies`` cycles and returns the cycle path.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from forge.appliers import PortSpec
from forge.appliers.plan import FragmentPlan
from forge.appliers.renderers import FragmentRenderer
from forge.config import BackendLanguage
from forge.fragments import FragmentImplSpec
from forge.specs.middleware import MiddlewareSpec
from forge.specs.port import (
    detect_port_cycle,
    render_axum_port,
    render_fastapi_port,
    render_fastify_port,
)

if TYPE_CHECKING:
    from forge.appliers.plan import InjectionZone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _python_port(
    name: str = "llm",
    attach_zone: InjectionZone = "generated",
    order: int = 100,
    port_dependencies: tuple[str, ...] = (),
) -> PortSpec:
    return PortSpec(
        name=name,
        backend=BackendLanguage.PYTHON,
        interface_path=f"app/ports/{name}.py",
        adapter_imports=(f"OpenAiAdapter from app.adapters.{name}.openai",),
        service_factory=f"_{name}_adapter = OpenAiAdapter(api_key='test')",
        attach_zone=attach_zone,
        order=order,
        port_dependencies=port_dependencies,
    )


def _node_port(name: str = "llm") -> PortSpec:
    return PortSpec(
        name=name,
        backend=BackendLanguage.NODE,
        interface_path=f"app/ports/{name}.ts",
        adapter_imports=(f"OpenAiAdapter from ./app/adapters/{name}/openai",),
        service_factory=f"const _{name}Adapter = new OpenAiAdapter();",
    )


def _rust_port(name: str = "llm") -> PortSpec:
    return PortSpec(
        name=name,
        backend=BackendLanguage.RUST,
        interface_path=f"src/ports/{name}.rs",
        adapter_imports=(f"crate::adapters::{name}_openai::OpenAiAdapter",),
        service_factory=f"let _{name}_adapter = OpenAiAdapter::new();",
    )


# ---------------------------------------------------------------------------
# Protocol conformance — Pillar A.2 contract
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_port_spec_is_a_fragment_renderer(self) -> None:
        assert isinstance(_python_port(), FragmentRenderer)

    def test_port_spec_render_filters_on_backend_mismatch(self) -> None:
        py_spec = _python_port()
        node_injs = py_spec.render(backend=BackendLanguage.NODE, feature_key="llm_port")
        assert node_injs == ()

    def test_port_spec_render_returns_empty_for_unknown_backend(self) -> None:
        """A spec whose backend has no registered renderer returns ``()``
        — matches :class:`MiddlewareSpec`'s graceful-degradation contract."""
        # No way to manufacture a "plugin language with no renderer" without
        # mutating internal dispatch tables. Closest exercise: a real
        # backend whose spec doesn't match the active backend. Distinct
        # filter; same observable behaviour.
        py_spec = _python_port()
        assert py_spec.render(backend=BackendLanguage.RUST, feature_key="x") == ()


# ---------------------------------------------------------------------------
# Per-backend renderer unit tests
# ---------------------------------------------------------------------------


class TestRenderFastapiPort:
    def test_emits_one_injection_at_container_anchor(self) -> None:
        spec = _python_port(name="llm")
        injs = spec.render(backend=BackendLanguage.PYTHON, feature_key="llm_port")

        assert len(injs) == 1
        inj = injs[0]
        assert inj.target == "src/app/core/container.py"
        assert inj.marker == "FORGE:APP_POST_CONFIGURE"
        assert inj.position == "after"
        assert inj.feature_key == "llm_port"

    def test_snippet_includes_port_import_and_adapter_import(self) -> None:
        spec = _python_port(name="llm")
        (inj,) = spec.render(backend=BackendLanguage.PYTHON, feature_key="llm_port")

        # Port interface import — slashes-to-dots, .py stripped.
        assert "from app.ports.llm import *" in inj.snippet
        # Adapter import — "Symbol from module" → "from module import Symbol"
        assert "from app.adapters.llm.openai import OpenAiAdapter" in inj.snippet
        # Service factory verbatim.
        assert "_llm_adapter = OpenAiAdapter(api_key='test')" in inj.snippet
        # Port-name comment header.
        assert "# Port: llm" in inj.snippet

    def test_module_level_render_function_matches_spec_render(self) -> None:
        spec = _python_port(name="llm")
        from forge.specs.port import _default_jinja_env  # noqa: PLC0415

        env = _default_jinja_env()
        direct = render_fastapi_port(spec, "llm_port", env)
        via_spec = spec.render(backend=BackendLanguage.PYTHON, feature_key="llm_port")
        assert direct == via_spec


class TestRenderFastifyPort:
    def test_emits_one_injection_at_app_imports_anchor(self) -> None:
        spec = _node_port(name="llm")
        injs = spec.render(backend=BackendLanguage.NODE, feature_key="llm_port")

        assert len(injs) == 1
        inj = injs[0]
        assert inj.target == "src/app.ts"
        assert inj.marker == "FORGE:MIDDLEWARE_IMPORTS"

    def test_snippet_includes_type_import_and_adapter_factory(self) -> None:
        spec = _node_port(name="llm")
        (inj,) = spec.render(backend=BackendLanguage.NODE, feature_key="llm_port")

        # Port type-only import — .ts → .js, leading ./ added.
        assert 'import type * as llmPort from "./app/ports/llm.js";' in inj.snippet
        # Adapter import.
        assert 'import { OpenAiAdapter } from "./app/adapters/llm/openai.js";' in inj.snippet
        # Service factory verbatim.
        assert "const _llmAdapter = new OpenAiAdapter();" in inj.snippet

    def test_module_level_render_function_matches_spec_render(self) -> None:
        spec = _node_port(name="llm")
        from forge.specs.port import _default_jinja_env  # noqa: PLC0415

        env = _default_jinja_env()
        direct = render_fastify_port(spec, "llm_port", env)
        via_spec = spec.render(backend=BackendLanguage.NODE, feature_key="llm_port")
        assert direct == via_spec


class TestRenderAxumPort:
    def test_emits_one_injection_at_lib_mod_anchor(self) -> None:
        spec = _rust_port(name="llm")
        injs = spec.render(backend=BackendLanguage.RUST, feature_key="llm_port")

        assert len(injs) == 1
        inj = injs[0]
        assert inj.target == "src/lib.rs"
        assert inj.marker == "FORGE:LIB_MOD_REGISTRATION"

    def test_snippet_derives_mod_decl_from_filesystem_path(self) -> None:
        spec = _rust_port(name="llm")
        (inj,) = spec.render(backend=BackendLanguage.RUST, feature_key="llm_port")

        # Filesystem-path shape → ``pub mod ports;`` + ``use crate::ports::llm::*;``
        assert "pub mod ports;" in inj.snippet
        assert "use crate::ports::llm::*;" in inj.snippet
        # Adapter use line.
        assert "use crate::adapters::llm_openai::OpenAiAdapter;" in inj.snippet

    def test_snippet_uses_module_path_shape_verbatim(self) -> None:
        """``interface_path="crate::ports::llm"`` skips the mod-decl derivation."""
        spec = PortSpec(
            name="llm",
            backend=BackendLanguage.RUST,
            interface_path="crate::ports::llm",
            adapter_imports=("crate::adapters::llm_openai::OpenAiAdapter",),
            service_factory="let _llm = OpenAiAdapter::new();",
        )
        (inj,) = spec.render(backend=BackendLanguage.RUST, feature_key="llm_port")
        assert "use crate::ports::llm::*;" in inj.snippet
        # Mod decl is suppressed for module-path shape.
        assert "pub mod ports;" not in inj.snippet

    def test_module_level_render_function_matches_spec_render(self) -> None:
        spec = _rust_port(name="llm")
        from forge.specs.port import _default_jinja_env  # noqa: PLC0415

        env = _default_jinja_env()
        direct = render_axum_port(spec, "llm_port", env)
        via_spec = spec.render(backend=BackendLanguage.RUST, feature_key="llm_port")
        assert direct == via_spec


# ---------------------------------------------------------------------------
# attach_zone propagation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("zone", ["generated", "user", "merge"])
class TestAttachZonePropagation:
    def test_python_propagates_to_emitted_injections(self, zone: InjectionZone) -> None:
        spec = _python_port(attach_zone=zone)
        injs = spec.render(backend=BackendLanguage.PYTHON, feature_key="llm_port")
        assert all(inj.zone == zone for inj in injs)

    def test_node_propagates_to_emitted_injections(self, zone: InjectionZone) -> None:
        spec = PortSpec(
            name="llm",
            backend=BackendLanguage.NODE,
            interface_path="app/ports/llm.ts",
            attach_zone=zone,
        )
        injs = spec.render(backend=BackendLanguage.NODE, feature_key="llm_port")
        assert all(inj.zone == zone for inj in injs)

    def test_rust_propagates_to_emitted_injections(self, zone: InjectionZone) -> None:
        spec = PortSpec(
            name="llm",
            backend=BackendLanguage.RUST,
            interface_path="src/ports/llm.rs",
            attach_zone=zone,
        )
        injs = spec.render(backend=BackendLanguage.RUST, feature_key="llm_port")
        assert all(inj.zone == zone for inj in injs)


# ---------------------------------------------------------------------------
# Heterogeneous dispatch — MiddlewareSpec + PortSpec in one fragment
# ---------------------------------------------------------------------------


class TestHeterogeneousDispatch:
    def test_middleware_and_port_specs_coexist(self, tmp_path: Path) -> None:
        frag = tmp_path / "combo"
        frag.mkdir()
        impl = FragmentImplSpec(fragment_dir=str(frag))

        mw = MiddlewareSpec(
            name="combo_mw",
            backend=BackendLanguage.PYTHON,
            order=50,
            import_snippet="import combo_mw",
            register_snippet="app.add_middleware(ComboMW)",
        )
        port = PortSpec(
            name="combo_port",
            backend=BackendLanguage.PYTHON,
            interface_path="app/ports/combo.py",
            adapter_imports=(),
            service_factory="",
            order=10,
        )

        plan = FragmentPlan.from_impl(
            impl,
            "combo",
            renderers=(mw, port),
            backend=BackendLanguage.PYTHON,
        )

        # 2 from middleware + 1 from port = 3 injections total.
        assert len(plan.injections) == 3
        markers = [inj.marker for inj in plan.injections]
        # ``_render_all`` sorts by ``(order, name)``, so combo_port
        # (order=10) renders before combo_mw (order=50). The single
        # port injection lands first.
        assert markers == [
            "FORGE:APP_POST_CONFIGURE",
            "FORGE:MIDDLEWARE_IMPORTS",
            "FORGE:MIDDLEWARE_REGISTRATION",
        ]

    def test_port_spec_skipped_on_backend_mismatch(self, tmp_path: Path) -> None:
        """A fragment shipping per-backend ports doesn't emit Python
        injections when the active backend is Node."""
        frag = tmp_path / "all_backends"
        frag.mkdir()
        impl = FragmentImplSpec(fragment_dir=str(frag))

        node_plan = FragmentPlan.from_impl(
            impl,
            "llm_port",
            renderers=(_python_port(), _node_port(), _rust_port()),
            backend=BackendLanguage.NODE,
        )
        # Only the Node spec contributes.
        assert len(node_plan.injections) == 1
        assert node_plan.injections[0].target == "src/app.ts"


# ---------------------------------------------------------------------------
# Pipeline round-trip
# ---------------------------------------------------------------------------


class TestPipelineRoundTrip:
    """PortSpec flows end-to-end through ``FragmentPipeline.run``."""

    def test_pipeline_run_expands_port_spec_into_injection_phase(self, tmp_path: Path) -> None:
        from forge.appliers.pipeline import FragmentPipeline  # noqa: PLC0415
        from forge.config import BackendConfig  # noqa: PLC0415
        from forge.fragment_context import FragmentContext  # noqa: PLC0415

        # Real frag dir on disk + a real backend target file the injection
        # applier can mutate.
        frag = tmp_path / "llm_port"
        frag.mkdir()
        impl = FragmentImplSpec(fragment_dir=str(frag))

        backend_dir = tmp_path / "backend"
        (backend_dir / "src" / "app" / "core").mkdir(parents=True)
        target = backend_dir / "src" / "app" / "core" / "container.py"
        target.write_text(
            "# top of container.py\n# FORGE:APP_POST_CONFIGURE\n# bottom\n",
            encoding="utf-8",
        )

        ctx = FragmentContext(
            backend_config=BackendConfig(
                name="api",
                project_name="p",
                language=BackendLanguage.PYTHON,
            ),
            backend_dir=backend_dir,
            project_root=tmp_path,
            options={},
            provenance=None,
        )

        FragmentPipeline.default().run(
            ctx,
            impl,
            "llm_port",
            renderers=(_python_port(),),
        )

        after = target.read_text(encoding="utf-8")
        # The injection landed.
        assert "FORGE:BEGIN" in after
        assert "from app.ports.llm import *" in after
        assert "_llm_adapter = OpenAiAdapter(api_key='test')" in after


# ---------------------------------------------------------------------------
# Cycle detection — Fragment-level validation helper
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_no_cycle_returns_none(self) -> None:
        ports = (
            _python_port(name="llm", order=100),
            _python_port(name="rag", order=110, port_dependencies=("llm",)),
            _python_port(name="agent", order=120, port_dependencies=("llm", "rag")),
        )
        assert detect_port_cycle(ports) is None

    def test_self_cycle_detected(self) -> None:
        ports = (_python_port(name="loop", port_dependencies=("loop",)),)
        cycle = detect_port_cycle(ports)
        assert cycle == ("loop", "loop")

    def test_two_node_cycle_detected(self) -> None:
        ports = (
            _python_port(name="a", port_dependencies=("b",)),
            _python_port(name="b", port_dependencies=("a",)),
        )
        cycle = detect_port_cycle(ports)
        assert cycle is not None
        # The first node visited starts the cycle; cycle returns to it.
        assert cycle[0] == cycle[-1]
        assert set(cycle) <= {"a", "b"}

    def test_external_dep_ignored(self) -> None:
        """A dep pointing at a port name not in the ``ports`` tuple is
        treated as external — no edge, no cycle."""
        ports = (
            _python_port(name="llm", port_dependencies=("queue",)),  # queue not present
        )
        assert detect_port_cycle(ports) is None

    def test_empty_ports_returns_none(self) -> None:
        assert detect_port_cycle(()) is None


# ---------------------------------------------------------------------------
# Adapter-less interface-only ports — the queue_port shape
# ---------------------------------------------------------------------------


class TestInterfaceOnlyPort:
    """A port with no concrete adapter (empty ``adapter_imports`` +
    empty ``service_factory``) still emits a valid import-only snippet —
    matches the pre-adapter ``queue_port`` shape."""

    def test_python_interface_only_emits_port_import(self) -> None:
        spec = PortSpec(
            name="queue",
            backend=BackendLanguage.PYTHON,
            interface_path="app/ports/queue.py",
        )
        (inj,) = spec.render(backend=BackendLanguage.PYTHON, feature_key="queue_port")
        assert "from app.ports.queue import *" in inj.snippet
        assert "# Port: queue" in inj.snippet

    def test_rust_interface_only_emits_mod_decl_only(self) -> None:
        spec = PortSpec(
            name="queue",
            backend=BackendLanguage.RUST,
            interface_path="src/ports/queue.rs",
        )
        (inj,) = spec.render(backend=BackendLanguage.RUST, feature_key="queue_port")
        assert "pub mod ports;" in inj.snippet
        assert "use crate::ports::queue::*;" in inj.snippet


# ---------------------------------------------------------------------------
# Parametrised render dispatch — guard against future regressions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("backend", "expected_target", "expected_marker"),
    [
        (BackendLanguage.PYTHON, "src/app/core/container.py", "FORGE:APP_POST_CONFIGURE"),
        (BackendLanguage.NODE, "src/app.ts", "FORGE:MIDDLEWARE_IMPORTS"),
        (BackendLanguage.RUST, "src/lib.rs", "FORGE:LIB_MOD_REGISTRATION"),
    ],
)
def test_render_dispatches_to_correct_anchor_per_backend(
    backend: BackendLanguage,
    expected_target: str,
    expected_marker: str,
) -> None:
    spec = PortSpec(
        name="dispatch",
        backend=backend,
        interface_path=(
            "app/ports/dispatch.py"
            if backend is BackendLanguage.PYTHON
            else "app/ports/dispatch.ts"
            if backend is BackendLanguage.NODE
            else "src/ports/dispatch.rs"
        ),
    )
    (inj,) = spec.render(backend=backend, feature_key="dispatch")
    assert inj.target == expected_target
    assert inj.marker == expected_marker
