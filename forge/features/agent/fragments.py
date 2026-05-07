"""Agent loop + LLM provider port/adapters.

The agent capability stack: ``agent_streaming`` adds the WebSocket
transport (depends on ``conversation_persistence`` from
``forge.features.conversation``); ``agent_tools`` ships the tool
registry (Tavily by default); ``agent`` ties them together with the
pydantic-ai loop.

The LLM provider stack ships ``llm_port`` (abstract interface) plus
four adapters (OpenAI, Anthropic, Ollama, Bedrock), each plugging a
provider SDK in behind it. Tier-3 (Python-only) — pydantic-ai +
the LLM SDK ecosystem are Python-first.
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


# --- agent ------------------------------------------------------------------

register_fragment(
    Fragment(
        name="agent_streaming",
        depends_on=("conversation_persistence",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("agent_streaming", "python"),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="agent_tools",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("agent_tools", "python"),
                dependencies=("httpx>=0.28.0",),
                env_vars=(("TAVILY_API_KEY", ""),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="agent",
        depends_on=("agent_streaming", "agent_tools"),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("agent", "python"),
                dependencies=("pydantic-ai>=0.0.14",),
                env_vars=(
                    ("LLM_PROVIDER", "anthropic"),
                    ("LLM_MODEL", ""),
                    ("ANTHROPIC_API_KEY", ""),
                    ("OPENAI_API_KEY", ""),
                    ("GOOGLE_API_KEY", ""),
                    ("OPENROUTER_API_KEY", ""),
                    ("AGENT_SYSTEM_PROMPT", ""),
                ),
            ),
        },
    )
)


# --- llm provider port + adapters -------------------------------------------

register_fragment(
    Fragment(
        name="llm_port",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("llm_port", "python"),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="llm_openai",
        depends_on=("llm_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("llm_openai", "python"),
                dependencies=("openai>=1.54.0",),
                env_vars=(
                    ("OPENAI_API_KEY", ""),
                    ("OPENAI_BASE_URL", ""),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="llm_anthropic",
        depends_on=("llm_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("llm_anthropic", "python"),
                dependencies=("anthropic>=0.40.0",),
                env_vars=(("ANTHROPIC_API_KEY", ""),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="llm_ollama",
        depends_on=("llm_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("llm_ollama", "python"),
                dependencies=("ollama>=0.4.0",),
                env_vars=(("OLLAMA_HOST", "http://localhost:11434"),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="llm_bedrock",
        depends_on=("llm_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("llm_bedrock", "python"),
                dependencies=("aioboto3>=13.2.0",),
                env_vars=(("AWS_REGION", "us-east-1"),),
            ),
        },
    )
)
