"""Backend language registry — built-in enum + plugin sentinels + per-language spec.

Each :class:`BackendSpec` registered in :data:`BACKEND_REGISTRY` ties a
backend language to its Copier template, its post-generate
:class:`~forge.toolchains.BackendToolchain`, and its CLI prompt
metadata. Plugins extend the registry via
:func:`~forge.api.ForgeAPI.add_backend`, which delegates to
:func:`register_backend_language` here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from forge.config._validators import validate_features, validate_port


class BackendLanguage(Enum):
    PYTHON = "python"
    NODE = "node"
    RUST = "rust"


# Plugin-registered backend language values. Keyed by the wire value
# (``"go"``, ``"java"``), value is a sentinel object (_PluginLanguage)
# that mimics a BackendLanguage member well enough for the generator
# dispatch + fragment lookup. Look up via ``resolve_backend_language``.
PLUGIN_LANGUAGES: dict[str, _PluginLanguage] = {}


class _PluginLanguage:
    """Synthetic BackendLanguage member for plugin-registered languages.

    Behaves like a frozen enum member: has ``.value``, ``.name``, and
    hashes consistently so it works as a dict key in BACKEND_REGISTRY.
    The Python enum machinery refuses to return non-Enum values from
    ``_missing_``, so we expose a separate resolution function instead
    of pretending this is a real member.
    """

    __slots__ = ("value", "name")

    def __init__(self, value: str) -> None:
        self.value = value
        self.name = value.upper()

    def __repr__(self) -> str:
        return f"<BackendLanguage.{self.name} (plugin)>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _PluginLanguage):
            return self.value == other.value
        if isinstance(other, BackendLanguage):
            return self.value == other.value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(("BackendLanguage", self.value))


def register_backend_language(value: str) -> _PluginLanguage:
    """Register a plugin language value. Returns the sentinel member."""
    if value not in PLUGIN_LANGUAGES:
        PLUGIN_LANGUAGES[value] = _PluginLanguage(value)
    return PLUGIN_LANGUAGES[value]


def resolve_backend_language(value: str) -> BackendLanguage | _PluginLanguage:
    """Look up a language by string value. Checks built-in enum first,
    then plugin-registered sentinels. Raises ValueError if neither
    matches — callers treat that as "unknown language".

    Used by fragment/generator code that deals with language strings
    from YAML configs or plugin metadata.
    """
    for member in BackendLanguage:
        if member.value == value:
            return member
    if value in PLUGIN_LANGUAGES:
        return PLUGIN_LANGUAGES[value]
    raise ValueError(f"Unknown backend language: {value!r}")


def _default_toolchain_factory() -> Any:
    """Lazy import to break the config → toolchains cycle.

    ``forge.toolchains`` depends only on ``forge.errors``, not ``forge.config``,
    so this factory runs at ``BackendSpec(...)`` instantiation time (well
    after import) without creating an import cycle.
    """
    from forge.toolchains import NOOP_TOOLCHAIN  # noqa: PLC0415

    return NOOP_TOOLCHAIN


@dataclass(frozen=True)
class BackendSpec:
    """Static metadata for a backend language: template, prompts, version field.

    Adding a 4th backend means adding one entry here plus one Copier template
    directory under `forge/templates/services/`. The CLI prompt loop, generator
    dispatch, and variable-mapper context builder all read from this registry.

    ``toolchain`` carries the per-language install / verify / post-generate
    hooks previously hardcoded in ``generator.py``'s language dispatch.
    Plugin-registered backends attach their own implementation — see
    ``forge.toolchains.BackendToolchain`` Protocol. Typed as ``Any`` to keep
    ``forge.config`` free of the ``forge.toolchains`` import (the factory
    resolves it lazily).
    """

    template_dir: str  # path under forge/templates/, e.g. "services/python-service-template"
    display_label: str  # shown in CLI prompts and log messages
    version_field: str  # name of the BackendConfig attribute holding the version
    version_choices: tuple[str, ...]  # interactive prompt choices, first is default
    toolchain: Any = field(default_factory=_default_toolchain_factory)


def _python_toolchain_factory() -> Any:
    from forge.toolchains.python import PYTHON_TOOLCHAIN  # noqa: PLC0415

    return PYTHON_TOOLCHAIN


def _node_toolchain_factory() -> Any:
    from forge.toolchains.node import NODE_TOOLCHAIN  # noqa: PLC0415

    return NODE_TOOLCHAIN


def _rust_toolchain_factory() -> Any:
    from forge.toolchains.rust import RUST_TOOLCHAIN  # noqa: PLC0415

    return RUST_TOOLCHAIN


# BACKEND_REGISTRY keys are either real ``BackendLanguage`` members or
# ``_PluginLanguage`` sentinels — both share the ``.value`` attribute so
# downstream code can treat them uniformly.
BACKEND_REGISTRY: dict[BackendLanguage | _PluginLanguage, BackendSpec] = {
    BackendLanguage.PYTHON: BackendSpec(
        template_dir="services/python-service-template",
        display_label="Python (FastAPI)",
        version_field="python_version",
        version_choices=("3.13", "3.12", "3.11"),
        toolchain=_python_toolchain_factory(),
    ),
    BackendLanguage.NODE: BackendSpec(
        template_dir="services/node-service-template",
        display_label="Node.js (Fastify)",
        version_field="node_version",
        version_choices=("22", "20", "18"),
        toolchain=_node_toolchain_factory(),
    ),
    BackendLanguage.RUST: BackendSpec(
        template_dir="services/rust-service-template",
        display_label="Rust (Axum)",
        version_field="rust_edition",
        version_choices=("2024", "2021"),
        toolchain=_rust_toolchain_factory(),
    ),
}


@dataclass
class BackendConfig:
    """Backend service configuration."""

    name: str = "backend"
    project_name: str = ""
    language: BackendLanguage = BackendLanguage.PYTHON
    description: str = "A microservice"
    features: list[str] = field(default_factory=lambda: ["items"])
    python_version: str = "3.13"
    node_version: str = "22"
    rust_edition: str = "2024"
    server_port: int = 5000

    def validate(self) -> None:
        validate_port(self.server_port, f"Backend '{self.name}' port")
        if not re.match(r"^[a-z][a-z0-9_-]*$", self.name):
            raise ValueError(f"Backend name '{self.name}' must be lowercase kebab/snake case.")
        if self.features:
            validate_features(self.features)
