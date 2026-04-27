"""LLM provider port + adapters (1.0.0a2+).

``llm_port`` defines the abstract LLM interface; the four adapters
(``llm_openai``, ``llm_anthropic``, ``llm_ollama``, ``llm_bedrock``)
plug their respective SDKs in behind it. Tier-3 (Python-only) — the
Anthropic/OpenAI/Bedrock SDK ecosystem is Python-first.
"""

from __future__ import annotations

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

register_fragment(
    Fragment(
        name="llm_port",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="llm_port/python",
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
                fragment_dir="llm_openai/python",
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
                fragment_dir="llm_anthropic/python",
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
                fragment_dir="llm_ollama/python",
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
                fragment_dir="llm_bedrock/python",
                dependencies=("aioboto3>=13.2.0",),
                env_vars=(("AWS_REGION", "us-east-1"),),
            ),
        },
    )
)
