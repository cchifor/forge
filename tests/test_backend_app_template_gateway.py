"""Tests for the ``api-gateway`` two-stage Python backend variant (P4.3).

``api-gateway`` is the FIRST shipped two-stage *backend* application template:
it renders the shared ``services/python-service-template`` base, then overlays a
thin gateway delta. These tests cover both the registry wiring (unit) and the
real two-stage render path end-to-end (integration), AST-parsing every rendered
gateway ``.py`` to catch syntax / Jinja errors.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from forge import backend_app_templates as bat
from forge.config import BackendConfig, BackendLanguage, ProjectConfig

_BASE = "services/python-service-template"
_TEMPLATE_DIR = "services/python/api-gateway"


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Restore built-in variants after any test that mutates the registry."""
    yield
    bat._reset_for_tests()


# --- (a) UNIT: registry + config wiring ------------------------------------


def test_api_gateway_registered_for_python():
    t = bat.get_backend_application_template(BackendLanguage.PYTHON, "api-gateway")
    assert t is not None
    assert t.supported is True
    assert t.template_dir == _TEMPLATE_DIR
    # Two-stage: a non-empty base distinguishes it from the self-contained
    # crud-service / worker variants.
    assert t.base_template_dir == _BASE


def test_api_gateway_in_available_python_templates():
    avail = bat.available_backend_templates(BackendLanguage.PYTHON)
    assert "api-gateway" in avail


def test_api_gateway_is_python_only():
    # The variant must not leak into node/rust.
    assert bat.get_backend_application_template(BackendLanguage.NODE, "api-gateway") is None
    assert bat.get_backend_application_template(BackendLanguage.RUST, "api-gateway") is None


def test_backend_config_validate_accepts_api_gateway():
    BackendConfig(
        name="edge", language=BackendLanguage.PYTHON, app_template="api-gateway"
    ).validate()


def test_backend_config_validate_rejects_unknown_app_template():
    cfg = BackendConfig(name="edge", language=BackendLanguage.PYTHON, app_template="not-a-variant")
    with pytest.raises(ValueError, match="not available"):
        cfg.validate()


def test_api_gateway_not_valid_for_node():
    # Language-scoped: api-gateway is Python-only.
    cfg = BackendConfig(name="edge", language=BackendLanguage.NODE, app_template="api-gateway")
    with pytest.raises(ValueError, match="not available for node"):
        cfg.validate()


# --- (b) INTEGRATION: real two-stage render path ---------------------------


def _render_gateway(tmp_path: Path, name: str = "edge-gateway") -> Path:
    cfg = ProjectConfig(
        project_name="gw_demo",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name=name,
                project_name="gw_demo",
                language=BackendLanguage.PYTHON,
                app_template="api-gateway",
                features=["items"],
            )
        ],
        frontend=None,
    )
    from forge.generator import generate

    root = generate(cfg, quiet=True, dry_run=True)
    return root / "services" / name


def _render_crud(tmp_path: Path, name: str = "edge-crud") -> Path:
    cfg = ProjectConfig(
        project_name="gw_demo",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name=name,
                project_name="gw_demo",
                language=BackendLanguage.PYTHON,
                app_template="crud-service",
                features=["items"],
            )
        ],
        frontend=None,
    )
    from forge.generator import generate

    root = generate(cfg, quiet=True, dry_run=True)
    return root / "services" / name


def test_two_stage_render_emits_gateway_overlay(tmp_path: Path):
    """The two-stage render emits the gateway overlay package + router."""
    svc = _render_gateway(tmp_path)
    for rel in (
        "src/app/gateway/__init__.py",
        "src/app/gateway/downstreams.py",
        "src/app/gateway/s2s_client.py",
        "src/app/api/v1/endpoints/gateway.py",
        "src/app/api/v1/api.py",
    ):
        assert (svc / rel).is_file(), f"missing overlay file: {rel}"


def test_api_py_registers_gateway_router(tmp_path: Path):
    """The overlaid api.py imports + registers the gateway router."""
    svc = _render_gateway(tmp_path)
    api_py = (svc / "src/app/api/v1/api.py").read_text(encoding="utf-8")
    assert "import admin, gateway, health, home, items" in api_py
    assert (
        'api_router.include_router(gateway.router, prefix="/gateway", tags=["gateway"])' in api_py
    )
    # entity_plural was substituted from the items feature (proves shared ctx).
    assert 'prefix="/items"' in api_py
    # The FORGE markers survive so downstream fragment injection still works.
    assert "# FORGE:API_ENDPOINT_IMPORTS" in api_py
    assert "# FORGE:API_ROUTER_REGISTRATION" in api_py


def test_base_only_file_unchanged_by_overlay(tmp_path: Path):
    """A base file the overlay does NOT own (main.py) is present and byte-
    identical to a plain crud-service render — i.e. the overlay is a true
    thin delta, not a divergent fork of the base."""
    gw = _render_gateway(tmp_path / "gw")
    crud = _render_crud(tmp_path / "crud")
    assert (gw / "src/app/main.py").is_file()
    assert (gw / "src/app/main.py").read_bytes() == (crud / "src/app/main.py").read_bytes(), (
        "overlay altered a base-owned file (main.py)"
    )


def test_rendered_gateway_python_is_parseable(tmp_path: Path):
    """AST-parse every rendered .py under src/app/gateway/ plus the rendered
    gateway endpoint + api.py — catches syntax / Jinja-leak errors."""
    svc = _render_gateway(tmp_path)
    targets = sorted((svc / "src/app/gateway").rglob("*.py"))
    targets.append(svc / "src/app/api/v1/endpoints/gateway.py")
    targets.append(svc / "src/app/api/v1/api.py")
    assert targets, "no gateway python files were rendered"
    for path in targets:
        source = path.read_text(encoding="utf-8")
        # compile() surfaces both syntax errors and un-rendered Jinja braces.
        compile(source, str(path), "exec")
        ast.parse(source)


def test_downstreams_and_s2s_module_contracts(tmp_path: Path):
    """The rendered gateway modules expose the documented public surface."""
    svc = _render_gateway(tmp_path)
    downstreams = ast.parse((svc / "src/app/gateway/downstreams.py").read_text(encoding="utf-8"))
    fn_names = {n.name for n in downstreams.body if isinstance(n, ast.FunctionDef)}
    assert {"downstream_map", "resolve_downstream"} <= fn_names

    s2s = ast.parse((svc / "src/app/gateway/s2s_client.py").read_text(encoding="utf-8"))
    class_names = {n.name for n in s2s.body if isinstance(n, ast.ClassDef)}
    assert "S2SClient" in class_names
    s2s_methods = {
        n.name
        for cls in s2s.body
        if isinstance(cls, ast.ClassDef) and cls.name == "S2SClient"
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "auth_header" in s2s_methods
