"""``agent.*`` and ``llm.*`` — LLM agent platform.

Streaming WebSocket, tool registry, pydantic-ai loop, plus the layer
discriminator (``agent.mode``) and the provider selector
(``llm.provider``). Conversational AI is the umbrella category for both.
"""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="agent.streaming",
        type=OptionType.BOOL,
        default=False,
        summary="/ws/agent with typed event protocol + runner dispatch.",
        description="""\
A WebSocket endpoint at /api/v1/ws/agent that streams typed AgentEvent
JSON frames (conversation_created, user_prompt, text_delta, tool_call,
tool_result, agent_status, error). Ships with an echo runner and a
runner-dispatch module that prefers ``app.agents.llm_runner`` if
present — enabling ``agent.llm`` swaps in a real LLM loop with zero
endpoint churn.

BACKENDS: python
ENDPOINTS: /api/v1/ws/agent (WebSocket)
REQUIRES: conversation.persistence = true.""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        stability="experimental",
        # Initiative #7 — depends transitively on conversation.persistence
        # (records the streamed conversation), which writes to the DB.
        requires_database=True,
        enables={True: ("agent_streaming",)},
    )
)


register_option(
    Option(
        path="agent.tools",
        type=OptionType.BOOL,
        default=False,
        summary="Tool registry + pre-baked `current_datetime`, `web_search`.",
        description="""\
A lightweight Tool base class, a process-wide registry, and two
pre-baked tools (current_datetime, web_search via Tavily). When
rag.backend ≠ none it auto-registers rag_search too. Exposes a
/api/v1/tools list + invoke endpoint so humans can exercise tools
without an LLM loop attached.

BACKENDS: python
ENDPOINTS: /api/v1/tools (GET list, POST invoke)
REQUIRES: TAVILY_API_KEY for the web_search tool (optional).""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        stability="experimental",
        enables={True: ("agent_tools",)},
    )
)


register_option(
    Option(
        path="agent.llm",
        type=OptionType.BOOL,
        default=False,
        summary="pydantic-ai loop -- Anthropic / OpenAI / Google / OpenRouter.",
        description="""\
A pydantic-ai LLM loop that swaps in for the echo runner shipped by
agent.streaming — no endpoint or WebSocket-contract change needed.
Auto-picks the provider from LLM_PROVIDER (anthropic / openai / google
/ openrouter). Every tool registered in the ToolRegistry is bridged
into pydantic-ai automatically.

BACKENDS: python
REQUIRES: one of ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY /
OPENROUTER_API_KEY; agent.streaming = true; agent.tools = true.""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        stability="experimental",
        # Initiative #7 — depends transitively on agent.streaming +
        # conversation.persistence, both of which write to the DB.
        requires_database=True,
        enables={True: ("agent",)},
    )
)


register_option(
    Option(
        path="llm.provider",
        type=OptionType.ENUM,
        default="none",
        options=("none", "openai", "anthropic", "ollama", "bedrock"),
        summary="LLM provider for the agent loop (OpenAI, Anthropic, Ollama, or AWS Bedrock).",
        description="""\
Selects which LLM provider the generated service talks to via the
``LlmPort`` (see ``docs/architecture-decisions/ADR-002-ports-and-adapters.md``
and the TypeSpec contract at ``forge/templates/_shared/ports/llm/contract.tsp``).
The chosen adapter registers with the dependency container; the rest
of the app imports the port interface. Swap providers in production
by changing one env var — no regeneration.

OPTIONS: none | openai | anthropic | ollama | bedrock
BACKENDS:
  - openai     python, node, rust    (Pillar D.2 — tier-1, three built-ins)
  - anthropic  python                (Python-only — Anthropic SDK ecosystem)
  - ollama     python                (Python-only — ollama-python is the canonical client)
  - bedrock    python                (Python-only — aioboto3)

Non-Python backends selecting ``anthropic`` / ``ollama`` / ``bedrock``
resolve the abstract ``llm_port`` only; the adapter fragment is
Python-only and silently skips on Node/Rust. Plugin authors fill the
gap (Featured Plugin tier — see ``docs/known-issues.md``).

DEPENDENCY: provider-specific SDK (openai / @ai-sdk/openai / async-openai
            / anthropic / ollama / aioboto3)
ENV: provider-specific API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        enables={
            "openai": ("llm_port", "llm_openai"),
            "anthropic": ("llm_port", "llm_anthropic"),
            "ollama": ("llm_port", "llm_ollama"),
            "bedrock": ("llm_port", "llm_bedrock"),
        },
    )
)


# Theme 2A — ``agent.mode`` (the layer discriminator) now lives in
# ``forge/options/agent/__init__.py`` alongside the other layer-mode
# registrations. The fragment bundle per enum value is defined there;
# this module keeps the fine-grained ``agent.streaming`` / ``agent.tools``
# / ``agent.llm`` toggles + the ``llm.provider`` adapter selector.
