"""Shared library fragment — project-scoped Python SDK scaffold.

Registers ``shared_lib_python`` as a project-scoped fragment that drops
a shared Python package at ``<project>/packages/shared/``. The package
provides a ``shared`` importable namespace with Pydantic domain models
and a utilities directory for cross-backend code reuse.

Fragment template tree ships from this package using absolute paths via
``Path(__file__).resolve().parent / "templates"`` — the same convention
the other built-in feature namespaces and third-party plugins use.
"""

from __future__ import annotations

from pathlib import Path

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


def register_all(api: ForgeAPI) -> None:
    # Project-scoped: the shared SDK lives at ``<project>/packages/shared/`` and
    # is referenced by every Python backend's pyproject.toml as a path
    # dependency. Only registers ``BackendLanguage.PYTHON`` so the
    # parity_tier auto-derives to 3 (python-only).
    api.add_fragment(
        Fragment(
            name="shared_lib_python",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("shared_lib_python", "all"),
                    scope="project",
                ),
            },
        )
    )
