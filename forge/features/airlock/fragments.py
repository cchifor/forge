"""Airlock fragments — async sandbox-orchestrator client wiring."""

from __future__ import annotations

from pathlib import Path

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


def register_all(api: ForgeAPI) -> None:
    api.add_fragment(
        Fragment(
            name="airlock_client",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("airlock_client", "python"),
                    # No extra deps: the vendored async client needs only
                    # httpx + pydantic, both base-template dependencies.
                    env_vars=(
                        ("AIRLOCK_BASE_URL", "http://airlock:5100"),
                        ("AIRLOCK_TOKEN", ""),
                    ),
                ),
            },
        )
    )
