"""Streaming fragments — SSE fanout of CloudEvents to browser subscribers."""

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
        name="streaming_sse",
        depends_on=("events_core",),
        capabilities=("postgres",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("streaming_sse", "python"),
                dependencies=("weld-streaming", "sse-starlette>=2.1.0"),
                env_vars=(
                    ("STREAMING_HEARTBEAT_S", "15"),
                    ("STREAMING_QUEUE_MAX", "1024"),
                ),
            ),
        },
    )
)
