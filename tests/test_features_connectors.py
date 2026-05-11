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
    assert "weld-connectors" in impl.dependencies
    assert frag.parity_tier == 3


def test_connectors_registry_scaffolds_app_connectors_tree() -> None:
    frag = FRAGMENT_REGISTRY["connectors_registry"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    files_root = Path(impl.fragment_dir) / "files"
    assert (files_root / "src" / "app" / "connectors" / "__init__.py").is_file()
    # registry.py.jinja (not .py) because the body has `{%- for %}` blocks
    # that resolve only at render time; ruff would refuse to parse the raw
    # template if it had a .py extension.
    assert (files_root / "src" / "app" / "connectors" / "registry.py.jinja").is_file()
