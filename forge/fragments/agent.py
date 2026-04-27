"""Conversational AI fragments — agent loop + persistence + tools + uploads.

The agent capability stack: ``conversation_persistence`` ships the
DB-backed history, ``agent_streaming`` adds the WebSocket transport,
``agent_tools`` the tool registry (Tavily by default), and ``agent``
ties them together with the pydantic-ai loop. ``file_upload`` shares
``conversation_persistence`` so attached files associate with their
conversation thread.

All five are tier-3 (Python-only) by auto-derivation — pydantic-ai +
the LLM SDK ecosystem don't have peer Node/Rust ports today.
"""

from __future__ import annotations

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

register_fragment(
    Fragment(
        name="conversation_persistence",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="conversation_persistence/python"
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="agent_streaming",
        depends_on=("conversation_persistence",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="agent_streaming/python"),
        },
    )
)


register_fragment(
    Fragment(
        name="agent_tools",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="agent_tools/python",
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
                fragment_dir="agent/python",
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


register_fragment(
    Fragment(
        name="file_upload",
        depends_on=("conversation_persistence",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="file_upload/python",
                dependencies=("python-multipart>=0.0.20",),
                env_vars=(
                    ("UPLOAD_DIR", "./uploads"),
                    ("MAX_UPLOAD_SIZE", "10485760"),
                    ("ALLOWED_MIME_TYPES", ""),
                ),
            ),
        },
    )
)
