"""Connectors fragment — registers a per-service ConnectorRegistry.

The fragment reads ``connectors.backends`` at render time and emits a
``weld-connectors[<bk>,<bk>,...]`` dep so unused extras stay out of the
generated service. Backend selection lives in the generated
``connectors.py`` and can be edited post-generate.
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


register_fragment(
    Fragment(
        name="connectors_registry",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("connectors_registry", "python"),
                dependencies=("weld-connectors",),
                reads_options=("connectors.backends",),
            ),
        },
    )
)
