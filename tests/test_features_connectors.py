"""Invariants for ``forge.features.connectors`` — weld-connectors registry."""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY
from forge.options import OPTION_REGISTRY


def test_connectors_enabled_option_registered() -> None:
    assert "connectors.enabled" in OPTION_REGISTRY
    opt = OPTION_REGISTRY["connectors.enabled"]
    assert opt.default is False
    assert opt.enables[True] == ("connectors_registry",)


def test_connectors_backends_option_is_list_type() -> None:
    """connectors.backends is the first LIST-typed option in the registry.

    The capability resolver was patched alongside this option to
    short-circuit `spec.enables.get(value, ())` when `spec.enables` is
    empty — without that fix, dict.get on the unhashable list value
    would raise TypeError during plan resolution.
    """
    from forge.options._registry import OptionType

    assert "connectors.backends" in OPTION_REGISTRY
    opt = OPTION_REGISTRY["connectors.backends"]
    assert opt.type is OptionType.LIST
    assert opt.default == []
    # LIST options validate forbids enables — keep it empty.
    assert opt.enables == {}


def test_connectors_registry_fragment_reads_backends_option() -> None:
    assert "connectors_registry" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["connectors_registry"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    assert "connectors.backends" in impl.reads_options
    assert frag.parity_tier == 3


def test_connectors_fragment_has_no_weld_dep() -> None:
    """P5 Stage 2c — the connector framework is vendored; no private SDK dep.

    The vendored source uses only pydantic + httpx + sqlalchemy from the
    base template, so the fragment declares zero extra dependencies (boto3
    / asyncpg are optional, import-guarded at runtime).
    """
    impl = FRAGMENT_REGISTRY["connectors_registry"].implementations[BackendLanguage.PYTHON]
    assert not any("weld" in dep for dep in impl.dependencies), (
        f"connectors_registry still declares a weld dependency: {impl.dependencies}"
    )


def test_connectors_fragment_ships_no_weld_imports() -> None:
    """The vendored connector source never imports ``weld``."""
    files_root = (
        Path(FRAGMENT_REGISTRY["connectors_registry"].implementations[BackendLanguage.PYTHON].fragment_dir)
        / "files"
    )
    for src in list(files_root.rglob("*.py")) + list(files_root.rglob("*.py.jinja")):
        for line in src.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            assert not stripped.startswith(("import weld", "from weld")), (
                f"weld import in vendored connectors source: {src}: {stripped}"
            )


def test_connectors_registry_scaffolds_app_connectors_tree() -> None:
    frag = FRAGMENT_REGISTRY["connectors_registry"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    files_root = Path(impl.fragment_dir) / "files"
    app_connectors = files_root / "src" / "app" / "connectors"
    assert (app_connectors / "__init__.py").is_file()
    # Vendored, weld-free framework modules.
    assert (app_connectors / "base.py").is_file()
    assert (app_connectors / "registry.py").is_file()
    assert (app_connectors / "runner.py").is_file()
    # The MCPConnector is intentionally NOT vendored (gatekeeper-coupled).
    builtin = app_connectors / "builtin"
    for name in ("http.py", "fs.py", "sample.py", "s3.py", "sql.py"):
        assert (builtin / name).is_file()
    assert not (builtin / "mcp.py").is_file()
    # _service.py.jinja holds the render-time backend selection (the body
    # has `{%- for %}` blocks that resolve only at render time).
    assert (app_connectors / "_service.py.jinja").is_file()
